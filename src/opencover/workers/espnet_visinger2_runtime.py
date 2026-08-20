"""Standalone score-driven Chinese VISinger2 batch runner.

The model is the CC BY 4.0 ESPnet ACESinger/OpenCpop VISinger2 release.  This
worker intentionally accepts the same score windows as the legacy DiffSinger
runner so the pipeline can replace the acoustic backend without changing the
GAME/MIDI melody extraction stage.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
import types
from pathlib import Path


_NOTE_OFFSETS = {
    "C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3,
    "E": 4, "F": 5, "F#": 6, "Gb": 6, "G": 7, "G#": 8,
    "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11,
}


def note_name_to_midi(note: str) -> int:
    if note == "rest":
        return 0
    match = re.fullmatch(r"([A-G](?:#|b)?)(-?\d+)", note)
    if not match:
        raise ValueError(f"VISinger2 不支持的音符：{note}")
    midi = _NOTE_OFFSETS[match.group(1)] + (int(match.group(2)) + 1) * 12
    if not 1 <= midi <= 127:
        raise ValueError(f"VISinger2 音符超出 MIDI 范围：{note}")
    return midi


def expand_score_windows(text: str, notes: str, durations: str) -> list[tuple[str, int, float]]:
    """Expand DiffSinger-style melisma windows to VISinger2 score syllables."""
    lyrics = re.findall(r"AP|SP|[\u4e00-\u9fff]", text)
    note_windows = [window.strip().split() for window in notes.split("|")]
    duration_windows = [window.strip().split() for window in durations.split("|")]
    if not lyrics or len(lyrics) != len(note_windows) or len(lyrics) != len(duration_windows):
        raise ValueError("VISinger2 歌词、音符和时值窗口数量不一致")

    expanded: list[tuple[str, int, float]] = []
    for lyric, pitches, values in zip(lyrics, note_windows, duration_windows):
        if len(pitches) != len(values) or not pitches:
            raise ValueError("VISinger2 复音窗口中的音符和时值数量不一致")
        for index, (pitch, value) in enumerate(zip(pitches, values)):
            duration = float(value)
            if duration <= 0:
                raise ValueError("VISinger2 音符时值必须大于零")
            expanded.append((lyric if index == 0 else "-", note_name_to_midi(pitch), duration))
    return expanded


def _prepare_imports(root: Path) -> Path:
    backend = root / "external_backends" / "espnet_visinger2"
    source = backend / "source"
    shared = root / "external_backends" / "rvc" / "runtime" / "Lib" / "site-packages"
    frontend = backend / "frontend"
    if not source.is_dir() or not shared.is_dir() or not frontend.is_dir():
        raise RuntimeError("VISinger2 源码、中文前端或共享 CUDA 依赖缺失")
    sys.path.insert(0, str(source))
    sys.path.insert(1, str(frontend))
    sys.path.append(str(shared))

    # ESPnet imports every language frontend at module import time.  English
    # and Korean G2P are not used for this Chinese-only checkpoint; stubbing
    # them prevents unrelated NLTK downloads and keeps the runtime offline.
    sys.modules["g2p_en"] = types.ModuleType("g2p_en")
    sys.modules["jamo"] = types.ModuleType("jamo")

    import numpy as np

    # The model was trained with an older NumPy-era ESPnet config while the
    # shared CUDA environment uses NumPy 1.26.
    np.complex = complex  # type: ignore[attr-defined]
    np.float = float  # type: ignore[attr-defined]
    np.int = int  # type: ignore[attr-defined]
    return backend


def _install_config_compatibility() -> None:
    """Fill parser defaults omitted from the 2024 serialized training config."""
    from espnet2.tasks.gan_svs import GANSVSTask

    original = GANSVSTask.build_model.__func__
    parser = GANSVSTask.get_parser()

    def build_model_compat(cls, args):
        for action in parser._actions:
            if action.dest != argparse.SUPPRESS and not hasattr(args, action.dest):
                setattr(args, action.dest, action.default)
        return original(cls, args)

    GANSVSTask.build_model = classmethod(build_model_compat)


def _phonemes_for_lyric(lyric: str) -> list[str]:
    if lyric in {"AP", "SP"}:
        return [lyric]
    from pypinyin import lazy_pinyin
    from resource.pinyin_dict import PINYIN_DICT

    pinyin = lazy_pinyin(lyric)[0].lower()
    phonemes = PINYIN_DICT.get(pinyin)
    if not phonemes:
        raise ValueError(f"VISinger2 中文前端不认识歌词：{lyric}（{pinyin}）")
    return list(phonemes)


def build_batch(text: str, notes: str, durations: str) -> dict[str, object]:
    labels: list[str] = []
    score_notes: list[list[object]] = []
    cursor = 0.0
    previous_final = ""
    for lyric, midi, duration in expand_score_windows(text, notes, durations):
        if lyric == "-":
            if not previous_final:
                raise ValueError("VISinger2 延音前没有可延续的歌词")
            phonemes = [previous_final]
        else:
            phonemes = _phonemes_for_lyric(lyric)
        phoneme_text = "_".join(phonemes)
        end = cursor + duration
        score_notes.append([cursor, end, "".join(phonemes), midi, phoneme_text])
        labels.extend(phonemes)
        previous_final = phonemes[-1]
        cursor = end
    return {"score": (120, score_notes), "text": " ".join(labels)}


def main(request_file: str) -> int:
    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    root = Path(request["root"]).resolve()
    backend = _prepare_imports(root)
    _install_config_compatibility()

    import numpy as np
    import soundfile as sf
    import torch
    from espnet2.bin.svs_inference import SingingGenerate

    model_root = backend / "model"
    config = model_root / "exp" / "svs_train_visinger2_40singer_raw_phn_None_zh" / "config.yaml"
    checkpoint = model_root / "exp" / "svs_train_visinger2_40singer_raw_phn_None_zh" / "500epoch.pth"
    if not config.is_file() or not checkpoint.is_file():
        raise RuntimeError("VISinger2 配置或权重缺失")

    os.chdir(model_root)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(int(request.get("seed", 777)))
    synthesizer = SingingGenerate(
        train_config=str(config), model_file=str(checkpoint), device=device,
        svs_task="gan_svs", noise_scale=float(request.get("noise_scale", 0.50)),
        noise_scale_dur=float(request.get("noise_scale_dur", 0.20)),
    )

    segments = request["segments"]
    total = len(segments)
    singer_id = int(request.get("singer_id", 29))
    for index, segment in enumerate(segments):
        output = Path(segment["output"])
        try:
            existing = sf.info(output)
            if existing.frames >= existing.samplerate // 4:
                print("OPENCOVER_PROGRESS " + json.dumps({"done": index + 1, "total": total}), flush=True)
                continue
        except (OSError, RuntimeError):
            pass

        batch = build_batch(str(segment["text"]), str(segment["notes"]), str(segment["notes_duration"]))
        # The 2024 demo intentionally passes a heterogeneous dict here, while
        # its old typeguard annotation says every dict value is a tuple.  Call
        # the same inference body without that stale runtime annotation.
        inference_body = inspect.unwrap(type(synthesizer).__call__)
        segment_singer_id = int(segment.get("singer_id", singer_id))
        with torch.no_grad():
            values = inference_body(
                synthesizer, batch, sids=np.asarray([segment_singer_id], dtype=np.int64),
            )["wav"]
        audio = values.detach().float().cpu().numpy().reshape(-1)
        if audio.size < 1024 or not np.isfinite(audio).all() or not np.any(audio != 0):
            raise RuntimeError("VISinger2 未生成有效非静音音频")
        peak = float(np.max(np.abs(audio)))
        if peak > 0.98:
            audio *= 0.98 / peak
        output.parent.mkdir(parents=True, exist_ok=True)
        sf.write(output, audio, 44100, subtype="PCM_24")
        print("OPENCOVER_PROGRESS " + json.dumps({"done": index + 1, "total": total}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
