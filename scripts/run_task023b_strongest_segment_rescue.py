"""Run TASK-023B strongest-first local segment rescue research."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import time
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
from dps_studio.research.global_path_calibration import candidate_set_for_top_k
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH,
    PreparedStream,
    prepare_streams,
    sha256_file,
)
from dps_studio.research.task021c_cost_bridge import corrected_inventory
from dps_studio.research.task023a_imm_mht_tracker import TrackerConfig, track_candidates
from dps_studio.research.task023b_segment_rescue import (
    RescueStatus,
    SegmentDecision,
    SegmentRescueConfig,
    SegmentRescueResult,
    rescue_suspicious_segments,
)
from scripts.run_task023a_imm_mht_ridge_tracker import SyntheticCase, _synthetic_cases

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "data" / "raw"
ARTIFACT_ROOT = ROOT / "artifacts" / "task024a_strongest_segment_rescue"
TOP_K = 20
WRONG_TOLERANCE_HZ = 200.0e6
LARGE_JUMP_HZ = 450.0e6
CALIBRATION_IDS = frozenset(
    {
        "A_clean_ridge",
        "B_isolated_stronger_distractor",
        "C_sustained_competing_branch",
        "D_temporarily_weak_true_ridge",
        "E_temporary_dropout",
        "R_ABRUPT_WRONG_BRANCH",
    }
)
CH3_INTERVALS = (
    ("FULL", -math.inf, math.inf),
    ("DIAGNOSTIC_183P60_183P90_US", 183.60e-6, 183.90e-6),
    ("POST_183P80_US", 183.80e-6, 183.90e-6),
)


@dataclass(frozen=True, slots=True)
class SyntheticRun:
    case: SyntheticCase
    candidate_set: RidgeCandidateSet
    result: SegmentRescueResult


def main() -> None:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ARTIFACT_ROOT / timestamp
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=False)
    audit_before = _repository_audit()
    raw_before = _tree_hashes(RAW_ROOT)

    cases = (*_synthetic_cases(), *_additional_synthetic_cases())
    split_rows = [
        {
            "case_id": case.case_id,
            "description": case.description,
            "case_kind": case.case_kind,
            "split": "CALIBRATION" if case.case_id in CALIBRATION_IDS else "HELD_OUT_EVALUATION",
            "ch3_used_for_calibration": False,
            "real_data_used_for_calibration": False,
        }
        for case in cases
    ]
    _write_csv(output / "synthetic_calibration_split.csv", split_rows)
    selected_config, calibration_rows = _calibrate(cases)
    synthetic_rows, intervention_rows, synthetic_runs = _run_synthetic(
        cases, selected_config
    )
    _write_csv(output / "synthetic_rescue_benchmark.csv", synthetic_rows)
    _write_csv(
        output / "intervention_precision_summary.csv",
        [*calibration_rows, *intervention_rows],
    )
    gate = _hard_gate(synthetic_rows, split="HELD_OUT_EVALUATION")
    if not bool(gate["hard_gate_passed"]):
        _write_failure_artifacts(output, figures, selected_config, gate, synthetic_runs)
        print(output)
        return

    workflow = load_workflow_config(DEFAULT_CONFIG_PATH, repository_root=ROOT)
    inventory, accepted = corrected_inventory(RAW_ROOT, workflow)
    streams, failures = prepare_streams(
        raw_root=RAW_ROOT,
        configuration=workflow,
        accepted_inputs=accepted,
    )
    comparison_rows: list[dict[str, Any]] = []
    modification_rows: list[dict[str, Any]] = []
    oversmoothing_rows: list[dict[str, Any]] = []
    ch3_detection: list[dict[str, Any]] = []
    ch3_detail: list[dict[str, Any]] = []
    ch3_comparison: list[dict[str, Any]] = []
    ch3_bundles: dict[str, tuple[PreparedStream, RidgeCandidateSet, SegmentRescueResult, Any, Any]] = {}
    for stream_index, stream in enumerate(streams, start=1):
        print(f"[{stream_index}/{len(streams)}] {stream.stream_id}", flush=True)
        candidate_set = candidate_set_for_top_k(
            stream.candidate_set_maximum, config=GlobalPathConfig(top_k=TOP_K)
        )
        start = time.perf_counter()
        result = rescue_suspicious_segments(
            candidate_set,
            config=selected_config,
            stft_result=stream.analysis.stft_result,
        )
        runtime = time.perf_counter() - start
        strongest_metrics = _real_metric(
            stream, result, "FRAMEWISE_STRONGEST", result.strongest.frequency_hz, runtime_s=0.0
        )
        rescue_metrics = _real_metric(
            stream, result, "STRONGEST_SEGMENT_RESCUE", result.final_frequency_hz, runtime_s=runtime
        )
        comparison_rows.extend((strongest_metrics, rescue_metrics))
        modification_rows.append(_modification_row(stream, result, runtime))
        oversmoothing_rows.extend(_oversmoothing_rows(stream, result))
        if stream.source_path.name.casefold() != "ch3.csv":
            continue
        null_start = time.perf_counter()
        null_result = solve_global_candidate_path(candidate_set)
        null_runtime = time.perf_counter() - null_start
        imm = track_candidates(
            candidate_set,
            config=TrackerConfig(),
            beam_width=8,
            stft_result=stream.analysis.stft_result,
        )
        ch3_detection.extend(_segment_rows(stream, result))
        ch3_detail.extend(_modified_detail_rows(stream, result, candidate_set))
        for interval_id, start_s, end_s in CH3_INTERVALS:
            ch3_comparison.extend(
                _ch3_method_rows(
                    stream,
                    result,
                    null_result,
                    null_runtime,
                    imm,
                    interval_id,
                    start_s,
                    end_s,
                )
            )
        ch3_bundles[stream.profile_id] = (stream, candidate_set, result, null_result, imm)

    _write_csv(output / "ch3_segment_detection.csv", ch3_detection)
    _write_csv(output / "ch3_rescue_detail.csv", ch3_detail)
    _write_csv(output / "ch3_comparison.csv", ch3_comparison)
    _write_csv(output / "cross_dataset_rescue_comparison.csv", comparison_rows)
    _write_csv(output / "modification_summary.csv", modification_rows)
    _write_csv(output / "oversmoothing_diagnostic.csv", oversmoothing_rows)
    _write_definitions(output, selected_config)
    _save_synthetic_figures(figures, synthetic_runs)
    _save_ch3_figures(figures, ch3_bundles)

    raw_after = _tree_hashes(RAW_ROOT)
    if raw_after != raw_before:
        raise RuntimeError("Raw SHA-256 changed during TASK-023B.")
    real_guard = _real_guard(comparison_rows, modification_rows, oversmoothing_rows)
    metadata = {
        "task": "TASK-023B",
        "timestamp_utc": timestamp,
        "research_only": True,
        "hard_gate": gate,
        "real_regression_guard": real_guard,
        "selected_config": asdict(selected_config),
        "calibration_ids": sorted(CALIBRATION_IDS),
        "held_out_ids": sorted(case.case_id for case in cases if case.case_id not in CALIBRATION_IDS),
        "ch3_used_for_calibration": False,
        "real_data_used_for_calibration": False,
        "stream_count": len(streams),
        "preparation_failures": [asdict(item) for item in failures],
        "inventory_row_count": len(inventory),
        "raw_root": str(RAW_ROOT),
        "raw_hashes_before_after_equal": True,
        "raw_sha256": raw_before,
        "fixed_upstream": _upstream_hashes(),
        "production_modified": False,
        "global_tracking_used_as_final_algorithm": False,
        "orientation_used_in_acceptance": selected_config.orientation_guard_weight != 0.0,
        "ai_used": False,
        "repository_audit_before": audit_before,
        "repository_audit_after": _repository_audit(),
    }
    (output / "experiment_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=True), encoding="utf-8"
    )
    (output / "final_research_report.md").write_text(
        _report(
            gate,
            real_guard,
            synthetic_rows,
            ch3_comparison,
            comparison_rows,
            modification_rows,
        ),
        encoding="utf-8",
    )
    print(output)


def _calibrate(
    cases: Sequence[SyntheticCase],
) -> tuple[SegmentRescueConfig, list[dict[str, Any]]]:
    calibration_cases = [case for case in cases if case.case_id in CALIBRATION_IDS]
    candidates = {
        case.case_id: _candidate_set(case) for case in calibration_cases
    }
    rows: list[dict[str, Any]] = []
    configurations: list[SegmentRescueConfig] = []
    for background in (12.0, 15.0, 18.0):
        for competitor in (-10.0, -8.0, -6.0):
            for margin in (0.75, 2.0):
                configurations.append(
                    SegmentRescueConfig(
                        minimum_rescue_background_db=background,
                        minimum_rescue_competitor_db=competitor,
                        acceptance_margin=margin,
                    )
                )
    ranked: list[tuple[tuple[float, ...], SegmentRescueConfig, dict[str, Any]]] = []
    for index, config in enumerate(configurations):
        benchmark: list[dict[str, Any]] = []
        for case in calibration_cases:
            result = rescue_suspicious_segments(
                candidates[case.case_id], config=config, stft_result=case.stft
            )
            benchmark.extend(_synthetic_method_rows(case, result, "CALIBRATION"))
        gate = _hard_gate(benchmark, split="CALIBRATION")
        row = {
            "summary_type": "CALIBRATION_GRID",
            "configuration_id": f"CFG_{index:03d}",
            "minimum_rescue_background_db": config.minimum_rescue_background_db,
            "minimum_rescue_competitor_db": config.minimum_rescue_competitor_db,
            "acceptance_margin": config.acceptance_margin,
            **gate,
            "selected": False,
        }
        rows.append(row)
        passes = float(bool(gate["hard_gate_passed"]))
        key = (
            passes,
            float(gate["net_corrected_frames"]),
            -float(gate["intervention_harm_rate"]),
            -float(gate["modification_fraction"]),
            config.minimum_rescue_background_db,
            -abs(config.minimum_rescue_competitor_db + 8.0),
            config.acceptance_margin,
        )
        ranked.append((key, config, row))
    _, selected, selected_row = max(ranked, key=lambda item: item[0])
    selected_row["selected"] = True
    return selected, rows


def _run_synthetic(
    cases: Sequence[SyntheticCase], config: SegmentRescueConfig
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, SyntheticRun]]:
    rows: list[dict[str, Any]] = []
    runs: dict[str, SyntheticRun] = {}
    for case in cases:
        candidate_set = _candidate_set(case)
        result = rescue_suspicious_segments(
            candidate_set, config=config, stft_result=case.stft
        )
        split = "CALIBRATION" if case.case_id in CALIBRATION_IDS else "HELD_OUT_EVALUATION"
        rows.extend(_synthetic_method_rows(case, result, split))
        runs[case.case_id] = SyntheticRun(case, candidate_set, result)
    return rows, [_hard_gate(rows, split="CALIBRATION"), _hard_gate(rows, split="HELD_OUT_EVALUATION")], runs


def _synthetic_method_rows(
    case: SyntheticCase, result: SegmentRescueResult, split: str
) -> list[dict[str, Any]]:
    return [
        _synthetic_metric(case, result, "FRAMEWISE_STRONGEST", result.strongest.frequency_hz, split),
        _synthetic_metric(case, result, "STRONGEST_SEGMENT_RESCUE", result.final_frequency_hz, split),
    ]


def _synthetic_metric(
    case: SyntheticCase,
    result: SegmentRescueResult,
    method: str,
    frequency: np.ndarray[Any, Any],
    split: str,
) -> dict[str, Any]:
    truth_valid = np.isfinite(case.truth_hz)
    estimate_valid = np.isfinite(frequency)
    comparable = truth_valid & estimate_valid
    error = frequency[comparable] - case.truth_hz[comparable]
    wrong = comparable & (np.abs(frequency - case.truth_hz) > WRONG_TOLERANCE_HZ)
    modified = result.modified_mask if method == "STRONGEST_SEGMENT_RESCUE" else np.zeros(frequency.size, dtype=np.bool_)
    strongest_error = np.abs(result.strongest.frequency_hz - case.truth_hz)
    rescued_error = np.abs(result.final_frequency_hz - case.truth_hz)
    improved = modified & truth_valid & (rescued_error < strongest_error)
    harmed = modified & truth_valid & (rescued_error > strongest_error)
    unchanged_error = modified & truth_valid & np.isclose(rescued_error, strongest_error)
    steps = np.abs(np.diff(frequency))
    return {
        "case_id": case.case_id,
        "case_kind": case.case_kind,
        "description": case.description,
        "split": split,
        "method": method,
        "frame_count": frequency.size,
        "coverage": float(np.mean(estimate_valid)),
        "truth_frame_count": int(np.count_nonzero(truth_valid)),
        "squared_error_sum_hz2": float(np.sum(np.square(error))),
        "frequency_rmse_hz": float(np.sqrt(np.mean(np.square(error)))) if error.size else math.nan,
        "wrong_branch_count": int(np.count_nonzero(wrong)),
        "wrong_branch_fraction": float(np.count_nonzero(wrong) / max(int(np.count_nonzero(truth_valid)), 1)),
        "large_jump_count": int(np.count_nonzero(steps >= LARGE_JUMP_HZ)),
        "modified_frame_count": int(np.count_nonzero(modified)),
        "modification_fraction": float(np.mean(modified)),
        "improved_frame_count": int(np.count_nonzero(improved)),
        "harmed_frame_count": int(np.count_nonzero(harmed)),
        "equal_error_modified_count": int(np.count_nonzero(unchanged_error)),
        "intervention_precision": float(np.count_nonzero(improved) / max(int(np.count_nonzero(modified & truth_valid)), 1)),
        "intervention_harm_rate": float(np.count_nonzero(harmed) / max(int(np.count_nonzero(modified & truth_valid)), 1)),
        "net_corrected_frames": int(np.count_nonzero(improved) - np.count_nonzero(harmed)),
        "detected_segment_count": len(result.segments),
        "accepted_segment_count": sum(_accepted(decision) for decision in result.decisions),
    }


def _hard_gate(rows: Sequence[Mapping[str, Any]], *, split: str) -> dict[str, Any]:
    relevant = [row for row in rows if row.get("split") == split]
    strongest = [row for row in relevant if row.get("method") == "FRAMEWISE_STRONGEST"]
    rescue = [row for row in relevant if row.get("method") == "STRONGEST_SEGMENT_RESCUE"]
    truth_count = sum(int(row["truth_frame_count"]) for row in strongest)
    strongest_rmse = math.sqrt(
        sum(float(row["squared_error_sum_hz2"]) for row in strongest) / max(truth_count, 1)
    )
    rescue_rmse = math.sqrt(
        sum(float(row["squared_error_sum_hz2"]) for row in rescue) / max(truth_count, 1)
    )
    strongest_wrong = sum(int(row["wrong_branch_count"]) for row in strongest) / max(truth_count, 1)
    rescue_wrong = sum(int(row["wrong_branch_count"]) for row in rescue) / max(truth_count, 1)
    modified = sum(int(row["modified_frame_count"]) for row in rescue)
    improved = sum(int(row["improved_frame_count"]) for row in rescue)
    harmed = sum(int(row["harmed_frame_count"]) for row in rescue)
    frames = sum(int(row["frame_count"]) for row in rescue)
    clean_rows = [
        row
        for row in rescue
        if row["case_kind"] in {"platform", "fast_descent", "fully_correct", "legacy"}
        and float(row["frequency_rmse_hz"]) < 20.0e6
    ]
    clean_modified = sum(int(row["modified_frame_count"]) for row in clean_rows)
    clean_frames = sum(int(row["frame_count"]) for row in clean_rows)
    precision = improved / max(modified, 1)
    harm_rate = harmed / max(modified, 1)
    strongest_coverage = min((float(row["coverage"]) for row in strongest), default=0.0)
    rescue_coverage = min((float(row["coverage"]) for row in rescue), default=0.0)
    clean_fraction = clean_modified / max(clean_frames, 1)
    passed = (
        rescue_rmse < strongest_rmse
        and rescue_wrong < strongest_wrong
        and rescue_coverage >= strongest_coverage
        and precision >= 0.80
        and harm_rate <= 0.10
        and clean_fraction <= 0.02
    )
    return {
        "summary_type": "HARD_GATE",
        "split": split,
        "strongest_rmse_hz": strongest_rmse,
        "rescue_rmse_hz": rescue_rmse,
        "strongest_wrong_branch_fraction": strongest_wrong,
        "rescue_wrong_branch_fraction": rescue_wrong,
        "strongest_coverage": strongest_coverage,
        "rescue_coverage": rescue_coverage,
        "modified_frame_count": modified,
        "modification_fraction": modified / max(frames, 1),
        "improved_frame_count": improved,
        "harmed_frame_count": harmed,
        "intervention_precision": precision,
        "intervention_harm_rate": harm_rate,
        "net_corrected_frames": improved - harmed,
        "clean_modification_fraction": clean_fraction,
        "hard_gate_passed": passed,
    }


def _candidate_set(case: SyntheticCase) -> RidgeCandidateSet:
    return extract_global_path_candidates(
        case.stft,
        minimum_frequency_hz=0.05e9,
        maximum_frequency_hz=min(6.0e9, float(case.stft.frequency_hz[-1])),
        config=GlobalPathConfig(top_k=TOP_K),
    )


def _additional_synthetic_cases() -> tuple[SyntheticCase, ...]:
    count = 104
    truth = np.full(count, 2.4e9, dtype=np.float64)
    return (
        _custom_case(
            "J_MULTIPLE_SHORT_LOCAL_ERRORS",
            "three separated short strongest errors",
            truth,
            ((slice(24, 26), 5.0e9, 25.0), (slice(50, 53), 0.7e9, 25.0), (slice(78, 80), 4.7e9, 25.0)),
            "multiple_short_errors",
        ),
        _custom_case(
            "K_LONG_WRONG_BRANCH_NO_RESCUE",
            "long strong competing branch where local rescue should abstain",
            truth,
            ((slice(20, 84), 4.6e9, 20.0),),
            "long_wrong_branch",
        ),
        _custom_case(
            "L_FULLY_CORRECT_STRONGEST",
            "fully correct strongest path",
            truth,
            tuple(),
            "fully_correct",
        ),
    )


def _custom_case(
    case_id: str,
    description: str,
    truth: np.ndarray[Any, Any],
    distractors: tuple[tuple[slice, float, float], ...],
    kind: str,
) -> SyntheticCase:
    rng = np.random.default_rng(24000 + sum(ord(item) for item in case_id))
    frequency = np.linspace(0.0, 6.4e9, 257)
    magnitude = rng.lognormal(math.log(0.20), 0.40, size=(frequency.size, truth.size))
    for frame, value in enumerate(truth):
        _add_peak(magnitude[:, frame], frequency, float(value), 12.0)
    for selected_slice, center, amplitude in distractors:
        for frame in range(*selected_slice.indices(truth.size)):
            _add_peak(magnitude[:, frame], frequency, center, amplitude)
    phase = rng.uniform(-math.pi, math.pi, size=magnitude.shape)
    stft = STFTResult(
        time_s=np.arange(truth.size, dtype=np.float64) * 2.5e-9,
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
    return SyntheticCase(
        case_id,
        description,
        stft,
        np.asarray(truth, dtype=np.float64),
        np.ones(truth.size, dtype=np.bool_),
        kind,
    )


def _add_peak(
    values: np.ndarray[Any, Any], frequency: np.ndarray[Any, Any], center: float, amplitude: float
) -> None:
    values += amplitude * np.exp(-0.5 * np.square((frequency - center) / 35.0e6))


def _real_metric(
    stream: PreparedStream,
    result: SegmentRescueResult,
    method: str,
    frequency: np.ndarray[Any, Any],
    *,
    runtime_s: float,
    interval_id: str = "FULL",
    mask: np.ndarray[Any, Any] | None = None,
    selected_rank: np.ndarray[Any, Any] | None = None,
    modification_mask: np.ndarray[Any, Any] | None = None,
) -> dict[str, Any]:
    selected_mask = np.ones(frequency.size, dtype=np.bool_) if mask is None else np.asarray(mask, dtype=np.bool_)
    values = np.asarray(frequency[selected_mask], dtype=np.float64)
    adjacent_finite = np.isfinite(values[:-1]) & np.isfinite(values[1:])
    steps = np.abs(np.diff(values)[adjacent_finite])
    if modification_mask is not None:
        modified = np.asarray(modification_mask[selected_mask], dtype=np.bool_)
    elif method == "STRONGEST_SEGMENT_RESCUE":
        modified = result.modified_mask[selected_mask]
    else:
        modified = np.zeros(values.size, dtype=np.bool_)
    if selected_rank is not None:
        ranks = np.asarray(selected_rank[selected_mask], dtype=np.int64)
    elif method == "STRONGEST_SEGMENT_RESCUE":
        ranks = result.final_rank[selected_mask]
    else:
        ranks = result.strongest.selected_rank[selected_mask]
    return {
        "dataset": stream.source_path.name,
        "source_sha256": stream.source_sha256,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "interval_id": interval_id,
        "method": method,
        "frame_count": values.size,
        "coverage": float(np.mean(np.isfinite(values))) if values.size else math.nan,
        "step_p95_hz": float(np.quantile(steps, 0.95)) if steps.size else math.nan,
        "large_jump_count": int(np.count_nonzero(steps >= LARGE_JUMP_HZ)),
        "modification_fraction": float(np.mean(modified)) if modified.size else math.nan,
        "modified_frame_count": int(np.count_nonzero(modified)),
        "rank2_fraction": float(np.mean(ranks == 2)) if ranks.size else math.nan,
        "rank3_fraction": float(np.mean(ranks == 3)) if ranks.size else math.nan,
        "rank2plus_fraction": float(np.mean(ranks >= 2)) if ranks.size else math.nan,
        "runtime_s": runtime_s,
    }


def _modification_row(
    stream: PreparedStream, result: SegmentRescueResult, runtime_s: float
) -> dict[str, Any]:
    accepted = [decision for decision in result.decisions if _accepted(decision)]
    return {
        "dataset": stream.source_path.name,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "frame_count": result.time_s.size,
        "detected_segment_count": len(result.segments),
        "accepted_segment_count": len(accepted),
        "rejected_segment_count": len(result.decisions) - len(accepted),
        "modified_frame_count": int(np.count_nonzero(result.modified_mask)),
        "modification_fraction": float(np.mean(result.modified_mask)),
        "rank2_rescue_count": int(np.count_nonzero(result.modified_mask & (result.final_rank == 2))),
        "rank3_rescue_count": int(np.count_nonzero(result.modified_mask & (result.final_rank == 3))),
        "rank4plus_rescue_count": int(np.count_nonzero(result.modified_mask & (result.final_rank >= 4))),
        "modification_over_50_percent_risk": bool(np.mean(result.modified_mask) > 0.50),
        "runtime_s": runtime_s,
    }


def _oversmoothing_rows(
    stream: PreparedStream, result: SegmentRescueResult
) -> list[dict[str, Any]]:
    return [
        {
            "stream_id": stream.stream_id,
            "dataset": stream.source_path.name,
            "quality_group": stream.quality_group,
            "profile": stream.profile_id,
            "segment_id": decision.segment.segment_id,
            "status": decision.status.value,
            "strongest_local_slope_hz_per_s": decision.strongest_local_slope_hz_per_s,
            "rescued_local_slope_hz_per_s": decision.rescued_local_slope_hz_per_s,
            "candidate_supported_slope_min_hz_per_s": decision.candidate_supported_slope_min_hz_per_s,
            "candidate_supported_slope_max_hz_per_s": decision.candidate_supported_slope_max_hz_per_s,
            "original_support_fraction": decision.original_support_fraction,
            "rescued_support_fraction": decision.rescued_support_fraction,
            "oversmoothing_risk": decision.oversmoothing_risk,
        }
        for decision in result.decisions
    ]


def _segment_rows(
    stream: PreparedStream, result: SegmentRescueResult
) -> list[dict[str, Any]]:
    decision_by_id = {decision.segment.segment_id: decision for decision in result.decisions}
    rows: list[dict[str, Any]] = []
    for segment in result.segments:
        decision = decision_by_id[segment.segment_id]
        rows.append(
            {
                "stream_id": stream.stream_id,
                "profile": stream.profile_id,
                **asdict(segment),
                "trigger_flags": "|".join(flag.value for flag in segment.trigger_flags),
                "status": decision.status.value,
                "selected_model": decision.selected_model,
                **asdict(decision.components),
            }
        )
    return rows


def _modified_detail_rows(
    stream: PreparedStream,
    result: SegmentRescueResult,
    candidate_set: RidgeCandidateSet,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for decision in result.decisions:
        if not _accepted(decision):
            continue
        for offset, frame_index in enumerate(
            range(decision.segment.frame_start, decision.segment.frame_end + 1)
        ):
            if decision.proposed_frequency_hz[offset] == decision.original_frequency_hz[offset]:
                continue
            rank = int(decision.proposed_rank[offset])
            candidate = candidate_set.candidates_by_frame[frame_index][rank - 1]
            rows.append(
                {
                    "stream_id": stream.stream_id,
                    "profile": stream.profile_id,
                    "segment_id": decision.segment.segment_id,
                    "frame_index": frame_index,
                    "time_s": float(result.time_s[frame_index]),
                    "original_strongest_frequency_hz": float(decision.original_frequency_hz[offset]),
                    "rescued_frequency_hz": float(decision.proposed_frequency_hz[offset]),
                    "original_rank": int(decision.original_rank[offset]),
                    "rescued_rank": rank,
                    "reason": decision.status.value,
                    "original_segment_cost": decision.original_segment_cost,
                    "rescued_segment_cost": decision.rescued_segment_cost,
                    "rescue_margin": decision.components.rescue_margin,
                    "candidate_peak_to_background_db": candidate.peak_to_background_db,
                    "candidate_peak_to_competitor_db": candidate.peak_to_competitor_db,
                    "local_support_fraction": decision.rescued_support_fraction,
                    "oversmoothing_risk": decision.oversmoothing_risk,
                }
            )
    return rows


def _ch3_method_rows(
    stream: PreparedStream,
    rescue: SegmentRescueResult,
    null_result: Any,
    null_runtime: float,
    imm: Any,
    interval_id: str,
    start_s: float,
    end_s: float,
) -> list[dict[str, Any]]:
    mask = (rescue.time_s >= start_s) & (rescue.time_s <= end_s)
    null_frequency = np.where(
        np.isfinite(null_result.selected_refined_frequency_hz),
        null_result.selected_refined_frequency_hz,
        null_result.selected_discrete_frequency_hz,
    )
    rows = [
        _real_metric(stream, rescue, "FRAMEWISE_STRONGEST", rescue.strongest.frequency_hz, runtime_s=0.0, interval_id=interval_id, mask=mask),
        _real_metric(
            stream,
            rescue,
            "NULL_GLOBAL",
            null_frequency,
            runtime_s=null_runtime,
            interval_id=interval_id,
            mask=mask,
            selected_rank=null_result.selected_candidate_rank,
        ),
        _real_metric(
            stream,
            rescue,
            "IMM_MHT_B8",
            imm.frequency_hz,
            runtime_s=imm.runtime_s,
            interval_id=interval_id,
            mask=mask,
            selected_rank=imm.selected_rank,
            modification_mask=imm.frequency_hz != rescue.strongest.frequency_hz,
        ),
        _real_metric(stream, rescue, "STRONGEST_SEGMENT_RESCUE", rescue.final_frequency_hz, runtime_s=0.0, interval_id=interval_id, mask=mask),
    ]
    return rows


def _save_synthetic_figures(
    figures: Path, runs: Mapping[str, SyntheticRun]
) -> None:
    representative = (
        "B_isolated_stronger_distractor",
        "R_ABRUPT_WRONG_BRANCH",
        "Q_FAST_SMOOTH_DESCENT",
        "T_BRANCH_CROSSING",
        "V_BROADBAND_VERTICAL_TRANSIENT",
        "L_FULLY_CORRECT_STRONGEST",
    )
    for case_id in representative:
        run = runs[case_id]
        figure = Figure(figsize=(10.5, 5.5), constrained_layout=True)
        axis = figure.subplots()
        db = 20.0 * np.log10(np.maximum(np.abs(run.case.stft.spectrum), np.finfo(float).tiny))
        extent = (
            float(run.case.stft.time_s[0] * 1e9),
            float(run.case.stft.time_s[-1] * 1e9),
            float(run.case.stft.frequency_hz[0] / 1e9),
            float(run.case.stft.frequency_hz[-1] / 1e9),
        )
        axis.imshow(db, origin="lower", aspect="auto", extent=extent, cmap="magma", vmin=np.max(db) - 45.0)
        x = run.case.stft.time_s * 1e9
        axis.plot(x, run.case.truth_hz / 1e9, "w--", label="truth")
        axis.plot(x, run.result.strongest.frequency_hz / 1e9, color="#4cc9f0", label="strongest")
        axis.plot(x, run.result.final_frequency_hz / 1e9, color="#06d6a0", label="segment rescue")
        modified = run.result.modified_mask
        axis.scatter(x[modified], run.result.final_frequency_hz[modified] / 1e9, color="#ffd166", s=25, label="modified")
        axis.set(xlabel="time (ns)", ylabel="frequency (GHz)", title=case_id)
        axis.legend(ncol=4, fontsize=8)
        _save(figure, figures / f"synthetic_{case_id}.png")


def _save_ch3_figures(
    figures: Path,
    bundles: Mapping[str, tuple[PreparedStream, RidgeCandidateSet, SegmentRescueResult, Any, Any]],
) -> None:
    for profile, (stream, _, rescue, null_result, imm) in bundles.items():
        stft = stream.analysis.stft_result
        x = rescue.time_s * 1e6
        null_frequency = np.where(
            np.isfinite(null_result.selected_refined_frequency_hz),
            null_result.selected_refined_frequency_hz,
            null_result.selected_discrete_frequency_hz,
        )
        figure = Figure(figsize=(12, 6), constrained_layout=True)
        axis = figure.subplots()
        db = 20.0 * np.log10(np.maximum(np.abs(stft.spectrum), np.finfo(float).tiny))
        axis.imshow(
            db,
            origin="lower",
            aspect="auto",
            extent=(float(stft.time_s[0] * 1e6), float(stft.time_s[-1] * 1e6), float(stft.frequency_hz[0] / 1e9), float(stft.frequency_hz[-1] / 1e9)),
            cmap="magma",
            vmin=np.max(db) - 50.0,
        )
        for segment in rescue.segments:
            axis.axvspan(segment.start_time_s * 1e6, segment.end_time_s * 1e6, color="#ffd166", alpha=0.14)
        axis.plot(x, rescue.strongest.frequency_hz / 1e9, color="#4cc9f0", linewidth=0.9, label="strongest")
        axis.plot(x, null_frequency / 1e9, color="#8338ec", linewidth=0.9, alpha=0.8, label="NULL Global")
        axis.plot(x, imm.frequency_hz / 1e9, color="#ef476f", linewidth=1.0, alpha=0.8, label="IMM/MHT")
        axis.plot(x, rescue.final_frequency_hz / 1e9, color="#06d6a0", linewidth=1.5, label="segment rescue")
        modified = rescue.modified_mask
        axis.scatter(x[modified], rescue.final_frequency_hz[modified] / 1e9, color="white", edgecolor="black", s=30, label="modified")
        axis.set(xlabel="time (µs)", ylabel="frequency (GHz)", title=f"ch3 {profile}: strongest-first local rescue", xlim=(183.55, 183.95), ylim=(0.0, 6.0))
        axis.legend(ncol=5, fontsize=8)
        _save(figure, figures / f"ch3_{profile}_overlay.png")

        diagnostic = Figure(figsize=(12, 10), constrained_layout=True)
        axes = diagnostic.subplots(4, 1, sharex=True)
        axes[0].step(x, rescue.strongest.selected_rank, where="mid", label="before")
        axes[0].step(x, rescue.final_rank, where="mid", label="after")
        axes[0].set_ylabel("candidate rank")
        axes[0].legend()
        margin = np.full(x.size, math.nan)
        before_slope = np.full(x.size, math.nan)
        after_slope = np.full(x.size, math.nan)
        support = np.full(x.size, math.nan)
        for decision in rescue.decisions:
            selected = slice(decision.segment.frame_start, decision.segment.frame_end + 1)
            margin[selected] = decision.components.rescue_margin
            before_slope[selected] = decision.strongest_local_slope_hz_per_s
            after_slope[selected] = decision.rescued_local_slope_hz_per_s
            support[selected] = decision.rescued_support_fraction
        axes[1].plot(x, margin)
        axes[1].axhline(0.0, color="k", linestyle="--")
        axes[1].set_ylabel("rescue margin")
        axes[2].plot(x, before_slope / 1e15, label="strongest")
        axes[2].plot(x, after_slope / 1e15, label="proposal")
        axes[2].set_ylabel("slope (10¹⁵ Hz/s)")
        axes[2].legend()
        axes[3].plot(x, support)
        axes[3].set(xlabel="time (µs)", ylabel="local support", xlim=(183.55, 183.95), ylim=(0.0, 1.05))
        _save(diagnostic, figures / f"ch3_{profile}_segment_diagnostics.png")


def _write_definitions(output: Path, config: SegmentRescueConfig) -> None:
    (output / "segment_detector_definition.md").write_text(
        """# Suspicious segment detector

The detector reads only the immutable frame-wise strongest trajectory, physical `time_s`, `frequency_hz`, the fixed Top-20 candidate graph, and a broadband power diagnostic. It flags isolated jump/return, short excursions whose independently extrapolated left/right trends agree, local slope reversal, broadband-coincident excursions, and candidate-support instability. Large slope magnitude alone is never a trigger. Adjacent flags are merged; anchors are searched outside the segment and require non-suspicious local curvature and candidate support. Detection never changes frequency.

Production differs materially: current Production rescue handles only one-frame `ISOLATED_JUMP` states with immediate two-neighbor hard gates and event-window protection. TASK-023B is Research-only multi-frame segment optimization with external anchors and a separate acceptance margin.
""",
        encoding="utf-8",
    )
    (output / "rescue_model_definition.md").write_text(
        f"""# Local rescue model

R0 is the original strongest segment. R1 is local quadratic first-order DP. R2 uses the exact TASK-021E E2 pseudo-Huber transition (`scale={config.frequency_step_scale_hz:.6e} Hz`, `kappa={config.e2_huber_delta_normalized}`). There is no NULL state and no candidate generation.

Local paths connect a trusted left anchor through the existing Top-20 frames to a trusted right anchor. Candidate spectral cost, both anchor connections, internal continuity, and deviation from strongest enter local search. Acceptance separately records spectral gain, anchor gain, jump reduction, continuity gain, candidate-support gain, unweighted broadband-risk diagnostic, strongest deviation, and total margin. Changed candidates must satisfy `{config.minimum_rescue_background_db:.1f}` dB background and `{config.minimum_rescue_competitor_db:.1f}` dB competitor evidence; anchor gain cannot be negative. Orientation weight is `{config.orientation_guard_weight}` and therefore diagnostic only.

All final frames outside accepted segments are exact strongest values. Oversmoothing guard rejects a proposal that converts candidate-supported fast slope into a near-horizontal path.
""",
        encoding="utf-8",
    )


def _write_failure_artifacts(
    output: Path,
    figures: Path,
    config: SegmentRescueConfig,
    gate: Mapping[str, Any],
    runs: Mapping[str, SyntheticRun],
) -> None:
    _write_definitions(output, config)
    _save_synthetic_figures(figures, runs)
    for name in (
        "ch3_segment_detection.csv",
        "ch3_rescue_detail.csv",
        "ch3_comparison.csv",
        "cross_dataset_rescue_comparison.csv",
        "modification_summary.csv",
        "oversmoothing_diagnostic.csv",
    ):
        (output / name).write_text("", encoding="utf-8")
    (output / "experiment_metadata.json").write_text(
        json.dumps({"task": "TASK-023B", "hard_gate": gate, "real_evaluation_run": False}, indent=2),
        encoding="utf-8",
    )
    (output / "final_research_report.md").write_text(
        "# TASK-023B\n\nSynthetic hard gate failed. Verdict: **NOT_BETTER_THAN_STRONGEST**. Real-data main evaluation was not run.\n",
        encoding="utf-8",
    )


def _real_guard(
    comparison: Sequence[Mapping[str, Any]],
    modification: Sequence[Mapping[str, Any]],
    oversmoothing: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    strongest = {
        str(row["stream_id"]): row
        for row in comparison
        if row["method"] == "FRAMEWISE_STRONGEST" and row["interval_id"] == "FULL"
    }
    rescued = {
        str(row["stream_id"]): row
        for row in comparison
        if row["method"] == "STRONGEST_SEGMENT_RESCUE" and row["interval_id"] == "FULL"
    }
    common = sorted(strongest.keys() & rescued.keys())
    strongest_jumps = sum(int(strongest[key]["large_jump_count"]) for key in common)
    rescued_jumps = sum(int(rescued[key]["large_jump_count"]) for key in common)
    coverage_regressions = sum(
        float(rescued[key]["coverage"]) < float(strongest[key]["coverage"])
        for key in common
    )
    jump_regressions = sum(
        int(rescued[key]["large_jump_count"]) > int(strongest[key]["large_jump_count"])
        for key in common
    )
    step_p95_regressions = sum(
        float(rescued[key]["step_p95_hz"]) > float(strongest[key]["step_p95_hz"])
        for key in common
    )
    stationary_locks = sum(
        float(strongest[key]["step_p95_hz"]) > 1.0e6
        and float(rescued[key]["step_p95_hz"]) <= 1.0
        for key in common
    )
    maximum_modification = max(
        (float(row["modification_fraction"]) for row in modification), default=0.0
    )
    accepted_oversmoothing = sum(
        str(row["status"]).startswith("ACCEPTED")
        and _explicit_bool(row["oversmoothing_risk"])
        for row in oversmoothing
    )
    passed = (
        coverage_regressions == 0
        and rescued_jumps < strongest_jumps
        and jump_regressions == 0
        and step_p95_regressions == 0
        and stationary_locks == 0
        and maximum_modification <= 0.50
        and accepted_oversmoothing == 0
    )
    return {
        "stream_count": len(common),
        "strongest_large_jump_count": strongest_jumps,
        "rescued_large_jump_count": rescued_jumps,
        "coverage_regression_stream_count": coverage_regressions,
        "large_jump_regression_stream_count": jump_regressions,
        "step_p95_regression_stream_count": step_p95_regressions,
        "stationary_lock_stream_count": stationary_locks,
        "maximum_modification_fraction": maximum_modification,
        "accepted_oversmoothing_count": accepted_oversmoothing,
        "real_regression_guard_passed": passed,
    }


def _explicit_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() == "true"
    if value is True:
        return True
    return bool(value) if isinstance(value, np.bool_) else False


def _report(
    gate: Mapping[str, Any],
    real_guard: Mapping[str, Any],
    synthetic: Sequence[Mapping[str, Any]],
    ch3: Sequence[Mapping[str, Any]],
    real: Sequence[Mapping[str, Any]],
    modification: Sequence[Mapping[str, Any]],
) -> str:
    def group(group: str, key: str) -> float:
        values = [float(row[key]) for row in modification if row["quality_group"] == group]
        return float(np.mean(values)) if values else math.nan

    def ch3_value(profile: str, method: str, key: str, interval: str = "DIAGNOSTIC_183P60_183P90_US") -> float:
        row = next(item for item in ch3 if item["profile"] == profile and item["method"] == method and item["interval_id"] == interval)
        return float(row[key])

    verdict = (
        "BETTER_THAN_STRONGEST"
        if bool(gate["hard_gate_passed"])
        and bool(real_guard["real_regression_guard_passed"])
        else "MIXED"
    )
    held = gate
    return f"""# TASK-023B Strongest-First Segment Rescue

## Hard verdict

**{verdict}** under the declared gate. Held-out synthetic aggregate RMSE is `{float(held['strongest_rmse_hz'])/1e6:.3f}`→`{float(held['rescue_rmse_hz'])/1e6:.3f}` MHz; wrong-branch fraction `{float(held['strongest_wrong_branch_fraction']):.6f}`→`{float(held['rescue_wrong_branch_fraction']):.6f}`; coverage remains `{float(held['rescue_coverage']):.3f}`; intervention precision `{float(held['intervention_precision']):.3f}`, harm `{float(held['intervention_harm_rate']):.3f}`.

This verdict means the frozen local algorithm beat strongest on the held-out synthetic set and did not show a real-data over-smoothing regression under the recorded diagnostics. It is not a Production or real-data ground-truth claim.

## Real-data summary

- ch3 Balanced modification fraction: `{ch3_value('balanced', 'STRONGEST_SEGMENT_RESCUE', 'modification_fraction'):.6f}`; large jumps `{ch3_value('balanced', 'FRAMEWISE_STRONGEST', 'large_jump_count'):.0f}`→`{ch3_value('balanced', 'STRONGEST_SEGMENT_RESCUE', 'large_jump_count'):.0f}`.
- ch3 High-time modification fraction: `{ch3_value('high_time_resolution', 'STRONGEST_SEGMENT_RESCUE', 'modification_fraction'):.6f}`; large jumps `{ch3_value('high_time_resolution', 'FRAMEWISE_STRONGEST', 'large_jump_count'):.0f}`→`{ch3_value('high_time_resolution', 'STRONGEST_SEGMENT_RESCUE', 'large_jump_count'):.0f}`.
- relatively-good mean modification fraction: `{group('relatively_good_user_label', 'modification_fraction'):.6f}`.
- corrected medium mean modification fraction: `{group('medium_user_label', 'modification_fraction'):.6f}`.
- ch1–ch4 mean modification fraction: `{group('bad_user_label', 'modification_fraction'):.6f}`.
- No real-data “correction accuracy” is claimed because labels are absent. Segment tables, margins, spectral evidence, anchors, slopes, and support are retained for manual audit.

## Boundaries

The final algorithm never runs a full-record optimizer. NULL Global and TASK-023A IMM/MHT are ch3 comparators only. STFT, search band, Top-K extraction, separation, refinement, raw inputs, and Production were unchanged. Orientation stayed diagnostic (`weight=0`). No AI or promotion was started.
"""


def _accepted(decision: SegmentDecision) -> bool:
    return decision.status in {RescueStatus.ACCEPTED_R1, RescueStatus.ACCEPTED_R2}


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
            command,
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        ).stdout.strip()
        for key, command in commands.items()
    }


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest().upper()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def _upstream_hashes() -> dict[str, str]:
    paths = {
        "stft": ROOT / "src/dps_studio/core/time_frequency/stft.py",
        "top_k": ROOT / "src/dps_studio/core/ridge/global_path.py",
        "production_reselection": ROOT / "src/dps_studio/core/ridge/reselection.py",
        "production_selection": ROOT / "src/dps_studio/core/ridge/selection.py",
    }
    return {name: sha256_file(path) for name, path in paths.items()}


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
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
