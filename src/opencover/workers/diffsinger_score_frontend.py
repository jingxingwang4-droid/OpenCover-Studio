"""Explicit phonemes and cumulative frame timing for the installed OpenCpop model."""
from __future__ import annotations
import math
import re


def prepare_score(segment, pinyin_to_phonemes, pinyin_function, sample_rate, hop_size, *, legato=False):
    text = str(segment['text'])
    tokens = re.findall(r'AP|SP|[\u4e00-\u9fff]', text)
    if ''.join(tokens) != text:
        raise ValueError('内部词谱含不支持的字符')
    lyric = ''.join(t for t in tokens if t not in {'AP','SP'})
    # Resolve polyphones in sentence context, before inserting score rests.
    pinyins = list(pinyin_function(lyric, strict=False))
    if len(pinyins) != len(lyric):
        raise ValueError('拼音数量与歌词不一致，不能丢字生成')
    pitches = segment['notes'].split('|')
    durations = segment['notes_duration'].split('|')
    if not len(tokens) == len(pitches) == len(durations):
        raise ValueError('词谱字段长度不一致')
    phones, notes, midi_durations, slurs, phone_lengths = [],[],[],[],[]
    cursor = 0
    groups = []
    score_pitches=[]; score_elapsed=0.0
    for token, ns, ds in zip(tokens,pitches,durations):
        ns, ds = ns.split(), [float(v) for v in ds.split()]
        if not ns or len(ns)!=len(ds) or any(not math.isfinite(v) or v<=0 for v in ds):
            raise ValueError('音符时值无效')
        for note,length in zip(ns,ds):
            score_elapsed+=length
            score_pitches.extend([note]*max(0,round(score_elapsed*sample_rate/hop_size)-len(score_pitches)))
        if legato and len(ns)>1 and 'rest' not in ns:
            # One continuous vowel across a melisma. Repeated nasal finals can
            # sound like extra syllables; the vocoder keeps the full note curve.
            ns=[ns[max(range(len(ds)),key=lambda i:ds[i])]]
            ds=[sum(ds)]
        if token in {'AP','SP'}:
            phs=[token]
        else:
            py=pinyins[cursor]; cursor+=1
            if py not in pinyin_to_phonemes:
                raise ValueError(f'“{token}”的拼音 {py} 不在模型字典中')
            phs=pinyin_to_phonemes[py].split()
        for index,(note,duration) in enumerate(zip(ns,ds)):
            if note=='rest':
                current=[token if token in {'AP','SP'} else 'SP']
                actual=[duration]
            elif index==0:
                current=phs
                if len(phs)==1:
                    actual=[duration]
                else:
                    consonant=min(.075,max(.025,duration*.20),duration*.40)
                    actual=[consonant/(len(phs)-1)]*(len(phs)-1)+[duration-consonant]
            else:
                current=[phs[-1]]; actual=[duration]
            groups.append({'phones':list(range(len(phones)+1,len(phones)+len(current)+1)), 'duration':duration})
            phones.extend(current)
            notes.extend([note]*len(current))
            midi_durations.extend([duration]*len(current))
            slurs.extend([int(index>0 and note!='rest')]*len(current))
            phone_lengths.extend(actual)
    # Round cumulative boundaries, never each note independently: no drift.
    frames=[]; elapsed=0.0
    total_frames=round(sum(phone_lengths)*sample_rate/hop_size)
    if total_frames < len(phones):
        raise ValueError('音素时间不足一个声学帧，请减少该句字数')
    for index,length in enumerate(phone_lengths):
        elapsed+=length
        end=min(total_frames-(len(phones)-index-1), max(len(frames)+1,round(elapsed*sample_rate/hop_size)))
        frames.extend([index+1]*(end-len(frames)))
    if not frames or set(frames)!=set(range(1,len(phones)+1)):
        raise ValueError('音素时间不足一个声学帧，请减少该句字数')
    payload={'text':text,'ph_seq':' '.join(phones),'note_seq':' '.join(notes),
        'note_dur_seq':' '.join(str(v) for v in midi_durations),'is_slur_seq':' '.join(str(v) for v in slurs),'input_type':'phoneme'}
    return payload,frames,{'pinyin':pinyins,'phones':phones,'phone_seconds':phone_lengths,'duration':elapsed,'frame_count':len(frames),'note_groups':groups,'score_frame_pitches':score_pitches,'legato':legato}


def learned_timing(predicted_frames, groups, sample_rate, hop_size):
    """Use learned consonant/vowel proportions inside exact score-note boundaries."""
    counts = {phone:predicted_frames.count(phone) for group in groups for phone in group['phones']}
    frames=[]; elapsed=0.0
    for group in groups:
        elapsed+=group['duration']
        end=round(elapsed*sample_rate/hop_size)
        phones=group['phones']
        room=end-len(frames)
        if room < len(phones):
            # Sub-frame ornament: borrow a frame from the next note, retaining
            # at least one frame for every phoneme; cumulative rounding recovers.
            room=len(phones)
        weights=[max(1,counts[phone]) for phone in phones]
        allocated=0
        for i,phone in enumerate(phones):
            boundary=round(room*sum(weights[:i+1])/sum(weights))
            boundary=min(room-(len(phones)-i-1),max(allocated+1,boundary))
            frames.extend([phone]*(boundary-allocated))
            allocated=boundary
    return frames
