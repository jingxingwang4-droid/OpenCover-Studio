from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path


_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_METADATA = re.compile(r"^\[(?:ar|al|ti|by|offset|re|ve):", re.IGNORECASE)
_CREDIT = re.compile(
    r"^(?:\u4f5c\u8bcd|\u4f5c\u66f2|\u7f16\u66f2|\u539f\u66f2|\u539f\u5531|\u6f14\u5531|\u6b4c\u624b|\u586b\u8bcd|\u8c31\u66f2|\u5236\u4f5c\u4eba|\u5236\u4f5c|\u6df7\u97f3|\u53d1\u884c|\u6240\u5c5e\u4e13\u8f91|\u4e13\u8f91)\s*[:\uff1a]",
    re.IGNORECASE,
)
_PUNCTUATION = re.compile(r"[\s\u3000，。！？、；：,.!?;:'\"“”‘’（）()【】\[\]《》…—-]+")


@dataclass(frozen=True)
class LyricCue:
    text: str
    start: float | None = None


@dataclass(frozen=True)
class LyricSegment:
    start: float
    end: float
    original_text: str
    new_text: str

    @property
    def duration(self) -> float:
        return self.end - self.start


def decode_lyrics_file(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("歌词文件不能超过 2 MiB")
    for encoding in ("utf-8-sig", "utf-16", "gb18030", "shift_jis"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError("无法识别歌词编码；请转换为 UTF-8、GBK 或常见日文编码")


def parse_lyrics(text: str) -> list[LyricCue]:
    cues: list[LyricCue] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line or _METADATA.match(line):
            continue
        stamps = list(_TIMESTAMP.finditer(line))
        cleaned = _TIMESTAMP.sub("", line).strip()
        if _CREDIT.match(cleaned):
            continue
        if stamps:
            if not cleaned:
                continue
            for stamp in stamps:
                minutes, seconds, fraction = stamp.groups()
                decimal = int(fraction or 0) / (10 ** len(fraction or "0"))
                cues.append(LyricCue(cleaned, int(minutes) * 60 + int(seconds) + decimal))
        else:
            tag_free = re.sub(r"\[[^]]+\]", "", cleaned).strip()
            if tag_free:
                cues.append(LyricCue(tag_free, None))
    return sorted(cues, key=lambda cue: cue.start or 0.0) if any(c.start is not None for c in cues) else cues


def lyrics_language(text: str) -> str:
    """Choose the Whisper tokenizer language from the user's lyric script."""
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "en"


def timed_lyrics_from_alignment(original: str, alignment: dict[str, object], duration: float) -> str:
    lines = [cue.text for cue in parse_lyrics(original)]
    raw_segments = alignment.get("segments")
    if not isinstance(raw_segments, list) or len(raw_segments) != len(lines):
        raise ValueError(f"自动对齐返回 {len(raw_segments or []) if isinstance(raw_segments, list) else 0} 段，但原歌词有 {len(lines)} 行")
    result: list[str] = []
    last_start = -1.0
    for line, raw in zip(lines, raw_segments):
        if not isinstance(raw, dict):
            raise ValueError("自动对齐结果格式无效")
        try:
            start = float(raw["start"])
            end = float(raw["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("自动对齐分段缺少有效时间") from exc
        if not 0 <= start < end <= duration + 0.5 or start <= last_start:
            raise ValueError("自动对齐时间不是严格递增的有效区间")
        last_start = start
        minutes = int(start // 60)
        seconds = start - minutes * 60
        result.append(f"[{minutes:02d}:{seconds:05.2f}]{line}")
    return "\n".join(result)


def _units(text: str) -> int:
    return max(1, len(_PUNCTUATION.sub("", text)))


def _split_text(text: str, count: int) -> list[str]:
    compact = text.strip()
    if count <= 1:
        return [compact]
    characters = list(compact)
    return [
        "".join(characters[round(index * len(characters) / count):round((index + 1) * len(characters) / count)]).strip()
        for index in range(count)
    ]


def _redistribute(lines: list[str], weights: list[int]) -> list[str]:
    if len(lines) == len(weights):
        return lines
    joined = "".join(line.strip() for line in lines)
    if not joined:
        raise ValueError("新歌词不能为空")
    total = sum(weights)
    boundaries = [0]
    cumulative = 0
    for weight in weights[:-1]:
        cumulative += weight
        boundaries.append(round(len(joined) * cumulative / total))
    boundaries.append(len(joined))
    return [joined[boundaries[i]:boundaries[i + 1]].strip() for i in range(len(weights))]


def build_lyric_segments(original: str, replacement: str, duration: float, strategy: str = "均衡") -> list[LyricSegment]:
    if not 0.5 <= duration <= 4 * 60 * 60:
        raise ValueError("输入音频时长不受支持")
    original_cues = parse_lyrics(original)
    replacement_cues = parse_lyrics(replacement)
    if not original_cues:
        raise ValueError("原歌词不能为空")
    if not replacement_cues:
        raise ValueError("新歌词不能为空")

    timed = [cue for cue in original_cues if cue.start is not None]
    base: list[tuple[float, float, str]] = []
    if timed:
        for index, cue in enumerate(timed):
            start = min(duration, max(0.0, float(cue.start or 0.0)))
            end = float(timed[index + 1].start) if index + 1 < len(timed) else duration
            # LRC usually stores line starts. A large gap contains an
            # instrumental break or outro, not more lyric phrases.
            end = min(duration, start + 15.0, max(start + 0.25, end))
            if start < duration:
                base.append((start, end, cue.text))
    else:
        line_count = len(original_cues)
        if duration / line_count > 18.0:
            raise ValueError("无时间戳歌词的行数过少；长音频请导入 LRC，或把歌词按短句逐行拆分")
        weights = [_units(cue.text) for cue in original_cues]
        total = sum(weights)
        cursor = 0.0
        for index, cue in enumerate(original_cues):
            end = duration if index == line_count - 1 else duration * sum(weights[:index + 1]) / total
            base.append((cursor, end, cue.text))
            cursor = end

    new_lines = [cue.text for cue in replacement_cues]
    allocated = _redistribute(new_lines, [_units(text) for _, _, text in base])
    ratio_limit = {"保守": 1.35, "均衡": 1.8, "强制": 2.5}.get(strategy, 1.8)
    planned: list[LyricSegment] = []
    for (start, end, old_text), new_text in zip(base, allocated):
        if _units(new_text) / _units(old_text) > ratio_limit:
            raise ValueError(f"新歌词“{new_text}”明显长于原句；请缩短文本或改用更强的适配策略")
        count = max(1, math.ceil((end - start) / 15.0))
        old_parts = _split_text(old_text, count)
        new_parts = _split_text(new_text, count)
        for index in range(count):
            part_start = start + (end - start) * index / count
            part_end = start + (end - start) * (index + 1) / count
            if new_parts[index]:
                planned.append(LyricSegment(part_start, part_end, old_parts[index] or old_text, new_parts[index]))
    if not planned:
        raise ValueError("歌词没有产生可生成的有效短句")
    return planned
