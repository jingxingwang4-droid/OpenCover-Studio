"""Validated, time preserving Chinese lyric scores (no model dependencies)."""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher

TOKEN = re.compile(r"AP|SP|[\u4e00-\u9fff]")
NOTE = re.compile(r"([A-G])([#b]?)(-?\d+)")


def characters(text: str) -> str:
    unsupported = [c for c in text if c.isalnum() and not '\u4e00' <= c <= '\u9fff']
    if unsupported:
        raise ValueError("当前中文歌声模型不支持这些歌词字符：" + ''.join(unsupported))
    result = ''.join(c for c in text if '\u4e00' <= c <= '\u9fff')
    if not result:
        raise ValueError("歌词必须包含中文汉字")
    return result


def validate_score(text: str, notes: str, durations: str, duration: float | None = None) -> dict:
    tokens = TOKEN.findall(text)
    if ''.join(tokens) != text or not tokens:
        raise ValueError("内部词谱存在无法发音的字符")
    pitches, lengths = notes.split('|'), durations.split('|')
    if not len(tokens) == len(pitches) == len(lengths):
        raise ValueError("内部词谱歌词、音高、时值数量不一致")
    total = 0.0
    for token, pitch, length in zip(tokens, pitches, lengths):
        ps, ds = pitch.split(), [float(v) for v in length.split()]
        if not ps or len(ps) != len(ds) or any(not math.isfinite(d) or d <= 0 for d in ds):
            raise ValueError("内部词谱音符与时值不匹配或时值无效")
        voiced = 0.0
        for p, d in zip(ps, ds):
            if p == 'rest':
                continue
            match = NOTE.fullmatch(p)
            if not match:
                raise ValueError("内部词谱音高无效：" + p)
            letter, accidental, octave = match.groups()
            midi = (int(octave) + 1) * 12 + {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[letter] + {'':0,'#':1,'b':-1}[accidental]
            if not 36 <= midi <= 96:
                raise ValueError("旋律超出可验证音域 C2–C7：" + p)
            voiced += d
        if token in {'SP', 'AP'} and any(p != 'rest' for p in ps):
            raise ValueError("休止符含有歌声音高")
        if token not in {'SP', 'AP'} and voiced < 0.065:
            raise ValueError(f"“{token}”的发音时间不足 65ms，请缩短该句新歌词或检查对齐")
        total += sum(ds)
    if duration is not None and (not math.isfinite(duration) or abs(total - duration) > 0.003):
        raise ValueError(f"词谱总时长 {total:.4f}s 与原句 {duration:.4f}s 不一致")
    return {'characters': len([t for t in tokens if t not in {'SP','AP'}]), 'duration': total, 'windows': len(tokens)}


def map_target_timings(original: str, target: str, timings: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Keep equal-length edits and unchanged word anchors at their original times."""
    source, replacement = characters(original), characters(target)
    if len(source) != len(timings):
        raise ValueError("逐字对齐数量不匹配")
    if any(not math.isfinite(a+b) or a < 0 or b <= a for a,b in timings):
        raise ValueError("逐字对齐含无效时间")
    if any(b > c + 1e-6 for (_,b),(c,_) in zip(timings,timings[1:])):
        raise ValueError("逐字对齐发生重叠")
    if len(source) == len(replacement):
        return list(timings)
    mapped = []
    for tag, a,b,c,d in SequenceMatcher(None,source,replacement,autojunk=False).get_opcodes():
        if tag == 'equal':
            mapped.extend(timings[a:b])
        elif d > c:
            if a == b:
                # An insertion borrows time from the adjacent original syllable,
                # then rebalances only that syllable and the inserted characters.
                if mapped:
                    start,end = mapped.pop()
                    count = d-c+1
                    mapped.extend((start+(end-start)*i/count,start+(end-start)*(i+1)/count) for i in range(count))
                else:
                    start,end = timings[0]
                    cut = start+(end-start)*(d-c)/(d-c+1)
                    mapped.extend((start+(cut-start)*i/(d-c),start+(cut-start)*(i+1)/(d-c)) for i in range(d-c))
                    timings = [(cut,end), *timings[1:]]
            else:
                start,end = timings[a][0],timings[b-1][1]
                mapped.extend((start+(end-start)*i/(d-c),start+(end-start)*(i+1)/(d-c)) for i in range(d-c))
    if len(mapped) != len(replacement):
        raise ValueError("新歌词分配失败")
    return mapped


def aligned_score(original: str, target: str, duration: float, events: list[tuple[float,float,str]], timings: list[tuple[float,float]]) -> dict:
    mapped = map_target_timings(original,target,timings)
    clean = characters(target)
    cuts = [0.0] + [(left[1]+right[0])/2 for left,right in zip(mapped,mapped[1:])] + [duration]
    if any(b <= a for a,b in zip(cuts,cuts[1:])) or mapped[-1][1] > duration + .05:
        raise ValueError("歌词对齐越过句子边界")
    ordered = sorted(events)
    if any(not math.isfinite(a+b) or a < 0 or b <= a or b > duration+.05 for a,b,_ in ordered):
        raise ValueError("GAME 返回无效音符时间")
    if any(b > c+.001 for (_,b,_),(c,_,_) in zip(ordered,ordered[1:])):
        raise ValueError("GAME 音符存在重叠")
    if len(ordered) >= len(clean):
        # Keep a syllable onset on a complete note, as in the accepted score
        # baseline. Cutting every note at a noisy ASR boundary produces tiny
        # initial notes and repeated vowels that damage consonants.
        previous = 0
        for i in range(1,len(clean)):
            candidates = range(previous+1,len(ordered)-(len(clean)-i)+1)
            cut = min(candidates,key=lambda k:abs(ordered[k-1][1]-mapped[i-1][1])
                      + max(0,.20-(ordered[k-1][1]-ordered[previous][0]))*2)
            cuts[i] = (ordered[cut-1][1]+ordered[cut][0])/2
            previous = cut
    # Alignment and F0 boundaries differ slightly. Avoid giving a consonant
    # only a few milliseconds on the preceding note before the real vowel.
    edges = sorted({v for a,b,_ in ordered for v in (a,b)})
    for i in range(1,len(cuts)-1):
        candidates = [edge for edge in edges if abs(edge-cuts[i]) <= .05
                      and cuts[i-1]+.065 <= edge <= cuts[i+1]-.065]
        if candidates:
            cuts[i] = min(candidates,key=lambda edge:abs(edge-cuts[i]))
    tokens, pitches, lengths, mapping = [],[],[],[]
    for char,start,end in zip(clean,cuts,cuts[1:]):
        hits = [(max(a,start),min(b,end),p) for a,b,p in ordered if min(b,end)-max(a,start) > 1e-6]
        if not hits:
            raise ValueError(f"“{char}”没有对应原唱音符，请检查原歌词和时间戳")
        if hits[0][0] > start+1e-6:
            tokens.append('SP'); pitches.append('rest'); lengths.append(f'{hits[0][0]-start:.6f}')
        ns, ds, cursor = [],[],hits[0][0]
        for a,b,p in hits:
            if a > cursor+1e-6:
                ns.append('rest'); ds.append(a-cursor)
            if ns and ns[-1]==p and abs(a-cursor)<1e-6:
                ds[-1]+=b-a
            else:
                ns.append(p); ds.append(b-a)
            cursor=b
        tokens.append(char); pitches.append(' '.join(ns)); lengths.append(' '.join(f'{v:.6f}' for v in ds))
        if end > cursor+1e-6:
            tokens.append('SP'); pitches.append('rest'); lengths.append(f'{end-cursor:.6f}')
        mapping.append({'character':char,'alignment':mapped[len(mapping)],'events':hits})
    result = {'text':''.join(tokens),'notes':' | '.join(pitches),'notes_duration':' | '.join(lengths)}
    result['validation'] = validate_score(result['text'],result['notes'],result['notes_duration'],duration)
    result['mapping'] = mapping
    return result
