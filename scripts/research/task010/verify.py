"""Release checks for complete denominators, exact-grid attribution, and media."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task010.audit import OUT, write_json


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("run","summary","figures","qa","cost","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists() or not args.output.resolve().is_relative_to(OUT):
        parser.error("Output must be a new TASK-010 file")
    data=pd.read_csv(args.run/"tables/synthetic_metrics.csv")
    real=pd.read_csv(args.run/"tables/real_metrics.csv")
    cost=pd.read_csv(args.cost/"measurements.csv")
    invariant=pd.read_csv(args.summary/"hop_invariance.csv")
    equivalent=json.loads((args.run/"checks/frozen_strict_equivalence.json").read_text(encoding="utf-8"))
    checks: dict[str,Any] = dict(
        synthetic_records=len(data),synthetic_cases=data.groupby("stage").case_id.nunique().to_dict(),
        real_records=len(real),real_streams=int(real.case_id.nunique()),
        benchmark_measurements=len(cost),frozen_strict_checks=len(equivalent),
        all_hop_common_scores_equal=bool(invariant.all_common_scores_equal.all()),
        all_frozen_nan_patterns_equal=all(r["nan_pattern_equal"] for r in equivalent),
        largest_frozen_frequency_difference_hz=max(r["max_abs_difference_hz"] for r in equivalent),
        input_completeness=json.loads((args.run/"checks/raw_input_completeness.json").read_text(encoding="utf-8")))
    assert len(data)==6714 and len(real)==170 and real.case_id.nunique()==17
    assert checks["synthetic_cases"]==dict(confirmation=24,fresh=96,phase_stress=50)
    assert len(cost)==189 and len(equivalent)==292
    assert checks["all_hop_common_scores_equal"] and checks["all_frozen_nan_patterns_equal"]
    assert checks["largest_frozen_frequency_difference_hz"]<1e-3
    for grid in ("common","native"):
        for state in ("candidate","supported"):
            for region in ("motion","low","fast","onset40"):
                prefix=f"{grid}_{state}_{region}_"
                n=data[prefix+"target_n"]
                finite=data[prefix+"finite_n"]
                failed=data[prefix+"failure_n"]
                assert ((0<=finite)&(finite<=n)&(failed>=n-finite)&(failed<=n)).all()
    rows = real.to_dict("records")
    for stage in ("fresh","phase_stress","confirmation"):
        part=data[data.stage==stage].drop_duplicates("case_id")
        rows.extend(part.to_dict("records"))
    for row in rows:
        with np.load(args.run/row["trajectory"]) as trace:
            assert np.isnan(trace["corrected_velocity_m_s"]).all()
            assert len(trace["flags"])==len(trace["frequency_hz"])
            assert np.all(np.diff(trace["sample_indices"])>0)
            assert np.all(np.isfinite(trace["frequency_hz"][np.isfinite(trace["accepted_hz"])]))
    figures=json.loads((args.figures/"figure_manifest.json").read_text(encoding="utf-8"))
    assert len(figures)==7
    for figure in figures:
        for ext in ("pdf","svg","png"):
            assert (args.figures/(figure["id"]+"."+ext)).stat().st_size>1000
        assert "<text" in (args.figures/(figure["id"]+".svg")).read_text(encoding="utf-8")
    qa=json.loads((args.qa/"qa_summary.json").read_text(encoding="utf-8"))
    assert len(qa)==9
    assert all(r["fonts_embedded"] and r["image_objects"]==0 and r["outside_words"]==0 for r in qa)
    checks.update(checked_velocity_separation_trajectories=len(rows),
                  denominator_checks_passed=True,figure_vector_checks_passed=True,
                  pdfs_passed=len(qa),all_passed=True)
    write_json(args.output,checks)
    print(json.dumps(checks,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
