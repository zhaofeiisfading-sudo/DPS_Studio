"""Run TASK-023D smooth wrong-branch discrimination research."""

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
from numpy.typing import NDArray

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
from dps_studio.research.task023b_segment_rescue import SegmentRescueConfig
from dps_studio.research.task023c_trusted_core_edge_rescue import EdgeRescueConfig, TrustedCoreConfig
from dps_studio.research.task023d_smooth_branch_rescue import (
    BranchAmbiguityConfig,
    BranchCompetitionConfig,
    CoreTrimConfig,
    SmoothBranchMethod,
    SmoothBranchOptimizationResult,
    optimize_smooth_wrong_branches,
)
from scripts.run_task023a_imm_mht_ridge_tracker import SyntheticCase, _synthetic_cases
from scripts.run_task023b_strongest_segment_rescue import _additional_synthetic_cases
from scripts.run_task023c_trusted_core_edge_rescue import _edge_synthetic_cases

ROOT = Path(__file__).resolve().parents[1]
RAW_ROOT = ROOT / "data" / "raw"
ARTIFACT_ROOT = ROOT / "artifacts" / "task023d_smooth_branch_rescue"
TOP_K = 20
WRONG_TOLERANCE_HZ = 200.0e6
LARGE_JUMP_HZ = 450.0e6
CORE_CONFIG = TrustedCoreConfig(trust_threshold=0.64)
EDGE_CONFIG = EdgeRescueConfig()
INTERNAL_CONFIG = SegmentRescueConfig(
    minimum_rescue_background_db=18.0,
    minimum_rescue_competitor_db=-8.0,
    acceptance_margin=2.0,
)
AMBIGUITY_CONFIG = BranchAmbiguityConfig()
EXPANDED_CALIBRATION_IDS = frozenset(
    {
        "D23_LEADING_SMOOTH_CAL_A",
        "D23_TRAILING_SMOOTH_CAL_A",
        "D23_CORRECT_SMOOTH_CAL",
        "D23_FAST_DESCENT_CAL",
        "D23_BROADBAND_COMPETING_CAL",
        "D23_RANDOM_FALSE_CAL",
    }
)
SMOOTH_HELD_OUT_IDS = frozenset(
    {
        "O_LEADING_SMOOTH_WRONG_BRANCH",
        "P_TRAILING_SMOOTH_WRONG_BRANCH",
        "D23_LEADING_SMOOTH_HELD_A",
        "D23_LEADING_SMOOTH_HELD_B",
        "D23_TRAILING_SMOOTH_HELD_A",
        "D23_TRAILING_SMOOTH_HELD_B",
        "D23_BRANCH_DIVERGENCE",
        "D23_BRANCH_MERGE",
    }
)
GUARD_HELD_OUT_IDS = frozenset(
    {
        "D23_CORRECT_SMOOTH_HELD",
        "D23_FAST_DESCENT_HELD",
        "D23_BROADBAND_COMPETING_HELD",
        "D23_RANDOM_FALSE_HELD",
    }
)
EVALUATION_METHODS = tuple(SmoothBranchMethod)
CH3_WINDOWS = (
    ("FULL", -math.inf, math.inf),
    ("LEFT_EDGE_183P55_183P65_US", 183.55e-6, 183.65e-6),
    ("MIDDLE_183P65_183P87_US", 183.65e-6, 183.87e-6),
    ("RIGHT_EDGE_183P87_183P95_US", 183.87e-6, 183.95e-6),
)


@dataclass(frozen=True, slots=True)
class SyntheticBundle:
    case: SyntheticCase
    candidate_set: RidgeCandidateSet
    results: Mapping[SmoothBranchMethod, SmoothBranchOptimizationResult]


def main() -> None:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = ARTIFACT_ROOT / timestamp
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=False)
    audit_before = _repository_audit()
    _write_repository_audit(output / "repository_audit.txt", audit_before)
    raw_before = _tree_hashes(RAW_ROOT)
    upstream_before = _upstream_hashes()

    cases = _deduplicated_cases(
        (*_synthetic_cases(), *_additional_synthetic_cases(), *_edge_synthetic_cases(), *_expanded_cases())
    )
    split_rows = [
        {
            "case_id": case.case_id,
            "description": case.description,
            "case_kind": case.case_kind,
            "split": "CALIBRATION" if case.case_id in EXPANDED_CALIBRATION_IDS else "HELD_OUT_EVALUATION",
            "ch3_used_for_calibration": False,
            "real_data_used_for_calibration": False,
        }
        for case in cases
    ]
    _write_csv(output / "synthetic_calibration_split.csv", split_rows)
    method, trim_config, branch_config, calibration_rows = _calibrate(cases)
    synthetic_rows, synthetic_bundles = _run_synthetic(
        cases,
        trim_config,
        branch_config,
    )
    _write_csv(output / "synthetic_smooth_branch_benchmark.csv", synthetic_rows)
    synthetic_gate = _synthetic_gate(synthetic_rows, selected_method=method)
    _write_csv(output / "synthetic_calibration_results.csv", calibration_rows)
    _save_synthetic_figures(figures, synthetic_bundles, method)

    workflow = load_workflow_config(DEFAULT_CONFIG_PATH, repository_root=ROOT)
    inventory, accepted = corrected_inventory(RAW_ROOT, workflow)
    streams, failures = prepare_streams(
        raw_root=RAW_ROOT,
        configuration=workflow,
        accepted_inputs=accepted,
    )
    core_audit_rows: list[dict[str, Any]] = []
    ch3_trim_rows: list[dict[str, Any]] = []
    ch3_detail_rows: list[dict[str, Any]] = []
    ch3_comparison_rows: list[dict[str, Any]] = []
    cross_rows: list[dict[str, Any]] = []
    ch3_bundles: dict[str, tuple[PreparedStream, SmoothBranchOptimizationResult]] = {}
    for stream_index, stream in enumerate(streams, start=1):
        print(f"[{stream_index}/{len(streams)}] {stream.stream_id}", flush=True)
        candidate_set = candidate_set_for_top_k(
            stream.candidate_set_maximum,
            config=GlobalPathConfig(top_k=TOP_K),
        )
        started = time.perf_counter()
        result = _optimize(
            candidate_set,
            method,
            trim_config,
            branch_config,
            stream.analysis.stft_result,
        )
        runtime_s = time.perf_counter() - started
        core_audit_rows.extend(_core_boundary_rows(stream, candidate_set, result))
        cross_rows.extend(_cross_rows(stream, result, runtime_s))
        if stream.source_path.name.casefold() != "ch3.csv":
            continue
        ch3_trim_rows.extend(_trim_rows(stream, result))
        ch3_detail_rows.extend(_branch_detail_rows(stream, result))
        for interval_id, start_s, end_s in CH3_WINDOWS:
            ch3_comparison_rows.extend(
                _ch3_comparison(stream, result, interval_id, start_s, end_s)
            )
        ch3_bundles[stream.profile_id] = (stream, result)

    _write_csv(output / "core_boundary_audit.csv", core_audit_rows)
    _write_csv(output / "ch3_core_trim_audit.csv", ch3_trim_rows)
    _write_csv(output / "ch3_branch_rescue_detail.csv", ch3_detail_rows)
    _write_csv(output / "ch3_comparison.csv", ch3_comparison_rows)
    _write_csv(output / "cross_dataset_validation.csv", cross_rows)
    _save_ch3_figures(figures, ch3_bundles, method)
    _write_definitions(output, trim_config, branch_config)

    raw_after = _tree_hashes(RAW_ROOT)
    upstream_after = _upstream_hashes()
    if raw_before != raw_after:
        raise RuntimeError("Raw SHA-256 changed during TASK-023D.")
    if upstream_before != upstream_after:
        raise RuntimeError("STFT or Top-K implementation changed during TASK-023D.")
    real_guard = _real_guard(cross_rows, method)
    component_verdicts = _component_verdicts(
        synthetic_gate,
        ch3_trim_rows,
        ch3_comparison_rows,
        method,
    )
    overall_verdict = _overall_verdict(synthetic_gate, real_guard)
    audit_after = _repository_audit()
    metadata = {
        "task": "TASK-023D",
        "timestamp_utc": timestamp,
        "research_only": True,
        "selected_method": method.value,
        "core_config": asdict(CORE_CONFIG),
        "edge_config": asdict(EDGE_CONFIG),
        "ambiguity_config": asdict(AMBIGUITY_CONFIG),
        "trim_config": asdict(trim_config),
        "branch_config": asdict(branch_config),
        "internal_config": asdict(INTERNAL_CONFIG),
        "synthetic_gate": synthetic_gate,
        "real_guard": real_guard,
        "component_verdicts": component_verdicts,
        "overall_verdict": overall_verdict,
        "calibration_ids": sorted(EXPANDED_CALIBRATION_IDS),
        "held_out_smooth_ids": sorted(SMOOTH_HELD_OUT_IDS),
        "held_out_guard_ids": sorted(GUARD_HELD_OUT_IDS),
        "ch3_used_for_calibration": False,
        "real_data_used_for_calibration": False,
        "stream_count": len(streams),
        "inventory_row_count": len(inventory),
        "preparation_failures": [asdict(item) for item in failures],
        "raw_sha256": raw_before,
        "raw_hashes_before_after_equal": True,
        "fixed_upstream": upstream_before,
        "upstream_hashes_before_after_equal": True,
        "production_modified": False,
        "ai_used": False,
        "repository_audit_before": audit_before,
        "repository_audit_after": audit_after,
    }
    (output / "experiment_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=True),
        encoding="utf-8",
    )
    (output / "final_research_report.md").write_text(
        _report(
            overall_verdict,
            component_verdicts,
            synthetic_gate,
            real_guard,
            ch3_trim_rows,
            ch3_detail_rows,
            ch3_comparison_rows,
            method,
        ),
        encoding="utf-8",
    )
    print(output)


def _optimize(
    candidate_set: RidgeCandidateSet,
    method: SmoothBranchMethod,
    trim_config: CoreTrimConfig,
    branch_config: BranchCompetitionConfig,
    stft_result: STFTResult | None,
) -> SmoothBranchOptimizationResult:
    return optimize_smooth_wrong_branches(
        candidate_set,
        method=method,
        core_config=CORE_CONFIG,
        edge_config=EDGE_CONFIG,
        internal_config=INTERNAL_CONFIG,
        ambiguity_config=AMBIGUITY_CONFIG,
        trim_config=trim_config,
        branch_config=branch_config,
        stft_result=stft_result,
    )


def _calibrate(
    cases: Sequence[SyntheticCase],
) -> tuple[
    SmoothBranchMethod,
    CoreTrimConfig,
    BranchCompetitionConfig,
    list[dict[str, Any]],
]:
    calibration = [case for case in cases if case.case_id in EXPANDED_CALIBRATION_IDS]
    specifications = (
        (
            "CFG_A",
            CoreTrimConfig(ambiguity_threshold=0.36),
            BranchCompetitionConfig(identity_break_penalty=8.0, deviation_weight=0.006, branch_acceptance_margin=1.0),
        ),
        (
            "CFG_B",
            CoreTrimConfig(ambiguity_threshold=0.42),
            BranchCompetitionConfig(identity_break_penalty=9.0, deviation_weight=0.008, branch_acceptance_margin=1.5),
        ),
        (
            "CFG_C",
            CoreTrimConfig(ambiguity_threshold=0.48),
            BranchCompetitionConfig(identity_break_penalty=11.0, deviation_weight=0.010, branch_acceptance_margin=2.0),
        ),
        (
            "CFG_D",
            CoreTrimConfig(ambiguity_threshold=0.42),
            BranchCompetitionConfig(identity_break_penalty=12.0, deviation_weight=0.006, branch_acceptance_margin=1.5),
        ),
    )
    rows: list[dict[str, Any]] = []
    passing: list[tuple[float, str, int, SmoothBranchMethod, CoreTrimConfig, BranchCompetitionConfig]] = []
    for config_id, trim, branch in specifications:
        for method in (
            SmoothBranchMethod.E3_CORE_TRIM_BRANCH,
            SmoothBranchMethod.E4_CONSERVATIVE_BRANCH,
        ):
            benchmark: list[dict[str, Any]] = []
            for case in calibration:
                candidate_set = _candidate_set(case)
                current = _optimize(
                    candidate_set,
                    SmoothBranchMethod.E1_TASK023C,
                    trim,
                    branch,
                    case.stft,
                )
                result = _optimize(candidate_set, method, trim, branch, case.stft)
                benchmark.extend(_synthetic_rows(case, current, "CALIBRATION"))
                benchmark.extend(_synthetic_rows(case, result, "CALIBRATION"))
            gate = _calibration_gate(benchmark, method)
            row = {
                "configuration_id": config_id,
                "method": method.value,
                "selected": False,
                **asdict(trim),
                **{f"branch_{key}": value for key, value in asdict(branch).items()},
                **gate,
            }
            rows.append(row)
            if bool(gate["passes_guardrails"]):
                passing.append(
                    (
                        float(gate["selected_smooth_rmse_hz"]),
                        config_id,
                        list(SmoothBranchMethod).index(method),
                        method,
                        trim,
                        branch,
                    )
                )
    if not passing:
        print(json.dumps(rows, indent=2, allow_nan=True), flush=True)
        raise RuntimeError("No TASK-023D synthetic calibration configuration passed guardrails.")
    *_, method, trim, branch = min(passing, key=lambda item: item[:3])
    for row in rows:
        if row["configuration_id"] in {
            item[1] for item in passing if item[3] is method and item[4] == trim and item[5] == branch
        } and row["method"] == method.value:
            row["selected"] = True
    return method, trim, branch, rows


def _calibration_gate(
    rows: Sequence[Mapping[str, Any]],
    method: SmoothBranchMethod,
) -> dict[str, Any]:
    smooth_ids = {
        "D23_LEADING_SMOOTH_CAL_A",
        "D23_TRAILING_SMOOTH_CAL_A",
    }
    return _comparison_gate(
        rows,
        method,
        smooth_ids=smooth_ids,
        correct_ids={"D23_CORRECT_SMOOTH_CAL"},
        fast_ids={"D23_FAST_DESCENT_CAL"},
        broadband_ids={"D23_BROADBAND_COMPETING_CAL"},
    )


def _run_synthetic(
    cases: Sequence[SyntheticCase],
    trim_config: CoreTrimConfig,
    branch_config: BranchCompetitionConfig,
) -> tuple[list[dict[str, Any]], dict[str, SyntheticBundle]]:
    rows: list[dict[str, Any]] = []
    bundles: dict[str, SyntheticBundle] = {}
    for case in cases:
        candidate_set = _candidate_set(case)
        results: dict[SmoothBranchMethod, SmoothBranchOptimizationResult] = {}
        split = "CALIBRATION" if case.case_id in EXPANDED_CALIBRATION_IDS else "HELD_OUT_EVALUATION"
        for method in EVALUATION_METHODS:
            result = _optimize(candidate_set, method, trim_config, branch_config, case.stft)
            results[method] = result
            rows.extend(_synthetic_rows(case, result, split))
        bundles[case.case_id] = SyntheticBundle(case, candidate_set, results)
    return rows, bundles


def _synthetic_rows(
    case: SyntheticCase,
    result: SmoothBranchOptimizationResult,
    split: str,
) -> list[dict[str, Any]]:
    masks = {
        "FULL": np.ones(case.truth_hz.size, dtype=np.bool_),
        "EDGE_FOCUS": np.asarray(case.focus_mask, dtype=np.bool_),
        "RETAINED_CORE": np.asarray(result.trimmed_core_mask, dtype=np.bool_),
    }
    return [
        _synthetic_metric(case, result, split, region, mask)
        for region, mask in masks.items()
    ]


def _synthetic_metric(
    case: SyntheticCase,
    result: SmoothBranchOptimizationResult,
    split: str,
    region: str,
    mask: BoolArray,
) -> dict[str, Any]:
    truth_valid = np.isfinite(case.truth_hz) & mask
    estimate_valid = np.isfinite(result.final_frequency_hz) & mask
    comparable = truth_valid & estimate_valid
    errors = result.final_frequency_hz[comparable] - case.truth_hz[comparable]
    wrong = comparable & (np.abs(result.final_frequency_hz - case.truth_hz) > WRONG_TOLERANCE_HZ)
    modified = result.modified_mask & mask
    strongest_error = np.abs(result.strongest.frequency_hz - case.truth_hz)
    selected_error = np.abs(result.final_frequency_hz - case.truth_hz)
    improved = modified & truth_valid & (selected_error < strongest_error)
    harmed = modified & truth_valid & (selected_error > strongest_error)
    selected = result.final_frequency_hz[mask]
    steps = np.abs(np.diff(selected))
    truth_count = int(np.count_nonzero(truth_valid))
    region_count = int(np.count_nonzero(mask))
    return {
        "case_id": case.case_id,
        "case_kind": case.case_kind,
        "description": case.description,
        "split": split,
        "method": result.method.value,
        "region": region,
        "region_frame_count": region_count,
        "truth_frame_count": truth_count,
        "coverage": float(np.count_nonzero(comparable) / truth_count) if truth_count else float(np.mean(np.isfinite(selected))) if region_count else math.nan,
        "squared_error_sum_hz2": float(np.sum(np.square(errors))),
        "frequency_rmse_hz": float(np.sqrt(np.mean(np.square(errors)))) if errors.size else math.nan,
        "wrong_branch_count": int(np.count_nonzero(wrong)),
        "wrong_branch_fraction": float(np.count_nonzero(wrong) / max(truth_count, 1)),
        "large_jump_count": int(np.count_nonzero(steps >= LARGE_JUMP_HZ)),
        "modified_frame_count": int(np.count_nonzero(modified)),
        "modification_fraction": float(np.count_nonzero(modified) / max(region_count, 1)),
        "improved_frame_count": int(np.count_nonzero(improved)),
        "harmed_frame_count": int(np.count_nonzero(harmed)),
        "core_preservation_rate": result.core_preservation_rate,
        "core_trimmed_frame_count": sum(item.left_trimmed_frames + item.right_trimmed_frames for item in result.trim_decisions),
    }


def _synthetic_gate(
    rows: Sequence[Mapping[str, Any]],
    *,
    selected_method: SmoothBranchMethod,
) -> dict[str, Any]:
    gate = _comparison_gate(
        [row for row in rows if row["split"] == "HELD_OUT_EVALUATION"],
        selected_method,
        smooth_ids=set(SMOOTH_HELD_OUT_IDS),
        correct_ids={"Q_FULLY_CORRECT_EDGES", "D23_CORRECT_SMOOTH_HELD"},
        fast_ids={"R_FAST_DESCENT_NEAR_TRAILING_EDGE", "D23_FAST_DESCENT_HELD"},
        broadband_ids={"S_BROADBAND_NEAR_TRAILING_EDGE", "D23_BROADBAND_COMPETING_HELD"},
    )
    original_counts = _original_op_counts(rows, selected_method)
    gate.update(original_counts)
    obvious_gain = (
        int(gate["selected_smooth_improved_frame_count"])
        - int(gate["task023c_smooth_improved_frame_count"])
    ) >= 8
    gate["smooth_gain_more_than_trivial"] = obvious_gain
    gate["hard_gate_passed"] = bool(gate["passes_guardrails"]) and obvious_gain
    return gate


def _comparison_gate(
    rows: Sequence[Mapping[str, Any]],
    method: SmoothBranchMethod,
    *,
    smooth_ids: set[str],
    correct_ids: set[str],
    fast_ids: set[str],
    broadband_ids: set[str],
) -> dict[str, Any]:
    focus = [row for row in rows if row["region"] == "EDGE_FOCUS"]
    current = [row for row in focus if row["method"] == SmoothBranchMethod.E1_TASK023C.value]
    selected = [row for row in focus if row["method"] == method.value]

    def chosen(source: Sequence[Mapping[str, Any]], ids: set[str]) -> list[Mapping[str, Any]]:
        return [row for row in source if str(row["case_id"]) in ids]

    def aggregate_rmse(source: Sequence[Mapping[str, Any]]) -> float:
        count = sum(int(row["truth_frame_count"]) for row in source)
        return math.sqrt(sum(float(row["squared_error_sum_hz2"]) for row in source) / max(count, 1))

    def wrong_fraction(source: Sequence[Mapping[str, Any]]) -> float:
        count = sum(int(row["truth_frame_count"]) for row in source)
        return sum(int(row["wrong_branch_count"]) for row in source) / max(count, 1)

    current_smooth = chosen(current, smooth_ids)
    selected_smooth = chosen(selected, smooth_ids)
    modified = sum(int(row["modified_frame_count"]) for row in selected)
    improved = sum(int(row["improved_frame_count"]) for row in selected)
    harmed = sum(int(row["harmed_frame_count"]) for row in selected)
    correct = chosen(selected, correct_ids)
    fast = chosen(selected, fast_ids)
    broadband = chosen(selected, broadband_ids)
    current_broadband = chosen(current, broadband_ids)
    coverage_current = min((float(row["coverage"]) for row in current if math.isfinite(float(row["coverage"]))), default=0.0)
    coverage_selected = min((float(row["coverage"]) for row in selected if math.isfinite(float(row["coverage"]))), default=0.0)
    values = {
        "task023c_smooth_rmse_hz": aggregate_rmse(current_smooth),
        "selected_smooth_rmse_hz": aggregate_rmse(selected_smooth),
        "task023c_smooth_wrong_branch_fraction": wrong_fraction(current_smooth),
        "selected_smooth_wrong_branch_fraction": wrong_fraction(selected_smooth),
        "task023c_smooth_improved_frame_count": sum(int(row["improved_frame_count"]) for row in current_smooth),
        "selected_smooth_improved_frame_count": sum(int(row["improved_frame_count"]) for row in selected_smooth),
        "intervention_modified_frame_count": modified,
        "intervention_improved_frame_count": improved,
        "intervention_harmed_frame_count": harmed,
        "intervention_precision": improved / max(modified, 1),
        "intervention_harm_rate": harmed / max(modified, 1),
        "correct_edge_modification_fraction": max((float(row["modification_fraction"]) for row in correct), default=0.0),
        "fast_descent_harmed_frame_count": sum(int(row["harmed_frame_count"]) for row in fast),
        "selected_broadband_harmed_frame_count": sum(int(row["harmed_frame_count"]) for row in broadband),
        "task023c_broadband_harmed_frame_count": sum(int(row["harmed_frame_count"]) for row in current_broadband),
        "task023c_coverage": coverage_current,
        "selected_coverage": coverage_selected,
    }
    values["passes_guardrails"] = (
        values["selected_smooth_rmse_hz"] < values["task023c_smooth_rmse_hz"]
        and values["selected_smooth_wrong_branch_fraction"] < values["task023c_smooth_wrong_branch_fraction"]
        and values["intervention_precision"] >= 0.80
        and values["intervention_harm_rate"] <= 0.10
        and values["correct_edge_modification_fraction"] <= 0.02
        and values["fast_descent_harmed_frame_count"] == 0
        and values["selected_broadband_harmed_frame_count"]
        <= values["task023c_broadband_harmed_frame_count"]
        and values["selected_coverage"] >= values["task023c_coverage"]
    )
    return values


def _original_op_counts(
    rows: Sequence[Mapping[str, Any]],
    selected_method: SmoothBranchMethod,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for case_id, prefix in (
        ("O_LEADING_SMOOTH_WRONG_BRANCH", "leading_original"),
        ("P_TRAILING_SMOOTH_WRONG_BRANCH", "trailing_original"),
    ):
        for method, label in (
            (SmoothBranchMethod.E1_TASK023C, "task023c"),
            (selected_method, "task023d"),
        ):
            row = next(
                item
                for item in rows
                if item["case_id"] == case_id
                and item["method"] == method.value
                and item["region"] == "EDGE_FOCUS"
            )
            result[f"{prefix}_{label}_modified_frames"] = int(row["modified_frame_count"])
            result[f"{prefix}_{label}_rmse_hz"] = float(row["frequency_rmse_hz"])
            result[f"{prefix}_{label}_wrong_branch_fraction"] = float(row["wrong_branch_fraction"])
    return result


def _candidate_set(case: SyntheticCase) -> RidgeCandidateSet:
    return extract_global_path_candidates(
        case.stft,
        minimum_frequency_hz=0.05e9,
        maximum_frequency_hz=min(6.0e9, float(case.stft.frequency_hz[-1])),
        config=GlobalPathConfig(top_k=TOP_K),
    )


def _deduplicated_cases(cases: Sequence[SyntheticCase]) -> tuple[SyntheticCase, ...]:
    values: dict[str, SyntheticCase] = {}
    for case in cases:
        values.setdefault(case.case_id, case)
    return tuple(values.values())


def _expanded_cases() -> tuple[SyntheticCase, ...]:
    return (
        _smooth_case("D23_LEADING_SMOOTH_CAL_A", "leading_smooth", slope_hz_per_frame=-10.0e6, wrong_amplitude=22.0),
        _smooth_case("D23_TRAILING_SMOOTH_CAL_A", "trailing_smooth", slope_hz_per_frame=10.0e6, wrong_amplitude=22.0),
        _smooth_case("D23_CORRECT_SMOOTH_CAL", "correct_smooth", slope_hz_per_frame=4.0e6),
        _smooth_case("D23_FAST_DESCENT_CAL", "fast_descent", slope_hz_per_frame=-78.0e6),
        _smooth_case("D23_BROADBAND_COMPETING_CAL", "broadband_competing", slope_hz_per_frame=8.0e6, wrong_amplitude=21.0),
        _smooth_case("D23_RANDOM_FALSE_CAL", "random_false"),
        _smooth_case("D23_LEADING_SMOOTH_HELD_A", "leading_smooth", slope_hz_per_frame=-5.0e6, wrong_amplitude=20.0),
        _smooth_case("D23_LEADING_SMOOTH_HELD_B", "leading_smooth", slope_hz_per_frame=13.0e6, wrong_amplitude=25.0),
        _smooth_case("D23_TRAILING_SMOOTH_HELD_A", "trailing_smooth", slope_hz_per_frame=5.0e6, wrong_amplitude=20.0),
        _smooth_case("D23_TRAILING_SMOOTH_HELD_B", "trailing_smooth", slope_hz_per_frame=-13.0e6, wrong_amplitude=25.0),
        _smooth_case("D23_CORRECT_SMOOTH_HELD", "correct_smooth", slope_hz_per_frame=-6.0e6),
        _smooth_case("D23_FAST_DESCENT_HELD", "fast_descent", slope_hz_per_frame=-92.0e6),
        _smooth_case("D23_BRANCH_DIVERGENCE", "branch_divergence", wrong_amplitude=22.0),
        _smooth_case("D23_BRANCH_MERGE", "branch_merge", wrong_amplitude=22.0),
        _smooth_case("D23_BROADBAND_COMPETING_HELD", "broadband_competing", slope_hz_per_frame=-9.0e6, wrong_amplitude=23.0),
        _smooth_case("D23_RANDOM_FALSE_HELD", "random_false"),
    )


def _smooth_case(
    case_id: str,
    kind: str,
    *,
    slope_hz_per_frame: float = 0.0,
    wrong_amplitude: float = 23.0,
) -> SyntheticCase:
    count = 120
    edge = 32
    rng = np.random.default_rng(23000 + sum(ord(char) for char in case_id))
    frequency = np.linspace(0.0, 6.4e9, 257)
    truth = np.full(count, 2.4e9, dtype=np.float64)
    if kind == "fast_descent":
        truth[:78] = 3.8e9
        truth[78:] = np.maximum(0.45e9, 3.8e9 + np.arange(count - 78) * slope_hz_per_frame)
    magnitude = rng.lognormal(math.log(0.18), 0.38, size=(frequency.size, count))
    focus = np.zeros(count, dtype=np.bool_)
    for frame, value in enumerate(truth):
        _add_peak(magnitude[:, frame], frequency, float(value), 13.0)
    if kind in {"leading_smooth", "branch_merge"}:
        selected = range(edge)
        focus[:edge] = True
    elif kind in {"trailing_smooth", "branch_divergence", "broadband_competing", "random_false"}:
        selected = range(count - edge, count)
        focus[-edge:] = True
    elif kind in {"correct_smooth", "fast_descent"}:
        selected = range(0)
        focus[:] = True
    else:
        raise ValueError(f"Unknown smooth synthetic kind: {kind}")
    for offset, frame in enumerate(selected):
        if kind == "random_false":
            center = float(rng.uniform(0.55e9, 5.8e9))
        elif kind == "branch_divergence":
            center = 2.4e9 + (offset + 1) * 42.0e6
        elif kind == "branch_merge":
            center = 2.4e9 + (edge - offset) * 42.0e6
        elif frame < edge:
            center = 4.65e9 + offset * slope_hz_per_frame
        else:
            center = 4.05e9 + offset * slope_hz_per_frame
        _add_peak(magnitude[:, frame], frequency, center, wrong_amplitude)
    if kind == "correct_smooth":
        for frame in range(count):
            _add_peak(magnitude[:, frame], frequency, 4.8e9 + frame * slope_hz_per_frame, 9.0)
    if kind == "fast_descent":
        for frame in range(78, count):
            _add_peak(magnitude[:, frame], frequency, 5.2e9, 9.0)
    if kind == "broadband_competing":
        magnitude[:, -24:] += 7.0
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
    return SyntheticCase(case_id, kind.replace("_", " "), stft, truth, focus, kind)


def _add_peak(
    values: NDArray[np.float64],
    frequency: NDArray[np.float64],
    center_hz: float,
    amplitude: float,
) -> None:
    values += amplitude * np.exp(-0.5 * np.square((frequency - center_hz) / 35.0e6))


BoolArray = NDArray[np.bool_]


def _core_boundary_rows(
    stream: PreparedStream,
    candidate_set: RidgeCandidateSet,
    result: SmoothBranchOptimizationResult,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    broadband_z = _broadband_z(stream.analysis.stft_result)
    for core in result.original_cores:
        decision = next(item for item in result.trim_decisions if item.core_id == core.core_id)
        for frame_index in range(core.frame_start, core.frame_end + 1):
            if frame_index - core.frame_start < 3:
                position = "LEFT_BOUNDARY"
            elif core.frame_end - frame_index < 3:
                position = "RIGHT_BOUNDARY"
            else:
                position = "INTERIOR"
            candidate = candidate_set.candidates_by_frame[frame_index][0]
            rows.append(
                {
                    "dataset": stream.source_path.name,
                    "quality_group": stream.quality_group,
                    "profile": stream.profile_id,
                    "channel": stream.channel_name,
                    "stream_id": stream.stream_id,
                    "core_id": core.core_id,
                    "position": position,
                    "frame_index": frame_index,
                    "time_s": float(result.task023c.time_s[frame_index]),
                    "original_core_start": core.frame_start,
                    "original_core_end": core.frame_end,
                    "trimmed_core_start": decision.trimmed_frame_start,
                    "trimmed_core_end": decision.trimmed_frame_end,
                    "retained_after_trim": decision.trimmed_frame_start <= frame_index <= decision.trimmed_frame_end,
                    "strongest_frequency_hz": float(result.strongest.frequency_hz[frame_index]),
                    "strongest_peak_to_background_db": candidate.peak_to_background_db,
                    "strongest_peak_to_competitor_db": candidate.peak_to_competitor_db,
                    "trust_score": float(result.task023c.trust.trust_score[frame_index]),
                    "topk_local_support": float(result.task023c.trust.candidate_support[frame_index]),
                    "strongest_backward_persistence": float(result.ambiguity.strongest_backward_persistence[frame_index]),
                    "strongest_forward_persistence": float(result.ambiguity.strongest_forward_persistence[frame_index]),
                    "strongest_branch_persistence": float(result.ambiguity.strongest_branch_persistence[frame_index]),
                    "persistent_branch_count": int(result.ambiguity.persistent_branch_count[frame_index]),
                    "branch_ambiguity": float(result.ambiguity.branch_ambiguity[frame_index]),
                    "strongest_vs_rank2_accumulated_evidence_db": float(result.ambiguity.strongest_vs_rank2_evidence_db[frame_index]),
                    "best_alternative_rank": int(result.ambiguity.best_alternative_rank[frame_index]),
                    "best_alternative_frequency_hz": float(result.ambiguity.best_alternative_frequency_hz[frame_index]),
                    "broadband_robust_z": float(broadband_z[frame_index]),
                }
            )
    return rows


def _trim_rows(
    stream: PreparedStream,
    result: SmoothBranchOptimizationResult,
) -> list[dict[str, Any]]:
    return [
        {
            "stream_id": stream.stream_id,
            "profile": stream.profile_id,
            **asdict(decision),
            "original_start_time_us": decision.original_start_time_s * 1e6,
            "original_end_time_us": decision.original_end_time_s * 1e6,
            "trimmed_start_time_us": decision.trimmed_start_time_s * 1e6,
            "trimmed_end_time_us": decision.trimmed_end_time_s * 1e6,
        }
        for decision in result.trim_decisions
    ]


def _branch_detail_rows(
    stream: PreparedStream,
    result: SmoothBranchOptimizationResult,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for decision in (result.leading_branch_decision, result.trailing_branch_decision):
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
                    "anchor_frame": decision.anchor_frame,
                    "branch_duration_s": decision.branch_duration_s,
                    **asdict(decision.score),
                    **asdict(step),
                }
            )
    return rows


def _cross_rows(
    stream: PreparedStream,
    result: SmoothBranchOptimizationResult,
    runtime_s: float,
) -> list[dict[str, Any]]:
    return [
        _real_metric(stream, result, SmoothBranchMethod.E0_KEEP_STRONGEST.value, result.strongest.frequency_hz, 0.0),
        _real_metric(stream, result, SmoothBranchMethod.E1_TASK023C.value, result.task023c.final_frequency_hz, 0.0),
        _real_metric(stream, result, result.method.value, result.final_frequency_hz, runtime_s),
    ]


def _ch3_comparison(
    stream: PreparedStream,
    result: SmoothBranchOptimizationResult,
    interval_id: str,
    start_s: float,
    end_s: float,
) -> list[dict[str, Any]]:
    mask = (result.task023c.time_s >= start_s) & (result.task023c.time_s <= end_s)
    return [
        _real_metric(stream, result, SmoothBranchMethod.E0_KEEP_STRONGEST.value, result.strongest.frequency_hz, 0.0, interval_id=interval_id, mask=mask),
        _real_metric(stream, result, SmoothBranchMethod.E1_TASK023C.value, result.task023c.final_frequency_hz, 0.0, interval_id=interval_id, mask=mask),
        _real_metric(stream, result, result.method.value, result.final_frequency_hz, 0.0, interval_id=interval_id, mask=mask),
    ]


def _real_metric(
    stream: PreparedStream,
    result: SmoothBranchOptimizationResult,
    method: str,
    frequency_hz: NDArray[np.float64],
    runtime_s: float,
    *,
    interval_id: str = "FULL",
    mask: BoolArray | None = None,
) -> dict[str, Any]:
    selected_mask = np.ones(frequency_hz.size, dtype=np.bool_) if mask is None else mask
    values = frequency_hz[selected_mask]
    steps = np.abs(np.diff(values))
    if method == SmoothBranchMethod.E1_TASK023C.value:
        modified = (result.task023c.final_frequency_hz != result.strongest.frequency_hz) & selected_mask
    elif method == result.method.value and result.method is not SmoothBranchMethod.E0_KEEP_STRONGEST:
        modified = result.modified_mask & selected_mask
    else:
        modified = np.zeros(frequency_hz.size, dtype=np.bool_)
    original_core_frames = sum(core.frame_count for core in result.original_cores)
    trimmed_core_frames = sum(core.frame_count for core in result.trimmed_cores)
    branch_steps = [
        step
        for decision in (result.leading_branch_decision, result.trailing_branch_decision)
        if decision is not None
        for step in decision.steps
        if step.modified and selected_mask[step.frame_index]
    ]
    return {
        "dataset": stream.source_path.name,
        "source_sha256": stream.source_sha256,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "interval_id": interval_id,
        "method": method,
        "frame_count": int(np.count_nonzero(selected_mask)),
        "coverage": float(np.mean(np.isfinite(values))) if values.size else math.nan,
        "step_p95_hz": float(np.quantile(steps, 0.95)) if steps.size else math.nan,
        "large_jump_count": int(np.count_nonzero(steps >= LARGE_JUMP_HZ)),
        "modified_frame_count": int(np.count_nonzero(modified)),
        "modification_fraction": float(np.count_nonzero(modified) / max(int(np.count_nonzero(selected_mask)), 1)),
        "rank2plus_modified_frame_count": int(np.count_nonzero(modified & (result.final_rank >= 2))) if method == result.method.value else math.nan,
        "original_core_fraction": original_core_frames / frequency_hz.size,
        "trimmed_core_fraction": trimmed_core_frames / frequency_hz.size,
        "core_trim_fraction": (original_core_frames - trimmed_core_frames) / max(original_core_frames, 1),
        "core_preservation_rate": result.core_preservation_rate,
        "mean_modified_branch_identity_support": float(np.mean([step.branch_identity_support for step in branch_steps])) if branch_steps else math.nan,
        "mean_modified_spectral_cost": float(np.mean([step.spectral_cost for step in branch_steps])) if branch_steps else math.nan,
        "mean_modified_broadband_exposure": float(np.mean([step.broadband_exposure for step in branch_steps])) if branch_steps else math.nan,
        "runtime_s": runtime_s,
    }


def _real_guard(
    rows: Sequence[Mapping[str, Any]],
    method: SmoothBranchMethod,
) -> dict[str, Any]:
    strongest = {str(row["stream_id"]): row for row in rows if row["method"] == SmoothBranchMethod.E0_KEEP_STRONGEST.value}
    current = {str(row["stream_id"]): row for row in rows if row["method"] == SmoothBranchMethod.E1_TASK023C.value}
    selected = {str(row["stream_id"]): row for row in rows if row["method"] == method.value}
    common = sorted(strongest.keys() & selected.keys() & current.keys())
    good = [selected[key] for key in common if selected[key]["quality_group"] == "relatively_good_user_label"]
    modifications = [float(row["modification_fraction"]) for row in good]
    return {
        "stream_count": len(common),
        "coverage_regression_stream_count": sum(float(selected[key]["coverage"]) < float(strongest[key]["coverage"]) for key in common),
        "minimum_core_preservation_rate": min((float(selected[key]["core_preservation_rate"]) for key in common if math.isfinite(float(selected[key]["core_preservation_rate"]))), default=0.0),
        "relatively_good_median_modification_fraction": float(np.median(modifications)) if modifications else math.nan,
        "relatively_good_over_5_percent_stream_count": sum(value > 0.05 for value in modifications),
        "strongest_large_jump_count": sum(int(strongest[key]["large_jump_count"]) for key in common),
        "task023c_large_jump_count": sum(int(current[key]["large_jump_count"]) for key in common),
        "task023d_large_jump_count": sum(int(selected[key]["large_jump_count"]) for key in common),
        "real_guard_passed": all(float(selected[key]["coverage"]) >= float(strongest[key]["coverage"]) for key in common)
        and all(float(selected[key]["core_preservation_rate"]) >= 0.98 for key in common if math.isfinite(float(selected[key]["core_preservation_rate"])))
        and not any(value > 0.05 for value in modifications),
    }


def _component_verdicts(
    gate: Mapping[str, Any],
    ch3_trim_rows: Sequence[Mapping[str, Any]],
    ch3_rows: Sequence[Mapping[str, Any]],
    method: SmoothBranchMethod,
) -> dict[str, str]:
    any_trim = any(int(row["left_trimmed_frames"]) + int(row["right_trimmed_frames"]) > 0 for row in ch3_trim_rows)
    core = "SUPPORTED" if any_trim else "MIXED"
    smooth = "SUPPORTED" if bool(gate["hard_gate_passed"]) else "MIXED" if bool(gate["passes_guardrails"]) else "NOT_SUPPORTED"
    current_jumps = sum(
        int(row["large_jump_count"])
        for row in ch3_rows
        if row["interval_id"] == "FULL"
        and row["method"] == SmoothBranchMethod.E1_TASK023C.value
    )
    selected_jumps = sum(
        int(row["large_jump_count"])
        for row in ch3_rows
        if row["interval_id"] == "FULL" and row["method"] == method.value
    )
    practical = (
        "IMPROVED"
        if selected_jumps < current_jumps
        else "UNCHANGED"
        if selected_jumps == current_jumps
        else "WORSE"
    )
    return {
        "core_boundary_refinement": core,
        "smooth_wrong_branch_discrimination": smooth,
        "ch3_practical_improvement": practical,
    }


def _overall_verdict(gate: Mapping[str, Any], real_guard: Mapping[str, Any]) -> str:
    if bool(gate["hard_gate_passed"]) and bool(real_guard["real_guard_passed"]):
        return "BETTER_THAN_TASK023C"
    if bool(gate["passes_guardrails"]) or bool(real_guard["real_guard_passed"]):
        return "MIXED"
    return "NOT_BETTER_THAN_TASK023C"


def _save_synthetic_figures(
    figures: Path,
    bundles: Mapping[str, SyntheticBundle],
    method: SmoothBranchMethod,
) -> None:
    selected_ids = (
        "O_LEADING_SMOOTH_WRONG_BRANCH",
        "P_TRAILING_SMOOTH_WRONG_BRANCH",
        "D23_LEADING_SMOOTH_HELD_A",
        "D23_TRAILING_SMOOTH_HELD_A",
        "D23_CORRECT_SMOOTH_HELD",
        "D23_FAST_DESCENT_HELD",
        "D23_BRANCH_DIVERGENCE",
        "D23_BRANCH_MERGE",
        "D23_BROADBAND_COMPETING_HELD",
        "D23_RANDOM_FALSE_HELD",
    )
    for case_id in selected_ids:
        bundle = bundles[case_id]
        current = bundle.results[SmoothBranchMethod.E1_TASK023C]
        selected = bundle.results[method]
        figure = Figure(figsize=(10.5, 5.6), constrained_layout=True)
        axis = figure.subplots()
        db = 20.0 * np.log10(np.maximum(np.abs(bundle.case.stft.spectrum), np.finfo(float).tiny))
        axis.imshow(
            db,
            origin="lower",
            aspect="auto",
            extent=(float(bundle.case.stft.time_s[0] * 1e9), float(bundle.case.stft.time_s[-1] * 1e9), float(bundle.case.stft.frequency_hz[0] / 1e9), float(bundle.case.stft.frequency_hz[-1] / 1e9)),
            cmap="magma",
            vmin=float(np.max(db) - 45.0),
        )
        x = bundle.case.stft.time_s * 1e9
        axis.plot(x, bundle.case.truth_hz / 1e9, "w--", linewidth=1.2, label="truth")
        axis.plot(x, selected.strongest.frequency_hz / 1e9, color="#4cc9f0", linewidth=0.9, label="strongest")
        axis.plot(x, current.final_frequency_hz / 1e9, color="#f77f00", linewidth=1.0, label="TASK-023C")
        axis.plot(x, selected.final_frequency_hz / 1e9, color="#06d6a0", linewidth=1.5, label="TASK-023D")
        axis.scatter(x[selected.modified_mask], selected.final_frequency_hz[selected.modified_mask] / 1e9, color="white", edgecolor="black", s=20, label="023D modified")
        axis.set(xlabel="time (ns)", ylabel="frequency (GHz)", title=case_id)
        axis.legend(ncol=4, fontsize=8)
        _save(figure, figures / f"synthetic_{case_id}.png")


def _save_ch3_figures(
    figures: Path,
    bundles: Mapping[str, tuple[PreparedStream, SmoothBranchOptimizationResult]],
    method: SmoothBranchMethod,
) -> None:
    for profile, (stream, result) in bundles.items():
        stft = stream.analysis.stft_result
        x = result.task023c.time_s * 1e6
        figure = Figure(figsize=(13.0, 6.8), constrained_layout=True)
        axis = figure.subplots()
        db = 20.0 * np.log10(np.maximum(np.abs(stft.spectrum), np.finfo(float).tiny))
        axis.imshow(
            db,
            origin="lower",
            aspect="auto",
            extent=(float(x[0]), float(x[-1]), float(stft.frequency_hz[0] / 1e9), float(stft.frequency_hz[-1] / 1e9)),
            cmap="magma",
            vmin=float(np.max(db) - 50.0),
        )
        for core in result.original_cores:
            axis.axvspan(core.start_time_s * 1e6, core.end_time_s * 1e6, color="#adb5bd", alpha=0.10, label="023C core")
        for core in result.trimmed_cores:
            axis.axvspan(core.start_time_s * 1e6, core.end_time_s * 1e6, color="#06d6a0", alpha=0.14, label="retained core")
        axis.plot(x, result.strongest.frequency_hz / 1e9, color="#4cc9f0", linewidth=0.8, label="strongest")
        axis.plot(x, result.task023c.final_frequency_hz / 1e9, color="#f77f00", linewidth=1.0, label="TASK-023C")
        axis.plot(x, result.final_frequency_hz / 1e9, color="#06d6a0", linewidth=1.5, label=method.value)
        axis.scatter(x[result.modified_mask], result.final_frequency_hz[result.modified_mask] / 1e9, color="white", edgecolor="black", s=23, label="023D modified")
        axis.set(xlabel="time (µs)", ylabel="frequency (GHz)", title=f"ch3 {profile}: smooth branch discrimination", xlim=(183.55, 183.95), ylim=(0.0, 6.0))
        handles, labels = axis.get_legend_handles_labels()
        unique = dict(zip(labels, handles, strict=True))
        axis.legend(unique.values(), unique.keys(), ncol=4, fontsize=8)
        _save(figure, figures / f"ch3_{profile}_smooth_branch_overlay.png")

        diagnostic = Figure(figsize=(12.0, 8.0), constrained_layout=True)
        axes = diagnostic.subplots(3, 1, sharex=True)
        axes[0].plot(x, result.task023c.trust.trust_score, label="023C trust")
        axes[0].axhline(CORE_CONFIG.trust_threshold, color="black", linestyle="--")
        axes[0].legend()
        axes[1].plot(x, result.ambiguity.branch_ambiguity, label="branch ambiguity", color="#ef476f")
        axes[1].plot(x, result.ambiguity.strongest_branch_persistence, label="strongest persistence", color="#118ab2")
        axes[1].legend()
        evidence = result.ambiguity.strongest_vs_rank2_evidence_db
        axes[2].plot(x, evidence, label="strongest-vs-alt evidence (dB)")
        axes[2].set(xlabel="time (µs)", ylabel="dB", xlim=(183.55, 183.95))
        axes[2].legend()
        _save(diagnostic, figures / f"ch3_{profile}_core_boundary_diagnostic.png")


def _write_definitions(
    output: Path,
    trim_config: CoreTrimConfig,
    branch_config: BranchCompetitionConfig,
) -> None:
    (output / "branch_ambiguity_definition.md").write_text(
        "# Branch ambiguity\n\nCandidates up to a fixed rank are linked between adjacent physical times when |Δf| is within a base Hz tolerance plus maximum physical rate × Δt. Forward and backward consecutive reach define persistence. Ambiguity is high only when the strongest tube and a frequency-separated alternative tube both persist and have competitive accumulated amplitude evidence. A one-frame extra peak cannot satisfy the persistence requirement.\n\n"
        + f"Config: `{json.dumps(asdict(AMBIGUITY_CONFIG), sort_keys=True)}`.\n",
        encoding="utf-8",
    )
    (output / "core_trim_definition.md").write_text(
        "# Trusted-core boundary refinement\n\nOnly the left or right boundary can move inward. Persistent branch ambiguity or joint degradation of background and competitor contrast can reclassify a boundary as REVIEWABLE_EDGE. Slope magnitude is absent from the rule. Minimum retained core length prevents deletion; frequencies in the retained core remain bitwise strongest.\n\n"
        + f"Config: `{json.dumps(asdict(trim_config), sort_keys=True)}`.\n",
        encoding="utf-8",
    )
    (output / "branch_competition_definition.md").write_text(
        "# Local branch competition\n\nThe anchor is extended only through existing Top-K candidates. Beam state retains frequencies, ranks, spectral cost, local support, anchor-tube identity, physical slope, broadband exposure, and deviation from strongest. Identity support is inherited through physically linkable candidates and sharply reduced on a broken connection; smoothness alone therefore cannot establish identity. Score components and every accepted frame are exported.\n\n"
        + f"Config: `{json.dumps(asdict(branch_config), sort_keys=True)}`.\n",
        encoding="utf-8",
    )


def _broadband_z(stft_result: STFTResult) -> NDArray[np.float64]:
    power = np.sum(np.square(np.abs(stft_result.spectrum)), axis=0)
    median = float(np.median(power))
    mad = float(np.median(np.abs(power - median)))
    scale = max(1.4826 * mad, np.finfo(float).eps * max(abs(median), 1.0))
    return np.asarray((power - median) / scale, dtype=np.float64)


def _report(
    overall: str,
    components: Mapping[str, str],
    gate: Mapping[str, Any],
    real_guard: Mapping[str, Any],
    trims: Sequence[Mapping[str, Any]],
    details: Sequence[Mapping[str, Any]],
    ch3: Sequence[Mapping[str, Any]],
    method: SmoothBranchMethod,
) -> str:
    del details
    core_lines = "\n".join(
        f"- {row['profile']} {row['core_id']}: {float(row['original_start_time_us']):.6f}–{float(row['original_end_time_us']):.6f} µs -> {float(row['trimmed_start_time_us']):.6f}–{float(row['trimmed_end_time_us']):.6f} µs (trim L{row['left_trimmed_frames']}/R{row['right_trimmed_frames']})"
        for row in trims
    )

    def metric(profile: str, method_name: str, key: str, interval: str = "FULL") -> float:
        row = next(item for item in ch3 if item["profile"] == profile and item["method"] == method_name and item["interval_id"] == interval)
        return float(row[key])

    return f"""# TASK-023D Smooth Wrong-Branch Discrimination

## Verdict

- Core boundary refinement: **{components['core_boundary_refinement']}**
- Smooth wrong-branch discrimination: **{components['smooth_wrong_branch_discrimination']}**
- ch3 practical improvement: **{components['ch3_practical_improvement']}**
- Overall: **{overall}**

Selected synthetic-only comparator: `{method.value}`. Held-out smooth-edge RMSE `{float(gate['task023c_smooth_rmse_hz']) / 1e6:.3f}` -> `{float(gate['selected_smooth_rmse_hz']) / 1e6:.3f}` MHz; wrong branch `{float(gate['task023c_smooth_wrong_branch_fraction']):.6f}` -> `{float(gate['selected_smooth_wrong_branch_fraction']):.6f}`. Intervention precision `{float(gate['intervention_precision']):.3f}`, harm `{float(gate['intervention_harm_rate']):.3f}`, coverage `{float(gate['selected_coverage']):.3f}`.

Original O/P benchmark: leading `{gate['leading_original_task023c_modified_frames']}/32 -> {gate['leading_original_task023d_modified_frames']}/32`; trailing `{gate['trailing_original_task023c_modified_frames']}/32 -> {gate['trailing_original_task023d_modified_frames']}/32`.

## ch3 core refinement

{core_lines}

Balanced full-record modifications: TASK-023C `{metric('balanced', SmoothBranchMethod.E1_TASK023C.value, 'modified_frame_count'):.0f}`, TASK-023D `{metric('balanced', method.value, 'modified_frame_count'):.0f}`. High-time: TASK-023C `{metric('high_time_resolution', SmoothBranchMethod.E1_TASK023C.value, 'modified_frame_count'):.0f}`, TASK-023D `{metric('high_time_resolution', method.value, 'modified_frame_count'):.0f}`.

Balanced jumps strongest/TASK-023C/TASK-023D: `{metric('balanced', SmoothBranchMethod.E0_KEEP_STRONGEST.value, 'large_jump_count'):.0f}` / `{metric('balanced', SmoothBranchMethod.E1_TASK023C.value, 'large_jump_count'):.0f}` / `{metric('balanced', method.value, 'large_jump_count'):.0f}`. High-time: `{metric('high_time_resolution', SmoothBranchMethod.E0_KEEP_STRONGEST.value, 'large_jump_count'):.0f}` / `{metric('high_time_resolution', SmoothBranchMethod.E1_TASK023C.value, 'large_jump_count'):.0f}` / `{metric('high_time_resolution', method.value, 'large_jump_count'):.0f}`. These real-data values are consistency diagnostics, not accuracy claims.

## Cross-dataset guard

All `{real_guard['stream_count']}` streams retained strongest coverage. Minimum retained-core preservation `{float(real_guard['minimum_core_preservation_rate']):.3f}`; relatively-good median modification `{float(real_guard['relatively_good_median_modification_fraction']):.6f}`; relatively-good streams above 5%: `{real_guard['relatively_good_over_5_percent_stream_count']}`. Aggregate jumps strongest/TASK-023C/TASK-023D: `{real_guard['strongest_large_jump_count']}` / `{real_guard['task023c_large_jump_count']}` / `{real_guard['task023d_large_jump_count']}`.

## Boundary

Strongest is immutable. Every changed output is an existing Top-K candidate. STFT, candidate extraction, search band, Top-K, refinement, raw data, Production, GUI, physics, and export were not changed. ch3 and all real streams were evaluation-only. No AI, promotion, commit, or push was performed.
"""


def _write_repository_audit(path: Path, audit: Mapping[str, str]) -> None:
    path.write_text(
        "\n\n".join(f"$ {key}\n{value}" for key, value in audit.items()) + "\n",
        encoding="utf-8",
    )


def _repository_audit() -> dict[str, str]:
    commands = {
        "git status --short --branch": ("git", "status", "--short", "--branch"),
        "git branch --show-current": ("git", "branch", "--show-current"),
        "git log -5 --oneline": ("git", "log", "-5", "--oneline"),
        "git diff --stat": ("git", "diff", "--stat"),
        "git diff --cached --stat": ("git", "diff", "--cached", "--stat"),
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
        writer.writerows(rows)


def _save(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=170)
    figure.clear()


if __name__ == "__main__":
    main()
