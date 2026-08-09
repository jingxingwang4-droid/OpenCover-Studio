from pathlib import Path
import wave

import pytest
from PIL import Image

from opencover.models.importer import ModelImporter
from opencover.models.registry import ModelRegistry


def _wav(path: Path) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1); handle.setsampwidth(2); handle.setframerate(16000)
        handle.writeframes(b"\x01\x00" * 1600)


def test_import_rvc_with_chinese_paths(tmp_path: Path) -> None:
    source = tmp_path / "中文来源"; source.mkdir()
    weight = source / "音色.pth"; weight.write_bytes(b"model-data" * 200)
    index = source / "检索.index"; index.write_bytes(b"index-data")
    avatar = source / "头像.png"; Image.new("RGB", (800, 400), "navy").save(avatar)
    preview = source / "试听.wav"; _wav(preview)
    model = ModelImporter(tmp_path / "weights").import_model(
        engine="rvc", weight=weight, index_or_config=index, display_name="测试音色",
        avatar=avatar, preview=preview,
    )
    assert model.preview_source == "uploaded"
    assert model.avatar == "avatar.webp"
    assert ModelRegistry(tmp_path / "weights").get(model.id) is not None


def test_duplicate_weight_is_rejected(tmp_path: Path) -> None:
    weight = tmp_path / "voice.pth"; weight.write_bytes(b"same-model" * 200)
    importer = ModelImporter(tmp_path / "weights")
    importer.import_model(engine="rvc", weight=weight, display_name="one")
    with pytest.raises(ValueError, match="已经导入"):
        importer.import_model(engine="rvc", weight=weight, display_name="two")


def test_missing_preview_stays_unavailable(tmp_path: Path) -> None:
    weight = tmp_path / "voice.pt"; weight.write_bytes(b"ddsp-model" * 200)
    model = ModelImporter(tmp_path / "weights").import_model(engine="ddsp", weight=weight, display_name="no preview")
    assert model.preview is None
    assert model.preview_source == "none"
