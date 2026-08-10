from __future__ import annotations

import json
import sys
from pathlib import Path

from opencover.models.registry import ModelRegistry
from opencover.core.retry_policy import is_cuda_oom
from opencover.pipelines.lyric_cover import LyricCoverPipeline, LyricCoverRequest


def emit(kind: str, **data: object) -> None:
    payload = json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(payload.encode("utf-8")); sys.stdout.buffer.flush()


def main(request_file: str) -> int:
    try:
        data = json.loads(Path(request_file).read_text(encoding="utf-8"))
        root = Path(data["root"]).resolve()
        voice = ModelRegistry(root / "weights").get(str(data["model_id"]))
        if voice is None:
            raise RuntimeError("找不到所选音色")
        options = data.get("options", {})
        request = LyricCoverRequest(
            input_path=Path(data["input_path"]), engine=str(data["engine"]), voice=voice,
            original_lyrics=str(options.get("original_lyrics", "")), new_lyrics=str(options.get("new_lyrics", "")),
            strategy=str(options.get("strategy", "均衡")), pitch=int(options.get("pitch", 0)),
            balance=str(options.get("balance", "均衡")), output_format=str(options.get("output_format", "wav")),
            generator=str(options.get("generator", "auto")),
            memory_profile=str(options.get("memory_profile", "标准")),
        )
        emit("status", message="正在检查改词组件")
        pipeline = LyricCoverPipeline(root)
        issues = pipeline.preflight(request)
        if issues:
            emit("error", code="PREFLIGHT_FAILED", message="；".join(issues))
            return 2

        def report(stage: str, value: int, message: str) -> None:
            emit("status", message=message)
            emit("progress", stage=stage, value=value)

        output = pipeline.run(request, Path(request_file).resolve().parent, report)
        emit("result", path=str(output))
        return 0
    except Exception as exc:
        emit("error", code="CUDA_OOM" if is_cuda_oom(exc) else "LYRIC_WORKER_ERROR", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
