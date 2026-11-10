"""Reassemble routing from retained components, then compute real observables."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task017.compare import diagnose, evidence, frozen_plans
from scripts.research.task017.prepare import OUT, load, records

SIMPLE = {"stationary": "stft_low", "onset": "stft_short", "rebound": "stft_short",
          "acceleration": "stft_short", "decline": "stft_short", "plateau": "stft_long",
          "noise": "stft_long", "weak_signal": "stft_long"}
ROUTES = {
    "M2_task014_gui": {"acceleration": "dechirp", "noise": "unobservable"},
    "M3_parameters": SIMPLE,
    "M4_specialized": {**SIMPLE, "stationary": "low_glrt", "plateau": "tone_refine",
                       "acceleration": "signed_dechirp", "decline": "signed_dechirp",
                       "noise": "clutter_varpro"},
}


def load_channel(run: Path, channel: str) -> tuple[dict[str, Any], dict[str, Any]]:
    meta = json.loads((run / channel / "metadata.json").read_text(encoding="utf-8"))
    traces = {name: dict(np.load(run / channel / f"{name}.npz")) for name in meta["methods"]}
    for name, mapping in ROUTES.items():
        v = {key: np.array(value, copy=True) for key, value in traces["M1_balanced"].items()}
        v["component"] = np.full(len(v["time_s"]), "M1_balanced", dtype="U40")
        for stage in np.unique(v["stage"]):
            component = mapping.get(str(stage), "M1_balanced")
            mask = v["stage"] == stage
            if component == "unobservable":
                for key in ("raw_frequency_hz", "frequency_hz", "gated_frequency_hz"):
                    v[key][mask] = np.nan
                v["spectrally_supported"][mask] = False
                v["quality"][mask] = "EXPLICIT_OPERATOR_EXCLUSION"
                v["missing_reason"][mask] = "EXPLICIT_OPERATOR_EXCLUSION"
                v["component"][mask] = component
                continue
            for key in v:
                if key != "component":
                    v[key][mask] = traces[component][key][mask]
            v["component"][mask] = component
            if component in ("dechirp", "clutter_varpro"):
                outside = mask & ((v["gated_frequency_hz"] < 50e6)
                                  | (v["gated_frequency_hz"] > 6e9))
                v["gated_frequency_hz"][outside] = np.nan
                v["quality"][outside] = "OUTSIDE_USER_FREQUENCY_BAND"
        outside = (v["raw_frequency_hz"] < 5e6) | (v["raw_frequency_hz"] > 6e9)
        v["frequency_hz"][outside] = np.nan
        v["spectrally_supported"][outside] = False
        v["missing_reason"][outside] = "OUTSIDE_METHOD_BAND"
        traces[name] = v
        meta["methods"][name]["band_hz"] = [5e6, 6e9]
    for name, values in traces.items():
        values.setdefault("component", np.full(len(values["time_s"]), name, dtype="U40"))
        reason = values["missing_reason"].astype("U64")
        missing = ~np.isfinite(values["raw_frequency_hz"])
        for text, label in (("NO_EVENT", "NO_EVENT_PREGENERATION_SKIP"),
                            ("PRE_EVENT", "PRE_EVENT_PREGENERATION_SKIP"),
                            ("INSUFFICIENT", "INSUFFICIENT_WINDOW_SUPPORT"),
                            ("ALGORITHM_ERROR", "ALGORITHM_ERROR")):
            reason[missing & (np.char.find(values["quality"].astype(str), text) >= 0)] = label
        values["missing_reason"] = reason
        values["gate_status"] = np.where(np.isfinite(values["gated_frequency_hz"]), "PASSED",
            np.where(np.isfinite(values["frequency_hz"]), "REJECTED_CANDIDATE_RETAINED", "MISSING"))
    return traces, meta


def metrics(values: dict[str, Any], mask: Any, name: str, channel: str,
            segment: str, stage: str, runtime: float) -> dict[str, Any]:
    f = values["frequency_hz"]
    candidate = mask & np.isfinite(f)
    gated = mask & np.isfinite(values["gated_frequency_hz"])
    supported = mask & values["spectrally_supported"]
    raw = mask & np.isfinite(values["raw_frequency_hz"])
    paired = mask[1:] & mask[:-1] & np.isfinite(f[1:]) & np.isfinite(f[:-1])
    jumps = abs(np.diff(f))[paired]
    result: dict[str, Any] = {"channel": channel, "method": name, "segment_id": segment,
        "stage": stage, "centers": int(mask.sum()), "raw_candidate_n": int(raw.sum()),
        "candidate_n": int(candidate.sum()), "gated_n": int(gated.sum()),
        "supported_n": int(supported.sum()), "supported_gated_n": int((supported & gated).sum()),
        "supported_common50_6_n": int((supported & (f >= 50e6) & (f <= 6e9)).sum()),
        "gate_rejected_n": int((candidate & ~gated).sum()),
        "no_candidate_n": int((mask & ~raw).sum()),
        "outside_band_n": int((raw & ~candidate).sum()),
        "jump_250MHz_n": int((jumps > 250e6).sum()),
        "max_jump_hz": float(jumps.max()) if len(jumps) else None,
        "first_supported_time_s": float(values["time_s"][supported][0]) if supported.any() else None,
        "runtime_full_record_s": runtime,
        "physical_branch": "requires experimental confirmation"}
    for key in ("spectral_contrast_db", "background_gain_db", "competitor_advantage_db",
                "raw_tone_r2", "raw_chirp_r2", "raw_tone_residual_rms_v",
                "raw_chirp_residual_rms_v"):
        selected = values[key][candidate]
        result["median_"+key] = float(np.nanmedian(selected)) if len(selected) else None
    if "long4096_spectrally_supported" in values:
        result["long4096_supported_n"] = int((mask & values["long4096_spectrally_supported"]).sum())
    denominator = max(int(mask.sum()), 1)
    for label in ("candidate", "gated", "supported"):
        result[label+"_coverage_pct"] = result[label+"_n"]/denominator*100
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--controls", type=Path)
    parser.add_argument("--long-diagnostics", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(OUT / "data"):
        parser.error("Output must be a new TASK-017 data directory")
    output.mkdir(exist_ok=False)
    plans = frozen_plans()
    summaries, gains, agreements, accounting = [], [], [], []
    methods_of_agreement = ("M1_balanced", "formal_short512", "formal_long2048", "dechirp",
                            "varpro", "clutter_varpro", "matrix_pencil", "acmd", "time_domain")
    for item in records():
        channel = item["id"]
        traces, meta = load_channel(args.run, channel)
        if args.controls:
            control_meta = json.loads((args.controls / channel / "metadata.json").read_text(
                encoding="utf-8"))["methods"]
            for name, definition in control_meta.items():
                traces[name] = dict(np.load(args.controls / channel / f"{name}.npz"))
                traces[name]["component"] = np.full(len(traces[name]["time_s"]), name, dtype="U40")
                traces[name]["gate_status"] = np.where(
                    np.isfinite(traces[name]["gated_frequency_hz"]), "PASSED",
                    np.where(np.isfinite(traces[name]["frequency_hz"]),
                             "REJECTED_CANDIDATE_RETAINED", "MISSING"))
                meta["methods"][name] = definition
        dest = output / channel
        dest.mkdir()
        base = traces["M1_balanced"]
        primary = base["primary_common_support"]
        t, y, fs = load(item)
        onset = next(seg for seg in plans[channel] if seg["stage"] == "onset")
        long_ev = (evidence(t, y, fs, base["sample_index"],
                            onset["start_range_s"][0]-2e-9, width=4096)
                   if args.long_diagnostics else None)
        frames = []
        for name, values in traces.items():
            if long_ev is None:
                for key in list(values):
                    if key.startswith("long4096_"):
                        del values[key]
            elif "long4096_spectrally_supported" not in values:
                long_diag = diagnose(values, long_ev, fs)
                for key, data in long_diag.items():
                    values["long4096_"+key.replace("cycles_256", "cycles_in_support")] = data
            # This agreement is descriptive. Related algorithms are not independent votes.
            agreement = np.zeros(len(primary), dtype=int)
            for other in methods_of_agreement:
                if other == name:
                    continue
                vv = traces[other]
                agreement += (values["spectrally_supported"] & vv["spectrally_supported"]
                              & (abs(values["frequency_hz"]-vv["frequency_hz"]) <= 100e6))
            values["cross_method_agreement_n"] = agreement
            np.savez_compressed(dest / f"{name}.npz", **values)
            frame = pd.DataFrame(values)
            frame.insert(0, "channel", channel)
            frame.insert(1, "method", name)
            frame["candidate_source"] = meta["methods"][name]["source"]
            frame["wavelength_m"] = np.nan
            frame["physical_branch"] = "requires experimental confirmation"
            frames.append(frame)
            for seg in [{"id": "ALL", "stage": "ALL"}, *plans[channel]]:
                mask = primary if seg["id"] == "ALL" else primary & (values["segment_id"] == seg["id"])
                summaries.append(metrics(values, mask, name, channel, seg["id"], seg["stage"],
                                         meta["methods"][name]["runtime_s"]))
                if seg["stage"] != "onset":
                    continue
                finite = np.isfinite(values["frequency_hz"])
                base_finite = np.isfinite(base["frequency_hz"])
                base_gate = np.isfinite(base["gated_frequency_hz"])
                support = values["spectrally_supported"]
                base_support = base["spectrally_supported"]
                tolerance = max(100e6, item["sample_rate_hz"]/256*.5)
                same = finite & base_finite & (abs(values["frequency_hz"]-base["frequency_hz"]) <= tolerance)
                gains.append({"channel": channel, "method": name, "centers": int(mask.sum()),
                    "supported_n": int((mask & support).sum()),
                    "base_supported_n": int((mask & base_support).sum()),
                    "supported_gain_n": int((mask & support & ~base_support).sum()),
                    "supported_loss_n": int((mask & base_support & ~support).sum()),
                    "supported_net_gain_n": int((mask & support).sum()-(mask & base_support).sum()),
                    "supported_common50_6_n": int((mask & support & (values["frequency_hz"] >= 50e6)
                                                   & (values["frequency_hz"] <= 6e9)).sum()),
                    "same_base_candidate_rejected_n": int((mask & support & same & ~base_gate).sum()),
                    "different_supported_candidate_n": int((mask & support & ~same & base_finite).sum()),
                    "new_when_base_candidate_missing_n": int((mask & support & ~base_finite).sum()),
                    "first_supported_time_s": summaries[-1]["first_supported_time_s"],
                    "gate_rejected_n": summaries[-1]["gate_rejected_n"],
                    "spectral_support_is_physical_truth": False})
                for quality in np.unique(values["quality"][mask]):
                    qmask = mask & (values["quality"] == quality)
                    accounting.append({"channel": channel, "method": name, "quality": quality,
                                       "centers": int(qmask.sum()),
                                       "candidate_n": int((qmask & finite).sum()),
                                       "gated_n": int((qmask & np.isfinite(values["gated_frequency_hz"])).sum())})
                agreements.append({"channel": channel, "method": name,
                    "supported_with_at_least_two_other_methods_n": int((mask & (agreement >= 2)).sum())})
        pd.concat(frames, ignore_index=True).to_csv(dest / "candidates.csv.gz", index=False)
        (dest / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        print("analyzed", channel, flush=True)
    pd.DataFrame(summaries).to_csv(output / "segment_metrics.csv", index=False)
    pd.DataFrame(gains).to_csv(output / "onset_gains.csv", index=False)
    pd.DataFrame(accounting).to_csv(output / "onset_quality_accounting.csv", index=False)
    pd.DataFrame(agreements).to_csv(output / "onset_agreement.csv", index=False)
    (output / "provenance.json").write_text(json.dumps({
        "input_run": str(args.run.resolve()), "visual_freeze": "../visual_freeze.json",
        "posthoc_dc_controls": str(args.controls.resolve()) if args.controls else None,
        "route_reassembled": True,
        "correction": "M2/M3/M4 user 6 GHz upper bound and frozen-adapter 50 MHz lower gate restored; "
                      "full_v01 native components retained unchanged; no waveform/trajectory interpolation",
        "diagnostic_thresholds": {"width": 256, "spectral_contrast_db": 10,
                                  "background_gain_db": 6, "cycles": 1, "r2": .2},
        "no_ground_truth": True, "no_synthetic_data": True}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
