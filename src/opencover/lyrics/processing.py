from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path


_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_END_TIMESTAMP = re.compile(r"\[end:(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
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
    end: float | None = None


@dataclass(frozen=True)
class LyricSegment:
    start: float
    end: float
    original_text: str
    new_text: str
    character_timings: tuple[tuple[float, float], ...] | None = None
    prompt_start: float | None = None
    prompt_end: float | None = None
    prompt_text: str | None = None
    prompt_character_timings: tuple[tuple[float, float], ...] | None = None

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
        end_stamp = _END_TIMESTAMP.search(line)
        end_value: float | None = None
        if end_stamp:
            end_minutes, end_seconds, end_fraction = end_stamp.groups()
            end_decimal = int(end_fraction or 0) / (10 ** len(end_fraction or "0"))
            end_value = int(end_minutes) * 60 + int(end_seconds) + end_decimal
        stamps = list(_TIMESTAMP.finditer(line))
        cleaned = _END_TIMESTAMP.sub("", _TIMESTAMP.sub("", line)).strip()
        if _CREDIT.match(cleaned):
            continue
        if stamps:
            if not cleaned:
                continue
            for stamp in stamps:
                minutes, seconds, fraction = stamp.groups()
                decimal = int(fraction or 0) / (10 ** len(fraction or "0"))
                cues.append(LyricCue(cleaned, int(minutes) * 60 + int(seconds) + decimal, end_value))
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
        words = raw.get("words")
        word_ends: list[float] = []
        if isinstance(words, list):
            for word in words:
                try:
                    candidate = float(word["end"]) if isinstance(word, dict) else -1.0
                except (KeyError, TypeError, ValueError):
                    continue
                if start < candidate <= end + 0.5:
                    word_ends.append(candidate)
        if word_ends:
            end = min(end, max(word_ends))
        if not 0 <= start < end <= duration + 0.5 or start <= last_start:
            raise ValueError("自动对齐时间不是严格递增的有效区间")
        last_start = start
        minutes = int(start // 60)
        seconds = start - minutes * 60
        end_minutes = int(end // 60)
        end_seconds = end - end_minutes * 60
        result.append(f"[{minutes:02d}:{seconds:05.2f}][end:{end_minutes:02d}:{end_seconds:05.2f}]{line}")
    return "\n".join(result)


def timed_lyrics_from_transcription(
    transcription: dict[str, object], duration: float, *, language: str = "zh",
) -> str:
    """Validate ASR output and turn singing segments into an internal LRC."""
    raw_segments = transcription.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("自动歌词识别没有返回有效分段")
    result: list[str] = []
    last_start = -1.0
    character_count = 0
    timed_word_count = 0
    probabilities: list[float] = []
    segment_logprobs: list[float] = []
    no_speech_probabilities: list[float] = []
    for raw in raw_segments:
        if not isinstance(raw, dict):
            raise ValueError("自动歌词识别分段格式无效")
        text = str(raw.get("text") or "").strip()
        if not text:
            continue
        try:
            start, end = float(raw["start"]), float(raw["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("自动歌词识别分段缺少有效时间") from exc
        if not 0 <= start < end <= duration + 0.5 or start <= last_start:
            raise ValueError("自动歌词识别时间不是严格递增的有效区间")
        last_start = start
        characters = _PUNCTUATION.sub("", text)
        character_count += len(characters)
        avg_logprob = raw.get("avg_logprob")
        if isinstance(avg_logprob, (int, float)):
            segment_logprobs.append(float(avg_logprob))
        no_speech_prob = raw.get("no_speech_prob")
        if isinstance(no_speech_prob, (int, float)):
            no_speech_probabilities.append(float(no_speech_prob))
        words = raw.get("words") or []
        if isinstance(words, list):
            for word in words:
                if not isinstance(word, dict):
                    continue
                try:
                    word_start, word_end = float(word["start"]), float(word["end"])
                except (KeyError, TypeError, ValueError):
                    continue
                if word_end > word_start:
                    timed_word_count += 1
                probability = word.get("probability")
                if isinstance(probability, (int, float)):
                    probabilities.append(float(probability))
        minutes = int(start // 60)
        seconds = start - minutes * 60
        result.append(f"[{minutes:02d}:{seconds:05.2f}]{text}")
    if not result or character_count < 2 or timed_word_count == 0:
        raise ValueError("自动歌词识别内容过少或没有词级时间")
    if language == "zh":
        cjk_count = sum(1 for character in "".join(result) if "\u4e00" <= character <= "\u9fff")
        if cjk_count / max(1, character_count) < 0.55:
            raise ValueError("中文歌词识别结果中的中文字比例过低")
    if probabilities:
        mean_probability = sum(probabilities) / len(probabilities)
        low_probability_ratio = sum(value < 0.20 for value in probabilities) / len(probabilities)
        if mean_probability < 0.55 or low_probability_ratio > 0.20:
            raise ValueError("自动歌词识别的词级置信度过低")
    if segment_logprobs and sum(segment_logprobs) / len(segment_logprobs) < -0.75:
        raise ValueError("自动歌词识别的段级置信度过低")
    if no_speech_probabilities and sum(no_speech_probabilities) / len(no_speech_probabilities) > 0.35:
        raise ValueError("自动歌词识别将过多非人声区域判为歌词")
    return "\n".join(result)


def _units(text: str) -> int:
    return max(1, len(_PUNCTUATION.sub("", text)))


def _cjk_characters(text: str) -> list[str]:
    return [character for character in text if "\u4e00" <= character <= "\u9fff"]


def lyric_edit_count(original: str, replacement: str) -> int:
    """Return the true character edit distance for synthesis planning."""
    original_units = [character.lower() for character in original if character.isalnum()]
    replacement_units = [character.lower() for character in replacement if character.isalnum()]
    previous = list(range(len(replacement_units) + 1))
    for old_index, old_character in enumerate(original_units, start=1):
        current = [old_index]
        for new_index, new_character in enumerate(replacement_units, start=1):
            current.append(min(
                current[-1] + 1,
                previous[new_index] + 1,
                previous[new_index - 1] + (old_character != new_character),
            ))
        previous = current
    return previous[-1]


def split_dense_rewrite_segment(
    segment: LyricSegment,
    character_timings: list[tuple[float, float]],
    *,
    edit_threshold: int = 2,
    maximum_duration: float = 3.5,
    maximum_characters: int = 6,
    maximum_edits: int = 4,
) -> list[LyricSegment]:
    """Split a dense rewrite only at forced-aligned original character gaps.

    Small edits retain the full phrase context. Dense edits are divided into
    short prompts whose audio windows and score timings both come from the same
    original-singing slice.
    """
    if lyric_edit_count(segment.original_text, segment.new_text) <= edit_threshold:
        return [segment]
    original = _cjk_characters(segment.original_text)
    replacement = _cjk_characters(segment.new_text)
    if not original or not replacement or len(character_timings) != len(original):
        raise ValueError("高密度改词缺少完整的原唱逐字边界")
    if maximum_duration <= 0 or maximum_characters <= 0 or maximum_edits <= 0:
        raise ValueError("高密度改词切片参数无效")
    if any(end <= start for start, end in character_timings):
        raise ValueError("高密度改词的原唱逐字边界无效")

    edit_count = lyric_edit_count(segment.original_text, segment.new_text)
    count = max(
        math.ceil(segment.duration / maximum_duration),
        math.ceil(max(len(original), len(replacement)) / maximum_characters),
        math.ceil(edit_count / maximum_edits),
    )
    count = max(1, min(count, len(original), len(replacement)))
    if count == 1:
        return [replace_segment_timings(segment, character_timings)]

    maximum_count = min(len(original), len(replacement))
    while True:
        old_boundaries = [round(index * len(original) / count) for index in range(count + 1)]
        new_boundaries = [round(index * len(replacement) / count) for index in range(count + 1)]
        time_boundaries = [0.0]
        for boundary in old_boundaries[1:-1]:
            left_end = character_timings[boundary - 1][1]
            right_start = character_timings[boundary][0]
            time_boundaries.append(max(0.0, min(segment.duration, (left_end + right_start) / 2)))
        time_boundaries.append(segment.duration)
        if any(time_boundaries[index] <= time_boundaries[index - 1] for index in range(1, len(time_boundaries))):
            raise ValueError("高密度改词无法在原唱字间隙形成有效切片")
        within_limits = all(
            time_boundaries[index + 1] - time_boundaries[index] <= maximum_duration + 1e-6
            and old_boundaries[index + 1] - old_boundaries[index] <= maximum_characters
            and new_boundaries[index + 1] - new_boundaries[index] <= maximum_characters
            and lyric_edit_count(
                "".join(original[old_boundaries[index]:old_boundaries[index + 1]]),
                "".join(replacement[new_boundaries[index]:new_boundaries[index + 1]]),
            ) <= maximum_edits
            for index in range(count)
        )
        if within_limits or count >= maximum_count:
            break
        count += 1

    planned: list[LyricSegment] = []
    for index in range(count):
        old_start, old_end = old_boundaries[index], old_boundaries[index + 1]
        new_start, new_end = new_boundaries[index], new_boundaries[index + 1]
        slice_start, slice_end = time_boundaries[index], time_boundaries[index + 1]
        local_timings = tuple(
            (max(0.0, start - slice_start), min(slice_end - slice_start, end - slice_start))
            for start, end in character_timings[old_start:old_end]
        )
        if any(end <= start for start, end in local_timings):
            raise ValueError("高密度改词切片截断了原唱字边界")
        planned.append(LyricSegment(
            segment.start + slice_start,
            segment.start + slice_end,
            "".join(original[old_start:old_end]),
            "".join(replacement[new_start:new_end]),
            local_timings,
            segment.start,
            segment.end,
            "".join(original),
            tuple(character_timings),
        ))
    return planned


def replace_segment_timings(
    segment: LyricSegment, character_timings: list[tuple[float, float]],
) -> LyricSegment:
    return LyricSegment(
        segment.start, segment.end, segment.original_text, segment.new_text,
        tuple(character_timings),
    )


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

def adaptive_chunk_count(duration: float, *, minimum: float = 5.0, maximum: float = 9.0) -> int:
    """Choose a near 5-9 second phrase count without creating tiny tails."""
    if duration <= maximum:
        return 1
    count = math.ceil(duration / maximum)
    if duration / count >= minimum:
        return count
    # A span just over the maximum is safer as one slightly long phrase than
    # two sub-five-second phrases cut through syllables.
    return max(1, math.floor(duration / minimum))




def split_lyric_segments(segments: list[LyricSegment]) -> list[LyricSegment]:
    """Split already-timed lyric lines without changing their total text."""
    planned: list[LyricSegment] = []
    for segment in segments:
        count = adaptive_chunk_count(segment.duration)
        old_parts = _split_text(segment.original_text, count)
        new_parts = _split_text(segment.new_text, count)
        for index in range(count):
            part_start = segment.start + segment.duration * index / count
            part_end = segment.start + segment.duration * (index + 1) / count
            if new_parts[index]:
                planned.append(LyricSegment(
                    part_start, part_end, old_parts[index] or segment.original_text, new_parts[index],
                ))
    return planned

def build_lyric_segments(original: str, replacement: str, duration: float, strategy: str = "均衡", *, split_phrases: bool = True) -> list[LyricSegment]:
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
            if cue.end is not None:
                end = min(duration, max(start + 0.25, float(cue.end)))
            else:
                end = float(timed[index + 1].start) if index + 1 < len(timed) else duration
                # Standard LRC has only starts. Recognized/aligned lines carry
                # an explicit end, so only unknown tails need this safety cap.
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
        planned.append(LyricSegment(start, end, old_text, new_text))
    if not planned:
        raise ValueError("歌词没有产生可生成的有效短句")
    return split_lyric_segments(planned) if split_phrases else planned
