"""Build self-contained 0.2 editions without using the local-install EXEs."""
from pathlib import Path
import argparse, ast, json, os, re, shutil, subprocess, sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'workspace/package_v02'
DEST = ROOT / 'release/_private'
RUNTIMES = ['diffsinger_legacy_runtime.py', 'diffsinger_score_frontend.py', 'game_runtime.py',
            'alignment_runtime.py', 'score_refinement_runtime.py', 'rvc_batch_runtime.py', 'vocalparse_runtime.py']
EXCLUDE = {'.git', '__pycache__', '.pytest_cache', '.cache', '.mypy_cache', '.ruff_cache',
           'tests', 'test', 'docs', '.github', 'node_modules'}

def setup():
    WORK.mkdir(parents=True, exist_ok=True)
    for key in ('TEMP','TMP','TMPDIR','NUMBA_CACHE_DIR','PYINSTALLER_CONFIG_DIR'):
        path = WORK / 'temp' / key
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    os.environ.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')
    sys.stdout.reconfigure(encoding='utf-8')
    os.chdir(ROOT)

def copytree(source, target):
    def ignore(path, names):
        excluded=EXCLUDE - {'tests','test','docs'} if 'site-packages' in Path(path).parts else EXCLUDE
        return [n for n in names if n in excluded or n.endswith(('.pyc','.pyo','.log','.egg-link'))
                or n == 'direct_url.json' or n.startswith('__editable__')]
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=ignore)

def build(edition):
    # Avoid collecting unrelated DLLs from host tools (e.g. Poppler's ICU).
    os.environ['PATH']=os.environ['SystemRoot']+'\\System32;'+os.environ['SystemRoot']
    folder = WORK / ('build_' + edition)
    folder.mkdir(parents=True, exist_ok=True)
    hook = WORK / 'portable_hook.py'
    hook.write_text('''import os, sys, pathlib
root = pathlib.Path(sys.executable).resolve().parent
os.environ['OPENCOVER_ROOT'] = str(root)
for key, leaf in [('TEMP','temp'),('TMP','temp'),('TMPDIR','temp'),('NUMBA_CACHE_DIR','cache/numba'),('HF_HOME','cache/huggingface'),('TORCH_HOME','cache/torch')]:
    p = root / 'workspace' / leaf
    p.mkdir(parents=True, exist_ok=True)
    os.environ[key] = str(p)
os.environ['PYTHONUTF8'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
os.environ['PYTHONNOUSERSITE'] = '1'
os.environ.pop('PYTHONPATH', None)
''', encoding='utf-8')
    common = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--paths', str(ROOT/'src'),
              '--specpath', str(folder/'spec'), '--distpath', str(folder/'dist'),
              '--runtime-hook', str(hook)]
    if edition == 'lite':
        for mod in ['opencover.lyrics','opencover.pipelines.lyric_cover','opencover.workers.lyric_cover_worker',
                    'opencover.pipelines.lyric_recognition','opencover.workers.lyric_recognition_worker']:
            common += ['--exclude-module',mod]
    else:
        for name in RUNTIMES:
            common += ['--add-data', str(ROOT/'src/opencover/workers'/name)+';workers']
    for name, entry, extra in [('OpenCoverStudio','app.py',['--windowed','--onedir']),
                                ('OpenCoverStudioWorker','worker_entry.py',['--console','--onefile'])]:
        command = common + ['--name',name,'--workpath',str(folder/name)] + extra
        if name == 'OpenCoverStudio':
            command += ['--icon',str(ROOT/'build/图标.ico')]
        with (folder/(name+'.log')).open('w',encoding='utf-8') as log:
            subprocess.run(command+[str(ROOT/entry)],stdout=log,stderr=subprocess.STDOUT,check=True)
        print('BUILT',edition,name,flush=True)

def portable_runtime(source, target):
    cfg = source/'pyvenv.cfg'
    if cfg.exists():
        home = next(line.split('=',1)[1].strip() for line in cfg.read_text().splitlines() if line.startswith('home'))
        base = Path(home)
        # The standalone interpreter/stdlib comes first; environment packages win.
        for p in base.iterdir():
            if p.name in ('Lib','Scripts','__pycache__'): continue
            if p.is_dir(): copytree(p,target/p.name)
            elif p.suffix not in ('.pyc','.pyo'): shutil.copy2(p,target/p.name)
        if (base/'Lib').exists():
            for p in (base/'Lib').iterdir():
                if p.name in ('site-packages',*EXCLUDE): continue
                if p.is_dir(): copytree(p,target/'Lib'/p.name)
                else:
                    (target/'Lib').mkdir(parents=True,exist_ok=True)
                    shutil.copy2(p,target/'Lib'/p.name)
    # Scripts contain absolute shebangs/uv trampolines and are unnecessary:
    # all inference is launched with the standalone runtime/python.exe.
    scripts = target/'Scripts'
    if scripts.exists(): shutil.rmtree(scripts)
    if (target/'pyvenv.cfg').exists(): (target/'pyvenv.cfg').unlink()
    # Resolve editable installs into real in-package modules.
    for finder in (source/'Lib/site-packages').glob('__editable__*_finder.py'):
        tree = ast.parse(finder.read_text(encoding='utf-8'))
        for node in tree.body:
            if isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Name) and node.target.id=='MAPPING':
                for name, path in ast.literal_eval(node.value).items():
                    p=Path(path); dest=target/'Lib/site-packages'/name
                    if p.is_dir(): copytree(p,dest)
                    else: shutil.copy2(p,dest.with_suffix('.py'))

def scrub(target):
    count=0
    patterns = [(str(ROOT), '.'), (str(ROOT).replace('\\','\\\\'), '.'), (ROOT.as_posix(), '.')]
    for p in target.rglob('*'):
        if not p.is_file(): continue
        if p.name == 'pyvenv.cfg': p.unlink(); continue
        if p.name == 'DELVEWHEEL': p.unlink(); continue
        if p.suffix.lower() not in ('.json','.yaml','.yml','.ini','.cfg','.toml','.pth','.py','.txt','.md','.bat','.cmd','.ps1','.sh','.csv','.html','.xml',''):
            continue
        if p.stat().st_size>12*1024*1024: continue
        try: content=p.read_text(encoding='utf-8-sig')
        except (UnicodeError,OSError): continue
        changed=content
        for old,new in patterns: changed=changed.replace(old,new)
        # Drop user/CI-home examples and build provenance in dependency text.
        # Do not rewrite DLLs, checkpoints, or path-parsing algorithms.
        changed=re.sub(r'(?i)[A-Z]:[\\/]+Users[\\/]+[^\\/\s\"\'`]*', '.', changed)
        if p.name=='model.json':
            model=json.loads(changed)
            if re.match(r'^[A-Za-z]:[\\/]',str(model.get('source',''))):
                model['source']='Local user model'
            changed=json.dumps(model,ensure_ascii=False,indent=2)
        if p.name=='backend.json':
            data=json.loads(changed)
            for key in ('evidence','smoke_test','input','output','test_input','preview_source_audio'):
                data.pop(key,None)
            if data.get('backend')=='vocalparse':
                data['detail']='VocalParse GPU 识别；结果须人工校对'
                data['runtime']='runtime/python.exe'
            changed=json.dumps(data,ensure_ascii=False,indent=2)
        if changed!=content:
            p.write_text(changed,encoding='utf-8');count+=1
    print('SANITIZED',target.name,count,flush=True)

def fix_faiss(target):
    for rel in ['source/rvc/modules/vc/pipeline.py','runtime/Lib/site-packages/rvc/modules/vc/pipeline.py']:
        path=target/'external_backends/rvc'/rel
        content=path.read_text(encoding='utf-8')
        # Python opens Unicode paths; FAISS receives memory rather than a narrow
        # Windows filename. Preserve the original checkpoint and index bytes.
        content=content.replace('index = faiss.read_index(file_index)',
            'with open(file_index, "rb") as index_stream:\n                    index = faiss.deserialize_index(np.frombuffer(index_stream.read(), dtype=np.uint8))')
        path.write_text(content,encoding='utf-8')

def fix_qt(target):
    # Qt uses Windows' unsuffixed ICU API. Poppler's same-named DLL exports
    # suffixed ICU 78 symbols and must never shadow the Windows component.
    for name in ('icuuc.dll','icudt78.dll'):
        path=target/'_internal'/name
        if path.exists():path.unlink()

def repair_dependencies(target):
    # Some wheels import helper modules from their tests packages at runtime
    # (NumPy 2's public testing API is imported by SciPy). Keep wheel contents.
    for backend in (target/'external_backends').iterdir():
        for runtime in ('runtime','legacy_runtime'):
            source=ROOT/'external_backends'/backend.name/runtime/'Lib/site-packages'
            if not source.exists():continue
            for path in source.rglob('*'):
                if path.is_dir() and path.name in ('tests','test','docs'):
                    copytree(path,backend/runtime/'Lib/site-packages'/path.relative_to(source))
    scrub(target)

def assemble(edition):
    target=DEST/('测试版0.2_'+('轻量版' if edition=='lite' else '完整版'))
    if target.exists(): raise RuntimeError('Refusing to overwrite '+str(target))
    target.mkdir(parents=True)
    copytree(WORK/('build_'+edition)/'dist/OpenCoverStudio',target)
    shutil.copy2(WORK/('build_'+edition)/'dist/OpenCoverStudioWorker.exe',target/'OpenCoverStudioWorker.exe')
    for name in ('assets','config','ffmpeg','weights'):
        copytree(ROOT/name,target/name)
    for rel in ['assets/audio','assets/test_source','assets/preview_sources/jingque_first_line.wav',
                'weights/ddsp/bundled/toyokawa_sakiko_ddsp']:
        p=target/rel
        if p.is_dir():shutil.rmtree(p)
        elif p.exists():p.unlink()
    backends=['msst','uvr5','rvc','ddsp']
    if edition=='full':backends+=['alignment','game','diffsinger','vocalparse']
    for name in backends:
        source=ROOT/'external_backends'/name; dest=target/'external_backends'/name
        print('COPY',edition,name,flush=True)
        copytree(source,dest)
        runtime=source/'runtime'
        if runtime.exists():portable_runtime(runtime,dest/'runtime')
        if name=='diffsinger':
            # Legacy dependencies are an overlay consumed by the RVC interpreter.
            for rel in ['legacy_runtime/Scripts','DiffSinger']:
                p=dest/rel
                if p.exists():shutil.rmtree(p)
    (target/'external_backends/rvc/.env').write_text('weight_root=models\nweight_uvr5_root=\nindex_root=models\nrmvpe_root=models\nhubert_path=models/hubert_base.pt\nsave_uvr_path=../../workspace/outputs\nTEMP=../../workspace/temp/rvc\npretrained=\n',encoding='utf-8')
    (target/'PRIVATE_EDITION').write_text('测试版0.2',encoding='utf-8')
    if edition=='full':(target/'LYRIC_EDITION').write_text('GAME + DiffSinger',encoding='utf-8')
    for name in ('LICENSE','THIRD_PARTY_NOTICES.md','RESOURCE_SOURCES.md'):
        shutil.copy2(ROOT/name,target/name)
    for name in ['outputs','jobs','logs','cache','temp']:(target/'workspace'/name).mkdir(parents=True,exist_ok=True)
    (target/'启动.cmd').write_text('@echo off\r\ncd /d "%~dp0"\r\nset "TEMP=%~dp0workspace\\temp"\r\nset "TMP=%TEMP%"\r\nif not exist "%TEMP%" mkdir "%TEMP%"\r\nstart "" "%~dp0OpenCoverStudio.exe"\r\n',encoding='utf-8')
    scrub(target)
    fix_faiss(target)
    fix_qt(target)
    print('ASSEMBLED',target,flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['build','assemble','scrub','fix_faiss','fix_qt','repair_dependencies']);parser.add_argument('edition',choices=['lite','full'])
    a=parser.parse_args();setup()
    if a.action in ('scrub','fix_faiss','fix_qt','repair_dependencies'):globals()[a.action](DEST/('测试版0.2_'+('轻量版' if a.edition=='lite' else '完整版')))
    else:globals()[a.action](a.edition)
