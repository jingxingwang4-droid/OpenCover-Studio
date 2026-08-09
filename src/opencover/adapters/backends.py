from __future__ import annotations

import json
from pathlib import Path

from .base import BackendStatus, BackendUnavailable, run_checked


class RVCAdapter:
    backend_id = "rvc"

    def __init__(self, root: Path):
        self.root = root

    def status(self) -> BackendStatus:
        exe = self.root / "python.exe"
        marker = self.root / "backend.json"
        installed = exe.is_file() and marker.is_file()
        return BackendStatus("rvc", "RVC", installed, installed, self._version(marker),
                             "独立 CLI 环境" if installed else "未安装官方 RVC CLI 环境")

    @staticmethod
    def _version(marker: Path) -> str:
        try:
            return json.loads(marker.read_text(encoding="utf-8")).get("commit", "未锁定")
        except (OSError, ValueError):
            return "未安装"

    def convert(self, input_audio: Path, output_audio: Path, model: Path, pitch: int, index: Path | None = None) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        args = [str(self.root / "python.exe"), "-m", "rvc", "infer", "-m", str(model),
                "-i", str(input_audio), "-o", str(output_audio), "-fu", str(pitch)]
        run_checked(args, self.root)
        if not output_audio.is_file() or output_audio.stat().st_size < 1024:
            raise RuntimeError("RVC 没有生成有效输出")
        return output_audio


class DDSPAdapter:
    backend_id = "ddsp"

    def __init__(self, root: Path):
        self.root = root

    def status(self) -> BackendStatus:
        exe, script = self.root / "python.exe", self.root / "DDSP-SVC" / "main_reflow.py"
        installed = exe.is_file() and script.is_file()
        return BackendStatus("ddsp", "DDSP-SVC", installed, installed, "5.x/待验证" if installed else "未安装",
                             "main_reflow.py" if installed else "未安装官方 DDSP-SVC 环境")

    def convert(self, input_audio: Path, output_audio: Path, model: Path, pitch: int, config: Path | None = None) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        args = [str(self.root / "python.exe"), "main_reflow.py", "-i", str(input_audio), "-m", str(model),
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
        exe, script = self.root / "python.exe", self.root / "Music-Source-Separation-Training" / "inference.py"
        installed = exe.is_file() and script.is_file()
        return BackendStatus("msst", "MSST", installed, installed, "待验证" if installed else "未安装",
                             "inference.py" if installed else "未安装 MSST 代码、环境和分离模型")

    def separate(self, input_dir: Path, output_dir: Path, model_type: str, config: Path, checkpoint: Path) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        args = [str(self.root / "python.exe"), "inference.py", "--model_type", model_type,
                "--config_path", str(config), "--start_check_point", str(checkpoint),
                "--input_folder", str(input_dir), "--store_dir", str(output_dir)]
        run_checked(args, self.root / "Music-Source-Separation-Training")
        wavs = list(output_dir.rglob("*.wav"))
        if not wavs:
            raise RuntimeError("MSST 没有生成分轨")
        return output_dir
