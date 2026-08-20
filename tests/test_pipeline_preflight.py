from pathlib import Path

from opencover.models.schema import VoiceModel
from opencover.pipelines.original_cover import CoverRequest, OriginalCoverPipeline, cache_key, separation_cache_key
from opencover.audio.pitch import PitchAnalysis, resolve_auto_pitch


def test_preflight_reports_missing_real_backends(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"; source.write_bytes(b"not-used")
    voice = VoiceModel(id="voice", display_name="Voice", engine="rvc", model_files=["model.pth"])
    issues = OriginalCoverPipeline(tmp_path).preflight(CoverRequest(source, "rvc", voice, 0, "均衡"))
    assert "FFmpeg 未安装" in issues
    assert any("MSST" in issue for issue in issues)
    assert any("RVC" in issue for issue in issues)


def test_preflight_rejects_invalid_voice_adaptation_options(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"; source.write_bytes(b"not-used")
    voice = VoiceModel(id="voice", display_name="Voice", engine="rvc", model_files=["model.pth"])
    request = CoverRequest(source, "rvc", voice, 0, "均衡", pitch_mode="guess", source_voice="other")
    issues = OriginalCoverPipeline(tmp_path).preflight(request)
    assert "升降调模式无效" in issues
    assert "原唱声部选项无效" in issues


def test_preflight_rejects_a_quality_rejected_voice(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"; source.write_bytes(b"not-used")
    voice = VoiceModel(
        id="bad", display_name="Bad", engine="ddsp", model_files=["model.pt"],
        selectable=False, quality_status="rejected",
    )
    issues = OriginalCoverPipeline(tmp_path).preflight(CoverRequest(source, "ddsp", voice, 0, "均衡"))
    assert "该音色已因真实歌曲验证质量不合格而停用" in issues


def test_separation_cache_is_shared_across_engines_and_voices(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"
    checkpoint = tmp_path / "separator.ckpt"
    source.write_bytes(b"source")
    checkpoint.write_bytes(b"model")
    rvc_voice = VoiceModel(id="a", display_name="A", engine="rvc", model_files=["a.pth"])
    ddsp_voice = VoiceModel(id="b", display_name="B", engine="ddsp", model_files=["b.pt"])
    rvc = CoverRequest(source, "rvc", rvc_voice, 0, "balanced")
    ddsp = CoverRequest(source, "ddsp", ddsp_voice, 7, "vocal")
    assert separation_cache_key(rvc, checkpoint) == separation_cache_key(ddsp, checkpoint)


def test_conversion_cache_ignores_mix_but_tracks_model_hash(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"; source.write_bytes(b"source")
    first = VoiceModel(id="voice", display_name="Voice", engine="rvc", model_files=["model.pth"], sha256={"model.pth": "aaa"})
    updated = first.model_copy(update={"sha256": {"model.pth": "bbb"}})
    balanced = CoverRequest(source, "rvc", first, 0, "均衡")
    vocal = CoverRequest(source, "rvc", first, 0, "人声更突出")
    replaced = CoverRequest(source, "rvc", updated, 0, "均衡")
    low_memory = CoverRequest(source, "rvc", first, 0, "均衡", memory_profile="低")
    assert cache_key(balanced) == cache_key(vocal)
    assert cache_key(balanced) != cache_key(replaced)
    assert cache_key(balanced) != cache_key(low_memory)
    male_auto = CoverRequest(source, "rvc", first, 0, "均衡", pitch_mode="auto", source_voice="male")
    assert cache_key(balanced) != cache_key(male_auto)


def test_auto_pitch_moves_between_known_voice_registers() -> None:
    male = PitchAnalysis(118.0, "male", 50, 0.9)
    female = PitchAnalysis(220.0, "female", 50, 0.9)
    assert resolve_auto_pitch(0, "auto", "female", male) == (12, "male")
    assert resolve_auto_pitch(0, "auto", "male", female) == (-12, "female")
    assert resolve_auto_pitch(2, "male", "female") == (12, "male")
    assert resolve_auto_pitch(0, "auto", "unknown", male) == (0, "male")
    boundary = PitchAnalysis(190.0, "unknown", 50, 0.9)
    assert resolve_auto_pitch(0, "auto", "female", boundary) == (0, "unknown")
