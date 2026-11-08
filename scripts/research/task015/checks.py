"""Run pytest with relocated data and exact protected-path write guards."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
PROTECTED = (ROOT.parent/'DPS_Studio', ROOT/'data/raw',
             ROOT/'data/research/TASK-009/source_data')


def guard(event, args):
    targets = ()
    if event == 'open' and len(args) >= 3:
        mode, flags = args[1:3]
        if ((isinstance(mode,str) and any(c in mode for c in 'wax+')) or
            (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC))):
            targets=args[:1]
    elif event in ('os.remove','os.rmdir','os.mkdir','os.chmod','os.utime','os.truncate'):
        targets=args[:1]
    elif event in ('os.rename','os.link','os.symlink'):
        targets=args[:2]
    for target in targets:
        if isinstance(target,(str,bytes,os.PathLike)):
            path=Path(os.fsdecode(target)).resolve()
            if any(path.is_relative_to(p) for p in PROTECTED):
                raise PermissionError(f'TASK-015 protected write denied: {path}')


if __name__ == '__main__':
    import faulthandler
    faulthandler.dump_traceback_later(90, repeat=True)
    sys.addaudithook(guard)
    from dps_studio.research.task009_data import install
    install()
    import pytest
    code = pytest.main(sys.argv[1:])
    faulthandler.cancel_dump_traceback_later()
    raise SystemExit(code)
