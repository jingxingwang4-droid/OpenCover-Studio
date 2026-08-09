from __future__ import annotations

import json
from pathlib import Path

from .base import BackendStatus, BackendUnavailable, run_checked


def _runtime_python(root: Path) -> Path:
    candidates = [root / "python.exe", root / "runtime" / "Scripts" / "python.exe"]
    return next((path for path in candidates if path.is_file()), candidates[-1])


def _marker(root: Path) -> dict[str, object]:
    try:
        return json.loads((root / "backend.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class RVCAdapter:
    backend_id = "rvc"

    def __init__(self, root: Path):
        self.root = root

    def status(self) -> BackendStatus:
        exe = _runtime_python(self.root)
        metadata = _marker(self.root)
        installed = exe.is_file() and (self.root / "source").is_dir()
        runnable = installed and metadata.get("smoke_test_passed") is True
        detail = "独立 CLI 环境已通过 smoke test" if runnable else ("环境存在但尚未通过真实推理 smoke test" if installed else "未安装官方 RVC CLI 环境")
        return BackendStatus("rvc", "RVC", installed, runnable, str(metadata.get("commit", "未验证")), detail)

    def convert(self, input_audio: Path, output_audio: Path, model: Path, pitch: int, index: Path | None = None) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        args = [str(_runtime_python(self.root)), "-m", "rvc.wrapper.cli.cli", "infer", "-m", str(model),
                "-i", str(input_audio), "-o", str(output_audio), "-fu", str(pitch),
                "-fm", "rmvpe", "-ir", "0.75" if index else "0"]
        if index:
            args += ["-if", str(index)]
        output_audio.parent.mkdir(parents=True, exist_ok=True)
        run_checked(args, self.root)
        if not output_audio.is_file() or output_audio.stat().st_size < 1024:
            raise RuntimeError("RVC 没有生成有效输出")
        return output_audio


class DDSPAdapter:
    backend_id = "ddsp"

    def __init__(self, root: Path):
        self.root = root

    def status(self) -> BackendStatus:
        exe, script = _runtime_python(self.root), self.root / "DDSP-SVC" / "main_reflow.py"
        installed = exe.is_file() and script.is_file()
        metadata = _marker(self.root)
        runnable = installed and metadata.get("smoke_test_passed") is True
        detail = "main_reflow.py 已通过真实推理" if runnable else ("环境存在但尚未通过真实推理 smoke test" if installed else "未安装官方 DDSP-SVC 环境")
        return BackendStatus("ddsp", "DDSP-SVC", installed, runnable, str(metadata.get("commit", "未验证")), detail)

    def convert(self, input_audio: Path, output_audio: Path, model: Path, pitch: int, config: Path | None = None) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        args = [str(_runtime_python(self.root)), "main_reflow.py", "-i", str(input_audio), "-m", str(model),
                "-o", str(output_audio), "-k", str(pitch), "-id", "1"]
        run_checked(args, self.root / "DDSP-SVC")
        if not output_audio.is_file() or output_audio.stat().st_size < 1024:
            raise RuntimeError("DDSP-SVC 没有生成有效输出")
        return output_audio


class MSSTAdapter:
    backend_id = "msst"

    def __init__(self, root: Path):
        self.root = root

    def status(self) -> BackendStatus:
        exe, script = _runtime_python(self.root), self.root / "Music-Source-Separation-Training" / "inference.py"
        installed = exe.is_file() and script.is_file()
        metadata = _marker(self.root)
        runnable = installed and metadata.get("smoke_test_passed") is True
        detail = "MDX23C 已通过真实分离" if runnable else ("源码/环境存在但尚未通过真实分离 smoke test" if installed else "未安装 MSST 代码、环境和分离模型")
        return BackendStatus("msst", "MSST", installed, runnable, str(metadata.get("commit", "未验证")), detail)

    def separate(self, input_dir: Path, output_dir: Path, model_type: str, config: Path, checkpoint: Path) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        args = [str(_runtime_python(self.root)), "inference.py", "--model_type", model_type,
                "--config_path", str(config), "--start_check_point", str(checkpoint),
                "--input_folder", str(input_dir), "--store_dir", str(output_dir),
                "--device_ids", "0", "--disable_detailed_pbar"]
        run_checked(args, self.root / "Music-Source-Separation-Training")
        wavs = list(output_dir.rglob("*.wav"))
        if not wavs:
            raise RuntimeError("MSST 没有生成分轨")
        return output_dir
