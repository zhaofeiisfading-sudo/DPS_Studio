"""Reproducible read-only boundary capture for a NEW TASK-026 artifact directory."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from scripts.freeze_task026 import ROOT, digest, write_json


def capture(root: Path, label: str, output: Path) -> dict[str, Any]:
    commands = ('status --short --branch', 'rev-parse HEAD', 'branch --show-current',
                'rev-parse main', 'diff', 'diff --cached')
    git = {}
    for command in commands:
        data = subprocess.check_output(['git', *command.split()], cwd=root)
        git[command] = data.decode('utf-8', errors='replace').strip()
        with (output/(label+'_'+command.replace(' ', '_')+'.txt')).open('xb') as handle:
            handle.write(data)
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
    files = {root/name for name in names if name and (root/name).is_file()}
    files.update(p for p in (root/'data/raw').rglob('*') if p.is_file())
    return dict(git=git, hashes={p.relative_to(root).as_posix(): digest(p) for p in sorted(files)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    parent = (ROOT/'artifacts/task026_frequency_representation').resolve()
    if output.parent != parent:
        raise ValueError('Use a new timestamp directory in Research artifacts/task026_frequency_representation')
    output.mkdir(parents=True, exist_ok=False)
    for name in ('tests', 'figures', 'waveforms', 'streams'):
        (output/name).mkdir()
    research = capture(ROOT, 'Research', output)
    production = capture(ROOT.parent/'DPS_Studio', 'Production', output)
    write_json(output/'boundary_before.json', dict(Research=research, Production=production))
    print(output)


if __name__ == '__main__':
    main()
