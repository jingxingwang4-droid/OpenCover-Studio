from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", type=Path)
    parser.add_argument("audio", nargs="+", type=Path)
    parser.add_argument("--language", default="zh")
    args = parser.parse_args()

    ffmpeg = next(Path.cwd().glob("ffmpeg/*/bin/ffmpeg.exe"), None)
    if ffmpeg is not None:
        os.environ["PATH"] = str(ffmpeg.parent) + os.pathsep + os.environ.get("PATH", "")

    import stable_whisper

    model = stable_whisper.load_model(str(args.model), device="cuda")
    for audio in args.audio:
        result = model.transcribe(
            str(audio), language=args.language, word_timestamps=True,
            regroup=False, verbose=None,
        )
        data = result.to_dict()
        print(json.dumps({
            "audio": str(audio),
            "text": data.get("text", ""),
            "segments": data.get("segments", []),
        }, ensure_ascii=False))


if __name__ == "__main__":
    main()
