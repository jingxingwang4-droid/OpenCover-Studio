from __future__ import annotations

import hashlib
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from opencover.adapters.backends import UVR5Adapter, VocalParseAdapter
from opencover.audio.processing import ffmpeg_path, normalize_input


@dataclass(frozen=True)
class LyricRecognitionRequest:
    input_path: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def recognition_separation_cache_key(input_path: Path, artifacts: tuple[Path, ...], separator_id: str) -> str:
    source_stat = input_path.stat()
    model_identity = ":".join(
        f"{path.resolve()}:{path.stat().st_size}:{path.stat().st_mtime_ns}" for path in artifacts
    )
    data = f"{separator_id}:{input_path.resolve()}:{source_stat.st_size}:{source_stat.st_mtime_ns}:{model_identity}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class LyricRecognitionPipeline:
    """Separate lead vocals, transcribe with VocalParse, then stop for human review."""

    def __init__(self, root: Path):
        self.root = root
        self.uvr5 = UVR5Adapter(
            root / "external_backends" / "uvr5",
            (ffmpeg_path(root) or root / "ffmpeg/ffmpeg.exe").parent,
        )
        self.vocalparse = VocalParseAdapter(root / "external_backends" / "vocalparse")

    def _runner(self) -> Path:
        candidates = [
            self.root / "src" / "opencover" / "workers" / "vocalparse_runtime.py",
            self.root / "_internal" / "workers" / "vocalparse_runtime.py",
            Path(getattr(sys, "_MEIPASS", "")) / "workers" / "vocalparse_runtime.py",
        ]
        return next((path for path in candidates if path.is_file()), candidates[0])

    def preflight(self, request: LyricRecognitionRequest) -> list[str]:
        issues: list[str] = []
        if not request.input_path.is_file():
            issues.append("输入音频不存在")
        if not ffmpeg_path(self.root):
            issues.append("FFmpeg 未安装")
        if not self.uvr5.status().runnable:
            issues.append("UVR5 不可用，无法取得干净主唱")
        if not self.vocalparse.status().runnable:
            issues.append(self.vocalparse.status().detail)
        if not self._runner().is_file():
            issues.append("VocalParse 运行脚本缺失")
        return issues

    def _separate(
        self, request: LyricRecognitionRequest, job_dir: Path,
        report: Callable[[str, int, str], None],
    ) -> Path:
        if not self.uvr5.status().runnable:
            raise RuntimeError("UVR5 不可用，不允许回退到其他分离器")
        separator_id = self.uvr5.pipeline_id
        artifacts = self.uvr5.model_paths
        key = recognition_separation_cache_key(request.input_path, artifacts, separator_id)
        cache = self.root / "workspace" / "cache" / "separation" / key
        cached_vocals = cache / "vocals.wav"
        cached_other = cache / "other.wav"
        if cached_vocals.is_file() and cached_vocals.stat().st_size > 1024:
            report("separate", 30, "已复用主唱分离缓存")
            return cached_vocals

        ffmpeg = ffmpeg_path(self.root)
        assert ffmpeg is not None
        normalized_dir = job_dir / "normalized"
        normalized = normalized_dir / "input.wav"
        report("normalize", 10, "正在标准化歌曲")
        normalize_input(request.input_path, normalized, ffmpeg)
        separation_dir = job_dir / "separation"
        report("separate", 25, "正在分离主唱供 VocalParse 识别")
        self.uvr5.separate(normalized, separation_dir)
        vocals = next(separation_dir.rglob("vocals.wav"), None)
        other = next(separation_dir.rglob("other.wav"), None)
        if vocals is None:
            raise RuntimeError("人声分离未生成 vocals.wav")
        cache.mkdir(parents=True, exist_ok=True)
        for source, target in ((vocals, cached_vocals), (other, cached_other)):
            if source is None:
                continue
            partial = target.with_suffix(target.suffix + ".part")
            shutil.copy2(source, partial)
            partial.replace(target)
        return cached_vocals

    def run(
        self, request: LyricRecognitionRequest, job_dir: Path,
        progress: Callable[[str, int, str], None] | None = None,
    ) -> Path:
        issues = self.preflight(request)
        if issues:
            raise RuntimeError("；".join(issues))
        report = progress or (lambda stage, value, message: None)
        vocals = self._separate(request, job_dir, report)
        vocal_stat = vocals.stat()
        marker = (self.vocalparse.root / "backend.json").read_text(encoding="utf-8")
        key_data = "\0".join([
            str(vocals.resolve()), str(vocal_stat.st_size), str(vocal_stat.st_mtime_ns),
            marker, _sha256(self._runner()),
        ])
        key = hashlib.sha256(key_data.encode("utf-8")).hexdigest()
        cached = self.root / "workspace" / "cache" / "vocalparse" / key / "recognition.json"
        if cached.is_file() and cached.stat().st_size > 32:
            report("recognize_lyrics", 90, "已复用 VocalParse 识别缓存")
        else:
            report("recognize_lyrics", 45, "正在联合识别歌词、音高和一字多音")
            request_file = job_dir / "vocalparse" / "request.json"
            result_file = job_dir / "vocalparse" / "recognition.json"
            request_file.parent.mkdir(parents=True, exist_ok=True)
            request_file.write_text(json.dumps({
                "root": str(self.root), "audio_path": str(vocals),
                "output_path": str(result_file), "attn_implementation": "sdpa",
                "max_new_tokens": 768,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            self.vocalparse.transcribe(request_file, self._runner())
            cached.parent.mkdir(parents=True, exist_ok=True)
            partial = cached.with_suffix(".json.part")
            shutil.copy2(result_file, partial)
            partial.replace(cached)

        data = json.loads(cached.read_text(encoding="utf-8"))
        lyrics = str(data.get("lyrics", "")).strip()
        if len("".join(lyrics.split())) < 2:
            raise RuntimeError("VocalParse 识别歌词为空")
        artifact_dir = job_dir / "recognized"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        lyrics_file = artifact_dir / "recognized_lyrics.txt"
        score_file = artifact_dir / "vocalparse_score.json"
        lyrics_file.write_text(lyrics + "\n", encoding="utf-8")
        shutil.copy2(cached, score_file)
        report("review", 100, "识别完成，请人工校对后再开始改词翻唱")
        return lyrics_file
