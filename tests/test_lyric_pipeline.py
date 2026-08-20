from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from opencover.adapters.backends import EspnetVisinger2Adapter, Vevo2Adapter
from opencover.lyrics.processing import LyricSegment
from opencover.models.schema import VoiceModel
from opencover.pipelines.lyric_cover import (
    LyricCoverPipeline, LyricCoverRequest, backend_markers, character_timings_from_alignment,
    game_melody_for_text,
    select_initial_generator, trim_segments_to_vocal_activity, transpose_note_windows,
    diffsinger_octave_adaptation,
)
from opencover.workers.diffsinger_legacy_runtime import _score_constrained_f0
from opencover.workers.espnet_visinger2_runtime import expand_score_windows, note_name_to_midi
from opencover.workers.score_refinement_runtime import refine_events
from opencover.workers.vevo2_runtime import _duration_token_budget


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


def test_visinger2_status_requires_runtime_source_model_and_smoke_marker(tmp_path: Path) -> None:
    root = tmp_path / "espnet_visinger2"
    required = [
        root / "runtime" / "Scripts" / "python.exe",
        root / "source" / "espnet2" / "bin" / "svs_inference.py",
        root / "frontend" / "resource" / "pinyin_dict.py",
        root / "model" / "exp" / "svs_train_visinger2_40singer_raw_phn_None_zh" / "config.yaml",
        root / "model" / "exp" / "svs_train_visinger2_40singer_raw_phn_None_zh" / "500epoch.pth",
        root / "runtime" / "Lib" / "site-packages" / "typeguard" / "__init__.py",
        root / "runtime" / "Lib" / "site-packages" / "pypinyin" / "__init__.py",
    ]
    for path in required:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"present")
    (root / "backend.json").write_text(
        json.dumps({"smoke_test_passed": True, "model_revision": "verified"}), encoding="utf-8",
    )
    assert EspnetVisinger2Adapter(root).status().runnable is True
    required[-1].unlink()
    assert EspnetVisinger2Adapter(root).status().runnable is False


def test_stitch_places_real_generated_segments_at_timestamps(tmp_path: Path) -> None:
    pipeline = LyricCoverPipeline(Path(__file__).resolve().parents[1])
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
    assert text == "春日SP花开"
    assert pitches.split(" | ") == ["C4", "C4", "rest", "D#4", "G4"]
    assert durations.split(" | ") == ["0.200000", "0.200000", "0.100000", "0.500000", "1.000000"]


def test_game_notes_preserve_melisma_and_relative_durations(tmp_path: Path) -> None:
    notes = tmp_path / "source_000.txt"
    notes.write_text(
        "0.2\t0.4\tC4\n0.4\t1.0\tD4\n1.0\t1.2\tE4\n1.2\t2.0\tG4\n",
        encoding="utf-8",
    )
    text, pitches, durations = game_melody_for_text("春日", 3.6, notes)
    assert text == "SP春日AP"
    assert pitches == "rest | C4 D4 | E4 G4 | rest"
    assert durations == "0.200000 | 0.200000 0.600000 | 0.200000 0.800000 | 1.600000"
    assert sum(float(value) for value in durations.replace("|", " ").split()) == pytest.approx(3.6)


def test_score_mapping_uses_elapsed_time_instead_of_even_note_counts(tmp_path: Path) -> None:
    notes = tmp_path / "source_000.txt"
    notes.write_text(
        "0.09\t0.24\tF4\n"
        "0.24\t0.45\tG4\n"
        "0.45\t0.77\tA#4\n"
        "0.77\t0.89\tA#4\n"
        "0.89\t1.07\tC5\n",
        encoding="utf-8",
    )
    text, pitches, durations = game_melody_for_text("轻舟渡", 1.07, notes)
    assert text == "SP轻舟渡"
    assert pitches == "rest | F4 G4 | A#4 | A#4 C5"
    assert durations == "0.090000 | 0.150000 0.210000 | 0.320000 | 0.120000 0.180000"


def test_character_alignment_splits_grouped_words_and_rejects_mismatch() -> None:
    aligned = {
        "segments": [{
            "words": [
                {"word": "白马", "start": 0.1, "end": 0.5},
                {"word": "过", "start": 0.5, "end": 0.8},
            ],
        }],
    }
    assert np.allclose(
        character_timings_from_alignment("白马过", aligned),
        [(0.1, 0.3), (0.3, 0.5), (0.5, 0.8)],
    )
    assert character_timings_from_alignment("白马来", aligned) is None


def test_f0_refinement_recovers_stable_transition_inside_coarse_note() -> None:
    times = np.arange(0.0, 0.61, 0.02, dtype=np.float32)
    f4 = 440.0 * 2.0 ** ((65 - 69) / 12)
    g4 = 440.0 * 2.0 ** ((67 - 69) / 12)
    f0 = np.where(times < 0.28, f4, g4).astype(np.float32)
    refined = refine_events([(0.0, 0.6, "G4")], times, f0)
    assert [note for _, _, note in refined] == ["F4", "G4"]
    assert refined[0][1] == pytest.approx(refined[1][0])


def test_auto_generator_prefers_clear_score_backend_and_falls_back_in_order() -> None:
    assert select_initial_generator(
        "auto", has_midi=False, vevo_runnable=True, fallback_runnable=True,
        score_runnable=True,
    ) == "diffsinger"
    assert select_initial_generator(
        "auto", has_midi=False, vevo_runnable=True, fallback_runnable=True,
    ) == "vevo2"
    assert select_initial_generator(
        "auto", has_midi=False, vevo_runnable=False, fallback_runnable=True,
    ) == "visinger2"
    assert select_initial_generator(
        "auto", has_midi=True, vevo_runnable=True, fallback_runnable=True,
    ) == "visinger2"


def test_visinger2_expands_melisma_windows_without_losing_score_time() -> None:
    expanded = expand_score_windows(
        "SP春日AP", "rest | C4 D4 | E4 | rest", "0.2 | 0.3 0.4 | 0.5 | 0.6",
    )
    assert expanded == [
        ("SP", 0, 0.2), ("春", 60, 0.3), ("-", 62, 0.4),
        ("日", 64, 0.5), ("AP", 0, 0.6),
    ]
    assert sum(item[2] for item in expanded) == pytest.approx(2.0)
    assert note_name_to_midi("A#4") == 70


def test_vevo_ar_generation_is_bounded_by_requested_duration() -> None:
    assert _duration_token_budget(5.0) == 68
    assert _duration_token_budget(1.5) == 21
    assert _duration_token_budget(100.0) == 500


def test_lrc_interval_is_trimmed_to_actual_vocal_activity(tmp_path: Path) -> None:
    rate = 1000
    audio = np.zeros(rate * 6, dtype=np.float32)
    audio[rate:rate * 3] = 0.2
    vocals = tmp_path / "vocals.wav"
    sf.write(vocals, audio, rate)
    result = trim_segments_to_vocal_activity(
        [LyricSegment(0.0, 6.0, "原词", "新词")], vocals,
    )
    assert 0.90 <= result[0].start <= 1.0
    assert 3.0 <= result[0].end <= 3.10


def test_diffsinger_vocoder_f0_is_constrained_to_score() -> None:
    # A2 requested but the legacy pitch extractor jumps to A4.  The score must
    # win; small non-octave movement is retained and unvoiced frames stay zero.
    corrected = _score_constrained_f0(
        np.array([[440.0, 113.0, 0.0]], dtype=np.float32),
        np.array([[45.0, 45.0, 45.0]], dtype=np.float32),
    )
    target_a2 = 110.0
    assert abs(float(corrected[0, 0]) - target_a2) < 1.0
    assert target_a2 < float(corrected[0, 1]) < 114.0
    assert corrected[0, 2] == 0.0


def test_diffsinger_range_adaptation_is_song_wide() -> None:
    low_song = ["F3 | A#2 C3", "G3 | A#3 | F3"]
    assert diffsinger_octave_adaptation(low_song) == 12
    assert transpose_note_windows(low_song[0], 12) == "F4 | A#3 C4"
    assert diffsinger_octave_adaptation(["F3 | G3", "A3 | C4"]) == 0


def test_lyric_preflight_rejects_unknown_generator(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"
    source.write_bytes(b"audio")
    voice = VoiceModel(id="voice", display_name="Voice", engine="rvc", model_files=["model.pth"])
    request = LyricCoverRequest(source, "rvc", voice, "原词", "新词", generator="unknown")
    assert "未知改词生成器：unknown" in LyricCoverPipeline(tmp_path).preflight(request)


def test_generation_marker_tolerates_missing_optional_backend_markers(tmp_path: Path) -> None:
    for name in ("espnet_visinger2", "vevo2", "game", "diffsinger", "alignment"):
        (tmp_path / "external_backends" / name).mkdir(parents=True)
    assert backend_markers(tmp_path) == "espnet_visinger2:missing\nvevo2:missing\ngame:missing\ndiffsinger:missing\nalignment:missing"
