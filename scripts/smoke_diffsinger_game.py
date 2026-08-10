from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from opencover.adapters.backends import DiffSingerLegacyAdapter
from opencover.pipelines.lyric_cover import game_melody_for_text


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    note_file = root / "workspace" / "test_outputs" / "diffsinger_game" / "notes" / "source_000.txt"
    source = root / "assets" / "preview_sources" / "neutral_melody.wav"
    _, rate = sf.read(source, dtype="float32")
    duration = sf.info(source).frames / rate
    text, notes, durations = game_melody_for_text("新的春天就在眼前", duration, note_file)
    output = root / "workspace" / "test_outputs" / "diffsinger_game" / "generated_from_game.wav"
    request = root / "workspace" / "test_inputs" / "diffsinger_game_request.json"
    request.parent.mkdir(parents=True, exist_ok=True)
    request.write_text(json.dumps({
        "root": str(root), "experiment": "0831_opencpop_ds1000",
        "segments": [{"text": text, "notes": notes, "notes_duration": durations, "output": str(output)}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    adapter = DiffSingerLegacyAdapter(root / "external_backends" / "diffsinger")
    adapter.generate_batch(request, root / "src" / "opencover" / "workers" / "diffsinger_legacy_runtime.py")
    audio, out_rate = sf.read(output, always_2d=True, dtype="float32")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    result = {
        "output": str(output), "sha256": digest, "sample_rate": out_rate,
        "duration": len(audio) / out_rate, "peak": float(np.max(np.abs(audio))),
        "rms": float(np.sqrt(np.mean(audio * audio))), "finite": bool(np.isfinite(audio).all()),
        "nonzero": bool(np.any(audio != 0)), "notes": notes,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["finite"] and result["nonzero"] and result["rms"] > 1e-5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
