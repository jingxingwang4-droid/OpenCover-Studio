from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from opencover.audio.lyric_workflow import level_vocal_phrases, mix_lyric_intervals
from opencover.audio.processing import mix_tracks
from opencover.workers.diffsinger_legacy_runtime import smooth_voiced_f0


def wav(path, data, rate=8000):
    sf.write(path, data, rate, subtype='FLOAT')
    return path


def test_smoothing_keeps_rests_and_pitch_centres():
    f0 = np.array([[220.]*50 + [440.]*50 + [0.]*10 + [330.]*50])
    result = smooth_voiced_f0(f0, 24000, 128)
    assert np.array_equal(result[0, 100:110], np.zeros(10))
    assert result[0, 20] == pytest.approx(220, abs=.001)
    assert result[0, 80] == pytest.approx(440, abs=.001)
    assert 220 < result[0, 49] < result[0, 50] < 440
    assert np.array_equal(f0[0, :50], np.full(50, 220.))


def test_phrase_levelling_is_constant_gain_and_preserves_gaps(tmp_path):
    sr = 8000
    t = np.arange(sr)/sr
    first = .04*np.sin(2*np.pi*440*t)
    signal = np.concatenate([first, np.zeros(sr), first*2])
    target = tmp_path/'level.wav'
    report = level_vocal_phrases(wav(tmp_path/'voice.wav', signal), [(0,1),(2,3)], target)
    result, _ = sf.read(target)
    assert np.array_equal(result[sr:2*sr], signal[sr:2*sr])
    levels = report['phrases']
    assert abs(levels[0]['after_lufs']-levels[1]['after_lufs']) == pytest.approx(1.50515, abs=.01)
    assert np.max(np.abs(result[:sr]-first*10**(levels[0]['gain_db']/20))) < 1e-7


@pytest.mark.parametrize('offset,gap', [(1., .38), (2.71,.19), (.2,.06)])
def test_all_boundaries_match_music_and_unedited_audio_is_exact(tmp_path, offset, gap):
    sr=8000; t=np.arange(sr*7)/sr
    bed=.1*np.sin(2*np.pi*200*t)
    old_voice=.04*np.sin(2*np.pi*430*t)
    spans=[(offset,offset+1),(offset+1+gap,offset+2+gap)]
    changed=np.zeros(len(t),dtype=bool)
    for a,b in spans:changed[round(a*sr):round(b*sr)]=True
    original=bed*1.3+old_voice*changed
    new_voice=.03*np.sin(2*np.pi*620*t)*changed
    source=wav(tmp_path/'source.wav',original)
    acc=wav(tmp_path/'acc.wav',bed); vocal=wav(tmp_path/'vocal.wav',new_voice)
    output=tmp_path/'result.wav'
    report=mix_lyric_intervals(source,vocal,acc,spans,output)
    result,_=sf.read(output,dtype='float32');stored,_=sf.read(source,dtype='float32')
    assert np.array_equal(result[~changed],stored[~changed])
    assert len(report['boundaries'])==4 and not report['review_required']
    for boundary in report['boundaries']:
        assert boundary['target_gain']==pytest.approx(1.3,rel=1e-5)
        k=round(boundary['time']*sr)
        sample=k if boundary['side']=='start' else k-1
        assert result[sample]==pytest.approx(bed[sample]*1.3,abs=2e-6)
    # In the middle of an edit, only the new voice and bed can be present.
    a=round((offset+.49)*sr);b=round((offset+.51)*sr)
    expected=bed[a:b]*report['mix_gains']['accompaniment_gain']+new_voice[a:b]*report['mix_gains']['vocal_gain']
    assert np.max(np.abs(result[a:b]-expected))<.003


def test_touching_edits_do_not_fade_the_middle_of_a_continuous_phrase(tmp_path):
    sr=8000;t=np.arange(sr*4)/sr
    bed=.08*np.cos(2*np.pi*211*t);v=.02*np.cos(2*np.pi*431*t)
    source=wav(tmp_path/'original.wav',bed)
    acc=wav(tmp_path/'acc.wav',bed);voice=wav(tmp_path/'v.wav',v)
    one=tmp_path/'one.wav';two=tmp_path/'two.wav'
    mix_lyric_intervals(source,voice,acc,[(1,3)],one)
    report=mix_lyric_intervals(source,voice,acc,[(1,2),(2,3)],two)
    assert one.read_bytes()==two.read_bytes()
    assert len(report['boundaries'])==2


def test_missing_music_reference_is_reported_without_copying_old_words(tmp_path):
    sr=8000;t=np.arange(sr*4)/sr
    source=wav(tmp_path/'source.wav',.1*np.sin(2*np.pi*333*t))
    acc=wav(tmp_path/'acc.wav',np.zeros_like(t))
    voice=wav(tmp_path/'voice.wav',.03*np.sin(2*np.pi*500*t))
    output=tmp_path/'out.wav'
    report=mix_lyric_intervals(source,voice,acc,[(1,3)],output)
    assert report['review_required']
    assert all(not edge['matched'] for edge in report['boundaries'])
    assert not report['old_vocals_reintroduced']


def test_gain_reporting_does_not_change_existing_original_cover_mixer(tmp_path):
    t=np.arange(24000)/8000
    voice=wav(tmp_path/'v.wav',np.sin(t*1500)*.1)
    acc=wav(tmp_path/'a.wav',np.sin(t*650)*.08)
    a=tmp_path/'a_mix.wav';b=tmp_path/'b_mix.wav';gains={}
    mix_tracks(voice,acc,a)
    mix_tracks(voice,acc,b,gain_report=gains)
    assert a.read_bytes()==b.read_bytes()
    assert gains['vocal_gain']>0 and gains['accompaniment_gain']>0


def test_short_silent_phrase_and_invalid_intervals(tmp_path):
    p=wav(tmp_path/'silence.wav',np.zeros(8000))
    result=level_vocal_phrases(p,[(.1,.2)],tmp_path/'out.wav')
    assert result['phrases'][0]['gain_db']==0
    with pytest.raises(ValueError,match='重叠'):
        level_vocal_phrases(p,[(.1,.4),(.3,.5)],tmp_path/'bad.wav')
