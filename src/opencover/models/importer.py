from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
import wave
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .registry import ModelRegistry
from .schema import ModelImportSchema, VoiceModel

RVC_SCHEMA = ModelImportSchema(required_files=[".pth"], optional_files=[".index"], accepted_extensions=[".pth", ".index"])
DDSP_SCHEMA = ModelImportSchema(required_files=[".pt"], optional_files=[".yaml", ".yml", ".json"], accepted_extensions=[".pt", ".ckpt", ".yaml", ".yml", ".json"])
MAX_WEIGHT_BYTES = 8 * 1024**3
MAX_IMAGE_BYTES = 20 * 1024**2


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slug(name: str) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return (ascii_part or "voice")[:40] + "_" + uuid.uuid4().hex[:8]


def _copy_exclusive(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"目标已存在：{target.name}")
    with source.open("rb") as src, target.open("xb") as dst:
        shutil.copyfileobj(src, dst, 1024 * 1024)


class ModelImporter:
    def __init__(self, weights_root: Path):
        self.weights_root = weights_root
        self.registry = ModelRegistry(weights_root)

    def import_model(
        self, *, engine: str, weight: Path, display_name: str, description: str = "",
        index_or_config: Path | None = None, avatar: Path | None = None,
        preview: Path | None = None, model_id: str | None = None,
    ) -> VoiceModel:
        if engine not in {"rvc", "ddsp"}:
            raise ValueError("不支持的引擎")
        weight = weight.resolve(strict=True)
        schema = RVC_SCHEMA if engine == "rvc" else DDSP_SCHEMA
        if weight.suffix.lower() not in schema.accepted_extensions or weight.suffix.lower() in {".json", ".yaml", ".yml", ".index"}:
            raise ValueError(f"{engine.upper()} 权重扩展名不正确")
        if not 1024 <= weight.stat().st_size <= MAX_WEIGHT_BYTES:
            raise ValueError("权重文件大小异常")
        digest = sha256(weight)
        if digest in self.registry.hashes():
            raise ValueError("此权重已经导入")
        identity = model_id or _slug(display_name)
        if self.registry.get(identity):
            raise ValueError("模型 ID 已存在")
        target = self.weights_root / engine / "user_models" / identity
        target.mkdir(parents=True, exist_ok=False)
        copied: list[Path] = []
        try:
            model_name = "model" + weight.suffix.lower()
            _copy_exclusive(weight, target / model_name)
            copied.append(target / model_name)
            indexes: list[str] = []
            configs: list[str] = []
            hashes = {model_name: digest}
            if index_or_config:
                extra = index_or_config.resolve(strict=True)
                expected = {".index"} if engine == "rvc" else {".yaml", ".yml", ".json"}
                if extra.suffix.lower() not in expected:
                    raise ValueError("索引/配置文件类型与引擎不匹配")
                extra_name = "model" + extra.suffix.lower()
                _copy_exclusive(extra, target / extra_name)
                copied.append(target / extra_name)
                hashes[extra_name] = sha256(extra)
                (indexes if engine == "rvc" else configs).append(extra_name)
            avatar_name = self._avatar(avatar, target, display_name)
            preview_name = self._preview(preview, target) if preview else None
            model = VoiceModel(
                id=identity, display_name=display_name.strip() or identity, description=description.strip(),
                engine=engine, model_files=[model_name], index_files=indexes, config_files=configs,
                avatar=avatar_name, preview=preview_name,
                preview_source="uploaded" if preview_name else "none", sha256=hashes,
            )
            (target / "model.json").write_text(model.model_dump_json(indent=2), encoding="utf-8")
            return model
        except Exception:
            shutil.rmtree(target, ignore_errors=True)
            raise

    def _avatar(self, source: Path | None, target: Path, label: str) -> str:
        output = target / "avatar.webp"
        if source:
            source = source.resolve(strict=True)
            if source.stat().st_size > MAX_IMAGE_BYTES:
                raise ValueError("头像不能超过 20 MB")
            try:
                with Image.open(source) as image:
                    image.verify()
                with Image.open(source) as image:
                    image = ImageOps.exif_transpose(image).convert("RGB")
                    image = ImageOps.fit(image, (512, 512), method=Image.Resampling.LANCZOS)
                    image.save(output, "WEBP", quality=90)
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError("头像不是有效图片") from exc
        else:
            from PIL import ImageDraw
            image = Image.new("RGB", (512, 512), "#536B78")
            draw = ImageDraw.Draw(image)
            letter = (label.strip() or "V")[0].upper()
            draw.text((256, 256), letter, fill="white", anchor="mm", font_size=220)
            image.save(output, "WEBP", quality=90)
        return output.name

    def _preview(self, source: Path, target: Path) -> str:
        source = source.resolve(strict=True)
        if source.suffix.lower() != ".wav":
            raise ValueError("当前未安装 FFmpeg 时仅支持上传 WAV 试听")
        try:
            with wave.open(str(source), "rb") as wav:
                if wav.getnchannels() not in {1, 2} or wav.getframerate() < 8000 or wav.getnframes() <= 0:
                    raise ValueError("试听 WAV 参数异常")
        except (wave.Error, EOFError) as exc:
            raise ValueError("试听不是有效 WAV") from exc
        _copy_exclusive(source, target / "preview.wav")
        return "preview.wav"
