from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _audio_chunks(wav: np.ndarray, sr: int) -> list[tuple[int, int]]:
    """Return silence-aware singing phrases that are normally 5-9 seconds."""
    import librosa
    import numpy as np

    intervals = librosa.effects.split(wav, top_db=38, frame_length=2048, hop_length=512)
    if len(intervals) == 0:
        intervals = np.asarray([[0, len(wav)]], dtype=np.int64)
    max_gap = int(0.65 * sr)
    minimum_audio = int(0.35 * sr)
    merged: list[tuple[int, int]] = []
    start, end = (int(value) for value in intervals[0])
    for raw_start, raw_end in intervals[1:]:
        next_start, next_end = int(raw_start), int(raw_end)
        if next_start - end <= max_gap:
            end = next_end
        else:
            if end - start >= minimum_audio:
                merged.append((start, end))
            start, end = next_start, next_end
    if end - start >= minimum_audio:
        merged.append((start, end))
    def quiet_boundary(lower: int, upper: int, ideal: int) -> int:
        if upper <= lower:
            return ideal
        half_window = max(1, round(0.020 * sr))
        hop = max(1, round(0.010 * sr))
        candidates = np.arange(lower, upper + 1, hop, dtype=np.int64)
        values: list[tuple[float, float, int]] = []
        for candidate in candidates:
            begin = max(0, int(candidate) - half_window)
            finish = min(len(wav), int(candidate) + half_window)
            rms = float(np.sqrt(np.mean(np.square(wav[begin:finish]), dtype=np.float64)))
            values.append((rms, abs(int(candidate) - ideal) / sr, int(candidate)))
        # Energy is decisive; distance breaks ties between similarly quiet
        # pauses so a boundary does not drift needlessly far from 7 seconds.
        floor = min(value[0] for value in values)
        near_floor = [value for value in values if value[0] <= floor * 1.15 + 1e-6]
        return min(near_floor, key=lambda value: (value[1], value[0], value[2]))[2]

    def partition_region(region_start: int, region_end: int) -> list[tuple[int, int]]:
        span = region_end - region_start
        minimum = int(5.0 * sr)
        maximum = int(9.0 * sr)
        if span <= maximum:
            return [(region_start, region_end)]
        count = int(np.ceil(span / maximum))
        if span / count < minimum:
            count = max(1, int(np.floor(span / minimum)))
        if count <= 1:
            return [(region_start, region_end)]
        boundaries = [region_start]
        for index in range(1, count):
            ideal = round(region_start + span * index / count)
            lower = max(boundaries[-1] + minimum, ideal - round(1.25 * sr))
            upper = min(
                boundaries[-1] + maximum,
                region_end - (count - index) * minimum,
                ideal + round(1.25 * sr),
            )
            boundaries.append(quiet_boundary(lower, upper, ideal))
        boundaries.append(region_end)
        return list(zip(boundaries, boundaries[1:]))

    chunks: list[tuple[int, int]] = []
    for start, end in merged:
        padded_start = max(0, start - round(0.12 * sr))
        padded_end = min(len(wav), end + round(0.12 * sr))
        chunks.extend(partition_region(padded_start, padded_end))
    return chunks or [(0, len(wav))]


def _decode_chunk(model, processor, device, wav: np.ndarray, max_new_tokens: int) -> str:
    import numpy as np
    import torch
    from vocalparse.prompts import build_prefix_text

    prefix_text = build_prefix_text(processor)
    inputs = processor(
        text=[prefix_text], audio=[wav.astype(np.float32, copy=False)],
        sampling_rate=16000, return_tensors="pt", padding=False, truncation=False,
    )
    inputs = {key: value.to(device) for key, value in inputs.items()}
    if "input_features" in inputs and inputs["input_features"].is_floating_point():
        inputs["input_features"] = inputs["input_features"].to(model.dtype)
    prefix_len = inputs["input_ids"].shape[1]
    with torch.inference_mode():
        outputs = model.generate(**inputs, max_new_tokens=max_new_tokens)
    sequence = outputs.sequences[0] if hasattr(outputs, "sequences") else outputs[0]
    return processor.tokenizer.decode(sequence[prefix_len:], skip_special_tokens=False)


def _cot_lyrics(raw: str) -> str:
    separator = "<|file_sep|>"
    if separator not in raw:
        return ""
    prefix = raw.split(separator, 1)[0]
    if "<asr_text>" in prefix:
        prefix = prefix.split("<asr_text>", 1)[1]
    prefix = re.sub(r"<[^>]+>", "", prefix)
    return prefix.strip()


def _parsed_score(raw: str) -> tuple[dict[str, object] | None, list[dict[str, object]]]:
    from vocalparse.evaluation import aggregate_to_words, parse_transcription_text

    parsed = parse_transcription_text(raw)
    if not parsed:
        return None, []
    score = [
        {
            "text": word.char,
            "notes": [
                {"midi": int(pitch), "value": str(note)}
                for pitch, note in word.pairs
            ],
        }
        for word in aggregate_to_words(parsed)
        if word.char not in {"AP", "SP", "·"}
    ]
    return parsed, score


def _score_lyrics(score: list[dict[str, object]]) -> str:
    return "".join(str(item.get("text", "")) for item in score)


def main(request_file: str) -> int:
    import numpy as np
    import torch

    request = json.loads(Path(request_file).read_text(encoding="utf-8"))
    root = Path(str(request["root"])).resolve()
    audio_path = Path(str(request["audio_path"])).resolve()
    output_path = Path(str(request["output_path"])).resolve()
    checkpoint = root / "external_backends" / "vocalparse" / "models" / "VocalParse"
    source = root / "external_backends" / "vocalparse" / "source"
    if str(source) not in sys.path:
        sys.path.insert(0, str(source))

    from vocalparse.model import load_audio, load_model

    wav = load_audio(str(audio_path), sr=16000).astype(np.float32)
    if wav.size < 8000 or not np.isfinite(wav).all() or float(np.max(np.abs(wav))) < 1e-5:
        raise RuntimeError("分离人声为空或无效，无法自动识别歌词")
    model, processor, device = load_model({
        "checkpoint": str(checkpoint),
        "attn_implementation": str(request.get("attn_implementation", "sdpa")),
    })

    phrases: list[dict[str, object]] = []
    combined_score: list[dict[str, object]] = []
    for start, end in _audio_chunks(wav, 16000):
        raw = _decode_chunk(model, processor, device, wav[start:end], int(request.get("max_new_tokens", 768)))
        parsed, score = _parsed_score(raw)
        lyrics = _cot_lyrics(raw) or _score_lyrics(score)
        lyrics = re.sub(r"\s+", "", lyrics).strip()
        if not lyrics:
            continue
        phrases.append({
            "start": start / 16000.0,
            "end": end / 16000.0,
            "lyrics": lyrics,
            "raw": raw,
            "bpm": int(parsed.get("bpm", 120)) if parsed else 120,
            "score": score,
        })
        combined_score.extend(score)

    lyric_lines = [str(item["lyrics"]) for item in phrases if str(item.get("lyrics", "")).strip()]
    plain_lyrics = "\n".join(lyric_lines).strip()
    timed_lines: list[str] = []
    for item in phrases:
        text = str(item.get("lyrics", "")).strip()
        if not text:
            continue
        start = float(item["start"])
        minutes = int(start // 60)
        seconds = start - minutes * 60
        end = float(item["end"])
        end_minutes = int(end // 60)
        end_seconds = end - end_minutes * 60
        timed_lines.append(f"[{minutes:02d}:{seconds:05.2f}][end:{end_minutes:02d}:{end_seconds:05.2f}]{text}")
    lyrics = "\n".join(timed_lines).strip()
    compact = re.sub(r"\s+", "", plain_lyrics)
    if len(compact) < 2:
        raise RuntimeError("VocalParse 没有识别出可供人工校对的歌词")
    cjk = sum("\u4e00" <= character <= "\u9fff" for character in compact)
    if len(compact) >= 8 and cjk / len(compact) < 0.45:
        raise RuntimeError("VocalParse 中文歌词比例过低，请确认歌曲语言或人声分离质量")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({
        "backend": "VocalParse",
        "lyrics": lyrics,
        "plain_lyrics": plain_lyrics,
        "phrases": phrases,
        "score": combined_score,
        "audio_path": str(audio_path),
        "cuda": torch.cuda.is_available(),
        "device": str(device),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
