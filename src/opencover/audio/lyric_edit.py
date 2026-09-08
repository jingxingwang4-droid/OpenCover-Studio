"""Replace only authorized lyric intervals; preserve the original outside them."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import soundfile as sf


def replace_intervals(source: Path, replacement: Path, intervals: list[tuple[float,float]], output: Path) -> Path:
    original, rate = sf.read(source,always_2d=True,dtype='float32')
    edited, edited_rate = sf.read(replacement,always_2d=True,dtype='float32')
    if rate != edited_rate or abs(len(original)-len(edited)) > 2:
        raise ValueError('区间替换要求相同采样率和时长')
    if edited.shape[1] == 1 and original.shape[1] == 2:
        edited = np.repeat(edited,2,axis=1)
    if original.shape[1] != edited.shape[1]:
        raise ValueError('区间替换声道数量不一致')
    if len(edited) < len(original):
        edited=np.pad(edited,((0,len(original)-len(edited)),(0,0)))
    edited=edited[:len(original)]
    result = original.copy()
    last_end = 0
    for start,end in sorted(intervals):
        a,b = round(start*rate),round(end*rate)
        if a < last_end or a < 0 or b <= a or b > len(result):
            raise ValueError('改词区间无效或重叠')
        patch = edited[a:b].copy()
        # Fade only the new signal: never reintroduce old syllables in the edit.
        fade = min(round(.005*rate),len(patch)//2)
        if fade:
            patch[:fade] *= np.linspace(0,1,fade)[:,None]
            patch[-fade:] *= np.linspace(1,0,fade)[:,None]
        result[a:b] = patch
        last_end = b
    if not np.isfinite(result).all():
        raise ValueError('区间替换结果含非有限值')
    output.parent.mkdir(parents=True,exist_ok=True)
    sf.write(output,result,rate,subtype='FLOAT')
    return output
