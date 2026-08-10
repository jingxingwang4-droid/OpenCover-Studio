from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opencover.lyrics.processing import timed_lyrics_from_alignment


DEFAULT_TEXT = (
    "And so my fellow Americans, ask not what your country can do for you, "
    "ask what you can do for your country."
)
STABLE_COMMIT = "e312072cc024ae9fceb25b057d7d18524873a02b"
WHISPER_COMMIT = "5f86d1d86363843179951550570367b37c5d6f78"
MODEL_SHA256 = "ed3a0b6b1c0edf879ad9b11b1af5a0e6ab5db9205f891f668f8b0e6c6326e34e"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audio_duration(root: Path, audio: Path) -> float:
    candidates = [root / "ffmpeg" / "bin" / "ffprobe.exe", *root.glob("ffmpeg/*/bin/ffprobe.exe")]
    ffprobe = next((path for path in candidates if path.is_file()), None)
    if ffprobe is None:
        raise RuntimeError("项目 FFprobe 缺失")
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(audio)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=False, shell=False,
    )
    if result.returncode:
        raise RuntimeError("FFprobe 无法读取测试音频时长")
    return float(result.stdout.strip())


def main(
    root_arg: str, audio_arg: str | None, text: str, language: str,
    mark_verified: bool, max_instant_words: int,
) -> int:
    root = Path(root_arg).resolve()
    backend = root / "external_backends" / "alignment"
    runtime = backend / "runtime" / "Scripts" / "python.exe"
    model = backend / "models" / "base.pt"
    runner = root / "src" / "opencover" / "workers" / "alignment_runtime.py"
    audio = Path(audio_arg).resolve() if audio_arg else backend / "whisper" / "tests" / "jfk.flac"
    if not all(path.is_file() for path in (runtime, model, runner, audio)):
        raise RuntimeError("歌词对齐 runtime、模型、runner 或测试音频缺失")
    if sha256(model) != MODEL_SHA256:
        raise RuntimeError("Whisper base 模型 SHA256 不匹配")
    target = root / "workspace" / "test_outputs" / "alignment"
    target.mkdir(parents=True, exist_ok=True)
    request_file = target / "request.json"
    output_file = target / "alignment.json"
    request_file.write_text(json.dumps({
        "root": str(root), "audio_path": str(audio), "text": text,
        "language": language, "output_path": str(output_file),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    started = time.perf_counter()
    process = subprocess.run(
        [str(runtime), "-X", "utf8", str(runner), str(request_file)],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=3600, check=False,
    )
    if process.returncode:
        raise RuntimeError((process.stderr or process.stdout or "对齐后端失败")[-4000:])
    data = json.loads(output_file.read_text(encoding="utf-8"))
    duration = audio_duration(root, audio)
    timed = timed_lyrics_from_alignment(text, data, duration)
    words = [word for segment in data["segments"] for word in segment.get("words", [])]
    instant_words = sum(float(word["end"]) <= float(word["start"]) for word in words)
    if not words or instant_words > max_instant_words:
        raise RuntimeError(f"对齐结果有 {instant_words} 个零时长词，超过允许值 {max_instant_words}")
    evidence = {
        "elapsed_seconds": time.perf_counter() - started,
        "audio": str(audio),
        "audio_sha256": sha256(audio),
        "output": str(output_file),
        "output_sha256": sha256(output_file),
        "segments": len(data["segments"]),
        "words": len(words),
        "instant_words": instant_words,
        "start": words[0]["start"],
        "end": words[-1]["end"],
        "timed_lyrics": timed,
        **data.get("runtime", {}),
    }
    if mark_verified:
        (backend / "backend.json").write_text(json.dumps({
            "backend": "alignment",
            "version": "Stable-ts 2.19.1 / OpenAI Whisper 20250625 / base",
            "commit": STABLE_COMMIT,
            "whisper_commit": WHISPER_COMMIT,
            "model_sha256": MODEL_SHA256,
            "runtime": "Python 3.10.20 / torch 2.9.1+cu130",
            "device": "NVIDIA GeForce RTX 5070 Ti Laptop GPU",
            "smoke_test_passed": True,
            "smoke_test_date": "2026-08-10",
            "detail": "Whisper base 已在 CUDA 上对官方 JFK 音频完成给定原文逐词强制对齐",
            "evidence": evidence,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--audio")
    parser.add_argument("--text", default=DEFAULT_TEXT)
    parser.add_argument("--language", default="en")
    parser.add_argument("--mark-verified", action="store_true")
    parser.add_argument("--max-instant-words", type=int, default=0)
    args = parser.parse_args()
    raise SystemExit(main(
        args.root, args.audio, args.text, args.language,
        args.mark_verified, args.max_instant_words,
    ))
