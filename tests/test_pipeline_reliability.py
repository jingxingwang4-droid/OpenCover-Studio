from pathlib import Path
import os
import subprocess
import sys

import numpy as np
import pytest
import soundfile as sf
from PySide6.QtCore import QProcess

from opencover.audio.processing import AudioError, audio_cache_valid, export_audio, validate_audio
from opencover.core.job_manager import JobManager
from opencover.storage.database import Database
from opencover.pipelines.validation import cover_option_issues


def test_audio_rejects_nonfinite_silent_and_wrong_duration(tmp_path):
    path = tmp_path / "audio.wav"
    sf.write(path, np.zeros(16000), 16000)
    assert audio_cache_valid(path)  # Silent accompaniment is allowed.
    assert not audio_cache_valid(path, require_signal=True)
    sf.write(path, np.full(16000, 0.2), 16000)
    assert audio_cache_valid(path, require_signal=True, expected_duration=1)
    assert not audio_cache_valid(path, expected_duration=2)
    sf.write(path, np.full(16000, np.nan), 16000, subtype="FLOAT")
    assert not audio_cache_valid(path)
    path.write_bytes(b"corrupt" * 1000)
    assert not audio_cache_valid(path)


def test_export_failure_preserves_existing_output(tmp_path, monkeypatch):
    source, target = tmp_path / "input.wav", tmp_path / "output.wav"
    sf.write(source, np.full(16000, 0.2), 16000)
    target.write_bytes(b"accepted output")

    def fail(source, output, ffmpeg):
        output.write_bytes(b"partial")
        raise AudioError("interrupted")

    monkeypatch.setattr("opencover.audio.processing._export_audio_file", fail)
    with pytest.raises(AudioError):
        export_audio(source, target, Path("ffmpeg"))
    assert target.read_bytes() == b"accepted output"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["input.wav", "output.wav"]


def test_export_cannot_overwrite_source(tmp_path):
    source = tmp_path / "input.wav"
    sf.write(source, np.full(16000, 0.2), 16000)
    with pytest.raises(AudioError, match="覆盖"):
        export_audio(source, source, Path("ffmpeg"))
    validate_audio(source)


@pytest.mark.parametrize("pitch,balance,fmt,profile", [(13, "均衡", "wav", "标准"), (0, "bad", "wav", "标准"), (0, "均衡", "exe", "标准"), (0, "均衡", "wav", "bad")])
def test_shared_options_reject_invalid_inputs(pitch, balance, fmt, profile):
    assert cover_option_issues(pitch, balance, fmt, profile)


@pytest.mark.parametrize("status,exit_code,expected", [("completed", 1, "failed"), ("completed", 0, "completed"), ("cancelled", 0, "cancelled"), ("running", 0, "failed")])
def test_job_exit_finalizes_database(qapp, tmp_path, monkeypatch, status, exit_code, expected):
    db = Database(tmp_path / "jobs.sqlite")
    manager = JobManager(db, tmp_path)
    db.create_job(dict(id="old", kind="original", input_path="a", engine="rvc", model_id="b"))
    db.update_job("old", status=status)
    # A task must still finalize after more than 100 newer records exist.
    for n in range(101):
        db.create_job(dict(id=str(n), kind="original", input_path="a", engine="rvc", model_id="b"))
    manager.processes["old"] = QProcess(manager)
    manager.buffers["old"] = ""
    monkeypatch.setattr(manager, "_read", lambda jid: None)
    monkeypatch.setattr(manager, "_read_error", lambda jid: None)
    manager._done("old", exit_code)
    assert db.get_job("old")["status"] == expected
    assert "old" not in manager.processes


def test_job_failed_start_is_terminal(qapp, tmp_path, monkeypatch):
    db = Database(tmp_path / "jobs.sqlite")
    manager = JobManager(db, tmp_path)
    db.create_job(dict(id="bad", kind="original", input_path="a", engine="rvc", model_id="b"))
    manager.processes["bad"] = QProcess(manager)
    manager.buffers["bad"] = ""
    monkeypatch.setattr(manager, "_read", lambda jid: None)
    monkeypatch.setattr(manager, "_read_error", lambda jid: None)
    manager._process_error("bad", QProcess.ProcessError.FailedToStart)
    assert db.get_job("bad")["status"] == "failed"
    assert not manager.processes


@pytest.mark.parametrize("frozen", [False, True])
def test_generation_code_hash_is_stable_across_workers(frozen):
    code = "from opencover.pipelines.lyric_cover import module_hash; "
    if frozen:
        code += (
            "import importlib.util, types; "
            "compiled=compile('options={\\\"rvc\\\",\\\"native\\\",\\\"ddsp\\\"}', 'embedded.py', 'exec'); "
            "importlib.util.find_spec=lambda name: types.SimpleNamespace(loader=types.SimpleNamespace(get_source=lambda name:None,get_code=lambda name:compiled)); "
        )
    code += "print(module_hash('opencover.pipelines.lyric_cover'))"
    values = [subprocess.check_output([sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": seed}) for seed in ("1", "2")]
    assert values[0] == values[1]
