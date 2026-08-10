from pathlib import Path

from opencover.storage.database import Database


def test_job_lifecycle(tmp_path: Path) -> None:
    db = Database(tmp_path / "状态.sqlite")
    db.create_job({"id": "abc", "kind": "original", "input_path": "中文/歌.wav", "engine": "rvc", "model_id": "voice", "options": {}})
    db.update_job("abc", status="running", progress=40, stage="convert")
    job = db.list_jobs()[0]
    assert job["status"] == "running"
    assert job["progress"] == 40
    assert job["input_path"] == "中文/歌.wav"


def test_interrupted_jobs_are_recovered_without_touching_completed(tmp_path: Path) -> None:
    db = Database(tmp_path / "state.sqlite")
    base = {"kind": "original", "input_path": "song.wav", "engine": "rvc", "model_id": "voice", "options": {}}
    db.create_job({"id": "running", **base}); db.update_job("running", status="running")
    db.create_job({"id": "done", **base}); db.update_job("done", status="completed", output_path="done.wav")
    assert db.recover_interrupted_jobs() == 1
    assert db.get_job("running")["status"] == "failed"
    assert "上次退出" in str(db.get_job("running")["error"])
    assert db.get_job("done")["status"] == "completed"
