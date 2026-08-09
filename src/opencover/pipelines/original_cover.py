from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from opencover.adapters.backends import DDSPAdapter, MSSTAdapter, RVCAdapter
from opencover.audio.processing import export_audio, ffmpeg_path, mix_tracks, normalize_input
from opencover.models.schema import VoiceModel


@dataclass(frozen=True)
class CoverRequest:
    input_path: Path
    engine: str
    voice: VoiceModel
    pitch: int
    balance: str
    output_format: str = "wav"


def cache_key(request: CoverRequest) -> str:
    stat = request.input_path.stat()
    data = f"{request.input_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{request.engine}:{request.voice.id}:{request.pitch}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class OriginalCoverPipeline:
    """Runs only verified real backends; missing components are hard failures."""

    def __init__(self, root: Path):
        self.root = root
        self.msst = MSSTAdapter(root / "external_backends" / "msst")
        self.rvc = RVCAdapter(root / "external_backends" / "rvc")
        self.ddsp = DDSPAdapter(root / "external_backends" / "ddsp")

    def preflight(self, request: CoverRequest) -> list[str]:
        issues: list[str] = []
        if not request.input_path.is_file():
            issues.append("输入音频不存在")
        if not ffmpeg_path(self.root):
            issues.append("FFmpeg 未安装")
        if not self.msst.status().runnable:
            issues.append(self.msst.status().detail)
        converter = self.rvc if request.engine == "rvc" else self.ddsp
        if not converter.status().runnable:
            issues.append(converter.status().detail)
        model_dir = request.voice.directory(self.root / "weights")
        if not all((model_dir / file).is_file() for file in request.voice.model_files):
            issues.append("音色权重缺失")
        return issues

    def run(
        self,
        request: CoverRequest,
        job_dir: Path,
        progress: Callable[[str, int, str], None] | None = None,
    ) -> Path:
        issues = self.preflight(request)
        if issues:
            raise RuntimeError("；".join(issues))
        report = progress or (lambda stage, value, message: None)
        ffmpeg = ffmpeg_path(self.root)
        assert ffmpeg is not None
        key = cache_key(request)
        extension = request.output_format.lower()
        output = self.root / "workspace" / "outputs" / f"{request.input_path.stem}_{request.voice.id}_{key[:10]}.{extension}"
        if output.is_file() and output.stat().st_size > 1024:
            report("export", 100, "已使用缓存结果")
            return output

        normalized_dir = job_dir / "normalized"
        normalized = normalized_dir / "input.wav"
        report("normalize", 8, "正在标准化音频")
        normalize_input(request.input_path, normalized, ffmpeg)

        separation_dir = job_dir / "separation"
        report("separate", 20, "正在分离人声与伴奏")
        self.msst.separate(
            normalized_dir,
            separation_dir,
            "mdx23c",
            self.root / "external_backends" / "msst" / "models" / "config_vocals_mdx23c.yaml",
            self.root / "external_backends" / "msst" / "models" / "model_vocals_mdx23c_sdr_10.17.ckpt",
        )
        vocals = next(separation_dir.rglob("vocals.wav"), None)
        accompaniment = next(separation_dir.rglob("other.wav"), None)
        if vocals is None or accompaniment is None:
            raise RuntimeError("MSST 未生成预期的 vocals.wav / other.wav")

        model_dir = request.voice.directory(self.root / "weights")
        model = model_dir / request.voice.model_files[0]
        converted_raw = job_dir / "conversion" / "vocal_raw.wav"
        report("convert", 58, f"正在使用 {request.engine.upper()} 转换音色")
        if request.engine == "rvc":
            index = model_dir / request.voice.index_files[0] if request.voice.index_files else None
            self.rvc.convert(vocals, converted_raw, model, request.pitch, index)
        elif request.engine == "ddsp":
            config = model_dir / request.voice.config_files[0] if request.voice.config_files else None
            self.ddsp.convert(vocals, converted_raw, model, request.pitch, config)
        else:
            raise RuntimeError(f"不支持的音色引擎：{request.engine}")

        converted = job_dir / "conversion" / "vocal_44100.wav"
        report("align", 80, "正在校正采样率与时长")
        normalize_input(converted_raw, converted, ffmpeg)
        mixed = job_dir / "mix" / "final.wav"
        report("mix", 90, "正在匹配响度并混音")
        mix_tracks(converted, accompaniment, mixed, request.balance)
        report("export", 97, "正在导出结果")
        export_audio(mixed, output, ffmpeg)
        report("export", 100, "翻唱已完成")
        return output
