from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, input_path TEXT NOT NULL,
 engine TEXT NOT NULL, model_id TEXT NOT NULL, status TEXT NOT NULL,
 progress INTEGER NOT NULL DEFAULT 0, stage TEXT, output_path TEXT,
 error TEXT, options_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_job(self, job: dict[str, object]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO jobs(id,kind,input_path,engine,model_id,status,options_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (job["id"], job["kind"], job["input_path"], job["engine"], job["model_id"],
                 "pending", json.dumps(job.get("options", {}), ensure_ascii=False), now, now),
            )

    def update_job(self, job_id: str, **fields: object) -> None:
        allowed = {"status", "progress", "stage", "output_path", "error"}
        selected = {k: v for k, v in fields.items() if k in allowed}
        if not selected:
            return
        selected["updated_at"] = datetime.now(timezone.utc).isoformat()
        sql = ",".join(f"{key}=?" for key in selected)
        with self.connect() as conn:
            conn.execute(f"UPDATE jobs SET {sql} WHERE id=?", (*selected.values(), job_id))

    def list_jobs(self, limit: int = 100) -> list[dict[str, object]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get_job(self, job_id: str) -> dict[str, object] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def delete_job(self, job_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))

    def recover_interrupted_jobs(self) -> int:
        """Turn stale in-flight rows from a previous application process into honest failures."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE status IN ('pending','running')",
                ("应用上次退出时任务仍在运行；可在任务记录中重新生成", now),
            )
        return max(0, cursor.rowcount)
