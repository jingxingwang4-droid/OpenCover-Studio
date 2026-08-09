from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from opencover.adapters.backends import DDSPAdapter, MSSTAdapter, RVCAdapter
from opencover.audio.processing import ffmpeg_path, mix_tracks, normalize_input
from opencover.models.schema import VoiceModel


@dataclass(frozen=True)
class CoverRequest:
    input_path: Path
    engine: str
    voice: VoiceModel
    pitch: int
    balance: str
    output_format: str = "wav"


def cache_key(request: CoverRequest) -> str:
    stat = request.input_path.stat()
    data = f"{request.input_path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}:{request.engine}:{request.voice.id}:{request.pitch}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class OriginalCoverPipeline:
    """Runs only verified real backends; missing components are hard failures."""

    def __init__(self, root: Path):
        self.root = root
        self.msst = MSSTAdapter(root / "external_backends" / "msst")
        self.rvc = RVCAdapter(root / "external_backends" / "rvc")
        self.ddsp = DDSPAdapter(root / "external_backends" / "ddsp")

    def preflight(self, request: CoverRequest) -> list[str]:
        issues: list[str] = []
        if not request.input_path.is_file():
            issues.append("输入音频不存在")
        if not ffmpeg_path(self.root):
            issues.append("FFmpeg 未安装")
        if not self.msst.status().runnable:
            issues.append(self.msst.status().detail)
        converter = self.rvc if request.engine == "rvc" else self.ddsp
        if not converter.status().runnable:
            issues.append(converter.status().detail)
        model_dir = request.voice.directory(self.root / "weights")
        if not all((model_dir / file).is_file() for file in request.voice.model_files):
            issues.append("音色权重缺失")
        return issues
