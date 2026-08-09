from pathlib import Path

from opencover.models.schema import VoiceModel
from opencover.pipelines.original_cover import CoverRequest, OriginalCoverPipeline


def test_preflight_reports_missing_real_backends(tmp_path: Path) -> None:
    source = tmp_path / "input.wav"; source.write_bytes(b"not-used")
    voice = VoiceModel(id="voice", display_name="Voice", engine="rvc", model_files=["model.pth"])
    issues = OriginalCoverPipeline(tmp_path).preflight(CoverRequest(source, "rvc", voice, 0, "均衡"))
    assert "FFmpeg 未安装" in issues
    assert any("MSST" in issue for issue in issues)
    assert any("RVC" in issue for issue in issues)
