"""Run RVC on generated lyric segments while loading the voice model once."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(request_file: str) -> int:
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))

    from dotenv import load_dotenv
    from rvc.modules.vc.modules import VC
    from scipy.io import wavfile

    load_dotenv(Path.cwd() / ".env")
    if not os.getenv("index_root"):
        raise RuntimeError("RVC 后端 .env 缺少 index_root")
    converter = VC()
    converter.get_vc(str(request["model"]))
    items = request["items"]
    total = len(items)
    for index, item in enumerate(items):
        output = Path(item["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        sample_rate, audio, _, _ = converter.vc_inference(
            int(request.get("sid", 0)),
            Path(item["input"]),
            int(request.get("pitch", 0)),
            str(request.get("f0_method", "rmvpe")),
            None,
            Path(request["index"]) if request.get("index") else None,
            float(request.get("index_rate", 0.0)),
            3,
            0,
            float(request.get("rms_mix_rate", 0.25)),
            float(request.get("protect", 0.33)),
        )
        wavfile.write(output, sample_rate, audio)
        if not output.is_file() or output.stat().st_size < 1024:
            raise RuntimeError(f"RVC 没有生成有效分段：{output.name}")
        print(
            "OPENCOVER_PROGRESS " + json.dumps({"done": index + 1, "total": total}),
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
