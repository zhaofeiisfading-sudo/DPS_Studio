"""Secondary, explicitly post-hoc diagnostics; no algorithm tuning."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from .audit import OUT
from dps_studio.algorithms.waveform.catalog import METHODS
from .runner import write_csv, write_json


def main() -> None:
    dual = []
    for i in range(8):
        case_id = f"fresh_two_component_{i:02d}"
        wave = np.load(OUT/"datasets/fresh"/f"{case_id}.npz")
        result = np.load(OUT/"matrix_pencil/runs/fresh"/case_id/"trajectory.npz")
        idx = result["sample_indices"]
        a, b = wave["truth_hz"][idx], wave["other_hz"][idx]
        x, y = result["frequency_hz"], result["secondary_frequency_hz"]
        target = np.isfinite(a) & np.isfinite(b)
        match = ((abs(x-a) <= 50e6) & (abs(y-b) <= 50e6)) | (
                 (abs(y-a) <= 50e6) & (abs(x-b) <= 50e6))
        separated = target & (abs(a-b) >= 100e6)
        dual.append(dict(case_id=case_id, target_frames=int(sum(target)),
                         both_components_within_50mhz=int(sum(target & match)),
                         both_success_fraction=float(sum(target & match)/sum(target)),
                         separation_ge_100mhz_frames=int(sum(separated)),
                         both_success_separated=int(sum(separated & match)),
                         note="POST_HOC pair-assignment diagnostic; single main-path RMSE is not dual separation"))
    write_csv(OUT/"tables/matrix_pencil_dual_diagnostic.csv", dual)
    convergence = []
    for stage in ("fresh", "real", "phase_stress"):
        for method in ("varpro", "clutter_varpro", "time_domain"):
            for folder in sorted((OUT/method/"runs"/stage).iterdir()):
                if not (folder/"diagnostics.json").exists():
                    continue
                diag = json.loads((folder/"diagnostics.json").read_text(encoding="utf-8"))["method"]
                result = np.load(folder/"trajectory.npz")
                if method == "time_domain":
                    fits = [s for s in diag.get("slabs", []) if "converged" in s]
                    count, converged = len(fits), sum(bool(s["converged"]) for s in fits)
                    not_converged = 0
                    for slab in fits:
                        if not slab["converged"]:
                            within = (result["sample_indices"] >= slab["start"]) & (
                                      result["sample_indices"] < slab["end"])
                            not_converged += int(sum(within & np.isfinite(result["accepted_hz"])))
                else:
                    fit = result["evaluations"] > 0
                    count = int(sum(fit))
                    converged = int(sum((result["optimizer_converged"] > 0) & fit))
                    not_converged = int(sum(fit & (result["optimizer_converged"] == 0)
                                             & np.isfinite(result["accepted_hz"])))
                convergence.append(dict(stage=stage, method=method, case_id=folder.name,
                    fits=count, converged=converged, accepted_frames_from_unconverged=not_converged,
                    note="Heuristic acceptance did not include optimizer convergence; diagnostic only"))
    write_csv(OUT/"tables/optimizer_convergence.csv", convergence)
    # Every real-stream rejection stays visible in the method's failure record.
    real = pd.read_csv(OUT/"tables/all_real_metrics.csv")
    for method in METHODS:
        s = real[real.method == method]
        no_event = s[s.detected_onset_s.isna()].case_id.tolist()
        no_support = s[s.accepted_finite_n == 0].case_id.tolist()
        write_json(OUT/method/"real_limitations.json", dict(
            no_detected_event=no_event, no_accepted_support=no_support,
            meaning="Missing event/support is an algorithm limitation, not proof of static target or absent optical return",
            all_real_paths=s.raw_path.unique().tolist(), tested_voltage_columns=len(s)))
    print("Secondary dual-component and optimizer diagnostics saved", flush=True)


if __name__ == "__main__":
    main()
