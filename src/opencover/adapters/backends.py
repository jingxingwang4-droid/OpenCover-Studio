from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
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


def _faiss_safe_index(index: Path) -> Path:
    """Return an ASCII-only cached path for FAISS on Windows when needed."""
    resolved = index.resolve()
    try:
        str(resolved).encode("ascii")
        return resolved
    except UnicodeEncodeError:
        pass
    digest_builder = hashlib.sha256()
    with resolved.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest_builder.update(block)
    digest = digest_builder.hexdigest()
    cache_dir = Path(tempfile.gettempdir()) / "OpenCoverStudio" / "faiss"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_dir / f"{digest}.index"
    if not cached.is_file() or cached.stat().st_size != resolved.stat().st_size:
        partial = cached.with_suffix(".index.part")
        shutil.copy2(resolved, partial)
        partial.replace(cached)
    return cached


class MarkerBackendAdapter:
    """Expose audited optional-backend state without importing heavy runtimes."""

    def __init__(self, root: Path, backend_id: str, name: str):
        self.root = root
        self.backend_id = backend_id
        self.name = name

    def status(self) -> BackendStatus:
        metadata = _marker(self.root)
        installed = self.root.is_dir() and bool(metadata or any(self.root.iterdir()))
        runnable = installed and metadata.get("smoke_test_passed") is True
        if runnable:
            detail = str(metadata.get("detail", "已通过真实推理 smoke test"))
        elif installed:
            detail = str(metadata.get("detail", "源码存在，但模型或真实推理尚未通过"))
        else:
            detail = "未安装"
        return BackendStatus(
            self.backend_id, self.name, installed, runnable,
            str(metadata.get("commit", metadata.get("version", "未验证"))), detail,
        )


class Vevo2Adapter:
    backend_id = "vevo2"

    def __init__(self, root: Path):
        self.root = root

    def status(self) -> BackendStatus:
        metadata = _marker(self.root)
        runtime = _runtime_python(self.root)
        source = self.root / "Amphion" / "models" / "svc" / "vevo2" / "vevo2_utils.py"
        model = self.root / "models" / "Vevo2"
        required = [
            model / "tokenizer" / "prosody_fvq512_6.25hz" / "model.safetensors",
            model / "tokenizer" / "contentstyle_fvq16384_12.5hz" / "model.safetensors",
            model / "contentstyle_modeling" / "posttrained" / "model.safetensors",
            model / "acoustic_modeling" / "fm_emilia101k_singnet7k_repa" / "model.safetensors",
            model / "vocoder" / "model.safetensors",
        ]
        installed = runtime.is_file() and source.is_file()
        runnable = installed and all(path.is_file() for path in required) and metadata.get("smoke_test_passed") is True
        if runnable:
            detail = str(metadata.get("detail", "中文/日文真实推理已通过"))
        elif installed:
            missing = sum(not path.is_file() for path in required)
            detail = f"环境存在，但缺少 {missing} 个必要权重或真实推理未通过"
        else:
            detail = "未安装 Vevo2 独立环境、源码和权重"
        return BackendStatus("vevo2", "Vevo2", installed, runnable, str(metadata.get("commit", "未验证")), detail)

    def generate_batch(self, request_file: Path, runner: Path) -> None:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        if not runner.is_file():
            raise BackendUnavailable("Vevo2 运行脚本缺失")
        run_checked([str(_runtime_python(self.root)), str(runner), str(request_file)], self.root, timeout=7200)


class GameAdapter:
    backend_id = "game"

    def __init__(self, root: Path):
        self.root = root

    def _python(self) -> Path:
        return self.root.parent / "ddsp" / "runtime" / "Scripts" / "python.exe"

    def _model(self) -> Path:
        return self.root / "models" / "GAME-1.0-small" / "GAME-1.0-small" / "model.pt"

    def status(self) -> BackendStatus:
        metadata = _marker(self.root)
        source = self.root / "GAME" / "infer.py"
        installed = self._python().is_file() and source.is_file() and self._model().is_file()
        runnable = installed and metadata.get("smoke_test_passed") is True
        detail = "GAME small 已通过真实 MIDI/文本提取" if runnable else (
            "文件存在但尚未通过真实提取" if installed else "缺少 GAME 源码、模型或兼容 runtime"
        )
        return BackendStatus("game", "GAME", installed, runnable, str(metadata.get("commit", "未验证")), detail)

    def extract_notes(self, input_dir: Path, output_dir: Path) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        output_dir.mkdir(parents=True, exist_ok=True)
        args = [
            str(self._python()), "-X", "utf8", "infer.py", "extract", str(input_dir), "-m", str(self._model()),
            "--language", "zh", "--batch-size", "1", "--num-workers", "0", "--precision", "32-true",
            "--glob", "source_*.wav", "--output-formats", "txt", "--pitch-format", "name",
            "--round-pitch", "--output-dir", str(output_dir),
        ]
        run_checked(args, self.root / "GAME", timeout=7200)
        if not list(output_dir.rglob("source_*.txt")):
            raise RuntimeError("GAME 没有生成音符文本")
        return output_dir


class DiffSingerLegacyAdapter:
    backend_id = "diffsinger"

    def __init__(self, root: Path):
        self.root = root

    def _python(self) -> Path:
        return self.root.parent / "rvc" / "runtime" / "Scripts" / "python.exe"

    def status(self) -> BackendStatus:
        metadata = _marker(self.root)
        demo = self.root / "legacy_demo"
        required = [
            demo / "checkpoints" / "0831_opencpop_ds1000" / "model_ckpt_steps_320000.ckpt",
            demo / "checkpoints" / "0102_xiaoma_pe" / "model_ckpt_steps_60000.ckpt",
            demo / "checkpoints" / "0109_hifigan_bigpopcs_hop128" / "model_ckpt_steps_1512000.ckpt",
        ]
        installed = self._python().is_file() and (self.root / "legacy_runtime" / "Lib" / "site-packages" / "pypinyin").is_dir()
        runnable = installed and all(path.is_file() for path in required) and metadata.get("legacy_smoke_test_passed") is True
        detail = "官方 legacy OpenCpop 模型已通过中文真实合成" if runnable else (
            "legacy 文件存在但真实合成尚未通过" if installed else "缺少 legacy 模型或兼容 runtime"
        )
        return BackendStatus("diffsinger", "DiffSinger", installed, runnable, str(metadata.get("legacy_commit", metadata.get("commit", "未验证"))), detail)

    def generate_batch(self, request_file: Path, runner: Path) -> None:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        if not runner.is_file():
            raise BackendUnavailable("DiffSinger 兼容运行脚本缺失")
        run_checked([str(self._python()), "-X", "utf8", str(runner), str(request_file)], self.root, timeout=7200)


class AlignmentAdapter:
    backend_id = "alignment"

    def __init__(self, root: Path):
        self.root = root

    def status(self) -> BackendStatus:
        metadata = _marker(self.root)
        runtime = _runtime_python(self.root)
        stable_package = self.root / "runtime" / "Lib" / "site-packages" / "stable_whisper"
        model = self.root / "models" / "base.pt"
        installed = runtime.is_file() and stable_package.is_dir() and model.is_file()
        runnable = installed and metadata.get("smoke_test_passed") is True
        detail = str(metadata.get("detail", "Whisper 强制对齐已通过真实测试")) if runnable else (
            "文件存在但尚未通过真实强制对齐" if installed else "缺少独立运行时、Stable-ts 或 Whisper base 模型"
        )
        return BackendStatus(
            "alignment", "歌词对齐", installed, runnable,
            str(metadata.get("commit", "未验证")), detail,
        )

    def align(self, request_file: Path, runner: Path) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        if not runner.is_file():
            raise BackendUnavailable("歌词对齐运行脚本缺失")
        run_checked([str(_runtime_python(self.root)), "-X", "utf8", str(runner), str(request_file)], self.root, timeout=3600)
        request = json.loads(request_file.read_text(encoding="utf-8"))
        output = Path(str(request["output_path"]))
        if not output.is_file() or output.stat().st_size < 32:
            raise RuntimeError("歌词对齐后端没有生成有效 JSON")
        return output


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
        usable_index = _faiss_safe_index(index) if index else None
        args = [str(_runtime_python(self.root)), "-m", "rvc.wrapper.cli.cli", "infer", "-m", str(model),
                "-i", str(input_audio), "-o", str(output_audio), "-fu", str(pitch),
                "-fm", "rmvpe", "-ir", "0.75" if usable_index else "0"]
        if usable_index:
            args += ["-if", str(usable_index)]
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
        output_audio.parent.mkdir(parents=True, exist_ok=True)
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
