from __future__ import annotations

import struct
from pathlib import Path

import pytest

from opencover.lyrics.midi import (
    load_midi, midi_notes_for_segments, select_midi_melody, trim_segments_to_midi_activity,
)
from opencover.lyrics.processing import LyricSegment
from opencover.core.job_manager import snapshot_lyric_midi
from opencover.pipelines.lyric_cover import midi_melody_for_text


def _vlq(value: int) -> bytes:
    encoded = [value & 0x7F]
    value >>= 7
    while value:
        encoded.append(0x80 | (value & 0x7F))
        value >>= 7
    return bytes(reversed(encoded))


def _track(*events: tuple[int, bytes]) -> bytes:
    payload = b"".join(_vlq(delta) + event for delta, event in events) + b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(payload)) + payload


def _midi(*tracks: bytes, format_type: int = 1, division: int = 480) -> bytes:
    return b"MThd" + struct.pack(">IHHH", 6, format_type, len(tracks), division) + b"".join(tracks)


def test_load_midi_supports_tempo_changes_track_names_and_running_status(tmp_path: Path) -> None:
    tempo = _track(
        (0, b"\xff\x51\x03\x07\xa1\x20"),  # 120 BPM
        (480, b"\xff\x51\x03\x0f\x42\x40"),  # 60 BPM
    )
    melody = _track(
        (0, b"\xff\x03\x06Melody"),
        (0, b"\x90\x3c\x64"),
        (480, b"\x3c\x00"),  # running-status Note On with velocity zero
        (0, b"\x3e\x64"),
        (480, b"\x3e\x00"),
    )
    path = tmp_path / "tempo.mid"
    path.write_bytes(_midi(tempo, melody))

    parsed = load_midi(path)
    assert parsed.format_type == 1
    assert parsed.track_count == 2
    assert parsed.note_count == 2
    assert parsed.parts[0].label == "Melody / 通道 1"
    assert parsed.parts[0].notes[0].start == pytest.approx(0.0)
    assert parsed.parts[0].notes[0].end == pytest.approx(0.5)
    assert parsed.parts[0].notes[1].end == pytest.approx(1.5)


def test_select_melody_ignores_drums_and_prefers_named_monophonic_track(tmp_path: Path) -> None:
    drums = _track((0, b"\x99\x24\x64"), (960, b"\x89\x24\x00"))
    chords = _track(
        (0, b"\xff\x03\x06Chords"),
        (0, b"\x90\x30\x64"), (0, b"\x34\x64"), (0, b"\x37\x64"),
        (960, b"\x80\x30\x00"), (0, b"\x34\x00"), (0, b"\x37\x00"),
    )
    melody = _track(
        (0, b"\xff\x03\x05Vocal"),
        (0, b"\x91\x3c\x64"), (480, b"\x81\x3c\x00"),
        (0, b"\x91\x3e\x64"), (480, b"\x81\x3e\x00"),
    )
    path = tmp_path / "multitrack.mid"
    path.write_bytes(_midi(drums, chords, melody))
    segments = [LyricSegment(2.0, 2.5, "原", "春"), LyricSegment(2.5, 3.0, "词", "日")]

    selection = select_midi_melody(load_midi(path), segments)
    assert selection.part.name == "Vocal"
    assert selection.part.channel == 1
    assert selection.offset == pytest.approx(2.0)
    note_groups = midi_notes_for_segments(selection, segments)
    assert [[note.pitch for note in notes] for notes in note_groups] == [[60], [62]]


def test_midi_notes_become_diffsinger_score_windows(tmp_path: Path) -> None:
    melody = _track(
        (0, b"\x90\x3c\x64"), (240, b"\x80\x3c\x00"),
        (0, b"\x90\x3e\x64"), (240, b"\x80\x3e\x00"),
        (0, b"\x90\x40\x64"), (480, b"\x80\x40\x00"),
    )
    path = tmp_path / "score.midi"
    path.write_bytes(_midi(melody, format_type=0))
    segment = LyricSegment(0.0, 1.0, "原词", "春日")
    notes = midi_notes_for_segments(select_midi_melody(load_midi(path), [segment]), [segment])[0]

    text, pitches, durations = midi_melody_for_text("春日", 1.0, notes)
    assert text == "春日"
    assert pitches == "C4 D4 | E4"
    assert sum(float(value) for value in durations.replace("|", " ").split()) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("bad.mid", b"not a midi file", "标准 MIDI"),
        ("score.txt", b"not a midi file", ".mid"),
        ("format2.mid", _midi(_track(), format_type=2), "format 2"),
    ],
)
def test_invalid_midi_is_rejected_with_actionable_message(
    tmp_path: Path, name: str, content: bytes, message: str,
) -> None:
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(ValueError, match=message):
        load_midi(path)


def test_missing_lyric_window_reports_line_number(tmp_path: Path) -> None:
    melody = _track((0, b"\x90\x3c\x64"), (480, b"\x80\x3c\x00"))
    path = tmp_path / "short.mid"
    path.write_bytes(_midi(melody, format_type=0))
    segments = [LyricSegment(0.0, 0.5, "原", "春"), LyricSegment(2.0, 2.5, "词", "日")]
    selection = select_midi_melody(load_midi(path), segments)
    with pytest.raises(ValueError, match="第 2"):
        midi_notes_for_segments(selection, segments)


def test_uploaded_midi_is_snapshotted_into_job_directory(tmp_path: Path) -> None:
    melody = _track((0, b"\x90\x3c\x64"), (480, b"\x80\x3c\x00"))
    source = tmp_path / "用户旋律.mid"
    source.write_bytes(_midi(melody, format_type=0))
    job_dir = tmp_path / "job"; job_dir.mkdir()
    record = {"kind": "lyric", "options": {"midi_path": str(source)}}

    copied = snapshot_lyric_midi(record, job_dir)
    options = copied["options"]
    assert isinstance(options, dict)
    assert options["midi_original_name"] == source.name
    snapshot = Path(str(options["midi_path"]))
    assert snapshot == job_dir / "melody.mid"
    assert snapshot.read_bytes() == source.read_bytes()
    source.unlink()
    assert load_midi(snapshot).note_count == 1


def test_lrc_instrumental_tail_is_trimmed_to_midi_activity(tmp_path: Path) -> None:
    melody = _track(
        (960, b"\x90\x3c\x64"),  # begins at 1.0 s
        (960, b"\x80\x3c\x00"),  # ends at 2.0 s
    )
    path = tmp_path / "tail.mid"
    path.write_bytes(_midi(melody, format_type=0))
    segments = [LyricSegment(0.0, 6.0, "原词", "春日")]
    selection = select_midi_melody(load_midi(path), segments)
    trimmed = trim_segments_to_midi_activity(selection, segments)
    assert trimmed[0].start == pytest.approx(0.96)
    assert trimmed[0].end == pytest.approx(2.04)
