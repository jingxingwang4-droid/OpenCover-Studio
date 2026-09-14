from __future__ import annotations
import sys, json, shutil, hashlib
from pathlib import Path
from typing import Callable
import numpy as np
import soundfile as sf
from opencover.lyrics.processing import LyricSegment, parse_lyrics, lyrics_language, timed_lyrics_from_alignment
from opencover.lyrics.score import _resample
from opencover.audio.processing import ffmpeg_path, normalize_input, validate_audio

def _digest(parts):
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()

class LyricSupport:
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

    def _score_refiner_runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "score_refinement_runtime.py",
            self.root / "_internal" / "workers" / "score_refinement_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "score_refinement_runtime.py",
        ]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _rvc_batch_runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "rvc_batch_runtime.py",
            self.root / "_internal" / "workers" / "rvc_batch_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "rvc_batch_runtime.py",
        ]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _align_plain_lyrics(
        self, vocals: Path, original: str, duration: float, job_dir: Path,
        report: Callable[[str, int, str], None], *, auto_recognize: bool = False,
    ) -> str:
        if auto_recognize:
            raise RuntimeError("请先使用 VocalParse 识别并人工校对歌词")
        cues = parse_lyrics(original)
        if any(cue.start is not None for cue in cues):
            report("align_lyrics", 24, "已读取歌词时间戳")
            return original
        status = self.alignment.status()
        if not status.runnable:
            raise RuntimeError("自动对齐组件未就绪，不能按字数猜测原唱时间")
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
            prompt_input: Path | None = None
            if segment.prompt_start is not None and segment.prompt_end is not None:
                prompt_begin = max(0, min(len(mono), round(segment.prompt_start * rate)))
                prompt_end = max(prompt_begin + 1, min(len(mono), round(segment.prompt_end * rate)))
                prompt_values = mono[prompt_begin:prompt_end]
                prompt_input = target / f"prompt_{index:03d}.wav"
                sf.write(
                    prompt_input, _resample(prompt_values, round(len(prompt_values) * 24000 / rate)),
                    24000, subtype="PCM_16",
                )
            manifest.append({
                "input": str(input_path),
                "output": str(output_path),
                "text": segment.new_text,
                "original_text": segment.original_text,
                "duration": segment.duration,
                **({"prompt_input": str(prompt_input)} if prompt_input is not None else {}),
            })
        return manifest

    def _stitch(self, manifest: list[dict[str, object]], segments: list[LyricSegment], duration: float, output: Path) -> Path:
        rate = 44100
        canvas = np.zeros(round(duration * rate), dtype=np.float32)
        ffmpeg = ffmpeg_path(self.root)
        if ffmpeg is None:
            raise RuntimeError("FFmpeg 未安装，无法执行保音高时长校正")
        fitted_dir = output.parent / "fitted_segments"
        for index, (item, segment) in enumerate(zip(manifest, segments)):
            fitted_path = fitted_dir / f"fitted_{index:03d}.wav"
            normalize_input(Path(str(item["output"])), fitted_path, ffmpeg)
            generated, generated_rate = sf.read(fitted_path, always_2d=True, dtype="float32")
            mono = generated.mean(axis=1)
            begin = max(0, round(segment.start * rate))
            end = min(len(canvas), round(segment.end * rate))
            target_frames = max(1, end - begin)
            if generated_rate != rate:
                raise RuntimeError("生成短句校时后采样率不是 44.1 kHz")
            if len(mono) < target_frames:
                fitted = np.pad(mono, (0, target_frames - len(mono)))
            else:
                fitted = mono[:target_frames]
            fade = min(round(0.005 * rate), len(fitted) // 2)
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
