from __future__ import annotations
import re
from pathlib import Path
from dataclasses import replace
import numpy as np
import soundfile as sf
from opencover.lyrics.processing import LyricSegment
from opencover.lyrics.midi import MidiNote

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
    outer_only: bool = False,
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
        if breaks.size and not outer_only:
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
