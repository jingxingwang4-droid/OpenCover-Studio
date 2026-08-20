from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from opencover.adapters.backends import DDSPAdapter, MSSTAdapter, RVCAdapter, UVR5Adapter
from opencover.audio.processing import export_audio, ffmpeg_path, mix_tracks, normalize_input, restore_vocal_detail
from opencover.audio.pitch import analyze_vocal_pitch, resolve_auto_pitch
from opencover.core.retry_policy import chunk_sizes_for_profile, convert_with_oom_retry
from opencover.models.schema import VoiceModel


@dataclass(frozen=True)
class CoverRequest:
    input_path: Path
    engine: str
    voice: VoiceModel
    pitch: int
    balance: str
    output_format: str = "wav"
    memory_profile: str = "标准"
    pitch_mode: str = "manual"
    source_voice: str = "auto"


def cache_key(request: CoverRequest, separation_identity: str = "msst-v1") -> str:
    stat = request.input_path.stat()
    model_identity = ":".join(f"{name}={digest}" for name, digest in sorted(request.voice.sha256.items()) if name in request.voice.model_files + request.voice.index_files + request.voice.config_files)
    data = f"vc9:{separation_identity}:{request.input_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{request.engine}:{request.voice.id}:{request.pitch}:{request.pitch_mode}:{request.source_voice}:{request.memory_profile}:{request.voice.inference_signature()}:{model_identity}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def separation_cache_key(
    request: CoverRequest, artifacts: Path | tuple[Path, ...], separator_id: str = "msst-v1",
) -> str:
    """A source-separation key intentionally independent of voice and engine."""
    source_stat = request.input_path.stat()
    paths = (artifacts,) if isinstance(artifacts, Path) else artifacts
    model_identity = ":".join(
        f"{path.resolve()}:{path.stat().st_size}:{path.stat().st_mtime_ns}" for path in paths
    )
    data = f"{separator_id}:{request.input_path.resolve()}:{source_stat.st_size}:{source_stat.st_mtime_ns}:{model_identity}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class OriginalCoverPipeline:
    """Runs only verified real backends; missing components are hard failures."""

    def __init__(self, root: Path):
        self.root = root
        self.msst = MSSTAdapter(root / "external_backends" / "msst")
        self.uvr5 = UVR5Adapter(
            root / "external_backends" / "uvr5",
            root / "ffmpeg" / "ffmpeg-9.0-essentials_build" / "bin",
        )
        self.rvc = RVCAdapter(root / "external_backends" / "rvc")
        self.ddsp = DDSPAdapter(root / "external_backends" / "ddsp")

    def preflight(self, request: CoverRequest) -> list[str]:
        issues: list[str] = []
        if not request.input_path.is_file():
            issues.append("输入音频不存在")
        if request.engine not in {"rvc", "ddsp"} or request.voice.engine != request.engine:
            issues.append("音色引擎与任务引擎不匹配")
        if not request.voice.selectable or request.voice.quality_status == "rejected":
            issues.append("该音色已因真实歌曲验证质量不合格而停用")
        if request.pitch_mode not in {"auto", "manual"}:
            issues.append("升降调模式无效")
        if request.source_voice not in {"auto", "male", "female"}:
            issues.append("原唱声部选项无效")
        if not ffmpeg_path(self.root):
            issues.append("FFmpeg 未安装")
        if not self.uvr5.status().runnable and not self.msst.status().runnable:
            issues.append("UVR5 与 MSST 均不可用：" + self.uvr5.status().detail + "；" + self.msst.status().detail)
        converter = self.rvc if request.engine == "rvc" else self.ddsp
        if not converter.status().runnable:
            issues.append(converter.status().detail)
        model_dir = request.voice.directory(self.root / "weights")
        if not all((model_dir / file).is_file() for file in request.voice.model_files):
            issues.append("音色权重缺失")
        if request.engine == "rvc" and not all((model_dir / file).is_file() for file in request.voice.index_files):
            issues.append("RVC 索引文件缺失")
        if request.engine == "ddsp" and not all((model_dir / file).is_file() for file in request.voice.config_files):
            issues.append("DDSP 配置文件缺失")
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
        use_uvr5 = self.uvr5.status().runnable
        separator_id = self.uvr5.pipeline_id if use_uvr5 else "msst-mdx23c-v1"
        separator_artifacts = self.uvr5.model_paths if use_uvr5 else (
            self.root / "external_backends" / "msst" / "models" / "model_vocals_mdx23c_sdr_10.17.ckpt",
        )
        checkpoint = self.root / "external_backends" / "msst" / "models" / "model_vocals_mdx23c_sdr_10.17.ckpt"
        shared_separation = self.root / "workspace" / "cache" / "separation" / separation_cache_key(
            request, separator_artifacts, separator_id,
        )
        cached_vocals = shared_separation / "vocals.wav"
        cached_accompaniment = shared_separation / "other.wav"
        if all(path.is_file() and path.stat().st_size > 1024 for path in (cached_vocals, cached_accompaniment)):
            report("normalize", 8, "已复用标准化与分离缓存")
            report("separate", 20, "已复用人声与伴奏缓存")
            vocals, accompaniment = cached_vocals, cached_accompaniment
        else:
            normalized_dir = job_dir / "normalized"
            normalized = normalized_dir / "input.wav"
            report("normalize", 8, "正在标准化音频")
            normalize_input(request.input_path, normalized, ffmpeg)

            separation_dir = job_dir / "separation"
            report("separate", 20, "正在使用 UVR5 分离总人声、剔除和声并强去混响" if use_uvr5 else "正在使用 MSST 分离人声与伴奏")
            if use_uvr5:
                self.uvr5.separate(normalized, separation_dir)
            else:
                self.msst.separate(
                    normalized_dir, separation_dir, "mdx23c",
                    self.root / "external_backends" / "msst" / "models" / "config_vocals_mdx23c.yaml",
                    checkpoint,
                )
            vocals = next(separation_dir.rglob("vocals.wav"), None)
            accompaniment = next(separation_dir.rglob("other.wav"), None)
            if vocals is None or accompaniment is None:
                raise RuntimeError("MSST 未生成预期的 vocals.wav / other.wav")
            shared_separation.mkdir(parents=True, exist_ok=True)
            for source, target in ((vocals, cached_vocals), (accompaniment, cached_accompaniment)):
                partial = target.with_suffix(target.suffix + ".part")
                shutil.copy2(source, partial)
                partial.replace(target)
            vocals, accompaniment = cached_vocals, cached_accompaniment

        analysis = None
        effective_pitch = request.pitch
        detected_gender = "unknown"
        if request.pitch_mode == "auto":
            report("pitch", 32, "正在分析原唱音域")
            analysis = analyze_vocal_pitch(vocals)
            effective_pitch, detected_gender = resolve_auto_pitch(
                request.pitch, request.source_voice, request.voice.voice_gender, analysis,
            )
            detected_label = {"male": "男声", "female": "女声", "unknown": "无法稳定判定"}[detected_gender]
            hz = f"（中位 F0 {analysis.median_hz:.0f} Hz）" if analysis.median_hz is not None else ""
            report("pitch", 38, f"原唱音域：{detected_label}{hz}；本次升降调 {effective_pitch:+d} 半音")
        effective_request = replace(request, pitch=effective_pitch)
        key = cache_key(effective_request, separator_id)
        final_key = hashlib.sha256(f"{key}:{request.balance}:{request.output_format.lower()}".encode("utf-8")).hexdigest()
        extension = request.output_format.lower()
        output = self.root / "workspace" / "outputs" / f"{request.input_path.stem}_{request.voice.id}_{final_key[:10]}.{extension}"
        if output.is_file() and output.stat().st_size > 1024:
            report("export", 100, "已使用缓存结果")
            return output

        model_dir = request.voice.directory(self.root / "weights")
        model = model_dir / request.voice.model_files[0]
        conversion_cache = self.root / "workspace" / "cache" / "voice_conversion" / key / "vocal_raw.wav"
        if conversion_cache.is_file() and conversion_cache.stat().st_size > 1024:
            report("convert", 58, "已复用音色转换缓存")
            converted_raw = conversion_cache
        else:
            converted_raw = job_dir / "conversion" / "vocal_raw.wav"
            report("convert", 58, f"正在使用 {request.engine.upper()} 转换音色")
            if request.engine == "rvc":
                index = model_dir / request.voice.index_files[0] if request.voice.index_files else None
                converter = lambda source, target: self.rvc.convert(
                    source, target, model, effective_pitch, index,
                    f0_method=request.voice.f0_method or "rmvpe",
                    index_rate=request.voice.index_rate if request.voice.index_rate is not None else 0.75,
                    protect=request.voice.protect if request.voice.protect is not None else 0.33,
                    rms_mix_rate=request.voice.rms_mix_rate if request.voice.rms_mix_rate is not None else 0.25,
                )
            else:
                config = model_dir / request.voice.config_files[0] if request.voice.config_files else None
                converter = lambda source, target: self.ddsp.convert(
                    source, target, model, effective_pitch, config,
                    f0_method=request.voice.f0_method or "rmvpe",
                    f0_min=min(request.voice.f0_min or 50, 40) if detected_gender == "male" else (request.voice.f0_min or 50),
                    f0_max=request.voice.f0_max or 1100,
                    threshold_db=request.voice.silence_threshold_db if request.voice.silence_threshold_db is not None else -60,
                )
            convert_with_oom_retry(
                vocals, converted_raw, converter, lambda message: report("convert", 62, message),
                chunk_sizes_for_profile(request.memory_profile),
            )
            conversion_cache.parent.mkdir(parents=True, exist_ok=True)
            partial = conversion_cache.with_suffix(".wav.part")
            shutil.copy2(converted_raw, partial); partial.replace(conversion_cache)
            converted_raw = conversion_cache

        converted = job_dir / "conversion" / "vocal_44100.wav"
        report("align", 80, "正在校正采样率并恢复咬字与高频细节")
        restore_vocal_detail(
            converted_raw, vocals, converted, ffmpeg,
            detail_mix=request.voice.source_detail_mix or 0.0,
            detail_cutoff_hz=request.voice.source_detail_cutoff_hz or 4000,
            treble_db=request.voice.converted_treble_db or 0.0,
            converted_gain=request.voice.converted_gain or 1.0,
        )
        mixed = job_dir / "mix" / "final.wav"
        report("mix", 90, "正在匹配响度并混音")
        mix_tracks(converted, accompaniment, mixed, request.balance)
        report("export", 97, "正在导出结果")
        export_audio(mixed, output, ffmpeg)
        report("export", 100, "翻唱已完成")
        return output
