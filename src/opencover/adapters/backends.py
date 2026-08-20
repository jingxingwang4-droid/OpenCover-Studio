from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Callable

from .base import BackendStatus, BackendUnavailable, run_checked, run_checked_streaming


def _runtime_python(root: Path) -> Path:
    candidates = [
        root / "python.exe",
        root / "runtime" / "python.exe",
        root / "runtime" / "Scripts" / "python.exe",
    ]
    return next((path for path in candidates if path.is_file()), candidates[-1])


def _venv_base_available(runtime: Path) -> bool:
    """Return false when a uv/venv launcher points at a deleted base Python."""
    config = runtime.parent.parent / "pyvenv.cfg"
    if not config.is_file():
        return True
    try:
        home = next(
            line.split("=", 1)[1].strip()
            for line in config.read_text(encoding="utf-8-sig").splitlines()
            if line.partition("=")[0].strip().lower() == "home"
        )
    except (OSError, StopIteration):
        return False
    base = Path(home)
    return base.is_dir() and any(
        candidate.is_file() for candidate in (base / "python.exe", base / "Scripts" / "python.exe")
    )


@lru_cache(maxsize=32)
def _probe_python_launcher(path: str, size: int, modified_ns: int) -> bool:
    del size, modified_ns  # They intentionally invalidate the cache when a launcher is repaired.
    try:
        result = subprocess.run(
            [path, "--version"], capture_output=True, check=False, shell=False, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _python_launcher_available(runtime: Path) -> bool:
    try:
        stat = runtime.stat()
    except OSError:
        return False
    return _probe_python_launcher(str(runtime), stat.st_size, stat.st_mtime_ns)


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

    def generate_batch(self, request_file: Path, runner: Path, progress: Callable[[int, int], None] | None = None) -> None:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        if not runner.is_file():
            raise BackendUnavailable("Vevo2 运行脚本缺失")
        prefix = "OPENCOVER_PROGRESS "

        def on_line(line: str) -> None:
            if progress is None or not line.startswith(prefix):
                return
            try:
                event = json.loads(line[len(prefix):])
                progress(int(event["done"]), int(event["total"]))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return

        run_checked_streaming(
            [str(_runtime_python(self.root)), str(runner), str(request_file)],
            self.root, on_line, timeout=7200,
        )


class GameAdapter:
    backend_id = "game"

    def __init__(self, root: Path):
        self.root = root

    def _python(self) -> Path:
        return _runtime_python(self.root)

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

    def refine_notes(
        self, source_dir: Path, notes_dir: Path, output_dir: Path, runner: Path,
    ) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        if not runner.is_file():
            raise BackendUnavailable("连续 F0 乐谱复核脚本缺失")
        request_file = output_dir.parent / "score_refinement_request.json"
        request_file.write_text(json.dumps({
            "source_dir": str(source_dir),
            "notes_dir": str(notes_dir),
            "output_dir": str(output_dir),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        run_checked([str(_runtime_python(self.root)), "-X", "utf8", str(runner), str(request_file)], self.root, timeout=3600)
        expected = sorted(notes_dir.glob("source_*.txt"))
        if not expected or not all((output_dir / path.name).is_file() for path in expected):
            raise RuntimeError("连续 F0 乐谱复核没有生成完整结果")
        return output_dir


class DiffSingerLegacyAdapter:
    backend_id = "diffsinger"

    def __init__(self, root: Path):
        self.root = root

    def _python(self) -> Path:
        return _runtime_python(self.root.parent / "rvc")

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

    def generate_batch(self, request_file: Path, runner: Path, progress: Callable[[int, int], None] | None = None) -> None:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        if not runner.is_file():
            raise BackendUnavailable("DiffSinger 兼容运行脚本缺失")
        prefix = "OPENCOVER_PROGRESS "

        def on_line(line: str) -> None:
            if progress is None or not line.startswith(prefix):
                return
            try:
                event = json.loads(line[len(prefix):])
                progress(int(event["done"]), int(event["total"]))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return

        run_checked_streaming(
            [str(self._python()), "-X", "utf8", str(runner), str(request_file)],
            self.root, on_line, timeout=7200,
        )


class EspnetVisinger2Adapter:
    backend_id = "espnet_visinger2"

    def __init__(self, root: Path):
        self.root = root

    def status(self) -> BackendStatus:
        metadata = _marker(self.root)
        runtime = _runtime_python(self.root)
        required = [
            self.root / "source" / "espnet2" / "bin" / "svs_inference.py",
            self.root / "frontend" / "resource" / "pinyin_dict.py",
            self.root / "model" / "exp" / "svs_train_visinger2_40singer_raw_phn_None_zh" / "config.yaml",
            self.root / "model" / "exp" / "svs_train_visinger2_40singer_raw_phn_None_zh" / "500epoch.pth",
            self.root / "runtime" / "Lib" / "site-packages" / "typeguard" / "__init__.py",
            self.root / "runtime" / "Lib" / "site-packages" / "pypinyin" / "__init__.py",
        ]
        installed = runtime.is_file() and all(path.is_file() for path in required)
        runnable = installed and metadata.get("smoke_test_passed") is True
        detail = str(metadata.get("detail", "44.1 kHz 中文乐谱模型已通过真实合成")) if runnable else (
            "VISinger2 文件存在但真实合成尚未通过" if installed else "缺少 VISinger2 独立环境、源码或权重"
        )
        return BackendStatus(
            self.backend_id, "VISinger2 乐谱歌声", installed, runnable,
            str(metadata.get("model_revision", metadata.get("source_commit", "未验证"))), detail,
        )

    def generate_batch(
        self, request_file: Path, runner: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        if not runner.is_file():
            raise BackendUnavailable("VISinger2 运行脚本缺失")
        prefix = "OPENCOVER_PROGRESS "

        def on_line(line: str) -> None:
            if progress is None or not line.startswith(prefix):
                return
            try:
                event = json.loads(line[len(prefix):])
                progress(int(event["done"]), int(event["total"]))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return

        run_checked_streaming(
            [str(_runtime_python(self.root)), "-X", "utf8", str(runner), str(request_file)],
            self.root, on_line, timeout=7200,
        )


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

    def convert(
        self, input_audio: Path, output_audio: Path, model: Path, pitch: int,
        index: Path | None = None, *, f0_method: str = "rmvpe", index_rate: float = 0.75,
        protect: float = 0.33, rms_mix_rate: float = 0.25,
    ) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        usable_index = _faiss_safe_index(index) if index else None
        args = [str(_runtime_python(self.root)), "-m", "rvc.wrapper.cli.cli", "infer", "-m", str(model),
                "-i", str(input_audio), "-o", str(output_audio), "-fu", str(pitch),
                "-fm", f0_method, "-ir", str(index_rate if usable_index else 0),
                "-rmr", str(rms_mix_rate), "-p", str(protect)]
        if usable_index:
            args += ["-if", str(usable_index)]
        output_audio.parent.mkdir(parents=True, exist_ok=True)
        run_checked(args, self.root)
        if not output_audio.is_file() or output_audio.stat().st_size < 1024:
            raise RuntimeError("RVC 没有生成有效输出")
        return output_audio

    def convert_batch(
        self, request_file: Path, runner: Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        if not runner.is_file():
            raise BackendUnavailable("RVC 分段运行脚本缺失")
        prefix = "OPENCOVER_PROGRESS "

        def on_line(line: str) -> None:
            if progress is None or not line.startswith(prefix):
                return
            try:
                event = json.loads(line[len(prefix):])
                progress(int(event["done"]), int(event["total"]))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return

        run_checked_streaming(
            [str(_runtime_python(self.root)), "-X", "utf8", str(runner), str(request_file)],
            self.root, on_line, timeout=7200,
        )


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

    def convert(
        self, input_audio: Path, output_audio: Path, model: Path, pitch: int,
        config: Path | None = None, *, f0_method: str = "rmvpe", f0_min: float = 50,
        f0_max: float = 1100, threshold_db: float = -60,
    ) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        output_audio.parent.mkdir(parents=True, exist_ok=True)
        args = [str(_runtime_python(self.root)), "main_reflow.py", "-i", str(input_audio), "-m", str(model),
                "-o", str(output_audio), "-k", str(pitch), "-id", "1",
                "-pe", f0_method, "-fmin", str(f0_min), "-fmax", str(f0_max),
                "-th", str(threshold_db)]
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


class UVR5Adapter:
    """Headless UVR5 chain: total vocals, lead-vocal split, then de-reverb."""

    backend_id = "uvr5"
    pipeline_id = "uvr5-voc-ft-5hp-karaoke-anvuew-dereverb-v2"
    vocal_model_name = "UVR-MDX-NET-Voc_FT.onnx"
    lead_model_name = "5_HP-Karaoke-UVR.pth"
    dereverb_model_name = "dereverb_mel_band_roformer_anvuew_sdr_19.1729.ckpt"
    dereverb_config_name = "dereverb_mel_band_roformer_anvuew.yaml"

    def __init__(self, root: Path, ffmpeg_bin: Path):
        self.root = root
        self.ffmpeg_bin = ffmpeg_bin

    @property
    def runtime(self) -> Path:
        return _runtime_python(self.root)

    @property
    def audio_separator_package(self) -> Path:
        return self.root / "runtime" / "Lib" / "site-packages" / "audio_separator"

    @property
    def model_dir(self) -> Path:
        return self.root / "models_runtime"

    @property
    def model_paths(self) -> tuple[Path, ...]:
        return (
            self.model_dir / self.vocal_model_name,
            self.model_dir / self.lead_model_name,
            self.model_dir / self.dereverb_model_name,
            self.model_dir / self.dereverb_config_name,
        )

    def status(self) -> BackendStatus:
        metadata = _marker(self.root)
        installed = self.runtime.is_file() and self.audio_separator_package.is_dir() and self.ffmpeg_bin.is_dir() and all(
            path.is_file() and path.stat().st_size > 1024 for path in self.model_paths
        )
        runtime_available = (
            installed
            and _venv_base_available(self.runtime)
            and _python_launcher_available(self.runtime)
        )
        runnable = (
            runtime_available
            and metadata.get("smoke_test_passed") is True
            and metadata.get("pipeline_id") == self.pipeline_id
        )
        if runnable:
            detail = str(metadata.get("detail", "UVR5 三阶段主唱分离与强去混响已通过真实测试"))
        elif installed and not runtime_available:
            detail = "UVR5 Python 运行时已丢失或断链，请修复组件后重试"
        elif installed:
            detail = "UVR5 文件存在，但尚未通过三阶段真实分离测试"
        else:
            detail = "缺少 UVR5 独立环境、总人声/主唱拆分模型或强去混响模型"
        return BackendStatus(
            self.backend_id, "UVR5 推荐分离", installed, runnable,
            str(metadata.get("version", metadata.get("commit", "未验证"))), detail,
        )

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PATH"] = str(self.ffmpeg_bin) + os.pathsep + env.get("PATH", "")
        return env

    def _run_model(self, source: Path, output_dir: Path, model_name: str) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)
        args = [
            str(self.runtime), "-X", "utf8", "-c",
            "from audio_separator.utils.cli import main; main()",
            str(source), "-m", model_name,
            "--model_file_dir", str(self.model_dir),
            "--output_dir", str(output_dir), "--output_format", "WAV",
            "--sample_rate", "44100", "--mdx_segment_size", "256",
            "--mdx_overlap", "0.5", "--mdxc_overlap", "8",
            "--mdxc_batch_size", "1", "--vr_window_size", "320",
            "--vr_aggression", "10", "--vr_enable_tta",
            "--vr_high_end_process", "--use_soundfile", "--log_level", "info",
        ]
        run_checked(args, self.root, timeout=7200, env=self._environment())

    @staticmethod
    def _model_stem(output_dir: Path, stem: str, model_name: str) -> Path | None:
        """Select this stage's stem even when input filenames contain old stem labels."""
        model_token = Path(model_name).stem
        return next(
            (path for path in output_dir.glob("*.wav") if f"_({stem})_{model_token}" in path.name),
            None,
        )

    def separate(self, input_audio: Path, output_dir: Path) -> Path:
        status = self.status()
        if not status.runnable:
            raise BackendUnavailable(status.detail)
        stage1 = output_dir / "stage1_total_vocals"
        stage2 = output_dir / "stage2_lead_vocal"
        stage3 = output_dir / "stage3_dereverb"
        self._run_model(input_audio, stage1, self.vocal_model_name)
        source_vocals = self._model_stem(stage1, "Vocals", self.vocal_model_name)
        source_other = self._model_stem(stage1, "Instrumental", self.vocal_model_name)
        if source_vocals is None or source_other is None:
            raise RuntimeError("UVR5 第一阶段未生成预期的人声/伴奏轨")
        self._run_model(source_vocals, stage2, self.lead_model_name)
        lead_vocals = self._model_stem(stage2, "Vocals", self.lead_model_name)
        backing_vocals = self._model_stem(stage2, "Instrumental", self.lead_model_name)
        if lead_vocals is None or backing_vocals is None:
            raise RuntimeError("UVR5 第二阶段未生成预期的主唱/和声轨")
        self._run_model(lead_vocals, stage3, self.dereverb_model_name)
        dry_vocals = next(stage3.glob("*_(No Reverb)_*.wav"), None)
        if dry_vocals is None:
            dry_vocals = next(stage3.glob("*_(noreverb)_*.wav"), None)
        if dry_vocals is None:
            dry_vocals = next(stage3.glob("*_(Dry)_*.wav"), None)
        if dry_vocals is None:
            raise RuntimeError("UVR5 第三阶段未生成去混响主唱")
        for source, target_name in ((dry_vocals, "vocals.wav"), (source_other, "other.wav")):
            target = output_dir / target_name
            partial = target.with_suffix(".wav.part")
            shutil.copy2(source, partial)
            partial.replace(target)
        return output_dir
