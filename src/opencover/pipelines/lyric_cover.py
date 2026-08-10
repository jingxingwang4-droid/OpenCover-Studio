from __future__ import annotations

import hashlib
import json
import shutil
import sys
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from opencover.adapters.backends import AlignmentAdapter, DDSPAdapter, DiffSingerLegacyAdapter, GameAdapter, MSSTAdapter, RVCAdapter, Vevo2Adapter
from opencover.audio.processing import export_audio, ffmpeg_path, mix_tracks, normalize_input, validate_audio
from opencover.core.retry_policy import chunk_sizes_for_profile, convert_with_oom_retry
from opencover.lyrics.processing import LyricSegment, build_lyric_segments, lyrics_language, parse_lyrics, timed_lyrics_from_alignment
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
    generator: str = "auto"
    memory_profile: str = "标准"


def _digest(parts: list[str]) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def backend_markers(root: Path) -> str:
    parts: list[str] = []
    for name in ("vevo2", "game", "diffsinger", "alignment"):
        marker = root / "external_backends" / name / "backend.json"
        parts.append(marker.read_text(encoding="utf-8") if marker.is_file() else f"{name}:missing")
    return "\n".join(parts)


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


def game_melody_for_text(text: str, duration: float, notes_file: Path) -> tuple[str, str, str]:
    """Map GAME's pitch contour to one DiffSinger note window per Chinese character."""
    clean = "".join(character for character in text if "\u4e00" <= character <= "\u9fff")
    if not clean:
        raise RuntimeError("DiffSinger fallback 当前只支持包含中文汉字的新歌词分段")
    events: list[tuple[float, float, str]] = []
    for line in notes_file.read_text(encoding="utf-8").splitlines():
        fields = line.strip().split("\t")
        if len(fields) != 3:
            continue
        match = re.match(r"^([A-G](?:#|b)?-?\d+)", fields[2])
        if not match:
            continue
        try:
            events.append((float(fields[0]), float(fields[1]), match.group(1)))
        except ValueError:
            continue
    if not events:
        raise RuntimeError(f"GAME 没有从 {notes_file.name} 提取到有效音符")
    window = max(0.05, duration / len(clean))
    pitches: list[str] = []
    for index in range(len(clean)):
        midpoint = (index + 0.5) * duration / len(clean)
        overlapping = [event for event in events if event[0] <= midpoint <= event[1]]
        chosen = min(overlapping or events, key=lambda event: abs((event[0] + event[1]) / 2 - midpoint))
        pitches.append(chosen[2])
    durations = [f"{window:.6f}" for _ in clean]
    return clean, " | ".join(pitches), " | ".join(durations)


class LyricCoverPipeline:
    """Experimental but real LRC/line-segmented Vevo2 → VC → mix pipeline."""

    def __init__(self, root: Path):
        self.root = root
        self.msst = MSSTAdapter(root / "external_backends" / "msst")
        self.vevo2 = Vevo2Adapter(root / "external_backends" / "vevo2")
        self.game = GameAdapter(root / "external_backends" / "game")
        self.diffsinger = DiffSingerLegacyAdapter(root / "external_backends" / "diffsinger")
        self.alignment = AlignmentAdapter(root / "external_backends" / "alignment")
        self.rvc = RVCAdapter(root / "external_backends" / "rvc")
        self.ddsp = DDSPAdapter(root / "external_backends" / "ddsp")

    def preflight(self, request: LyricCoverRequest) -> list[str]:
        issues: list[str] = []
        if request.generator not in {"auto", "vevo2", "diffsinger"}:
            issues.append(f"未知改词生成器：{request.generator}")
        if not request.input_path.is_file():
            issues.append("输入音频不存在")
        if not ffmpeg_path(self.root):
            issues.append("FFmpeg 未安装")
        status = self.msst.status()
        if not status.runnable:
            issues.append(status.detail)
        vevo_status = self.vevo2.status()
        fallback_statuses = (self.game.status(), self.diffsinger.status())
        fallback_ready = all(item.runnable for item in fallback_statuses)
        if request.generator == "vevo2" and not vevo_status.runnable:
            issues.append(vevo_status.detail)
        elif request.generator == "diffsinger" and not fallback_ready:
            issues.append("GAME + DiffSinger fallback 未同时就绪：" + "；".join(item.detail for item in fallback_statuses))
        elif request.generator == "auto" and not vevo_status.runnable and not fallback_ready:
            issues.append("Vevo2 不可用，且 GAME + DiffSinger fallback 未同时就绪：" + "；".join(
                [vevo_status.detail, *(item.detail for item in fallback_statuses)]
            ))
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

    def _diffsinger_runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "diffsinger_legacy_runtime.py",
            self.root / "_internal" / "workers" / "diffsinger_legacy_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "diffsinger_legacy_runtime.py",
        ]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _alignment_runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "alignment_runtime.py",
            self.root / "_internal" / "workers" / "alignment_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "alignment_runtime.py",
        ]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _align_plain_lyrics(
        self, vocals: Path, original: str, duration: float, job_dir: Path,
        report: Callable[[str, int, str], None],
    ) -> str:
        cues = parse_lyrics(original)
        if any(cue.start is not None for cue in cues):
            report("align_lyrics", 24, "已读取歌词时间戳")
            return original
        status = self.alignment.status()
        if not status.runnable:
            report("align_lyrics", 24, "自动对齐组件未就绪，使用逐行保守分段")
            return original
        vocal_stat = vocals.stat()
        marker = (self.root / "external_backends" / "alignment" / "backend.json").read_text(encoding="utf-8")
        key = _digest([str(vocals.resolve()), str(vocal_stat.st_size), str(vocal_stat.st_mtime_ns), original, marker])
        cached = self.root / "workspace" / "cache" / "lyric_alignment" / key / "alignment.json"
        if cached.is_file() and cached.stat().st_size > 32:
            report("align_lyrics", 24, "已复用 Whisper 歌词对齐缓存")
        else:
            report("align_lyrics", 22, "正在用 Whisper 将原歌词强制对齐到分离人声")
            request_file = job_dir / "alignment" / "request.json"
            result_file = job_dir / "alignment" / "alignment.json"
            request_file.parent.mkdir(parents=True, exist_ok=True)
            request_file.write_text(json.dumps({
                "root": str(self.root), "audio_path": str(vocals), "text": original,
                "language": lyrics_language(original), "output_path": str(result_file),
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                self.alignment.align(request_file, self._alignment_runner())
            except Exception as exc:
                raise RuntimeError(f"自动歌词对齐失败；请检查原歌词或改用 LRC：{exc}") from exc
            cached.parent.mkdir(parents=True, exist_ok=True)
            partial = cached.with_suffix(".json.part")
            shutil.copy2(result_file, partial); partial.replace(cached)
            report("align_lyrics", 24, "Whisper 原歌词强制对齐完成")
        try:
            data = json.loads(cached.read_text(encoding="utf-8"))
            return timed_lyrics_from_alignment(original, data, duration)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"自动歌词对齐结果无效；请改用 LRC：{exc}") from exc

    def _generate_diffsinger(
        self, manifest: list[dict[str, object]], segments: list[LyricSegment], segment_dir: Path,
        report: Callable[[str, int, str], None],
    ) -> None:
        notes_dir = segment_dir / "game_notes"
        report("generate", 44, "正在用 GAME 提取旋律")
        self.game.extract_notes(segment_dir, notes_dir)
        ds_segments: list[dict[str, object]] = []
        for index, (item, segment) in enumerate(zip(manifest, segments)):
            note_file = notes_dir / f"source_{index:03d}.txt"
            if not note_file.is_file():
                raise RuntimeError(f"GAME 缺少分段音符：{note_file.name}")
            text, notes, durations = game_melody_for_text(segment.new_text, segment.duration, note_file)
            ds_segments.append({"text": text, "notes": notes, "notes_duration": durations, "output": item["output"]})
        request_file = segment_dir / "diffsinger_request.json"
        request_file.write_text(json.dumps({
            "root": str(self.root), "experiment": "0831_opencpop_ds1000", "segments": ds_segments,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        report("generate", 48, f"DiffSinger 正在一次加载模型并生成 {len(ds_segments)} 个短句")
        self.diffsinger.generate_batch(request_file, self._diffsinger_runner())

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
        aligned_original = self._align_plain_lyrics(vocals, request.original_lyrics, duration, job_dir, report)
        segments = build_lyric_segments(aligned_original, request.new_lyrics, duration, request.strategy)

        source_stat = request.input_path.stat()
        marker = backend_markers(self.root)
        generation_key = _digest([
            str(request.input_path.resolve()), str(source_stat.st_size), str(source_stat.st_mtime_ns),
            request.original_lyrics, request.new_lyrics, request.strategy, request.generator, request.memory_profile, marker,
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
            flow_steps = {"极低": 16, "低": 24, "标准": 32, "高质量": 32}.get(request.memory_profile, 32)
            request_file.write_text(json.dumps({
                "root": str(self.root), "seed": 1234, "flow_matching_steps": flow_steps, "segments": manifest,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            vevo_error: Exception | None = None
            use_vevo = request.generator in {"auto", "vevo2"} and self.vevo2.status().runnable
            if use_vevo:
                report("generate", 40, f"Vevo2 正在一次加载模型并生成 {len(segments)} 个短句")
                try:
                    self.vevo2.generate_batch(request_file, self._runner())
                except Exception as exc:
                    vevo_error = exc
            fallback_ready = self.game.status().runnable and self.diffsinger.status().runnable
            use_fallback = request.generator == "diffsinger" or (
                request.generator == "auto" and (vevo_error is not None or not self.vevo2.status().runnable)
            )
            if use_fallback:
                if not fallback_ready:
                    raise RuntimeError(f"Vevo2 失败且 DiffSinger fallback 未就绪：{vevo_error or self.vevo2.status().detail}")
                if request.generator == "auto":
                    report("generate", 42, f"Vevo2 失败，自动切换 GAME + DiffSinger：{vevo_error or self.vevo2.status().detail}")
                else:
                    report("generate", 42, "已按任务参数选择 GAME + DiffSinger")
                self._generate_diffsinger(manifest, segments, segment_dir, report)
            elif vevo_error is not None:
                raise RuntimeError(f"Vevo2 生成失败：{vevo_error}") from vevo_error
            missing = [item["output"] for item in manifest if not Path(str(item["output"])).is_file()]
            if missing:
                raise RuntimeError(f"改词生成器缺少 {len(missing)} 个分段输出")
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
        conversion_key = _digest([generation_key, request.engine, request.voice.id, str(request.pitch), request.memory_profile, model_identity])
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
                converter = lambda source, target: self.rvc.convert(source, target, model, request.pitch, index)
            else:
                config = model_dir / request.voice.config_files[0] if request.voice.config_files else None
                converter = lambda source, target: self.ddsp.convert(source, target, model, request.pitch, config)
            convert_with_oom_retry(
                generated_vocal, converted_raw, converter, lambda message: report("convert", 76, message),
                chunk_sizes_for_profile(request.memory_profile),
            )
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
