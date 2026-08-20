from __future__ import annotations

import subprocess
import locale
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class BackendStatus:
    backend_id: str
    name: str
    installed: bool
    runnable: bool
    version: str
    detail: str


class BackendUnavailable(RuntimeError):
    pass


def _decode_output(data: bytes | None) -> str:
    if not data:
        return ""
    candidates = ["utf-8", locale.getpreferredencoding(False), "gb18030"]
    for encoding in dict.fromkeys(candidates):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def run_checked(
    args: list[str], cwd: Path, timeout: int = 3600, env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=False,
            timeout=timeout, check=False, shell=False,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"后端运行超过 {timeout} 秒，已终止") from exc
    stdout, stderr = _decode_output(result.stdout), _decode_output(result.stderr)
    if result.returncode:
        detail = (stderr or stdout or "后端未提供错误信息").strip()
        raise RuntimeError(f"后端退出码 {result.returncode}：{detail[-4000:]}")
    return subprocess.CompletedProcess(result.args, result.returncode, stdout, stderr)


def run_checked_streaming(
    args: list[str], cwd: Path, on_stdout_line: Callable[[str], None] | None = None, timeout: int = 3600,
) -> subprocess.CompletedProcess[str]:
    """Run a backend while forwarding complete stdout lines without pipe deadlocks."""
    process = subprocess.Popen(
        args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    messages: queue.Queue[tuple[str, bytes]] = queue.Queue()

    def read_stream(channel: str, stream: object) -> None:
        assert hasattr(stream, "readline")
        for raw in iter(stream.readline, b""):  # type: ignore[attr-defined]
            messages.put((channel, raw))

    threads = [
        threading.Thread(target=read_stream, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=read_stream, args=("stderr", process.stderr), daemon=True),
    ]
    for thread in threads:
        thread.start()
    captured: dict[str, list[str]] = {"stdout": [], "stderr": []}
    started = time.monotonic()
    try:
        while process.poll() is None or any(thread.is_alive() for thread in threads) or not messages.empty():
            if time.monotonic() - started > timeout:
                process.kill()
                raise RuntimeError(f"后端运行超过 {timeout} 秒，已终止")
            try:
                channel, raw = messages.get(timeout=0.1)
            except queue.Empty:
                continue
            line = _decode_output(raw)
            captured[channel].append(line)
            if channel == "stdout" and on_stdout_line is not None:
                on_stdout_line(line.rstrip("\r\n"))
    finally:
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                stream.close()
        for thread in threads:
            thread.join(timeout=1)
    returncode = process.wait()
    stdout, stderr = "".join(captured["stdout"]), "".join(captured["stderr"])
    if returncode:
        detail = (stderr or stdout or "后端未提供错误信息").strip()
        raise RuntimeError(f"后端退出码 {returncode}：{detail[-4000:]}")
    return subprocess.CompletedProcess(args, returncode, stdout, stderr)
