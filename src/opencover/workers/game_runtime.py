"""Deterministic GPU-only entry for the installed GAME source checkout."""
from pathlib import Path
import runpy
import sys


def main():
    source=Path(sys.argv[1]).resolve()
    arguments=sys.argv[2:]
    import torch
    import lightning as pl
    if not torch.cuda.is_available():
        raise RuntimeError('GAME CUDA 不可用')
    pl.seed_everything(777,workers=True)
    print('OPENCOVER_GAME_CUDA '+torch.cuda.get_device_name(0),flush=True)
    sys.path.insert(0,str(source))
    sys.argv=[str(source/'infer.py'),*arguments]
    runpy.run_path(str(source/'infer.py'),run_name='__main__')


if __name__=='__main__':
    main()
