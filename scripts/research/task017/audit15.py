"""Read archived numerical gates for current-raw channels and current owning source."""
from __future__ import annotations

import gzip
import hashlib
import json

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task017.prepare import OUT, ROOT, records


def main() -> None:
    dest = OUT / "data/forensic_v01"
    dest.mkdir(exist_ok=False)
    rows, flags, nuisance = [], [], []
    old = ROOT / "artifacts/TASK-015/data/real_v02"
    for item in records():
        path = old / f"{item['id']}.npz"
        if path.exists():
            values = np.load(path)
            for key in values.files:
                if not key.endswith("__candidate"):
                    continue
                name = key.removesuffix("__candidate")
                cand = values[key]
                accepted = values[name+"__accepted"]
                rows.append({"channel": item["id"], "method": name, "centers": len(cand),
                             "candidate_n": int(np.isfinite(cand).sum()),
                             "gated_n": int(np.isfinite(accepted).sum()),
                             "gate_rejected_n": int((np.isfinite(cand) & ~np.isfinite(accepted)).sum()),
                             "no_candidate_n": int((~np.isfinite(cand)).sum()),
                             "archive": path.relative_to(ROOT).as_posix()})
                for label in np.unique(values[name+"__flags"]):
                    mask = values[name+"__flags"] == label
                    flags.append({"channel": item["id"], "method": name, "quality": str(label),
                                  "n": int(mask.sum()),
                                  "candidate_n": int((mask & np.isfinite(cand)).sum()),
                                  "gated_n": int((mask & np.isfinite(accepted)).sum())})
        current = OUT / "data/full_v01" / item["id"]
        with gzip.open(current / "clutter_varpro__details.json.gz", "rt", encoding="utf-8") as handle:
            details = json.load(handle)
        nuisance.append({"channel": item["id"], **details["diagnostics"]["nuisance"]})
    pd.DataFrame(rows).to_csv(dest / "task015_gate_counts.csv", index=False)
    pd.DataFrame(flags).to_csv(dest / "task015_quality_counts.csv", index=False)
    pd.DataFrame(nuisance).to_csv(dest / "current_clutter_prefix.csv", index=False)
    owners = ["src/dps_studio/core/segmentation/pool.py",
              "src/dps_studio/core/segmentation/strategies.py",
              "src/dps_studio/core/workflow/analysis.py", "src/dps_studio/core/quality/detection.py",
              "src/dps_studio/algorithms/waveform/common.py",
              "src/dps_studio/algorithms/waveform/dechirp/implementation.py",
              "src/dps_studio/algorithms/waveform/varpro/implementation.py",
              "src/dps_studio/algorithms/waveform/clutter_varpro/implementation.py",
              "scripts/research/task015/real.py", "scripts/research/task015/experiment.py",
              "scripts/research/task014/study.py"]
    source = {}
    for name in owners:
        with (ROOT / name).open("rb") as handle:
            source[name] = hashlib.file_digest(handle, "sha256").hexdigest()
    (dest / "owning_source_hashes.json").write_text(json.dumps(source, indent=2), encoding="utf-8")
    print("Archived gate audit:", len(rows), "channel-method records", flush=True)


if __name__ == "__main__":
    main()
