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
