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
    assert "avatar_original.png" in model.sha256
    assert "preview_original.wav" in model.sha256
    assert ModelRegistry(tmp_path / "weights").get(model.id) is not None


def test_duplicate_weight_is_rejected(tmp_path: Path) -> None:
    weight = tmp_path / "voice.pth"; weight.write_bytes(b"same-model" * 200)
    importer = ModelImporter(tmp_path / "weights")
    importer.import_model(engine="rvc", weight=weight, display_name="one")
    with pytest.raises(ValueError, match="已经导入"):
        importer.import_model(engine="rvc", weight=weight, display_name="two")


def test_missing_preview_stays_unavailable(tmp_path: Path) -> None:
    weight = tmp_path / "voice.pt"; weight.write_bytes(b"ddsp-model" * 200)
    config = tmp_path / "模型.yml"; config.write_text("model: {}", encoding="utf-8")
    model = ModelImporter(tmp_path / "weights").import_model(engine="ddsp", weight=weight, display_name="no preview", index_or_config=config)
    assert model.preview is None
    assert model.preview_source == "none"
    assert model.config_files == ["config.yaml"]


def test_edit_metadata_remove_preview_and_delete_user_model(tmp_path: Path) -> None:
    weight = tmp_path / "voice.pth"; weight.write_bytes(b"model" * 300)
    preview = tmp_path / "preview.wav"; _wav(preview)
    importer = ModelImporter(tmp_path / "weights")
    model = importer.import_model(engine="rvc", weight=weight, display_name="旧名称", preview=preview)
    changed = importer.update_model(
        model.id, display_name="新名称", description="新简介", recommended_pitch=3,
        languages=["zh", "ja"], remove_preview=True,
    )
    assert changed.display_name == "新名称"
    assert changed.recommended_pitch == 3
    assert changed.preview is None
    assert not list(changed.directory(tmp_path / "weights").glob("preview*"))
    importer.delete_user_model(model.id)
    assert ModelRegistry(tmp_path / "weights").get(model.id) is None
