"""Standalone Vevo2 batch runner executed by the optional backend runtime."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


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
    for index, segment in enumerate(data["segments"]):
        output = Path(segment["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        audio = pipeline.inference_ar_and_fm(
            target_text=str(segment["text"]),
            prosody_wav_path=str(segment["input"]),
            style_ref_wav_path=None,
            style_ref_wav_text="",
            timbre_ref_wav_path=str(segment["input"]),
            use_prosody_code=True,
            target_duration=float(segment["duration"]),
            flow_matching_steps=int(data.get("flow_matching_steps", 32)),
        ).detach().float().cpu().squeeze()
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
        torch.cuda.empty_cache()
    print(json.dumps({"ok": True, "results": results}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
