from pathlib import Path
import zipfile

import pytest

from opencover.core.download_manager import DownloadError, safe_extract_zip
from opencover.workers.resource_worker import cache_path, install_resource


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


def test_zip_symlink_is_rejected(tmp_path: Path) -> None:
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        link = zipfile.ZipInfo("link"); link.create_system = 3; link.external_attr = 0o120777 << 16
        handle.writestr(link, "../outside")
    with pytest.raises(DownloadError, match="符号链接"):
        safe_extract_zip(archive, tmp_path / "out")


def test_resource_install_respects_root_and_never_overwrites(tmp_path: Path) -> None:
    source = tmp_path / "downloads" / "model.pt"
    source.parent.mkdir(); source.write_bytes(b"verified model bytes")
    item = {"install_directory": "external_backends/test/model.pt"}
    installed = install_resource(tmp_path, item, source)
    assert installed.read_bytes() == b"verified model bytes"
    installed.write_bytes(b"user data")
    with pytest.raises(DownloadError, match="不会覆盖"):
        install_resource(tmp_path, item, source)
    with pytest.raises(DownloadError, match="越界"):
        install_resource(tmp_path, {"install_directory": "../escape.pt"}, source)


def test_resource_zip_install_and_cache_name(tmp_path: Path) -> None:
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as handle:
        handle.writestr("package/readme.txt", "safe")
    destination = install_resource(tmp_path, {"install_directory": "external_backends/demo"}, archive)
    assert (destination / "package" / "readme.txt").read_text() == "safe"
    item = {"resource_id": "demo", "download_url": "https://example.invalid/files/model.tar.gz?download=1"}
    assert cache_path(tmp_path, item).name == "demo.tar.gz"
