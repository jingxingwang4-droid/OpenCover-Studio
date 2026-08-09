from __future__ import annotations

import subprocess
import locale
from dataclasses import dataclass
from pathlib import Path


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


def run_checked(args: list[str], cwd: Path, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args, cwd=cwd, capture_output=True, text=False,
            timeout=timeout, check=False, shell=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"后端运行超过 {timeout} 秒，已终止") from exc
    stdout, stderr = _decode_output(result.stdout), _decode_output(result.stderr)
    if result.returncode:
        detail = (stderr or stdout or "后端未提供错误信息").strip()
        raise RuntimeError(f"后端退出码 {result.returncode}：{detail[-4000:]}")
    return subprocess.CompletedProcess(result.args, result.returncode, stdout, stderr)
