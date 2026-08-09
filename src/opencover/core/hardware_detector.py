from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict


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


def detect_hardware(local_ffmpeg: str | None = None) -> HardwareInfo:
    gpu = vram = driver = cuda = None
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
        except (OSError, ValueError, subprocess.SubprocessError, IndexError):
            pass
    try:
        ram_gb = round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024**3, 1)
    except (AttributeError, ValueError, OSError):
        ram_gb = None
    ffmpeg = local_ffmpeg if local_ffmpeg and os.path.exists(local_ffmpeg) else shutil.which("ffmpeg")
    return HardwareInfo(
        os_name=platform.platform(), cpu=platform.processor() or "未知", ram_gb=ram_gb,
        gpu=gpu, vram_gb=vram, driver=driver, cuda_reported=cuda,
        ffmpeg=ffmpeg, memory_profile=_memory_profile(vram),
    )
