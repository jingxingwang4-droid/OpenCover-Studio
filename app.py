from __future__ import annotations

import sys


def dispatch() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        from opencover.workers.original_cover_worker import main as worker_main

        return worker_main(sys.argv[2])
    from opencover.ui.application import main

    return main()

if __name__ == "__main__":
    raise SystemExit(dispatch())
