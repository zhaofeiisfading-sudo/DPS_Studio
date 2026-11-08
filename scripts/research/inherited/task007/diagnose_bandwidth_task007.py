"""Persist paired record uncertainty, reference convergence and boundary checks."""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.research.bandwidth_task007_simulation import Acquisition, simulate, transfer


def diagnose(root: Path) -> dict[str, Any]:
    frame = pd.read_csv(root / "output/frames.csv")
    gated = pd.read_csv(root / "supplement/gated_baseline_frames.csv")
    combined = pd.concat([frame, gated])
    subset = combined[(combined.family == "tone_scan") & ~combined.alias_ambiguous].copy()
    subset["good"] = (np.isfinite(subset.frequency_hz)
                      & (abs(subset.frequency_hz - subset.truth_hz) <= subset.tolerance_hz))
    values = subset.groupby(["case_id", "method"]).good.mean().unstack()
    delta = (values.VP_tone - values.Existing_STFT_quality).to_numpy()
    rng = np.random.default_rng(700902)
    boot = rng.choice(delta, (4000, len(delta))).mean(axis=1)
    paired = dict(records=len(delta), mean_correct_fraction_difference=float(delta.mean()),
                  record_bootstrap_95=np.quantile(boot, [.025, .975]).tolist(), seed=700902,
                  interpretation="same grid mixture, paired record bootstrap; not hardware generalization")
    cfg = Acquisition(16e9, 2e9, 4, 30., 12, 4., 8)
    coarse = simulate(cfg, frequency_hz=3.13e9, chirp_hz_per_s=1e15, seed=3)
    fine = simulate(replace(cfg, reference_oversampling=16), frequency_hz=3.13e9,
                    chirp_hz_per_s=1e15, seed=3)
    convergence = dict(reference_rates_hz=[128e9, 256e9],
        maximum_clean_voltage_difference_v=float(np.max(abs(
            coarse.noiseless_sampled_v - fine.noiseless_sampled_v))),
        interpretation="deterministic analog response convergence; noise realizations not compared")
    freq = np.array([3.099e9, 3.1e9, 3.101e9])
    response = transfer(freq, cfg)
    delay = float(-np.gradient(np.unwrap(np.angle(response)), freq)[1] / (2 * np.pi))
    chirp = frame[(frame.family == "fast_chirp") & (frame.method == "VP_chirp")]
    group_delay = dict(at_frequency_hz=3.1e9, group_delay_s=delay,
        predicted_input_output_frequency_difference_hz=-1.1e16 * delay,
        observed_mean_signed_error_hz=float(np.mean(chirp.frequency_hz - chirp.truth_hz)),
        interpretation="model-based approximate explanation, no real hardware calibration")
    before = json.loads((root.parent / "output/audit_before.json").read_text(encoding="utf-8"))
    after = json.loads((root.parent / "output/audit_after.json").read_text(encoding="utf-8"))
    raw_before = {row["path"]: row["sha256"] for row in before["raw"]}
    raw_after = {row["path"]: row["sha256"] for row in after["raw"]}
    integrity = dict(raw_sha256_unchanged=raw_before == raw_after,
        raw_files_including_gitkeep=len(raw_before),
        protected_core_gui_config_unchanged=before["protected_sha256"] == after["protected_sha256"],
        protected_files=len(before["protected_sha256"]))
    assert integrity["raw_sha256_unchanged"] and integrity["protected_core_gui_config_unchanged"]
    return dict(paired_comparison=paired, reference_grid=convergence,
                chirp_group_delay=group_delay, integrity=integrity)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    value = diagnose(args.run)
    with (args.run / "supplement/additional_diagnostics.json").open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps(value, indent=2))


if __name__ == "__main__":
    main()
