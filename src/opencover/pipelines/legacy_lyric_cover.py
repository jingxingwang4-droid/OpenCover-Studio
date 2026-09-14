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

from opencover.adapters.backends import AceStepAdapter, AlignmentAdapter, DDSPAdapter, DiffSingerLegacyAdapter, EspnetVisinger2Adapter, GameAdapter, MSSTAdapter, RVCAdapter, SoulXSingerAdapter, UVR5Adapter, Vevo2Adapter
from opencover.audio.processing import compare_vocal_rhythm, export_audio, ffmpeg_path, fit_audio_duration, guard_lyric_accompaniment, mix_tracks, normalize_input, restore_vocal_detail, validate_audio
from opencover.core.retry_policy import chunk_sizes_for_profile, convert_with_oom_retry
from opencover.lyrics.midi import (
    MidiNote, load_midi, midi_identity, midi_notes_for_segments, select_midi_melody,
    trim_segments_to_midi_activity,
)
from opencover.lyrics.processing import (
    LyricSegment, build_lyric_segments, lyric_edit_count, lyrics_language, parse_lyrics,
    split_dense_rewrite_segment, split_lyric_segments, timed_lyrics_from_alignment,
)
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
    generator: str = "acestep"
    memory_profile: str = "标准"
    midi_path: Path | None = None
    soulx_prompt_metadata_path: Path | None = None
    soulx_target_metadata_path: Path | None = None
    auto_recognize_lyrics: bool = False


def _digest(parts: list[str]) -> str:
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def _file_sha256(path: Path | None) -> str:
    if path is None or not path.is_file():
        return "missing"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def backend_markers(root: Path, generator: str = "soulx") -> str:
    parts: list[str] = []
    names = ("ace_step", "alignment") if generator == "acestep" else ("soulx_singer", "alignment")
    for name in names:
        marker = root / "external_backends" / name / "backend.json"
        parts.append(marker.read_text(encoding="utf-8") if marker.is_file() else f"{name}:missing")
    return "\n".join(parts)


_TIMING_PREFIX = re.compile(
    r"^\s*(?:\[[0-9:.]+\s*(?:-->|-)\s*[0-9:.]+\]|\[[0-9:.]+\])\s*"
)


def ace_lyrics_text(value: str) -> str:
    """Remove LRC timing prefixes while retaining lyric lines and section tags."""
    lines = [_TIMING_PREFIX.sub("", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line).strip()


_ACE_SECTION_TAG = re.compile(
    r"^\[(?:intro|verse(?:\s+\d+)?|pre-chorus|chorus(?:\s+\d+)?|"
    r"bridge|interlude|instrumental|outro|hook|break|rap(?:\s+\d+)?)\]$",
    re.IGNORECASE,
)


def ace_flowedit_lyrics_pair(original: str, target: str) -> tuple[str, str]:
    """Give source and target the same English section-tag scaffold.

    The native Edit tutorial conditions both velocity branches with matching
    English section tags.  LRC timestamps are internal alignment data and are
    removed before the pair is sent to ACE-Step.
    """
    source_lines = ace_lyrics_text(original).splitlines()
    target_lines = ace_lyrics_text(target).splitlines()

    def split(lines: list[str]) -> tuple[list[str], list[tuple[int, str]]]:
        lyrics: list[str] = []
        tags: list[tuple[int, str]] = []
        for line in lines:
            if _ACE_SECTION_TAG.fullmatch(line):
                tags.append((len(lyrics), line))
            else:
                lyrics.append(line)
        return lyrics, tags

    source_words, source_tags = split(source_lines)
    target_words, target_tags = split(target_lines)
    template_tags = source_tags or target_tags or [(0, "[Verse]")]
    template_length = len(source_words) if source_tags else len(target_words)

    def apply(lines: list[str]) -> str:
        insertions: dict[int, list[str]] = {}
        for position, tag in template_tags:
            mapped = round(position * len(lines) / max(1, template_length))
            mapped = max(0, min(len(lines), mapped))
            insertions.setdefault(mapped, []).append(tag)
        output: list[str] = []
        for index in range(len(lines) + 1):
            output.extend(insertions.get(index, []))
            if index < len(lines):
                output.append(lines[index])
        return "\n".join(output).strip()

    return apply(source_words), apply(target_words)


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
            if end < start:
                return None
            for index, character in enumerate(characters):
                found.append(character)
                if end == start:
                    timings.append((start, end))
                else:
                    timings.append((
                        start + (end - start) * index / len(characters),
                        start + (end - start) * (index + 1) / len(characters),
                    ))
    if "".join(found) != expected:
        return None

    # Stable-Whisper can preserve the exact forced text yet collapse one short
    # character to a zero-width boundary. Repair only an isolated character by
    # redistributing it together with its valid neighbours. Multi-character or
    # edge collapses remain rejected because inventing those timings would be
    # unsafe for lyric-to-note mapping.
    repaired = list(timings)
    collapsed = [index for index, (start, end) in enumerate(repaired) if end <= start]
    if not collapsed:
        return repaired
    if any(
        (index > 0 and index - 1 in collapsed) or (index + 1 < len(repaired) and index + 1 in collapsed)
        for index in collapsed
    ):
        return None
    for index in collapsed:
        if index == 0 or index + 1 >= len(repaired):
            return None
        left_start, left_end = repaired[index - 1]
        boundary, _ = repaired[index]
        right_start, right_end = repaired[index + 1]
        if left_end < left_start or right_end <= right_start:
            return None
        if boundary < left_start or boundary > right_end:
            return None
        width = (right_end - left_start) / 3
        if width < 0.025:
            return None
        repaired[index - 1] = (left_start, left_start + width)
        repaired[index] = (left_start + width, left_start + 2 * width)
        repaired[index + 1] = (left_start + 2 * width, right_end)
    if any(end <= start for start, end in repaired):
        return None
    if any(repaired[index][0] < repaired[index - 1][1] - 1e-6 for index in range(1, len(repaired))):
        return None
    return repaired


def lyric_text_identity(text: str) -> str:
    """Normalize a segment for deciding whether synthesis is necessary."""
    return "".join(character.lower() for character in text if character.isalnum())


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
        # A lyric-heavy interval may have no true silence in its 20th
        # percentile. Treating that percentile as a noise floor previously
        # raised the gate above quieter trailing words and deleted them. Cap
        # the adaptive floor by the phrase-relative threshold so soft singing
        # remains active while genuine digital silence is still removed.
        threshold = max(
            10 ** (-52 / 20),
            min(noise_floor * 2.5, peak_rms * 0.04),
        )
        active = np.flatnonzero(rms >= threshold)
        if active.size == 0:
            trimmed.append(segment)
            continue
        maximum_gap_frames = max(1, round(2.0 * rate / hop))
        breaks = np.flatnonzero(np.diff(active) > maximum_gap_frames)
        if breaks.size:
            groups = np.split(active, breaks + 1)
            active = max(
                groups, key=lambda group: (len(group), float(rms[group].sum()), -int(group[0])),
            )
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
        self.soulx = SoulXSingerAdapter(root / "external_backends" / "soulx_singer")
        self.acestep = AceStepAdapter(root / "external_backends" / "ace_step")
        self.game = GameAdapter(root / "external_backends" / "game")
        self.visinger2 = EspnetVisinger2Adapter(root / "external_backends" / "espnet_visinger2")
        self.diffsinger = DiffSingerLegacyAdapter(root / "external_backends" / "diffsinger")
        self.alignment = AlignmentAdapter(root / "external_backends" / "alignment")
        self.rvc = RVCAdapter(root / "external_backends" / "rvc")
        self.ddsp = DDSPAdapter(root / "external_backends" / "ddsp")

    def preflight(self, request: LyricCoverRequest) -> list[str]:
        issues: list[str] = []
        if request.generator not in {"acestep", "soulx"}:
            issues.append("未知改词生成器；只允许 ACE-Step 或 SoulX-Singer")
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
        if request.generator == "acestep":
            ace_status = self.acestep.status()
            if not ace_status.runnable:
                issues.append(ace_status.detail)
            if not self._ace_step_runner().is_file():
                issues.append("ACE-Step 原生 EDIT/FlowEdit worker 缺失")
        elif request.generator == "soulx":
            soulx_status = self.soulx.status()
            if not soulx_status.runnable:
                issues.append(soulx_status.detail)
            if not self._soulx_score_runner().is_file():
                issues.append("SoulX 自动构谱 worker 缺失")
        alignment_status = self.alignment.status()
        has_timing = any(cue.start is not None for cue in parse_lyrics(request.original_lyrics))
        if not alignment_status.runnable and (request.generator == "soulx" or not has_timing):
            issues.append(("SoulX 改词需要逐字对齐组件：" if request.generator == "soulx" else "无时间戳歌词需要对齐组件：") + alignment_status.detail)
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
        if request.auto_recognize_lyrics:
            issues.append("请先在界面使用 VocalParse 识别并人工校对歌词，不能在生成阶段自动识别")
        if not request.original_lyrics.strip():
            issues.append("原歌词不能为空；请先自动识别并人工校对")
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

    def _soulx_runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "soulx_singer_batch_runtime.py",
            self.root / "_internal" / "workers" / "soulx_singer_batch_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "soulx_singer_batch_runtime.py",
        ]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _ace_step_runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "ace_step_runtime.py",
            self.root / "_internal" / "workers" / "ace_step_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "ace_step_runtime.py",
        ]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _soulx_score_runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "soulx_auto_score_runtime.py",
            self.root / "_internal" / "workers" / "soulx_auto_score_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "soulx_auto_score_runtime.py",
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
            game_source_dir = segment_dir / "game_sources"
            game_source_dir.mkdir(parents=True, exist_ok=True)
            for item in manifest:
                source = Path(str(item["input"]))
                target = game_source_dir / source.name
                if not target.is_file() or target.stat().st_size != source.stat().st_size:
                    shutil.copy2(source, target)
            notes_dir = segment_dir / "game_notes"
            expected_notes = [
                notes_dir / (Path(str(item["input"])).stem + ".txt")
                for item in manifest
            ]
            if not all(path.is_file() and path.stat().st_size > 0 for path in expected_notes):
                report("generate", 44, "正在用 GAME 提取旋律")
                self.game.extract_notes(game_source_dir, notes_dir)
            else:
                report("generate", 44, "已复用 GAME 原曲旋律与节奏")
            refined_notes_dir = segment_dir / "game_notes_refined"
            expected_refined = [refined_notes_dir / path.name for path in expected_notes]
            if not all(path.is_file() and path.stat().st_size > 0 for path in expected_refined):
                report("generate", 45, "正在用连续 F0 复核 GAME 音高和被合并的转音")
                self.game.refine_notes(
                    game_source_dir, notes_dir, refined_notes_dir, self._score_refiner_runner(),
                )
            notes_dir = refined_notes_dir
            for index, (item, segment) in enumerate(zip(manifest, segments)):
                note_file = notes_dir / (Path(str(item["input"])).stem + ".txt")
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

    def _refine_dense_rewrites(
        self,
        vocals: Path,
        segments: list[LyricSegment],
        job_dir: Path,
        report: Callable[[str, int, str], None],
    ) -> list[LyricSegment]:
        """Plan dense rewrites on exact original-singing character gaps."""
        dense = [
            (index, segment) for index, segment in enumerate(segments)
            if lyric_text_identity(segment.original_text) != lyric_text_identity(segment.new_text)
            and lyric_edit_count(segment.original_text, segment.new_text) > 2
        ]
        if not dense:
            return segments

        planning_dir = job_dir / "dense_rewrite_planning"
        manifest = self._extract_segments(vocals, [segment for _, segment in dense], planning_dir)
        request_file = planning_dir / "alignment_request.json"
        result_file = planning_dir / "alignment.json"
        request_file.write_text(json.dumps({
            "root": str(self.root),
            "output_path": str(result_file),
            "items": [
                {
                    "audio_path": str(item["input"]),
                    "text": segment.original_text,
                    "language": lyrics_language(segment.original_text),
                }
                for item, (_, segment) in zip(manifest, dense)
            ],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            report("score", 26, f"正在按原唱逐字边界细分 {len(dense)} 个高密度改词片段")
            self.alignment.align(request_file, self._alignment_runner())
            value = json.loads(result_file.read_text(encoding="utf-8"))
            aligned_items = value.get("items")
            if not isinstance(aligned_items, list) or len(aligned_items) != len(dense):
                raise RuntimeError("高密度改词对齐结果数量与分段不一致")
            replacements: dict[int, list[LyricSegment]] = {}
            for (original_index, segment), item in zip(dense, aligned_items):
                timing = character_timings_from_alignment(segment.original_text, item) if isinstance(item, dict) else None
                if timing is None:
                    raise RuntimeError(f"无法取得“{segment.original_text}”的完整逐字边界")
                replacements[original_index] = split_dense_rewrite_segment(segment, timing)
        except Exception as exc:
            raise RuntimeError(f"高密度改词智能切片失败，已停止生成含混咬字：{exc}") from exc

        planned: list[LyricSegment] = []
        for index, segment in enumerate(segments):
            planned.extend(replacements.get(index, [segment]))
        extra = len(planned) - len(segments)
        report("score", 28, f"已沿原唱字间隙增加 {extra} 个严格参考切片")
        return planned

    def _generate_soulx(
        self,
        manifest: list[dict[str, object]],
        segments: list[LyricSegment],
        segment_dir: Path,
        report: Callable[[str, int, str], None],
    ) -> None:
        if not manifest:
            return
        timings: list[list[tuple[float, float]] | tuple[tuple[float, float], ...] | None] = [
            segment.character_timings for segment in segments
        ]
        missing_positions = [index for index, timing in enumerate(timings) if timing is None]
        try:
            if missing_positions:
                alignment_request = segment_dir / "soulx_alignment_request.json"
                alignment_result = segment_dir / "soulx_alignment.json"
                alignment_request.write_text(json.dumps({
                    "root": str(self.root),
                    "output_path": str(alignment_result),
                    "items": [
                        {
                            "audio_path": str(manifest[index]["input"]),
                            "text": segments[index].original_text,
                            "language": lyrics_language(segments[index].original_text),
                        }
                        for index in missing_positions
                    ],
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                report("score", 32, f"正在将 {len(missing_positions)} 个原歌词片段逐字对齐到分离人声")
                self.alignment.align(alignment_request, self._alignment_runner())
                value = json.loads(alignment_result.read_text(encoding="utf-8"))
                aligned_items = value.get("items")
                if not isinstance(aligned_items, list) or len(aligned_items) != len(missing_positions):
                    raise RuntimeError("逐字对齐结果数量与待对齐改词短句不一致")
                for index, item in zip(missing_positions, aligned_items):
                    timings[index] = character_timings_from_alignment(
                        segments[index].original_text, item,
                    ) if isinstance(item, dict) else None
            missing = [
                segment.original_text for segment, timing in zip(segments, timings)
                if timing is None
            ]
            if missing:
                raise RuntimeError("以下原歌词无法取得完整逐字边界：" + "；".join(missing[:3]))
            reused = len(timings) - len(missing_positions)
            report("score", 36, f"逐字边界就绪（{reused} 句复用智能切片，{len(missing_positions)} 句现场对齐）")
        except Exception as exc:
            raise RuntimeError(f"SoulX 原唱逐字对齐失败，已停止生成错误咬字：{exc}") from exc

        metadata_dir = segment_dir / "soulx_auto_metadata"
        score_items: list[dict[str, object]] = []
        inference_items: list[dict[str, object]] = []
        for item, segment, character_timing in zip(manifest, segments, timings):
            stem = Path(str(item["output"])).stem
            prompt_metadata = metadata_dir / f"{stem}.prompt.json"
            target_metadata = metadata_dir / f"{stem}.target.json"
            score_items.append({
                "input": str(item["input"]),
                "original_text": segment.original_text,
                "new_text": segment.new_text,
                "character_timings": character_timing,
                "prompt_input": str(item.get("prompt_input") or item["input"]),
                "prompt_original_text": segment.prompt_text or segment.original_text,
                "prompt_character_timings": (
                    segment.prompt_character_timings or character_timing
                ),
                "prompt_metadata": str(prompt_metadata),
                "target_metadata": str(target_metadata),
            })
            inference_items.append({
                "prompt_audio": str(item.get("prompt_input") or item["input"]),
                "prompt_metadata": str(prompt_metadata),
                "target_metadata": str(target_metadata),
                "output": str(item["output"]),
            })
        score_request = segment_dir / "soulx_auto_score_request.json"
        score_request.write_text(json.dumps({
            "phone_set": str(self.soulx.repository / "soulxsinger" / "utils" / "phoneme" / "phone_set.json"),
            "diagnostics": str(metadata_dir / "diagnostics.json"),
            "items": score_items,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        report("score", 37, f"正在从原唱音高自动生成 {len(score_items)} 句 SoulX 词谱")
        self.soulx.prepare_score(
            score_request,
            self._soulx_score_runner(),
            lambda done, total: report("score", 37 + round(5 * done / max(1, total)), f"自动构谱（{done}/{total}）"),
        )
        request_file = segment_dir / "soulx_request.json"
        request_file.write_text(json.dumps({
            "backend_root": str(self.soulx.root),
            "segments": inference_items,
            "seed": 20260823,
            "n_steps": 32,
            "cfg": 3.0,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        report("generate", 42, f"SoulX-Singer 已一次加载模型，正在生成 {len(inference_items)} 个改词短句")
        self.soulx.generate(
            request_file,
            self._soulx_runner(),
            lambda done, total: report(
                "generate",
                42 + round(23 * done / max(1, total)),
                f"SoulX-Singer 正在生成（{done}/{total}）",
            ),
        )

    def _generate_acestep(
        self,
        request: LyricCoverRequest,
        output: Path,
        report: Callable[[str, int, str], None],
    ) -> Path:
        """Run the tutorial's native Analyze + EDIT/FlowEdit workflow."""
        ffmpeg = ffmpeg_path(self.root)
        assert ffmpeg is not None
        source = output.parent / "ace_source.wav"
        source.parent.mkdir(parents=True, exist_ok=True)
        normalize_input(request.input_path, source, ffmpeg)
        if lyric_edit_count(request.original_lyrics, request.new_lyrics) == 0:
            shutil.copy2(source, output)
            report("generate", 68, "歌词没有变化，已跳过 ACE-Step EDIT/FlowEdit")
            return output
        source_lyrics, target_lyrics = ace_flowedit_lyrics_pair(
            request.original_lyrics, request.new_lyrics,
        )
        request_file = output.parent / "ace_step_request.json"
        request_file.write_text(json.dumps({
            "backend_root": str(self.acestep.root),
            "source_root": str(self.acestep.source_root),
            "source_revision": self.acestep.flowedit_revision,
            "source_audio": str(source),
            "output_path": str(output),
            "model": "acestep-v15-turbo",
            "mode": "edit",
            "analyze_source": True,
            "analysis_path": str(output.parent / "ace_source_analysis.json"),
            "source_lyrics": source_lyrics,
            "lyrics": target_lyrics,
            "vocal_language": lyrics_language(request.new_lyrics),
            "seed": 20260831,
            "flow_edit_n_min": 0.6,
            "flow_edit_n_max": 1.0,
            "flow_edit_n_avg": 3,
            "audio_cover_strength": 0.5,
            "cover_noise_strength": 0.0,
            "method": {
                "model_task": "cover",
                "flow_edit_morph": True,
                "edit_preset": "only_lyrics",
                "source_metadata": "native_analyze_source_audio_0.6B_pt",
                "source_condition": "analyzed_caption_plus_original_tagged_lyrics",
                "target_condition": "same_analyzed_caption_plus_new_tagged_lyrics",
                "sample_rate": 48000,
                "inference_steps": 8,
                "shift": 3.0,
                "flow_edit_n_min": 0.6,
                "flow_edit_n_max": 1.0,
                "flow_edit_n_avg": 3,
                "audio_cover_strength": 0.5,
                "cover_noise_strength": 0.0,
                "enable_normalization": True,
                "normalization_db": -1.0,
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        report("generate", 31, "正在按原视频执行分析 + EDIT/FlowEdit 整首改词")
        self.acestep.generate(
            request_file,
            self._ace_step_runner(),
            lambda done, total: report(
                "generate", 31 + round(35 * done / max(1, total)),
                f"ACE-Step 原生 EDIT/FlowEdit 正在生成（{done}/{total}）",
            ),
        )
        _, _, source_duration = validate_audio(source)
        _, _, output_duration = validate_audio(output)
        if not 0.97 <= output_duration / source_duration <= 1.03:
            raise RuntimeError(
                f"ACE-Step 输出时长异常（{output_duration:.2f}s / 原曲 {source_duration:.2f}s）"
            )
        report("generate", 68, "ACE-Step 原生 EDIT/FlowEdit 整首生成完成")
        return output

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
        aligned_original = self._align_plain_lyrics(
            vocals, request.original_lyrics, duration, job_dir, report,
            auto_recognize=request.auto_recognize_lyrics,
        )
        segments = build_lyric_segments(
            aligned_original, request.new_lyrics, duration, request.strategy,
            split_phrases=False,
        )
        segments = trim_segments_to_vocal_activity(segments, vocals)
        segments = split_lyric_segments(segments)
        if request.generator == "soulx":
            segments = self._refine_dense_rewrites(vocals, segments, job_dir, report)
            report("score", 28, f"已自动规划 {len(segments)} 个严格参考原唱的演唱短句")
        else:
            report("score", 28, "已准备 EDIT/FlowEdit 成对原词/新词及相同英文标签")

        source_stat = request.input_path.stat()
        marker = backend_markers(self.root, request.generator)
        separation_identity = self.uvr5.pipeline_id if self.uvr5.status().runnable else "msst-mdx23c-v1"
        worker_identity = (
            "ace-worker:" + _file_sha256(self._ace_step_runner())
            if request.generator == "acestep"
            else "score-worker:" + _file_sha256(self._soulx_score_runner())
            + "\nsinger-worker:" + _file_sha256(self._soulx_runner())
        )
        generation_key = _digest([
            "lyric-generation-acestep-native-flowedit-only-lyrics-v3" if request.generator == "acestep" else "lyric-generation-soulx-auto-score-v12-full-parent-prompts",
            separation_identity,
            str(request.input_path.resolve()), str(source_stat.st_size), str(source_stat.st_mtime_ns),
            request.original_lyrics, str(request.auto_recognize_lyrics), aligned_original,
            request.new_lyrics, request.strategy, request.generator, request.memory_profile,
            worker_identity,
            marker,
        ])
        generation_cache = self.root / "workspace" / "cache" / "lyric_generation" / generation_key
        generated_vocal = generation_cache / "edited_vocal.wav"
        if generated_vocal.is_file() and generated_vocal.stat().st_size > 1024:
            report("generate", 68, "已复用改词歌声缓存")
        elif request.generator == "acestep":
            ace_mix = generation_cache / "ace_native_flowedit.wav"
            self._generate_acestep(request, ace_mix, report)
            report("separate_ace", 69, "正在从 ACE-Step 原生 EDIT 结果中提取新主唱")
            ace_request = replace(request, input_path=ace_mix)
            ace_vocals, _ = self._separate(
                ace_request,
                job_dir / "ace_native_flowedit_separation",
                lambda _stage, value, message: report(
                    "separate_ace", 69 + round(value * 0.04), "ACE-Step 结果：" + message,
                ),
            )
            generation_cache.mkdir(parents=True, exist_ok=True)
            partial = generated_vocal.with_suffix(".wav.part")
            shutil.copy2(ace_vocals, partial)
            partial.replace(generated_vocal)
            (generation_cache / "segments.json").write_text(
                json.dumps([segment.__dict__ for segment in segments], ensure_ascii=False, indent=2), encoding="utf-8",
            )
            report("separate_ace", 73, "ACE-Step 新主唱已提取，准备音色转换")
        else:
            # Keep valid partial segments in the generation cache so interrupted
            # long jobs can resume instead of starting every phrase over.
            segment_dir = generation_cache / "segments_work"
            report("segment", 30, f"正在准备 {len(segments)} 个短句")
            manifest = self._extract_segments(vocals, segments, segment_dir)
            generation_pairs = [
                (item, segment)
                for item, segment in zip(manifest, segments)
                if lyric_text_identity(segment.original_text) != lyric_text_identity(segment.new_text)
            ]
            generation_manifest = [item for item, _ in generation_pairs]
            generation_segments = [segment for _, segment in generation_pairs]
            for item, segment in zip(manifest, segments):
                if lyric_text_identity(segment.original_text) == lyric_text_identity(segment.new_text):
                    shutil.copy2(Path(str(item["input"])), Path(str(item["output"])))
            if generation_manifest:
                unchanged_count = len(segments) - len(generation_segments)
                report(
                    "generate", 31,
                    f"{unchanged_count} 个原词片段直接进入翻唱引擎，仅 {len(generation_segments)} 个改词片段调度 SoulX-Singer",
                )
                self._generate_soulx(generation_manifest, generation_segments, segment_dir, report)
                self._validate_score_generated_segments(generation_manifest, generation_segments, "SoulX-Singer")
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
                if request.generator == "acestep":
                    self.rvc.convert(
                        generated_vocal, converted_raw, model, request.pitch, index,
                        f0_method=request.voice.f0_method or "rmvpe",
                        index_rate=request.voice.index_rate if request.voice.index_rate is not None else 0.75,
                        protect=request.voice.protect if request.voice.protect is not None else 0.33,
                        rms_mix_rate=request.voice.rms_mix_rate if request.voice.rms_mix_rate is not None else 0.25,
                    )
                else:
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
