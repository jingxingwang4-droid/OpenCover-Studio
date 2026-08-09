from __future__ import annotations

from pathlib import Path

import pytest

from opencover.lyrics.processing import build_lyric_segments, decode_lyrics_file, parse_lyrics


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
