from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from opencover.adapters.backends import Vevo2Adapter
from opencover.lyrics.processing import LyricSegment
from opencover.models.schema import VoiceModel
from opencover.pipelines.lyric_cover import LyricCoverPipeline, LyricCoverRequest, backend_markers, game_melody_for_text


def test_vevo2_status_requires_runtime_source_models_and_smoke_marker(tmp_path: Path) -> None:
    root = tmp_path / "vevo2"
    (root / "runtime" / "Scripts").mkdir(parents=True)
    (root / "runtime" / "Scripts" / "python.exe").write_bytes(b"python")
    (root / "Amphion" / "models" / "svc" / "vevo2").mkdir(parents=True)
    (root / "Amphion" / "models" / "svc" / "vevo2" / "vevo2_utils.py").write_text("", encoding="utf-8")
    model = root / "models" / "Vevo2"
    required = [
        model / "tokenizer" / "prosody_fvq512_6.25hz" / "model.safetensors",
        model / "tokenizer" / "contentstyle_fvq16384_12.5hz" / "model.safetensors",
        model / "contentstyle_modeling" / "posttrained" / "model.safetensors",
        model / "acoustic_modeling" / "fm_emilia101k_singnet7k_repa" / "model.safetensors",
        model / "vocoder" / "model.safetensors",
    ]
    for path in required:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"model")
    (root / "backend.json").write_text(json.dumps({"smoke_test_passed": True, "commit": "verified"}), encoding="utf-8")
    status = Vevo2Adapter(root).status()
    assert status.installed is True
    assert status.runnable is True
    required[-1].unlink()
    assert Vevo2Adapter(root).status().runnable is False


def test_stitch_places_real_generated_segments_at_timestamps(tmp_path: Path) -> None:
    pipeline = LyricCoverPipeline(tmp_path)
    segment_audio = tmp_path / "generated.wav"
    sf.write(segment_audio, np.full(24000, 0.2, dtype=np.float32), 24000)
    segments = [LyricSegment(1.0, 2.0, "原词", "新词")]
    output = pipeline._stitch([{"output": str(segment_audio)}], segments, 3.0, tmp_path / "stitched.wav")
    audio, rate = sf.read(output, dtype="float32")
    assert rate == 44100
    assert np.max(np.abs(audio[:40000])) == 0
    assert np.max(np.abs(audio[45000:85000])) > 0.1
    assert np.max(np.abs(audio[90000:])) == 0


def test_game_notes_are_mapped_to_chinese_diffsinger_windows(tmp_path: Path) -> None:
    notes = tmp_path / "source_000.txt"
    notes.write_text("0.0\t0.4\tC4+12\n0.5\t1.0\tD#4-5\n1.0\t2.0\tG4+0\n", encoding="utf-8")
    text, pitches, durations = game_melody_for_text("春日，花开！", 2.0, notes)
    assert text == "春日花开"
    assert pitches.split(" | ") == ["C4", "D#4", "G4", "G4"]
    assert durations.split(" | ") == ["0.500000"] * 4


def test_lyric_preflight_rejects_unknown_generator(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"
    source.write_bytes(b"audio")
    voice = VoiceModel(id="voice", display_name="Voice", engine="rvc", model_files=["model.pth"])
    request = LyricCoverRequest(source, "rvc", voice, "原词", "新词", generator="unknown")
    assert "未知改词生成器：unknown" in LyricCoverPipeline(tmp_path).preflight(request)


def test_generation_marker_tolerates_missing_optional_backend_markers(tmp_path: Path) -> None:
    for name in ("vevo2", "game", "diffsinger", "alignment"):
        (tmp_path / "external_backends" / name).mkdir(parents=True)
    assert backend_markers(tmp_path) == "vevo2:missing\ngame:missing\ndiffsinger:missing\nalignment:missing"
