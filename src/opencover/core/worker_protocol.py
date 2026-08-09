from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field


class WorkerEvent(BaseModel):
    type: Literal["status", "progress", "result", "error"]
    message: str | None = None
    stage: str | None = None
    value: int | None = Field(None, ge=0, le=100)
    path: str | None = None
    code: str | None = None

    @classmethod
    def parse_line(cls, line: str) -> "WorkerEvent":
        return cls.model_validate(json.loads(line))
