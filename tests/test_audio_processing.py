from pathlib import Path

import numpy as np
import soundfile as sf

from opencover.audio.processing import mix_tracks, validate_audio


def test_mix_tracks_creates_real_non_silent_wav(tmp_path: Path) -> None:
    sr = 16000; t = np.arange(sr, dtype=np.float32) / sr
    vocal = 0.1 * np.sin(2 * np.pi * 220 * t)
    backing = 0.1 * np.sin(2 * np.pi * 110 * t)
    vocal_path = tmp_path / "vocal.wav"; backing_path = tmp_path / "backing.wav"; output = tmp_path / "mix.wav"
    sf.write(vocal_path, vocal, sr); sf.write(backing_path, backing, sr)
    mix_tracks(vocal_path, backing_path, output)
    _, _, duration = validate_audio(output)
    data, _ = sf.read(output)
    assert duration == 1.0
    assert float(np.max(np.abs(data))) > 0.01
