"""Package a complete M4Singer song from downloaded WAV/TextGrid and meta.json.

MIDI notes and timing come directly from the dataset's manually composed score
annotations. No pitch is inferred from audio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import wave
from pathlib import Path


TPQ = 480
TEMPO_US = 500_000
GAP_SECONDS = 0.30


def vlq(value: int) -> bytes:
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, 0x80 | value & 0x7F)
        value >>= 7
    return bytes(out)


def meta(kind: int, payload: bytes) -> bytes:
    return bytes((0xFF, kind)) + vlq(len(payload)) + payload


def ticks(seconds: float) -> int:
    return round(seconds * TPQ * 1_000_000 / TEMPO_US)


def lrc_time(seconds: float) -> str:
    centis = round(seconds * 100)
    minute, centis = divmod(centis, 6000)
    second, centis = divmod(centis, 100)
    return f"[{minute:02d}:{second:02d}.{centis:02d}]"


def first_lyric_time(textgrid: Path) -> float:
    text = textgrid.read_text(encoding="utf-8")
    matches = re.findall(
        r'xmin = ([0-9.]+)\s+xmax = ([0-9.]+)\s+text = "([^"]*)"', text
    )
    for start, _, word in matches:
        if word not in {"SP", "AP", ""}:
            return float(start)
    return 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phrases", type=Path)
    parser.add_argument("meta_json", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    all_meta = json.loads(args.meta_json.read_text(encoding="utf-8"))
    song_rows = [r for r in all_meta if r["item_name"].startswith("Alto-1#")]
    song_prefix = next(
        r["item_name"].rsplit("#", 1)[0]
        for r in song_rows
        if r["item_name"].endswith("#0000") and r.get("txt") == "哼你的晚安"
    )
    rows = sorted(
        (r for r in all_meta if r["item_name"].rsplit("#", 1)[0] == song_prefix),
        key=lambda r: r["item_name"],
    )
    wavs = sorted((args.phrases / "wav").glob("*.wav"))
    grids = sorted((args.phrases / "TextGrid").glob("*.TextGrid"))
    if not rows or not (len(rows) == len(wavs) == len(grids)):
        raise SystemExit(f"incomplete song: meta={len(rows)} wav={len(wavs)} TextGrid={len(grids)}")

    args.output.mkdir(parents=True, exist_ok=True)
    out_wav = args.output / "云烟成雨-M4Singer女声完整清唱.wav"
    out_lrc = args.output / "云烟成雨-M4Singer女声完整清唱.lrc"
    out_mid = args.output / "云烟成雨-M4Singer人工乐谱.mid"

    offsets: list[float] = []
    cursor = 0.0
    wav_params = None
    audio_parts: list[bytes] = []
    for index, wav_path in enumerate(wavs):
        offsets.append(cursor)
        with wave.open(str(wav_path), "rb") as src:
            current = (src.getnchannels(), src.getsampwidth(), src.getframerate())
            if wav_params is None:
                wav_params = current
            elif current != wav_params:
                raise SystemExit(f"WAV parameters differ: {wav_path}")
            audio_parts.append(src.readframes(src.getnframes()))
            cursor += src.getnframes() / src.getframerate()
            if index + 1 < len(wavs):
                gap_frames = round(GAP_SECONDS * src.getframerate())
                audio_parts.append(b"\0" * gap_frames * src.getnchannels() * src.getsampwidth())
                cursor += gap_frames / src.getframerate()

    assert wav_params is not None
    channels, width, rate = wav_params
    with wave.open(str(out_wav), "wb") as dst:
        dst.setnchannels(channels)
        dst.setsampwidth(width)
        dst.setframerate(rate)
        dst.writeframes(b"".join(audio_parts))

    lrc = ["[ti:云烟成雨]", "[ar:M4Singer Alto-1]", "[by:M4Singer meta.json 人工标注]"]
    for offset, grid, row in zip(offsets, grids, rows):
        lrc.append(f"{lrc_time(offset + first_lyric_time(grid))}{row['txt']}")
    out_lrc.write_text("\n".join(lrc) + "\n", encoding="utf-8-sig")

    events: list[tuple[int, int, bytes]] = [
        (0, 0, meta(0x03, "云烟成雨 - M4Singer人工乐谱".encode("utf-8"))),
        (0, 1, meta(0x51, TEMPO_US.to_bytes(3, "big"))),
        (0, 2, bytes((0xC0, 53))),
    ]
    note_count = 0
    min_pitch = 127
    max_pitch = 0
    for offset, row in zip(offsets, rows):
        events.append((ticks(offset), 3, meta(0x05, row["txt"].encode("utf-8"))))
        local = 0.0
        if len(row["notes"]) != len(row["ph_dur"]):
            raise SystemExit(f"score/alignment length differs: {row['item_name']}")
        for pitch, duration in zip(row["notes"], row["ph_dur"]):
            duration = float(duration)
            if int(pitch) > 0:
                start = ticks(offset + local)
                end = max(start + 1, ticks(offset + local + duration))
                events.append((start, 5, bytes((0x90, int(pitch), 88))))
                events.append((end, 4, bytes((0x80, int(pitch), 0))))
                note_count += 1
                min_pitch = min(min_pitch, int(pitch))
                max_pitch = max(max_pitch, int(pitch))
            local += duration

    events.sort(key=lambda event: (event[0], event[1]))
    track = bytearray()
    previous = 0
    for tick, _, payload in events:
        track += vlq(tick - previous) + payload
        previous = tick
    track += b"\x00" + meta(0x2F, b"")
    out_mid.write_bytes(
        b"MThd" + struct.pack(">IHHH", 6, 0, 1, TPQ) + b"MTrk" + struct.pack(">I", len(track)) + track
    )

    summary = {
        "source": "M4Singer Alto-1#云烟成雨",
        "phrases": len(rows),
        "duration_seconds": round(cursor, 3),
        "midi_notes": note_count,
        "midi_pitch_range": [min_pitch, max_pitch],
        "midi_duration_seconds": round(previous * TEMPO_US / (TPQ * 1_000_000), 3),
        "wav": {"sample_rate": rate, "channels": channels, "bit_depth": width * 8},
    }
    for key, path in (("wav_file", out_wav), ("lrc_file", out_lrc), ("midi_file", out_mid)):
        summary[key] = {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    (args.output / "校验信息.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
