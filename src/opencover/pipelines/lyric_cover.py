from __future__ import annotations
import hashlib
import json
import shutil
import importlib.util
import marshal
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import soundfile as sf
from opencover.adapters.backends import AlignmentAdapter, DDSPAdapter, DiffSingerLegacyAdapter, GameAdapter, RVCAdapter, UVR5Adapter
from opencover.audio.processing import export_audio, ffmpeg_path, guard_lyric_accompaniment, mix_tracks, normalize_input, restore_vocal_detail, validate_audio
from opencover.core.retry_policy import chunk_sizes_for_profile, convert_with_oom_retry
from opencover.audio.lyric_workflow import WORKFLOW_ID, level_vocal_phrases, mix_lyric_intervals
from opencover.lyrics.processing import build_lyric_segments, parse_lyrics
from opencover.lyrics.edit_plan import changed_phrases
from opencover.lyrics.score import character_timings_from_alignment, game_melody_for_text, midi_melody_for_text, read_game_events, lyric_text_identity, trim_segments_to_vocal_activity, transpose_note_windows, diffsinger_octave_adaptation
from opencover.lyrics.score_contract import aligned_score, characters
from opencover.models.schema import VoiceModel
from opencover.pipelines.lyric_support import LyricSupport

@dataclass(frozen=True)
class LyricCoverRequest:
    input_path: Path
    engine: str
    voice: VoiceModel | None
    original_lyrics: str
    new_lyrics: str
    strategy: str = '均衡'
    pitch: int = 0
    balance: str = '均衡'
    output_format: str = 'wav'
    generator: str = 'diffsinger'
    memory_profile: str = '标准'
    auto_recognize_lyrics: bool = False

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + '.part')
    partial.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    partial.replace(path)

def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def module_hash(name):
    """Works with source checkouts and PyInstaller's embedded Python modules."""
    spec=importlib.util.find_spec(name)
    code=spec.loader.get_code(name)
    return hashlib.sha256(marshal.dumps(code)).hexdigest()

def backend_markers(root, generator='diffsinger'):
    if generator != 'diffsinger':
        raise ValueError('当前改词翻唱只支持 GAME + DiffSinger')
    parts=[]
    for name in ('game','diffsinger','alignment','uvr5'):
        path=root/'external_backends'/name/'backend.json'
        parts.append(path.read_text(encoding='utf-8') if path.is_file() else name+':missing')
    return '\n'.join(parts)

class LyricCoverPipeline(LyricSupport):
    """UVR5 → aligned GAME score → DiffSinger → voice conversion → local edits."""
    def __init__(self, root):
        self.root=root.resolve()
        base=self.root/'external_backends'
        self.uvr5=UVR5Adapter(base/'uvr5',(ffmpeg_path(self.root) or self.root/'ffmpeg/ffmpeg.exe').parent)
        self.game=GameAdapter(base/'game')
        self.diffsinger=DiffSingerLegacyAdapter(base/'diffsinger')
        self.alignment=AlignmentAdapter(base/'alignment')
        self.rvc=RVCAdapter(base/'rvc')
        self.ddsp=DDSPAdapter(base/'ddsp')

    def preflight(self, request):
        issues=[]
        if request.generator != 'diffsinger':
            issues.append('当前改词翻唱只支持 GAME + DiffSinger；请重新创建历史任务')
        if not request.input_path.is_file():
            issues.append('输入音频不存在')
        if request.engine not in {'native','rvc','ddsp'} or (request.engine != 'native' and (request.voice is None or request.voice.engine != request.engine)):
            issues.append('音色引擎与任务引擎不匹配')
        if request.voice is not None and (not request.voice.selectable or request.voice.quality_status == 'rejected'):
            issues.append('所选音色已停用')
        if request.output_format.lower() not in {'wav','flac','mp3'}:
            issues.append('输出格式必须是 WAV、FLAC 或 MP3')
        if not -12 <= request.pitch <= 12:
            issues.append('升降调必须在 -12 到 12 半音之间')
        if not ffmpeg_path(self.root):
            issues.append('FFmpeg 未安装')
        adapters=[self.uvr5,self.game,self.diffsinger,self.alignment]
        if request.engine in {'rvc','ddsp'}:
            adapters.append(self.rvc if request.engine=='rvc' else self.ddsp)
        for adapter in adapters:
            status=adapter.status()
            if not status.runnable:
                issues.append(status.name+'：'+status.detail)
        for runner in (self._diffsinger_runner(),self._alignment_runner(),self._score_refiner_runner()):
            if not runner.is_file():
                issues.append('运行脚本缺失：'+runner.name)
        if request.voice is not None:
            directory=request.voice.directory(self.root/'weights')
            for name in request.voice.model_files+request.voice.index_files+request.voice.config_files:
                if not (directory/name).is_file():
                    issues.append('音色文件缺失：'+name)
        if request.auto_recognize_lyrics:
            issues.append('请先使用 VocalParse 校对歌词，不能在生成阶段自动识别')
        for label,lyrics in (('原歌词',request.original_lyrics),('新歌词',request.new_lyrics)):
            cues=parse_lyrics(lyrics)
            if not cues:
                issues.append(label+'不能为空')
            try:
                for cue in cues:
                    characters(cue.text)
            except ValueError as exc:
                issues.append(label+'：'+str(exc))
        if len(parse_lyrics(request.original_lyrics)) != len(parse_lyrics(request.new_lyrics)):
            issues.append('新旧歌词行数必须一致；请在对应原句中增减字词')
        return issues

    def _separate(self, request, job_dir, report):
        if not self.uvr5.status().runnable:
            raise RuntimeError('UVR5 不可用：'+self.uvr5.status().detail)
        models=''.join(f'{p.name}:{p.stat().st_size}:{p.stat().st_mtime_ns}' for p in self.uvr5.model_paths)
        key=hashlib.sha256((file_hash(request.input_path)+self.uvr5.pipeline_id+models+'lyric-total-v2').encode()).hexdigest()
        cache=self.root/'workspace/cache/separation'/key
        normalized,vocals,other,total=[cache/name for name in ('input.wav','vocals.wav','other.wav','total_vocals.wav')]
        if not all(p.is_file() for p in (normalized,vocals,other,total)):
            report('normalize',8,'正在标准化输入音频')
            normalize_input(request.input_path,normalized,ffmpeg_path(self.root))
            report('separate',18,'正在使用 UVR5 分离主唱、和声与伴奏')
            separated=job_dir/'separation'
            self.uvr5.separate(normalized,separated)
            for source,target in ((separated/'vocals.wav',vocals),(separated/'total_vocals.wav',total)):
                if not source.is_file():
                    raise RuntimeError('UVR5 缺少必要分轨：'+source.name)
                shutil.copy2(source,target)
            guard=guard_lyric_accompaniment(normalized,vocals,separated/'other.wav',other)
            write_json(cache/'guard.json',guard.__dict__)
        for path in (normalized,vocals,other,total):
            validate_audio(path)
        report('separate',20,'UVR5 分轨就绪；改词区间旧和声将移除')
        return vocals,other

    def _generate_diffsinger(self, manifest, segments, directory, report):
        alignment_request=directory/'score_alignment_request.json'
        alignment_output=directory/'score_alignment.json'
        write_json(alignment_request,{'root':str(self.root),'output_path':str(alignment_output),'items':[
            {'audio_path':i['input'],'text':s.original_text,'language':'zh'} for i,s in zip(manifest,segments)]})
        report('align_lyrics',32,'正在批量对齐原唱每个字的时间')
        self.alignment.align(alignment_request,self._alignment_runner())
        aligned=json.loads(alignment_output.read_text(encoding='utf-8')).get('items',[])
        if len(aligned)!=len(segments):
            raise RuntimeError('逐句对齐数量不一致')
        source_dir=directory/'game_sources'
        source_dir.mkdir(parents=True,exist_ok=True)
        for item in manifest:
            source=Path(item['input'])
            shutil.copy2(source,source_dir/source.name)
        report('score',40,'GAME 正在提取原唱旋律')
        notes_dir=directory/'game_notes'
        self.game.extract_notes(source_dir,notes_dir)
        refined=directory/'game_notes_refined'
        report('score',44,'正在用连续音高复核旋律并分配新歌词')
        self.game.refine_notes(source_dir,notes_dir,refined,self._score_refiner_runner())
        scores=[]
        for item,segment,alignment in zip(manifest,segments,aligned):
            timings=character_timings_from_alignment(segment.original_text,alignment)
            if timings is None:
                raise RuntimeError('无法取得可靠逐字对齐：'+segment.original_text)
            notes=read_game_events(refined/(Path(item['input']).stem+'.txt'))
            score=aligned_score(segment.original_text,segment.new_text,segment.duration,notes,timings)
            scores.append({**score,'source_character_timings':timings,'output':item['output']})
        write_json(directory/'mapped_score.json',scores)
        request_file=directory/'diffsinger_request.json'
        write_json(request_file,{'root':str(self.root),'experiment':'0831_opencpop_ds1000','pitch_control':'score','strict_timing':True,'workflow':WORKFLOW_ID,'segments':scores})
        report('generate',48,f'DiffSinger 正在一次加载模型生成 {len(scores)} 个改词短句')
        self.diffsinger.generate_batch(request_file,self._diffsinger_runner(),lambda done,total:report('generate',48+round(17*done/total),f'已生成 {done}/{total} 句'))
        self._validate_score_generated_segments(manifest,segments,'DiffSinger')

    @staticmethod
    def _validate_score_generated_segments(manifest,segments,generator):
        if len(manifest)!=len(segments):
            raise RuntimeError('生成结果数量不匹配')
        for item,segment in zip(manifest,segments):
            audio,rate=sf.read(item['output'],always_2d=True,dtype='float32')
            if audio.size==0 or not np.isfinite(audio).all() or float(np.sqrt(np.mean(audio*audio)))<1e-5:
                raise RuntimeError(generator+' 输出静音或无效音频')
            if abs(len(audio)/rate-segment.duration)>.08:
                raise RuntimeError(generator+' 输出时长与词谱相差超过 80ms，拒绝整体拉伸')

    def _convert(self,request,manifest,segments,duration,job_dir,report):
        if request.engine=='native':
            source=job_dir/'audition/01_generated_lead.wav'
            destination=job_dir/'audition/02_converted_lead.wav'
            if request.pitch:
                from opencover.adapters.base import run_checked
                factor=2.0**(request.pitch/12.0)
                frames=sf.info(source).frames
                run_checked([str(ffmpeg_path(self.root)),'-hide_banner','-loglevel','error','-y','-i',str(source),
                    '-af',f'asetrate={44100*factor:.8f},aresample=44100,atempo={1/factor:.8f},apad=whole_len={frames},atrim=end_sample={frames}',
                    '-ac','2','-c:a','pcm_s24le',str(destination)],self.root)
            else:
                shutil.copy2(source,destination)
            report('convert',80,'使用原生中文歌声，保留生成阶段的吐字')
            return destination
        directory=request.voice.directory(self.root/'weights')
        model=directory/request.voice.model_files[0]
        signature = request.engine + str(request.pitch) + request.memory_profile + request.voice.inference_signature()
        signature += ''.join(file_hash(Path(i['output'])) for i in manifest)
        signature += ''.join(file_hash(directory/name) for name in request.voice.model_files+request.voice.index_files+request.voice.config_files)
        signature += module_hash(__name__) + file_hash(self._rvc_batch_runner())
        cache = self.root/'workspace/cache/voice_conversion'/('lyric_'+hashlib.sha256(signature.encode()).hexdigest())
        cached = cache/'converted.wav'
        completed = cache/'complete.json'
        destination = job_dir/'audition/02_converted_lead.wav'
        if cached.is_file() and completed.is_file():
            try:
                if json.loads(completed.read_text(encoding='utf-8'))['sha256'] == file_hash(cached):
                    validate_audio(cached)
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(cached,destination)
                    report('convert',80,'已校验并复用改词音色转换缓存')
                    return destination
            except (OSError,ValueError,KeyError,RuntimeError):
                pass
        converted=[{'input':i['output'],'output':str(job_dir/'conversion'/f'phrase_{n:03d}.wav')} for n,i in enumerate(manifest)]
        report('convert',72,'正在转换改词短句音色')
        if request.engine=='rvc':
            batch=job_dir/'conversion/request.json'
            write_json(batch,{'model':str(model),'index':str(directory/request.voice.index_files[0]) if request.voice.index_files else '',
                'pitch':request.pitch,'f0_method':request.voice.f0_method or 'rmvpe',
                'index_rate':request.voice.index_rate if request.voice.index_rate is not None else .75,
                'protect':request.voice.protect if request.voice.protect is not None else .33,
                'rms_mix_rate':request.voice.rms_mix_rate if request.voice.rms_mix_rate is not None else .25,'items':converted})
            self.rvc.convert_batch(batch,self._rvc_batch_runner())
        else:
            # A single sparse vocal track loads DDSP only once per task.
            source=self._stitch(manifest,segments,duration,job_dir/'conversion/ddsp_source.wav')
            raw=job_dir/'conversion/ddsp_raw.wav'
            def convert(source,target):
                self.ddsp.convert(source,target,model,request.pitch,
                    directory/request.voice.config_files[0] if request.voice.config_files else None,
                    f0_method=request.voice.f0_method or 'rmvpe',f0_min=request.voice.f0_min or 50,f0_max=request.voice.f0_max or 1100,
                    threshold_db=request.voice.silence_threshold_db if request.voice.silence_threshold_db is not None else -60)
            convert_with_oom_retry(source,raw,convert,lambda text:report('convert',76,text),chunk_sizes_for_profile(request.memory_profile))
            normalize_input(raw,destination,ffmpeg_path(self.root))
        if request.engine=='rvc':
            self._validate_score_generated_segments(converted,segments,request.engine.upper())
            self._stitch(converted,segments,duration,destination)
        native=job_dir/'audition/01_generated_lead.wav'
        detailed=job_dir/'conversion/detailed.wav'
        restore_vocal_detail(destination,native,detailed,ffmpeg_path(self.root),
            detail_mix=request.voice.source_detail_mix or 0.0,detail_cutoff_hz=request.voice.source_detail_cutoff_hz or 4000,
            treble_db=request.voice.converted_treble_db or 0.0,
            converted_gain=request.voice.converted_gain if request.voice.converted_gain is not None else 1.0)
        shutil.copy2(detailed,destination)
        cache.mkdir(parents=True,exist_ok=True)
        shutil.copy2(destination,cached)
        write_json(completed,{'sha256':file_hash(cached)})
        return destination

    def run(self,request,job_dir,progress=None):
        issues=self.preflight(request)
        if issues:
            raise RuntimeError('；'.join(issues))
        job_dir.mkdir(parents=True,exist_ok=True)
        report=progress or (lambda *args:None)
        vocals,accompaniment=self._separate(request,job_dir,report)
        normalized=vocals.parent/'input.wav'
        _,_,duration=validate_audio(normalized)
        original=self._align_plain_lyrics(vocals,request.original_lyrics,duration,job_dir,report)
        planned=build_lyric_segments(original,request.new_lyrics,duration,request.strategy,split_phrases=False)
        if not all(cue.end is not None for cue in parse_lyrics(request.original_lyrics)):
            # Plain text and standard LRC do not establish exact phrase ends.
            # Exclude outer instrumental silence while retaining internal pauses.
            planned=trim_segments_to_vocal_activity(planned,vocals,outer_only=True)
        segments, edit_intervals=changed_phrases(planned)
        if any(s.start<prev.end for prev,s in zip(planned,planned[1:])):
            raise ValueError('歌词区间重叠，请检查时间戳')
        report('segment',28,f'{len(edit_intervals)} 句改词，按 {len(segments)} 个演唱短句生成')
        write_json(job_dir/'segments.json',[s.__dict__ for s in segments])
        write_json(job_dir/'edit_intervals.json',edit_intervals)
        voice_id=request.voice.id if request.voice else 'diffsinger_native'
        output=self.root/'workspace/outputs'/f'{request.input_path.stem}_改词_{voice_id}_{job_dir.name}.{request.output_format.lower()}'
        if not segments:
            return export_audio(normalized,output,ffmpeg_path(self.root))
        identity=file_hash(vocals)+json.dumps([s.__dict__ for s in segments],ensure_ascii=False)+backend_markers(self.root)
        identity+=''.join(file_hash(p) for p in (self._diffsinger_runner(),self._diffsinger_runner().with_name('diffsinger_score_frontend.py'),self._diffsinger_runner().with_name('game_runtime.py'),self._alignment_runner(),self._score_refiner_runner()))
        identity+=''.join(module_hash(name) for name in (__name__,'opencover.lyrics.edit_plan','opencover.lyrics.score_contract','opencover.lyrics.score','opencover.pipelines.lyric_support'))
        key=hashlib.sha256(identity.encode()).hexdigest()
        directory=self.root/'workspace/cache/lyric_generation'/key/'segments_work'
        manifest=self._extract_segments(vocals,segments,directory)
        marker=directory/'complete.json'
        valid=False
        if marker.is_file():
            try:
                hashes=json.loads(marker.read_text(encoding='utf-8'))
                valid=all(file_hash(Path(i['output']))==hashes[i['output']] for i in manifest)
                if valid:
                    self._validate_score_generated_segments(manifest,segments,'DiffSinger')
            except (OSError,ValueError,KeyError,RuntimeError):
                valid=False
        if not valid:
            self._generate_diffsinger(manifest,segments,directory,report)
            write_json(marker,{i['output']:file_hash(Path(i['output'])) for i in manifest})
        else:
            report('generate',65,'已校验并复用改词短句缓存')
        native=self._stitch(manifest,segments,duration,job_dir/'audition/01_generated_lead.wav')
        converted=self._convert(request,manifest,segments,duration,job_dir,report)
        report('level',85,'正在按演唱短句自动均衡人声音量')
        levelled=job_dir/'audition/05_levelled_lead.wav'
        levels=level_vocal_phrases(converted,[(s.start,s.end) for s in segments],levelled)
        report('mix',90,'正在自动匹配全部改词边界的伴奏电平，保留未改词部分')
        mixed=job_dir/'audition/04_final_mix.wav'
        mixing=mix_lyric_intervals(normalized,levelled,accompaniment,edit_intervals,mixed,request.balance)
        lead,rate=sf.read(converted,always_2d=True,dtype='float32')
        sf.write(job_dir/'audition/03_removed_old_harmony.wav',np.zeros_like(lead),rate,subtype='PCM_16')
        export_audio(mixed,output,ffmpeg_path(self.root))
        write_json(job_dir/'validation.json',{'generator':'GAME + DiffSinger','workflow':WORKFLOW_ID,'output':str(output),'score':str(directory/'mapped_score.json'),
            'changed_segments':len(edit_intervals),'synthesis_phrases':len(segments),'unchanged_segments':len(planned)-len(edit_intervals),'native':str(native),
            'old_harmony':'removed inside edit intervals','outside_edits':'original normalized audio samples',
            'levelled_lead':str(levelled),'loudness':levels,'mixing':mixing,
            'technical_validation_passed':True,'pronunciation_listening_accepted':False,'melody_listening_accepted':False})
        message='已导出改词翻唱；句间响度与伴奏衔接已自动处理，请试听确认'
        if mixing['review_required']:
            message='已导出改词翻唱；部分边界缺少可靠伴奏参考或余量，请重点试听衔接'
        report('export',100,message)
        return output
