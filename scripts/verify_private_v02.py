"""Audit and exercise a finished package using its bundled executables."""
from pathlib import Path
import argparse, json, os, re, subprocess, sys, time

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'workspace/package_v02'
def run(command,cwd,env,log):
    with log.open('w',encoding='utf-8') as f:
        p=subprocess.run([str(x) for x in command],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=1800)
    if p.returncode:raise RuntimeError(f'Exit {p.returncode}: {log}')
    return log.read_text(encoding='utf-8',errors='replace')

def clean_env(root):
    env={k:v for k,v in os.environ.items() if k.upper() in
         {'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','SYSTEMDRIVE','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMDATA','PROGRAMFILES','PROGRAMFILES(X86)','PROGRAMW6432','COMPUTERNAME','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE'}}
    env.update(PATH=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot'],
               PYTHONUTF8='1',PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',
               HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OPENCOVER_ROOT=str(root))
    for key,leaf in [('TEMP','temp'),('TMP','temp'),('NUMBA_CACHE_DIR','cache/numba'),('HF_HOME','cache/huggingface'),('TORCH_HOME','cache/torch')]:
        p=root/'workspace'/leaf;p.mkdir(parents=True,exist_ok=True);env[key]=str(p)
    return env

def audit(root):
    findings=[];runtimes=[]
    pattern=re.compile(r'(?i)(?:[C-Z]:[\\/]+(?:Users[\\/]|project[\\/]|AI[\\/]))')
    for p in root.rglob('*'):
        if not p.is_file():continue
        if p.suffix.lower() not in ('.py','.pth','.cfg','.ini','.json','.yaml','.yml','.toml','.cmd','.bat','.ps1','.txt','.md',''):continue
        if 'workspace' in p.relative_to(root).parts or p.stat().st_size>12*1024*1024:continue
        try:text=p.read_text(encoding='utf-8-sig')
        except (UnicodeError,OSError):continue
        hits=[(n,line[:240]) for n,line in enumerate(text.splitlines(),1) if pattern.search(line)]
        if hits:findings.append({'file':p.relative_to(root).as_posix(),'hits':hits[:8]})
    out=WORK/(root.name+'_audit.json');out.write_text(json.dumps(findings,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PATH_FINDINGS',len(findings),out,flush=True)
    for p in root.glob('external_backends/*/runtime/python.exe'):
        command=[p,'-I','-B','-c',"import sys,json,torch; x=torch.ones(4,device='cuda'); print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,base_prefix=sys.base_prefix,path=sys.path,torch=torch.__version__,cuda=torch.cuda.is_available(),gpu=torch.cuda.get_device_name(),result=float(x.sum()))))"]
        log=WORK/(root.name+'_'+p.parents[1].name+'_probe.log')
        result=run(command,root,clean_env(root),log)
        data=json.loads(result.strip().splitlines()[-1]);runtimes.append(data)
        if not data['prefix'].lower().startswith(str(root).lower()):raise RuntimeError('External Python prefix')
        print('GPU_RUNTIME_OK',p.parents[1].name,flush=True)
    (WORK/(root.name+'_runtimes.json')).write_text(json.dumps(runtimes,ensure_ascii=False,indent=2),encoding='utf-8')

def worker(root,kind,engine):
    env=clean_env(root)
    folder=root/'workspace/jobs'/('portable_'+kind+'_'+engine+'_'+time.strftime('%H%M%S'))
    if folder.exists():raise RuntimeError('New job directory required')
    folder.mkdir(parents=True)
    if kind=='lyric':
        data=json.loads((ROOT/'workspace/refactor_20260907/e2e_short/request.json').read_text(encoding='utf-8'))
        data['options']['original_lyrics']='我多想再见你\n哪怕匆匆一眼就别离'
        data['options']['new_lyrics']='我多想奔向你\n哪怕匆匆一眼就别离'
    else:
        data={'engine':engine,'model_id':'voice_5a170464' if engine=='rvc' else 'toyokawa_sakiko_ddsp_local_v1',
              'options':{'pitch':0,'pitch_mode':'manual','output_format':'wav','memory_profile':'低'}}
    source=folder/'输入示例.wav'
    import shutil
    shutil.copy2(ROOT/'workspace/refactor_20260907/short_source.wav',source)
    data.update(root=str(root),input_path=str(source),kind=kind)
    request=folder/'request.json';request.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    start=time.monotonic();log=folder/'worker.log'
    output=run([root/'OpenCoverStudioWorker.exe',request],root,env,log)
    events=[]
    for line in output.splitlines():
        try:events.append(json.loads(line))
        except ValueError:pass
    results=[e for e in events if e.get('type')=='result']
    if not results:raise RuntimeError('No worker result: '+str(log))
    import numpy as np,soundfile as sf
    audio,sr=sf.read(results[-1]['path'],always_2d=True,dtype='float32')
    if not np.isfinite(audio).all() or float(np.sqrt(np.mean(audio**2)))<1e-5:raise RuntimeError('Silent/invalid result')
    if abs(len(audio)/sr-12)>0.1:raise RuntimeError('Unexpected output length')
    if 'could not open' in output and 'index' in output:raise RuntimeError('FAISS index failed')
    result={'success':True,'kind':kind,'engine':engine,'elapsed_seconds':time.monotonic()-start,
            'duration':len(audio)/sr,'rms':float(np.sqrt(np.mean(audio**2))),'output':results[-1]['path']}
    (folder/'job.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (WORK/(root.name+'_'+kind+'_'+engine+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('action',choices=['audit','lyric','original']);p.add_argument('--engine',default='rvc');a=p.parse_args()
    if a.action=='audit':audit(a.root.resolve())
    else:worker(a.root.resolve(),a.action,a.engine)
