"""Read-only inventories; all audit outputs remain in TASK-015. Never deletes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
OUT = (Path(__file__).resolve().parents[3] / "artifacts/TASK-015") / 'disk_governance'
PRODUCTION = ROOT.parent / 'DPS_Studio'

def files(root):
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not (Path(folder)/d).is_junction()
                         and not (Path(folder)/d).is_symlink())
        for name in sorted(names):
            p = Path(folder)/name
            if not p.is_symlink():
                yield p

def manifest(root):
    result = {}
    for p in files(root):
        stat = p.stat()
        with p.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
        result[p.relative_to(root).as_posix()] = dict(sha256=digest, bytes=stat.st_size,
                                                    mtime_ns=stat.st_mtime_ns)
    return result

def git(root):
    def command(*args):
        return subprocess.check_output(['git','--no-optional-locks','-C',str(root),*args],
                                       encoding='utf-8').strip()
    return dict(head=command('rev-parse','HEAD'), branch=command('branch','--show-current'),
                status=command('status','--porcelain=v1'),
                common=command('rev-parse','--path-format=absolute','--git-common-dir'))

def save(name, value):
    with (OUT/name).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)

def main():
    label = argparse.ArgumentParser()
    label.add_argument('phase', choices=['before','after'])
    phase = label.parse_args().phase
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = {}
    for p in files(ROOT):
        relative = p.relative_to(ROOT)
        key = relative.parts[0]
        item = sizes.setdefault(key, dict(files=0, bytes=0))
        item['files'] += 1
        item['bytes'] += p.stat().st_size
    save(f'workspace_audit_{phase}.json', sizes)
    lines = ['# Workspace disk inventory', '', '| Root entry | Files | MiB |',
             '|---|---:|---:|']
    lines += [f'| {k} | {v["files"]} | {v["bytes"]/2**20:.2f} |'
              for k,v in sorted(sizes.items(), key=lambda x:-x[1]['bytes'])]
    (OUT/f'workspace_audit_{phase}.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(phase=phase, files=sum(x['files'] for x in sizes.values()),
                         GiB=sum(x['bytes'] for x in sizes.values())/2**30)), flush=True)
    boundaries = dict(research_git=git(ROOT), production_git=git(PRODUCTION),
                      raw=manifest(ROOT/'data/raw'),
                      supplement=manifest(ROOT/'data/research/TASK-009/source_data'),
                      production=manifest(PRODUCTION), python=sys.executable)
    save(f'boundaries_{phase}.json', boundaries)
    if phase == 'after':
        before = json.loads((OUT/'boundaries_before.json').read_text(encoding='utf-8'))
        check = {k: before[k] == boundaries[k] for k in
                 ('production_git','raw','supplement','production')}
        save('boundary_comparison.json', check)
        print(check, flush=True)
        if not all(check.values()):
            raise RuntimeError('Protected boundary changed; inspect complete manifests')
    print('Boundary hash inventory complete', flush=True)

if __name__ == '__main__':
    main()
