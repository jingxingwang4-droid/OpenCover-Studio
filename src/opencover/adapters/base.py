from __future__ import annotations

import subprocess
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


def run_checked(args: list[str], cwd: Path, timeout: int = 3600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, check=True, shell=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
