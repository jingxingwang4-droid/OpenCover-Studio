from __future__ import annotations

import glob
import json
import os
import re
import sys
import types
from pathlib import Path


def _score_constrained_f0(predicted_f0, score_midi, *, max_deviation_semitones: float = 0.45):
    """Keep vocoder F0 close to the requested score while preserving small motion.

    The legacy OpenCpop pitch extractor can octave-jump on notes below its
    comfortable female range.  Its output is useful for voicing and subtle
    movement, but it must not replace the MIDI score that drove synthesis.
    """
    import numpy as np

    predicted = np.asarray(predicted_f0, dtype=np.float32)
    midi = np.asarray(score_midi, dtype=np.float32)
    target = np.where(midi > 0, 440.0 * np.power(2.0, (midi - 69.0) / 12.0), 0.0).astype(np.float32)
    voiced = (predicted > 1.0) & (target > 1.0)
    result = target.copy()
    if np.any(voiced):
        deviation = 12.0 * np.log2(np.maximum(predicted[voiced], 1.0) / target[voiced])
        # Remove octave mistakes first, then retain only restrained expressive
        # deviation around the explicitly requested note.
        deviation -= 12.0 * np.round(deviation / 12.0)
        deviation = np.clip(deviation, -max_deviation_semitones, max_deviation_semitones)
        result[voiced] = target[voiced] * np.power(2.0, deviation / 12.0)
    result[~voiced] = 0.0
    return result


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
    if str(request.get("pitch_control", "score")) == "score":
        import torch

        def score_constrained_forward(instance, inp):
            sample = instance.input_to_batch(inp)
            with torch.no_grad():
                output = instance.model(
                    sample["txt_tokens"], spk_id=sample.get("spk_ids"), ref_mels=None, infer=True,
                    pitch_midi=sample["pitch_midi"], midi_dur=sample["midi_dur"],
                    is_slur=sample["is_slur"],
                )
                mel_out = output["mel_out"]
                predicted_f0 = instance.pe(mel_out)["f0_denorm_pred"]
                mel2ph = output["mel2ph"]
                padded_midi = torch.nn.functional.pad(sample["pitch_midi"], [1, 0])
                frame_midi = torch.gather(padded_midi, 1, mel2ph).cpu().numpy()
                corrected = _score_constrained_f0(predicted_f0.cpu().numpy(), frame_midi)
                vocoder_f0 = torch.from_numpy(corrected).to(mel_out.device)
                wav_out = instance.run_vocoder(mel_out, f0=vocoder_f0)
            return wav_out.cpu().numpy()[0]

        infer.forward_model = types.MethodType(score_constrained_forward, infer)
    rate = int(hparams["audio_sample_rate"])
    segments = request["segments"]
    total = len(segments)
    for index, segment in enumerate(segments):
        output = Path(segment["output"])
        try:
            existing = sf.info(output)
            if existing.frames >= existing.samplerate // 4:
                print("OPENCOVER_PROGRESS " + json.dumps({"done": index + 1, "total": total}), flush=True)
                continue
        except (OSError, RuntimeError):
            pass
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
        output_pitch_shift = float(segment.get("output_pitch_shift", 0.0))
        if output_pitch_shift:
            import librosa
            audio = librosa.effects.pitch_shift(
                audio, sr=rate, n_steps=output_pitch_shift, bins_per_octave=12,
            ).astype(np.float32, copy=False)
        if audio.size < rate // 4 or not np.isfinite(audio).all() or not np.any(audio != 0):
            raise RuntimeError("DiffSinger 未生成有效非静音音频")
        peak = float(np.max(np.abs(audio)))
        if peak > 0.98:
            audio *= 0.98 / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, rate, subtype="PCM_16")
        print("OPENCOVER_PROGRESS " + json.dumps({"done": index + 1, "total": total}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
