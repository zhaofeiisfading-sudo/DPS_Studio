"""Verify pre-existing files and raw/Production boundaries without modifying them."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Any

from scripts.run_task025 import load_json
from scripts.run_task023f_proposal_recovery import ROOT, sha256, write_csv, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output.resolve()
    frozen = load_json(output / 'frozen_manifest.json')
    raw, differences, snapshots = [], [], {}
    count = 0
    for name, root in (('Research', ROOT), ('Production', ROOT.parent / 'DPS_Studio')):
        before = frozen[name]
        commands = tuple(before['git'])
        after = {cmd: subprocess.check_output(['git', *cmd.split()], cwd=root,
                    text=True).strip() for cmd in commands}
        snapshots[name] = after
        for relative, expected in before['hashes'].items():
            path = root / relative
            actual = sha256(path) if path.is_file() else 'MISSING'
            count += 1
            if actual != expected:
                differences.append(dict(tree=name, path=relative, before=expected, after=actual))
            if relative.startswith('data/raw/'):
                raw.append(dict(tree=name, path=relative, before_sha256=expected,
                                after_sha256=actual, unchanged=actual == expected))
        original_raw = {p for p in before['hashes'] if p.startswith('data/raw/')}
        actual_raw = {p.relative_to(root).as_posix() for p in (root / 'data/raw').rglob('*')
                      if p.is_file()}
        assert actual_raw == original_raw, f'{name} raw inventory changed'
        for command in ('rev-parse HEAD', 'rev-parse main', 'branch --show-current'):
            assert before['git'][command] == after[command], f'{name} {command} changed'
        if name == 'Production':
            assert before['git'] == after, 'Production git state changed'
    for relative, expected in load_json(output / 'implementation_freeze.json').items():
        assert sha256(ROOT / relative) == expected, relative
    for file, field in (('protocol.md', 'protocol_sha256'),
                        ('seed_registration.json', 'seed_sha256'),
                        ('threshold_protocol.json', 'threshold_protocol_sha256')):
        assert sha256(output / file) == frozen[field], file
    write_csv(output / 'raw_hash_verification.csv', raw)
    write_csv(output / 'boundary_differences.csv', differences,
              ('tree', 'path', 'before', 'after'))
    write_json(output / 'repository_after.json', snapshots)
    summary: dict[str, Any] = dict(preexisting_files_checked=count,
        all_preexisting_files_unchanged=not differences, raw_entries=len(raw),
        raw_hash_unchanged=all(v['unchanged'] for v in raw), production_unchanged=True,
        main_refs_unchanged=True, research_head_unchanged=True,
        frozen_implementation_unchanged=True, preregistration_unchanged=True,
        differences=differences)
    write_json(output / 'boundary_verification.json', summary)
    print(summary, flush=True)
    assert not differences, 'Pre-existing file changed; see boundary_differences.csv'


if __name__ == '__main__':
    main()
