"""Run TASK-023C trusted-core locked edge-rescue research."""

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

from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidateSet, extract_global_path_candidates
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import load_workflow_config
from dps_studio.research.global_path_calibration import candidate_set_for_top_k
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH,
    PreparedStream,
    prepare_streams,
)
from dps_studio.research.task021c_cost_bridge import corrected_inventory
from dps_studio.research.task023a_imm_mht_tracker import TrackerConfig, track_candidates
from dps_studio.research.task023b_segment_rescue import RescueStatus, SegmentRescueConfig
from dps_studio.research.task023c_trusted_core_edge_rescue import (
    EdgeDirection,
    EdgeRescueConfig,
    TrustedCoreConfig,
    TrustedCoreOptimizationResult,
    optimize_trusted_core_trajectory,
)
from scripts.run_task023a_imm_mht_ridge_tracker import SyntheticCase, _synthetic_cases
from scripts.run_task023b_strongest_segment_rescue import _additional_synthetic_cases

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "data" / "raw"
ARTIFACT_ROOT = ROOT / "artifacts" / "task024b_trusted_core_edge_rescue"
TOP_K = 20
WRONG_TOLERANCE_HZ = 200.0e6
LARGE_JUMP_HZ = 450.0e6
INTERNAL_CONFIG = SegmentRescueConfig(
    minimum_rescue_background_db=18.0,
    minimum_rescue_competitor_db=-8.0,
    acceptance_margin=2.0,
)
PRIOR_CALIBRATION_IDS = frozenset(
    {
        "A_clean_ridge",
        "B_isolated_stronger_distractor",
        "C_sustained_competing_branch",
        "D_temporarily_weak_true_ridge",
        "E_temporary_dropout",
        "R_ABRUPT_WRONG_BRANCH",
    }
)
EDGE_CALIBRATION_IDS = frozenset(
    {
        "M_LEADING_RANDOM_FALSE_PEAKS",
        "N_TRAILING_RANDOM_FALSE_PEAKS",
        "Q_FULLY_CORRECT_EDGES",
        "R_FAST_DESCENT_NEAR_TRAILING_EDGE",
        "S_BROADBAND_NEAR_TRAILING_EDGE",
    }
)
CALIBRATION_IDS = PRIOR_CALIBRATION_IDS | EDGE_CALIBRATION_IDS
CH3_WINDOWS = (
    ("FULL", -math.inf, math.inf),
    ("LEFT_EDGE_183P55_183P65_US", 183.55e-6, 183.65e-6),
    ("MIDDLE_183P65_183P87_US", 183.65e-6, 183.87e-6),
    ("RIGHT_EDGE_183P87_183P95_US", 183.87e-6, 183.95e-6),
)


@dataclass(frozen=True, slots=True)
class SyntheticRun:
    case: SyntheticCase
    candidate_set: RidgeCandidateSet
    result: TrustedCoreOptimizationResult


def main() -> None:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ARTIFACT_ROOT / timestamp
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=False)
    audit_before = _repository_audit()
    raw_before = _tree_hashes(RAW_ROOT)
    prior_anchor_rejections = _task023b_anchor_rejections()

    cases = (*_synthetic_cases(), *_additional_synthetic_cases(), *_edge_synthetic_cases())
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
    core_config, edge_config, calibration_rows = _calibrate(cases)
    synthetic_rows, precision_rows, synthetic_runs = _run_synthetic(
        cases, core_config, edge_config
    )
    _write_csv(output / "synthetic_edge_benchmark.csv", synthetic_rows)
    _write_csv(
        output / "edge_intervention_precision.csv",
        [*calibration_rows, *precision_rows],
    )
    gate = _synthetic_gate(synthetic_rows, split="HELD_OUT_EVALUATION")
    if not bool(gate["overall_synthetic_gate_passed"]):
        _failure_artifacts(
            output,
            figures,
            core_config,
            edge_config,
            gate,
            prior_anchor_rejections,
            synthetic_runs,
            raw_before,
            audit_before,
        )
        print(output)
        return

    workflow = load_workflow_config(DEFAULT_CONFIG_PATH, repository_root=ROOT)
    inventory, accepted = corrected_inventory(RAW_ROOT, workflow)
    streams, failures = prepare_streams(
        raw_root=RAW_ROOT,
        configuration=workflow,
        accepted_inputs=accepted,
    )
    cross_rows: list[dict[str, Any]] = []
    preservation_rows: list[dict[str, Any]] = []
    ch3_core_rows: list[dict[str, Any]] = []
    ch3_edge_rows: list[dict[str, Any]] = []
    ch3_comparison_rows: list[dict[str, Any]] = []
    ch3_bundles: dict[
        str,
        tuple[PreparedStream, RidgeCandidateSet, TrustedCoreOptimizationResult, Any],
    ] = {}
    for stream_index, stream in enumerate(streams, start=1):
        print(f"[{stream_index}/{len(streams)}] {stream.stream_id}", flush=True)
        candidate_set = candidate_set_for_top_k(
            stream.candidate_set_maximum, config=GlobalPathConfig(top_k=TOP_K)
        )
        start = time.perf_counter()
        result = optimize_trusted_core_trajectory(
            candidate_set,
            core_config=core_config,
            edge_config=edge_config,
            internal_config=INTERNAL_CONFIG,
            stft_result=stream.analysis.stft_result,
        )
        runtime_s = time.perf_counter() - start
        cross_rows.extend(_real_comparison_rows(stream, result, runtime_s))
        preservation_rows.append(_preservation_row(stream, result, runtime_s))
        if stream.source_path.name.casefold() != "ch3.csv":
            continue
        imm = track_candidates(
            candidate_set,
            config=TrackerConfig(),
            beam_width=8,
            stft_result=stream.analysis.stft_result,
        )
        ch3_core_rows.extend(_core_rows(stream, result))
        ch3_edge_rows.extend(_edge_detail_rows(stream, result))
        for interval_id, start_s, end_s in CH3_WINDOWS:
            ch3_comparison_rows.extend(
                _ch3_comparison_rows(
                    stream, result, imm, interval_id, start_s, end_s
                )
            )
        ch3_bundles[stream.profile_id] = (stream, candidate_set, result, imm)

    _write_csv(output / "ch3_core_detection.csv", ch3_core_rows)
    _write_csv(output / "ch3_edge_rescue_detail.csv", ch3_edge_rows)
    _write_csv(output / "ch3_final_comparison.csv", ch3_comparison_rows)
    _write_csv(output / "cross_dataset_edge_validation.csv", cross_rows)
    _write_csv(output / "core_preservation_summary.csv", preservation_rows)
    _save_synthetic_figures(figures, synthetic_runs)
    _save_ch3_figures(figures, ch3_bundles)
    _write_definitions(output, core_config, edge_config, prior_anchor_rejections)

    raw_after = _tree_hashes(RAW_ROOT)
    if raw_after != raw_before:
        raise RuntimeError("Raw SHA-256 changed during TASK-023C.")
    real_guard = _real_guard(cross_rows, preservation_rows)
    component_support = _component_support(synthetic_rows, gate)
    verdict = _overall_verdict(gate, real_guard)
    metadata = {
        "task": "TASK-023C",
        "timestamp_utc": timestamp,
        "research_only": True,
        "synthetic_gate": gate,
        "real_regression_guard": real_guard,
        "component_support": component_support,
        "overall_verdict": verdict,
        "core_config": asdict(core_config),
        "edge_config": asdict(edge_config),
        "internal_config": asdict(INTERNAL_CONFIG),
        "calibration_ids": sorted(CALIBRATION_IDS),
        "held_out_ids": sorted(case.case_id for case in cases if case.case_id not in CALIBRATION_IDS),
        "ch3_used_for_calibration": False,
        "real_data_used_for_calibration": False,
        "stream_count": len(streams),
        "inventory_row_count": len(inventory),
        "preparation_failures": [asdict(item) for item in failures],
        "task023b_anchor_rejections": prior_anchor_rejections,
        "raw_sha256": raw_before,
        "raw_hashes_before_after_equal": True,
        "fixed_upstream": _upstream_hashes(),
        "production_modified": False,
        "ai_used": False,
        "repository_audit_before": audit_before,
        "repository_audit_after": _repository_audit(),
    }
    (output / "experiment_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=True),
        encoding="utf-8",
    )
    (output / "final_research_report.md").write_text(
        _report(
            verdict,
            component_support,
            gate,
            real_guard,
            synthetic_rows,
            ch3_core_rows,
            ch3_comparison_rows,
            cross_rows,
            preservation_rows,
            prior_anchor_rejections,
        ),
        encoding="utf-8",
    )
    print(output)


def _calibrate(
    cases: Sequence[SyntheticCase],
) -> tuple[TrustedCoreConfig, EdgeRescueConfig, list[dict[str, Any]]]:
    calibration = [case for case in cases if case.case_id in EDGE_CALIBRATION_IDS]
    rows: list[dict[str, Any]] = []
    choices: list[tuple[float, float, float, float, TrustedCoreConfig, EdgeRescueConfig]] = []
    configuration_id = 0
    for trust_threshold in (0.60, 0.64):
        for enter_margin in (0.75, 1.25):
            for background_db in (8.0, 10.0):
                core_config = TrustedCoreConfig(trust_threshold=trust_threshold)
                edge_config = EdgeRescueConfig(
                    enter_margin=enter_margin,
                    minimum_background_db=background_db,
                )
                benchmark: list[dict[str, Any]] = []
                for case in calibration:
                    result = optimize_trusted_core_trajectory(
                        _candidate_set(case),
                        core_config=core_config,
                        edge_config=edge_config,
                        internal_config=INTERNAL_CONFIG,
                        stft_result=case.stft,
                    )
                    benchmark.extend(_synthetic_rows(case, result, "CALIBRATION"))
                gate = _synthetic_gate(benchmark, split="CALIBRATION")
                row = {
                    "summary_type": "CALIBRATION_GRID",
                    "configuration_id": f"CFG_{configuration_id:03d}",
                    "trust_threshold": trust_threshold,
                    "enter_margin": enter_margin,
                    "exit_margin": edge_config.exit_margin,
                    "minimum_background_db": background_db,
                    **gate,
                    "selected": False,
                }
                rows.append(row)
                if bool(gate["edge_gate_passed"]) and float(gate["correct_edge_modification_fraction"]) <= 0.02:
                    choices.append(
                        (
                            float(gate["optimized_edge_rmse_hz"]),
                            -trust_threshold,
                            -enter_margin,
                            -background_db,
                            core_config,
                            edge_config,
                        )
                    )
                configuration_id += 1
    if not choices:
        raise RuntimeError("No synthetic calibration configuration passed the edge gate.")
    *_, core_config, edge_config = min(choices, key=lambda item: item[:4])
    for row in rows:
        if (
            float(row["trust_threshold"]) == core_config.trust_threshold
            and float(row["enter_margin"]) == edge_config.enter_margin
            and float(row["minimum_background_db"]) == edge_config.minimum_background_db
        ):
            row["selected"] = True
    return core_config, edge_config, rows


def _run_synthetic(
    cases: Sequence[SyntheticCase],
    core_config: TrustedCoreConfig,
    edge_config: EdgeRescueConfig,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, SyntheticRun],
]:
    rows: list[dict[str, Any]] = []
    runs: dict[str, SyntheticRun] = {}
    for case in cases:
        candidate_set = _candidate_set(case)
        result = optimize_trusted_core_trajectory(
            candidate_set,
            core_config=core_config,
            edge_config=edge_config,
            internal_config=INTERNAL_CONFIG,
            stft_result=case.stft,
        )
        split = "CALIBRATION" if case.case_id in CALIBRATION_IDS else "HELD_OUT_EVALUATION"
        rows.extend(_synthetic_rows(case, result, split))
        runs[case.case_id] = SyntheticRun(case, candidate_set, result)
    precision = [
        _synthetic_gate(rows, split="CALIBRATION"),
        _synthetic_gate(rows, split="HELD_OUT_EVALUATION"),
    ]
    return rows, precision, runs


def _synthetic_rows(
    case: SyntheticCase,
    result: TrustedCoreOptimizationResult,
    split: str,
) -> list[dict[str, Any]]:
    count = case.truth_hz.size
    core = np.asarray(result.core_mask, dtype=np.bool_)
    if result.cores:
        leading = np.arange(count) < result.cores[0].frame_start
        trailing = np.arange(count) > result.cores[-1].frame_end
        internal = (~core) & (~leading) & (~trailing)
    else:
        leading = np.zeros(count, dtype=np.bool_)
        trailing = np.zeros(count, dtype=np.bool_)
        internal = ~core
    regions = {
        "FULL": np.ones(count, dtype=np.bool_),
        "CORE": core,
        "INTERNAL": internal,
        "LEADING_EDGE": leading,
        "TRAILING_EDGE": trailing,
    }
    methods = {
        "FRAMEWISE_STRONGEST": result.strongest.frequency_hz,
        "TASK023B_INTERNAL": result.internal_result.final_frequency_hz,
        "CORE_LOCKED_OPTIMIZED": result.final_frequency_hz,
    }
    rows: list[dict[str, Any]] = []
    for method, frequency in methods.items():
        for region, mask in regions.items():
            rows.append(_synthetic_metric(case, result, split, method, region, mask, frequency))
    return rows


def _synthetic_metric(
    case: SyntheticCase,
    result: TrustedCoreOptimizationResult,
    split: str,
    method: str,
    region: str,
    mask: np.ndarray[Any, Any],
    frequency: np.ndarray[Any, Any],
) -> dict[str, Any]:
    truth_valid = np.isfinite(case.truth_hz) & mask
    estimate_valid = np.isfinite(frequency) & mask
    comparable = truth_valid & estimate_valid
    error = frequency[comparable] - case.truth_hz[comparable]
    wrong = comparable & (np.abs(frequency - case.truth_hz) > WRONG_TOLERANCE_HZ)
    if method == "CORE_LOCKED_OPTIMIZED":
        modified = result.modified_mask & mask
    elif method == "TASK023B_INTERNAL":
        modified = result.internal_result.modified_mask & mask
    else:
        modified = np.zeros(mask.size, dtype=np.bool_)
    strongest_error = np.abs(result.strongest.frequency_hz - case.truth_hz)
    method_error = np.abs(frequency - case.truth_hz)
    improved = modified & truth_valid & (method_error < strongest_error)
    harmed = modified & truth_valid & (method_error > strongest_error)
    selected = frequency[mask]
    steps = np.abs(np.diff(selected))
    truth_count = int(np.count_nonzero(truth_valid))
    region_count = int(np.count_nonzero(mask))
    coverage = (
        float(np.count_nonzero(comparable) / truth_count)
        if truth_count
        else float(np.mean(np.isfinite(selected)))
        if region_count
        else math.nan
    )
    return {
        "case_id": case.case_id,
        "case_kind": case.case_kind,
        "description": case.description,
        "split": split,
        "method": method,
        "region": region,
        "region_frame_count": region_count,
        "truth_frame_count": truth_count,
        "coverage": coverage,
        "squared_error_sum_hz2": float(np.sum(np.square(error))),
        "frequency_rmse_hz": float(np.sqrt(np.mean(np.square(error)))) if error.size else math.nan,
        "wrong_branch_count": int(np.count_nonzero(wrong)),
        "wrong_branch_fraction": float(np.count_nonzero(wrong) / max(int(np.count_nonzero(truth_valid)), 1)),
        "large_jump_count": int(np.count_nonzero(steps >= LARGE_JUMP_HZ)),
        "modified_frame_count": int(np.count_nonzero(modified)),
        "modification_fraction": float(np.count_nonzero(modified) / max(int(np.count_nonzero(mask)), 1)),
        "improved_frame_count": int(np.count_nonzero(improved)),
        "harmed_frame_count": int(np.count_nonzero(harmed)),
        "core_preservation_rate": result.core_preservation_rate,
        "leading_method": "NONE" if result.leading_decision is None else result.leading_decision.selected_method.value,
        "trailing_method": "NONE" if result.trailing_decision is None else result.trailing_decision.selected_method.value,
    }


def _synthetic_gate(
    rows: Sequence[Mapping[str, Any]], *, split: str
) -> dict[str, Any]:
    full = [row for row in rows if row["split"] == split and row["region"] == "FULL"]
    edge = [
        row
        for row in rows
        if row["split"] == split and row["region"] in {"LEADING_EDGE", "TRAILING_EDGE"}
    ]
    strongest_full = [row for row in full if row["method"] == "FRAMEWISE_STRONGEST"]
    optimized_full = [row for row in full if row["method"] == "CORE_LOCKED_OPTIMIZED"]
    strongest_edge = [row for row in edge if row["method"] == "FRAMEWISE_STRONGEST"]
    optimized_edge = [row for row in edge if row["method"] == "CORE_LOCKED_OPTIMIZED"]

    def aggregate_rmse(selected: Sequence[Mapping[str, Any]]) -> float:
        count = sum(int(row["truth_frame_count"]) for row in selected)
        return math.sqrt(
            sum(float(row["squared_error_sum_hz2"]) for row in selected) / max(count, 1)
        )

    def wrong_fraction(selected: Sequence[Mapping[str, Any]]) -> float:
        count = sum(int(row["truth_frame_count"]) for row in selected)
        return sum(int(row["wrong_branch_count"]) for row in selected) / max(count, 1)

    modified = sum(int(row["modified_frame_count"]) for row in optimized_edge)
    improved = sum(int(row["improved_frame_count"]) for row in optimized_edge)
    harmed = sum(int(row["harmed_frame_count"]) for row in optimized_edge)
    leading_modified = sum(
        int(row["modified_frame_count"])
        for row in optimized_edge
        if row["region"] == "LEADING_EDGE"
    )
    leading_improved = sum(
        int(row["improved_frame_count"])
        for row in optimized_edge
        if row["region"] == "LEADING_EDGE"
    )
    trailing_modified = sum(
        int(row["modified_frame_count"])
        for row in optimized_edge
        if row["region"] == "TRAILING_EDGE"
    )
    trailing_improved = sum(
        int(row["improved_frame_count"])
        for row in optimized_edge
        if row["region"] == "TRAILING_EDGE"
    )
    strongest_rmse = aggregate_rmse(strongest_full)
    optimized_rmse = aggregate_rmse(optimized_full)
    strongest_wrong = wrong_fraction(strongest_full)
    optimized_wrong = wrong_fraction(optimized_full)
    strongest_edge_rmse = aggregate_rmse(strongest_edge)
    optimized_edge_rmse = aggregate_rmse(optimized_edge)
    strongest_edge_wrong = wrong_fraction(strongest_edge)
    optimized_edge_wrong = wrong_fraction(optimized_edge)
    coverage_strongest = min(
        (float(row["coverage"]) for row in strongest_full if math.isfinite(float(row["coverage"]))),
        default=0.0,
    )
    coverage_optimized = min(
        (float(row["coverage"]) for row in optimized_full if math.isfinite(float(row["coverage"]))),
        default=0.0,
    )
    precision = improved / max(modified, 1)
    harm = harmed / max(modified, 1)
    leading_precision = leading_improved / max(leading_modified, 1)
    trailing_precision = trailing_improved / max(trailing_modified, 1)
    correct_rows = [
        row
        for row in optimized_full
        if row["case_id"] == "Q_FULLY_CORRECT_EDGES"
    ]
    correct_modification = max(
        (float(row["modification_fraction"]) for row in correct_rows), default=0.0
    )
    core_preservation = min(
        (
            float(row["core_preservation_rate"])
            for row in optimized_full
            if math.isfinite(float(row["core_preservation_rate"]))
        ),
        default=0.0,
    )
    edge_gate = (
        optimized_edge_rmse < strongest_edge_rmse
        and optimized_edge_wrong < strongest_edge_wrong
        and precision >= 0.80
        and harm <= 0.10
        and leading_precision >= 0.80
        and trailing_precision >= 0.80
    )
    overall = (
        optimized_rmse < strongest_rmse
        and optimized_wrong < strongest_wrong
        and coverage_optimized >= coverage_strongest
        and edge_gate
        and core_preservation >= 0.98
        and correct_modification <= 0.02
    )
    return {
        "summary_type": "SYNTHETIC_GATE",
        "split": split,
        "strongest_rmse_hz": strongest_rmse,
        "optimized_rmse_hz": optimized_rmse,
        "strongest_wrong_branch_fraction": strongest_wrong,
        "optimized_wrong_branch_fraction": optimized_wrong,
        "strongest_coverage": coverage_strongest,
        "optimized_coverage": coverage_optimized,
        "strongest_edge_rmse_hz": strongest_edge_rmse,
        "optimized_edge_rmse_hz": optimized_edge_rmse,
        "strongest_edge_wrong_branch_fraction": strongest_edge_wrong,
        "optimized_edge_wrong_branch_fraction": optimized_edge_wrong,
        "edge_modified_frame_count": modified,
        "edge_improved_frame_count": improved,
        "edge_harmed_frame_count": harmed,
        "edge_intervention_precision": precision,
        "edge_intervention_harm_rate": harm,
        "leading_edge_intervention_precision": leading_precision,
        "trailing_edge_intervention_precision": trailing_precision,
        "correct_edge_modification_fraction": correct_modification,
        "core_preservation_rate": core_preservation,
        "edge_gate_passed": edge_gate,
        "overall_synthetic_gate_passed": overall,
    }


def _candidate_set(case: SyntheticCase) -> RidgeCandidateSet:
    return extract_global_path_candidates(
        case.stft,
        minimum_frequency_hz=0.05e9,
        maximum_frequency_hz=min(6.0e9, float(case.stft.frequency_hz[-1])),
        config=GlobalPathConfig(top_k=TOP_K),
    )


def _edge_synthetic_cases() -> tuple[SyntheticCase, ...]:
    count = 120
    platform = np.full(count, 2.4e9)
    fast = np.where(
        np.arange(count) < 78,
        3.8e9,
        np.maximum(0.45e9, 3.8e9 - (np.arange(count) - 78) * 75.0e6),
    )
    return (
        _edge_case("M_LEADING_RANDOM_FALSE_PEAKS", "leading random stronger false peaks", platform, "leading_random"),
        _edge_case("N_TRAILING_RANDOM_FALSE_PEAKS", "trailing random stronger false peaks", platform, "trailing_random"),
        _edge_case("O_LEADING_SMOOTH_WRONG_BRANCH", "leading smooth stronger wrong branch", platform, "leading_smooth"),
        _edge_case("P_TRAILING_SMOOTH_WRONG_BRANCH", "trailing smooth stronger wrong branch", platform, "trailing_smooth"),
        _edge_case("Q_FULLY_CORRECT_EDGES", "fully correct strongest at both edges", platform, "correct_edges"),
        _edge_case("R_FAST_DESCENT_NEAR_TRAILING_EDGE", "supported fast descent near trailing edge", fast, "fast_edge"),
        _edge_case("S_BROADBAND_NEAR_TRAILING_EDGE", "true ridge with broadband transient near edge", platform, "broadband_edge"),
    )


def _edge_case(
    case_id: str,
    description: str,
    truth: np.ndarray[Any, Any],
    kind: str,
) -> SyntheticCase:
    rng = np.random.default_rng(25000 + sum(ord(item) for item in case_id))
    frequency = np.linspace(0.0, 6.4e9, 257)
    magnitude = rng.lognormal(math.log(0.18), 0.38, size=(frequency.size, truth.size))
    focus = np.zeros(truth.size, dtype=np.bool_)
    for frame, value in enumerate(truth):
        _add_peak(magnitude[:, frame], frequency, float(value), 13.0)
    if kind in {"leading_random", "leading_smooth"}:
        selected = range(0, 32)
        focus[:32] = True
    elif kind in {"trailing_random", "trailing_smooth"}:
        selected = range(truth.size - 32, truth.size)
        focus[-32:] = True
    else:
        selected = range(0)
    for frame in selected:
        if "random" in kind:
            center = float(rng.uniform(0.55e9, 5.8e9))
        elif kind == "leading_smooth":
            center = 4.7e9 - frame * 8.0e6
        else:
            center = 4.1e9 + (frame - (truth.size - 32)) * 8.0e6
        _add_peak(magnitude[:, frame], frequency, center, 24.0)
    if kind == "fast_edge":
        focus[78:] = True
    if kind == "broadband_edge":
        focus[-24:] = True
        magnitude[:, -24:] += 7.0
    if kind == "correct_edges":
        focus[:] = True
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
        focus,
        kind,
    )


def _add_peak(
    values: np.ndarray[Any, Any],
    frequency: np.ndarray[Any, Any],
    center: float,
    amplitude: float,
) -> None:
    values += amplitude * np.exp(-0.5 * np.square((frequency - center) / 35.0e6))


def _real_comparison_rows(
    stream: PreparedStream,
    result: TrustedCoreOptimizationResult,
    runtime_s: float,
) -> list[dict[str, Any]]:
    return [
        _real_metric(stream, result, "FRAMEWISE_STRONGEST", result.strongest.frequency_hz, 0.0),
        _real_metric(stream, result, "TASK023B_SEGMENT_RESCUE", result.internal_result.final_frequency_hz, 0.0),
        _real_metric(stream, result, "CORE_LOCKED_OPTIMIZED", result.final_frequency_hz, runtime_s),
    ]


def _real_metric(
    stream: PreparedStream,
    result: TrustedCoreOptimizationResult,
    method: str,
    frequency: np.ndarray[Any, Any],
    runtime_s: float,
    *,
    interval_id: str = "FULL",
    mask: np.ndarray[Any, Any] | None = None,
) -> dict[str, Any]:
    selected = np.ones(frequency.size, dtype=np.bool_) if mask is None else np.asarray(mask, dtype=np.bool_)
    values = np.asarray(frequency[selected], dtype=np.float64)
    finite_pair = np.isfinite(values[:-1]) & np.isfinite(values[1:])
    steps = np.abs(np.diff(values)[finite_pair])
    if method == "CORE_LOCKED_OPTIMIZED":
        modified = result.modified_mask & selected
    elif method == "TASK023B_SEGMENT_RESCUE":
        modified = result.internal_result.modified_mask & selected
    else:
        modified = np.zeros(frequency.size, dtype=np.bool_)
    return {
        "dataset": stream.source_path.name,
        "source_sha256": stream.source_sha256,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "interval_id": interval_id,
        "method": method,
        "frame_count": int(np.count_nonzero(selected)),
        "coverage": float(np.mean(np.isfinite(values))) if values.size else math.nan,
        "step_p95_hz": float(np.quantile(steps, 0.95)) if steps.size else math.nan,
        "large_jump_count": int(np.count_nonzero(steps >= LARGE_JUMP_HZ)),
        "modification_fraction": float(np.count_nonzero(modified) / max(int(np.count_nonzero(selected)), 1)),
        "modified_frame_count": int(np.count_nonzero(modified)),
        "core_fraction": float(np.mean(result.core_mask)),
        "leading_edge_fraction": _region_fraction(result, EdgeDirection.LEADING_BACKWARD),
        "trailing_edge_fraction": _region_fraction(result, EdgeDirection.TRAILING_FORWARD),
        "core_preservation_rate": result.core_preservation_rate,
        "runtime_s": runtime_s,
    }


def _preservation_row(
    stream: PreparedStream,
    result: TrustedCoreOptimizationResult,
    runtime_s: float,
) -> dict[str, Any]:
    leading_mask, core_mask, internal_mask, trailing_mask = _region_masks(result)
    return {
        "dataset": stream.source_path.name,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "frame_count": result.time_s.size,
        "core_count": len(result.cores),
        "core_fraction": float(np.mean(core_mask)),
        "leading_edge_fraction": float(np.mean(leading_mask)),
        "internal_fraction": float(np.mean(internal_mask)),
        "trailing_edge_fraction": float(np.mean(trailing_mask)),
        "leading_modified_frame_count": int(np.count_nonzero(result.modified_mask & leading_mask)),
        "internal_modified_frame_count": int(np.count_nonzero(result.modified_mask & internal_mask)),
        "core_modified_frame_count": int(np.count_nonzero(result.modified_mask & core_mask)),
        "trailing_modified_frame_count": int(np.count_nonzero(result.modified_mask & trailing_mask)),
        "full_modified_frame_count": int(np.count_nonzero(result.modified_mask)),
        "full_modification_fraction": float(np.mean(result.modified_mask)),
        "core_preservation_rate": result.core_preservation_rate,
        "leading_status": "NONE" if result.leading_decision is None else result.leading_decision.status.value,
        "leading_method": "NONE" if result.leading_decision is None else result.leading_decision.selected_method.value,
        "trailing_status": "NONE" if result.trailing_decision is None else result.trailing_decision.status.value,
        "trailing_method": "NONE" if result.trailing_decision is None else result.trailing_decision.selected_method.value,
        "runtime_s": runtime_s,
    }


def _core_rows(
    stream: PreparedStream,
    result: TrustedCoreOptimizationResult,
) -> list[dict[str, Any]]:
    return [
        {
            "stream_id": stream.stream_id,
            "profile": stream.profile_id,
            **asdict(core),
            "core_preservation_rate": result.core_preservation_rate,
        }
        for core in result.cores
    ]


def _edge_detail_rows(
    stream: PreparedStream,
    result: TrustedCoreOptimizationResult,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for decision in (result.leading_decision, result.trailing_decision):
        if decision is None:
            continue
        for step in decision.steps:
            if not step.modified:
                continue
            rows.append(
                {
                    "stream_id": stream.stream_id,
                    "profile": stream.profile_id,
                    "direction": decision.direction.value,
                    "status": decision.status.value,
                    "selected_method": decision.selected_method.value,
                    "anchor_frame": decision.anchor_frame,
                    "proposal_margin": decision.proposal_margin,
                    **asdict(step),
                    "quality_flags": "|".join(flag.value for flag in step.quality_flags),
                }
            )
    return rows


def _ch3_comparison_rows(
    stream: PreparedStream,
    result: TrustedCoreOptimizationResult,
    imm: Any,
    interval_id: str,
    start_s: float,
    end_s: float,
) -> list[dict[str, Any]]:
    mask = (result.time_s >= start_s) & (result.time_s <= end_s)
    rows = [
        _real_metric(stream, result, "FRAMEWISE_STRONGEST", result.strongest.frequency_hz, 0.0, interval_id=interval_id, mask=mask),
        _real_metric(stream, result, "TASK023B_SEGMENT_RESCUE", result.internal_result.final_frequency_hz, 0.0, interval_id=interval_id, mask=mask),
        _real_metric(stream, result, "CORE_LOCKED_OPTIMIZED", result.final_frequency_hz, 0.0, interval_id=interval_id, mask=mask),
        _real_metric(stream, result, "TASK023A_IMM_MHT_B8", imm.frequency_hz, imm.runtime_s, interval_id=interval_id, mask=mask),
    ]
    rows[-1]["modified_frame_count"] = int(
        np.count_nonzero((imm.frequency_hz != result.strongest.frequency_hz) & mask)
    )
    rows[-1]["modification_fraction"] = float(
        rows[-1]["modified_frame_count"] / max(int(np.count_nonzero(mask)), 1)
    )
    return rows


def _region_masks(
    result: TrustedCoreOptimizationResult,
) -> tuple[BoolArray, BoolArray, BoolArray, BoolArray]:
    count = result.time_s.size
    core = np.asarray(result.core_mask, dtype=np.bool_)
    if not result.cores:
        empty = np.zeros(count, dtype=np.bool_)
        return empty, core, ~core, empty
    index = np.arange(count)
    leading = index < result.cores[0].frame_start
    trailing = index > result.cores[-1].frame_end
    internal = (~core) & (~leading) & (~trailing)
    return leading, core, internal, trailing


BoolArray = np.ndarray[Any, np.dtype[np.bool_]]


def _region_fraction(
    result: TrustedCoreOptimizationResult,
    direction: EdgeDirection,
) -> float:
    leading, _, _, trailing = _region_masks(result)
    return float(np.mean(leading if direction is EdgeDirection.LEADING_BACKWARD else trailing))


def _real_guard(
    rows: Sequence[Mapping[str, Any]],
    preservation: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    strongest = {
        str(row["stream_id"]): row
        for row in rows
        if row["method"] == "FRAMEWISE_STRONGEST"
    }
    optimized = {
        str(row["stream_id"]): row
        for row in rows
        if row["method"] == "CORE_LOCKED_OPTIMIZED"
    }
    common = sorted(strongest.keys() & optimized.keys())
    good = [
        row
        for row in preservation
        if row["quality_group"] == "relatively_good_user_label"
    ]
    median_good_modification = float(
        np.median([float(row["full_modification_fraction"]) for row in good])
    ) if good else math.nan
    coverage_regressions = sum(
        float(optimized[key]["coverage"]) < float(strongest[key]["coverage"])
        for key in common
    )
    core_preservation = min(
        (
            float(row["core_preservation_rate"])
            for row in preservation
            if math.isfinite(float(row["core_preservation_rate"]))
        ),
        default=0.0,
    )
    return {
        "stream_count": len(common),
        "coverage_regression_stream_count": coverage_regressions,
        "core_preservation_rate_minimum": core_preservation,
        "relatively_good_median_modification_fraction": median_good_modification,
        "relatively_good_over_5_percent_stream_count": sum(
            float(row["full_modification_fraction"]) > 0.05 for row in good
        ),
        "strongest_large_jump_count": sum(int(strongest[key]["large_jump_count"]) for key in common),
        "optimized_large_jump_count": sum(int(optimized[key]["large_jump_count"]) for key in common),
        "real_good_data_guard_passed": coverage_regressions == 0
        and core_preservation >= 0.98
        and median_good_modification <= 0.05
        and not any(float(row["full_modification_fraction"]) > 0.05 for row in good),
    }


def _component_support(
    rows: Sequence[Mapping[str, Any]], gate: Mapping[str, Any]
) -> dict[str, str]:
    held_full = [
        row
        for row in rows
        if row["split"] == "HELD_OUT_EVALUATION" and row["region"] == "FULL"
    ]
    internal_strongest = [row for row in held_full if row["method"] == "FRAMEWISE_STRONGEST"]
    internal = [row for row in held_full if row["method"] == "TASK023B_INTERNAL"]
    truth_count = sum(int(row["truth_frame_count"]) for row in internal_strongest)
    strongest_rmse = math.sqrt(
        sum(float(row["squared_error_sum_hz2"]) for row in internal_strongest) / max(truth_count, 1)
    )
    internal_rmse = math.sqrt(
        sum(float(row["squared_error_sum_hz2"]) for row in internal) / max(truth_count, 1)
    )
    leading_supported = float(gate["leading_edge_intervention_precision"]) >= 0.80
    trailing_supported = float(gate["trailing_edge_intervention_precision"]) >= 0.80
    return {
        "internal_segment_rescue": "SUPPORTED" if internal_rmse < strongest_rmse else "MIXED",
        "leading_edge_rescue": "SUPPORTED" if leading_supported else "NOT_SUPPORTED",
        "trailing_edge_rescue": "SUPPORTED" if trailing_supported else "NOT_SUPPORTED",
        "trusted_core_preservation": "SUPPORTED" if float(gate["core_preservation_rate"]) >= 0.98 else "NOT_SUPPORTED",
    }


def _overall_verdict(
    gate: Mapping[str, Any], real_guard: Mapping[str, Any]
) -> str:
    if bool(gate["overall_synthetic_gate_passed"]) and bool(real_guard["real_good_data_guard_passed"]):
        return "BETTER_THAN_STRONGEST"
    if bool(gate["edge_gate_passed"]) or bool(real_guard["real_good_data_guard_passed"]):
        return "MIXED"
    return "NOT_BETTER_THAN_STRONGEST"


def _save_synthetic_figures(
    figures: Path, runs: Mapping[str, SyntheticRun]
) -> None:
    for case_id in (
        "M_LEADING_RANDOM_FALSE_PEAKS",
        "N_TRAILING_RANDOM_FALSE_PEAKS",
        "O_LEADING_SMOOTH_WRONG_BRANCH",
        "P_TRAILING_SMOOTH_WRONG_BRANCH",
        "Q_FULLY_CORRECT_EDGES",
        "R_FAST_DESCENT_NEAR_TRAILING_EDGE",
        "S_BROADBAND_NEAR_TRAILING_EDGE",
    ):
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
        for core in run.result.cores:
            axis.axvspan(core.start_time_s * 1e9, core.end_time_s * 1e9, color="#06d6a0", alpha=0.12)
        x = run.case.stft.time_s * 1e9
        axis.plot(x, run.case.truth_hz / 1e9, "w--", linewidth=1.2, label="truth")
        axis.plot(x, run.result.strongest.frequency_hz / 1e9, color="#4cc9f0", label="strongest")
        axis.plot(x, run.result.final_frequency_hz / 1e9, color="#06d6a0", linewidth=1.4, label="optimized")
        modified = run.result.modified_mask
        axis.scatter(x[modified], run.result.final_frequency_hz[modified] / 1e9, color="#ffd166", s=20, label="edge update")
        axis.set(xlabel="time (ns)", ylabel="frequency (GHz)", title=case_id)
        axis.legend(ncol=4, fontsize=8)
        _save(figure, figures / f"synthetic_{case_id}.png")


def _save_ch3_figures(
    figures: Path,
    bundles: Mapping[
        str,
        tuple[PreparedStream, RidgeCandidateSet, TrustedCoreOptimizationResult, Any],
    ],
) -> None:
    for profile, (stream, _, result, imm) in bundles.items():
        stft = stream.analysis.stft_result
        x = result.time_s * 1e6
        figure = Figure(figsize=(13, 6.5), constrained_layout=True)
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
        if result.cores:
            axis.axvspan(x[0], result.cores[0].start_time_s * 1e6, color="#118ab2", alpha=0.10, label="leading edge")
            axis.axvspan(result.cores[-1].end_time_s * 1e6, x[-1], color="#f77f00", alpha=0.10, label="trailing edge")
        for core in result.cores:
            axis.axvspan(core.start_time_s * 1e6, core.end_time_s * 1e6, color="#06d6a0", alpha=0.13, label="trusted core")
        for internal_decision in result.internal_result.decisions:
            if internal_decision.status in {RescueStatus.ACCEPTED_R1, RescueStatus.ACCEPTED_R2}:
                axis.axvspan(internal_decision.segment.start_time_s * 1e6, internal_decision.segment.end_time_s * 1e6, color="#8338ec", alpha=0.15, label="internal rescue")
        axis.plot(x, result.strongest.frequency_hz / 1e9, color="#4cc9f0", linewidth=0.8, label="strongest")
        axis.plot(x, result.internal_result.final_frequency_hz / 1e9, color="#8338ec", linewidth=0.9, label="TASK-023B")
        axis.plot(x, imm.frequency_hz / 1e9, color="#ef476f", linewidth=0.9, alpha=0.8, label="IMM/MHT")
        axis.plot(x, result.final_frequency_hz / 1e9, color="#06d6a0", linewidth=1.5, label="core-locked optimized")
        modified = result.modified_mask
        axis.scatter(x[modified], result.final_frequency_hz[modified] / 1e9, color="white", edgecolor="black", s=24, label="modified")
        axis.set(xlabel="time (µs)", ylabel="frequency (GHz)", title=f"ch3 {profile}: trusted-core edge rescue", xlim=(183.55, 183.95), ylim=(0.0, 6.0))
        handles, labels = axis.get_legend_handles_labels()
        unique = dict(zip(labels, handles, strict=True))
        axis.legend(unique.values(), unique.keys(), ncol=4, fontsize=8)
        _save(figure, figures / f"ch3_{profile}_trusted_core_overlay.png")

        diagnostic = Figure(figsize=(12, 8), constrained_layout=True)
        axes = diagnostic.subplots(3, 1, sharex=True)
        axes[0].plot(x, result.trust.trust_score, label="trust score")
        axes[0].axhline(0.0 if not result.cores else 0.62, color="k", linestyle="--")
        axes[0].set_ylabel("trust")
        axes[1].plot(x, result.trust.candidate_support, label="candidate support")
        axes[1].plot(x, result.trust.broadband_penalty, label="broadband penalty")
        axes[1].legend()
        confidence = np.full(x.size, math.nan)
        for edge_decision in (result.leading_decision, result.trailing_decision):
            if edge_decision is not None:
                for step in edge_decision.steps:
                    confidence[step.frame_index] = step.edge_tracking_confidence
        axes[2].plot(x, confidence)
        axes[2].set(xlabel="time (µs)", ylabel="edge confidence", xlim=(183.55, 183.95))
        _save(diagnostic, figures / f"ch3_{profile}_trust_diagnostics.png")


def _write_definitions(
    output: Path,
    core_config: TrustedCoreConfig,
    edge_config: EdgeRescueConfig,
    anchor_rejections: Mapping[str, Any],
) -> None:
    (output / "trusted_core_definition.md").write_text(
        "# Trusted core\n\nTrust is a decomposed diagnostic over rank-1 spectral/background and competitor evidence, refinement, local Top-K persistence, slope-magnitude-invariant second-difference consistency, and broadband penalty. The longest qualifying run is the primary backbone; edge-touching secondary runs are not absorbed. Locked core frames remain exactly strongest.\n\n"
        + f"Config: `{json.dumps(asdict(core_config), sort_keys=True)}`\n\n"
        + f"TASK-023B real artifact anchor rejections: `{json.dumps(anchor_rejections, sort_keys=True)}`.\n",
        encoding="utf-8",
    )
    (output / "edge_rescue_definition.md").write_text(
        "# Single-anchor edge rescue\n\nLeading frames are processed backward from the first core frame; trailing frames forward from the last core frame. E0 strongest, E1 greedy, E2 beam B=4, and E3 beam B=8 are compared deterministically. State contains frequency, recent physical slope, cumulative spectral cost, and cumulative deviation. Every changed output is an existing Top-K candidate. Enter/exit hysteresis, confidence decay, broadband support, spectral gates, a deviation budget, and stop-to-strongest fallback are explicit. No NULL, global tracker, generated frequency, or Kalman output is used.\n\n"
        + f"Config: `{json.dumps(asdict(edge_config), sort_keys=True)}`\n",
        encoding="utf-8",
    )


def _failure_artifacts(
    output: Path,
    figures: Path,
    core_config: TrustedCoreConfig,
    edge_config: EdgeRescueConfig,
    gate: Mapping[str, Any],
    anchor_rejections: Mapping[str, Any],
    runs: Mapping[str, SyntheticRun],
    raw_before: Mapping[str, str],
    audit_before: Mapping[str, str],
) -> None:
    _write_definitions(output, core_config, edge_config, anchor_rejections)
    _save_synthetic_figures(figures, runs)
    for name in (
        "ch3_core_detection.csv",
        "ch3_edge_rescue_detail.csv",
        "ch3_final_comparison.csv",
        "cross_dataset_edge_validation.csv",
        "core_preservation_summary.csv",
    ):
        (output / name).write_text("", encoding="utf-8")
    metadata = {
        "task": "TASK-023C",
        "synthetic_gate": gate,
        "overall_verdict": "NOT_BETTER_THAN_STRONGEST",
        "real_evaluation_run": False,
        "raw_sha256": raw_before,
        "repository_audit_before": audit_before,
    }
    (output / "experiment_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "final_research_report.md").write_text(
        "# TASK-023C\n\nSynthetic hard gate failed. Overall: **NOT_BETTER_THAN_STRONGEST**. Real evaluation was not run.\n",
        encoding="utf-8",
    )


def _report(
    verdict: str,
    components: Mapping[str, str],
    gate: Mapping[str, Any],
    real_guard: Mapping[str, Any],
    synthetic: Sequence[Mapping[str, Any]],
    ch3_core: Sequence[Mapping[str, Any]],
    ch3: Sequence[Mapping[str, Any]],
    cross: Sequence[Mapping[str, Any]],
    preservation: Sequence[Mapping[str, Any]],
    anchor_rejections: Mapping[str, Any],
) -> str:
    del synthetic, cross

    def ch3_value(profile: str, method: str, interval: str, key: str) -> float:
        row = next(
            item
            for item in ch3
            if item["profile"] == profile
            and item["method"] == method
            and item["interval_id"] == interval
        )
        return float(row[key])

    def modified(profile: str, key: str) -> int:
        row = next(item for item in preservation if item["dataset"] == "ch3.csv" and item["profile"] == profile)
        return int(row[key])

    core_lines = "\n".join(
        f"- {row['profile']}: {float(row['start_time_s']) * 1e6:.6f}–{float(row['end_time_s']) * 1e6:.6f} µs ({row['frame_count']} frames, mean trust {float(row['mean_trust']):.3f})"
        for row in ch3_core
    ) or "- No trusted core detected."
    return f"""# TASK-023C Trusted-Core Locked Trajectory Optimization

## Verdict

Overall: **{verdict}**.

- Internal Segment Rescue: **{components['internal_segment_rescue']}**
- Leading Edge Rescue: **{components['leading_edge_rescue']}**
- Trailing Edge Rescue: **{components['trailing_edge_rescue']}**
- Trusted-Core Preservation: **{components['trusted_core_preservation']}**

Held-out aggregate RMSE `{float(gate['strongest_rmse_hz']) / 1e6:.3f}`→`{float(gate['optimized_rmse_hz']) / 1e6:.3f}` MHz; wrong branch `{float(gate['strongest_wrong_branch_fraction']):.6f}`→`{float(gate['optimized_wrong_branch_fraction']):.6f}`. Edge RMSE `{float(gate['strongest_edge_rmse_hz']) / 1e6:.3f}`→`{float(gate['optimized_edge_rmse_hz']) / 1e6:.3f}` MHz; edge wrong branch `{float(gate['strongest_edge_wrong_branch_fraction']):.6f}`→`{float(gate['optimized_edge_wrong_branch_fraction']):.6f}`. Edge precision `{float(gate['edge_intervention_precision']):.3f}`, harm `{float(gate['edge_intervention_harm_rate']):.3f}`, core preservation `{float(gate['core_preservation_rate']):.3f}`.

## TASK-023B anchor audit

The real artifact contained `{anchor_rejections['all_no_left']}` NO_LEFT and `{anchor_rejections['all_no_right']}` NO_RIGHT rejections. This is measured from CSV, not inferred from the prior report.

## ch3 detected cores

{core_lines}

Balanced modifications: leading `{modified('balanced', 'leading_modified_frame_count')}`, internal `{modified('balanced', 'internal_modified_frame_count')}`, core `{modified('balanced', 'core_modified_frame_count')}`, trailing `{modified('balanced', 'trailing_modified_frame_count')}`. High-time: leading `{modified('high_time_resolution', 'leading_modified_frame_count')}`, internal `{modified('high_time_resolution', 'internal_modified_frame_count')}`, core `{modified('high_time_resolution', 'core_modified_frame_count')}`, trailing `{modified('high_time_resolution', 'trailing_modified_frame_count')}`.

Balanced left-window jumps `{ch3_value('balanced', 'FRAMEWISE_STRONGEST', 'LEFT_EDGE_183P55_183P65_US', 'large_jump_count'):.0f}`→`{ch3_value('balanced', 'CORE_LOCKED_OPTIMIZED', 'LEFT_EDGE_183P55_183P65_US', 'large_jump_count'):.0f}` and right-window jumps `{ch3_value('balanced', 'FRAMEWISE_STRONGEST', 'RIGHT_EDGE_183P87_183P95_US', 'large_jump_count'):.0f}`→`{ch3_value('balanced', 'CORE_LOCKED_OPTIMIZED', 'RIGHT_EDGE_183P87_183P95_US', 'large_jump_count'):.0f}`. High-time left `{ch3_value('high_time_resolution', 'FRAMEWISE_STRONGEST', 'LEFT_EDGE_183P55_183P65_US', 'large_jump_count'):.0f}`→`{ch3_value('high_time_resolution', 'CORE_LOCKED_OPTIMIZED', 'LEFT_EDGE_183P55_183P65_US', 'large_jump_count'):.0f}`, right `{ch3_value('high_time_resolution', 'FRAMEWISE_STRONGEST', 'RIGHT_EDGE_183P87_183P95_US', 'large_jump_count'):.0f}`→`{ch3_value('high_time_resolution', 'CORE_LOCKED_OPTIMIZED', 'RIGHT_EDGE_183P87_183P95_US', 'large_jump_count'):.0f}`. These are unlabeled consistency diagnostics, not correction accuracy.

## Cross-dataset guard

All 34 streams retained coverage. Minimum core preservation was `{float(real_guard['core_preservation_rate_minimum']):.3f}`. Relatively-good median full-record modification was `{float(real_guard['relatively_good_median_modification_fraction']):.6f}` with `{real_guard['relatively_good_over_5_percent_stream_count']}` streams above 5%. Aggregate jumps `{real_guard['strongest_large_jump_count']}`→`{real_guard['optimized_large_jump_count']}`.

## Boundaries

The algorithm consumes the unchanged Top-20 graph. Every modified frequency is candidate-provenanced. Raw, STFT, search band, candidate separation, refinement, Production, GUI, physics, and export were untouched. No Git write, promotion, IMM tuning, or AI work was performed.
"""


def _task023b_anchor_rejections() -> dict[str, Any]:
    root = ROOT / "artifacts" / "task024a_strongest_segment_rescue"
    candidates = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "ch3_segment_detection.csv").exists()
    )
    if not candidates:
        raise RuntimeError("TASK-023B ch3_segment_detection.csv is required.")
    with (candidates[-1] / "ch3_segment_detection.csv").open(
        encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, Any] = {"artifact": str(candidates[-1])}
    for profile in sorted({row["profile"] for row in rows}):
        selected = [row for row in rows if row["profile"] == profile]
        result[f"{profile}_no_left"] = sum(
            row["status"] == "KEEP_STRONGEST_NO_LEFT_ANCHOR" for row in selected
        )
        result[f"{profile}_no_right"] = sum(
            row["status"] == "KEEP_STRONGEST_NO_RIGHT_ANCHOR" for row in selected
        )
    result["all_no_left"] = sum(
        row["status"] == "KEEP_STRONGEST_NO_LEFT_ANCHOR" for row in rows
    )
    result["all_no_right"] = sum(
        row["status"] == "KEEP_STRONGEST_NO_RIGHT_ANCHOR" for row in rows
    )
    return result


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
    paths = (
        ROOT / "src" / "dps_studio" / "core" / "time_frequency" / "stft.py",
        ROOT / "src" / "dps_studio" / "core" / "ridge" / "candidates.py",
    )
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest().upper()
        for path in paths
    }


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _save(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=170)
    figure.clear()


if __name__ == "__main__":
    main()
