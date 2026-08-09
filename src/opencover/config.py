from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


class Settings(BaseModel):
    last_page: str = "首页"
    window_width: int = Field(1180, ge=900)
    window_height: int = Field(760, ge=620)
    memory_profile: Literal["极低", "低", "标准", "高质量"] = "标准"
    output_format: Literal["wav", "flac", "mp3"] = "wav"
    minimize_to_tray: bool = True

    @classmethod
    def load(cls, path: Path) -> "Settings":
        if not path.exists():
            return cls()
        try:
            return cls.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        temp.replace(path)
