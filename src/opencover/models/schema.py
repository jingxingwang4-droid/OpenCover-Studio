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
    voice_gender: Literal["male", "female", "unknown"] = "unknown"
    f0_method: Literal["rmvpe", "fcpe", "harvest", "dio", "crepe", "parselmouth", "pm"] | None = None
    f0_min: float | None = Field(None, ge=20, le=2000)
    f0_max: float | None = Field(None, ge=20, le=4000)
    index_rate: float | None = Field(None, ge=0, le=1)
    protect: float | None = Field(None, ge=0, le=0.5)
    rms_mix_rate: float | None = Field(None, ge=0, le=1)
    silence_threshold_db: float | None = Field(None, ge=-100, le=0)
    source_detail_mix: float | None = Field(None, ge=0, le=0.5)
    source_detail_cutoff_hz: int | None = Field(None, ge=2000, le=12000)
    converted_treble_db: float | None = Field(None, ge=-12, le=12)
    converted_gain: float | None = Field(None, ge=0.5, le=1)
    languages: list[str] = Field(default_factory=list)
    source: str = ""
    author: str = ""
    license: str = ""
    redistribution_allowed: bool = False
    sha256: dict[str, str] = Field(default_factory=dict)
    bundled: bool = False
    featured: bool = False
    sort_order: int = 100
    selectable: bool = True
    quality_status: Literal["verified", "experimental", "rejected"] = "experimental"

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in value):
            raise ValueError("模型 ID 只能包含小写字母、数字、下划线和连字符")
        return value

    def directory(self, weights_root: Path) -> Path:
        group = "bundled" if self.bundled else "user_models"
        return weights_root / self.engine / group / self.id

    def inference_signature(self) -> str:
        """Stable cache identity for settings that materially change generated audio."""
        fields = (
            self.f0_method, self.f0_min, self.f0_max, self.index_rate,
            self.protect, self.rms_mix_rate, self.silence_threshold_db,
            self.source_detail_mix, self.source_detail_cutoff_hz,
            self.converted_treble_db, self.converted_gain,
            self.voice_gender,
        )
        return ":".join("" if value is None else str(value) for value in fields)
