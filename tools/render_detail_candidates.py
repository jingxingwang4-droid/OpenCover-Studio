from __future__ import annotations

import argparse
from pathlib import Path

from opencover.audio.processing import ffmpeg_path, restore_vocal_detail


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("converted", type=Path)
    parser.add_argument("source", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    ffmpeg = ffmpeg_path(args.root)
    if ffmpeg is None:
        raise RuntimeError("FFmpeg missing")
    presets = {
        "detail_current.wav": (0.18, 4200),
        "detail_3500.wav": (0.35, 3500),
        "detail_2500.wav": (0.30, 2500),
        "detail_1000.wav": (0.15, 1000),
    }
    for name, (mix, cutoff) in presets.items():
        restore_vocal_detail(
            args.converted, args.source, args.output_dir / name, ffmpeg,
            detail_mix=mix, detail_cutoff_hz=cutoff, converted_gain=0.96,
        )


if __name__ == "__main__":
    main()
