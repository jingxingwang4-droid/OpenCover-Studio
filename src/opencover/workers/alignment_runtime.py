from __future__ import annotations

import json
import os
import sys
import time
import warnings
from pathlib import Path


def _ffmpeg_directory(root: Path) -> Path | None:
    candidates = [root / "ffmpeg" / "bin" / "ffmpeg.exe", *root.glob("ffmpeg/*/bin/ffmpeg.exe")]
    executable = next((path for path in candidates if path.is_file()), None)
    return executable.parent if executable else None


def main(request_file: str) -> int:
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    root = Path(request["root"]).resolve()
    audio = Path(request["audio_path"]).resolve()
    output = Path(request["output_path"]).resolve()
    model_path = root / "external_backends" / "alignment" / "models" / "base.pt"
    if not audio.is_file() or not model_path.is_file():
        raise RuntimeError("对齐输入音频或 Whisper base 模型缺失")
    ffmpeg_dir = _ffmpeg_directory(root)
    if ffmpeg_dir:
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")

    import torch
    import stable_whisper

    if not torch.cuda.is_available():
        raise RuntimeError("歌词对齐 CUDA 运行时不可用")
    started = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    warnings.filterwarnings(
        "ignore",
        message="The installed version of Whisper might be incompatible.*",
        module="stable_whisper.whisper_compatibility",
    )
    model = stable_whisper.load_model(str(model_path), device="cuda")
    result = model.align(
        str(audio), str(request["text"]), language=str(request["language"]),
        original_split=True, failure_threshold=0.2, verbose=None,
    )
    if result is None:
        raise RuntimeError("Whisper 没有产生歌词对齐结果")
    data = result.to_dict()
    segments = data.get("segments") or []
    if not segments:
        raise RuntimeError("Whisper 对齐结果没有有效分段")
    lines = [line.strip() for line in str(request["text"]).splitlines() if line.strip()]
    if len(segments) != len(lines):
        raise RuntimeError(f"Whisper 返回 {len(segments)} 段，但原歌词有 {len(lines)} 行")
    last_start = -1.0
    for segment in segments:
        start, end = float(segment["start"]), float(segment["end"])
        if start < 0 or end <= start or start <= last_start:
            raise RuntimeError("Whisper 返回了无效或非递增的句级时间")
        last_start = start
    data["runtime"] = {
        "seconds": time.perf_counter() - started,
        "max_cuda_bytes": torch.cuda.max_memory_allocated(),
        "language": request["language"],
        "model": "base",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + ".part")
    partial.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    partial.replace(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
