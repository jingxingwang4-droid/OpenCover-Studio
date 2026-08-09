from __future__ import annotations

import json
import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer

from opencover.core.job_manager import JobManager
from opencover.storage.database import Database


def main(root_arg: str, cancel_test: bool = False) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = Path(root_arg).resolve()
    app = QCoreApplication([])
    database = Database(root / "workspace" / "job-manager-smoke.sqlite")
    manager = JobManager(database, root, app)
    events: list[str] = []
    manager.event.connect(lambda job_id, event: events.append(event.type))
    result: dict[str, object] = {"finished": False}

    def finished(job_id: str, success: bool) -> None:
        result.update({"finished": True, "success": success, "job": database.get_job(job_id), "events": events})
        app.quit()

    manager.finished.connect(finished)
    setattr(sys, "frozen", True)
    job_id = manager.submit_lyric({
        "root": str(root),
        "input_path": str(root / "assets" / "preview_sources" / "neutral_melody.wav"),
        "engine": "rvc",
        "model_id": "toyokawa_sakiko_rvc",
        "options": {
            "original_lyrics": "啦啦啦啦啦啦啦啦啦啦",
            "new_lyrics": "取消测试正在眼前，听见花开的声音" if cancel_test else "新的春天正在眼前，听见花开的声音",
            "strategy": "强制", "pitch": 0, "balance": "均衡", "output_format": "wav",
        },
    })
    if cancel_test:
        QTimer.singleShot(12_000, lambda: manager.cancel(job_id))
    QTimer.singleShot(45_000, app.quit)
    app.exec()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    job = result.get("job") or {}
    if cancel_test:
        return 0 if isinstance(job, dict) and job.get("status") == "cancelled" and not manager.running() else 1
    return 0 if result.get("success") and "result" in events else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("root"); parser.add_argument("--cancel", action="store_true")
    arguments = parser.parse_args()
    raise SystemExit(main(arguments.root, arguments.cancel))
