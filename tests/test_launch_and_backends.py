from __future__ import annotations

import json
import sys
from pathlib import Path

import app
from opencover.adapters import backends


def test_source_launcher_restarts_with_project_pythonw(tmp_path: Path, monkeypatch) -> None:
    pythonw = tmp_path / ".venv" / "Scripts" / "pythonw.exe"
    pythonw.parent.mkdir(parents=True)
    pythonw.write_bytes(b"launcher")
    system_python = tmp_path / "system-python.exe"
    system_python.write_bytes(b"python")
    launches: list[tuple[list[str], dict[str, object]]] = []

    monkeypatch.setattr(app, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "executable", str(system_python))
    monkeypatch.delenv("OPENCOVER_BOOTSTRAPPED", raising=False)
    monkeypatch.setattr(
        app.subprocess,
        "Popen",
        lambda args, **kwargs: launches.append((args, kwargs)),
    )

    assert app._restart_in_project_environment() is True
    assert launches[0][0][0] == str(pythonw)
    assert launches[0][1]["cwd"] == str(tmp_path)
    assert launches[0][1]["env"]["OPENCOVER_BOOTSTRAPPED"] == "1"


def test_rvc_adapter_uses_real_cli_module(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "rvc"
    python = root / "runtime" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    (root / "source").mkdir()
    (root / "backend.json").write_text(
        json.dumps({"smoke_test_passed": True, "commit": "verified"}),
        encoding="utf-8",
    )
    output = tmp_path / "out.wav"
    calls: list[tuple[list[str], Path]] = []

    def fake_run(args: list[str], cwd: Path) -> None:
        calls.append((args, cwd))
        output.write_bytes(b"RIFF" + b"\0" * 2048)

    monkeypatch.setattr(backends, "run_checked", fake_run)
    adapter = backends.RVCAdapter(root)
    adapter.convert(tmp_path / "输入.wav", output, tmp_path / "voice.pth", 0)

    assert calls[0][0][1:4] == ["-m", "rvc.wrapper.cli.cli", "infer"]
    assert calls[0][1] == root
