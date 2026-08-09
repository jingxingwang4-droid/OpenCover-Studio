"""Lyric decoding, parsing and conservative segment planning."""

from .processing import LyricSegment, build_lyric_segments, decode_lyrics_file

__all__ = ["LyricSegment", "build_lyric_segments", "decode_lyrics_file"]
