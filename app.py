from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))


def _restart_in_project_environment() -> bool:
    """Relaunch a double-clicked source entry with the project's GUI Python."""
    if getattr(sys, "frozen", False) or os.environ.get("OPENCOVER_BOOTSTRAPPED") == "1":
        return False
    pythonw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
        return False
    current = Path(sys.executable).resolve()
    venv_python = ROOT / ".venv" / "Scripts" / "python.exe"
    if current in {pythonw.resolve(), venv_python.resolve()}:
        return False
    environment = os.environ.copy()
    environment["OPENCOVER_BOOTSTRAPPED"] = "1"
    subprocess.Popen(
        [str(pythonw), str(Path(__file__).resolve()), *sys.argv[1:]],
        cwd=str(ROOT),
        env=environment,
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return True


def dispatch() -> int:
    if _restart_in_project_environment():
        return 0
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        request = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
        if request.get("kind") == "preview":
            from opencover.workers.preview_worker import main as worker_main
        else:
            from opencover.workers.original_cover_worker import main as worker_main

        return worker_main(sys.argv[2])
    from opencover.ui.application import main

    return main()

if __name__ == "__main__":
    raise SystemExit(dispatch())
