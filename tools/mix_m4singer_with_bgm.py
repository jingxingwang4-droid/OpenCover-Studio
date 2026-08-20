"""Place the M4Singer vocal/score on the 4-minute song timeline and mix BGM.

The vocal pitch and timing are read only from M4Singer's manual annotations.
The external LRC supplies the absolute song timeline.  No pitch extraction or
audio-to-MIDI conversion is performed here.
"""

from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import re
import struct
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path


TPQ = 480
TEMPO_US = 500_000


@dataclass(frozen=True)
class Anchor:
    lrc_line: int | None
    word: str | None = None
    after_previous: bool = False


# Indices address non-empty lyric lines.  Phrases 0/1 split the first two LRC
# lines at unusual places, and phrases 8/17 continue the preceding LRC line.
ANCHORS = (
    Anchor(0, "ni"),
    Anchor(1, "wo"),
    Anchor(2),
    Anchor(3),
    Anchor(4),
    Anchor(5),
    Anchor(6),
    Anchor(7),
    Anchor(None, after_previous=True),
    Anchor(8),
    Anchor(10),
    Anchor(12),
    Anchor(14),
    Anchor(16),
    Anchor(17),
    Anchor(18),
    Anchor(19),
    Anchor(None, after_previous=True),
    Anchor(20),
    Anchor(22),
    Anchor(24),
    Anchor(26),
    Anchor(28),
    Anchor(30),
    Anchor(31),
    Anchor(32),
    Anchor(34),
    Anchor(36),
    Anchor(38),
)


SIMPLIFIED = str.maketrans(
    "識惻隱療夢囈寫來賦義雲煙變過場電影讓裡見離燈黃長徑話還說落漸遠們臺響聲著尋驚別葉個",
    "识恻隐疗梦呓写来赋义云烟变过场电影让里见离灯黄长径话还说落渐远们台响声着寻惊别叶个",
)


def vlq(value: int) -> bytes:
    out = bytearray((value & 0x7F,))
    value >>= 7
    while value:
        out.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(out)


def meta(kind: int, payload: bytes) -> bytes:
    return bytes((0xFF, kind)) + vlq(len(payload)) + payload


def ticks(seconds: float) -> int:
    return round(seconds * TPQ * 1_000_000 / TEMPO_US)


def parse_lrc(path: Path) -> list[tuple[float, str]]:
    entries: list[tuple[float, str]] = []
    pattern = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\]\s*(.*)")
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        match = pattern.fullmatch(raw.strip())
        if not match or not match.group(3).strip():
            continue
        seconds = int(match.group(1)) * 60 + float(match.group(2))
        entries.append((seconds, match.group(3).strip().translate(SIMPLIFIED)))
    if len(entries) < 39:
        raise SystemExit(f"expected at least 39 timed lyric lines, got {len(entries)}")
    return entries


def word_intervals(path: Path) -> list[tuple[float, float, str]]:
    text = path.read_text(encoding="utf-8")
    first_tier = text.split("item [2]:", 1)[0]
    return [
        (float(start), float(end), word)
        for start, end, word in re.findall(
            r'xmin = ([0-9.]+)\s+xmax = ([0-9.]+)\s+text = "([^"]*)"', first_tier
        )
    ]


def first_sung(intervals: list[tuple[float, float, str]]) -> float:
    return next((start for start, _, word in intervals if word not in {"", "AP", "SP"}), 0.0)


def anchor_local_time(intervals: list[tuple[float, float, str]], word: str | None) -> float:
    if word is None:
        return first_sung(intervals)
    for start, _, current in intervals:
        if current == word:
            return start
    raise SystemExit(f"anchor word {word!r} not found")


def locate_ffmpeg(root: Path) -> tuple[Path, Path]:
    candidates = sorted(root.glob("ffmpeg/**/bin/ffmpeg.exe"))
    if not candidates:
        raise SystemExit("bundled ffmpeg.exe was not found")
    ffmpeg = candidates[-1]
    ffprobe = ffmpeg.with_name("ffprobe.exe")
    if not ffprobe.exists():
        raise SystemExit("ffprobe.exe was not found beside ffmpeg.exe")
    return ffmpeg, ffprobe


def probe_duration(ffprobe: Path, audio: Path) -> float:
    output = subprocess.check_output(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio),
        ],
        text=True,
        encoding="utf-8",
    )
    return float(output.strip())


def build_midi(
    path: Path,
    rows: list[dict[str, object]],
    offsets: list[float],
    total_duration: float,
) -> dict[str, object]:
    events: list[tuple[int, int, bytes]] = [
        (0, 0, meta(0x03, "云烟成雨 - M4Singer人工乐谱/原曲时间轴".encode("utf-8"))),
        (0, 1, meta(0x51, TEMPO_US.to_bytes(3, "big"))),
        (0, 2, bytes((0xC0, 53))),
    ]
    note_count = 0
    min_pitch = 127
    max_pitch = 0
    last_note = 0
    for offset, row in zip(offsets, rows):
        lyric = str(row["txt"])
        events.append((ticks(offset), 3, meta(0x05, lyric.encode("utf-8"))))
        notes = list(row["notes"])
        durations = list(row["ph_dur"])
        if len(notes) != len(durations):
            raise SystemExit(f"score/alignment length differs: {row['item_name']}")
        local = 0.0
        for pitch_raw, duration_raw in zip(notes, durations):
            pitch = int(pitch_raw)
            duration = float(duration_raw)
            if pitch > 0:
                start = ticks(offset + local)
                end = max(start + 1, ticks(offset + local + duration))
                events.append((start, 5, bytes((0x90, pitch, 88))))
                events.append((end, 4, bytes((0x80, pitch, 0))))
                note_count += 1
                min_pitch = min(min_pitch, pitch)
                max_pitch = max(max_pitch, pitch)
                last_note = max(last_note, end)
            local += duration
    events.append((ticks(total_duration), 6, meta(0x06, b"BGM end")))
    events.sort(key=lambda event: (event[0], event[1]))
    track = bytearray()
    previous = 0
    for tick, _, payload in events:
        track += vlq(tick - previous) + payload
        previous = tick
    track += b"\x00" + meta(0x2F, b"")
    path.write_bytes(
        b"MThd"
        + struct.pack(">IHHH", 6, 0, 1, TPQ)
        + b"MTrk"
        + struct.pack(">I", len(track))
        + track
    )
    return {
        "notes": note_count,
        "pitch_range": [min_pitch, max_pitch],
        "last_note_seconds": round(last_note * TEMPO_US / (TPQ * 1_000_000), 3),
        "timeline_seconds": round(total_duration, 3),
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="folder containing meta and original phrases")
    parser.add_argument("bgm", type=Path)
    parser.add_argument("timeline_lrc", type=Path)
    args = parser.parse_args()

    source = args.source.resolve()
    project_root = Path(__file__).resolve().parents[1]
    ffmpeg, ffprobe = locate_ffmpeg(project_root)
    bgm_duration = probe_duration(ffprobe, args.bgm.resolve())
    lrc_entries = parse_lrc(args.timeline_lrc.resolve())

    all_meta = json.loads((source / "M4Singer-meta.json").read_text(encoding="utf-8"))
    song_prefix = next(
        row["item_name"].rsplit("#", 1)[0]
        for row in all_meta
        if row["item_name"].endswith("#0000") and row.get("txt") == "哼你的晚安"
    )
    rows = sorted(
        (row for row in all_meta if row["item_name"].rsplit("#", 1)[0] == song_prefix),
        key=lambda row: row["item_name"],
    )
    phrase_root = next(
        path for path in source.iterdir() if path.is_dir() and (path / "wav").is_dir() and (path / "TextGrid").is_dir()
    )
    wavs = sorted((phrase_root / "wav").glob("*.wav"))
    grids = sorted((phrase_root / "TextGrid").glob("*.TextGrid"))
    if not (len(ANCHORS) == len(rows) == len(wavs) == len(grids) == 29):
        raise SystemExit(
            f"incomplete song: anchors={len(ANCHORS)} meta={len(rows)} wav={len(wavs)} TextGrid={len(grids)}"
        )

    wav_info: list[tuple[int, int, int, int]] = []
    for wav_path in wavs:
        with wave.open(str(wav_path), "rb") as src:
            wav_info.append((src.getnchannels(), src.getsampwidth(), src.getframerate(), src.getnframes()))
    channels, width, rate, _ = wav_info[0]
    if (channels, width, rate) != (1, 2, 48_000) or any(info[:3] != (channels, width, rate) for info in wav_info):
        raise SystemExit(f"unexpected or inconsistent source WAV format: {wav_info[0][:3]}")

    offsets: list[float] = []
    for index, (anchor, grid, info) in enumerate(zip(ANCHORS, grids, wav_info)):
        if anchor.after_previous:
            previous_duration = wav_info[index - 1][3] / rate
            offset = offsets[index - 1] + previous_duration
        else:
            assert anchor.lrc_line is not None
            local_time = anchor_local_time(word_intervals(grid), anchor.word)
            offset = lrc_entries[anchor.lrc_line][0] - local_time
        if offset < 0:
            raise SystemExit(f"negative phrase offset at {index}: {offset}")
        offsets.append(offset)

    total_frames = round(bgm_duration * rate)
    timeline = array("h", [0]) * total_frames
    overlap_samples = 0
    for offset, wav_path in zip(offsets, wavs):
        with wave.open(str(wav_path), "rb") as src:
            samples = array("h")
            samples.frombytes(src.readframes(src.getnframes()))
        start = round(offset * rate)
        if start + len(samples) > len(timeline):
            raise SystemExit(f"phrase exceeds BGM timeline: {wav_path.name}")
        for local_index, sample in enumerate(samples):
            target_index = start + local_index
            if timeline[target_index] and sample:
                overlap_samples += 1
            mixed = timeline[target_index] + sample
            timeline[target_index] = max(-32768, min(32767, mixed))

    aligned_vocal = source / "云烟成雨-M4Singer女声原曲时间轴干声.wav"
    with wave.open(str(aligned_vocal), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        dst.writeframes(timeline.tobytes())

    output_lrc = source / "云烟成雨-M4Singer女声+BGM完整混音.lrc"
    lrc_lines = [
        "[ti:云烟成雨]",
        "[ar:M4Singer Alto-1 + 风雅官网伴奏]",
        "[by:LRCLIB 4:01 时间轴]",
    ]
    for timestamp, lyric in lrc_entries:
        centiseconds = round(timestamp * 100)
        minute, centiseconds = divmod(centiseconds, 6000)
        second, centiseconds = divmod(centiseconds, 100)
        lrc_lines.append(f"[{minute:02d}:{second:02d}.{centiseconds:02d}]{lyric}")
    output_lrc.write_text("\n".join(lrc_lines) + "\n", encoding="utf-8-sig")

    output_midi = source / "云烟成雨-M4Singer人工乐谱-原曲时间轴.mid"
    midi_info = build_midi(output_midi, rows, offsets, bgm_duration)

    output_mix = source / "云烟成雨-M4Singer女声+BGM完整混音.wav"
    subprocess.run(
        [
            str(ffmpeg),
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-i",
            str(args.bgm.resolve()),
            "-i",
            str(aligned_vocal),
            "-filter_complex",
            "[0:a]aresample=48000,volume=-6dB[bgm];"
            "[1:a]pan=stereo|c0=c0|c1=c0,volume=-1dB[vocal];"
            "[bgm][vocal]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            "alimiter=limit=0.95[out]",
            "-map",
            "[out]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(output_mix),
        ],
        check=True,
    )

    products = {
        "mixed_wav": output_mix,
        "aligned_lrc": output_lrc,
        "aligned_midi": output_midi,
        "aligned_dry_vocal": aligned_vocal,
        "downloaded_bgm": args.bgm.resolve(),
        "downloaded_timeline_lrc": args.timeline_lrc.resolve(),
    }
    summary: dict[str, object] = {
        "source_vocal": "M4Singer Alto-1#云烟成雨",
        "source_bgm": "嘉兴风雅乐器制造有限公司官网公开伴奏下载",
        "timeline": "LRCLIB track 34492273 (duration 241 seconds)",
        "phrases": len(rows),
        "bgm_duration_seconds": round(bgm_duration, 6),
        "mix": {"sample_rate": 48_000, "channels": 2, "bit_depth": 16, "bgm_gain_db": -6, "vocal_gain_db": -1},
        "midi": midi_info,
        "overlap_samples": overlap_samples,
        "phrase_offsets_seconds": [round(value, 3) for value in offsets],
        "files": {},
    }
    for key, path in products.items():
        summary["files"][key] = {
            "name": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        }
    (source / "混音校验信息.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
