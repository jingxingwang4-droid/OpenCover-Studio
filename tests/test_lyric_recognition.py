from __future__ import annotations

from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np

from opencover.pipelines.lyric_recognition import recognition_separation_cache_key
from opencover.workers.vocalparse_runtime import _audio_chunks, _cot_lyrics


def test_vocalparse_cot_lyrics_are_extracted_for_manual_review() -> None:
    raw = (
        "language Chinese<asr_text>白马过了离原，三月的天"
        "<|file_sep|>白<P_60><NOTE_4>马<P_62><NOTE_8><BPM_90>"
    )
    assert _cot_lyrics(raw) == "白马过了离原，三月的天"
    assert _cot_lyrics("白<P_60><NOTE_4>") == ""


def test_recognition_separation_cache_tracks_audio_and_separator(tmp_path: Path) -> None:
    source = tmp_path / "song.wav"
    model = tmp_path / "separator.ckpt"
    source.write_bytes(b"audio-v1")
    model.write_bytes(b"model-v1")
    first = recognition_separation_cache_key(source, (model,), "separator-v1")
    assert first == recognition_separation_cache_key(source, (model,), "separator-v1")
    assert first != recognition_separation_cache_key(source, (model,), "separator-v2")
    source.write_bytes(b"audio-v2-with-change")
    assert first != recognition_separation_cache_key(source, (model,), "separator-v1")


def test_vocalparse_uses_silence_aware_five_to_nine_second_chunks(monkeypatch) -> None:
    rate = 16000
    wav = np.zeros(rate * 21, dtype=np.float32)
    for begin, end in ((0.2, 6.5), (7.0, 13.8), (14.2, 20.7)):
        t = np.arange(round((end - begin) * rate), dtype=np.float32) / rate
        wav[round(begin * rate):round(end * rate)] = 0.2 * np.sin(2 * np.pi * 220 * t)
    fake_librosa = SimpleNamespace(effects=SimpleNamespace(split=lambda *args, **kwargs: np.asarray([
        [round(0.2 * rate), round(20.7 * rate)],
    ], dtype=np.int64)))
    monkeypatch.setitem(sys.modules, "librosa", fake_librosa)
    chunks = _audio_chunks(wav, rate)
    durations = [(end - start) / rate for start, end in chunks]
    assert len(chunks) == 3
    assert all(5.0 <= duration <= 9.0 for duration in durations)
    assert all(chunks[index][1] <= chunks[index + 1][0] for index in range(len(chunks) - 1))
