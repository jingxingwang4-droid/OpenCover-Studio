"""Install the pinned training source and verified base weights inside the project.

Run using the GUI Python after the normal RVC inference component is installed.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import requests

COMMIT = "7ef19867780cf703841ebafb565a4e47d1ea86ff"
WEIGHTS = {
    "f0G40k.pth": "3b2c44035e782c4b14ddc0bede9e2f4a724d025cd073f736d4f43708453adfcb",
    "f0D40k.pth": "6b6ab091e70801b28e3f41f335f2fc5f3f35c75b39ae2628d419644ec2b0fa09",
}


def main():
    root = Path(__file__).resolve().parents[1]
    backend = root / "external_backends/rvc_training"
    source = backend / "source"
    runtime = root / "external_backends/rvc/runtime/Scripts/python.exe"
    if not runtime.is_file(): runtime = root / "external_backends/rvc/runtime/python.exe"
    if not runtime.is_file(): raise RuntimeError("请先安装 RVC 推理组件")
    temp = root / "workspace/tmp/training_setup"; temp.mkdir(parents=True, exist_ok=True)
    os.environ.update(TEMP=str(temp), TMP=str(temp), UV_CACHE_DIR=str(root / "workspace/cache/uv"))
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7897")
    if not source.exists():
        subprocess.run(["git", "clone", "--no-checkout", "--filter=blob:none", "https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI.git", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", COMMIT], check=True)
    actual = subprocess.check_output(["git", "-c", f"safe.directory={source.as_posix()}", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != COMMIT: raise RuntimeError("已有训练源码版本不符，请先备份并检查；安装器不会覆盖已有源码")
    weights = backend / "pretrained"; weights.mkdir(parents=True, exist_ok=True)
    for name, digest in WEIGHTS.items():
        target = weights / name
        if target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest: raise RuntimeError(f"已有权重校验失败：{name}")
            continue
        part = target.with_suffix(".download")
        try:
            with requests.get("https://huggingface.co/lj1995/VoiceConversionWebUI/resolve/main/pretrained_v2/" + name, stream=True, timeout=60) as response:
                response.raise_for_status()
                with part.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024): output.write(chunk)
            if hashlib.sha256(part.read_bytes()).hexdigest() != digest: raise RuntimeError(f"下载校验失败：{name}")
            part.rename(target)
        finally:
            part.unlink(missing_ok=True)
    uv = shutil.which("uv")
    if not uv: raise RuntimeError("安装训练依赖需要 uv")
    subprocess.run([uv, "pip", "install", "--python", str(runtime), "tensorboard==2.21.0", "ffmpeg-python==0.2.0", "matplotlib==3.9.4"], check=True)
    subprocess.run([str(runtime), "-c", "import torch, tensorboard, ffmpeg, matplotlib, fairseq, parselmouth, pyworld, faiss; assert torch.cuda.is_available(); print(torch.cuda.get_device_name(0))"], check=True)
    (backend / "backend.json").write_text(json.dumps({"source": "RVC-Project/Retrieval-based-Voice-Conversion-WebUI", "commit": COMMIT, "weights": WEIGHTS, "version": "v2-40k", "runtime": "../rvc/runtime"}, indent=2), encoding="utf-8")
    print("RVC_TRAINING_READY")


if __name__ == "__main__": main()
