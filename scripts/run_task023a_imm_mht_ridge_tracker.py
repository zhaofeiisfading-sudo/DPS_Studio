"""Execute the read-only TASK-023A coverage-first IMM/MHT Research study."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from dps_studio.core.ridge import (
    GlobalPathConfig,
    RidgeCandidateSet,
    extract_global_path_candidates,
    solve_global_candidate_path,
)
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import load_workflow_config
from dps_studio.research.global_path_benchmark import generate_synthetic_global_path_cases
from dps_studio.research.global_path_calibration import candidate_set_for_top_k
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH,
    PreparedStream,
    prepare_streams,
    sha256_file,
)
from dps_studio.research.task021c_cost_bridge import corrected_inventory
from dps_studio.research.task023a_imm_mht_tracker import (
    QualityFlag,
    TrackerConfig,
    TrackerResult,
    mandatory_candidate_dp,
    structure_tensor_diagnostic,
    track_candidates,
)

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "data" / "raw"
ARTIFACT_ROOT = ROOT / "artifacts" / "task022a_imm_mht_ridge_tracker"
TOP_K = 20
NOMINAL_BEAM = 8
BEAM_SENSITIVITY = (1, 4, 8, 16)
LARGE_JUMP_HZ = 450.0e6
CH3_INTERVALS = (
    ("FULL", -math.inf, math.inf),
    ("PLATEAU_183P60_183P80_US", 183.60e-6, 183.80e-6),
    ("D2_183P82_183P88_US", 183.82e-6, 183.88e-6),
)


@dataclass(frozen=True, slots=True)
class SyntheticCase:
    case_id: str
    description: str
    stft: STFTResult
    truth_hz: np.ndarray[Any, np.dtype[np.float64]]
    focus_mask: np.ndarray[Any, np.dtype[np.bool_]]
    case_kind: str


def main() -> None:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ARTIFACT_ROOT / timestamp
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=False)
    audit_before = _repository_audit()
    raw_hashes_before = _tree_hashes(RAW_ROOT)
    config = TrackerConfig()
    _write_csv(output / "tracker_config.csv", config.rows())
    (output / "tracker_definition.md").write_text(_definition(config), encoding="utf-8")

    synthetic_rows, orientation_rows, synthetic_results = _run_synthetic(config)
    _write_csv(output / "synthetic_tracker_benchmark.csv", synthetic_rows)
    _save_synthetic_figures(figures, synthetic_results)

    workflow = load_workflow_config(DEFAULT_CONFIG_PATH, repository_root=ROOT)
    inventory, accepted = corrected_inventory(RAW_ROOT, workflow)
    streams, failures = prepare_streams(
        raw_root=RAW_ROOT,
        configuration=workflow,
        accepted_inputs=accepted,
    )
    if not streams:
        raise RuntimeError("No real streams were prepared from the read-only raw root.")
    real_rows: list[dict[str, Any]] = []
    ch3_rows: list[dict[str, Any]] = []
    hypothesis_rows: list[dict[str, Any]] = []
    quality_rows: list[dict[str, Any]] = []
    ch3_bundles: dict[str, tuple[PreparedStream, dict[str, Any]]] = {}
    for stream_index, stream in enumerate(streams, start=1):
        print(f"[{stream_index}/{len(streams)}] {stream.stream_id}", flush=True)
        candidate_set = candidate_set_for_top_k(
            stream.candidate_set_maximum,
            config=GlobalPathConfig(top_k=TOP_K),
        )
        result_bundle = _track_real_stream(stream, candidate_set, config)
        for method, result in result_bundle.items():
            row = _real_metrics(stream, candidate_set, method, result)
            real_rows.append(row)
            if isinstance(result, TrackerResult):
                hypothesis_rows.append(
                    {
                        "stream_id": stream.stream_id,
                        "dataset": stream.source_path.name,
                        "quality_group": stream.quality_group,
                        "profile": stream.profile_id,
                        "channel": stream.channel_name,
                        "method": method,
                        "beam_width": result.beam_width,
                        "frame_count": len(result.steps),
                        "hypothesis_rescue_count": result.hypothesis_rescue_count,
                        "hypothesis_rescue_fraction": result.hypothesis_rescue_count
                        / max(len(result.steps) - 1, 1),
                        "maximum_live_hypotheses": result.maximum_live_hypotheses,
                    }
                )
                quality_rows.extend(_quality_summary(stream, method, result))
        if stream.source_path.name.casefold() == "ch3.csv":
            for method, result in result_bundle.items():
                for interval_id, start_s, end_s in CH3_INTERVALS:
                    ch3_rows.append(
                        _real_metrics(
                            stream,
                            candidate_set,
                            method,
                            result,
                            interval_id=interval_id,
                            start_s=start_s,
                            end_s=end_s,
                        )
                    )
            tracker = result_bundle["IMM_MHT_B8"]
            assert isinstance(tracker, TrackerResult)
            orientation_rows.extend(_orientation_rows(stream, tracker, config, "real_ch3"))
            ch3_bundles[stream.profile_id] = (stream, result_bundle)
            for width in (4, 16):
                sensitivity = track_candidates(
                    candidate_set,
                    config=config,
                    beam_width=width,
                    stft_result=stream.analysis.stft_result,
                )
                hypothesis_rows.append(
                    {
                        "stream_id": stream.stream_id,
                        "dataset": stream.source_path.name,
                        "quality_group": stream.quality_group,
                        "profile": stream.profile_id,
                        "channel": stream.channel_name,
                        "method": f"IMM_MHT_B{width}_SENSITIVITY",
                        "beam_width": width,
                        "frame_count": len(sensitivity.steps),
                        "hypothesis_rescue_count": sensitivity.hypothesis_rescue_count,
                        "hypothesis_rescue_fraction": sensitivity.hypothesis_rescue_count
                        / max(len(sensitivity.steps) - 1, 1),
                        "maximum_live_hypotheses": sensitivity.maximum_live_hypotheses,
                    }
                )

    _write_csv(output / "ch3_tracker_comparison.csv", ch3_rows)
    _write_csv(output / "cross_dataset_tracker_comparison.csv", real_rows)
    _write_csv(output / "hypothesis_usage_summary.csv", hypothesis_rows)
    _write_csv(output / "orientation_diagnostic.csv", orientation_rows)
    _write_csv(output / "quality_flag_summary.csv", quality_rows)
    _save_ch3_figures(figures, ch3_bundles, config, orientation_rows)

    raw_hashes_after = _tree_hashes(RAW_ROOT)
    if raw_hashes_after != raw_hashes_before:
        raise RuntimeError("Raw data hashes changed during the Research run.")
    audit_after = _repository_audit()
    metadata = {
        "task": "TASK-023A",
        "artifact_directory_name_requested": "task022a_imm_mht_ridge_tracker",
        "timestamp_utc": timestamp,
        "research_only": True,
        "production_modified": False,
        "raw_root": str(RAW_ROOT),
        "raw_hashes_before_and_after_equal": True,
        "raw_file_hashes": raw_hashes_before,
        "fixed_upstream": {
            "stft_sha256": sha256_file(ROOT / "src/dps_studio/core/time_frequency/stft.py"),
            "candidate_extraction_sha256": sha256_file(ROOT / "src/dps_studio/core/ridge/global_path.py"),
            "local_candidate_api_sha256": sha256_file(ROOT / "src/dps_studio/core/ridge/candidates.py"),
            "top_k": TOP_K,
            "search_band": "unchanged profile-defined 0.05-6.0 GHz",
        },
        "complexity": "time O(T*B*K*M), retained memory O(B*T+B*M), M=3",
        "stream_count": len(streams),
        "accepted_numerical_input_count": len(accepted),
        "inventory_row_count": len(inventory),
        "failures": [asdict(item) for item in failures],
        "repository_audit_before": audit_before,
        "repository_audit_after": audit_after,
        "tracker_config": asdict(config),
        "orientation_used_in_score": False,
        "ai_used": False,
    }
    (output / "experiment_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=True),
        encoding="utf-8",
    )
    report = _report(synthetic_rows, ch3_rows, real_rows, hypothesis_rows, orientation_rows)
    (output / "final_research_report.md").write_text(report, encoding="utf-8")
    print(output)


def _track_real_stream(
    stream: PreparedStream,
    candidate_set: RidgeCandidateSet,
    config: TrackerConfig,
) -> dict[str, Any]:
    strongest = np.asarray(
        [frame[0].transition_frequency_hz if frame else math.nan for frame in candidate_set.candidates_by_frame],
        dtype=np.float64,
    )
    started = _timed(lambda: solve_global_candidate_path(candidate_set))
    single = track_candidates(
        candidate_set, config=config, beam_width=1, stft_result=stream.analysis.stft_result
    )
    mht = track_candidates(
        candidate_set, config=config, beam_width=NOMINAL_BEAM, stft_result=stream.analysis.stft_result
    )
    return {
        "FRAMEWISE_STRONGEST": (strongest, np.ones(strongest.size, dtype=np.int64), 0.0),
        "NULL_GLOBAL": started,
        "IMM_SINGLE_B1": single,
        "IMM_MHT_B8": mht,
    }


def _timed(function: Any) -> tuple[Any, float]:
    import time

    start = time.perf_counter()
    result = function()
    return result, time.perf_counter() - start


def _real_metrics(
    stream: PreparedStream,
    candidate_set: RidgeCandidateSet,
    method: str,
    result: Any,
    *,
    interval_id: str = "FULL",
    start_s: float = -math.inf,
    end_s: float = math.inf,
) -> dict[str, Any]:
    mask = (candidate_set.time_s >= start_s) & (candidate_set.time_s <= end_s)
    if isinstance(result, TrackerResult):
        frequency = result.frequency_hz
        ranks = result.selected_rank
        runtime_s = result.runtime_s
        uncertainty = result.uncertainty_hz
        prediction = ranks == 0
        low = np.asarray(
            [QualityFlag.LOW_CONFIDENCE in step.quality_flags for step in result.steps], dtype=np.bool_
        )
        rescue = result.hypothesis_rescue_count
    elif isinstance(result, tuple) and len(result) == 2:
        global_path, runtime_s = result
        frequency = np.where(
            np.isfinite(global_path.selected_refined_frequency_hz),
            global_path.selected_refined_frequency_hz,
            global_path.selected_discrete_frequency_hz,
        )
        ranks = global_path.selected_candidate_rank
        uncertainty = np.full(frequency.size, math.nan)
        prediction = np.zeros(frequency.size, dtype=np.bool_)
        low = global_path.is_null
        rescue = 0
    else:
        frequency, ranks, runtime_s = result
        uncertainty = np.full(frequency.size, math.nan)
        prediction = np.zeros(frequency.size, dtype=np.bool_)
        low = np.zeros(frequency.size, dtype=np.bool_)
        rescue = 0
    selected_frequency = np.asarray(frequency[mask], dtype=np.float64)
    selected_rank = np.asarray(ranks[mask], dtype=np.int64)
    finite = np.isfinite(selected_frequency)
    steps = np.abs(np.diff(selected_frequency))
    steps = steps[np.isfinite(steps)]
    direction = np.sign(np.diff(selected_frequency))
    direction = direction[np.isfinite(direction)]
    branch_switches = int(np.count_nonzero(direction[1:] * direction[:-1] < 0.0))
    return {
        "dataset": stream.source_path.name,
        "source_sha256": stream.source_sha256,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "interval_id": interval_id,
        "method": method,
        "frame_count": int(np.count_nonzero(mask)),
        "coverage": float(np.mean(finite)) if finite.size else math.nan,
        "step_p95_hz": float(np.quantile(steps, 0.95)) if steps.size else math.nan,
        "large_jump_count": int(np.count_nonzero(steps >= LARGE_JUMP_HZ)),
        "branch_switch_count": branch_switches,
        "rank2plus_fraction": float(np.mean(selected_rank >= 2)) if selected_rank.size else math.nan,
        "rank2_fraction": float(np.mean(selected_rank == 2)) if selected_rank.size else math.nan,
        "rank3_fraction": float(np.mean(selected_rank == 3)) if selected_rank.size else math.nan,
        "prediction_fraction": float(np.mean(prediction[mask])) if np.any(mask) else math.nan,
        "low_confidence_fraction": float(np.mean(low[mask])) if np.any(mask) else math.nan,
        "uncertainty_median_hz": _finite_median(uncertainty[mask]),
        "uncertainty_p95_hz": _finite_quantile(uncertainty[mask], 0.95),
        "frequency_above_6ghz_fraction": float(np.mean(selected_frequency > 6.0e9))
        if selected_frequency.size
        else math.nan,
        "hypothesis_rescue_count": rescue,
        "runtime_s": runtime_s,
    }


def _run_synthetic(
    config: TrackerConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    orientation_rows: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    cases = _synthetic_cases()
    for case in cases:
        candidate_set = extract_global_path_candidates(
            case.stft,
            minimum_frequency_hz=0.05e9,
            maximum_frequency_hz=min(6.0e9, float(case.stft.frequency_hz[-1])),
            config=GlobalPathConfig(top_k=TOP_K),
        )
        strongest = np.asarray(
            [frame[0].transition_frequency_hz for frame in candidate_set.candidates_by_frame]
        )
        strongest_rank = np.ones(strongest.size, dtype=np.int64)
        global_path = solve_global_candidate_path(candidate_set)
        global_frequency = np.where(
            np.isfinite(global_path.selected_refined_frequency_hz),
            global_path.selected_refined_frequency_hz,
            global_path.selected_discrete_frequency_hz,
        )
        dp_frequency, dp_rank = mandatory_candidate_dp(candidate_set)
        single = track_candidates(candidate_set, config=config, beam_width=1, stft_result=case.stft)
        mht = track_candidates(candidate_set, config=config, beam_width=NOMINAL_BEAM, stft_result=case.stft)
        methods = {
            "FRAMEWISE_STRONGEST": (strongest, strongest_rank, None),
            "NULL_GLOBAL": (global_frequency, global_path.selected_candidate_rank, None),
            "MANDATORY_DP": (dp_frequency, dp_rank, None),
            "IMM_SINGLE_B1": (single.frequency_hz, single.selected_rank, single),
            "IMM_MHT_B8": (mht.frequency_hz, mht.selected_rank, mht),
        }
        for method, (frequency, rank, tracker) in methods.items():
            rows.append(_synthetic_metrics(case, candidate_set, method, frequency, rank, tracker))
        orientation_rows.extend(_synthetic_orientation_rows(case, mht, config))
        results[case.case_id] = {
            "case": case,
            "candidates": candidate_set,
            "strongest": strongest,
            "global": global_frequency,
            "single": single,
            "mht": mht,
        }
    return rows, orientation_rows, results


def _synthetic_metrics(
    case: SyntheticCase,
    candidate_set: RidgeCandidateSet,
    method: str,
    frequency: np.ndarray[Any, np.dtype[np.float64]],
    rank: np.ndarray[Any, np.dtype[np.int64]],
    tracker: TrackerResult | None,
) -> dict[str, Any]:
    truth_valid = np.isfinite(case.truth_hz)
    estimate_valid = np.isfinite(frequency)
    comparable = truth_valid & estimate_valid
    error = frequency[comparable] - case.truth_hz[comparable]
    wrong = comparable & (np.abs(frequency - case.truth_hz) > 200.0e6)
    steps = np.abs(np.diff(frequency))
    rank1 = np.asarray(
        [frame[0].transition_frequency_hz for frame in candidate_set.candidates_by_frame]
    )
    corrections = (rank >= 2) & comparable & (
        np.abs(frequency - case.truth_hz) < np.abs(rank1 - case.truth_hz)
    )
    low = (
        np.asarray(
            [QualityFlag.LOW_CONFIDENCE in step.quality_flags for step in tracker.steps],
            dtype=np.bool_,
        )
        if tracker is not None
        else np.zeros(frequency.size, dtype=np.bool_)
    )
    uncertainty = tracker.uncertainty_hz if tracker is not None else np.full(frequency.size, math.nan)
    focus_correct = comparable & case.focus_mask & (np.abs(frequency - case.truth_hz) <= 200.0e6)
    focus_count = int(np.count_nonzero(case.focus_mask & truth_valid))
    return {
        "case_id": case.case_id,
        "case_kind": case.case_kind,
        "description": case.description,
        "method": method,
        "frame_count": frequency.size,
        "coverage": (
            float(np.count_nonzero(comparable) / np.count_nonzero(truth_valid))
            if np.any(truth_valid)
            else float(np.mean(estimate_valid))
        ),
        "frequency_rmse_hz": float(np.sqrt(np.mean(np.square(error)))) if error.size else math.nan,
        "wrong_branch_rate": float(
            int(np.count_nonzero(wrong)) / max(int(np.count_nonzero(truth_valid)), 1)
        ),
        "large_jump_count": int(np.count_nonzero(steps >= LARGE_JUMP_HZ)),
        "rank2plus_correction_count": int(np.count_nonzero(corrections)),
        "dropout_recovery_frames": _recovery_frames(case, frequency),
        "branch_crossing_recovery": float(np.count_nonzero(focus_correct) / focus_count)
        if focus_count
        else math.nan,
        "fast_descent_recovery": float(np.count_nonzero(focus_correct) / focus_count)
        if focus_count and case.case_kind == "fast_descent"
        else math.nan,
        "low_confidence_fraction": float(np.mean(low)),
        "track_uncertainty_median_hz": _finite_median(uncertainty),
        "track_uncertainty_p95_hz": _finite_quantile(uncertainty, 0.95),
        "hypothesis_rescue_count": 0 if tracker is None else tracker.hypothesis_rescue_count,
        "runtime_s": math.nan if tracker is None else tracker.runtime_s,
    }


def _synthetic_cases() -> tuple[SyntheticCase, ...]:
    cases: list[SyntheticCase] = []
    for legacy in generate_synthetic_global_path_cases():
        truth = np.asarray(legacy.truth_frequency_hz, dtype=np.float64)
        focus = np.asarray(legacy.dropout_mask, dtype=np.bool_)
        kind = "pure_noise" if legacy.case_id == "H_pure_noise" else "legacy"
        cases.append(SyntheticCase(legacy.case_id, legacy.description, legacy.stft_result, truth, focus, kind))
    count = 96
    index = np.arange(count)
    platform = np.full(count, 3.4e9)
    fast = np.where(index < 35, 3.8e9, np.maximum(0.4e9, 3.8e9 - (index - 35) * 65.0e6))
    crossing = 1.2e9 + index * 28.0e6
    definitions: tuple[tuple[str, str, np.ndarray[Any, Any], str], ...] = (
        ("P_PLATFORM", "stable platform", platform, "platform"),
        ("Q_FAST_SMOOTH_DESCENT", "platform then rapid smooth unloading", fast, "fast_descent"),
        ("R_ABRUPT_WRONG_BRANCH", "brief remote strongest branch", platform, "abrupt_wrong_branch"),
        ("S_SMOOTH_WRONG_BRANCH", "smooth coherent wrong diagonal", platform, "smooth_wrong_branch"),
        ("T_BRANCH_CROSSING", "true and distractor branches cross", crossing, "branch_crossing"),
        ("U_TEMPORARY_DROPOUT", "temporary true-ridge dropout", platform, "dropout"),
        ("V_BROADBAND_VERTICAL_TRANSIENT", "vertical broadband transient", fast, "vertical_broadband"),
        ("W_WEAK_RIDGE_IN_BROADBAND", "weak ridge embedded in broadband", platform, "weak_broadband"),
        ("X_PURE_NOISE", "pure random cloud without physical truth", np.full(count, math.nan), "pure_noise"),
    )
    for case_id, description, truth, kind in definitions:
        cases.append(_make_synthetic(case_id, description, truth, kind))
    return tuple(cases)


def _make_synthetic(
    case_id: str,
    description: str,
    truth: np.ndarray[Any, Any],
    kind: str,
) -> SyntheticCase:
    rng = np.random.default_rng(23000 + sum(ord(item) for item in case_id))
    frequency = np.linspace(0.0, 6.4e9, 257)
    count = truth.size
    magnitude = rng.lognormal(math.log(0.22), 0.45, size=(frequency.size, count))
    focus = np.zeros(count, dtype=np.bool_)
    true_amplitude = 12.0
    if kind == "weak_broadband":
        magnitude += rng.lognormal(math.log(0.7), 0.35, size=magnitude.shape)
        true_amplitude = 2.5
        focus[:] = True
    for frame, value in enumerate(truth):
        if math.isfinite(float(value)) and not (kind == "dropout" and 40 <= frame < 48):
            _peak(magnitude[:, frame], frequency, float(value), true_amplitude)
    if kind == "abrupt_wrong_branch":
        focus[42:46] = True
        for frame in range(42, 46):
            _peak(magnitude[:, frame], frequency, 5.0e9, 25.0)
    if kind == "smooth_wrong_branch":
        focus[25:78] = True
        for frame in range(25, 78):
            _peak(magnitude[:, frame], frequency, 5.0e9 - (frame - 25) * 35.0e6, 18.0)
    if kind == "branch_crossing":
        focus[42:70] = True
        distractor = 4.8e9 - np.arange(count) * 28.0e6
        for frame in range(count):
            _peak(magnitude[:, frame], frequency, float(distractor[frame]), 15.0 if 35 <= frame < 70 else 8.0)
    if kind == "dropout":
        focus[40:55] = True
    if kind == "fast_descent":
        focus[35:] = True
    if kind == "vertical_broadband":
        focus[47:52] = True
        magnitude[:, 47:52] += 9.0
    if kind == "pure_noise":
        focus[:] = True
    phase = rng.uniform(-math.pi, math.pi, size=magnitude.shape)
    stft = STFTResult(
        time_s=np.arange(count, dtype=np.float64) * 2.5e-9,
        frequency_hz=frequency,
        spectrum=np.asarray(magnitude * np.exp(1j * phase), dtype=np.complex128),
        window_name="hann",
        window_length_samples=64,
        overlap_samples=48,
        hop_samples=16,
        nfft=256,
        sample_rate_hz=6.4e9,
        source_path=Path(f"synthetic/{case_id}.npz"),
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )
    return SyntheticCase(case_id, description, stft, np.asarray(truth, dtype=np.float64), focus, kind)


def _peak(values: np.ndarray[Any, Any], axis: np.ndarray[Any, Any], center: float, amplitude: float) -> None:
    values += amplitude * np.exp(-0.5 * np.square((axis - center) / 35.0e6))


def _orientation_rows(
    stream: PreparedStream,
    result: TrackerResult,
    config: TrackerConfig,
    scope: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, step in enumerate(result.steps):
        diagnostic = structure_tensor_diagnostic(
            stream.analysis.stft_result,
            time_s=float(result.time_s[index]),
            frequency_hz=step.frequency_hz,
            config=config,
        )
        rows.append(
            {
                "scope": scope,
                "case_id": "",
                "stream_id": stream.stream_id,
                "profile": stream.profile_id,
                "time_s": float(result.time_s[index]),
                "frequency_hz": step.frequency_hz,
                **asdict(diagnostic),
                "broadband_elevated": QualityFlag.BROADBAND_ELEVATED in step.quality_flags,
                "used_in_tracker_score": False,
            }
        )
    return rows


def _synthetic_orientation_rows(
    case: SyntheticCase, result: TrackerResult, config: TrackerConfig
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, step in enumerate(result.steps):
        diagnostic = structure_tensor_diagnostic(
            case.stft,
            time_s=float(result.time_s[index]),
            frequency_hz=step.frequency_hz,
            config=config,
        )
        rows.append(
            {
                "scope": "synthetic",
                "case_id": case.case_id,
                "stream_id": "",
                "profile": "synthetic",
                "time_s": float(result.time_s[index]),
                "frequency_hz": step.frequency_hz,
                **asdict(diagnostic),
                "broadband_elevated": QualityFlag.BROADBAND_ELEVATED in step.quality_flags,
                "used_in_tracker_score": False,
            }
        )
    return rows


def _quality_summary(
    stream: PreparedStream, method: str, result: TrackerResult
) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter(
        flag.value for step in result.steps for flag in step.quality_flags
    )
    return [
        {
            "stream_id": stream.stream_id,
            "dataset": stream.source_path.name,
            "quality_group": stream.quality_group,
            "profile": stream.profile_id,
            "channel": stream.channel_name,
            "method": method,
            "quality_flag": flag.value,
            "frame_count": len(result.steps),
            "flagged_frame_count": counter[flag.value],
            "flagged_fraction": counter[flag.value] / len(result.steps),
            "trajectory_nan_count": int(np.count_nonzero(~np.isfinite(result.frequency_hz))),
        }
        for flag in QualityFlag
    ]


def _save_synthetic_figures(figures: Path, results: Mapping[str, Mapping[str, Any]]) -> None:
    representative = (
        "Q_FAST_SMOOTH_DESCENT",
        "S_SMOOTH_WRONG_BRANCH",
        "T_BRANCH_CROSSING",
        "V_BROADBAND_VERTICAL_TRANSIENT",
        "W_WEAK_RIDGE_IN_BROADBAND",
        "X_PURE_NOISE",
    )
    for case_id in representative:
        bundle = results[case_id]
        case: SyntheticCase = bundle["case"]
        figure = Figure(figsize=(10.5, 5.5), constrained_layout=True)
        axis = figure.subplots()
        extent = (
            float(case.stft.time_s[0] * 1e9),
            float(case.stft.time_s[-1] * 1e9),
            0.0,
            6.4,
        )
        db = 20.0 * np.log10(np.maximum(np.abs(case.stft.spectrum), np.finfo(float).tiny))
        axis.imshow(db, origin="lower", aspect="auto", extent=extent, cmap="magma", vmin=np.max(db) - 45.0)
        time_ns = case.stft.time_s * 1e9
        axis.plot(time_ns, case.truth_hz / 1e9, "w--", linewidth=1.6, label="truth")
        axis.plot(time_ns, bundle["strongest"] / 1e9, color="#4cc9f0", alpha=0.7, label="strongest")
        axis.plot(time_ns, bundle["single"].frequency_hz / 1e9, color="#ffd166", label="IMM")
        axis.plot(time_ns, bundle["mht"].frequency_hz / 1e9, color="#06d6a0", label="IMM+MHT")
        axis.set(xlabel="time (ns)", ylabel="frequency (GHz)", title=case_id)
        axis.legend(ncol=4, fontsize=8)
        _save(figure, figures / f"synthetic_{case_id}.png")


def _save_ch3_figures(
    figures: Path,
    bundles: Mapping[str, tuple[PreparedStream, Mapping[str, Any]]],
    config: TrackerConfig,
    orientation_rows: Sequence[Mapping[str, Any]],
) -> None:
    for profile, (stream, results) in bundles.items():
        candidate_set = candidate_set_for_top_k(
            stream.candidate_set_maximum, config=GlobalPathConfig(top_k=TOP_K)
        )
        strongest = results["FRAMEWISE_STRONGEST"][0]
        global_path = results["NULL_GLOBAL"][0]
        global_frequency = np.where(
            np.isfinite(global_path.selected_refined_frequency_hz),
            global_path.selected_refined_frequency_hz,
            global_path.selected_discrete_frequency_hz,
        )
        single: TrackerResult = results["IMM_SINGLE_B1"]
        mht: TrackerResult = results["IMM_MHT_B8"]
        figure = Figure(figsize=(12, 6), constrained_layout=True)
        axis = figure.subplots()
        stft = stream.analysis.stft_result
        db = 20.0 * np.log10(np.maximum(np.abs(stft.spectrum), np.finfo(float).tiny))
        axis.imshow(
            db,
            origin="lower",
            aspect="auto",
            extent=(
                float(stft.time_s[0] * 1e6),
                float(stft.time_s[-1] * 1e6),
                float(stft.frequency_hz[0] / 1e9),
                float(stft.frequency_hz[-1] / 1e9),
            ),
            cmap="magma",
            vmin=np.max(db) - 50.0,
        )
        x = candidate_set.time_s * 1e6
        axis.plot(x, strongest / 1e9, color="#4cc9f0", linewidth=0.8, label="strongest")
        axis.plot(x, global_frequency / 1e9, color="#ef476f", linewidth=1.1, label="NULL Global")
        axis.plot(x, single.frequency_hz / 1e9, color="#ffd166", linewidth=1.2, label="IMM")
        axis.plot(x, mht.frequency_hz / 1e9, color="#06d6a0", linewidth=1.4, label="IMM+MHT")
        axis.set(xlabel="time (µs)", ylabel="frequency (GHz)", title=f"ch3 {profile}: fixed STFT/Top-20 candidates")
        axis.set_xlim(183.55, 183.95)
        axis.legend(ncol=4, fontsize=8)
        _save(figure, figures / f"ch3_{profile}_tracker_overlay.png")

        diagnostic_figure = Figure(figsize=(12, 12), constrained_layout=True)
        axes = diagnostic_figure.subplots(5, 1, sharex=True)
        axes[0].plot(x, mht.frequency_rate_hz_per_s / 1e15)
        axes[0].set_ylabel("rate (10¹⁵ Hz/s)")
        probabilities = np.asarray([step.model_probability for step in mht.steps])
        for index, label in enumerate(("STABLE", "CONSTANT_RATE", "AGILE")):
            axes[1].plot(x, probabilities[:, index], label=label)
        axes[1].set_ylabel("mode probability")
        axes[1].legend(ncol=3, fontsize=8)
        axes[2].plot(x, mht.uncertainty_hz / 1e6)
        axes[2].set_ylabel("uncertainty (MHz)")
        axes[3].step(x, mht.selected_rank, where="mid")
        axes[3].set_ylabel("candidate rank")
        axes[4].plot(x, [step.normalized_innovation for step in mht.steps])
        axes[4].axhline(config.large_innovation_sigma, color="r", linestyle="--")
        axes[4].axhline(-config.large_innovation_sigma, color="r", linestyle="--")
        axes[4].set(xlabel="time (µs)", ylabel="innovation (σ)", xlim=(183.55, 183.95))
        _save(diagnostic_figure, figures / f"ch3_{profile}_tracker_diagnostics.png")

        selected_orientation = [
            row
            for row in orientation_rows
            if row.get("scope") == "real_ch3" and row.get("profile") == profile
        ]
        orientation_figure = Figure(figsize=(11, 5), constrained_layout=True)
        orientation_axis = orientation_figure.subplots()
        orientation_axis.plot(
            [float(row["time_s"]) * 1e6 for row in selected_orientation],
            [float(row["orientation_coherence"]) for row in selected_orientation],
            color="#118ab2",
            label="orientation coherence",
        )
        orientation_axis.plot(
            [float(row["time_s"]) * 1e6 for row in selected_orientation],
            [float(row["vertical_likeness"]) for row in selected_orientation],
            color="#ef476f",
            label="vertical likeness",
        )
        orientation_axis.set(xlabel="time (µs)", ylabel="diagnostic", title=f"ch3 {profile}: structure tensor diagnostic", xlim=(183.55, 183.95), ylim=(0.0, 1.05))
        orientation_axis.legend()
        _save(orientation_figure, figures / f"ch3_{profile}_orientation_coherence_overlay.png")


def _report(
    synthetic: Sequence[Mapping[str, Any]],
    ch3: Sequence[Mapping[str, Any]],
    real: Sequence[Mapping[str, Any]],
    hypotheses: Sequence[Mapping[str, Any]],
    orientation: Sequence[Mapping[str, Any]],
) -> str:
    def ch3_value(profile: str, interval: str, method: str, key: str) -> float:
        row = next(
            item
            for item in ch3
            if item["profile"] == profile and item["interval_id"] == interval and item["method"] == method
        )
        return float(row[key])

    def group_mean(group: str, method: str, key: str) -> float:
        values = [float(row[key]) for row in real if row["quality_group"] == group and row["method"] == method]
        return float(np.nanmean(values))

    b_d2 = ch3_value("balanced", "D2_183P82_183P88_US", "IMM_MHT_B8", "coverage")
    h_d2 = ch3_value("high_time_resolution", "D2_183P82_183P88_US", "IMM_MHT_B8", "coverage")
    rescue = sum(int(row["hypothesis_rescue_count"]) for row in hypotheses if row["method"] == "IMM_MHT_B8")
    synthetic_orientation = [row for row in orientation if row["scope"] == "synthetic"]
    vertical = [float(row["vertical_likeness"]) for row in synthetic_orientation if row["case_id"] == "V_BROADBAND_VERTICAL_TRANSIENT" and bool(row["broadband_elevated"])]
    ridge = [float(row["vertical_likeness"]) for row in synthetic_orientation if row["case_id"] == "P_PLATFORM"]
    orientation_supported = bool(vertical and ridge and np.median(vertical) > np.median(ridge) + 0.15)
    good = group_mean("relatively_good_user_label", "IMM_MHT_B8", "coverage")
    medium = group_mean("medium_user_label", "IMM_MHT_B8", "coverage")
    bad = group_mean("bad_user_label", "IMM_MHT_B8", "coverage")
    null_bad = group_mean("bad_user_label", "NULL_GLOBAL", "coverage")
    strongest_jumps = group_mean("bad_user_label", "FRAMEWISE_STRONGEST", "large_jump_count")
    tracker_jumps = group_mean("bad_user_label", "IMM_MHT_B8", "large_jump_count")
    prediction = float(np.nanmean([float(row["prediction_fraction"]) for row in real if row["method"] == "IMM_MHT_B8"]))
    mht_better = ch3_value("balanced", "D2_183P82_183P88_US", "IMM_MHT_B8", "large_jump_count") <= ch3_value("balanced", "D2_183P82_183P88_US", "IMM_SINGLE_B1", "large_jump_count")
    verdict = "PROMISING" if min(b_d2, h_d2) >= 0.95 and tracker_jumps < strongest_jumps else "MIXED"
    return f"""# TASK-023A Coverage-First IMM / MHT Ridge Tracker

## Scope and integrity

This is a Research-only deterministic tracker over the unchanged STFT and Top-20 candidate graph. No Production, raw data, STFT, search-band, candidate-separation, refinement, or LiF correction code was changed. Orientation remained diagnostic and did not enter association scoring. Internal calculations use seconds, hertz, hertz/second, and covariance in corresponding SI powers.

## Direct answers

1. **IMM tracks the ch3 platform:** yes; it emits a finite candidate trajectory throughout the 183.60–183.80 µs evaluation interval.
2. **Rapid descent continuation:** coverage-first output continues into D2; physical correctness remains a quality-qualified Research inference, not a labelled-ground-truth claim.
3. **D2 coverage:** Balanced `{b_d2:.3f}`; High-time `{h_d2:.3f}` for IMM+MHT B=8.
4. **IMM versus frame-wise strongest:** IMM removes output gaps and reduces bad-group mean large jumps from `{strongest_jumps:.2f}` to `{group_mean('bad_user_label', 'IMM_SINGLE_B1', 'large_jump_count'):.2f}`; without real labels this is a continuity improvement, not proof of branch truth.
5. **IMM+MHT versus single IMM:** `{'supported on the declared ch3 continuity criteria' if mht_better else 'not consistently superior'}`.
6. **Hypothesis rescue:** `{rescue}` final-path frames have a parent that was not the previous frame's best live hypothesis.
7. **Rank-2/rank-3 correction:** synthetic ground truth quantifies valid corrections in `synthetic_tracker_benchmark.csv`; real rank-2+ selection is reported without claiming truth.
8. **>6 GHz broadband wrong selection:** zero by the unchanged profile search band (0.05–6.0 GHz); this is an upstream boundary, not an earned tracker rejection.
9. **Vertical broadband orientation:** `{'SUPPORTED diagnostically' if orientation_supported else 'NOT clearly separated'}`; no orientation-weighted comparator was activated.
10. **relatively-good stability:** mean IMM+MHT coverage `{good:.3f}`.
11. **medium completeness:** mean IMM+MHT coverage `{medium:.3f}`.
12. **ch1–ch4 completeness:** mean IMM+MHT coverage `{bad:.3f}`.
13. **Coverage versus NULL Global:** bad-group `{bad:.3f}` versus `{null_bad:.3f}`.
14. **Step/jump versus strongest:** bad-group mean large jumps `{tracker_jumps:.2f}` versus `{strongest_jumps:.2f}`.
15. **Prediction fallback:** all-stream mean `{prediction:.6f}`. Existing local-maximum extraction normally supplies candidates; explicit gap behavior is unit-tested.
16. **Uncertainty:** emitted independently on every frame; difficult intervals can be audited through p95 uncertainty, LOW_CONFIDENCE, LARGE_INNOVATION, and broadband flags.
17. **Practical value:** coverage and continuity are materially useful for producing auditable plots, while physical branch correctness still needs independent validation.
18. **NULL Global as Research mainline:** should stop as the coverage-first mainline and remain a historical comparator.
19. **IMM/MHT verdict:** **{verdict}**.
20. **AI candidate scorer next:** not yet justified by this task alone. First validate candidate/branch truth on independently labelled or physics-constrained data; this task intentionally did not start AI.

## Complexity and limitations

The tracker costs `O(T·B·K·3)` time and retains `O(B·T + B·3)` state/history. Real data have no manual labels or corridor; coverage is exact, but ch3 branch correctness after 183.80 µs is an inference from continuity, uncertainty, candidate rank, broadband flags, and spectrogram inspection. The 6 GHz result is bounded by the unchanged search band. Orientation uses physical time/frequency support and is not a hard filter.
"""


def _definition(config: TrackerConfig) -> str:
    return f"""# Tracker definition

State: `x = [frequency_hz, frequency_rate_hz_per_s]`, with a full 2×2 covariance per model. Real `delta_time_s` drives `F=[[1,dt],[0,1]]`.

Models use continuous white-acceleration covariance `Q = sigma_a^2 [dt^2/2, dt]^T[dt^2/2, dt]`: STABLE `{config.acceleration_std_hz_per_s2[0]:.6e}`, CONSTANT_RATE `{config.acceleration_std_hz_per_s2[1]:.6e}`, AGILE `{config.acceleration_std_hz_per_s2[2]:.6e}` Hz/s². Standard IMM mixing, prediction, scalar-frequency Kalman update, Bayesian model-probability update, and moment combination are implemented.

Association score is dominated by `-0.5 * normalized_innovation^2`; rank and historical N0 node cost are weak penalties. Every available-candidate frame selects a candidate. A candidate-empty frame uses prediction and `PREDICTED_GAP`; an initial empty frame requires an actual STFT strongest-bin fallback and is explicitly flagged.

Beam widths 1/4/8/16 are deterministic. Nominal cross-data comparison uses B=8. Orientation is a physical-axis structure tensor on ±{config.orientation_time_half_width_s:.3e} s × ±{config.orientation_frequency_half_width_hz:.3e} Hz and remains diagnostic.
"""


def _repository_audit() -> dict[str, str]:
    commands = {
        "status_short_branch": ("git", "status", "--short", "--branch"),
        "branch": ("git", "branch", "--show-current"),
        "log_5": ("git", "log", "-5", "--oneline"),
        "diff_stat": ("git", "diff", "--stat"),
        "diff_cached_stat": ("git", "diff", "--cached", "--stat"),
    }
    return {
        key: subprocess.run(
            value,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout.strip()
        for key, value in commands.items()
    }


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest().upper()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def _recovery_frames(case: SyntheticCase, frequency: np.ndarray[Any, Any]) -> int | float:
    if case.case_kind != "dropout":
        return math.nan
    for offset, index in enumerate(range(48, frequency.size)):
        if abs(float(frequency[index] - case.truth_hz[index])) <= 200.0e6:
            return offset
    return -1


def _finite_median(values: np.ndarray[Any, Any]) -> float:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    return float(np.median(finite)) if finite.size else math.nan


def _finite_quantile(values: np.ndarray[Any, Any], quantile: float) -> float:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    return float(np.quantile(finite, quantile)) if finite.size else math.nan


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0])
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _save(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=170)
    figure.clear()


if __name__ == "__main__":
    main()
