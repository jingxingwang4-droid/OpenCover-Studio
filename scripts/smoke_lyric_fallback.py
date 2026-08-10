from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from opencover.models.registry import ModelRegistry
from opencover.pipelines.lyric_cover import LyricCoverPipeline, LyricCoverRequest


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    voice = ModelRegistry(root / "weights").get("toyokawa_sakiko_rvc")
    if voice is None:
        raise RuntimeError("缺少本机祥子 RVC 模型")
    pipeline = LyricCoverPipeline(root)
    request = LyricCoverRequest(
        input_path=root / "assets" / "preview_sources" / "neutral_melody.wav",
        engine="rvc", voice=voice, original_lyrics="啦啦啦啦啦啦啦啦",
        new_lyrics="回退链路现在成功", strategy="强制", pitch=0, balance="均衡", output_format="wav",
        generator="diffsinger", memory_profile="低",
    )
    events: list[dict[str, object]] = []
    output = pipeline.run(
        request, root / "workspace" / "test_outputs" / "lyric_fallback" / "job",
        lambda stage, value, message: events.append({"stage": stage, "value": value, "message": message}),
    )
    audio, rate = sf.read(output, always_2d=True, dtype="float32")
    result = {
        "output": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "sample_rate": rate, "channels": audio.shape[1], "duration": len(audio) / rate,
        "peak": float(np.max(np.abs(audio))), "rms": float(np.sqrt(np.mean(audio * audio))),
        "finite": bool(np.isfinite(audio).all()), "nonzero": bool(np.any(audio != 0)), "events": events,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["finite"] and result["nonzero"] and result["rms"] > 1e-5 else 1


if __name__ == "__main__":
    raise SystemExit(main())
