from __future__ import annotations

import json
import sys
from pathlib import Path

from opencover.core.retry_policy import is_cuda_oom
from opencover.pipelines.lyric_recognition import LyricRecognitionPipeline, LyricRecognitionRequest


def emit(kind: str, **data: object) -> None:
    payload = json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(payload.encode("utf-8"))
    sys.stdout.buffer.flush()


def main(request_file: str) -> int:
    try:
        data = json.loads(Path(request_file).read_text(encoding="utf-8"))
        root = Path(str(data["root"])).resolve()
        request = LyricRecognitionRequest(Path(str(data["input_path"])).resolve())
        pipeline = LyricRecognitionPipeline(root)
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
        emit(
            "error",
            code="CUDA_OOM" if is_cuda_oom(exc) else "LYRIC_RECOGNITION_ERROR",
            message=str(exc),
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
