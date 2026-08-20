from __future__ import annotations

import json
import sys
from pathlib import Path

import app
from opencover.adapters import backends
from opencover.adapters.base import run_checked


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


def test_backend_error_includes_captured_stderr(tmp_path: Path) -> None:
    script = tmp_path / "failure.py"
    script.write_text("import sys; print('具体失败原因', file=sys.stderr); raise SystemExit(7)", encoding="utf-8")
    try:
        run_checked([sys.executable, str(script)], tmp_path)
    except RuntimeError as exc:
        assert "退出码 7" in str(exc)
        assert "具体失败原因" in str(exc)
    else:
        raise AssertionError("后端失败必须抛出包含 stderr 的异常")


def test_alignment_adapter_requires_verified_runtime_and_output(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "alignment"
    python = root / "runtime" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_bytes(b"python")
    (root / "runtime" / "Lib" / "site-packages" / "stable_whisper").mkdir(parents=True)
    (root / "models").mkdir()
    (root / "models" / "base.pt").write_bytes(b"model")
    (root / "backend.json").write_text(json.dumps({"smoke_test_passed": True, "commit": "verified"}), encoding="utf-8")
    runner = tmp_path / "alignment_runtime.py"; runner.write_text("", encoding="utf-8")
    output = tmp_path / "alignment.json"
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"output_path": str(output)}), encoding="utf-8")

    def fake_run(args: list[str], cwd: Path, timeout: int = 3600) -> None:
        assert args[0] == str(python)
        assert timeout == 3600
        output.write_text('{"segments":[{"start":0,"end":1}]}', encoding="utf-8")

    monkeypatch.setattr(backends, "run_checked", fake_run)
    adapter = backends.AlignmentAdapter(root)
    assert adapter.status().runnable is True
    assert adapter.align(request, runner) == output


def test_uvr5_rejects_launcher_with_deleted_base_python(tmp_path: Path) -> None:
    root = tmp_path / "uvr5"
    runtime = root / "runtime" / "Scripts" / "python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"launcher")
    (root / "runtime" / "Lib" / "site-packages" / "audio_separator").mkdir(parents=True)
    (root / "runtime" / "pyvenv.cfg").write_text(
        f"home = {tmp_path / 'deleted-python'}\nversion_info = 3.10\n",
        encoding="utf-8",
    )
    model_dir = root / "models_runtime"
    model_dir.mkdir()
    adapter = backends.UVR5Adapter(root, tmp_path / "ffmpeg")
    adapter.ffmpeg_bin.mkdir()
    for model in adapter.model_paths:
        model.write_bytes(b"model" * 300)
    (root / "backend.json").write_text(
        json.dumps({"smoke_test_passed": True, "pipeline_id": adapter.pipeline_id}),
        encoding="utf-8",
    )

    status = adapter.status()

    assert status.installed is True
    assert status.runnable is False
    assert "运行时已丢失或断链" in status.detail


def test_uvr5_rejects_broken_launcher_even_with_existing_base_python(tmp_path: Path) -> None:
    root = tmp_path / "uvr5"
    runtime = root / "runtime" / "Scripts" / "python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"launcher")
    (root / "runtime" / "Lib" / "site-packages" / "audio_separator").mkdir(parents=True)
    base = tmp_path / "python-base"
    base.mkdir()
    (base / "python.exe").write_bytes(b"python")
    (root / "runtime" / "pyvenv.cfg").write_text(
        f"home = {base}\nversion_info = 3.10\n",
        encoding="utf-8",
    )
    model_dir = root / "models_runtime"
    model_dir.mkdir()
    adapter = backends.UVR5Adapter(root, tmp_path / "ffmpeg")
    adapter.ffmpeg_bin.mkdir()
    for model in adapter.model_paths:
        model.write_bytes(b"model" * 300)
    (root / "backend.json").write_text(
        json.dumps({"smoke_test_passed": True, "pipeline_id": adapter.pipeline_id}),
        encoding="utf-8",
    )

    status = adapter.status()
    assert status.installed is True
    assert status.runnable is False
    assert "运行时已丢失或断链" in status.detail


def test_uvr5_accepts_working_launcher(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "uvr5"
    runtime = root / "runtime" / "Scripts" / "python.exe"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"launcher")
    (root / "runtime" / "Lib" / "site-packages" / "audio_separator").mkdir(parents=True)
    base = tmp_path / "python-base"
    base.mkdir()
    (base / "python.exe").write_bytes(b"python")
    (root / "runtime" / "pyvenv.cfg").write_text(
        f"home = {base}\nversion_info = 3.10\n",
        encoding="utf-8",
    )
    model_dir = root / "models_runtime"
    model_dir.mkdir()
    adapter = backends.UVR5Adapter(root, tmp_path / "ffmpeg")
    adapter.ffmpeg_bin.mkdir()
    for model in adapter.model_paths:
        model.write_bytes(b"model" * 300)
    (root / "backend.json").write_text(
        json.dumps({"smoke_test_passed": True, "pipeline_id": adapter.pipeline_id}),
        encoding="utf-8",
    )
    monkeypatch.setattr(backends, "_python_launcher_available", lambda runtime: True)

    assert adapter.status().runnable is True


def test_runtime_python_prefers_portable_interpreter(tmp_path: Path) -> None:
    root = tmp_path / "backend"
    portable = root / "runtime" / "python.exe"
    portable.parent.mkdir(parents=True)
    portable.write_bytes(b"portable")
    legacy = root / "runtime" / "Scripts" / "python.exe"
    legacy.parent.mkdir()
    legacy.write_bytes(b"legacy trampoline")

    assert backends._runtime_python(root) == portable
