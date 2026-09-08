from __future__ import annotations

from pathlib import Path

import pytest

from opencover.lyrics.processing import (
    LyricSegment, adaptive_chunk_count, build_lyric_segments, decode_lyrics_file,
    lyric_edit_count, lyrics_language, parse_lyrics, split_dense_rewrite_segment,
    timed_lyrics_from_alignment, timed_lyrics_from_transcription,
)


def test_decode_gbk_and_parse_lrc(tmp_path: Path) -> None:
    path = tmp_path / "歌词.lrc"
    path.write_bytes("[ar:测试]\n[00:01.50]第一句\n[00:05.25][00:09.00]第二句".encode("gb18030"))
    cues = parse_lyrics(decode_lyrics_file(path))
    assert [(cue.text, cue.start) for cue in cues] == [("第一句", 1.5), ("第二句", 5.25), ("第二句", 9.0)]


def test_build_timed_segments_and_redistribute_new_text() -> None:
    segments = build_lyric_segments(
        "[00:01.00]春天到来\n[00:06.00]听见花开",
        "新的春天正在眼前\n听见花开的声音",
        duration=12.0,
        strategy="强制",
    )
    assert [(item.start, item.end) for item in segments] == [(1.0, 6.0), (6.0, 12.0)]
    assert segments[0].new_text == "新的春天正在眼前"
    assert segments[1].new_text == "听见花开的声音"


def test_long_untimed_song_requires_more_lines() -> None:
    with pytest.raises(ValueError, match="LRC"):
        build_lyric_segments("只有一句", "替换一句", duration=120.0)


def test_balanced_strategy_rejects_extreme_density() -> None:
    with pytest.raises(ValueError, match="明显长于原句"):
        build_lyric_segments("短句", "这是一句明显过长而且无法合理塞入原旋律的新歌词", duration=6.0, strategy="均衡")


def test_alignment_result_preserves_user_lines_and_detects_script() -> None:
    aligned = timed_lyrics_from_alignment(
        "春天到来\n花在歌唱",
        {"segments": [{"start": 1.25, "end": 5.0, "words": [{"end": 4.0}]}, {"start": 5.5, "end": 9.0}]},
        duration=10.0,
    )
    assert aligned == "[00:01.25][end:00:04.00]春天到来\n[00:05.50][end:00:09.00]花在歌唱"
    assert lyrics_language(aligned) == "zh"
    assert lyrics_language("春の日、歌う") == "ja"
    assert lyrics_language("sing a song") == "en"


def test_transcription_result_becomes_internal_lrc_and_checks_quality() -> None:
    result = timed_lyrics_from_transcription({"segments": [
        {"start": 1.2, "end": 2.5, "text": "轻舟已过", "words": [
            {"word": "轻舟", "start": 1.2, "end": 1.8, "probability": 0.8},
            {"word": "已过", "start": 1.8, "end": 2.5, "probability": 0.7},
        ]},
        {"start": 3.0, "end": 4.8, "text": "柳絮满长街", "words": [
            {"word": "柳絮满长街", "start": 3.0, "end": 4.8, "probability": 0.6},
        ]},
    ]}, 5.0)
    assert result == "[00:01.20]轻舟已过\n[00:03.00]柳絮满长街"
    with pytest.raises(ValueError, match="中文字比例"):
        timed_lyrics_from_transcription({"segments": [{
            "start": 0.1, "end": 1.0, "text": "hello world",
            "words": [{"word": "hello", "start": 0.1, "end": 1.0}],
        }]}, 2.0)
    with pytest.raises(ValueError, match="置信度"):
        timed_lyrics_from_transcription({"segments": [{
            "start": 0.1, "end": 1.0, "text": "轻舟已过",
            "avg_logprob": -0.9, "no_speech_prob": 0.4,
            "words": [{"word": "轻舟已过", "start": 0.1, "end": 1.0, "probability": 0.3}],
        }]}, 2.0)


def test_alignment_rejects_segment_count_or_non_monotonic_time() -> None:
    with pytest.raises(ValueError, match="原歌词有 2 行"):
        timed_lyrics_from_alignment("第一行\n第二行", {"segments": [{"start": 0.0, "end": 1.0}]}, 3.0)
    with pytest.raises(ValueError, match="严格递增"):
        timed_lyrics_from_alignment(
            "第一行\n第二行",
            {"segments": [{"start": 1.0, "end": 2.0}, {"start": 0.5, "end": 2.5}]},
            3.0,
        )


def test_adaptive_phrase_count_targets_five_to_nine_seconds() -> None:
    assert adaptive_chunk_count(8.9) == 1
    assert adaptive_chunk_count(9.2) == 1
    assert adaptive_chunk_count(10.0) == 2
    assert adaptive_chunk_count(14.0) == 2
    assert adaptive_chunk_count(20.0) == 3


def test_long_lrc_line_is_split_into_near_five_to_nine_second_phrases() -> None:
    original = "abcdefghijklmnopqrstuvwxyz1234567890"
    segments = build_lyric_segments(
        f"[00:44.00][end:01:05.00]{original}\n[01:05.00][end:01:10.00]tail",
        f"{original}\ntail",
        duration=70.0,
    )
    first_line = segments[:3]
    assert len(first_line) == 3
    assert all(5.0 <= item.duration <= 9.0 for item in first_line)
    assert "".join(item.original_text for item in first_line) == original


def test_small_lyric_edit_keeps_full_phrase_context() -> None:
    segment = LyricSegment(10.0, 16.0, "你的晚安是恻隐", "你的早安是恻隐")
    timings = [(index * 0.7, index * 0.7 + 0.5) for index in range(7)]
    assert lyric_edit_count(segment.original_text, segment.new_text) == 1
    assert split_dense_rewrite_segment(segment, timings) == [segment]


def test_dense_rewrite_uses_exact_original_character_gaps() -> None:
    original = "春夏秋冬东西南北天地山河"
    replacement = "甲乙丙丁戊己庚辛壬癸子丑"
    segment = LyricSegment(10.0, 18.0, original, replacement)
    timings = [(0.2 + index * 0.6, 0.65 + index * 0.6) for index in range(12)]

    planned = split_dense_rewrite_segment(segment, timings)

    assert len(planned) == 3
    assert "".join(item.original_text for item in planned) == original
    assert "".join(item.new_text for item in planned) == replacement
    assert planned[0].start == segment.start
    assert planned[-1].end == segment.end
    assert all(left.end == right.start for left, right in zip(planned, planned[1:]))
    expected_first_boundary = segment.start + (timings[3][1] + timings[4][0]) / 2
    assert planned[0].end == pytest.approx(expected_first_boundary)
    assert planned[0].character_timings == tuple(timings[:4])
    assert planned[1].character_timings is not None
    assert all(item.prompt_start == segment.start for item in planned)
    assert all(item.prompt_end == segment.end for item in planned)
    assert all(item.prompt_text == original for item in planned)
    assert all(item.prompt_character_timings == tuple(timings) for item in planned)
    assert planned[1].character_timings[0][0] == pytest.approx(
        timings[4][0] - (planned[1].start - segment.start)
    )
    assert all(len(item.original_text) <= 6 for item in planned)
    assert all(lyric_edit_count(item.original_text, item.new_text) <= 4 for item in planned)
