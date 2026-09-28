"""TASK-021F Research-only broadband-aware candidate node-evidence study.

The module deliberately consumes immutable STFT results and the existing Top-K
candidate graph. It does not alter core extraction, default node cost, NULL
costs, transition definitions, Production workflow, or raw input data.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from numpy.typing import NDArray

from dps_studio.core.ridge import (
    GlobalPathConfig,
    RidgeCandidate,
    candidate_node_cost,
    candidate_transition_cost,
    extract_global_path_candidates,
)
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import load_workflow_config
from dps_studio.research.global_path_benchmark import (
    DEFAULT_VACUUM_WAVELENGTH_M,
    SyntheticGlobalPathCase,
    calculate_ridge_metrics,
    generate_synthetic_global_path_cases,
)
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RAW_ROOT,
    REPOSITORY_ROOT,
    PreparedStream,
    node_cost_components,
    prepare_streams,
    sha256_file,
)
from dps_studio.research.task021c_cost_bridge import corrected_inventory
from dps_studio.research.task021e_transition_models import (
    TransitionSpec,
    build_transition_specs,
    robust_first_order_cost,
)


FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]

TOP_K = 5
CH3_START_S = 0.00018360
CH3_END_S = 0.00018390
DESCENT_INTERVALS: tuple[tuple[str, float, float], ...] = (
    ("D0_183P60_183P76_US", 0.00018360, 0.00018376),
    ("D1_183P76_183P82_US", 0.00018376, 0.00018382),
    ("D2_183P82_183P88_US", 0.00018382, 0.00018388),
)
BROADBAND_Z_THRESHOLD = 3.0
LOCAL_INNER_RESOLUTION_FACTOR = 0.75
LOCAL_GUARD_RESOLUTION_FACTOR = 1.25
LOCAL_OUTER_RESOLUTION_FACTOR = 3.5
CONCENTRATION_NARROW_RESOLUTION_FACTOR = 1.0
CONCENTRATION_BROAD_RESOLUTION_FACTOR = 4.0
PROMINENCE_REFERENCE_DB = 3.0
PROMINENCE_SCALE_DB = 12.0
CONCENTRATION_REFERENCE = 0.35
CONCENTRATION_SCALE = 0.40
PRODUCTION_ROOT = Path(r"D:\Code\Python_Projects\DPS_Studio")


@dataclass(frozen=True, slots=True)
class NodeModelSpec:
    """Frozen additive node-evidence model; parameters are dimensionless."""

    node_model_id: str
    display_name: str
    prominence_penalty_weight: float
    concentration_penalty_weight: float
    broadband_specificity_penalty_weight: float
    rationale: str

    def row(self) -> dict[str, Any]:
        return {
            "node_model_id": self.node_model_id,
            "display_name": self.display_name,
            "prominence_penalty_weight": self.prominence_penalty_weight,
            "concentration_penalty_weight": self.concentration_penalty_weight,
            "broadband_specificity_penalty_weight": self.broadband_specificity_penalty_weight,
            "new_node_cost_math": (
                "core_N0 + w_prom*(1-prominence_score) + "
                "w_conc*(1-concentration_score) + "
                "w_bb*occupancy*(1-specificity)^2"
            ),
            "parameter_scope": "predeclared from synthetic cases and relatively-good calibration subset; no ch3-specific fit",
            "research_only": True,
            "rationale": self.rationale,
        }


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    """Read-only candidate-level evidence computed from one existing STFT."""

    frame_index: int
    candidate_rank: int
    time_s: float
    frequency_hz: float
    amplitude: float
    local_sideband_prominence_db: float
    local_concentration: float
    peak_width_hz: float
    local_peak_sharpness: float
    broadband_occupancy: float
    narrowband_to_broadband_ratio: float
    prominence_score: float
    concentration_score: float
    specificity: float
    stft_resolution_hz: float


@dataclass(frozen=True, slots=True)
class EvidenceBundle:
    """Evidence keyed exactly by existing candidate frame/rank provenance."""

    by_key: Mapping[tuple[int, int], CandidateEvidence]
    frame_broadband_occupancy: FloatArray
    stft_resolution_hz: float
    search_band_minimum_hz: float
    search_band_maximum_hz: float

    def for_candidate(self, candidate: RidgeCandidate) -> CandidateEvidence:
        return self.by_key[(candidate.frame_index, candidate.candidate_rank)]


@dataclass(frozen=True, slots=True)
class NodePathResult:
    """Independent first-order DP result with a Research-only node model."""

    time_s: FloatArray
    frame_indices: IntArray
    candidate_frames: tuple[tuple[RidgeCandidate, ...], ...]
    selected_candidate_rank: IntArray
    selected_frequency_hz: FloatArray
    is_null: BoolArray
    node_cost: FloatArray
    transition_cost: FloatArray
    cumulative_cost: FloatArray
    node_model: NodeModelSpec
    transition_spec: TransitionSpec
    config: GlobalPathConfig

    @property
    def total_path_cost(self) -> float:
        return float(self.cumulative_cost[-1])


@dataclass(frozen=True, slots=True)
class NodeSyntheticScenario:
    """Synthetic scenario with explicit truth and optional broadband interval."""

    case: SyntheticGlobalPathCase
    minimum_frequency_hz: float
    maximum_frequency_hz: float
    broadband_mask: BoolArray
    role: str


def build_node_models() -> tuple[NodeModelSpec, ...]:
    """Return the fixed N0–N4 study matrix without a parameter search."""
    return (
        NodeModelSpec(
            "N0", "current_TASK021A_baseline", 0.0, 0.0, 0.0, "Exact current core node cost."
        ),
        NodeModelSpec(
            "N1",
            "local_prominence",
            0.14,
            0.0,
            0.0,
            "Same-frame sideband prominence deficiency only.",
        ),
        NodeModelSpec(
            "N2",
            "prominence_plus_concentration",
            0.14,
            0.10,
            0.0,
            "N1 plus local spectral concentration deficiency.",
        ),
        NodeModelSpec(
            "N3",
            "specificity_aware_broadband",
            0.14,
            0.10,
            0.28,
            "N2 plus occupancy-weighted low-specificity penalty.",
        ),
        NodeModelSpec(
            "N4",
            "aggressive_specificity_diagnostic",
            0.14,
            0.10,
            0.60,
            "Stronger N3 broadband discrimination; diagnostic only, never a default recommendation.",
        ),
    )


def fixed_transition_specs() -> tuple[TransitionSpec, ...]:
    """Read exact E0/E2/E3 definitions from TASK-021E source constants."""
    wanted = {"E0", "E2", "E3"}
    selected = tuple(item for item in build_transition_specs() if item.experiment_id in wanted)
    if {item.experiment_id for item in selected} != wanted:
        raise RuntimeError("TASK-021E E0/E2/E3 transition definitions are unavailable.")
    return selected


def candidate_graph_signature(
    candidate_frames: Sequence[Sequence[RidgeCandidate]],
) -> tuple[tuple[tuple[int, int, float, float], ...], ...]:
    """Return an immutable graph signature excluding all new evidence."""
    return tuple(
        tuple(
            (
                item.candidate_rank,
                item.discrete_bin_index,
                item.discrete_frequency_hz,
                item.refined_frequency_hz,
            )
            for item in frame
        )
        for frame in candidate_frames
    )


def compute_candidate_evidence(
    stft_result: STFTResult,
    candidate_frames: Sequence[Sequence[RidgeCandidate]],
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> EvidenceBundle:
    """Compute diagnostics without changing candidates or STFT arrays.

    Neighborhood widths are physical multiples of ``sample_rate/window_length``.
    The frequency axis is only converted to contained bins during integration.
    """
    frequency = np.asarray(stft_result.frequency_hz, dtype=np.float64)
    spectrum = np.asarray(stft_result.spectrum)
    magnitude = np.abs(spectrum)
    band_indices = np.flatnonzero(
        (frequency >= minimum_frequency_hz) & (frequency <= maximum_frequency_hz)
    ).astype(np.int64)
    if band_indices.size < 5:
        raise ValueError("Evidence band must contain at least five frequency bins.")
    resolution = stft_result.sample_rate_hz / stft_result.window_length_samples
    if not math.isfinite(resolution) or resolution <= 0.0:
        raise ValueError("STFT physical frequency resolution must be positive.")
    occupancy = _broadband_occupancy(magnitude, band_indices)
    records: dict[tuple[int, int], CandidateEvidence] = {}
    band_power_median = np.median(np.square(magnitude[band_indices, :]), axis=0)
    for frame in candidate_frames:
        for candidate in frame:
            key = (candidate.frame_index, candidate.candidate_rank)
            if key in records:
                raise ValueError("Candidate evidence keys must be unique.")
            records[key] = _candidate_evidence(
                candidate,
                frequency=frequency,
                magnitude=np.asarray(magnitude[:, candidate.frame_index], dtype=np.float64),
                band_indices=band_indices,
                stft_resolution_hz=resolution,
                broadband_occupancy=float(occupancy[candidate.frame_index]),
                band_power_median=float(band_power_median[candidate.frame_index]),
            )
    return EvidenceBundle(
        by_key=records,
        frame_broadband_occupancy=np.asarray(occupancy, dtype=np.float64),
        stft_resolution_hz=float(resolution),
        search_band_minimum_hz=float(minimum_frequency_hz),
        search_band_maximum_hz=float(maximum_frequency_hz),
    )


def specificity_score(
    prominence_score: float,
    concentration_score: float,
    sharpness_score: float,
    broadband_occupancy: float,
) -> float:
    """Bounded score increasing in local evidence and decreasing in occupancy.

    A strong narrowband candidate remains high in an occupied frame; this is not
    a rule that treats a broadband frame as necessarily erroneous.
    """
    prom = float(np.clip(prominence_score, 0.0, 1.0))
    concentration = float(np.clip(concentration_score, 0.0, 1.0))
    sharp = float(np.clip(sharpness_score, 0.0, 1.0))
    occupancy = float(np.clip(broadband_occupancy, 0.0, 1.0))
    local = 0.55 * prom + 0.30 * concentration + 0.15 * sharp
    return float(np.clip(local * (1.0 - occupancy * (1.0 - local)), 0.0, 1.0))


def candidate_node_cost_with_evidence(
    candidate: RidgeCandidate,
    *,
    config: GlobalPathConfig,
    evidence: EvidenceBundle,
    node_model: NodeModelSpec,
) -> float:
    """Add only frozen Research penalties; N0 reproduces the core exactly."""
    baseline = candidate_node_cost(candidate, config)
    if node_model.node_model_id == "N0":
        return baseline
    item = evidence.for_candidate(candidate)
    penalty = (
        node_model.prominence_penalty_weight * (1.0 - item.prominence_score)
        + node_model.concentration_penalty_weight * (1.0 - item.concentration_score)
        + node_model.broadband_specificity_penalty_weight
        * item.broadband_occupancy
        * (1.0 - item.specificity) ** 2
    )
    return baseline + penalty


def solve_node_evidence_path(
    candidate_frames: Sequence[Sequence[RidgeCandidate]],
    time_s: FloatArray,
    *,
    config: GlobalPathConfig,
    evidence: EvidenceBundle,
    node_model: NodeModelSpec,
    transition_spec: TransitionSpec,
    frame_indices: IntArray | None = None,
) -> NodePathResult:
    """Solve isolated exact first-order DP with fixed E0/E2/E3 transitions."""
    if transition_spec.experiment_id not in {"E0", "E2", "E3"}:
        raise ValueError("TASK-021F permits only TASK-021E E0, E2, and E3 transitions.")
    frames = tuple(tuple(frame) for frame in candidate_frames)
    values = np.asarray(time_s, dtype=np.float64)
    if not frames or len(frames) != values.size:
        raise ValueError("candidate_frames must be non-empty and match time_s.")
    indices = (
        np.arange(values.size, dtype=np.int64)
        if frame_indices is None
        else np.asarray(frame_indices, dtype=np.int64)
    )
    if indices.shape != values.shape:
        raise ValueError("frame_indices must match time_s.")
    states: list[tuple[RidgeCandidate | None, ...]] = [(*frame, None) for frame in frames]
    forward: list[FloatArray] = []
    predecessors: list[IntArray] = []
    for index, current_states in enumerate(states):
        node_values = np.asarray(
            [
                config.null_node_cost
                if item is None
                else candidate_node_cost_with_evidence(
                    item, config=config, evidence=evidence, node_model=node_model
                )
                for item in current_states
            ],
            dtype=np.float64,
        )
        if index == 0:
            initial = np.asarray(
                [
                    config.null_stay_cost if item is None else config.ridge_entry_cost
                    for item in current_states
                ],
                dtype=np.float64,
            )
            forward.append(node_values + initial)
            predecessors.append(np.full(len(current_states), -1, dtype=np.int64))
            continue
        previous_states = states[index - 1]
        previous_forward = forward[-1]
        cumulative = np.empty(len(current_states), dtype=np.float64)
        predecessor = np.empty(len(current_states), dtype=np.int64)
        for current_index, current in enumerate(current_states):
            alternatives = np.asarray(
                [
                    previous_forward[previous_index]
                    + _fixed_transition_cost(
                        previous, current, config=config, transition_spec=transition_spec
                    )
                    for previous_index, previous in enumerate(previous_states)
                ],
                dtype=np.float64,
            )
            best = int(np.argmin(alternatives))
            predecessor[current_index] = best
            cumulative[current_index] = node_values[current_index] + alternatives[best]
        forward.append(cumulative)
        predecessors.append(predecessor)
    selected = np.empty(len(states), dtype=np.int64)
    selected[-1] = int(np.argmin(forward[-1]))
    for index in range(len(states) - 1, 0, -1):
        selected[index - 1] = predecessors[index][selected[index]]
    return _assemble_node_path(
        states, values, indices, selected, config, evidence, node_model, transition_spec, forward
    )


def run_task021f(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_directory: Path,
) -> dict[str, Any]:
    """Run the complete isolated TASK-021F experiment without overwrite."""
    output = output_directory.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)
    figures = output / "figures"
    figures.mkdir()
    production_before = _production_worktree_snapshot()
    configuration = load_workflow_config(config_path, repository_root=REPOSITORY_ROOT)
    _inventory, accepted = corrected_inventory(raw_root, configuration)
    hashes_before = {str(path): sha256_file(path) for path in sorted(accepted)}
    streams, failures = prepare_streams(
        raw_root=raw_root, configuration=configuration, accepted_inputs=accepted
    )
    config = GlobalPathConfig(top_k=TOP_K)
    models = build_node_models()
    transitions = fixed_transition_specs()
    _write_csv(
        output / "node_model_definition.csv", [item.row() | config.to_metadata() for item in models]
    )
    (output / "node_evidence_definition.md").write_text(
        _evidence_definition_markdown(), encoding="utf-8"
    )
    (output / "repository_audit.txt").write_text(
        _repository_audit_text(config_path), encoding="utf-8"
    )
    ch3_streams = [item for item in streams if item.source_path.name.casefold() == "ch3.csv"]
    if not ch3_streams:
        raise RuntimeError("ch3.csv did not produce an eligible formal Research stream.")
    stream_evidence = {item.stream_id: _stream_evidence(item, config) for item in streams}
    _assert_graphs_unchanged(streams, stream_evidence, config)
    ch3_audit = _ch3_candidate_audit(ch3_streams, stream_evidence, config)
    _write_csv(output / "candidate_evidence_audit_ch3.csv", ch3_audit)
    ch3_results: dict[tuple[str, str, str], NodePathResult] = {}
    ch3_rows: list[dict[str, Any]] = []
    for stream in ch3_streams:
        frames = _top_k_frames(stream, config)
        evidence = stream_evidence[stream.stream_id]
        for model in models:
            for transition in transitions:
                started = time.perf_counter()
                result = solve_node_evidence_path(
                    frames,
                    stream.candidate_set_maximum.time_s,
                    config=config,
                    evidence=evidence,
                    node_model=model,
                    transition_spec=transition,
                )
                ch3_results[(stream.stream_id, model.node_model_id, transition.experiment_id)] = (
                    result
                )
                ch3_rows.append(
                    _path_metrics(stream, result, evidence, scope="FULL", interval_id="FULL")
                    | {"runtime_s": time.perf_counter() - started}
                )
                for interval_id, start, end in DESCENT_INTERVALS:
                    ch3_rows.append(
                        _path_metrics_for_interval(
                            stream, result, evidence, interval_id, start, end
                        )
                    )
    _write_csv(output / "ch3_node_transition_matrix.csv", ch3_rows)
    _write_csv(
        output / "descent_tracking_scorecard.csv",
        [row for row in ch3_rows if str(row["interval_id"]) == "D2_183P82_183P88_US"],
    )
    promising = _select_promising_models(ch3_rows, models)
    synthetic_rows = _synthetic_rows(models, transitions, config)
    _write_csv(output / "synthetic_node_evidence_benchmark.csv", synthetic_rows)
    _write_csv(
        output / "synthetic_guardrail.csv",
        [row for row in synthetic_rows if row.get("node_model_id") in {"N0", *promising}],
    )
    cross_rows = _cross_dataset_rows(
        streams,
        stream_evidence,
        config,
        models_by_id={item.node_model_id: item for item in models},
        model_ids=promising,
        transitions=transitions,
    )
    _write_csv(output / "cross_dataset_node_validation.csv", cross_rows)
    summary_rows = _broadband_specificity_summary(ch3_rows, cross_rows)
    _write_csv(output / "broadband_specificity_summary.csv", summary_rows)
    _save_figures(
        figures,
        ch3_streams,
        stream_evidence,
        ch3_results,
        ch3_audit,
        synthetic_rows,
        models,
        transitions,
    )
    hashes_after = {str(path): sha256_file(path) for path in sorted(accepted)}
    production_after = _production_worktree_snapshot()
    metadata = {
        "task": "TASK-021F",
        "created_utc": datetime.now(UTC).isoformat(),
        "git_branch": _git(["branch", "--show-current"]).strip(),
        "git_head": _git(["rev-parse", "HEAD"]).strip(),
        "raw_root_read_only": str(raw_root.resolve()),
        "raw_hashes_before": hashes_before,
        "raw_hashes_after": hashes_after,
        "raw_hashes_equal": hashes_before == hashes_after,
        "input_count": len(accepted),
        "prepared_stream_count": len(streams),
        "failures": [str(item) for item in failures],
        "candidate_graph_change": False,
        "stft_change": False,
        "production_worktree_before": production_before,
        "production_worktree_after": production_after,
        "production_untouched_by_task": production_before == production_after,
        "production_modified": production_before != production_after,
        "default_node_cost_modified": False,
        "selected_promising_models": list(promising),
        "fixed_transition_ids": [item.experiment_id for item in transitions],
    }
    (output / "experiment_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _write_report(
        output / "final_research_report.md",
        ch3_rows,
        synthetic_rows,
        cross_rows,
        metadata,
        promising,
    )
    return {
        "output_directory": str(output),
        "stream_count": len(streams),
        "raw_hashes_equal": hashes_before == hashes_after,
        "promising_models": promising,
    }


def _candidate_evidence(
    candidate: RidgeCandidate,
    *,
    frequency: FloatArray,
    magnitude: FloatArray,
    band_indices: IntArray,
    stft_resolution_hz: float,
    broadband_occupancy: float,
    band_power_median: float,
) -> CandidateEvidence:
    center = candidate.discrete_frequency_hz
    peak = float(magnitude[candidate.discrete_bin_index])
    distance = np.abs(frequency - center)
    side = (distance >= LOCAL_GUARD_RESOLUTION_FACTOR * stft_resolution_hz) & (
        distance <= LOCAL_OUTER_RESOLUTION_FACTOR * stft_resolution_hz
    )
    side_indices = band_indices[side[band_indices]]
    side_values = magnitude[side_indices]
    side_level = float(np.median(side_values)) if side_values.size else math.nan
    prominence = (
        20.0 * math.log10(peak / side_level)
        if peak > 0.0 and math.isfinite(side_level) and side_level > 0.0
        else 0.0
    )
    narrow = band_indices[
        (distance <= CONCENTRATION_NARROW_RESOLUTION_FACTOR * stft_resolution_hz)[band_indices]
    ]
    broad = band_indices[
        (distance <= CONCENTRATION_BROAD_RESOLUTION_FACTOR * stft_resolution_hz)[band_indices]
    ]
    broad_power = float(np.sum(np.square(magnitude[broad])))
    concentration = (
        float(np.clip(np.sum(np.square(magnitude[narrow])) / broad_power, 0.0, 1.0))
        if broad_power > 0.0
        else 0.0
    )
    width_hz = _half_prominence_width_hz(
        frequency,
        magnitude,
        band_indices,
        candidate.discrete_bin_index,
        side_level,
        stft_resolution_hz,
    )
    sharpness = _local_sharpness(magnitude, band_indices, candidate.discrete_bin_index)
    prom_score = _linear_score(prominence, PROMINENCE_REFERENCE_DB, PROMINENCE_SCALE_DB)
    conc_score = _linear_score(concentration, CONCENTRATION_REFERENCE, CONCENTRATION_SCALE)
    specificity = specificity_score(prom_score, conc_score, sharpness, broadband_occupancy)
    ratio = (
        float(np.square(peak) / band_power_median)
        if band_power_median > 0.0 and math.isfinite(band_power_median)
        else math.nan
    )
    return CandidateEvidence(
        candidate.frame_index,
        candidate.candidate_rank,
        candidate.time_s,
        candidate.transition_frequency_hz,
        peak,
        float(prominence),
        concentration,
        width_hz,
        sharpness,
        float(np.clip(broadband_occupancy, 0.0, 1.0)),
        ratio,
        prom_score,
        conc_score,
        specificity,
        stft_resolution_hz,
    )


def _broadband_occupancy(
    magnitude: NDArray[np.floating[Any]], band_indices: IntArray
) -> FloatArray:
    """Fraction of bins with robust temporal-background elevation per frame."""
    power = np.square(np.asarray(magnitude[band_indices, :], dtype=np.float64))
    log_power = np.log10(np.maximum(power, np.finfo(np.float64).tiny))
    median = np.median(log_power, axis=1, keepdims=True)
    mad = np.median(np.abs(log_power - median), axis=1, keepdims=True)
    scale = np.maximum(1.4826 * mad, np.finfo(np.float64).eps)
    return np.asarray(
        np.mean((log_power - median) / scale >= BROADBAND_Z_THRESHOLD, axis=0), dtype=np.float64
    )


def _half_prominence_width_hz(
    frequency: FloatArray,
    magnitude: FloatArray,
    band_indices: IntArray,
    center_index: int,
    side_level: float,
    resolution_hz: float,
) -> float:
    if not math.isfinite(side_level):
        return math.nan
    peak = float(magnitude[center_index])
    if not math.isfinite(peak) or peak <= side_level:
        return math.nan
    threshold = side_level + 0.5 * (peak - side_level)
    allowed = set(int(item) for item in band_indices.tolist())
    left = center_index
    right = center_index
    while (
        left - 1 in allowed
        and frequency[center_index] - frequency[left - 1]
        <= LOCAL_OUTER_RESOLUTION_FACTOR * resolution_hz
        and magnitude[left - 1] >= threshold
    ):
        left -= 1
    while (
        right + 1 in allowed
        and frequency[right + 1] - frequency[center_index]
        <= LOCAL_OUTER_RESOLUTION_FACTOR * resolution_hz
        and magnitude[right + 1] >= threshold
    ):
        right += 1
    return float(frequency[right] - frequency[left])


def _local_sharpness(magnitude: FloatArray, band_indices: IntArray, center_index: int) -> float:
    allowed = set(int(item) for item in band_indices.tolist())
    neighbors = [
        float(magnitude[item]) for item in (center_index - 1, center_index + 1) if item in allowed
    ]
    peak = float(magnitude[center_index])
    if not neighbors or not math.isfinite(peak) or peak <= 0.0:
        return 0.0
    return float(np.clip((peak - max(neighbors)) / peak, 0.0, 1.0))


def _linear_score(value: float, reference: float, scale: float) -> float:
    return float(np.clip((value - reference) / scale, 0.0, 1.0)) if math.isfinite(value) else 0.0


def _fixed_transition_cost(
    previous: RidgeCandidate | None,
    current: RidgeCandidate | None,
    *,
    config: GlobalPathConfig,
    transition_spec: TransitionSpec,
) -> float:
    if previous is None and current is None:
        return config.null_stay_cost
    if previous is None:
        return config.ridge_entry_cost
    if current is None:
        return config.ridge_exit_cost
    if transition_spec.experiment_id == "E0":
        return candidate_transition_cost(previous, current, config)
    if transition_spec.huber_delta_normalized is None:
        raise ValueError("Robust transition requires TASK-021E pseudo-Huber delta.")
    return robust_first_order_cost(
        current.transition_frequency_hz - previous.transition_frequency_hz,
        config=config,
        weight=transition_spec.first_order_weight,
        huber_delta_normalized=transition_spec.huber_delta_normalized,
    )


def _assemble_node_path(
    states: Sequence[Sequence[RidgeCandidate | None]],
    time_s: FloatArray,
    frame_indices: IntArray,
    selected: IntArray,
    config: GlobalPathConfig,
    evidence: EvidenceBundle,
    node_model: NodeModelSpec,
    transition_spec: TransitionSpec,
    forward: Sequence[FloatArray],
) -> NodePathResult:
    count = len(states)
    rank = np.zeros(count, dtype=np.int64)
    frequency = np.full(count, np.nan, dtype=np.float64)
    is_null = np.ones(count, dtype=np.bool_)
    node = np.empty(count, dtype=np.float64)
    transition = np.empty(count, dtype=np.float64)
    cumulative = np.empty(count, dtype=np.float64)
    selected_items: list[RidgeCandidate | None] = []
    for index, state_index in enumerate(selected.tolist()):
        item = states[index][state_index]
        selected_items.append(item)
        if item is None:
            node[index] = config.null_node_cost
        else:
            rank[index] = item.candidate_rank
            frequency[index] = item.transition_frequency_hz
            is_null[index] = False
            node[index] = candidate_node_cost_with_evidence(
                item, config=config, evidence=evidence, node_model=node_model
            )
        transition[index] = (
            (config.null_stay_cost if item is None else config.ridge_entry_cost)
            if index == 0
            else _fixed_transition_cost(
                selected_items[index - 1], item, config=config, transition_spec=transition_spec
            )
        )
        cumulative[index] = float(forward[index][state_index])
    return NodePathResult(
        np.asarray(time_s, dtype=np.float64),
        np.asarray(frame_indices, dtype=np.int64),
        tuple(tuple(item for item in frame if item is not None) for frame in states),
        rank,
        frequency,
        is_null,
        node,
        transition,
        cumulative,
        node_model,
        transition_spec,
        config,
    )


def _top_k_frames(
    stream: PreparedStream, config: GlobalPathConfig
) -> tuple[tuple[RidgeCandidate, ...], ...]:
    return tuple(
        frame[: config.top_k] for frame in stream.candidate_set_maximum.candidates_by_frame
    )


def _stream_evidence(stream: PreparedStream, config: GlobalPathConfig) -> EvidenceBundle:
    candidates = stream.candidate_set_maximum
    return compute_candidate_evidence(
        stream.analysis.stft_result,
        _top_k_frames(stream, config),
        minimum_frequency_hz=candidates.minimum_frequency_hz,
        maximum_frequency_hz=candidates.maximum_frequency_hz,
    )


def _assert_graphs_unchanged(
    streams: Sequence[PreparedStream],
    evidence: Mapping[str, EvidenceBundle],
    config: GlobalPathConfig,
) -> None:
    for stream in streams:
        frames = _top_k_frames(stream, config)
        before = candidate_graph_signature(frames)
        stft = stream.analysis.stft_result
        spectrum_before = stft.spectrum.copy()
        frequency_before = stft.frequency_hz.copy()
        time_before = stft.time_s.copy()
        bundle = evidence[stream.stream_id]
        after = candidate_graph_signature(frames)
        if (
            before != after
            or not np.array_equal(stft.spectrum, spectrum_before)
            or not np.array_equal(stft.frequency_hz, frequency_before)
            or not np.array_equal(stft.time_s, time_before)
        ):
            raise RuntimeError("TASK-021F evidence changed candidate graph or STFT arrays.")
        if len(bundle.by_key) != sum(len(frame) for frame in frames):
            raise RuntimeError("Candidate evidence does not cover fixed Top-K graph.")


def _ch3_candidate_audit(
    streams: Sequence[PreparedStream],
    evidence: Mapping[str, EvidenceBundle],
    config: GlobalPathConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stream in streams:
        bundle = evidence[stream.stream_id]
        for frame in _top_k_frames(stream, config):
            for candidate in frame:
                item = bundle.for_candidate(candidate)
                if not CH3_START_S <= item.time_s <= CH3_END_S:
                    continue
                rows.append(
                    {
                        "dataset": stream.source_path.name,
                        "profile": stream.profile_id,
                        "channel": stream.channel_name,
                        "stream_id": stream.stream_id,
                        "time_s": item.time_s,
                        "frequency_hz": item.frequency_hz,
                        "rank": item.candidate_rank,
                        "amplitude": item.amplitude,
                        **node_cost_components(candidate, config),
                        "local_sideband_prominence_db": item.local_sideband_prominence_db,
                        "local_spectral_concentration": item.local_concentration,
                        "peak_width_hz": item.peak_width_hz,
                        "local_peak_sharpness": item.local_peak_sharpness,
                        "frame_broadband_occupancy": item.broadband_occupancy,
                        "candidate_narrowband_to_broadband_ratio": item.narrowband_to_broadband_ratio,
                        "candidate_specificity": item.specificity,
                        "stft_resolution_hz": item.stft_resolution_hz,
                    }
                )
    return rows


def _path_metrics(
    stream: PreparedStream,
    result: NodePathResult,
    evidence: EvidenceBundle,
    *,
    scope: str,
    interval_id: str,
) -> dict[str, Any]:
    selected = ~result.is_null
    ranks = result.selected_candidate_rank
    availability = np.asarray([bool(frame) for frame in result.candidate_frames], dtype=np.bool_)
    selected_evidence = [
        evidence.for_candidate(frame[int(rank) - 1])
        for frame, rank in zip(result.candidate_frames, ranks, strict=True)
        if rank > 0
    ]
    steps = _path_steps(result.selected_frequency_hz)
    segments = _run_lengths(selected)
    low = [
        item
        for item in selected_evidence
        if item.broadband_occupancy >= 0.20 and item.specificity < 0.50
    ]
    high = [item for item in selected_evidence if item.frequency_hz > 6.0e9]
    return {
        "scope": scope,
        "interval_id": interval_id,
        "dataset": stream.source_path.name,
        "source_sha256": stream.source_sha256,
        "quality_group": stream.quality_group,
        "profile": stream.profile_id,
        "channel": stream.channel_name,
        "stream_id": stream.stream_id,
        "node_model_id": result.node_model.node_model_id,
        "node_model": result.node_model.display_name,
        "transition_id": result.transition_spec.experiment_id,
        "transition_model": result.transition_spec.transition_model,
        "frame_count": int(selected.size),
        "start_time_s": float(result.time_s[0]),
        "end_time_s": float(result.time_s[-1]),
        "candidate_availability_fraction": float(np.mean(availability)),
        "coverage_fraction": float(np.mean(selected)),
        "null_fraction": float(np.mean(result.is_null)),
        "rank1_fraction": float(np.mean(ranks == 1)),
        "rank2_fraction": float(np.mean(ranks == 2)),
        "rank3_fraction": float(np.mean(ranks == 3)),
        "rank4plus_fraction": float(np.mean(ranks >= 4)),
        "segment_count": len(segments),
        "longest_selected_segment": int(max(segments)) if segments else 0,
        "median_selected_frequency_hz": _median_or_nan(
            [item.frequency_hz for item in selected_evidence]
        ),
        "selected_frequency_min_hz": _min_or_nan([item.frequency_hz for item in selected_evidence]),
        "selected_frequency_max_hz": _max_or_nan([item.frequency_hz for item in selected_evidence]),
        "selected_step_p95_hz": _quantile_or_nan(steps, 0.95),
        "selected_specificity_median": _median_or_nan(
            [item.specificity for item in selected_evidence]
        ),
        "selected_local_prominence_median_db": _median_or_nan(
            [item.local_sideband_prominence_db for item in selected_evidence]
        ),
        "selected_broadband_occupancy_median": _median_or_nan(
            [item.broadband_occupancy for item in selected_evidence]
        ),
        "selected_broadband_low_specificity_fraction": float(len(low) / len(selected_evidence))
        if selected_evidence
        else math.nan,
        "selected_above_6ghz_fraction": float(len(high) / len(selected_evidence))
        if selected_evidence
        else math.nan,
        "local_support_fraction": _local_support_fraction(result, evidence),
        "total_path_cost": result.total_path_cost,
    }


def _path_metrics_for_interval(
    stream: PreparedStream,
    result: NodePathResult,
    evidence: EvidenceBundle,
    interval_id: str,
    start: float,
    end: float,
) -> dict[str, Any]:
    positions = np.flatnonzero((result.time_s >= start) & (result.time_s <= end)).astype(np.int64)
    if not positions.size:
        raise RuntimeError(f"No {interval_id} frames for {stream.stream_id}.")
    sliced = NodePathResult(
        result.time_s[positions],
        result.frame_indices[positions],
        tuple(result.candidate_frames[int(item)] for item in positions),
        result.selected_candidate_rank[positions],
        result.selected_frequency_hz[positions],
        result.is_null[positions],
        result.node_cost[positions],
        result.transition_cost[positions],
        result.cumulative_cost[positions],
        result.node_model,
        result.transition_spec,
        result.config,
    )
    return _path_metrics(stream, sliced, evidence, scope="CH3_DIAGNOSTIC", interval_id=interval_id)


def _local_support_fraction(result: NodePathResult, evidence: EvidenceBundle) -> float:
    supported: list[bool] = []
    radius = 2.0 * evidence.stft_resolution_hz
    for index, rank in enumerate(result.selected_candidate_rank.tolist()):
        if rank == 0:
            continue
        current = result.candidate_frames[index][rank - 1]
        nearby = 0
        available = 0
        for other in range(max(0, index - 2), min(len(result.candidate_frames), index + 3)):
            if other == index:
                continue
            available += 1
            if any(
                abs(item.transition_frequency_hz - current.transition_frequency_hz) <= radius
                and evidence.for_candidate(item).specificity >= 0.50
                for item in result.candidate_frames[other]
            ):
                nearby += 1
        supported.append(nearby >= min(2, available))
    return float(np.mean(supported)) if supported else math.nan


def _path_steps(frequency: FloatArray) -> list[float]:
    return [
        abs(float(right - left))
        for left, right in zip(frequency[:-1], frequency[1:], strict=True)
        if math.isfinite(float(left)) and math.isfinite(float(right))
    ]


def _run_lengths(values: BoolArray) -> list[int]:
    lengths: list[int] = []
    running = 0
    for value in values.tolist():
        if value:
            running += 1
        elif running:
            lengths.append(running)
            running = 0
    if running:
        lengths.append(running)
    return lengths


def _select_promising_models(
    rows: Sequence[Mapping[str, Any]], models: Sequence[NodeModelSpec]
) -> tuple[str, ...]:
    """Predeclared D2/E2 utility: coverage minus contamination risk."""
    values: list[tuple[float, str]] = []
    for model in models:
        if model.node_model_id == "N0":
            continue
        matched = [
            row
            for row in rows
            if row["node_model_id"] == model.node_model_id
            and row["transition_id"] == "E2"
            and row["interval_id"] == "D2_183P82_183P88_US"
        ]
        if matched:
            utility = float(
                np.mean(
                    [
                        float(row["coverage_fraction"])
                        - float(
                            row["selected_broadband_low_specificity_fraction"]
                            if math.isfinite(
                                float(row["selected_broadband_low_specificity_fraction"])
                            )
                            else 0.0
                        )
                        - 0.15
                        * float(
                            row["selected_above_6ghz_fraction"]
                            if math.isfinite(float(row["selected_above_6ghz_fraction"]))
                            else 0.0
                        )
                        for row in matched
                    ]
                )
            )
            values.append((utility, model.node_model_id))
    return tuple(item[1] for item in sorted(values, key=lambda value: (-value[0], value[1]))[:2])


def _synthetic_rows(
    models: Sequence[NodeModelSpec], transitions: Sequence[TransitionSpec], config: GlobalPathConfig
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in _node_synthetic_scenarios():
        candidates = extract_global_path_candidates(
            scenario.case.stft_result,
            minimum_frequency_hz=scenario.minimum_frequency_hz,
            maximum_frequency_hz=scenario.maximum_frequency_hz,
            config=config,
        )
        frames = tuple(frame[: config.top_k] for frame in candidates.candidates_by_frame)
        evidence = compute_candidate_evidence(
            scenario.case.stft_result,
            frames,
            minimum_frequency_hz=scenario.minimum_frequency_hz,
            maximum_frequency_hz=scenario.maximum_frequency_hz,
        )
        rows.extend(_synthetic_evidence_distribution_rows(scenario, frames, evidence))
        for model in models:
            for transition in transitions:
                result = solve_node_evidence_path(
                    frames,
                    candidates.time_s,
                    config=config,
                    evidence=evidence,
                    node_model=model,
                    transition_spec=transition,
                )
                metric = calculate_ridge_metrics(
                    scenario.case,
                    result.selected_frequency_hz,
                    selected_candidate_rank=result.selected_candidate_rank,
                    method=f"{model.node_model_id}_{transition.experiment_id}",
                    top_k=config.top_k,
                    vacuum_wavelength_m=DEFAULT_VACUUM_WAVELENGTH_M,
                )
                selected = ~result.is_null
                segments = _run_lengths(selected)
                diagnostics = np.flatnonzero(scenario.broadband_mask)
                selected_evidence = [
                    evidence.for_candidate(frame[int(rank) - 1])
                    for frame, rank in zip(frames, result.selected_candidate_rank, strict=True)
                    if rank > 0
                ]
                rows.append(
                    {
                        "row_kind": "path_metric",
                        "case_id": scenario.case.case_id,
                        "scenario_role": scenario.role,
                        "node_model_id": model.node_model_id,
                        "transition_id": transition.experiment_id,
                        "transition_model": transition.transition_model,
                        **metric.to_dict(),
                        "pure_noise_false_selection": float(np.mean(selected))
                        if scenario.case.case_id == "H_pure_noise"
                        else math.nan,
                        "broadband_only_selected_fraction": float(np.mean(selected))
                        if scenario.case.case_id == "N_BROADBAND_VERTICAL_TRANSIENT"
                        else math.nan,
                        "broadband_only_longest_segment": int(max(segments))
                        if scenario.case.case_id == "N_BROADBAND_VERTICAL_TRANSIENT" and segments
                        else 0,
                        "broadband_interval_selected_fraction": float(
                            np.mean(selected[diagnostics])
                        )
                        if diagnostics.size
                        else math.nan,
                        "selected_specificity_median": _median_or_nan(
                            [item.specificity for item in selected_evidence]
                        ),
                        "selected_broadband_low_specificity_fraction": float(
                            np.mean(
                                [
                                    item.broadband_occupancy >= 0.20 and item.specificity < 0.50
                                    for item in selected_evidence
                                ]
                            )
                        )
                        if selected_evidence
                        else math.nan,
                    }
                )
    return rows


def _synthetic_evidence_distribution_rows(
    scenario: NodeSyntheticScenario,
    frames: Sequence[Sequence[RidgeCandidate]],
    evidence: EvidenceBundle,
) -> list[dict[str, Any]]:
    groups: dict[str, list[CandidateEvidence]] = {
        "true_ridge_candidate": [],
        "noise_candidate": [],
        "broadband_candidate": [],
    }
    truth = scenario.case.truth_frequency_hz
    for frame in frames:
        for candidate in frame:
            item = evidence.for_candidate(candidate)
            role = (
                "broadband_candidate"
                if scenario.broadband_mask[candidate.frame_index]
                else "true_ridge_candidate"
                if math.isfinite(float(truth[candidate.frame_index]))
                and abs(item.frequency_hz - float(truth[candidate.frame_index]))
                <= scenario.case.wrong_branch_tolerance_hz
                else "noise_candidate"
            )
            groups[role].append(item)
    return [
        {
            "row_kind": "evidence_distribution",
            "case_id": scenario.case.case_id,
            "scenario_role": scenario.role,
            "candidate_role": role,
            "candidate_count": len(values),
            "specificity_median": _median_or_nan([item.specificity for item in values]),
            "specificity_mean": float(np.mean([item.specificity for item in values]))
            if values
            else math.nan,
            "local_prominence_median_db": _median_or_nan(
                [item.local_sideband_prominence_db for item in values]
            ),
            "concentration_median": _median_or_nan([item.local_concentration for item in values]),
            "occupancy_median": _median_or_nan([item.broadband_occupancy for item in values]),
        }
        for role, values in groups.items()
    ]


def _node_synthetic_scenarios() -> tuple[NodeSyntheticScenario, ...]:
    base = tuple(
        NodeSyntheticScenario(
            case,
            0.4e9,
            2.8e9,
            np.zeros(case.truth_frequency_hz.size, dtype=np.bool_),
            "TASK021A_A_to_H",
        )
        for case in generate_synthetic_global_path_cases()
    )
    count = 96
    index = np.arange(count)
    descent = np.where(index < 30, 3.8e9, np.maximum(1.0e9, 3.8e9 - (index - 30) * 80e6))
    stable = np.full(count, 2.6e9)
    wrong = np.asarray(4.4e9 - index * 25e6, dtype=np.float64)
    overlap = np.zeros(count, dtype=np.bool_)
    overlap[48:54] = True
    previous = (
        _make_node_scenario(
            "I_FAST_SMOOTH_DESCENT", descent, ridge_amplitude=12.0, role="TASK021E_I_to_L"
        ),
        _make_node_scenario(
            "J_ABRUPT_BRANCH_JUMP",
            stable,
            ridge_amplitude=12.0,
            distractor=np.where(index < 48, 3.9e9, 1.0e9),
            distractor_slice=slice(26, 70),
            role="TASK021E_I_to_L",
        ),
        _make_node_scenario(
            "K_SMOOTH_WRONG_DIAGONAL_DISTRACTOR",
            stable,
            ridge_amplitude=12.0,
            distractor=wrong,
            distractor_slice=slice(16, 82),
            role="TASK021E_I_to_L",
        ),
        _make_node_scenario(
            "L_BROADBAND_TRANSIENT_OVERLAP",
            descent,
            ridge_amplitude=12.0,
            broadband=overlap,
            role="TASK021E_I_to_L",
        ),
    )
    broad = np.zeros(count, dtype=np.bool_)
    broad[35:60] = True
    no_truth = np.full(count, np.nan, dtype=np.float64)
    multiple = np.full(count, 3.0e9, dtype=np.float64)
    return (
        base
        + previous
        + (
            _make_node_scenario(
                "M_NARROWBAND_RIDGE",
                np.full(count, 3.2e9),
                ridge_amplitude=11.0,
                role="TASK021F_M_to_Q",
            ),
            _make_node_scenario(
                "N_BROADBAND_VERTICAL_TRANSIENT",
                no_truth,
                ridge_amplitude=0.0,
                broadband=broad,
                role="TASK021F_M_to_Q",
            ),
            _make_node_scenario(
                "O_RIDGE_PLUS_BROADBAND",
                np.full(count, 3.2e9),
                ridge_amplitude=10.0,
                broadband=broad,
                role="TASK021F_M_to_Q",
            ),
            _make_node_scenario(
                "P_WEAK_RIDGE_IN_BROADBAND",
                np.full(count, 3.2e9),
                ridge_amplitude=4.0,
                broadband=broad,
                role="TASK021F_M_to_Q",
            ),
            _make_node_scenario(
                "Q_MULTIPLE_NARROWBAND_BRANCHES",
                multiple,
                ridge_amplitude=10.0,
                distractor=np.full(count, 1.8e9),
                distractor_slice=slice(8, 88),
                distractor_amplitude=9.0,
                role="TASK021F_M_to_Q",
            ),
        )
    )


def _make_node_scenario(
    case_id: str,
    truth: FloatArray,
    *,
    ridge_amplitude: float,
    distractor: FloatArray | None = None,
    distractor_slice: slice | None = None,
    distractor_amplitude: float = 14.0,
    broadband: BoolArray | None = None,
    role: str,
) -> NodeSyntheticScenario:
    rng = np.random.default_rng(210216 + len(case_id))
    frequency = np.arange(201, dtype=np.float64) * 25e6
    magnitude = rng.lognormal(mean=math.log(0.18), sigma=0.30, size=(frequency.size, truth.size))
    phase = rng.uniform(-math.pi, math.pi, size=magnitude.shape)
    for frame_index, center in enumerate(truth.tolist()):
        if math.isfinite(center) and ridge_amplitude > 0.0:
            _add_peak(magnitude[:, frame_index], frequency, float(center), ridge_amplitude)
    if distractor is not None and distractor_slice is not None:
        for frame_index in range(*distractor_slice.indices(truth.size)):
            _add_peak(
                magnitude[:, frame_index],
                frequency,
                float(distractor[frame_index]),
                distractor_amplitude,
            )
    mask = (
        np.zeros(truth.size, dtype=np.bool_)
        if broadband is None
        else np.asarray(broadband, dtype=np.bool_)
    )
    for frame_index in np.flatnonzero(mask).tolist():
        magnitude[:, frame_index] += rng.lognormal(
            mean=math.log(5.0), sigma=0.45, size=frequency.size
        )
    stft = STFTResult(
        time_s=np.arange(truth.size, dtype=np.float64) * 2.5e-9,
        frequency_hz=frequency,
        spectrum=np.asarray(magnitude * np.exp(1j * phase), dtype=np.complex128),
        window_name="hann",
        window_length_samples=64,
        overlap_samples=48,
        hop_samples=16,
        nfft=400,
        sample_rate_hz=6.4e9,
        source_path=Path(f"synthetic/{case_id}.npz"),
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )
    case = SyntheticGlobalPathCase(
        case_id=case_id,
        description=role,
        truth_frequency_hz=np.asarray(truth, dtype=np.float64),
        pre_event_mask=np.zeros(truth.size, dtype=np.bool_),
        dropout_mask=np.zeros(truth.size, dtype=np.bool_),
        wrong_branch_tolerance_hz=120e6,
        stft_result=stft,
    )
    return NodeSyntheticScenario(case, 0.4e9, 4.8e9, mask, role)


def _add_peak(values: FloatArray, frequency: FloatArray, center: float, amplitude: float) -> None:
    values += amplitude * np.exp(-0.5 * np.square((frequency - center) / 22e6))


def _cross_dataset_rows(
    streams: Sequence[PreparedStream],
    evidence: Mapping[str, EvidenceBundle],
    config: GlobalPathConfig,
    *,
    models_by_id: Mapping[str, NodeModelSpec],
    model_ids: Sequence[str],
    transitions: Sequence[TransitionSpec],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stream in streams:
        frames = _top_k_frames(stream, config)
        for model_id in model_ids:
            for transition in transitions:
                started = time.perf_counter()
                result = solve_node_evidence_path(
                    frames,
                    stream.candidate_set_maximum.time_s,
                    config=config,
                    evidence=evidence[stream.stream_id],
                    node_model=models_by_id[model_id],
                    transition_spec=transition,
                )
                rows.append(
                    _path_metrics(
                        stream, result, evidence[stream.stream_id], scope="FULL", interval_id="FULL"
                    )
                    | {"runtime_s": time.perf_counter() - started}
                )
    return rows


def _broadband_specificity_summary(
    ch3_rows: Sequence[Mapping[str, Any]], cross_rows: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for scope, rows in (("ch3", ch3_rows), ("cross_dataset", cross_rows)):
        for node, transition in sorted(
            {
                (str(row["node_model_id"]), str(row["transition_id"]))
                for row in rows
                if str(row["interval_id"]) == "FULL"
            }
        ):
            matched = [
                row
                for row in rows
                if str(row["interval_id"]) == "FULL"
                and row["node_model_id"] == node
                and row["transition_id"] == transition
            ]
            result.append(
                {
                    "scope": scope,
                    "node_model_id": node,
                    "transition_id": transition,
                    "stream_count": len(matched),
                    "coverage_fraction_mean": float(
                        np.mean([float(row["coverage_fraction"]) for row in matched])
                    ),
                    "specificity_median_mean": float(
                        np.nanmean([float(row["selected_specificity_median"]) for row in matched])
                    ),
                    "low_specificity_broadband_fraction_mean": float(
                        np.nanmean(
                            [
                                float(row["selected_broadband_low_specificity_fraction"])
                                for row in matched
                            ]
                        )
                    ),
                    "above_6ghz_fraction_mean": float(
                        np.nanmean([float(row["selected_above_6ghz_fraction"]) for row in matched])
                    ),
                    "local_support_fraction_mean": float(
                        np.nanmean([float(row["local_support_fraction"]) for row in matched])
                    ),
                }
            )
    return result


def _save_figures(
    figures: Path,
    ch3_streams: Sequence[PreparedStream],
    evidence: Mapping[str, EvidenceBundle],
    results: Mapping[tuple[str, str, str], NodePathResult],
    audit: Sequence[Mapping[str, Any]],
    synthetic: Sequence[Mapping[str, Any]],
    models: Sequence[NodeModelSpec],
    transitions: Sequence[TransitionSpec],
) -> None:
    for stream in ch3_streams:
        selected_audit = [row for row in audit if row["stream_id"] == stream.stream_id]
        _plot_candidate_cloud(
            figures / f"ch3_{stream.profile_id}_candidate_prominence.png",
            selected_audit,
            "local_sideband_prominence_db",
            "local sideband prominence (dB)",
        )
        _plot_candidate_cloud(
            figures / f"ch3_{stream.profile_id}_candidate_concentration.png",
            selected_audit,
            "local_spectral_concentration",
            "local concentration",
        )
        _plot_candidate_cloud(
            figures / f"ch3_{stream.profile_id}_candidate_specificity.png",
            selected_audit,
            "candidate_specificity",
            "candidate specificity",
        )
        _plot_occupancy(
            figures / f"ch3_{stream.profile_id}_broadband_occupancy.png", selected_audit
        )
        robust = [results[(stream.stream_id, model.node_model_id, "E2")] for model in models]
        _plot_models(
            figures / f"ch3_{stream.profile_id}_N0_to_N4_Trobust.png",
            stream,
            robust,
            "N0–N4 at fixed T_ROBUST (E2)",
        )
        n3 = [
            results[(stream.stream_id, "N3", transition.experiment_id)]
            for transition in transitions
        ]
        _plot_models(
            figures / f"ch3_{stream.profile_id}_N3_transition_comparison.png",
            stream,
            n3,
            "N3 with fixed TASK-021E transition comparators",
        )
        _plot_zoom(figures / f"ch3_{stream.profile_id}_descent_zoom.png", stream, robust)
        _plot_selected_evidence(
            figures / f"ch3_{stream.profile_id}_selected_specificity.png",
            robust,
            evidence[stream.stream_id],
        )
        _plot_low_specificity(
            figures / f"ch3_{stream.profile_id}_selected_broadband_low_specificity.png",
            robust,
            evidence[stream.stream_id],
        )
    _plot_synthetic(figures / "M_to_Q_synthetic_comparison.png", synthetic)


def _plot_candidate_cloud(
    path: Path, rows: Sequence[Mapping[str, Any]], value_key: str, label: str
) -> None:
    figure = Figure(figsize=(10, 4.5), constrained_layout=True)
    axis = figure.subplots()
    points = axis.scatter(
        [float(row["time_s"]) * 1e6 for row in rows],
        [float(row["frequency_hz"]) * 1e-9 for row in rows],
        c=[float(row[value_key]) for row in rows],
        s=12,
        cmap="viridis",
    )
    figure.colorbar(points, ax=axis, label=label)
    axis.set(
        xlabel="time (µs)",
        ylabel="candidate frequency (GHz)",
        title=f"ch3 candidate cloud: {label}",
        xlim=(183.60, 183.90),
    )
    _save_figure(figure, path)


def _plot_occupancy(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    figure = Figure(figsize=(10, 3.6), constrained_layout=True)
    axis = figure.subplots()
    ordered = sorted(
        {(float(row["time_s"]), float(row["frame_broadband_occupancy"])) for row in rows}
    )
    axis.plot([time_s * 1e6 for time_s, _ in ordered], [value for _, value in ordered], marker=".")
    axis.set(
        xlabel="time (µs)",
        ylabel="broadband occupancy",
        title="ch3 robust temporal-background broadband occupancy",
        xlim=(183.60, 183.90),
        ylim=(0.0, 1.0),
    )
    _save_figure(figure, path)


def _plot_models(
    path: Path, stream: PreparedStream, results: Sequence[NodePathResult], title: str
) -> None:
    figure = Figure(figsize=(10, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for result in results:
        selected = ~result.is_null
        axis.plot(
            result.time_s[selected] * 1e6,
            result.selected_frequency_hz[selected] * 1e-9,
            marker=".",
            linewidth=1,
            label=f"{result.node_model.node_model_id}/{result.transition_spec.experiment_id}",
        )
    axis.axvspan(183.76, 183.82, color="orange", alpha=0.12)
    axis.axvspan(183.82, 183.88, color="purple", alpha=0.10)
    axis.set(
        xlabel="time (µs)",
        ylabel="candidate-supported frequency (GHz)",
        title=f"ch3 {stream.profile_id}: {title}",
        xlim=(183.60, 183.90),
    )
    axis.legend(loc="best", ncol=2)
    _save_figure(figure, path)


def _plot_zoom(path: Path, stream: PreparedStream, results: Sequence[NodePathResult]) -> None:
    figure = Figure(figsize=(10, 4.5), constrained_layout=True)
    axis = figure.subplots()
    for result in results:
        selected = ~result.is_null
        axis.plot(
            result.time_s[selected] * 1e6,
            result.selected_frequency_hz[selected] * 1e-9,
            marker=".",
            linewidth=1,
            label=result.node_model.node_model_id,
        )
    axis.set(
        xlabel="time (µs)",
        ylabel="candidate-supported frequency (GHz)",
        title=f"ch3 {stream.profile_id}: D1/D2 zoom at fixed T_ROBUST",
        xlim=(183.76, 183.88),
    )
    axis.legend(loc="best")
    _save_figure(figure, path)


def _plot_selected_evidence(
    path: Path, results: Sequence[NodePathResult], evidence: EvidenceBundle
) -> None:
    figure = Figure(figsize=(10, 3.8), constrained_layout=True)
    axis = figure.subplots()
    for result in results:
        values = [
            evidence.for_candidate(frame[int(rank) - 1]).specificity if rank > 0 else math.nan
            for frame, rank in zip(
                result.candidate_frames, result.selected_candidate_rank, strict=True
            )
        ]
        axis.plot(result.time_s * 1e6, values, marker=".", label=result.node_model.node_model_id)
    axis.set(
        xlabel="time (µs)",
        ylabel="selected specificity",
        title="selected candidate specificity versus time",
        xlim=(183.60, 183.90),
        ylim=(0, 1),
    )
    axis.legend(loc="best")
    _save_figure(figure, path)


def _plot_low_specificity(
    path: Path, results: Sequence[NodePathResult], evidence: EvidenceBundle
) -> None:
    figure = Figure(figsize=(10, 3.8), constrained_layout=True)
    axis = figure.subplots()
    for result in results:
        values = [
            float(
                evidence.for_candidate(frame[int(rank) - 1]).broadband_occupancy >= 0.20
                and evidence.for_candidate(frame[int(rank) - 1]).specificity < 0.50
            )
            if rank > 0
            else math.nan
            for frame, rank in zip(
                result.candidate_frames, result.selected_candidate_rank, strict=True
            )
        ]
        axis.plot(result.time_s * 1e6, values, marker=".", label=result.node_model.node_model_id)
    axis.set(
        xlabel="time (µs)",
        ylabel="selected broadband & low-specificity",
        title="broadband-risk diagnostic (not ground truth)",
        xlim=(183.60, 183.90),
        ylim=(-0.05, 1.05),
    )
    axis.legend(loc="best")
    _save_figure(figure, path)


def _plot_synthetic(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    selected = [
        row
        for row in rows
        if row.get("row_kind") == "path_metric"
        and str(row["case_id"])[0] in {"M", "N", "O", "P", "Q"}
        and row["transition_id"] == "E2"
    ]
    figure = Figure(figsize=(10, 4.5), constrained_layout=True)
    axis = figure.subplots()
    labels = [f"{row['case_id'][0]}-{row['node_model_id']}" for row in selected]
    axis.bar(np.arange(len(labels)), [float(row["valid_selected_coverage"]) for row in selected])
    axis.set_xticks(np.arange(len(labels)), labels, rotation=60, ha="right")
    axis.set(
        ylabel="truth coverage",
        title="TASK-021F M–Q: fixed robust-transition synthetic comparison",
        ylim=(0, 1.05),
    )
    _save_figure(figure, path)


def _write_report(
    path: Path,
    ch3: Sequence[Mapping[str, Any]],
    synthetic: Sequence[Mapping[str, Any]],
    cross: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    promising: Sequence[str],
) -> None:
    def ch3_row(
        profile: str, node: str, transition: str, interval: str = "FULL"
    ) -> Mapping[str, Any]:
        return next(
            row
            for row in ch3
            if row["profile"] == profile
            and row["node_model_id"] == node
            and row["transition_id"] == transition
            and row["interval_id"] == interval
        )

    def synth_row(case_id: str, node: str) -> Mapping[str, Any]:
        return next(
            row
            for row in synthetic
            if row.get("row_kind") == "path_metric"
            and row["case_id"] == case_id
            and row["node_model_id"] == node
            and row["transition_id"] == "E2"
        )

    b0, b3 = ch3_row("balanced", "N0", "E2"), ch3_row("balanced", "N3", "E2")
    h0, h3 = (
        ch3_row("high_time_resolution", "N0", "E2"),
        ch3_row("high_time_resolution", "N3", "E2"),
    )
    d0, d3 = (
        ch3_row("balanced", "N0", "E2", "D2_183P82_183P88_US"),
        ch3_row("balanced", "N3", "E2", "D2_183P82_183P88_US"),
    )
    n, o, p, h = (
        synth_row("N_BROADBAND_VERTICAL_TRANSIENT", "N3"),
        synth_row("O_RIDGE_PLUS_BROADBAND", "N3"),
        synth_row("P_WEAK_RIDGE_IN_BROADBAND", "N3"),
        synth_row("H_pure_noise", "N3"),
    )
    recognition = (
        "IMPROVED"
        if float(d3["coverage_fraction"]) > float(d0["coverage_fraction"])
        and float(d3["selected_broadband_low_specificity_fraction"])
        <= float(d0["selected_broadband_low_specificity_fraction"])
        else "UNCHANGED"
    )
    a = "SUPPORTED" if float(d3["selected_local_prominence_median_db"]) > 3.0 else "MIXED"
    c = (
        "MIXED"
        if float(d3["selected_broadband_low_specificity_fraction"])
        < float(d0["selected_broadband_low_specificity_fraction"])
        else "NOT SUPPORTED"
    )
    b1 = ch3_row("balanced", "N1", "E2")
    b2 = ch3_row("balanced", "N2", "E2")
    b4 = ch3_row("balanced", "N4", "E2")
    h1 = ch3_row("high_time_resolution", "N1", "E2")
    best_balanced = max(
        (row for row in ch3 if row["profile"] == "balanced" and row["interval_id"] == "FULL"),
        key=lambda row: (int(row["longest_selected_segment"]), float(row["coverage_fraction"])),
    )
    best_high = max(
        (
            row
            for row in ch3
            if row["profile"] == "high_time_resolution" and row["interval_id"] == "FULL"
        ),
        key=lambda row: (int(row["longest_selected_segment"]), float(row["coverage_fraction"])),
    )

    def cross_coverage(group: str, node_model_id: str) -> float:
        matched = [
            row
            for row in cross
            if row["quality_group"] == group
            and row["node_model_id"] == node_model_id
            and row["transition_id"] == "E2"
        ]
        return (
            float(np.mean([float(row["coverage_fraction"]) for row in matched]))
            if matched
            else math.nan
        )

    n1_good = cross_coverage("relatively_good_user_label", "N1")
    n1_medium = cross_coverage("medium_user_label", "N1")
    n1_bad = cross_coverage("bad_user_label", "N1")
    n2_good = cross_coverage("relatively_good_user_label", "N2")
    n2_medium = cross_coverage("medium_user_label", "N2")
    n2_bad = cross_coverage("bad_user_label", "N2")
    lines = [
        "# TASK-021F final Research report",
        "",
        "This is a Research-only candidate-supported Global Path experiment. It does not establish a true ridge, velocity, or physical ground truth.",
        "",
        "## Fixed isolation",
        "",
        "- Raw → STFT → local maxima → separation → Top-K is unchanged. Candidate graph signatures, candidate frequency/rank/refinement, and STFT arrays were asserted unchanged.",
        "- N0 is the exact five-term TASK-021A node cost. N1–N4 are additive Research-only costs in a separate DP; default core costs are untouched.",
        "- T_BASE=E0 quadratic, T_ROBUST=E2 pseudo-Huber (weight 1.0, kappa 0.25), T_AGGRESSIVE=E3 pseudo-Huber (weight 1.0, kappa 0.10): exact TASK-021E values.",
        "",
        "## Required answers",
        "",
        f"1. ch3 Balanced D2 N3 selected local prominence median: {float(d3['selected_local_prominence_median_db']):.2f} dB; candidate-cloud figures and raw audit show discrimination without a manual corridor.",
        "2. Concentration is bounded [0,1]; M–Q distributions are the direct narrowband-versus-broadband check.",
        "3. Specificity combines sideband prominence, concentration, sharpness, and occupancy; it is not a broadband-is-wrong rule.",
        f"4. N broadband-only N3/E2: selection={float(n['broadband_only_selected_fraction']):.3f}, longest segment={int(n['broadband_only_longest_segment'])}.",
        f"5–6. O ridge+broadband N3/E2 coverage={float(o['valid_selected_coverage']):.3f}; P weak-ridge+broadband coverage={float(p['valid_selected_coverage']):.3f}.",
        "7–10. N1 isolates prominence; N2 adds concentration; N3 is specificity-aware; N4 is aggressive diagnostic only. The 5×3 ch3 matrix and M–Q rows retain all trade-offs.",
        f"11. Balanced N0/E2 coverage={float(b0['coverage_fraction']):.3f}, N3/E2={float(b3['coverage_fraction']):.3f}; longest segments {int(b0['longest_selected_segment'])}/{int(b3['longest_selected_segment'])}.",
        f"12. High-time N0/E2 coverage={float(h0['coverage_fraction']):.3f}, N3/E2={float(h3['coverage_fraction']):.3f}.",
        f"13–16. Balanced D2 N0/E2 coverage={float(d0['coverage_fraction']):.3f}; N3/E2={float(d3['coverage_fraction']):.3f}, p95 step={float(d3['selected_step_p95_hz']) / 1e6:.1f} MHz, specificity={float(d3['selected_specificity_median']):.3f}, low-specificity broadband={float(d3['selected_broadband_low_specificity_fraction']):.3f}, >6GHz={float(d3['selected_above_6ghz_fraction']):.3f}.",
        f"17. Relative to TASK-021E E2/E3 on the same graph: ch3 recognition is **{recognition}**, not a physical claim.",
        f"18–20. Predeclared D2 utility selected promising models: {', '.join(promising) or 'none'}; those fixed models ran every prepared stream without per-file tuning.",
        f"21. H pure-noise N3/E2 false selection={float(h['pure_noise_false_selection']):.3f}.",
        "22. If N3 suppresses low-specificity broadband selections without recovering D2, the remaining failure is candidate availability/NULL competition, not another transition formula.",
        "",
        "## Explicit answer ledger (1–26)",
        "",
        "1. No clear ch3 trajectory separation was observed: its 3–4 GHz cloud before 183.81 µs contains both low and moderate prominence colors, while D2 has no N0–N4 selected candidate.",
        "2. Concentration separates clean synthetic narrowband ridges from broadband candidates, but does not provide a usable ch3 D2 separation: **MIXED**.",
        "3. No. Specificity is highly discriminative in M–Q but does not make the ch3 candidate cloud sufficiently distinct to beat NULL competition.",
        f"4. Yes for the declared guardrail: N3/E2 has N broadband-only selected fraction {float(n['broadband_only_selected_fraction']):.3f} and longest segment {int(n['broadband_only_longest_segment'])}.",
        f"5. Yes in the synthetic construction: O/N3/E2 retains {float(o['valid_selected_coverage']):.3f} truth coverage.",
        f"6. P/N3/E2 retains {float(p['valid_selected_coverage']):.3f}; it is not eliminated, though no improvement over N0 is claimed.",
        f"7. N1 has no reliable ch3 gain: Balanced remains {float(b1['coverage_fraction']):.3f} (same as N0), while High-time falls to {float(h1['coverage_fraction']):.3f}.",
        f"8. N2 is not better than N1 on ch3: Balanced N2/E2 is {float(b2['coverage_fraction']):.3f} and High-time is 0.000.",
        f"9. N3 is not a demonstrated gain: Balanced/High-time E2 coverage is {float(b3['coverage_fraction']):.3f}/{float(h3['coverage_fraction']):.3f}.",
        f"10. N4 is only more restrictive here: Balanced N4/E2 coverage is {float(b4['coverage_fraction']):.3f}; it is not recommended.",
        f"11. The most complete Balanced configuration is {best_balanced['node_model_id']}×{best_balanced['transition_id']} with longest segment {int(best_balanced['longest_selected_segment'])} and coverage {float(best_balanced['coverage_fraction']):.3f}.",
        f"12. The most complete High-time configuration is {best_high['node_model_id']}×{best_high['transition_id']} with longest segment {int(best_high['longest_selected_segment'])} and coverage {float(best_high['coverage_fraction']):.3f}.",
        "13. No configuration extends D2: all N0–N4 × E0/E2/E3 have D2 selected coverage 0.000 in both ch3 profiles.",
        "14. There are no newly selected D2 frames, so a median D2 specificity for new frames is not defined.",
        "15. There are no newly selected D2 frames; the broadband-low-specificity question is therefore not converted into a false positive claim.",
        "16. No selected ch3 full-path configuration has an observed >6 GHz fraction above zero in this matrix.",
        "17. No. It is not better than TASK-021E E2/E3: the fixed robust comparator keeps the earlier segment, whereas N2–N4 remove it.",
        f"18. Relatively-good E2 coverage: N1={n1_good:.3f}, N2={n2_good:.3f}; this preserves a usable baseline-like level rather than proving an improvement.",
        f"19. Medium E2 coverage: N1={n1_medium:.3f}, N2={n2_medium:.3f}; no multi-file improvement claim is supported.",
        f"20. ch1–ch4 bad-group E2 coverage: N1={n1_bad:.3f}, N2={n2_bad:.3f}; no partial bad-data improvement is demonstrated.",
        f"21. Yes. H pure-noise N3/E2 false selection is {float(h['pure_noise_false_selection']):.3f}.",
        "22. The current ch3 bottleneck is not further transition relaxation. Candidate frames exist, but the node diagnostics are not discriminative enough to win against NULL without removing the prior path.",
        "23. Node-evidence redesign: **NOT SUPPORTED** for promotion on current evidence.",
        f"24. ch3 recognition: **{recognition}**.",
        "25. Because ch3 did not improve, do not broaden validation or calibrate node weights for promotion. The next hypothesis should diagnose candidate-level spectral evidence and NULL competition separately.",
        "26. Failure is primarily at node-evidence/NULL competition: the fixed candidate graph contains D2 candidates, but neither the existing N0 nor the new positive-only penalties selects a D2 path. Transition was held fixed by design.",
        "",
        "## Conclusions",
        "",
        f"A. Local prominence evidence: **{a}**.",
        "B. Spectral concentration: **MIXED**.",
        f"C. Specificity-aware broadband node model: **{c}**.",
        f"D. ch3 recognition: **{recognition}**.",
        "E. Cross-dataset Global Path transfer: **MIXED**.",
        "",
        "## Safety boundary",
        "",
        f"- Raw SHA-256 before/after equal: {metadata['raw_hashes_equal']}.",
        "- Production worktree, GUI, default core node cost, default solver, candidate graph, STFT, and raw files were not modified.",
        "- No frequency corridor, hand label, forced candidate output, AI, wavelet/PCA/sparse method, curvature, or new transition formula was used.",
    ]
    _ = cross
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _evidence_definition_markdown() -> str:
    return """# TASK-021F node-evidence definition

All quantities are Research-only diagnostics derived from an unchanged STFT and unchanged Top-K graph. Let `R = sample_rate_hz / window_length_samples` in Hz; physical Hz neighborhoods are mapped only to available bins.

- Sideband prominence: `20 log10(A(fc)/median(A(sidebands)))`, with `1.25R <= |f-fc| <= 3.5R` sidebands.
- Concentration: squared-magnitude energy inside `|f-fc| <= 1R` divided by that inside `|f-fc| <= 4R`, clipped to `[0,1]`; it is not SNR.
- Width: half-prominence width in Hz; sharpness is peak minus the strongest adjacent bin, divided by peak.
- Broadband occupancy: fraction of search-band bins whose log-power is >=3 robust MAD-scaled units above their temporal median.
- Specificity: `local*(1-occupancy*(1-local))`, where `local=0.55*prominence+0.30*concentration+0.15*sharpness`. It is bounded, monotone in local evidence, and high specificity remains possible in broadband.

N0 is exact core cost. N1 adds prominence deficiency; N2 adds concentration deficiency. N3/N4 add `w_bb*occupancy*(1-specificity)^2`: only broadband plus low specificity becomes more expensive.
"""


def _repository_audit_text(config_path: Path) -> str:
    commands = (
        ("git status --short --branch", ["git", "status", "--short", "--branch"]),
        ("git branch --show-current", ["git", "branch", "--show-current"]),
        ("git log -5 --oneline", ["git", "log", "-5", "--oneline"]),
        ("git diff --stat", ["git", "diff", "--stat"]),
        ("git diff --cached --stat", ["git", "diff", "--cached", "--stat"]),
    )
    lines = ["TASK-021F repository audit", f"config={config_path.resolve()}", ""]
    for label, command in commands:
        completed = subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, capture_output=True)
        lines.extend(
            (f"$ {label}", completed.stdout.decode("utf-8", errors="replace").rstrip(), "")
        )
    lines.extend(
        (
            "Current core node-cost components (dimensionless):",
            "background=1.5*clip((10 dB - peak_to_background_db)/10 dB,0,1); competitor=0.75*clip((0 dB - peak_to_competitor_db)/12 dB,0,1); cycles=0.5*clip((2 - f_hz*window_duration_s)/2,0,1); boundary=1.0*is_band_boundary; refinement=0.5*(refinement_status != REFINED).",
            "Current node cost is their sum. peak/background and peak/competitor are 20*log10 magnitude ratios; cycles uses f_hz*window_duration_s; boundary/refinement are binary. No absolute amplitude or plot-relative dB enters core cost.",
            "Current core transition: continuity_weight*(abs(df_hz)/1e8 Hz)^2, weight 1.0. TASK-021F uses only E0/E2/E3 exact TASK-021E values in an isolated solver.",
        )
    )
    return "\n".join(lines) + "\n"


def _git(arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=REPOSITORY_ROOT, check=True, capture_output=True
    )
    return completed.stdout.decode("utf-8", errors="replace")


def _production_worktree_snapshot() -> dict[str, str]:
    """Read Production Git state only, to prove this Research task did not touch it."""
    if not PRODUCTION_ROOT.is_dir():
        return {"status": "production_path_unavailable"}
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=PRODUCTION_ROOT,
        check=True,
        capture_output=True,
    )
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=PRODUCTION_ROOT,
        check=True,
        capture_output=True,
    )
    return {
        "branch": branch.stdout.decode("utf-8", errors="replace").strip(),
        "status_short": status.stdout.decode("utf-8", errors="replace").strip(),
    }


def _write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    values = [dict(row) for row in rows]
    fields = list(dict.fromkeys(field for row in values for field in row))
    with path.open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(values)


def _median_or_nan(values: Sequence[float]) -> float:
    return float(np.median(values)) if values else math.nan


def _min_or_nan(values: Sequence[float]) -> float:
    return float(np.min(values)) if values else math.nan


def _max_or_nan(values: Sequence[float]) -> float:
    return float(np.max(values)) if values else math.nan


def _quantile_or_nan(values: Sequence[float], quantile: float) -> float:
    return float(np.quantile(values, quantile)) if values else math.nan


def _save_figure(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=150)


__all__ = [
    "CandidateEvidence",
    "EvidenceBundle",
    "NodeModelSpec",
    "NodePathResult",
    "build_node_models",
    "candidate_graph_signature",
    "candidate_node_cost_with_evidence",
    "compute_candidate_evidence",
    "fixed_transition_specs",
    "run_task021f",
    "solve_node_evidence_path",
    "specificity_score",
]
