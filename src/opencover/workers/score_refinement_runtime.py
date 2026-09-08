"""Refine coarse GAME notes against the source vocal's continuous F0."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


_NOTE_NAMES = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")


def mask_unreliable_f0(f0, probability, rms):
    """Quiet separator artifacts can have stable pitch without being singing."""
    threshold=max(1e-5,min(10**(-55/20),float(np.percentile(rms,95))*.01))
    return np.where((probability>=.5)&(rms>=threshold),f0,np.nan)


def midi_note_name(value: int) -> str:
    value = max(1, min(127, int(value)))
    return f"{_NOTE_NAMES[value % 12]}{value // 12 - 1}"


def _smooth_midi(values: np.ndarray, radius: int = 2) -> np.ndarray:
    result = values.astype(np.int16, copy=True)
    for index in range(len(values)):
        window = values[max(0, index - radius):min(len(values), index + radius + 1)]
        result[index] = int(round(float(np.median(window))))
    return result


def _stable_runs(
    frame_times: np.ndarray, midi_values: np.ndarray, start: float, end: float,
    *, minimum_run: float = 0.10,
) -> list[tuple[float, float, int]]:
    if not len(midi_values):
        return []
    smoothed = _smooth_midi(midi_values)
    changes = [0, *list(np.flatnonzero(smoothed[1:] != smoothed[:-1]) + 1), len(smoothed)]
    raw: list[tuple[float, float, int]] = []
    for left, right in zip(changes, changes[1:]):
        run_start = start if left == 0 else float((frame_times[left - 1] + frame_times[left]) / 2)
        run_end = end if right == len(smoothed) else float((frame_times[right - 1] + frame_times[right]) / 2)
        raw.append((max(start, run_start), min(end, run_end), int(round(float(np.median(smoothed[left:right]))))))

    # Short pitch flips are usually vibrato or consonant tracking errors. Merge
    # them into the longer neighbour instead of creating impossible score notes.
    runs = raw
    while len(runs) > 1:
        short_index = next((
            index for index, (run_start, run_end, _) in enumerate(runs)
            if run_end - run_start < minimum_run
        ), None)
        if short_index is None:
            break
        if short_index == 0:
            target = 1
        elif short_index == len(runs) - 1:
            target = short_index - 1
        else:
            left_duration = runs[short_index - 1][1] - runs[short_index - 1][0]
            right_duration = runs[short_index + 1][1] - runs[short_index + 1][0]
            target = short_index - 1 if left_duration >= right_duration else short_index + 1
        first, second = sorted((short_index, target))
        merged = (
            runs[first][0], runs[second][1],
            runs[target][2],
        )
        runs = runs[:first] + [merged] + runs[second + 1:]
    return runs


def refine_events(
    events: list[tuple[float, float, str]], times: np.ndarray, f0: np.ndarray,
) -> list[tuple[float, float, str]]:
    refined: list[tuple[float, float, str]] = []
    finite = np.isfinite(f0) & (f0 > 0)
    for start, end, original_note in events:
        selected = finite & (times >= start) & (times <= end)
        selected_times = times[selected]
        selected_f0 = f0[selected]
        if len(selected_f0) < 3:
            refined.append((start, end, original_note))
            continue
        midi = np.rint(69.0 + 12.0 * np.log2(selected_f0 / 440.0)).astype(np.int16)
        runs = _stable_runs(selected_times, midi, start, end)
        if not runs:
            refined.append((start, end, original_note))
            continue
        refined.extend((run_start, run_end, midi_note_name(value)) for run_start, run_end, value in runs)
    # GAME can omit a quiet pickup syllable entirely. Refining only its existing
    # notes can never recover that syllable. Recover sustained, voiced F0 runs
    # in uncovered gaps, leaving silence and short consonant tracks untouched.
    covered = np.zeros(len(times), dtype=bool)
    for start, end, _ in events:
        covered |= (times >= start) & (times <= end)
    missing = np.flatnonzero(finite & ~covered)
    hop = float(np.median(np.diff(times))) if len(times) > 1 else .01
    groups = np.split(missing, np.flatnonzero(np.diff(missing) > 1) + 1)
    for group in groups:
        if len(group) < 5:
            continue
        start, end = max(0.0, float(times[group[0]])-hop/2), float(times[group[-1]])+hop/2
        for left, right, _ in events:
            if right <= times[group[0]]:
                start = max(start, right)
            if left >= times[group[-1]]:
                end = min(end, left)
        if end-start < .065:
            continue
        midi = 69.0 + 12.0*np.log2(f0[group]/440.0)
        if float(np.percentile(midi, 90)-np.percentile(midi, 10)) > 1.5:
            continue
        refined.append((start, end, midi_note_name(int(round(float(np.median(midi)))))))
    return sorted(refined)


def _read_events(path: Path) -> list[tuple[float, float, str]]:
    events: list[tuple[float, float, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) >= 3:
            events.append((float(fields[0]), float(fields[1]), fields[2].split("+")[0]))
    return events


def main(request_file: str) -> int:
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    source_dir = Path(request["source_dir"])
    notes_dir = Path(request["notes_dir"])
    output_dir = Path(request["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    import librosa

    note_files = sorted(notes_dir.glob("source_*.txt"))
    if not note_files:
        raise RuntimeError("连续 F0 复核没有找到 GAME 音符")
    for note_file in note_files:
        audio_file = source_dir / f"{note_file.stem}.wav"
        audio, sample_rate = librosa.load(audio_file, sr=22050, mono=True)
        hop_length = 256
        f0, _, voiced_probability = librosa.pyin(
            audio, fmin=librosa.note_to_hz("C2"), fmax=librosa.note_to_hz("C7"),
            sr=sample_rate, frame_length=2048, hop_length=hop_length,
        )
        times = librosa.times_like(f0, sr=sample_rate, hop_length=hop_length)
        rms=librosa.feature.rms(y=audio,frame_length=2048,hop_length=hop_length)[0]
        f0 = mask_unreliable_f0(f0,voiced_probability,rms[:len(f0)])
        refined = refine_events(_read_events(note_file), times, f0)
        refined = [(a, min(b, len(audio)/sample_rate), note) for a,b,note in refined if a < len(audio)/sample_rate]
        if not refined:
            raise RuntimeError(f"连续 F0 复核没有为 {note_file.name} 产生音符")
        target = output_dir / note_file.name
        target.write_text("".join(
            f"{start:.3f}\t{end:.3f}\t{note}\n" for start, end, note in refined
        ), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
