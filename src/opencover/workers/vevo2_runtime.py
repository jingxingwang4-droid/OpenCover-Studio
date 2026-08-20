"""Standalone Vevo2 batch runner executed by the optional backend runtime."""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path


def _duration_token_budget(duration: float) -> int:
    """Bound Vevo2's 12.5 Hz content-code generation near phrase length."""
    if duration <= 0:
        raise ValueError("Vevo2 目标短句时长无效")
    # Keep only a small EOS allowance.  The previous 12% + 2-token margin was
    # harmless on long phrases but made 1–2 second score-locked blocks overrun
    # their slots by roughly 25–30%.
    return max(15, min(500, math.ceil(duration * 12.5 * 1.06) + 1))


def main(request_file: str) -> int:
    data = json.loads(Path(request_file).read_text(encoding="utf-8"))
    root = Path(data["root"]).resolve()
    source = root / "external_backends" / "vevo2" / "Amphion"
    model = root / "external_backends" / "vevo2" / "models" / "Vevo2"
    os.chdir(source)
    sys.path.insert(0, str(source))

    import numpy as np
    import soundfile as sf
    import torch
    from models.svc.vevo2.vevo2_utils import Vevo2InferencePipeline

    torch.manual_seed(int(data.get("seed", 1234)))
    pipeline = Vevo2InferencePipeline(
        prosody_tokenizer_ckpt_path=model / "tokenizer" / "prosody_fvq512_6.25hz",
        content_style_tokenizer_ckpt_path=model / "tokenizer" / "contentstyle_fvq16384_12.5hz",
        ar_cfg_path=model / "contentstyle_modeling" / "posttrained" / "amphion_config.json",
        ar_ckpt_path=model / "contentstyle_modeling" / "posttrained",
        fmt_cfg_path=model / "acoustic_modeling" / "fm_emilia101k_singnet7k_repa" / "config.json",
        fmt_ckpt_path=model / "acoustic_modeling" / "fm_emilia101k_singnet7k_repa",
        vocoder_cfg_path=model / "vocoder" / "config.json",
        vocoder_ckpt_path=model / "vocoder",
        device=torch.device("cuda"),
    )
    results: list[dict[str, object]] = []
    segments = data["segments"]
    total = len(segments)
    for index, segment in enumerate(segments):
        output = Path(segment["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = sf.info(output)
            if existing.samplerate == 24000 and existing.frames >= 1024:
                results.append({"index": index, "output": str(output), "frames": existing.frames, "cached": True})
                print("OPENCOVER_PROGRESS " + json.dumps({"done": index + 1, "total": total}), flush=True)
                continue
        except (OSError, RuntimeError):
            pass
        duration = float(segment["duration"])
        # Amphion hard-codes max_new_tokens=500, which can turn a five-second
        # phrase into roughly forty seconds when EOS is missed.  Limit the AR
        # response to the requested 12.5 Hz content-code length.  The small
        # allowance gives the model room to emit EOS and is corrected later by
        # pitch-preserving Rubber Band, never by sample-rate abuse.
        original_generate = pipeline.ar_model.generate

        def duration_limited_generate(*args, **kwargs):
            kwargs["max_new_tokens"] = min(
                int(kwargs.get("max_new_tokens", 500)), _duration_token_budget(duration),
            )
            kwargs["min_new_tokens"] = min(
                int(kwargs.get("min_new_tokens", 15)), kwargs["max_new_tokens"],
            )
            return original_generate(*args, **kwargs)

        pipeline.ar_model.generate = duration_limited_generate
        try:
            audio = pipeline.inference_ar_and_fm(
                target_text=str(segment["text"]),
                prosody_wav_path=str(segment["input"]),
                style_ref_wav_path=None,
                style_ref_wav_text="",
                timbre_ref_wav_path=str(segment["input"]),
                use_prosody_code=True,
                target_duration=duration,
                flow_matching_steps=int(data.get("flow_matching_steps", 32)),
            ).detach().float().cpu().squeeze()
        finally:
            pipeline.ar_model.generate = original_generate
        values = audio.numpy()
        if values.ndim != 1 or values.size < 1024 or not np.isfinite(values).all():
            raise RuntimeError(f"Vevo2 第 {index + 1} 段生成了无效音频")
        rms = float(np.sqrt(np.mean(values ** 2)))
        if rms > 1e-8:
            values *= 10 ** ((-25.0 - 20.0 * np.log10(rms)) / 20.0)
        peak = float(np.max(np.abs(values)))
        if peak > 0.98:
            values *= 0.98 / peak
        sf.write(output, values, 24000, subtype="PCM_16")
        results.append({"index": index, "output": str(output), "frames": int(values.size)})
        print("OPENCOVER_PROGRESS " + json.dumps({"done": index + 1, "total": total}), flush=True)
        torch.cuda.empty_cache()
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
