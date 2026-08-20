from __future__ import annotations

import argparse
import math
from pathlib import Path

import librosa
import numpy as np


def parse_events(path: Path) -> list[tuple[float, float, str]]:
    events: list[tuple[float, float, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = line.split()
        if len(fields) == 3:
            events.append((float(fields[0]), float(fields[1]), fields[2]))
    return events


def note_hz(note: str) -> float:
    return float(librosa.midi_to_hz(librosa.note_to_midi(note)))


def analyze(audio_path: Path, events_path: Path, offset: float) -> None:
    audio, sample_rate = librosa.load(audio_path, sr=22050, mono=True)
    hop_length = 256
    f0, voiced, probability = librosa.pyin(
        audio,
        fmin=librosa.note_to_hz("C2"),
        fmax=librosa.note_to_hz("C7"),
        sr=sample_rate,
        frame_length=2048,
        hop_length=hop_length,
    )
    times = librosa.times_like(f0, sr=sample_rate, hop_length=hop_length)
    print(f"audio={audio_path} duration={len(audio) / sample_rate:.6f}s offset={offset:+.3f}s")
    absolute_errors: list[float] = []
    signed_errors: list[float] = []
    for index, (start, end, note) in enumerate(parse_events(events_path), 1):
        duration = end - start
        margin = min(0.04, duration * 0.2)
        selected = (
            (times >= start + offset + margin)
            & (times <= end + offset - margin)
            & voiced
            & np.isfinite(f0)
        )
        values = f0[selected]
        expected = note_hz(note)
        if values.size:
            cents = 1200.0 * np.log2(values / expected)
            median = float(np.median(cents))
            mad = float(np.median(np.abs(cents - median)))
            voiced_ratio = float(values.size / max(1, np.count_nonzero(
                (times >= start + offset + margin) & (times <= end + offset - margin)
            )))
            signed_errors.append(median)
            absolute_errors.append(abs(median))
            detected = librosa.hz_to_note(float(np.median(values)), cents=True)
            print(
                f"{index:02d} {start:.3f}-{end:.3f} {note:>3} "
                f"detected={detected:>8} error={median:+7.1f}c mad={mad:6.1f}c voiced={voiced_ratio:.2f}"
            )
        else:
            print(f"{index:02d} {start:.3f}-{end:.3f} {note:>3} detected=unvoiced")
    if absolute_errors:
        print(
            f"summary notes={len(absolute_errors)} "
            f"median_abs={np.median(absolute_errors):.1f}c "
            f"mean_abs={np.mean(absolute_errors):.1f}c "
            f"global_median={np.median(signed_errors):+.1f}c "
            f"within_50c={np.mean(np.asarray(absolute_errors) <= 50):.3f} "
            f"within_100c={np.mean(np.asarray(absolute_errors) <= 100):.3f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio", type=Path)
    parser.add_argument("events", type=Path)
    parser.add_argument("--offset", type=float, default=0.0)
    args = parser.parse_args()
    analyze(args.audio, args.events, args.offset)


if __name__ == "__main__":
    main()
