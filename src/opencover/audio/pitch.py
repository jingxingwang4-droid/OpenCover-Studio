from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import soundfile as sf


VoiceGender = Literal["auto", "male", "female", "unknown"]


@dataclass(frozen=True)
class PitchAnalysis:
    median_hz: float | None
    gender: Literal["male", "female", "unknown"]
    voiced_frames: int
    confidence: float


def analyze_vocal_pitch(path: Path, *, max_frames: int = 600) -> PitchAnalysis:
    """Estimate a singing voice's register without loading a model.

    This is deliberately a conservative classifier, not a note transcriber.  It
    uses normalized FFT autocorrelation and returns ``unknown`` when too little
    stable voiced material is available, so automatic mode never guesses from
    silence or accompaniment leakage.
    """
    audio, rate = sf.read(path, always_2d=True, dtype="float32")
    mono = audio.mean(axis=1)
    frame_size = max(1024, round(rate * 0.050))
    hop = max(1, round(rate * 0.025))
    if len(mono) < frame_size:
        return PitchAnalysis(None, "unknown", 0, 0.0)

    starts = np.arange(0, len(mono) - frame_size + 1, hop)
    if len(starts) > max_frames:
        starts = starts[np.linspace(0, len(starts) - 1, max_frames, dtype=int)]
    rms = np.asarray([
        np.sqrt(np.mean(np.square(mono[start:start + frame_size]), dtype=np.float64))
        for start in starts
    ])
    nonzero = rms[rms > 1e-5]
    if not len(nonzero):
        return PitchAnalysis(None, "unknown", 0, 0.0)
    energy_gate = max(1e-4, float(np.percentile(nonzero, 35)) * 0.45)

    min_lag = max(1, rate // 420)
    max_lag = min(frame_size - 2, rate // 55)
    window = np.hanning(frame_size).astype(np.float32)
    estimates: list[float] = []
    correlations: list[float] = []
    fft_size = 1 << (frame_size * 2 - 1).bit_length()
    for start, level in zip(starts, rms, strict=True):
        if level < energy_gate:
            continue
        frame = mono[start:start + frame_size]
        frame = (frame - float(frame.mean())) * window
        spectrum = np.fft.rfft(frame, fft_size)
        acf = np.fft.irfft(spectrum * np.conj(spectrum), fft_size)[:frame_size]
        if acf[0] <= 1e-9:
            continue
        search = acf[min_lag:max_lag + 1] / np.maximum(
            acf[0] * (frame_size - np.arange(min_lag, max_lag + 1)) / frame_size,
            1e-9,
        )
        peak_offset = int(np.argmax(search))
        correlation = float(search[peak_offset])
        if correlation < 0.48:
            continue
        lag = min_lag + peak_offset
        frequency = rate / lag
        if 55 <= frequency <= 420:
            estimates.append(frequency)
            correlations.append(min(1.0, correlation))

    if len(estimates) < 8:
        return PitchAnalysis(None, "unknown", len(estimates), 0.0)
    median = float(np.median(estimates))
    confidence = float(np.mean(correlations) * min(1.0, len(estimates) / 40.0))
    # The overlap is intentional: voices around this boundary are not forced an
    # octave in automatic mode.  The explicit GUI preset remains available.
    gender: Literal["male", "female", "unknown"]
    if median <= 180:
        gender = "male"
    elif median >= 200:
        gender = "female"
    else:
        gender = "unknown"
    return PitchAnalysis(median, gender, len(estimates), confidence)


def resolve_auto_pitch(
    base_pitch: int,
    source_gender: VoiceGender,
    target_gender: VoiceGender,
    analysis: PitchAnalysis | None = None,
) -> tuple[int, Literal["male", "female", "unknown"]]:
    detected: Literal["male", "female", "unknown"] = (
        analysis.gender if source_gender == "auto" and analysis is not None
        else source_gender if source_gender in {"male", "female"}
        else "unknown"
    )
    octave = 0
    if detected == "male" and target_gender == "female":
        octave = 12
    elif detected == "female" and target_gender == "male":
        octave = -12
    return max(-12, min(12, base_pitch + octave)), detected
