from __future__ import annotations

import json
import sys
from pathlib import Path


def emit_error(code: str, message: str) -> None:
    payload = json.dumps({"type": "error", "code": code, "message": message}, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(payload.encode("utf-8")); sys.stdout.buffer.flush()


def main() -> int:
    if len(sys.argv) != 2:
        emit_error("BAD_ARGUMENTS", "缺少任务请求文件")
        return 2
    request_path = Path(sys.argv[1])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
    except Exception as exc:
        emit_error("BAD_REQUEST", str(exc))
        return 2
    kind = request.get("kind")
    if kind == "preview":
        from opencover.workers.preview_worker import main as worker_main
    elif kind == "lyric":
        from opencover.workers.lyric_cover_worker import main as worker_main
    elif kind == "original":
        from opencover.workers.original_cover_worker import main as worker_main
    else:
        emit_error("BAD_KIND", f"未知任务类型：{kind}")
        return 2
    return worker_main(str(request_path))


if __name__ == "__main__":
    raise SystemExit(main())
