from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from opencover.adapters.backends import DDSPAdapter, MSSTAdapter, RVCAdapter, Vevo2Adapter
from opencover.audio.processing import export_audio, ffmpeg_path, mix_tracks, normalize_input, validate_audio
from opencover.lyrics.processing import LyricSegment, build_lyric_segments
from opencover.models.schema import VoiceModel
from opencover.pipelines.original_cover import CoverRequest, separation_cache_key


@dataclass(frozen=True)
class LyricCoverRequest:
    input_path: Path
    engine: str
    voice: VoiceModel
    original_lyrics: str
    new_lyrics: str
    strategy: str = "均衡"
    pitch: int = 0
    balance: str = "均衡"
    output_format: str = "wav"


def _digest(parts: list[str]) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _resample(values: np.ndarray, target_frames: int) -> np.ndarray:
    if target_frames <= 0:
        return np.zeros(0, dtype=np.float32)
    if len(values) == target_frames:
        return values.astype(np.float32, copy=False)
    if len(values) < 2:
        return np.zeros(target_frames, dtype=np.float32)
    old = np.linspace(0.0, 1.0, len(values), endpoint=False)
    new = np.linspace(0.0, 1.0, target_frames, endpoint=False)
    return np.interp(new, old, values).astype(np.float32)


class LyricCoverPipeline:
    """Experimental but real LRC/line-segmented Vevo2 → VC → mix pipeline."""

    def __init__(self, root: Path):
        self.root = root
        self.msst = MSSTAdapter(root / "external_backends" / "msst")
        self.vevo2 = Vevo2Adapter(root / "external_backends" / "vevo2")
        self.rvc = RVCAdapter(root / "external_backends" / "rvc")
        self.ddsp = DDSPAdapter(root / "external_backends" / "ddsp")

    def preflight(self, request: LyricCoverRequest) -> list[str]:
        issues: list[str] = []
        if not request.input_path.is_file():
            issues.append("输入音频不存在")
        if not ffmpeg_path(self.root):
            issues.append("FFmpeg 未安装")
        for adapter in (self.msst, self.vevo2):
            status = adapter.status()
            if not status.runnable:
                issues.append(status.detail)
        converter = self.rvc if request.engine == "rvc" else self.ddsp
        status = converter.status()
        if not status.runnable:
            issues.append(status.detail)
        model_dir = request.voice.directory(self.root / "weights")
        if not all((model_dir / name).is_file() for name in request.voice.model_files):
            issues.append("音色权重缺失")
        if request.engine == "rvc" and not all((model_dir / name).is_file() for name in request.voice.index_files):
            issues.append("RVC 索引文件缺失")
        if request.engine == "ddsp" and not all((model_dir / name).is_file() for name in request.voice.config_files):
            issues.append("DDSP 配置文件缺失")
        if not request.original_lyrics.strip():
            issues.append("原歌词为空")
        if not request.new_lyrics.strip():
            issues.append("新歌词为空")
        return issues

    def _separate(
        self,
        request: LyricCoverRequest,
        job_dir: Path,
        report: Callable[[str, int, str], None],
    ) -> tuple[Path, Path]:
        checkpoint = self.root / "external_backends" / "msst" / "models" / "model_vocals_mdx23c_sdr_10.17.ckpt"
        base_request = CoverRequest(request.input_path, request.engine, request.voice, request.pitch, request.balance)
        cache = self.root / "workspace" / "cache" / "separation" / separation_cache_key(base_request, checkpoint)
        vocals, accompaniment = cache / "vocals.wav", cache / "other.wav"
        if all(path.is_file() and path.stat().st_size > 1024 for path in (vocals, accompaniment)):
            report("normalize", 8, "已复用标准化缓存")
            report("separate", 18, "已复用人声与伴奏缓存")
            return vocals, accompaniment
        ffmpeg = ffmpeg_path(self.root)
        assert ffmpeg is not None
        normalized_dir = job_dir / "normalized"
        report("normalize", 8, "正在标准化输入音频")
        normalize_input(request.input_path, normalized_dir / "input.wav", ffmpeg)
        separated = job_dir / "separation"
        report("separate", 18, "正在使用 MSST 分离人声与伴奏")
        self.msst.separate(
            normalized_dir,
            separated,
            "mdx23c",
            self.root / "external_backends" / "msst" / "models" / "config_vocals_mdx23c.yaml",
            checkpoint,
        )
        source_vocals = next(separated.rglob("vocals.wav"), None)
        source_other = next(separated.rglob("other.wav"), None)
        if source_vocals is None or source_other is None:
            raise RuntimeError("MSST 未生成预期的 vocals.wav / other.wav")
        cache.mkdir(parents=True, exist_ok=True)
        for source, target in ((source_vocals, vocals), (source_other, accompaniment)):
            partial = target.with_suffix(".wav.part")
            shutil.copy2(source, partial)
            partial.replace(target)
        return vocals, accompaniment

    def _runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "vevo2_runtime.py",
            self.root / "_internal" / "workers" / "vevo2_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "vevo2_runtime.py",
        ]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _extract_segments(self, vocals: Path, segments: list[LyricSegment], target: Path) -> list[dict[str, object]]:
        audio, rate = sf.read(vocals, always_2d=True, dtype="float32")
        mono = audio.mean(axis=1)
        target.mkdir(parents=True, exist_ok=True)
        manifest: list[dict[str, object]] = []
        for index, segment in enumerate(segments):
            begin = max(0, min(len(mono), round(segment.start * rate)))
            end = max(begin + 1, min(len(mono), round(segment.end * rate)))
            source_values = mono[begin:end]
            input_path = target / f"source_{index:03d}.wav"
            output_path = target / f"generated_{index:03d}.wav"
            sf.write(input_path, _resample(source_values, round(len(source_values) * 24000 / rate)), 24000, subtype="PCM_16")
            manifest.append({
                "input": str(input_path),
                "output": str(output_path),
                "text": segment.new_text,
                "original_text": segment.original_text,
                "duration": segment.duration,
            })
        return manifest

    def _stitch(self, manifest: list[dict[str, object]], segments: list[LyricSegment], duration: float, output: Path) -> Path:
        rate = 44100
        canvas = np.zeros(round(duration * rate), dtype=np.float32)
        for item, segment in zip(manifest, segments):
            generated, _ = sf.read(Path(str(item["output"])), always_2d=True, dtype="float32")
            mono = generated.mean(axis=1)
            begin = max(0, round(segment.start * rate))
            end = min(len(canvas), round(segment.end * rate))
            fitted = _resample(mono, max(0, end - begin))
            fade = min(round(0.03 * rate), len(fitted) // 2)
            if fade:
                fitted[:fade] *= np.linspace(0.0, 1.0, fade, endpoint=False)
                fitted[-fade:] *= np.linspace(1.0, 0.0, fade, endpoint=False)
            canvas[begin:end] += fitted[:end - begin]
        peak = float(np.max(np.abs(canvas))) if canvas.size else 0.0
        if peak > 0.98:
            canvas *= 0.98 / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, canvas, rate, subtype="PCM_24")
        validate_audio(output)
        return output

    def run(
        self,
        request: LyricCoverRequest,
        job_dir: Path,
        progress: Callable[[str, int, str], None] | None = None,
    ) -> Path:
        issues = self.preflight(request)
        if issues:
            raise RuntimeError("；".join(issues))
        report = progress or (lambda stage, value, message: None)
        vocals, accompaniment = self._separate(request, job_dir, report)
        _, _, duration = validate_audio(vocals)
        report("align_lyrics", 24, "正在解析歌词和时间戳")
        segments = build_lyric_segments(request.original_lyrics, request.new_lyrics, duration, request.strategy)

        source_stat = request.input_path.stat()
        marker = (self.root / "external_backends" / "vevo2" / "backend.json").read_text(encoding="utf-8")
        generation_key = _digest([
            str(request.input_path.resolve()), str(source_stat.st_size), str(source_stat.st_mtime_ns),
            request.original_lyrics, request.new_lyrics, request.strategy, marker,
        ])
        generation_cache = self.root / "workspace" / "cache" / "lyric_generation" / generation_key
        generated_vocal = generation_cache / "edited_vocal.wav"
        if generated_vocal.is_file() and generated_vocal.stat().st_size > 1024:
            report("generate", 68, "已复用改词歌声缓存")
        else:
            segment_dir = job_dir / "lyric_segments"
            report("segment", 30, f"正在准备 {len(segments)} 个短句")
            manifest = self._extract_segments(vocals, segments, segment_dir)
            request_file = segment_dir / "vevo2_request.json"
            request_file.write_text(json.dumps({
                "root": str(self.root), "seed": 1234, "flow_matching_steps": 32, "segments": manifest,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            report("generate", 40, f"Vevo2 正在一次加载模型并生成 {len(segments)} 个短句")
            self.vevo2.generate_batch(request_file, self._runner())
            missing = [item["output"] for item in manifest if not Path(str(item["output"])).is_file()]
            if missing:
                raise RuntimeError(f"Vevo2 缺少 {len(missing)} 个分段输出")
            stitched = job_dir / "lyric_generation" / "edited_vocal.wav"
            self._stitch(manifest, segments, duration, stitched)
            generation_cache.mkdir(parents=True, exist_ok=True)
            partial = generated_vocal.with_suffix(".wav.part")
            shutil.copy2(stitched, partial)
            partial.replace(generated_vocal)
            (generation_cache / "segments.json").write_text(
                json.dumps([segment.__dict__ for segment in segments], ensure_ascii=False, indent=2), encoding="utf-8",
            )
            report("stitch", 68, "改词短句已校正时长并拼接")

        model_identity = ":".join(f"{name}={digest}" for name, digest in sorted(request.voice.sha256.items()) if name in request.voice.model_files + request.voice.index_files + request.voice.config_files)
        conversion_key = _digest([generation_key, request.engine, request.voice.id, str(request.pitch), model_identity])
        final_key = _digest([conversion_key, request.balance, request.output_format])
        extension = request.output_format.lower()
        output = self.root / "workspace" / "outputs" / f"{request.input_path.stem}_改词_{request.voice.id}_{final_key[:10]}.{extension}"
        if output.is_file() and output.stat().st_size > 1024:
            report("export", 100, "已使用完整改词缓存")
            return output

        model_dir = request.voice.directory(self.root / "weights")
        model = model_dir / request.voice.model_files[0]
        conversion_cache = self.root / "workspace" / "cache" / "voice_conversion" / f"lyric_{conversion_key}" / "vocal_raw.wav"
        if conversion_cache.is_file() and conversion_cache.stat().st_size > 1024:
            report("convert", 74, "已复用改词音色转换缓存")
            converted_raw = conversion_cache
        else:
            converted_raw = job_dir / "conversion" / "lyric_vocal_raw.wav"
            report("convert", 74, f"正在使用 {request.engine.upper()} 转换最终音色")
            if request.engine == "rvc":
                index = model_dir / request.voice.index_files[0] if request.voice.index_files else None
                self.rvc.convert(generated_vocal, converted_raw, model, request.pitch, index)
            else:
                config = model_dir / request.voice.config_files[0] if request.voice.config_files else None
                self.ddsp.convert(generated_vocal, converted_raw, model, request.pitch, config)
            conversion_cache.parent.mkdir(parents=True, exist_ok=True)
            partial = conversion_cache.with_suffix(".wav.part")
            shutil.copy2(converted_raw, partial); partial.replace(conversion_cache)
            converted_raw = conversion_cache
        ffmpeg = ffmpeg_path(self.root)
        assert ffmpeg is not None
        converted = job_dir / "conversion" / "lyric_vocal_44100.wav"
        report("fit_duration", 84, "正在校正生成歌声时长")
        normalize_input(converted_raw, converted, ffmpeg)
        mixed = job_dir / "mix" / "lyric_final.wav"
        report("mix", 92, "正在匹配响度并混合原伴奏")
        mix_tracks(converted, accompaniment, mixed, request.balance)
        report("export", 98, "正在导出改词结果")
        export_audio(mixed, output, ffmpeg)
        report("export", 100, "改词翻唱已完成")
        return output
