"""Read-only SHA-256/mtime snapshots including the actual Production Git store."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.research.task017.boundary import PRODUCTION, ROOT, git, manifest
from scripts.research.task017.compare import digest

OUT = ROOT / 'artifacts/TASK-018'


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=['before', 'after'])
    parser.add_argument('--output', default='boundary')
    args = parser.parse_args()
    dest = (OUT / 'data' / args.output).resolve()
    assert dest.parent == (OUT / 'data').resolve()
    dest.mkdir(parents=True, exist_ok=True)
    research = git(ROOT)
    production = git(PRODUCTION)
    value = dict(research_git=research, production_git=production,
                 research_index=digest(Path(research['common']) / 'index'),
                 production_git_files=manifest(Path(production['common'])),
                 production=manifest(PRODUCTION), raw=manifest(ROOT / 'data/raw'),
                 source=manifest(ROOT / 'src'), previous=manifest(ROOT / 'artifacts/TASK-017'))
    with (dest / f'{args.phase}.json').open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    if args.phase == 'after':
        old = json.loads((dest / 'before.json').read_text(encoding='utf-8'))
        checks = {key: old[key] == val for key, val in value.items() if key != 'research_git'}
        for key in ('head', 'branch', 'staged', 'common'):
            checks[f'research_{key}'] = old['research_git'][key] == research[key]
        with (dest / 'comparison.json').open('x', encoding='utf-8') as stream:
            json.dump(checks, stream, indent=2)
        if not all(checks.values()):
            raise RuntimeError(checks)
        print(checks)
    print(f'{args.phase} snapshot complete', flush=True)


if __name__ == '__main__':
    main()
