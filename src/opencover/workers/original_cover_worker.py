from __future__ import annotations

import json
import sys
from pathlib import Path

from opencover.models.registry import ModelRegistry
from opencover.core.retry_policy import is_cuda_oom
from opencover.pipelines.original_cover import CoverRequest, OriginalCoverPipeline


def emit(kind: str, **data: object) -> None:
    payload = json.dumps({"type": kind, **data}, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(payload.encode("utf-8")); sys.stdout.buffer.flush()


def main(request_file: str) -> int:
    try:
        data = json.loads(Path(request_file).read_text(encoding="utf-8"))
        root = Path(data["root"]).resolve()
        voice = ModelRegistry(root / "weights").get(str(data["model_id"]))
        if not voice:
            raise RuntimeError("找不到所选音色")
        options = data.get("options", {})
        request = CoverRequest(
            input_path=Path(data["input_path"]), engine=str(data["engine"]), voice=voice,
            pitch=int(options.get("pitch", 0)), balance=str(options.get("balance", "均衡")),
            output_format=str(options.get("output_format", "wav")),
            memory_profile=str(options.get("memory_profile", "标准")),
        )
        emit("status", message="正在检查组件")
        pipeline = OriginalCoverPipeline(root)
        issues = pipeline.preflight(request)
        if issues:
            emit("error", code="PREFLIGHT_FAILED", message="；".join(issues))
            return 2
        job_dir = Path(request_file).resolve().parent

        def report(stage: str, value: int, message: str) -> None:
            emit("status", message=message)
            emit("progress", stage=stage, value=value)

        output = pipeline.run(request, job_dir, report)
        emit("result", path=str(output))
        return 0
    except Exception as exc:
        emit("error", code="CUDA_OOM" if is_cuda_oom(exc) else "WORKER_ERROR", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
