"""Read-only diagnostics of the in-tree documented waveform reference.

Mapping evidence: docs/user_manual/PDV_Studio_用户使用说明书.md:305.
No external raw migration; no physical-frequency acceptance or velocity conversion.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from dps_studio.core.io import read_delimited_signals  # noqa: E402
from dps_studio.research.bandwidth_task001 import (  # noqa: E402
    local_model_residual, residual_diagnostics, spectral_baselines,
)
from run_task001_bandwidth import ROOT, sha, validate_output, write_csv, write_json, write_text  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    source = ROOT / "docs" / "原始数据.csv"
    resolved = source.resolve(strict=True)
    if not resolved.is_relative_to(ROOT.resolve()):
        raise ValueError("Reference target resolves outside worktree")
    out = validate_output(ROOT / "results" / "task001_bandwidth" / args.run_id)
    before = sha(resolved)
    write_json(out / "read_audit_before.json", {
        "source": str(resolved), "sha256_before": before,
        "mapping_source": "docs/user_manual/PDV_Studio_用户使用说明书.md:305",
        "time_column": 0, "voltage_columns": {"ch1": 1, "ch2": 2},
        "time_scale": 1., "voltage_scales": {"ch1": 1., "ch2": 1.},
        "original_time_unit": "s", "original_voltage_unit": "V", "delimiter": ",",
        "has_header": False, "encoding": "utf-8",
        "selection": "48 uniformly spaced nonoverlapping frames per channel and sample length",
        "sample_lengths": [256, 512], "search_band_hz": [0.2e9, 9.5e9],
        "instrument_response": "UNKNOWN", "bandwidth_hz": "UNKNOWN", "optical_offset_hz": "UNKNOWN",
        "wavelength_m": "UNKNOWN", "independent_frequency_truth": "UNKNOWN",
        "source_sha256": {str(p.relative_to(ROOT)): sha(p) for p in (
            Path(__file__), ROOT / "src/dps_studio/research/bandwidth_task001.py")},
    })
    rows: list[dict[str, Any]] = []
    examples: dict[str, Any] = {}
    sampling: dict[str, Any] = {}
    started = perf_counter()
    try:
        loaded = read_delimited_signals(
            resolved, time_column=0, voltage_columns={"ch1": 1, "ch2": 2}, delimiter=",",
            has_header=False, encoding="utf-8", time_scale=1.,
            voltage_scales={"ch1": 1., "ch2": 1.}, original_time_unit="s",
            original_voltage_units={"ch1": "V", "ch2": "V"},
        )
        for channel, record in loaded.records.items():
            if not record.is_uniformly_sampled:
                raise ValueError("Nonuniform sampling: cannot apply the uniform local model")
            fs = record.sample_rate_hz
            sampling[channel] = {"sample_rate_hz": fs, "nyquist_hz": fs / 2,
                                 "sample_count": record.sample_count,
                                 "start_time_s": record.start_time_s, "end_time_s": record.end_time_s}
            for n in (256, 512):
                for frame, block in enumerate(np.linspace(0, record.sample_count // n - 1, 48,
                                                         dtype=int)):
                    start = int(block) * n
                    y = record.voltage_v[start:start + n]
                    baseline = spectral_baselines(y, fs)
                    for model in ("tone", "chirp", "two_tone"):
                        residual, fit = local_model_residual(y, fs, model)
                        diagnostics = residual_diagnostics(residual, fs)
                        rows.append({"channel": channel, "n": n, "frame": frame,
                                     "start_sample": start,
                                     "center_time_s": float(record.time_s[start:start + n].mean()),
                                     "frame_window_s": n / fs, "fft_grid_hz": fs / (4 * n),
                                     "fit_model": model,
                                     "candidate_frequency_hz": fit["frequency_hz"],
                                     "stft_candidate_frequency_hz": baseline.peak_hz,
                                     "accepted_frequency_hz": math.nan, "uncertainty_hz": math.nan,
                                     "quality_flag": "OBSERVATIONAL_REFERENCE_ONLY",
                                     "provenance": str(resolved), **fit, **diagnostics})
                        if n == 512 and frame == 24:
                            examples[f"{channel}_{model}"] = residual
                            examples[f"{channel}_time_s"] = record.time_s[start:start + n]
                            examples[f"{channel}_signal_v"] = y
        write_csv(out / "real_residual_diagnostics.csv", rows)
        np.savez_compressed(out / "real_examples.npz", **examples)
        groups: dict[tuple[str, int, str], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            groups[row["channel"], row["n"], row["fit_model"]].append(row)
        summary = [{"channel": c, "n": n, "fit_model": m, "frames": len(part),
                    "converged": sum(r["converged"] for r in part),
                    **{f"median_{k}": float(np.median([r[k] for r in part])) for k in (
                        "lag1", "residual_rms_v", "quarter_power_ratio", "psd_peak_hz")},
                    "fraction_abs_lag1_above_0_3": float(np.mean([abs(r["lag1"]) > 0.3 for r in part]))}
                   for (c, n, m), part in groups.items()]
        write_csv(out / "real_summary.csv", summary)
        fig, axes = plt.subplots(2, 2, figsize=(11, 7), constrained_layout=True)
        for j, channel in enumerate(("ch1", "ch2")):
            for model in ("tone", "chirp", "two_tone"):
                part = [r for r in rows if r["channel"] == channel and r["n"] == 512
                        and r["fit_model"] == model]
                times = np.array([r["center_time_s"] for r in part])
                axes[j, 0].plot((times - times[0]) * 1e6, [r["lag1"] for r in part],
                                ".-", label=model)
                axes[j, 1].plot((times - times[0]) * 1e6,
                                np.array([r["candidate_frequency_hz"] for r in part]) / 1e9,
                                ".", label=model)
            axes[j, 0].set(title=f"{channel}: residual ACF", xlabel="Time from first frame (µs)",
                           ylabel="Lag-1 ACF")
            axes[j, 1].set(title=f"{channel}: unaccepted candidates", xlabel="Time from first frame (µs)",
                           ylabel="Frequency (GHz)")
            axes[j, 0].legend()
            axes[j, 1].legend()
        fig.savefig(out / "real_diagnostics.png", dpi=180)
        plt.close(fig)
        write_text(out / "REAL_REFERENCE_DIAGNOSTICS.md", "# Real reference waveform diagnostics\n\n"
                   "OBSERVATIONAL_REFERENCE_ONLY. docs/原始数据.csv is documented as a raw reference copy,"
                   " 80000 rows, 3 columns. Time column 0 in s; channels 1/2 in V; mapping comes from the"
                   " existing user manual. It is not any of the four old TASK-007 named files.\n\n"
                   "48 uniformly spaced nonoverlapping frames per channel and N=256/512; tone, chirp and"
                   " two-tone descriptive fits. Both window sizes share a record and must not be treated"
                   " as independent experiments. No independent noise-only region is certified, so no AR"
                   " detection threshold, interval or physical-frequency acceptance is transferred from"
                   " the synthetic benchmark. Instrument/optical/target truth UNKNOWN; no velocity output.\n\n"
                   "Compare real_summary.csv and real_diagnostics.png. ACF reductions cannot uniquely distinguish"
                   " AM/chirp/multiple beats from filtered electronics. A single reference record cannot supply"
                   " file-level real train/test validation. Before/after hashes are in real_data_status.json.\n")
    except Exception as exc:
        write_json(out / "failure.json", {"type": type(exc).__name__, "reason": str(exc)})
        raise
    finally:
        after = sha(resolved)
        write_json(out / "real_data_status.json", {"status": "OBSERVATIONAL_REFERENCE_ONLY",
                                                   "source": str(resolved), "sha256_before": before,
                                                   "sha256_after": after, "unchanged": before == after,
                                                   "sampling": sampling, "rows_written": len(rows),
                                                   "elapsed_s": perf_counter() - started})
        if before != after:
            raise RuntimeError("Reference waveform changed during read-only diagnostics")
    print(json.dumps({"out": str(out), "rows": len(rows), "sha256": before}, ensure_ascii=False))


if __name__ == "__main__":
    main()
