"""Group adjacent edited lines for synthesis without absorbing unchanged lyrics."""
from opencover.lyrics.processing import LyricSegment
from opencover.lyrics.score import lyric_text_identity


def changed_phrases(planned: list[LyricSegment], maximum_seconds: float = 7.0):
    groups = []
    intervals = []
    adjacent = False
    for segment in planned:
        changed = lyric_text_identity(segment.original_text) != lyric_text_identity(segment.new_text)
        if not changed:
            adjacent = False
            continue
        intervals.append((segment.start, segment.end))
        # Keep short lines' consonant attacks independent. Pair longer adjacent
        # lines for acoustic context, but never cross a meaningful phrase pause.
        if (adjacent and groups[-1].duration >= 2.5 and segment.duration >= 2.5
                and segment.start-groups[-1].end <= .2 + 1e-6
                and segment.end-groups[-1].start <= maximum_seconds):
            previous=groups[-1]
            groups[-1]=LyricSegment(previous.start,segment.end,
                previous.original_text+'\n'+segment.original_text,previous.new_text+'\n'+segment.new_text)
        else:
            groups.append(segment)
        adjacent = True
    return groups, intervals
