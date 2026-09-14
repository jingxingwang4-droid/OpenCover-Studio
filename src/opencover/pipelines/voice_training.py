from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import numpy as np
import soundfile as sf

from opencover.audio.processing import ffmpeg_path
from opencover.models.importer import ModelImporter

AUDIO_EXTENSIONS = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aac"}


def audio_sources(source: Path) -> list[Path]:
    if not source.exists():
        raise ValueError("素材路径不存在")
    paths = [source] if source.is_file() else [p for p in source.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS]
    if not paths or any(p.suffix.lower() not in AUDIO_EXTENSIONS for p in paths):
        raise ValueError("请选择音频文件或包含音频的文件夹")
    return sorted(paths, key=lambda p: [int(s) if s.isdigit() else s.casefold() for s in re.split(r"(\d+)", str(p))])


def validate_options(options: dict) -> None:
    if not isinstance(options, dict):
        raise ValueError("训练设置格式无效")
    if options.get("action", "train") not in {"merge", "slice", "train"}:
        raise ValueError("不支持的训练操作")
    for name, low, high, default in (("epochs", 1, 1000, 100), ("batch_size", 1, 16, 4), ("slice_seconds", 2, 10, 4)):
        value = options.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f"{name} 必须在 {low}–{high} 之间")
    if not isinstance(options.get("display_name"), str) or not options["display_name"].strip():
        raise ValueError("请填写音色名称")
    if options.get("voice_gender", "unknown") not in {"unknown", "female", "male"}:
        raise ValueError("目标声部选项无效")


def merge_audio(sources: list[Path], target: Path, ffmpeg: Path, report=lambda *args: None) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / "decoded.wav"
    manifest = []
    frames = 0
    try:
        with sf.SoundFile(target, "w", samplerate=40000, channels=1, subtype="PCM_24") as output:
            for i, source in enumerate(sources):
                subprocess.run([str(ffmpeg), "-nostdin", "-v", "error", "-y", "-i", str(source), "-ar", "40000", "-c:a", "pcm_f32le", str(temporary)], check=True, capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                samples, _ = sf.read(temporary, dtype="float32", always_2d=True)
                samples = samples.mean(axis=1)
                if not len(samples) or not np.isfinite(samples).all() or np.max(np.abs(samples)) < 1e-5:
                    raise ValueError(f"素材为空、静音或损坏：{source.name}")
                gain = min(1.0, .999 / float(np.max(np.abs(samples))))
                samples *= gain
                manifest.append({"source": str(source), "start_frame": frames, "frames": len(samples), "gain": gain, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()})
                output.write(samples)
                frames += len(samples)
                # Silence marks each original clip boundary for later slicing.
                if i < len(sources) - 1:
                    output.write(np.zeros(16000, dtype="float32")); frames += 16000
                report("merge", int(15 * (i + 1) / len(sources)), f"合并素材 {i + 1}/{len(sources)}")
    finally:
        temporary.unlink(missing_ok=True)
    return {"sample_rate": 40000, "frames": frames, "seconds": frames / 40000, "gap_seconds": .4, "sources": manifest}


class VoiceTrainingPipeline:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.backend = self.root / "external_backends/rvc_training"
        self.python = self.root / "external_backends/rvc/runtime/Scripts/python.exe"
        if not self.python.is_file():
            self.python = self.root / "external_backends/rvc/runtime/python.exe"

    def preflight(self, source: Path, options: dict) -> None:
        validate_options(options)
        audio_sources(source)
        if not ffmpeg_path(self.root):
            raise RuntimeError("FFmpeg 未安装")
        if options.get("action", "train") == "merge":
            return
        needed = [self.python, self.backend / "source/infer/modules/train/preprocess.py"]
        if options.get("action", "train") == "train":
            needed += [self.backend / f"pretrained/{name}.pth" for name in ("f0G40k", "f0D40k")]
            needed += [self.root / "external_backends/rvc/models" / name for name in ("hubert_base.pt", "rmvpe.pt")]
        for path in needed:
            if not path.is_file():
                raise RuntimeError(f"训练组件缺失：{path}。请运行 scripts/setup_rvc_training.py 安装。")

    def run(self, source: Path, options: dict, job: Path, report=lambda *args: None) -> Path:
        self.preflight(source, options)
        sources = audio_sources(source)
        job.mkdir(parents=True, exist_ok=True)
        work = job / "training"
        (work / "input").mkdir(parents=True, exist_ok=False)
        manifest = merge_audio(sources, work / "input/merged.wav", ffmpeg_path(self.root), report)
        (work / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if options.get("action") == "merge":
            return work / "input/merged.wav"
        experiment = work / "logs/voice"
        experiment.mkdir(parents=True)
        config = json.loads((self.backend / "source/configs/v1/40k.json").read_text())
        config["train"].update(fp16_run=True, log_interval=20)
        (experiment / "config.json").write_text(json.dumps(config), encoding="utf-8")
        (work / "assets/weights").mkdir(parents=True)
        if options.get("action", "train") == "train":
            for source_name, relative in (("hubert_base.pt", "hubert/hubert_base.pt"), ("rmvpe.pt", "rmvpe/rmvpe.pt")):
                target = work / "assets" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                original = self.root / "external_backends/rvc/models" / source_name
                try:
                    os.link(original, target)
                except OSError:
                    shutil.copy2(original, target)
            shutil.copytree(self.backend / "source/i18n", work / "i18n")
        request = {"root": str(self.root), "work": str(work), "epochs": options.get("epochs", 100), "batch_size": options.get("batch_size", 4), "slice_seconds": options.get("slice_seconds", 4)}
        request_path = work / "runtime_request.json"
        request_path.write_text(json.dumps(request), encoding="utf-8")
        runner = Path(__file__).resolve().parents[1] / "workers/rvc_training_runtime.py"
        if not runner.is_file():
            import sys
            runner = Path(getattr(sys, "_MEIPASS", self.root / "_opencover_runtime")) / "workers/rvc_training_runtime.py"
        if not runner.is_file():
            runner = self.root / "_opencover_runtime/workers/rvc_training_runtime.py"
        env = os.environ.copy()
        env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1", OMP_NUM_THREADS="4", MKL_NUM_THREADS="4")
        env["PATH"] = str(ffmpeg_path(self.root).parent) + os.pathsep + env.get("PATH", "")
        env["PYTHONPATH"] = str(self.backend / "source")
        temp = work / "tmp"; temp.mkdir()
        env.update(TEMP=str(temp), TMP=str(temp), NUMBA_CACHE_DIR=str(temp / "numba"), MPLCONFIGDIR=str(temp / "matplotlib"))
        stages = [("slice", 18, "静音切片与音频预处理")]
        if options.get("action", "train") == "train":
            stages += [("f0", 25, "提取 RMVPE 音高"), ("features", 32, "提取音色训练特征"), ("index", 40, "校验特征并建立检索索引"), ("train", 45, "GPU 音色训练"), ("verify", 96, "校验训练权重")]
        for stage, progress, label in stages:
            report(stage, progress, label)
            with (work / f"{stage}.log").open("w", encoding="utf-8") as log:
                process = subprocess.Popen([str(self.python), "-X", "utf8", str(runner), str(request_path), stage], cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    for line in process.stdout:
                        log.write(line); log.flush()
                        match = re.search(r"====> Epoch: (\d+)", line)
                        if match:
                            epoch = int(match.group(1))
                            report("train", min(95, 45 + int(50 * epoch / request["epochs"])), f"训练 {epoch}/{request['epochs']} 轮")
                    code = process.wait()
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait()
            if code:
                detail = (work / f"{stage}.log").read_text(encoding="utf-8")[-2400:]
                raise RuntimeError(f"{label}失败（{code}）：{detail}")
        if options.get("action") == "slice":
            return experiment / "0_gt_wavs"
        model = ModelImporter(self.root / "weights", ffmpeg_path(self.root)).import_model(engine="rvc", weight=work / "assets/weights/voice.pth", index_or_config=work / "voice.index", display_name=options["display_name"], voice_gender=options.get("voice_gender", "unknown"), description=f"本地 RVC v2 40k 训练，{request['epochs']} 轮；听感待验收。")
        result = {"model_id": model.id, "model_path": str(model.directory(self.root / "weights")), "epochs": request["epochs"], "training_seconds": manifest["seconds"], "listening_accepted": False}
        result_path = work / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        report("complete", 100, "训练完成，音色已加入音色管理")
        return result_path
