from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from opencover.storage.database import Database
from opencover.models.registry import ModelRegistry
from opencover.adapters.base import _decode_output
from .worker_protocol import WorkerEvent

LOG = logging.getLogger(__name__)


class JobManager(QObject):
    event = Signal(str, object)
    finished = Signal(str, bool)

    def __init__(self, database: Database, root: Path, parent: QObject | None = None):
        super().__init__(parent)
        self.database = database
        self.root = root
        self.processes: dict[str, QProcess] = {}
        self.buffers: dict[str, str] = {}

    def submit_original(self, payload: dict[str, object]) -> str:
        job_id = uuid.uuid4().hex
        record = {"id": job_id, "kind": "original", **payload}
        return self._submit(record, "opencover.workers.original_cover_worker")

    def submit_preview(self, model_id: str) -> str:
        model = ModelRegistry(self.root / "weights").get(model_id)
        if model is None:
            raise ValueError("找不到所选音色")
        source = self.root / "assets" / "preview_sources" / "neutral_melody.wav"
        if not source.is_file():
            raise FileNotFoundError("标准试听干声未安装")
        job_id = uuid.uuid4().hex
        record = {
            "id": job_id,
            "kind": "preview",
            "root": str(self.root),
            "input_path": str(source),
            "engine": model.engine,
            "model_id": model.id,
            "options": {},
        }
        return self._submit(record, "opencover.workers.preview_worker")

    def submit_lyric(self, payload: dict[str, object]) -> str:
        job_id = uuid.uuid4().hex
        record = {"id": job_id, "kind": "lyric", **payload}
        return self._submit(record, "opencover.workers.lyric_cover_worker")

    def _submit(self, record: dict[str, object], source_module: str) -> str:
        job_id = str(record["id"])
        self.database.create_job(record)
        job_dir = self.root / "workspace" / "jobs" / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        request_path = job_dir / "request.json"
        request_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        process = QProcess(self)
        if os.name == "nt" and hasattr(process, "setCreateProcessArgumentsModifier"):
            def hide_console(arguments):  # type: ignore[no-untyped-def]
                arguments.flags |= 0x08000000  # CREATE_NO_WINDOW
            process.setCreateProcessArgumentsModifier(hide_console)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.setWorkingDirectory(str(self.root))
        environment = QProcessEnvironment.systemEnvironment()
        source_dir = str(self.root / "src")
        environment.insert("PYTHONPATH", source_dir + os.pathsep + environment.value("PYTHONPATH"))
        process.setProcessEnvironment(environment)
        process.readyReadStandardOutput.connect(lambda jid=job_id: self._read(jid))
        process.readyReadStandardError.connect(lambda jid=job_id: self._read_error(jid))
        process.finished.connect(lambda code, status, jid=job_id: self._done(jid, code))
        self.processes[job_id] = process
        self.buffers[job_id] = ""
        self.database.update_job(job_id, status="running", stage="validate")
        if getattr(sys, "frozen", False):
            worker = self.root / "OpenCoverStudioWorker.exe"
            if not worker.is_file():
                self.database.update_job(job_id, status="failed", error="发行包缺少 OpenCoverStudioWorker.exe")
                self.processes.pop(job_id, None); self.buffers.pop(job_id, None)
                raise FileNotFoundError("发行包缺少 OpenCoverStudioWorker.exe")
            process.start(str(worker), [str(request_path)])
        else:
            process.start(sys.executable, ["-m", source_module, str(request_path)])
        return job_id

    def cancel(self, job_id: str) -> None:
        process = self.processes.get(job_id)
        if process and process.state() != QProcess.ProcessState.NotRunning:
            self.database.update_job(job_id, status="cancelled", error="用户取消")
            pid = int(process.processId())
            if os.name == "nt" and pid > 0:
                subprocess.run(
                    ["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                    capture_output=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), shell=False,
                )
            else:
                process.terminate()
                if not process.waitForFinished(3000):
                    process.kill()

    def running(self) -> bool:
        return any(p.state() != QProcess.ProcessState.NotRunning for p in self.processes.values())

    def _read(self, job_id: str) -> None:
        process = self.processes[job_id]
        text = _decode_output(bytes(process.readAllStandardOutput()))
        self.buffers[job_id] += text
        while "\n" in self.buffers[job_id]:
            line, self.buffers[job_id] = self.buffers[job_id].split("\n", 1)
            try:
                event = WorkerEvent.parse_line(line)
            except (ValueError, json.JSONDecodeError):
                LOG.warning("无效 worker 输出: %s", line)
                continue
            update: dict[str, object] = {}
            if event.type == "progress":
                update = {"progress": event.value or 0, "stage": event.stage}
            elif event.type == "result":
                update = {"status": "completed", "progress": 100, "output_path": event.path}
            elif event.type == "error":
                update = {"status": "failed", "error": event.message}
            if update:
                self.database.update_job(job_id, **update)
            self.event.emit(job_id, event)

    def _read_error(self, job_id: str) -> None:
        error = _decode_output(bytes(self.processes[job_id].readAllStandardError())).strip()
        if error:
            LOG.error("worker %s stderr: %s", job_id, error)

    def _done(self, job_id: str, exit_code: int) -> None:
        rows = [row for row in self.database.list_jobs() if row["id"] == job_id]
        success = bool(rows and rows[0]["status"] == "completed" and exit_code == 0)
        if rows and rows[0]["status"] == "running":
            self.database.update_job(job_id, status="failed", error=f"工作进程异常退出（{exit_code}）")
        self.finished.emit(job_id, success)
        self.processes.pop(job_id, None)
        self.buffers.pop(job_id, None)
