from __future__ import annotations

import argparse
import os
import sys
import time
import zipfile
from pathlib import Path


def create_zip(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination = destination.resolve()
    partial = destination.with_suffix(destination.suffix + ".part")
    if not source.is_dir():
        raise FileNotFoundError(f"source directory not found: {source}")
    if destination.exists() or partial.exists():
        raise FileExistsError(f"destination already exists: {destination} or {partial}")
    if destination.parent != source.parent:
        raise ValueError("archive must be created beside the private package directory")

    written = 0
    started = time.monotonic()
    try:
        with zipfile.ZipFile(
            partial,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=1,
            allowZip64=True,
            strict_timestamps=False,
        ) as archive:
            for directory, dirnames, filenames in os.walk(source):
                dirnames.sort()
                filenames.sort()
                current = Path(directory)
                relative_dir = current.relative_to(source.parent)
                if not dirnames and not filenames:
                    archive.write(current, relative_dir.as_posix() + "/")
                for filename in filenames:
                    path = current / filename
                    relative = path.relative_to(source.parent).as_posix()
                    archive.write(path, relative)
                    written += 1
                    if written % 5000 == 0:
                        gib = partial.stat().st_size / (1024 ** 3)
                        elapsed = time.monotonic() - started
                        print(f"files={written} archive_gib={gib:.3f} elapsed_s={elapsed:.1f}", flush=True)
        partial.replace(destination)
    except BaseException:
        if partial.exists():
            partial.unlink()
        raise
    print(f"complete files={written} bytes={destination.stat().st_size}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    create_zip(arguments.source, arguments.destination)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
