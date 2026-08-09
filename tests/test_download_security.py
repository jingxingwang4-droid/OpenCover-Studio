from pathlib import Path
import zipfile

import pytest

from opencover.core.download_manager import DownloadError, safe_extract_zip


def test_safe_zip_extracts(tmp_path: Path) -> None:
    archive = tmp_path / "ok.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("folder/file.txt", "ok")
    target = tmp_path / "out"
    safe_extract_zip(archive, target)
    assert (target / "folder" / "file.txt").read_text() == "ok"


def test_zip_traversal_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    with pytest.raises(DownloadError, match="路径穿越"):
        safe_extract_zip(archive, tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()
