from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path

from opencover.lyrics.processing import LyricSegment


MAX_MIDI_BYTES = 10 * 1024 * 1024
MAX_MIDI_EVENTS = 1_000_000


@dataclass(frozen=True)
class MidiNote:
    start: float
    end: float
    pitch: int


@dataclass(frozen=True)
class MidiPart:
    track: int
    channel: int
    name: str
    notes: tuple[MidiNote, ...]

    @property
    def label(self) -> str:
        title = self.name.strip() or f"轨道 {self.track + 1}"
        return f"{title} / 通道 {self.channel + 1}"


@dataclass(frozen=True)
class MidiFile:
    format_type: int
    track_count: int
    duration: float
    parts: tuple[MidiPart, ...]
    note_count: int


@dataclass(frozen=True)
class MidiSelection:
    part: MidiPart
    offset: float
    notes: tuple[MidiNote, ...]


def _read_varlen(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if position >= len(data):
            raise ValueError("MIDI 事件在变长整数中间意外结束")
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, position
    raise ValueError("MIDI 变长整数超过 4 字节")


def _decode_name(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(encoding).strip("\x00 ")
        except UnicodeDecodeError:
            pass
    return ""


def load_midi(path: Path) -> MidiFile:
    """Read a standard MIDI file without requiring a system MIDI installation.

    Format 0/1, running status, multi-track tempo maps, and both PPQN and
    SMPTE time divisions are supported.  Format 2 is intentionally rejected:
    its tracks are independent songs and cannot share one lyric timeline.
    """
    if path.suffix.lower() not in {".mid", ".midi"}:
        raise ValueError("请选择 .mid 或 .midi 文件")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError(f"无法读取 MIDI 文件：{exc}") from exc
    if size < 14:
        raise ValueError("MIDI 文件过短或已损坏")
    if size > MAX_MIDI_BYTES:
        raise ValueError(f"MIDI 文件不能超过 {MAX_MIDI_BYTES // 1024 // 1024} MB")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"无法读取 MIDI 文件：{exc}") from exc
    if data[:4] != b"MThd":
        raise ValueError("文件不是标准 MIDI（缺少 MThd 文件头）")
    header_length = struct.unpack_from(">I", data, 4)[0]
    if header_length < 6 or 8 + header_length > len(data):
        raise ValueError("MIDI 文件头已损坏")
    format_type, declared_tracks, division = struct.unpack_from(">HHH", data, 8)
    if format_type not in {0, 1}:
        raise ValueError("MIDI format 2 包含多条独立时间线，请先导出为 format 0 或 1")
    if not 1 <= declared_tracks <= 256:
        raise ValueError("MIDI 轨道数无效或过多")
    if division == 0:
        raise ValueError("MIDI 时基无效")

    position = 8 + header_length
    raw_notes: list[tuple[int, int, int, int, int]] = []
    tempos: list[tuple[int, int, int]] = [(0, 500_000, -1)]
    track_names: dict[int, str] = {}
    maximum_tick = 0
    event_count = 0
    parsed_tracks = 0
    while parsed_tracks < declared_tracks:
        if position + 8 > len(data):
            raise ValueError("MIDI 轨道数与文件头声明不一致")
        chunk_type = data[position:position + 4]
        chunk_length = struct.unpack_from(">I", data, position + 4)[0]
        position += 8
        chunk_end = position + chunk_length
        if chunk_end > len(data):
            raise ValueError("MIDI 轨道数据被截断")
        if chunk_type != b"MTrk":
            position = chunk_end
            continue

        track_data = data[position:chunk_end]
        parsed_tracks += 1
        track_index = parsed_tracks - 1
        cursor = 0
        tick = 0
        running_status: int | None = None
        active: dict[tuple[int, int], list[int]] = {}
        while cursor < len(track_data):
            delta, cursor = _read_varlen(track_data, cursor)
            tick += delta
            maximum_tick = max(maximum_tick, tick)
            if cursor >= len(track_data):
                raise ValueError(f"MIDI 轨道 {track_index + 1} 事件被截断")
            first = track_data[cursor]
            if first & 0x80:
                status = first
                cursor += 1
                if status < 0xF0:
                    running_status = status
            elif running_status is not None:
                status = running_status
            else:
                raise ValueError(f"MIDI 轨道 {track_index + 1} 的 running status 无效")

            if status == 0xFF:
                running_status = None
                if cursor >= len(track_data):
                    raise ValueError("MIDI meta 事件被截断")
                meta_type = track_data[cursor]
                cursor += 1
                length, cursor = _read_varlen(track_data, cursor)
                end = cursor + length
                if end > len(track_data):
                    raise ValueError("MIDI meta 事件内容被截断")
                payload = track_data[cursor:end]
                cursor = end
                if meta_type == 0x03 and track_index not in track_names:
                    track_names[track_index] = _decode_name(payload)
                elif meta_type == 0x51 and length == 3:
                    tempo = int.from_bytes(payload, "big")
                    if tempo:
                        tempos.append((tick, tempo, track_index))
                elif meta_type == 0x2F:
                    break
                continue
            if status in {0xF0, 0xF7}:
                running_status = None
                length, cursor = _read_varlen(track_data, cursor)
                cursor += length
                if cursor > len(track_data):
                    raise ValueError("MIDI SysEx 事件被截断")
                continue
            if status >= 0xF0:
                raise ValueError(f"不支持的 MIDI 系统事件：0x{status:02X}")

            kind = status & 0xF0
            channel = status & 0x0F
            data_length = 1 if kind in {0xC0, 0xD0} else 2
            if cursor + data_length > len(track_data):
                raise ValueError(f"MIDI 轨道 {track_index + 1} 的通道事件被截断")
            first_data = track_data[cursor]
            second_data = track_data[cursor + 1] if data_length == 2 else 0
            if first_data & 0x80 or second_data & 0x80:
                raise ValueError(f"MIDI 轨道 {track_index + 1} 的数据字节无效")
            cursor += data_length
            event_count += 1
            if event_count > MAX_MIDI_EVENTS:
                raise ValueError("MIDI 事件数过多")
            if kind == 0x90 and second_data > 0:
                active.setdefault((channel, first_data), []).append(tick)
            elif kind == 0x80 or (kind == 0x90 and second_data == 0):
                starts = active.get((channel, first_data))
                if starts:
                    start_tick = starts.pop(0)
                    if tick > start_tick:
                        raw_notes.append((track_index, channel, start_tick, tick, first_data))
        position = chunk_end

    if parsed_tracks != declared_tracks:
        raise ValueError("MIDI 轨道数与文件头声明不一致")
    if not raw_notes:
        raise ValueError("MIDI 中没有可用的 Note On/Off 音符")

    if division & 0x8000:
        signed_fps = struct.unpack("b", bytes([(division >> 8) & 0xFF]))[0]
        ticks_per_frame = division & 0xFF
        fps = 29.97 if signed_fps == -29 else float(-signed_fps)
        if fps <= 0 or ticks_per_frame <= 0:
            raise ValueError("MIDI SMPTE 时基无效")
        tick_to_seconds = lambda value: value / (fps * ticks_per_frame)
    else:
        ticks_per_beat = division
        # Tempo events at the same tick use the event encountered last.
        tempo_by_tick: dict[int, tuple[int, int]] = {}
        for tick, tempo, order in tempos:
            tempo_by_tick[tick] = (tempo, order)
        ordered_tempos = sorted((tick, value[0]) for tick, value in tempo_by_tick.items())
        tempo_points: list[tuple[int, float, int]] = []
        last_tick = 0
        seconds = 0.0
        tempo = 500_000
        for tempo_tick, new_tempo in ordered_tempos:
            seconds += (tempo_tick - last_tick) * tempo / 1_000_000 / ticks_per_beat
            tempo_points.append((tempo_tick, seconds, new_tempo))
            last_tick = tempo_tick
            tempo = new_tempo

        def tick_to_seconds(value: int) -> float:
            point = tempo_points[0]
            for candidate in tempo_points[1:]:
                if candidate[0] > value:
                    break
                point = candidate
            return point[1] + (value - point[0]) * point[2] / 1_000_000 / ticks_per_beat

    grouped: dict[tuple[int, int], list[MidiNote]] = {}
    for track, channel, start, end, pitch in raw_notes:
        grouped.setdefault((track, channel), []).append(
            MidiNote(tick_to_seconds(start), tick_to_seconds(end), pitch)
        )
    parts = tuple(
        MidiPart(track, channel, track_names.get(track, ""), tuple(sorted(notes, key=lambda item: (item.start, item.end, item.pitch))))
        for (track, channel), notes in sorted(grouped.items())
    )
    duration = max((note.end for part in parts for note in part.notes), default=tick_to_seconds(maximum_tick))
    return MidiFile(format_type, declared_tracks, duration, parts, len(raw_notes))


def midi_identity(path: Path) -> str:
    midi = load_midi(path)
    stat = path.stat()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{digest}:{midi.note_count}"


def _interval_union_length(intervals: list[tuple[float, float]]) -> float:
    if not intervals:
        return 0.0
    total = 0.0
    start, end = sorted(intervals)[0]
    for next_start, next_end in sorted(intervals)[1:]:
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def _part_score(part: MidiPart, segments: list[LyricSegment], offset: float) -> float:
    shifted = [(note.start + offset, note.end + offset) for note in part.notes]
    covered = 0
    overlap_intervals: list[tuple[float, float]] = []
    for segment in segments:
        local: list[tuple[float, float]] = []
        for start, end in shifted:
            clipped = (max(start, segment.start), min(end, segment.end))
            if clipped[1] > clipped[0]:
                local.append(clipped)
        overlap = _interval_union_length(local)
        covered += int(overlap >= min(0.06, segment.duration * 0.1))
        overlap_intervals.extend(local)
    coverage = covered / max(1, len(segments))
    lyric_duration = sum(segment.duration for segment in segments)
    duration_coverage = _interval_union_length(overlap_intervals) / max(0.001, lyric_duration)
    total_note_duration = sum(max(0.0, end - start) for start, end in shifted)
    monophony = min(1.0, _interval_union_length(shifted) / max(0.001, total_note_duration))
    lowered = part.name.lower()
    name_bonus = 1.0 if any(word in lowered for word in ("melody", "vocal", "voice", "lead", "sing", "主旋律", "人声")) else 0.0
    sane_pitch = sum(36 <= note.pitch <= 96 for note in part.notes) / max(1, len(part.notes))
    return coverage * 8.0 + duration_coverage * 3.0 + monophony * 2.0 + name_bonus * 3.0 + sane_pitch


def _top_line(notes: tuple[MidiNote, ...]) -> tuple[MidiNote, ...]:
    """Reduce simultaneous chord tones to the highest melodic note."""
    if not notes:
        return notes
    total_duration = sum(max(0.0, note.end - note.start) for note in notes)
    monophony = _interval_union_length([(note.start, note.end) for note in notes]) / max(0.001, total_duration)
    if monophony >= 0.75:
        return notes
    onset_groups: list[list[MidiNote]] = []
    for note in notes:
        if onset_groups and abs(note.start - onset_groups[-1][0].start) <= 0.025:
            onset_groups[-1].append(note)
        else:
            onset_groups.append([note])
    selected = [max(group, key=lambda note: (note.pitch, note.end)) for group in onset_groups]
    result: list[MidiNote] = []
    for index, note in enumerate(selected):
        next_start = selected[index + 1].start if index + 1 < len(selected) else note.end
        end = min(note.end, next_start) if next_start > note.start else note.end
        result.append(MidiNote(note.start, max(note.start + 0.03, end), note.pitch))
    return tuple(result)


def select_midi_melody(midi: MidiFile, segments: list[LyricSegment]) -> MidiSelection:
    if not segments:
        raise ValueError("没有可用于 MIDI 对齐的歌词分段")
    non_drum = [part for part in midi.parts if part.channel != 9]
    if not non_drum:
        raise ValueError("MIDI 只有通道 10 的鼓组音符，没有可用的人声旋律")
    candidates = non_drum
    scored: list[tuple[float, int, float, MidiPart]] = []
    for part in candidates:
        offsets = {0.0, segments[0].start - part.notes[0].start}
        for offset in offsets:
            scored.append((_part_score(part, segments, offset), len(part.notes), -abs(offset), part))
    score, _, _, part = max(scored, key=lambda item: item[:3])
    # Recover the exact candidate offset; the tuple keeps -abs(offset) only for tie-breaking.
    offsets = {0.0, segments[0].start - part.notes[0].start}
    offset = max(offsets, key=lambda value: (_part_score(part, segments, value), -abs(value)))
    if score < 2.0:
        raise ValueError("MIDI 音符与 LRC/歌曲时间轴几乎没有重叠")
    shifted = tuple(
        MidiNote(note.start + offset, note.end + offset, note.pitch)
        for note in _top_line(part.notes)
    )
    return MidiSelection(part, offset, shifted)


def trim_segments_to_midi_activity(
    selection: MidiSelection, segments: list[LyricSegment], *, padding: float = 0.04,
) -> list[LyricSegment]:
    """Trim LRC line tails to the score instead of source-audio energy."""
    trimmed: list[LyricSegment] = []
    for segment in segments:
        overlapping = [
            note for note in selection.notes
            if note.end > segment.start and note.start < segment.end
        ]
        if not overlapping:
            trimmed.append(segment)
            continue
        start = max(segment.start, min(note.start for note in overlapping) - padding)
        end = min(segment.end, max(note.end for note in overlapping) + padding)
        trimmed.append(LyricSegment(start, end, segment.original_text, segment.new_text))
    return trimmed


def midi_notes_for_segments(selection: MidiSelection, segments: list[LyricSegment]) -> list[list[MidiNote]]:
    result: list[list[MidiNote]] = []
    missing: list[int] = []
    tolerance = 0.08
    for index, segment in enumerate(segments):
        notes: list[MidiNote] = []
        for note in selection.notes:
            start = max(segment.start, note.start)
            end = min(segment.end, note.end)
            if end > start:
                notes.append(MidiNote(start - segment.start, end - segment.start, note.pitch))
        if not notes:
            nearest = min(
                selection.notes,
                key=lambda note: min(abs(note.end - segment.start), abs(note.start - segment.end)),
            )
            distance = min(abs(nearest.end - segment.start), abs(nearest.start - segment.end))
            if distance <= tolerance:
                center = min(segment.duration, max(0.0, (nearest.start + nearest.end) / 2 - segment.start))
                notes.append(MidiNote(max(0.0, center - 0.03), min(segment.duration, center + 0.03), nearest.pitch))
        if not notes:
            missing.append(index + 1)
        result.append(notes)
    if missing:
        shown = "、".join(str(index) for index in missing[:8])
        suffix = "等" if len(missing) > 8 else ""
        raise ValueError(f"MIDI 在第 {shown} {suffix}句歌词时段内没有音符，请检查 LRC 时间戳或 MIDI 起始位置")
    return result
