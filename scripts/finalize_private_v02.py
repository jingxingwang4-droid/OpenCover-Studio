"""Finalize an already validated private edition and verify its ZIP CRCs."""
from pathlib import Path
import argparse, hashlib, json, os, re, shutil, sys, time, zipfile
from build_private_v02 import ROOT, WORK, DEST, scrub
from create_private_zip import create_zip

def sha256(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()

def finalize(edition):
    name='测试版0.2_'+('轻量版' if edition=='lite' else '完整版')
    target=(DEST/name).resolve()
    if target.parent!=DEST.resolve() or not target.is_dir():raise RuntimeError('Unexpected package target')
    evidence=WORK/('evidence_'+edition+'_final')
    if evidence.exists():evidence=WORK/(evidence.name+'_'+time.strftime('%H%M%S'))
    if (target/'workspace').exists():shutil.move(str(target/'workspace'),str(evidence))
    for name in ('outputs','jobs','logs','cache','temp'):(target/'workspace'/name).mkdir(parents=True,exist_ok=True)
    scrub(target)
    for path in target.rglob('*.pyc'):
        if not path.resolve().is_relative_to(target):raise RuntimeError('Cache escaped package')
        path.unlink()
    for path in sorted(target.rglob('__pycache__'),key=lambda p:len(p.parts),reverse=True):
        if not path.resolve().is_relative_to(target):raise RuntimeError('Cache escaped package')
        if path.is_dir():shutil.rmtree(path)
    for path in target.rglob('*'):
        if path.is_symlink():raise RuntimeError('Package contains a symlink: '+str(path))
        if path.is_file() and (path.name=='pyvenv.cfg' or path.suffix in ('.pyc','.pyo')):
            raise RuntimeError('Package contains runtime residue: '+str(path))
    feature='不含改词翻唱、自动识词及其运行时。' if edition=='lite' else '包含 GAME + DiffSinger 改词翻唱，以及 VocalParse 自动识词。'
    notes=f'''OpenCover Studio 测试版 0.2
{'轻量版' if edition=='lite' else '完整版'}

使用方式
完整解压后运行“启动.cmd”或 OpenCoverStudio.exe。不要在压缩包内运行。
整个软件目录可以一起移动，不要单独移动 EXE 或模型目录。
音频、任务、缓存和输出保存在软件目录下的 workspace 中。
请放在有写入权限且磁盘空间充足的位置。

版本内容
两版都包含 UVR5、人声音色转换 RVC/DDSP、音色管理、混音与 WAV/FLAC/MP3 导出。
{feature}
完整版仅要求原曲、对应原歌词和新歌词，不要求 MIDI 或内部词谱文件。
自动识词结果需要人工校对。仅修改实际改词短句；未改词区间保留原曲。
改词短句移除原词和声，转音、句间音量与伴奏衔接自动处理。
改词仍为测试功能，导出后请检查歌词、旋律、和声和衔接；技术校验不代表听感验收。

运行环境
64 位 Windows 10/11，NVIDIA Modern 显卡及兼容包内 CUDA 13.0 运行时的驱动。
无需另外安装 Python、Conda 或 CUDA Toolkit。
当前实测 GPU：RTX 5070 Ti Laptop GPU；驱动：591.86。
旧显卡及不同电脑的硬件兼容性尚未逐台验收；本包不是 Legacy CUDA 11.8 版本。

本次验证
相关自动化测试 75 项通过；最终冻结 GUI 已检查。
RVC、DDSP 已在成品环境完成约 12 秒真实 GPU 转换和最终混音导出。
完整版已完成纯文本歌词到 GAME + DiffSinger 改词混音的真实 GPU 任务。
迁移验证使用同一台电脑的另一目录和盘符映射，不等同于另一台实体电脑测试。
PACKAGE_SHA256.txt 列出包内文件校验值；压缩包旁另有整个 ZIP 的 SHA-256。
此包不携带开发机环境、历史任务、测试歌曲、访问凭据或演示视频。

私人使用
含用户私人音色资源，仅作私人迁移使用。不要将此包或其中的模型上传到公开仓库。
源码与第三方许可说明见 LICENSE、THIRD_PARTY_NOTICES.md、RESOURCE_SOURCES.md。
'''
    (target/'请先阅读.txt').write_text(notes,encoding='utf-8')
    info={'version':'0.2测试版','edition':edition,'lyric_cover':edition=='full','build_date':'2026-09-09',
          'runtime_profile':'NVIDIA Modern / CUDA 13.0','source_version':'0.2测试版',
          'other_physical_computers_verified':False,'listening_acceptance':'pending user review'}
    (target/'PACKAGE_INFO.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),encoding='utf-8')
    # Scan user/development roots in every shipped text file, including metadata.
    bad=[];pattern=re.compile(r'(?i)(?:[C-Z]:[\\/]+(?:Users[\\/]|project[\\/]|AI[\\/]))')
    files=sorted(p for p in target.rglob('*') if p.is_file())
    for path in files:
        if path.suffix.lower() in ('.py','.pth','.cfg','.ini','.json','.yaml','.yml','.toml','.cmd','.bat','.ps1','.txt','.md','') and path.stat().st_size<12*1024*1024:
            try:text=path.read_text(encoding='utf-8-sig')
            except (UnicodeError,OSError):continue
            if pattern.search(text):bad.append(path.relative_to(target).as_posix())
    if bad:raise RuntimeError('Unresolved absolute user/development roots: '+json.dumps(bad,ensure_ascii=False))
    manifest=target/'PACKAGE_SHA256.txt'
    with manifest.open('w',encoding='utf-8') as f:
        for i,path in enumerate(files):
            f.write(sha256(path)+'  '+path.relative_to(target).as_posix()+'\n')
            if i%15000==0:print('HASHED',edition,i,flush=True)
    report={'files':len(files)+1,'bytes':sum(p.stat().st_size for p in files)+manifest.stat().st_size,
            'absolute_user_or_project_roots':0,'workspace_empty':True}
    (WORK/(edition+'_final_payload.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    archive=target.with_suffix('.zip')
    # with_suffix would truncate names containing 0.2; append the suffix instead.
    archive=Path(str(target)+'.zip')
    create_zip(target,archive)
    with zipfile.ZipFile(archive) as bundle:
        for name in bundle.namelist():
            if name.startswith(('/','\\')) or '..' in Path(name).parts or re.match(r'^[A-Za-z]:',name):
                raise RuntimeError('Unsafe ZIP member')
        bad=bundle.testzip()
        if bad:raise RuntimeError('ZIP CRC failed: '+bad)
    digest=sha256(archive)
    Path(str(archive)+'.sha256').write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
    report.update(archive_bytes=archive.stat().st_size,archive_sha256=digest,zip_crc_verified=True)
    (WORK/(edition+'_final_payload.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('FINALIZED',archive,json.dumps(report),flush=True)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');p=argparse.ArgumentParser();p.add_argument('edition',choices=['lite','full']);finalize(p.parse_args().edition)
