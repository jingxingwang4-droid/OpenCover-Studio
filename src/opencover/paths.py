from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class AppPaths:
    root: Path
    workspace: Path
    weights: Path
    assets: Path
    config: Path
    external_backends: Path
    ffmpeg: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        root = Path(os.environ.get("OPENCOVER_ROOT", project_root())).resolve()
        return cls(
            root=root,
            workspace=root / "workspace",
            weights=root / "weights",
            assets=root / "assets",
            config=root / "config",
            external_backends=root / "external_backends",
            ffmpeg=root / "ffmpeg",
        )

    def ensure(self) -> None:
        for path in (
            self.workspace / "outputs",
            self.workspace / "cache",
            self.workspace / "logs",
            self.workspace / "jobs",
            self.weights / "rvc" / "bundled",
            self.weights / "rvc" / "user_models",
            self.weights / "ddsp" / "bundled",
            self.weights / "ddsp" / "user_models",
            self.assets / "backgrounds",
            self.assets / "preview_sources",
            self.assets / "voice_avatars" / "placeholders",
            self.external_backends,
            self.ffmpeg,
        ):
            path.mkdir(parents=True, exist_ok=True)
