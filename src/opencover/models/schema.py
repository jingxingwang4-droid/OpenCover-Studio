from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ModelImportSchema(BaseModel):
    required_files: list[str]
    optional_files: list[str] = Field(default_factory=list)
    accepted_extensions: list[str]


class VoiceModel(BaseModel):
    id: str
    display_name: str
    description: str = ""
    engine: Literal["rvc", "ddsp"]
    model_files: list[str]
    index_files: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    avatar: str | None = None
    preview: str | None = None
    preview_source: Literal["uploaded", "bundled", "generated", "none"] = "none"
    preview_source_audio: str | None = None
    recommended_pitch: int = Field(0, ge=-12, le=12)
    languages: list[str] = Field(default_factory=list)
    source: str = ""
    author: str = ""
    license: str = ""
    redistribution_allowed: bool = False
    sha256: dict[str, str] = Field(default_factory=dict)
    bundled: bool = False
    featured: bool = False
    sort_order: int = 100

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in value):
            raise ValueError("模型 ID 只能包含小写字母、数字、下划线和连字符")
        return value

    def directory(self, weights_root: Path) -> Path:
        group = "bundled" if self.bundled else "user_models"
        return weights_root / self.engine / group / self.id
