from pathlib import Path
import pytest
from opencover.core.job_manager import JobManager
from opencover.storage.database import Database
from opencover.pipelines.lyric_cover import LyricCoverPipeline, LyricCoverRequest
from opencover.models.schema import VoiceModel
from opencover.lyrics.edit_plan import changed_phrases
from opencover.lyrics.processing import LyricSegment
import numpy as np
import soundfile as sf


@pytest.mark.parametrize('generator',['soulx','acestep','vevo2','visinger2','auto'])
def test_job_submission_rejects_retired_generators_before_creating_a_job(tmp_path: Path,generator):
    manager=JobManager(Database(tmp_path/'test.sqlite'),tmp_path)
    with pytest.raises(ValueError,match='GAME'):
        manager.submit_lyric({'options':{'generator':generator}})
    assert not (tmp_path/'workspace/jobs').exists()


def test_job_input_contains_only_user_inputs(tmp_path: Path):
    manager=JobManager(Database(tmp_path/'test.sqlite'),tmp_path)
    with pytest.raises(ValueError,match='后台自动生成'):
        manager.submit_lyric({'options':{'midi_path':'user.mid'}})


def test_invalid_text_is_rejected_before_gpu_work(tmp_path: Path):
    voice=VoiceModel(id='test',display_name='Test',engine='rvc',model_files=['model.pth'])
    req=LyricCoverRequest(tmp_path/'song.wav','rvc',voice,'春天\n花开','hello')
    errors=LyricCoverPipeline(tmp_path).preflight(req)
    assert any('行数' in e for e in errors)
    assert any('不支持' in e for e in errors)


def test_phrase_grouping_preserves_gaps_and_never_absorbs_unchanged_lines():
    plan=[LyricSegment(0,3,'春天','晴天'),LyricSegment(3.2,6,'花开','花落'),
          LyricSegment(6,6.2,'来','来'),LyricSegment(6.2,9,'原词','新词')]
    groups,intervals=changed_phrases(plan)
    assert len(groups)==2
    assert groups[0].new_text=='晴天\n花落'
    assert groups[1].start==6.2
    assert intervals==[(0,3),(3.2,6),(6.2,9)]


def test_native_voice_requires_no_registered_model_or_conversion_backend(tmp_path: Path):
    request=LyricCoverRequest(tmp_path/'song.wav','native',None,'春天','晴天')
    pipeline=LyricCoverPipeline(tmp_path)
    issues=pipeline.preflight(request)
    assert not any('音色' in issue or 'RVC' in issue or 'DDSP' in issue for issue in issues)
    source=tmp_path/'audition/01_generated_lead.wav'
    source.parent.mkdir()
    sf.write(source,np.sin(np.arange(44100)*.1)*.1,44100)
    pipeline.rvc=None;pipeline.ddsp=None
    output=pipeline._convert(request,[],[],1,tmp_path,lambda *args:None)
    assert output.read_bytes()==source.read_bytes()
