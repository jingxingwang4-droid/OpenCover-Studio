"""The accepted C workflow, applied to arbitrary lyric phrase boundaries."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from .processing import mix_tracks

WORKFLOW_ID = 'clear_c_v1'


def _write_report(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


def _interval_frames(intervals, rate, length):
    result = []
    for start, end in sorted(intervals):
        if not np.isfinite([start, end]).all():
            raise ValueError('改词区间包含无效时间')
        a, b = round(start * rate), round(end * rate)
        if a < 0 or b <= a or b > length or (result and a < result[-1][1]):
            raise ValueError('改词区间无效或重叠')
        result.append((a, b))
    return result


def level_vocal_phrases(source: Path, intervals, output: Path) -> dict:
    """C's slow phrase gains; do not apply syllable-level automatic gain."""
    audio, rate = sf.read(source, always_2d=True, dtype='float32')
    if not audio.size or not np.isfinite(audio).all():
        raise ValueError('句间响度均衡收到无效人声')
    spans = _interval_frames(intervals, rate, len(audio))
    meter = pyln.Meter(rate)
    levels = []
    for a, b in spans:
        part = audio[a:b]
        # BS.1770 needs a 400 ms block. Padding is measurement-only.
        if len(part) < round(rate * .4):
            part = np.pad(part, ((0, round(rate * .4) - len(part)), (0, 0)))
        levels.append(float(meter.integrated_loudness(part)))
    valid = [v for v in levels if np.isfinite(v)]
    target = float(np.median(valid)) if valid else None
    gains = [float(np.clip(.75 * (target - v), -3, 3)) if target is not None and np.isfinite(v) else 0.0 for v in levels]
    for (a, b), gain in zip(spans, gains):
        audio[a:b] *= 10 ** (gain / 20)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Float preserves headroom; the final mixer reserves it before PCM export.
    sf.write(output, audio, rate, subtype='FLOAT')
    report = {'workflow': WORKFLOW_ID, 'target_lufs': target, 'gain_limit_db': 3,
              'correction_ratio': .75, 'phrases': [
                  {'start': a / rate, 'end': b / rate, 'before_lufs': v if np.isfinite(v) else None,
                   'gain_db': g, 'after_lufs': v + g if np.isfinite(v) else None}
                  for (a, b), v, g in zip(spans, levels, gains)]}
    _write_report(output.with_suffix('.levels.json'), report)
    return report


def _fit_bed(source, bed, rate, start, end):
    """Estimate a scalar from music-dominated windows, never copy old vocals."""
    block = max(1, round(.10 * rate))
    if end - start < round(.03 * rate):
        return None
    values, explained = [], []
    for a in range(start, end, block):
        b = min(a + block, end)
        if b - a < round(.03 * rate):
            continue
        x, y = bed[a:b].astype(np.float64), source[a:b].astype(np.float64)
        xx, yy = float(np.sum(x*x)), float(np.sum(y*y))
        if xx / x.size < 1e-8 or yy / y.size < 1e-8:
            continue
        gain = float(np.sum(x*y) / xx)
        fit = 1 - float(np.sum((y-gain*x)**2)) / yy
        if .125 <= gain <= 8 and fit > .995:
            values.append(gain)
            explained.append(fit)
    if not values:
        return None
    return {'gain': float(np.median(values)), 'explained_energy': float(np.median(explained)),
            'windows': len(values)}


def _channels(audio, count):
    if audio.shape[1] == count:
        return audio
    if audio.shape[1] == 1:
        return np.repeat(audio, count, axis=1)
    raise ValueError('改词混音声道数量不匹配')


def mix_lyric_intervals(source: Path, vocal: Path, accompaniment: Path, intervals,
                        output: Path, balance: str = '均衡') -> dict:
    """C1 boundary correction on every edit, with original gaps kept bit exact."""
    original, rate = sf.read(source, always_2d=True, dtype='float32')
    bed, bed_rate = sf.read(accompaniment, always_2d=True, dtype='float32')
    voice, voice_rate = sf.read(vocal, always_2d=True, dtype='float32')
    if not original.size or not np.isfinite(original).all() or not np.isfinite(bed).all() or not np.isfinite(voice).all():
        raise ValueError('改词混音含空音频或非有限值')
    if rate != bed_rate or rate != voice_rate or len(original) != len(bed) or len(original) != len(voice):
        raise ValueError('改词混音要求分轨具有相同采样率与时长')
    spans = _interval_frames(intervals, rate, len(original))
    merged = []
    for a, b in spans:
        if merged and merged[-1][1] == a:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    channels = original.shape[1]
    bed = _channels(bed, channels)
    output.parent.mkdir(parents=True, exist_ok=True)
    gains = {}
    candidate_path = output.with_name(output.stem + '_candidate.wav')
    mix_tracks(vocal, accompaniment, candidate_path, balance, gain_report=gains)
    candidate, _ = sf.read(candidate_path, always_2d=True, dtype='float32')
    candidate = _channels(candidate, channels)
    base_gain = gains['accompaniment_gain']
    # Collect reference windows only outside edited lyrics. A busy/fully vocal
    # boundary can reuse a reliable gain from another instrumental gap.
    gaps, cursor = [], 0
    for a, b in merged:
        if a > cursor:
            gaps.append((cursor, a))
        cursor = b
    if cursor < len(original):
        gaps.append((cursor, len(original)))
    fits = [fit for a, b in gaps if (fit := _fit_bed(original, bed, rate, a, b))]
    global_fit = None
    if fits:
        global_fit = {'gain': float(np.median([f['gain'] for f in fits])),
                      'explained_energy': float(np.median([f['explained_energy'] for f in fits])),
                      'windows': sum(f['windows'] for f in fits)}
    result, boundaries, headroom = original.copy(), [], []
    for index, (a, b) in enumerate(merged):
        count = b - a
        curve = np.full(count, base_gain, dtype=np.float64)
        ramp = min(round(.50 * rate), count // 2)
        left = merged[index-1][1] if index else 0
        right = merged[index+1][0] if index+1 < len(merged) else len(original)
        for side, k, c, d in [('start', a, max(left, a-round(.6*rate)), a),
                              ('end', b, b, min(right, b+round(.6*rate)))]:
            if k in (0, len(original)):
                continue
            fit = _fit_bed(original, bed, rate, c, d)
            origin = 'adjacent_gap'
            if fit is None:
                fit, origin = global_fit, 'other_music_gaps'
            target = fit['gain'] if fit else base_gain
            boundaries.append({'time': k/rate, 'side': side, 'reference': origin if fit else 'unverified',
                               'matched': fit is not None, 'base_gain': base_gain, 'target_gain': target,
                               'fit': fit, 'ramp_seconds': ramp/rate})
            if ramp:
                weight = .5 - .5*np.cos(np.linspace(0, np.pi, ramp))
                if side == 'start':
                    curve[:ramp] += (target-base_gain) * weight[::-1]
                else:
                    curve[-ramp:] += (target-base_gain) * weight
        music = bed[a:b].astype(np.float64) * curve[:, None]
        # Fade only the generated component, never the instrumental bed.
        generated = candidate[a:b].astype(np.float64) - bed[a:b].astype(np.float64)*base_gain
        fade = min(round(.005 * rate), count // 2)
        if fade:
            generated[:fade] *= np.linspace(0, 1, fade)[:, None]
            generated[-fade:] *= np.linspace(1, 0, fade)[:, None]
        music_peak = float(np.max(np.abs(music)))
        music_scale = min(1.0, .98/max(music_peak, 1e-12))
        music *= music_scale
        nonzero = np.abs(generated) > 1e-12
        limits = (.98-np.sign(generated[nonzero])*music[nonzero]) / np.abs(generated[nonzero])
        voice_scale = float(np.clip(np.min(limits), 0, 1)) if limits.size else 1.0
        result[a:b] = music + generated*voice_scale
        if music_scale < 1 or voice_scale < 1:
            headroom.append({'start': a/rate, 'end': b/rate, 'music_scale': music_scale, 'voice_scale': voice_scale})
    sf.write(output, result, rate, subtype='FLOAT')
    report = {'workflow': WORKFLOW_ID, 'intervals': [(a/rate, b/rate) for a, b in merged],
              'mix_gains': gains, 'boundaries': boundaries, 'headroom': headroom,
              'outside_edits': 'original samples', 'old_vocals_reintroduced': False,
              'review_required': any(not b['matched'] for b in boundaries) or any(h['music_scale'] < 1 for h in headroom)}
    _write_report(output.with_suffix('.mix.json'), report)
    return report
