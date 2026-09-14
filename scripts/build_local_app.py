"""Build the local desktop app against this project's existing E-drive resources.

This installs a local EXE, not a portable distribution of backend environments.
"""
from pathlib import Path
from datetime import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    work = root / 'workspace' / 'local_app_build'
    for name in ('TEMP', 'TMP', 'TMPDIR'):
        directory = work / 'tmp' / name
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(directory)
    os.environ['PYTHONUTF8'] = '1'
    os.environ['PYINSTALLER_CONFIG_DIR'] = str(work / 'pyinstaller_cache')
    runtimes = ['diffsinger_legacy_runtime.py', 'diffsinger_score_frontend.py', 'game_runtime.py',
                'alignment_runtime.py', 'score_refinement_runtime.py', 'rvc_batch_runtime.py', 'vocalparse_runtime.py',
                'rvc_training_runtime.py']
    common = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--paths', str(root/'src'),
              '--specpath', str(work/'spec'), '--distpath', str(work/'dist')]
    for name in runtimes:
        common += ['--add-data', str(root/'src/opencover/workers'/name) + os.pathsep + 'workers']
    gui = common + ['--workpath', str(work/'gui'), '--windowed', '--onedir',
                    '--contents-directory', '_opencover_runtime', '--name', 'OpenCoverStudio']
    icon = root/'build/图标.ico'
    if icon.is_file():
        gui += ['--icon', str(icon)]
    subprocess.run(gui + [str(root/'app.py')], cwd=root, check=True)
    runtime_tmp = root/'workspace/tmp/frozen_worker'
    runtime_tmp.mkdir(parents=True, exist_ok=True)
    subprocess.run(common + ['--workpath', str(work/'worker'), '--console', '--onefile',
                             '--runtime-tmpdir', str(runtime_tmp), '--name', 'OpenCoverStudioWorker',
                             str(root/'worker_entry.py')], cwd=root, check=True)
    backup = root/'workspace/source_backups'/('local_app_' + datetime.now().strftime('%Y%m%d_%H%M%S'))
    files = [(p, root/p.relative_to(work/'dist/OpenCoverStudio'))
             for p in (work/'dist/OpenCoverStudio').rglob('*') if p.is_file()]
    files.append((work/'dist/OpenCoverStudioWorker.exe', root/'OpenCoverStudioWorker.exe'))
    for source, target in files:
        if target.exists():
            saved = backup/target.relative_to(root)
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    manifest = {'kind': 'local_project_install', 'portable': False, 'root': str(root),
                'built_at': datetime.now().isoformat(), 'executables': {}}
    for name in ('OpenCoverStudio.exe', 'OpenCoverStudioWorker.exe'):
        path = root/name
        manifest['executables'][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (work/'installed.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('INSTALLED ' + str(root/'OpenCoverStudio.exe'), flush=True)


if __name__ == '__main__':
    main()
