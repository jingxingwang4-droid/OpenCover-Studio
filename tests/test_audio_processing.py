from pathlib import Path
import warnings

import numpy as np
import soundfile as sf

import pytest

from opencover.audio.processing import AudioError, compare_vocal_rhythm, ffmpeg_path, fit_audio_duration, guard_lyric_accompaniment, mix_tracks, validate_audio
from opencover.audio.pitch import analyze_vocal_pitch


def test_mix_tracks_creates_real_non_silent_wav(tmp_path: Path) -> None:
    sr = 16000; t = np.arange(sr, dtype=np.float32) / sr
    vocal = 0.1 * np.sin(2 * np.pi * 220 * t)
    backing = 0.1 * np.sin(2 * np.pi * 110 * t)
    vocal_path = tmp_path / "vocal.wav"; backing_path = tmp_path / "backing.wav"; output = tmp_path / "mix.wav"
    sf.write(vocal_path, vocal, sr); sf.write(backing_path, backing, sr)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        mix_tracks(vocal_path, backing_path, output)
    assert not [item for item in caught if "clipped" in str(item.message).casefold()]
    _, _, duration = validate_audio(output)
    data, _ = sf.read(output)
    assert duration == 1.0
    assert float(np.max(np.abs(data))) > 0.01


def test_pitch_analysis_classifies_low_and_high_singing_registers(tmp_path: Path) -> None:
    sr = 16000
    time = np.arange(sr * 2, dtype=np.float32) / sr
    low = tmp_path / "low.wav"; high = tmp_path / "high.wav"
    sf.write(low, 0.2 * np.sin(2 * np.pi * 110 * time), sr)
    sf.write(high, 0.2 * np.sin(2 * np.pi * 220 * time), sr)
    assert analyze_vocal_pitch(low).gender == "male"
    assert analyze_vocal_pitch(high).gender == "female"


def test_duration_fit_preserves_pitch_and_rejects_destructive_stretch(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    ffmpeg = ffmpeg_path(project_root)
    if ffmpeg is None:
        pytest.skip("project FFmpeg is not installed")
    rate = 24000
    time = np.arange(rate, dtype=np.float32) / rate
    source = tmp_path / "tone.wav"
    fitted = tmp_path / "fitted.wav"
    sf.write(source, 0.2 * np.sin(2 * np.pi * 440 * time), rate)

    fit_audio_duration(source, fitted, ffmpeg, 1.2)
    audio, output_rate = sf.read(fitted, dtype="float32")
    center = audio[output_rate // 10:-output_rate // 10]
    frequencies = np.fft.rfftfreq(len(center), 1 / output_rate)
    peak_hz = float(frequencies[np.argmax(np.abs(np.fft.rfft(center)))])
    assert abs(peak_hz - 440.0) < 3.0
    assert sf.info(fitted).duration == pytest.approx(1.2, abs=0.01)

    with pytest.raises(AudioError, match="相差过大"):
        fit_audio_duration(source, tmp_path / "bad.wav", ffmpeg, 2.0)


def test_accompaniment_guard_mutes_scaled_copy_of_dry_vocal(tmp_path: Path) -> None:
    rate = 16000
    time = np.arange(rate * 2, dtype=np.float32) / rate
    dry_vocal = (0.2 + 0.1 * np.sin(2 * np.pi * 2 * time)) * np.sin(2 * np.pi * 220 * time)
    source = tmp_path / "source.wav"
    vocal = tmp_path / "vocal.wav"
    false_accompaniment = tmp_path / "false_accompaniment.wav"
    guarded = tmp_path / "guarded.wav"
    sf.write(source, dry_vocal, rate)
    sf.write(vocal, dry_vocal * 0.6, rate)
    sf.write(false_accompaniment, dry_vocal * 0.3, rate)

    result = guard_lyric_accompaniment(source, vocal, false_accompaniment, guarded)

    output, _ = sf.read(guarded, dtype="float32")
    assert result.muted is True
    assert result.source_correlation > 0.999
    assert float(np.max(np.abs(output))) == 0.0


def test_accompaniment_guard_preserves_real_instrumental(tmp_path: Path) -> None:
    rate = 16000
    time = np.arange(rate * 2, dtype=np.float32) / rate
    vocal_audio = 0.15 * np.sin(2 * np.pi * 220 * time)
    backing_audio = 0.18 * np.sin(2 * np.pi * 110 * time)
    source = tmp_path / "source.wav"
    vocal = tmp_path / "vocal.wav"
    accompaniment = tmp_path / "accompaniment.wav"
    guarded = tmp_path / "guarded.wav"
    sf.write(source, vocal_audio + backing_audio, rate)
    sf.write(vocal, vocal_audio, rate)
    sf.write(accompaniment, backing_audio, rate)

    result = guard_lyric_accompaniment(source, vocal, accompaniment, guarded)

    output, _ = sf.read(guarded, dtype="float32")
    assert result.muted is False
    assert np.max(np.abs(output - backing_audio)) < 1e-4


def test_rhythm_comparison_ignores_timbre_but_rejects_retimed_attacks(tmp_path: Path) -> None:
    rate = 16000
    length = rate * 4

    def phrase(frequency: float, attacks: list[float]) -> np.ndarray:
        result = np.zeros(length, dtype=np.float32)
        for attack in attacks:
            begin = round(attack * rate)
            frames = min(round(0.32 * rate), length - begin)
            time = np.arange(frames, dtype=np.float32) / rate
            result[begin:begin + frames] += (
                0.2 * np.sin(2 * np.pi * frequency * time) * np.exp(-7 * time)
            )
        return result

    source = tmp_path / "source.wav"
    matching = tmp_path / "matching.wav"
    retimed = tmp_path / "retimed.wav"
    sf.write(source, phrase(220, [0.15, 0.75, 1.60, 2.05, 3.20]), rate)
    sf.write(matching, phrase(330, [0.15, 0.75, 1.60, 2.05, 3.20]), rate)
    sf.write(retimed, phrase(330, [0.35, 1.15, 1.35, 2.75, 3.55]), rate)

    matching_result = compare_vocal_rhythm(source, matching)
    retimed_result = compare_vocal_rhythm(source, retimed)

    assert matching_result.reliable is True
    assert matching_result.score > 0.90
    assert retimed_result.reliable is True
    assert retimed_result.score < 0.10
