"""Copy a curated phone-readable package, preserving any different cloud version."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.research.task010.audit import OUT, sha, write_json

CLOUD = Path("G:/我的云端硬盘/codex/pdv_studio_research/research_clean_task10")


def planned_files() -> list[Path]:
    files=[OUT/name for name in ("README.md","COMPARISON.md","FIGURE_INDEX.md","FAILURES.md",
                                 "METHODS.md","VALIDATION.md","PROTOCOL.md","config.json")]
    files += list((OUT/"figures/v02").glob("*.*"))
    files += list((OUT/"summary/v02").glob("*.csv"))
    files += list((OUT/"tables").glob("*.csv"))
    files += [OUT/"runs/v01/tables"/name for name in ("real_metrics.csv","raw_streams.csv")]
    files += [OUT/"transient/v01"/name for name in ("spectral_mixing_metrics.csv","methodology.json")]
    files += [OUT/"cost/v01"/name for name in ("measurements.csv","methodology.json")]
    files += [OUT/"checks"/name for name in ("boundary_verification.json","release_verification.json",
                                            "visual_review.json","source_freeze.json")]
    for folder in (OUT/"origin/v01").iterdir():
        if folder.is_dir():
            files += [p for p in folder.iterdir() if p.suffix in (".opju",".png",".svg")
                      or p.name.endswith("_embedded.pdf")]
    return sorted(set(files))


def copy_package(files: list[Path], cloud: Path) -> dict[str, Any]:
    if not cloud.parent.is_dir():
        raise FileNotFoundError(f"Cloud parent unavailable: {cloud.parent}")
    conflicts=[]
    for path in files:
        target=cloud/path.relative_to(OUT)
        if target.exists() and sha(target)!=sha(path):
            conflicts.append(str(target))
    destination=cloud
    if conflicts:
        destination=cloud/"versions"/("2026-11-05_"+sha(OUT/"COMPARISON.md")[:12])
        if destination.exists():
            raise FileExistsError(f"Different version already occupies safe destination: {destination}")
    destination.mkdir(parents=True,exist_ok=True)
    records: list[dict[str, Any]]=[]
    for path in files:
        if not path.is_file() or not path.resolve().is_relative_to(OUT):
            raise ValueError(f"Source must be an existing local TASK-010 file: {path}")
        target=destination/path.relative_to(OUT)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if sha(target)!=sha(path):
                raise FileExistsError(f"Refusing to overwrite: {target}")
            action="IDENTICAL_KEPT"
        else:
            with path.open("rb") as source, target.open("xb") as output:
                while block:=source.read(1024*1024):
                    output.write(block)
            action="COPIED"
        local_sha=sha(path)
        if sha(target)!=local_sha:
            raise OSError(f"Cloud SHA readback mismatch: {target}")
        records.append(dict(path=path.relative_to(OUT).as_posix(),sha256=local_sha,
                            bytes=path.stat().st_size,action=action))
    value=dict(success=True,destination=str(destination),files=len(records),
               bytes=sum(r["bytes"] for r in records),conflicts_preserved=conflicts,
               local_files_moved=0,local_files_deleted=0,all_sha_readbacks_match=True,records=records,
               complete_data_and_source="authoritative in local Research artifact; NPZ/source not uploaded")
    manifest=destination/"CLOUD_MANIFEST.json"
    if not manifest.exists():
        write_json(manifest,value)
    return value


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination",type=Path,default=CLOUD)
    parser.add_argument("--receipt",type=Path,default=OUT/"checks/cloud_sync.json")
    args=parser.parse_args()
    if args.receipt.exists():
        parser.error("Receipt exists; use a new receipt filename")
    try:
        result=copy_package(planned_files(),args.destination)
    except Exception as exc:
        result=dict(success=False,destination=str(args.destination),reason=f"{type(exc).__name__}: {exc}",
                    local_artifacts_preserved=True,next_step="restore G drive access or use a new cloud version; rerun with a new receipt filename")
        write_json(args.receipt,result)
        print(json.dumps(result,ensure_ascii=False))
        raise SystemExit(1) from exc
    write_json(args.receipt,result)
    print(json.dumps({k:v for k,v in result.items() if k!="records"},ensure_ascii=False))


if __name__=="__main__":
    main()
