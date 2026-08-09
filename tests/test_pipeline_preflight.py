from pathlib import Path

from opencover.models.schema import VoiceModel
from opencover.pipelines.original_cover import CoverRequest, OriginalCoverPipeline, separation_cache_key


def test_preflight_reports_missing_real_backends(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"; source.write_bytes(b"not-used")
    voice = VoiceModel(id="voice", display_name="Voice", engine="rvc", model_files=["model.pth"])
    issues = OriginalCoverPipeline(tmp_path).preflight(CoverRequest(source, "rvc", voice, 0, "均衡"))
    assert "FFmpeg 未安装" in issues
    assert any("MSST" in issue for issue in issues)
    assert any("RVC" in issue for issue in issues)


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
