from pathlib import Path
import numpy as np
import pytest
import soundfile as sf
from opencover.lyrics.score_contract import aligned_score, map_target_timings, validate_score
from opencover.audio.lyric_edit import replace_intervals
from opencover.workers.diffsinger_score_frontend import prepare_score
from opencover.workers.score_refinement_runtime import refine_events, mask_unreliable_f0
from opencover.lyrics.score import trim_segments_to_vocal_activity
from opencover.lyrics.processing import LyricSegment


def test_aligned_note_can_be_split_at_a_consonant_without_changing_pitch():
    score=aligned_score('春天','晴天',1.0,[(0,1,'C4')],[(0,.3),(.3,1)])
    assert score['notes']=='C4 | C4'
    assert score['notes_duration']=='0.300000 | 0.700000'


def test_internal_silence_never_compresses_the_following_notes():
    score=aligned_score('春','晴',1,[(0,.3,'C4'),(.5,1,'D4')],[(0,1)])
    assert score['notes']=='C4 rest D4'
    assert score['notes_duration']=='0.300000 0.200000 0.500000'
    assert score['validation']['duration']==1


def test_insertion_preserves_unchanged_syllable_anchors():
    timing=map_target_timings('我爱你','我很爱你',[(0,.6),(.6,1),(1,2)])
    assert timing==[(0,.3),(.3,.6),(.6,1),(1,2)]


@pytest.mark.parametrize('notes,durations',[('C4','nan'),('C4 D4','.1'),('C0','1'),('rest','1')])
def test_invalid_score_is_rejected_before_loading_models(notes,durations):
    with pytest.raises(ValueError):
        validate_score('春',notes,durations,1)


def test_frontend_keeps_context_and_exact_rest_frames():
    seen=[]
    def pinyin(text,**kwargs):
        seen.append(text)
        return ['chang','da']
    payload,frames,evidence=prepare_score({'text':'长SP大','notes':'C4 | rest | D4','notes_duration':'.4 | .1 | .5'},
        {'chang':'ch ang','da':'d a'},pinyin,1000,10)
    assert seen==['长大']
    assert payload['ph_seq']=='ch ang SP d a'
    assert len(frames)==100
    assert frames[40:50]==[3]*10
    assert sum(evidence['phone_seconds'])==pytest.approx(1)


def test_missing_pronunciation_cannot_silently_drop_a_character():
    with pytest.raises(ValueError,match='模型字典'):
        prepare_score({'text':'春','notes':'C4','notes_duration':'1'}, {}, lambda *a,**k:['chun'],1000,10)


def test_quiet_pickup_omitted_by_game_is_recovered_from_sustained_f0():
    times=np.arange(0,1,.01)
    f0=np.where(times<.3,220.0,440.0)
    events=refine_events([(.3,1,'A4')],times,f0)
    assert events[0][2]=='A3'
    assert events[0][0]==0
    assert .28<events[0][1]<=.3


def test_first_consonant_is_not_assigned_to_a_ten_millisecond_note_tail():
    score=aligned_score('春天','晴天',1,[(0,.31,'C4'),(.31,1,'D4')],[(0,.3),(.3,1)])
    assert score['notes']=='C4 | D4'


def test_unedited_audio_is_bit_exact_and_old_harmony_is_absent(tmp_path: Path):
    source=tmp_path/'source.wav'; generated=tmp_path/'new.wav'
    original=np.linspace(-.2,.2,3000,dtype=np.float32)
    sf.write(source,original,1000,subtype='FLOAT')
    sf.write(generated,np.zeros(3000,dtype=np.float32),1000,subtype='FLOAT')
    output=replace_intervals(source,generated,[(1,2)],tmp_path/'result.wav')
    result,_=sf.read(output,dtype='float32')
    assert np.array_equal(result[:1000],original[:1000])
    assert np.array_equal(result[2000:],original[2000:])
    assert not np.any(result[1000:2000])


def test_melisma_has_one_nasal_final_but_preserves_every_pitch_transition():
    payload,frames,evidence=prepare_score(
        {'text':'径','notes':'C4 D4 E4','notes_duration':'.3 .2 .5'},
        {'jing':'j ing'},lambda *a,**k:['jing'],1000,10,legato=True)
    assert payload['ph_seq']=='j ing'
    assert len(frames)==100
    assert evidence['score_frame_pitches']==['C4']*30+['D4']*20+['E4']*50


def test_stable_pitch_in_separator_noise_cannot_become_a_new_note():
    f0=np.array([1975.,220.,440.])
    masked=mask_unreliable_f0(f0,np.ones(3),np.array([.0001,.01,.1]))
    assert np.isnan(masked[0])
    assert np.array_equal(masked[1:],f0[1:])


def test_plain_lyric_boundary_preserves_intro_and_internal_instrumental_pause(tmp_path):
    rate=1000
    values=np.zeros(rate*8,dtype=np.float32)
    values[2000:3000]=.1;values[6000:7000]=.1
    path=tmp_path/'vocal.wav';sf.write(path,values,rate,subtype='FLOAT')
    segment=LyricSegment(0,8,'春天来了','晴天来了')
    actual=trim_segments_to_vocal_activity([segment],path,outer_only=True)[0]
    assert 1.8<actual.start<2
    assert 7<actual.end<7.2
