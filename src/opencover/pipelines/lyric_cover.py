from __future__ import annotations

import hashlib
import json
import shutil
import sys
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

import numpy as np
import soundfile as sf

from opencover.adapters.backends import AlignmentAdapter, DDSPAdapter, DiffSingerLegacyAdapter, EspnetVisinger2Adapter, GameAdapter, MSSTAdapter, RVCAdapter, UVR5Adapter, Vevo2Adapter
from opencover.audio.processing import compare_vocal_rhythm, export_audio, ffmpeg_path, fit_audio_duration, guard_lyric_accompaniment, mix_tracks, normalize_input, restore_vocal_detail, validate_audio
from opencover.core.retry_policy import chunk_sizes_for_profile, convert_with_oom_retry
from opencover.lyrics.midi import (
    MidiNote, load_midi, midi_identity, midi_notes_for_segments, select_midi_melody,
    trim_segments_to_midi_activity,
)
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
    midi_path: Path | None = None


def _digest(parts: list[str]) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def backend_markers(root: Path) -> str:
    parts: list[str] = []
    for name in ("espnet_visinger2", "vevo2", "game", "diffsinger", "alignment"):
        marker = root / "external_backends" / name / "backend.json"
        parts.append(marker.read_text(encoding="utf-8") if marker.is_file() else f"{name}:missing")
    return "\n".join(parts)


def select_initial_generator(
    requested: str, *, has_midi: bool, vevo_runnable: bool, fallback_runnable: bool,
    score_runnable: bool = False,
) -> str:
    """Choose the first real generator without silently downgrading quality."""
    if has_midi:
        if score_runnable:
            return "diffsinger"
        return "visinger2" if fallback_runnable else "unavailable"
    if requested == "diffsinger":
        if score_runnable:
            return "diffsinger"
        return "visinger2" if fallback_runnable else "unavailable"
    if requested == "auto" and score_runnable:
        return "diffsinger"
    if requested in {"auto", "vevo2"} and vevo_runnable:
        return "vevo2"
    if requested == "auto" and fallback_runnable:
        return "visinger2"
    return "unavailable"


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


def melody_for_text(text: str, duration: float, events: list[tuple[float, float, str]]) -> tuple[str, str, str]:
    """Map score notes to Chinese words while retaining phrase rests.

    GAME/MIDI events contain timing, not lyric alignment.  When there are more
    notes than characters they become melismas; when there are fewer notes, a
    note is divided between adjacent characters.  Crucially, note durations are
    never globally stretched to fill rests: DiffSinger receives explicit SP/AP
    rest windows instead.
    """
    clean, windows = melody_windows_for_text(text, duration, events)
    return _melody_from_windows(clean, duration, windows)


def _melody_from_windows(
    clean: str, duration: float, windows: list[list[tuple[float, float, str]]],
) -> tuple[str, str, str]:
    output_text: list[str] = []
    pitches: list[str] = []
    durations: list[str] = []
    previous_end = 0.0

    def append_rest(rest_duration: float) -> None:
        if rest_duration < 0.02:
            return
        output_text.append("AP" if rest_duration >= 0.45 else "SP")
        pitches.append("rest")
        durations.append(f"{rest_duration:.6f}")

    for character, window in zip(clean, windows):
        append_rest(max(0.0, window[0][0] - previous_end))
        output_text.append(character)
        pitches.append(" ".join(event[2] for event in window))
        durations.append(" ".join(f"{event[1] - event[0]:.6f}" for event in window))
        previous_end = window[-1][1]
    append_rest(max(0.0, duration - previous_end))
    return "".join(output_text), " | ".join(pitches), " | ".join(durations)


def melody_windows_for_text(
    text: str, duration: float, events: list[tuple[float, float, str]],
    character_timings: list[tuple[float, float]] | None = None,
) -> tuple[str, list[list[tuple[float, float, str]]]]:
    """Assign score notes by elapsed phrase time, not by raw note count.

    A syllable may cover several short transition notes while the next syllable
    covers one long note. Splitting note indices evenly gives consonants
    implausibly short windows and moves later lyrics onto the wrong pitches.
    Boundaries are therefore chosen near equal elapsed-time targets while
    retaining at least one note for every character.
    """
    clean = "".join(character for character in text if "\u4e00" <= character <= "\u9fff")
    if not clean:
        raise RuntimeError("DiffSinger fallback 当前只支持包含中文汉字的新歌词分段")
    if not events:
        raise RuntimeError("旋律中没有可用音符")

    ordered: list[tuple[float, float, str]] = []
    cursor = 0.0
    for raw_start, raw_end, note in sorted(events, key=lambda event: (event[0], event[1], event[2])):
        start = max(cursor, 0.0, min(duration, raw_start))
        end = max(start, min(duration, raw_end))
        if end - start < 0.02:
            continue
        ordered.append((start, end, note))
        cursor = end
    if not ordered:
        raise RuntimeError("旋律中没有时长足够的有效音符")

    character_count = len(clean)
    event_count = len(ordered)
    windows: list[list[tuple[float, float, str]]] = []
    if event_count >= character_count:
        boundaries = [0]
        active_start = ordered[0][0]
        active_span = ordered[-1][1] - active_start
        use_aligned_timings = character_timings is not None and len(character_timings) == character_count
        previous = 0
        for index in range(1, character_count):
            target = (
                float(character_timings[index - 1][1])
                if use_aligned_timings
                else active_start + active_span * index / character_count
            )
            remaining_characters = character_count - index
            first_cut = previous + 1
            last_cut = event_count - remaining_characters
            cut = min(
                range(first_cut, last_cut + 1),
                key=lambda candidate: (
                    round(
                        abs(ordered[candidate - 1][1] - target)
                        + max(0.0, 0.20 - (
                            ordered[candidate - 1][1] - ordered[previous][0]
                        )) * 2.0,
                        9,
                    ),
                    candidate,
                ),
            )
            boundaries.append(cut)
            previous = cut
        boundaries.append(event_count)
        windows = [
            ordered[boundaries[index]:boundaries[index + 1]]
            for index in range(character_count)
        ]
    else:
        assignments = [min(event_count - 1, index * event_count // character_count) for index in range(character_count)]
        counts = [assignments.count(index) for index in range(event_count)]
        offsets = [0] * event_count
        for index in range(character_count):
            event_index = assignments[index]
            start, end, note = ordered[event_index]
            part = offsets[event_index]
            part_count = counts[event_index]
            part_start = start + (end - start) * part / part_count
            part_end = start + (end - start) * (part + 1) / part_count
            offsets[event_index] += 1
            windows.append([(part_start, part_end, note)])

    return clean, windows


def character_timings_from_alignment(
    text: str, alignment: dict[str, object],
) -> list[tuple[float, float]] | None:
    """Read character windows from a forced-alignment result.

    Whisper occasionally groups multiple CJK characters into one word.  In
    that case its word interval is divided evenly so the result remains usable
    as a monotonic score boundary, but any character mismatch rejects the
    alignment instead of silently shifting lyrics.
    """
    expected = "".join(character for character in text if "\u4e00" <= character <= "\u9fff")
    segments = alignment.get("segments")
    if not expected or not isinstance(segments, list):
        return None
    found: list[str] = []
    timings: list[tuple[float, float]] = []
    for segment in segments:
        if not isinstance(segment, dict) or not isinstance(segment.get("words"), list):
            continue
        for word in segment["words"]:
            if not isinstance(word, dict):
                continue
            characters = [
                character for character in str(word.get("word", ""))
                if "\u4e00" <= character <= "\u9fff"
            ]
            if not characters:
                continue
            try:
                start, end = float(word["start"]), float(word["end"])
            except (KeyError, TypeError, ValueError):
                return None
            if end <= start:
                return None
            for index, character in enumerate(characters):
                found.append(character)
                timings.append((
                    start + (end - start) * index / len(characters),
                    start + (end - start) * (index + 1) / len(characters),
                ))
    return timings if "".join(found) == expected else None


def read_game_events(notes_file: Path) -> list[tuple[float, float, str]]:
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
    return events


def game_melody_for_text(
    text: str, duration: float, notes_file: Path,
    character_timings: list[tuple[float, float]] | None = None,
) -> tuple[str, str, str]:
    """Read GAME notes and retain all notes/melismas for DiffSinger."""
    events = read_game_events(notes_file)
    if not events:
        raise RuntimeError(f"GAME 没有从 {notes_file.name} 提取到有效音符")
    clean, windows = melody_windows_for_text(text, duration, events, character_timings)
    return _melody_from_windows(clean, duration, windows)


_NOTE_MIDI = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4,
              "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8, "Ab": 8,
              "A": 9, "A#": 10, "Bb": 10, "B": 11}
_MIDI_NOTE = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def midi_melody_for_text(text: str, duration: float, notes: list[MidiNote]) -> tuple[str, str, str]:
    return melody_for_text(text, duration, [
        (note.start, note.end, f"{_MIDI_NOTE[note.pitch % 12]}{note.pitch // 12 - 1}")
        for note in notes
    ])


def transpose_note_windows(notes: str, semitones: int) -> str:
    """Transpose DiffSinger note windows without changing window boundaries."""
    def transpose(token: str) -> str:
        match = re.fullmatch(r"([A-G](?:#|b)?)(-?\d+)", token)
        if not match:
            return token
        midi = _NOTE_MIDI[match.group(1)] + (int(match.group(2)) + 1) * 12 + semitones
        return f"{_MIDI_NOTE[midi % 12]}{midi // 12 - 1}"

    return " | ".join(
        " ".join(transpose(token) for token in window.strip().split())
        for window in notes.split("|")
    )


def diffsinger_octave_adaptation(note_windows: list[str]) -> int:
    """Choose one song-wide shift for the female OpenCpop fallback model."""
    midi_values: list[int] = []
    for notes in note_windows:
        for token in notes.replace("|", " ").split():
            match = re.fullmatch(r"([A-G](?:#|b)?)(-?\d+)", token)
            if match:
                midi_values.append(_NOTE_MIDI[match.group(1)] + (int(match.group(2)) + 1) * 12)
    # Notes below C3 are outside the reliable range observed for this fixed
    # OpenCpop female model.  Shift the entire song, never individual phrases.
    return 12 if midi_values and min(midi_values) < 48 else 0


def trim_segments_to_vocal_activity(
    segments: list[LyricSegment], vocals: Path, *, minimum_duration: float = 0.25,
) -> list[LyricSegment]:
    """Trim outer silence that an LRC line-start interval may contain.

    LRC timestamps describe starts, not ends.  The next timestamp can be many
    seconds away because of an instrumental break.  Feeding that whole interval
    to melody extraction makes the last detected pitch fill the gap.  This
    conservative energy gate removes only leading/trailing inactive audio and
    leaves internal pauses untouched.
    """
    audio, rate = sf.read(vocals, always_2d=True, dtype="float32")
    mono = audio.mean(axis=1)
    frame_size = max(1, round(rate * 0.020))
    hop = max(1, round(rate * 0.010))
    pad = round(rate * 0.080)
    trimmed: list[LyricSegment] = []
    for segment in segments:
        begin = max(0, min(len(mono), round(segment.start * rate)))
        end = max(begin + 1, min(len(mono), round(segment.end * rate)))
        values = mono[begin:end]
        if len(values) < frame_size:
            trimmed.append(segment)
            continue
        starts = np.arange(0, len(values) - frame_size + 1, hop)
        rms = np.asarray([
            float(np.sqrt(np.mean(np.square(values[start:start + frame_size]), dtype=np.float64)))
            for start in starts
        ])
        peak_rms = float(rms.max(initial=0.0))
        if peak_rms <= 1e-5:
            trimmed.append(segment)
            continue
        noise_floor = float(np.percentile(rms, 20))
        threshold = max(10 ** (-52 / 20), noise_floor * 2.5, peak_rms * 0.04)
        active = np.flatnonzero(rms >= threshold)
        if active.size == 0:
            trimmed.append(segment)
            continue
        local_begin = max(0, int(starts[int(active[0])]) - pad)
        local_end = min(len(values), int(starts[int(active[-1])]) + frame_size + pad)
        new_start = segment.start + local_begin / rate
        new_end = segment.start + local_end / rate
        if new_end - new_start < minimum_duration:
            trimmed.append(segment)
        else:
            trimmed.append(replace(segment, start=new_start, end=new_end))
    return trimmed


class LyricCoverPipeline:
    """Experimental but real LRC/line-segmented Vevo2 → VC → mix pipeline."""

    def __init__(self, root: Path):
        self.root = root
        self.msst = MSSTAdapter(root / "external_backends" / "msst")
        self.uvr5 = UVR5Adapter(
            root / "external_backends" / "uvr5",
            root / "ffmpeg" / "ffmpeg-9.0-essentials_build" / "bin",
        )
        self.vevo2 = Vevo2Adapter(root / "external_backends" / "vevo2")
        self.game = GameAdapter(root / "external_backends" / "game")
        self.visinger2 = EspnetVisinger2Adapter(root / "external_backends" / "espnet_visinger2")
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
        if request.engine not in {"rvc", "ddsp"} or request.voice.engine != request.engine:
            issues.append("音色引擎与任务引擎不匹配")
        if not request.voice.selectable or request.voice.quality_status == "rejected":
            issues.append("该音色已因真实歌曲验证质量不合格而停用")
        if not ffmpeg_path(self.root):
            issues.append("FFmpeg 未安装")
        if not self.uvr5.status().runnable and not self.msst.status().runnable:
            issues.append("UVR5 与 MSST 均不可用：" + self.uvr5.status().detail + "；" + self.msst.status().detail)
        vevo_status = self.vevo2.status()
        score_status = self.diffsinger.status()
        fallback_score_status = self.visinger2.status()
        game_status = self.game.status()
        fallback_ready = fallback_score_status.runnable and (
            request.midi_path is not None or game_status.runnable
        )
        score_ready = score_status.runnable and (request.midi_path is not None or game_status.runnable)
        midi_ready = request.midi_path is not None and (score_status.runnable or fallback_score_status.runnable)
        if request.midi_path is not None:
            try:
                load_midi(request.midi_path)
            except ValueError as exc:
                issues.append(f"MIDI 无效：{exc}")
            if request.generator == "vevo2":
                issues.append("上传 MIDI 后必须使用乐谱生成器，不能强制使用 Vevo2")
            if not midi_ready:
                issues.append("MIDI 乐谱演唱需要 legacy DiffSinger 或 VISinger2：" + score_status.detail)
        elif request.generator == "vevo2" and not vevo_status.runnable:
            issues.append(vevo_status.detail)
        elif request.generator == "diffsinger" and not score_ready and not fallback_ready:
            issues.append("GAME + legacy DiffSinger/VISinger2 均未就绪：" + "；".join(
                [game_status.detail, score_status.detail, fallback_score_status.detail]
            ))
        elif request.generator == "auto" and not score_ready and not vevo_status.runnable and not fallback_ready and not midi_ready:
            issues.append("legacy DiffSinger、Vevo2 与 VISinger2 均不可用：" + "；".join(
                [score_status.detail, vevo_status.detail, game_status.detail, fallback_score_status.detail]
            ))
        status = (self.rvc if request.engine == "rvc" else self.ddsp).status()
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
        use_uvr5 = self.uvr5.status().runnable
        separator_backend_id = self.uvr5.pipeline_id if use_uvr5 else "msst-mdx23c-v1"
        separator_id = f"{separator_backend_id}-lyric-accompaniment-guard-v1"
        checkpoint = self.root / "external_backends" / "msst" / "models" / "model_vocals_mdx23c_sdr_10.17.ckpt"
        artifacts = self.uvr5.model_paths if use_uvr5 else (checkpoint,)
        base_request = CoverRequest(request.input_path, request.engine, request.voice, request.pitch, request.balance)
        cache = self.root / "workspace" / "cache" / "separation" / separation_cache_key(base_request, artifacts, separator_id)
        vocals, accompaniment = cache / "vocals.wav", cache / "other.wav"
        if all(path.is_file() and path.stat().st_size > 1024 for path in (vocals, accompaniment)):
            report("normalize", 8, "已复用标准化缓存")
            guard_marker = cache / "accompaniment_guard.txt"
            if guard_marker.is_file() and guard_marker.read_text(encoding="utf-8").startswith("muted"):
                report("separate", 18, "已复用分轨缓存；输入接近清唱，未混入疑似原唱的伪伴奏轨")
            else:
                report("separate", 18, "已复用人声与伴奏缓存")
            return vocals, accompaniment
        ffmpeg = ffmpeg_path(self.root)
        assert ffmpeg is not None
        normalized_dir = job_dir / "normalized"
        report("normalize", 8, "正在标准化输入音频")
        normalize_input(request.input_path, normalized_dir / "input.wav", ffmpeg)
        separated = job_dir / "separation"
        report("separate", 18, "正在使用 UVR5 分离总人声、剔除和声并强去混响" if use_uvr5 else "正在使用 MSST 分离人声与伴奏")
        if use_uvr5:
            self.uvr5.separate(normalized_dir / "input.wav", separated)
        else:
            self.msst.separate(
                normalized_dir, separated, "mdx23c",
                self.root / "external_backends" / "msst" / "models" / "config_vocals_mdx23c.yaml",
                checkpoint,
            )
        source_vocals = next(separated.rglob("vocals.wav"), None)
        source_other = next(separated.rglob("other.wav"), None)
        if source_vocals is None or source_other is None:
            raise RuntimeError("MSST 未生成预期的 vocals.wav / other.wav")
        guarded_other = separated / "other_guarded.wav"
        guard = guard_lyric_accompaniment(
            normalized_dir / "input.wav", source_vocals, source_other, guarded_other,
        )
        if guard.muted:
            report(
                "separate", 18,
                f"检测到伴奏轨几乎是原唱复制（相关度 {guard.source_correlation:.3f}），已禁止混回成品",
            )
        else:
            report("separate", 18, "伴奏分轨已通过原唱回流检测")
        cache.mkdir(parents=True, exist_ok=True)
        for source, target in ((source_vocals, vocals), (guarded_other, accompaniment)):
            partial = target.with_suffix(".wav.part")
            shutil.copy2(source, partial)
            partial.replace(target)
        (cache / "accompaniment_guard.txt").write_text(
            ("muted" if guard.muted else "kept")
            + f"\nsource_correlation={guard.source_correlation:.9f}"
            + f"\nvocal_correlation={guard.vocal_correlation:.9f}"
            + f"\naccompaniment_source_ratio={guard.accompaniment_source_ratio:.9f}"
            + f"\nvocal_source_ratio={guard.vocal_source_ratio:.9f}\n",
            encoding="utf-8",
        )
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

    def _visinger2_runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "espnet_visinger2_runtime.py",
            self.root / "_internal" / "workers" / "espnet_visinger2_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "espnet_visinger2_runtime.py",
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
        report: Callable[[str, int, str], None], midi_path: Path | None = None,
        *, modern: bool = False,
    ) -> None:
        ds_segments: list[dict[str, object]] = []
        score_timings: list[list[tuple[float, float]] | None] = [None] * len(segments)
        if midi_path is None and self.alignment.status().runnable:
            report("generate", 42, "正在逐字对齐原唱，避免新歌词落到错误音符")
            request_file = segment_dir / "score_alignment_request.json"
            result_file = segment_dir / "score_alignment.json"
            request_file.write_text(json.dumps({
                "root": str(self.root),
                "output_path": str(result_file),
                "items": [
                    {
                        "audio_path": str(item["input"]),
                        "text": segment.original_text,
                        "language": lyrics_language(segment.original_text),
                    }
                    for item, segment in zip(manifest, segments)
                ],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                self.alignment.align(request_file, self._alignment_runner())
                alignment_data = json.loads(result_file.read_text(encoding="utf-8"))
                aligned_items = alignment_data.get("items")
                if not isinstance(aligned_items, list) or len(aligned_items) != len(segments):
                    raise RuntimeError("逐句对齐结果数量与歌词分段不一致")
                score_timings = [
                    character_timings_from_alignment(segment.original_text, item)
                    if isinstance(item, dict) else None
                    for segment, item in zip(segments, aligned_items)
                ]
                for segment, timing in zip(segments, score_timings):
                    original_count = sum("\u4e00" <= character <= "\u9fff" for character in segment.original_text)
                    replacement_count = sum("\u4e00" <= character <= "\u9fff" for character in segment.new_text)
                    if original_count == replacement_count and timing is None:
                        raise RuntimeError(f"无法取得“{segment.original_text}”的逐字边界")
                usable = sum(timing is not None for timing in score_timings)
                report("generate", 44, f"逐字对齐完成（{usable}/{len(segments)} 句可用于乐谱映射）")
            except Exception as exc:
                raise RuntimeError(f"原唱逐字对齐失败，已停止生成错误咬字：{exc}") from exc
        if midi_path is not None:
            report("generate", 43, "正在解析 MIDI 并与 LRC 时间轴对齐")
            midi = load_midi(midi_path)
            selection = select_midi_melody(midi, segments)
            segment_notes = midi_notes_for_segments(selection, segments)
            offset_text = f"，自动偏移 {selection.offset:+.2f}s" if abs(selection.offset) >= 0.01 else ""
            report("generate", 45, f"已选 MIDI {selection.part.label}{offset_text}，将按乐谱音高合成")
            for item, segment, notes_for_segment in zip(manifest, segments, segment_notes):
                text, notes, durations = midi_melody_for_text(segment.new_text, segment.duration, notes_for_segment)
                ds_segments.append({"text": text, "notes": notes, "notes_duration": durations, "output": item["output"]})
        else:
            notes_dir = segment_dir / "game_notes"
            expected_notes = [notes_dir / f"source_{index:03d}.txt" for index in range(len(manifest))]
            if not all(path.is_file() and path.stat().st_size > 0 for path in expected_notes):
                report("generate", 44, "正在用 GAME 提取旋律")
                self.game.extract_notes(segment_dir, notes_dir)
            else:
                report("generate", 44, "已复用 GAME 原曲旋律与节奏")
            refined_notes_dir = segment_dir / "game_notes_refined"
            expected_refined = [refined_notes_dir / path.name for path in expected_notes]
            if not all(path.is_file() and path.stat().st_size > 0 for path in expected_refined):
                report("generate", 45, "正在用连续 F0 复核 GAME 音高和被合并的转音")
                self.game.refine_notes(
                    segment_dir, notes_dir, refined_notes_dir, self._score_refiner_runner(),
                )
            notes_dir = refined_notes_dir
            for index, (item, segment) in enumerate(zip(manifest, segments)):
                note_file = notes_dir / f"source_{index:03d}.txt"
                if not note_file.is_file():
                    raise RuntimeError(f"GAME 缺少分段音符：{note_file.name}")
                timing = score_timings[index]
                original_count = sum("\u4e00" <= character <= "\u9fff" for character in segment.original_text)
                replacement_count = sum("\u4e00" <= character <= "\u9fff" for character in segment.new_text)
                if original_count != replacement_count:
                    timing = None
                text, notes, durations = game_melody_for_text(
                    segment.new_text, segment.duration, note_file, timing,
                )
                ds_segments.append({"text": text, "notes": notes, "notes_duration": durations, "output": item["output"]})
        synthesis_transpose = 0 if modern else diffsinger_octave_adaptation([str(item["notes"]) for item in ds_segments])
        if synthesis_transpose:
            report("generate", 46, "原曲包含低音区，正以统一舒适音域合成后无变速还原")
            for item in ds_segments:
                item["notes"] = transpose_note_windows(str(item["notes"]), synthesis_transpose)
                item["output_pitch_shift"] = -synthesis_transpose
        if modern:
            request_file = segment_dir / "visinger2_request.json"
            request_file.write_text(json.dumps({
                "root": str(self.root), "seed": 777, "singer_id": 8,
                "noise_scale": 0.35, "noise_scale_dur": 0.10,
                "segments": ds_segments,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            report("generate", 48, f"VISinger2 正在按乐谱生成 {len(ds_segments)} 个短句")
            self.visinger2.generate_batch(
                request_file, self._visinger2_runner(),
                lambda done, total: report(
                    "generate", 48 + round(17 * done / max(1, total)),
                    f"VISinger2 正在生成短句（{done}/{total}）",
                ),
            )
        else:
            request_file = segment_dir / "diffsinger_request.json"
            request_file.write_text(json.dumps({
                "root": str(self.root), "experiment": "0831_opencpop_ds1000",
                "pitch_control": "score", "segments": ds_segments,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            report("generate", 48, f"legacy DiffSinger 正在一次加载模型并生成 {len(ds_segments)} 个短句")
            self.diffsinger.generate_batch(
                request_file, self._diffsinger_runner(),
                lambda done, total: report(
                    "generate", 48 + round(17 * done / max(1, total)),
                    f"legacy DiffSinger 正在生成短句（{done}/{total}）",
                ),
            )

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
        ffmpeg = ffmpeg_path(self.root)
        if ffmpeg is None:
            raise RuntimeError("FFmpeg 未安装，无法执行保音高时长校正")
        fitted_dir = output.parent / "fitted_segments"
        for index, (item, segment) in enumerate(zip(manifest, segments)):
            fitted_path = fitted_dir / f"fitted_{index:03d}.wav"
            fit_audio_duration(Path(str(item["output"])), fitted_path, ffmpeg, segment.duration)
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
            fade = min(round(0.02 * rate), len(fitted) // 2)
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

    @staticmethod
    def _validate_generated_segments(manifest: list[dict[str, object]], segments: list[LyricSegment]) -> None:
        for item, segment in zip(manifest, segments):
            path = Path(str(item["output"]))
            try:
                info = sf.info(path)
            except (OSError, RuntimeError) as exc:
                raise RuntimeError(f"生成短句无法读取：{path.name}") from exc
            tempo = info.duration / segment.duration
            if info.frames < 1024 or not 0.80 <= tempo <= 1.25:
                raise RuntimeError(
                    f"生成短句时长异常（{info.duration:.1f}s / 目标 {segment.duration:.1f}s）：{segment.new_text[:18]}"
                )
            rhythm = compare_vocal_rhythm(Path(str(item["input"])), path)
            if rhythm.reliable and rhythm.score < 0.10:
                raise RuntimeError(
                    f"Vevo2 短句内部节奏与原曲偏差过大（节奏得分 {rhythm.score:.3f}）："
                    f"{segment.new_text[:18]}"
                )

    @staticmethod
    def _validate_score_generated_segments(
        manifest: list[dict[str, object]], segments: list[LyricSegment], generator: str,
    ) -> None:
        """Validate score-driven output without misreading changed phonemes as bad rhythm."""
        for item, segment in zip(manifest, segments):
            path = Path(str(item["output"]))
            try:
                info = sf.info(path)
            except (OSError, RuntimeError) as exc:
                raise RuntimeError(f"{generator} 生成短句无法读取：{path.name}") from exc
            ratio = info.duration / segment.duration
            if info.frames < 1024 or not 0.80 <= ratio <= 1.20:
                raise RuntimeError(
                    f"{generator} 生成时长异常（{info.duration:.2f}s / 乐谱 {segment.duration:.2f}s）："
                    f"{segment.new_text[:18]}"
                )

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
        # LRC timestamps describe starts, not ends.  Trim long instrumental
        # tails against whichever melody source is authoritative.
        if request.midi_path is not None:
            selection = select_midi_melody(load_midi(request.midi_path), segments)
            segments = trim_segments_to_midi_activity(selection, segments)
        else:
            segments = trim_segments_to_vocal_activity(segments, vocals)

        source_stat = request.input_path.stat()
        marker = backend_markers(self.root)
        midi_marker = midi_identity(request.midi_path) if request.midi_path is not None else "midi:none"
        separation_identity = self.uvr5.pipeline_id if self.uvr5.status().runnable else "msst-mdx23c-v1"
        generation_key = _digest([
            "lyric-generation-v22-f0-refined-diffsinger", separation_identity,
            str(request.input_path.resolve()), str(source_stat.st_size), str(source_stat.st_mtime_ns),
            request.original_lyrics, request.new_lyrics, request.strategy, request.generator, request.memory_profile,
            midi_marker, marker,
        ])
        generation_cache = self.root / "workspace" / "cache" / "lyric_generation" / generation_key
        generated_vocal = generation_cache / "edited_vocal.wav"
        if generated_vocal.is_file() and generated_vocal.stat().st_size > 1024:
            report("generate", 68, "已复用改词歌声缓存")
        else:
            # Keep valid partial segments in the generation cache so interrupted
            # long jobs can resume instead of starting every phrase over.
            segment_dir = generation_cache / "segments_work"
            report("segment", 30, f"正在准备 {len(segments)} 个短句")
            manifest = self._extract_segments(vocals, segments, segment_dir)
            flow_steps = {"极低": 16, "低": 24, "标准": 32, "高质量": 32}.get(request.memory_profile, 32)
            vevo_error: Exception | None = None
            fallback_ready = self.visinger2.status().runnable and (
                request.midi_path is not None or self.game.status().runnable
            )
            score_ready = self.diffsinger.status().runnable and (
                request.midi_path is not None or self.game.status().runnable
            )
            initial_generator = select_initial_generator(
                request.generator,
                has_midi=request.midi_path is not None,
                vevo_runnable=self.vevo2.status().runnable,
                fallback_runnable=fallback_ready,
                score_runnable=score_ready,
            )
            if initial_generator == "diffsinger":
                if request.midi_path is not None:
                    report("generate", 42, "已上传 MIDI，将使用 legacy DiffSinger 逐音符乐谱合成")
                else:
                    report("generate", 42, "正在使用逐字对齐 + GAME + legacy DiffSinger 保留原曲节奏与音高")
                self._generate_diffsinger(
                    manifest, segments, segment_dir, report, request.midi_path,
                )
                self._validate_score_generated_segments(manifest, segments, "legacy DiffSinger")
            elif initial_generator == "visinger2":
                report("generate", 42, "legacy DiffSinger 不可用，改用 GAME + VISinger2 乐谱合成")
                self._generate_diffsinger(
                    manifest, segments, segment_dir, report, request.midi_path, modern=True,
                )
                self._validate_score_generated_segments(manifest, segments, "VISinger2")
            use_vevo = initial_generator == "vevo2"
            if use_vevo:
                try:
                    request_file = segment_dir / "vevo2_request.json"
                    request_file.write_text(json.dumps({
                        "root": str(self.root), "seed": 1234, "flow_matching_steps": flow_steps,
                        "segments": manifest,
                    }, ensure_ascii=False, indent=2), encoding="utf-8")
                    report("generate", 40, f"Vevo2 正在一次加载模型并生成 {len(segments)} 个短句")
                    self.vevo2.generate_batch(
                        request_file, self._runner(),
                        lambda done, total: report(
                            "generate", 40 + round(25 * done / max(1, total)),
                            f"Vevo2 正在生成短句（{done}/{total}）",
                        ),
                    )
                    self._validate_generated_segments(manifest, segments)
                except Exception as exc:
                    vevo_error = exc
            use_fallback = (
                request.generator == "auto" and (vevo_error is not None or not self.vevo2.status().runnable)
                and initial_generator == "vevo2"
            )
            if use_fallback:
                fallback_backend = "diffsinger" if score_ready else "visinger2" if fallback_ready else ""
                if not fallback_backend:
                    raise RuntimeError(f"Vevo2 失败，且乐谱生成器未就绪：{vevo_error}")
                report(
                    "generate", 42,
                    f"Vevo2 失败，自动切换 {'legacy DiffSinger' if fallback_backend == 'diffsinger' else 'VISinger2'}：{vevo_error}",
                )
                if vevo_error is not None:
                    for item in manifest:
                        Path(str(item["output"])).unlink(missing_ok=True)
                self._generate_diffsinger(
                    manifest, segments, segment_dir, report, request.midi_path,
                    modern=fallback_backend == "visinger2",
                )
                self._validate_score_generated_segments(
                    manifest, segments,
                    "legacy DiffSinger" if fallback_backend == "diffsinger" else "VISinger2",
                )
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
        conversion_key = _digest([
            "vc8-rvc-segment-before-fit", generation_key, request.engine, request.voice.id, str(request.pitch),
            request.memory_profile, request.voice.inference_signature(), model_identity,
        ])
        final_key = _digest([
            "lyric-mix-original-vocal-guard-v1", conversion_key, request.balance, request.output_format,
        ])
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
                segment_sources = [
                    generation_cache / "segments_work" / f"generated_{item_index:03d}.wav"
                    for item_index in range(len(segments))
                ]
                missing_sources = [path for path in segment_sources if not path.is_file()]
                if missing_sources:
                    raise RuntimeError(f"RVC 分段转换缺少 {len(missing_sources)} 个生成短句")
                segment_dir = job_dir / "conversion" / "rvc_segments"
                converted_items = [
                    {
                        "input": str(source),
                        "output": str(segment_dir / f"converted_{item_index:03d}.wav"),
                    }
                    for item_index, source in enumerate(segment_sources)
                ]
                batch_request = job_dir / "conversion" / "rvc_batch_request.json"
                batch_request.parent.mkdir(parents=True, exist_ok=True)
                batch_request.write_text(json.dumps({
                    "model": str(model), "index": str(index) if index else "",
                    "pitch": request.pitch,
                    "f0_method": request.voice.f0_method or "rmvpe",
                    "index_rate": request.voice.index_rate if request.voice.index_rate is not None else 0.75,
                    "protect": request.voice.protect if request.voice.protect is not None else 0.33,
                    "rms_mix_rate": request.voice.rms_mix_rate if request.voice.rms_mix_rate is not None else 0.25,
                    "items": converted_items,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                self.rvc.convert_batch(
                    batch_request, self._rvc_batch_runner(),
                    lambda done, total: report(
                        "convert", 74 + round(8 * done / max(1, total)),
                        f"RVC 正在逐句转换并保留咬字（{done}/{total}）",
                    ),
                )
                self._stitch(converted_items, segments, duration, converted_raw)
            else:
                config = model_dir / request.voice.config_files[0] if request.voice.config_files else None
                converter = lambda source, target: self.ddsp.convert(
                    source, target, model, request.pitch, config,
                    f0_method=request.voice.f0_method or "rmvpe",
                    f0_min=request.voice.f0_min or 50,
                    f0_max=request.voice.f0_max or 1100,
                    threshold_db=request.voice.silence_threshold_db if request.voice.silence_threshold_db is not None else -60,
                )
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
        report("fit_duration", 84, "正在校正生成歌声时长并恢复咬字细节")
        restore_vocal_detail(
            converted_raw, generated_vocal, converted, ffmpeg,
            detail_mix=request.voice.source_detail_mix or 0.0,
            detail_cutoff_hz=request.voice.source_detail_cutoff_hz or 4000,
            treble_db=request.voice.converted_treble_db or 0.0,
            converted_gain=request.voice.converted_gain or 1.0,
        )
        mixed = job_dir / "mix" / "lyric_final.wav"
        report("mix", 92, "正在匹配响度并混合原伴奏")
        mix_tracks(converted, accompaniment, mixed, request.balance)
        report("export", 98, "正在导出改词结果")
        export_audio(mixed, output, ffmpeg)
        report("export", 100, "改词翻唱已完成")
        return output
