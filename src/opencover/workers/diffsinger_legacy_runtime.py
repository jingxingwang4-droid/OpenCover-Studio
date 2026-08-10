from __future__ import annotations

import glob
import json
import os
import re
import sys
import types
from pathlib import Path


def _prepare_imports(root: Path) -> tuple[Path, Path]:
    backend = root / "external_backends" / "diffsinger"
    demo = backend / "legacy_demo"
    extras = backend / "legacy_runtime" / "Lib" / "site-packages"
    if not demo.is_dir() or not extras.is_dir():
        raise RuntimeError("DiffSinger legacy 源码或轻量依赖环境缺失")
    sys.path.insert(0, str(demo))
    sys.path.append(str(extras))
    os.chdir(demo)

    import scipy.signal
    from scipy.signal.windows import kaiser
    scipy.signal.kaiser = kaiser  # type: ignore[attr-defined]

    original_glob = glob.glob
    glob.glob = lambda *args, **kwargs: [  # type: ignore[assignment]
        path.replace("\\", "/") for path in original_glob(*args, **kwargs)
    ]

    from usr.diff.net import DiffNet
    minimal = types.ModuleType("usr.diffsinger_task")
    minimal.DIFF_DECODERS = {"wavenet": lambda hp: DiffNet(hp["audio_num_mel_bins"])}  # type: ignore[attr-defined]
    sys.modules["usr.diffsinger_task"] = minimal
    return backend, demo


def main(request_file: str) -> int:
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    root = Path(request["root"]).resolve()
    _, demo = _prepare_imports(root)
    import numpy as np
    import soundfile as sf
    from inference.svs.ds_e2e import DiffSingerE2EInfer
    from utils.hparams import hparams, set_hparams

    experiment = str(request.get("experiment") or "0831_opencpop_ds1000")
    config = demo / "usr" / "configs" / "midi" / "e2e" / "opencpop" / "ds100_adj_rel.yaml"
    set_hparams(config=str(config), exp_name=experiment, print_hparams=False)
    infer = DiffSingerE2EInfer(hparams)
    rate = int(hparams["audio_sample_rate"])
    for segment in request["segments"]:
        text = re.sub(r"\s+", "", str(segment["text"]))
        if not text:
            raise RuntimeError("DiffSinger 分段歌词为空")
        values = infer.infer_once({
            "text": text,
            "notes": str(segment["notes"]),
            "notes_duration": str(segment["notes_duration"]),
            "input_type": "word",
        })
        audio = np.asarray(values, dtype=np.float32).reshape(-1)
        if audio.size < rate // 4 or not np.isfinite(audio).all() or not np.any(audio != 0):
            raise RuntimeError("DiffSinger 未生成有效非静音音频")
        peak = float(np.max(np.abs(audio)))
        if peak > 0.98:
            audio *= 0.98 / peak
        output = Path(segment["output"])
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, rate, subtype="PCM_16")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
