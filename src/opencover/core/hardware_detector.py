from __future__ import annotations

import os
import json
import ctypes
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass(frozen=True)
class HardwareInfo:
    os_name: str
    cpu: str
    ram_gb: float | None
    gpu: str | None
    vram_gb: float | None
    driver: str | None
    cuda_reported: str | None
    ffmpeg: str | None
    memory_profile: str
    compute_capability: str | None = None
    fp16_supported: bool | None = None
    cuda_smoke: bool = False
    disk_free_gb: float | None = None

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _memory_profile(vram: float | None) -> str:
    if vram is None or vram < 4:
        return "极低"
    if vram < 6:
        return "低"
    if vram <= 10:
        return "标准"
    return "高质量"


def detect_hardware(local_ffmpeg: str | None = None, torch_python: str | None = None, workspace: str | None = None) -> HardwareInfo:
    gpu = vram = driver = cuda = compute = None
    smi = shutil.which("nvidia-smi")
    if smi:
        try:
            query = subprocess.run(
                [smi, "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                check=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.strip().splitlines()[0]
            parts = [part.strip() for part in query.split(",")]
            gpu, vram_mb, driver = parts[:3]
            vram = round(float(vram_mb) / 1024, 1)
            banner = subprocess.run(
                [smi], capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout
            match = re.search(r"CUDA Version:\s*([\d.]+)", banner)
            cuda = match.group(1) if match else None
            try:
                compute = subprocess.run(
                    [smi, "--query-gpu=compute_cap", "--format=csv,noheader"], capture_output=True,
                    text=True, timeout=8, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ).stdout.strip().splitlines()[0]
            except (OSError, subprocess.SubprocessError, IndexError):
                compute = None
        except (OSError, ValueError, subprocess.SubprocessError, IndexError):
            pass
    try:
        if os.name == "nt":
            class MemoryStatus(ctypes.Structure):
                _fields_ = [
                    ("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                    ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                    ("total_page_file", ctypes.c_ulonglong), ("avail_page_file", ctypes.c_ulonglong),
                    ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                    ("avail_extended_virtual", ctypes.c_ulonglong),
                ]
            memory = MemoryStatus(); memory.length = ctypes.sizeof(memory)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
                raise OSError("GlobalMemoryStatusEx failed")
            ram_gb = round(memory.total_phys / 1024**3, 1)
        else:
            ram_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
    except (AttributeError, ValueError, OSError):
        ram_gb = None
    ffmpeg = local_ffmpeg if local_ffmpeg and os.path.exists(local_ffmpeg) else shutil.which("ffmpeg")
    cuda_smoke = False
    fp16: bool | None = None
    if torch_python and Path(torch_python).is_file():
        smoke_code = (
            "import json,torch; ok=torch.cuda.is_available(); cap=torch.cuda.get_device_capability(0) if ok else None; "
            "x=torch.tensor([1.,2.],device='cuda',dtype=torch.float16) if ok else None; "
            "valid=bool(ok and float((x*x).sum().item())==5.0); print(json.dumps({'ok':valid,'cap':cap,'fp16':valid}))"
        )
        try:
            smoke = subprocess.run(
                [torch_python, "-c", smoke_code], capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=30, check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            result = json.loads(smoke.stdout.strip().splitlines()[-1])
            cuda_smoke = result.get("ok") is True
            fp16 = result.get("fp16") is True
            if not compute and result.get("cap"):
                compute = ".".join(map(str, result["cap"]))
        except (OSError, ValueError, subprocess.SubprocessError, IndexError):
            pass
    try:
        free = round(shutil.disk_usage(workspace or os.getcwd()).free / 1024**3, 1)
    except OSError:
        free = None
    return HardwareInfo(
        os_name=platform.platform(), cpu=platform.processor() or "未知", ram_gb=ram_gb,
        gpu=gpu, vram_gb=vram, driver=driver, cuda_reported=cuda,
        ffmpeg=ffmpeg, memory_profile=_memory_profile(vram), compute_capability=compute,
        fp16_supported=fp16, cuda_smoke=cuda_smoke, disk_free_gb=free,
    )
