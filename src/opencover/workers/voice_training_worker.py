from __future__ import annotations

import json
from pathlib import Path
import sys
import traceback

from opencover.pipelines.voice_training import VoiceTrainingPipeline
from opencover.workers.original_cover_worker import emit


def main(request_file: str) -> int:
    try:
        data = json.loads(Path(request_file).read_text(encoding="utf-8"))
        output = VoiceTrainingPipeline(Path(data["root"])).run(Path(data["input_path"]), data["options"], Path(request_file).parent, lambda stage, value, message: emit("progress", stage=stage, value=value, message=message))
        emit("result", path=str(output))
        return 0
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit("error", code="TRAINING_FAILED", message=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
