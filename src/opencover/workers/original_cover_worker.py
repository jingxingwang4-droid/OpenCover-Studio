from __future__ import annotations

import json
import sys
from pathlib import Path

from opencover.models.registry import ModelRegistry
from opencover.pipelines.original_cover import CoverRequest, OriginalCoverPipeline


def emit(kind: str, **data: object) -> None:
    print(json.dumps({"type": kind, **data}, ensure_ascii=False), flush=True)


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
        )
        emit("status", message="正在检查组件")
        pipeline = OriginalCoverPipeline(root)
        issues = pipeline.preflight(request)
        if issues:
            emit("error", code="PREFLIGHT_FAILED", message="；".join(issues))
            return 2
        # No backend output may be synthesized until every resource has passed its own smoke test.
        emit("error", code="BACKEND_NOT_VALIDATED", message="组件存在但尚未完成本机真实推理验证，已安全停止")
        return 3
    except Exception as exc:
        emit("error", code="WORKER_ERROR", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
