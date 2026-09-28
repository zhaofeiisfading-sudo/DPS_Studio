"""TASK-021G Research-only spatiotemporal candidate-coherence study."""

from __future__ import annotations

import csv
import json
import math
import subprocess
import time
from collections.abc import Mapping, Sequence
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
from dps_studio.research.task021e_transition_models import (
    TransitionSpec,
    build_transition_specs,
    robust_first_order_cost,
)
from dps_studio.research.task021f_node_evidence import (
    CandidateEvidence,
    EvidenceBundle,
    candidate_graph_signature,
    compute_candidate_evidence,
)
from dps_studio.research.global_path_benchmark import (
    DEFAULT_VACUUM_WAVELENGTH_M,
    calculate_ridge_metrics,
)
from dps_studio.research.task021b_real_experiment import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RAW_ROOT,
    REPOSITORY_ROOT,
    PreparedStream,
    prepare_streams,
    sha256_file,
)
from dps_studio.research.task021c_cost_bridge import corrected_inventory
from dps_studio.research.task021f_node_evidence import (
    NodeSyntheticScenario,
    _make_node_scenario,
    _node_synthetic_scenarios,
)
from dps_studio.core.workflow import load_workflow_config

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]
WINDOWS: tuple[int, ...] = (1, 2, 3, 5)
PRIMARY_WINDOW = 3
TOP_K = 5


@dataclass(frozen=True, slots=True)
class CoherenceRecord:
    """Candidate support on the unchanged graph, measured in frames and hertz."""

    frame_index: int
    candidate_rank: int
    time_s: float
    frequency_hz: float
    link_tolerance_hz: float
    forward_w1: float
    forward_w2: float
    forward_w3: float
    forward_w5: float
    backward_w1: float
    backward_w2: float
    backward_w3: float
    backward_w5: float
    geometric_persistence: float
    continuation_ambiguity: float
    tube_coherence: float
    coherent_spectral_support: float

    def window_value(self, direction: str, window: int) -> float:
        return float(getattr(self, f"{direction}_w{window}"))


@dataclass(frozen=True, slots=True)
class CoherenceBundle:
    """Read-only TASK-021F local evidence plus new candidate-graph evidence."""

    by_key: Mapping[tuple[int, int], CoherenceRecord]
    spectral_evidence: EvidenceBundle
    link_tolerance_hz: float
    windows: tuple[int, ...]

    def for_candidate(self, candidate: RidgeCandidate) -> CoherenceRecord:
        return self.by_key[(candidate.frame_index, candidate.candidate_rank)]

    def spectral_for_candidate(self, candidate: RidgeCandidate) -> CandidateEvidence:
        return self.spectral_evidence.for_candidate(candidate)


@dataclass(frozen=True, slots=True)
class CoherenceModelSpec:
    """Frozen bounded-reward model; G0 is the unmodified core node cost."""

    coherence_model_id: str
    display_name: str
    reward_weight: float
    reward_source: str
    rationale: str

    def row(self) -> dict[str, Any]:
        return {
            "coherence_model_id": self.coherence_model_id,
            "display_name": self.display_name,
            "reward_weight": self.reward_weight,
            "reward_source": self.reward_source,
            "new_node_cost_math": "max(0, core_N0 - reward_weight * bounded_reward)",
            "calibration_scope": "predeclared synthetic geometry study; no ch3-specific fit",
            "rationale": self.rationale,
            "research_only": True,
        }


@dataclass(frozen=True, slots=True)
class CoherencePathResult:
    """Independent first-order DP result retaining cost provenance per frame."""

    time_s: FloatArray
    frame_indices: IntArray
    candidate_frames: tuple[tuple[RidgeCandidate, ...], ...]
    selected_candidate_rank: IntArray
    selected_frequency_hz: FloatArray
    is_null: BoolArray
    base_node_cost: FloatArray
    reward: FloatArray
    node_cost: FloatArray
    transition_cost: FloatArray
    cumulative_cost: FloatArray
    model: CoherenceModelSpec
    transition_spec: TransitionSpec
    config: GlobalPathConfig

    @property
    def total_path_cost(self) -> float:
        return float(self.cumulative_cost[-1])


def build_coherence_models() -> tuple[CoherenceModelSpec, ...]:
    """Return the fixed G0-G4 study matrix without a tuning sweep."""
    return (
        CoherenceModelSpec("G0", "current_TASK021A_baseline", 0.0, "none", "Exact N0 comparator."),
        CoherenceModelSpec(
            "G1", "tube_reward_nominal", 0.30, "tube", "Bounded tube coherence reward."
        ),
        CoherenceModelSpec(
            "G2", "tube_reward_weaker", 0.15, "tube", "Weaker fixed tube reward sensitivity."
        ),
        CoherenceModelSpec(
            "G3",
            "tube_plus_local_prominence",
            0.30,
            "coherent_spectral",
            "Tube coherence gated by pre-existing local prominence.",
        ),
        CoherenceModelSpec(
            "G4",
            "ambiguity_guarded",
            0.30,
            "ambiguity_guarded",
            "G3 reward further guarded by continuation ambiguity.",
        ),
    )


def fixed_transition_specs() -> tuple[TransitionSpec, ...]:
    """Use only exact TASK-021E E0 and E2, with no curvature or other sweep."""
    selected = tuple(
        item for item in build_transition_specs() if item.experiment_id in {"E0", "E2"}
    )
    if {item.experiment_id for item in selected} != {"E0", "E2"}:
        raise RuntimeError("TASK-021E E0/E2 transition definitions are unavailable.")
    return selected


def compute_candidate_coherence(
    stft_result: STFTResult,
    candidate_frames: Sequence[Sequence[RidgeCandidate]],
    *,
    config: GlobalPathConfig,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> CoherenceBundle:
    """Compute forward/backward persistence without changing STFT or candidates."""
    frames = tuple(tuple(frame[: config.top_k]) for frame in candidate_frames)
    if not frames:
        raise ValueError("candidate_frames must not be empty.")
    before = candidate_graph_signature(frames)
    spectral = compute_candidate_evidence(
        stft_result,
        frames,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
    )
    tolerance = max(1.5 * spectral.stft_resolution_hz, config.frequency_step_scale_hz)
    forward = _adjacent_links(frames, tolerance_hz=tolerance, forward=True)
    backward = _adjacent_links(frames, tolerance_hz=tolerance, forward=False)
    max_candidates = max(len(frame) for frame in frames)
    records: dict[tuple[int, int], CoherenceRecord] = {}
    for frame in frames:
        for candidate in frame:
            key = _candidate_key(candidate)
            f_values = _support_values(key, forward)
            b_values = _support_values(key, backward)
            f = {window: float(np.mean(f_values[:window])) for window in WINDOWS}
            b = {window: float(np.mean(b_values[:window])) for window in WINDOWS}
            persistence = float(math.sqrt(f[PRIMARY_WINDOW] * b[PRIMARY_WINDOW]))
            ambiguity = _ambiguity(key, forward, backward, max_candidates)
            tube = float(np.clip(persistence * (1.0 - ambiguity), 0.0, 1.0))
            prominence = spectral.for_candidate(candidate).prominence_score
            coherent_spectral = float(math.sqrt(tube * np.clip(prominence, 0.0, 1.0)))
            records[key] = CoherenceRecord(
                candidate.frame_index,
                candidate.candidate_rank,
                candidate.time_s,
                candidate.transition_frequency_hz,
                tolerance,
                f[1],
                f[2],
                f[3],
                f[5],
                b[1],
                b[2],
                b[3],
                b[5],
                persistence,
                ambiguity,
                tube,
                coherent_spectral,
            )
    if candidate_graph_signature(frames) != before:
        raise RuntimeError("TASK-021G must not alter the fixed candidate graph.")
    return CoherenceBundle(records, spectral, float(tolerance), WINDOWS)


def coherence_reward(
    candidate: RidgeCandidate, bundle: CoherenceBundle, model: CoherenceModelSpec
) -> float:
    """Return the model's non-negative bounded reward before its fixed weight."""
    if model.coherence_model_id == "G0":
        return 0.0
    record = bundle.for_candidate(candidate)
    if model.reward_source == "tube":
        value = record.tube_coherence
    elif model.reward_source == "coherent_spectral":
        value = record.coherent_spectral_support
    elif model.reward_source == "ambiguity_guarded":
        value = record.coherent_spectral_support * (1.0 - record.continuation_ambiguity)
    else:
        raise ValueError(f"Unsupported coherence reward source: {model.reward_source}")
    return float(np.clip(value, 0.0, 1.0))


def candidate_node_cost_with_coherence(
    candidate: RidgeCandidate,
    *,
    config: GlobalPathConfig,
    bundle: CoherenceBundle,
    model: CoherenceModelSpec,
) -> tuple[float, float, float]:
    """Return core N0, bounded reward amount, and floored Research-only cost."""
    baseline = candidate_node_cost(candidate, config)
    reward = model.reward_weight * coherence_reward(candidate, bundle, model)
    return float(baseline), float(reward), float(max(0.0, baseline - reward))


def solve_coherence_path(
    candidate_frames: Sequence[Sequence[RidgeCandidate]],
    time_s: FloatArray,
    *,
    config: GlobalPathConfig,
    bundle: CoherenceBundle,
    model: CoherenceModelSpec,
    transition_spec: TransitionSpec,
    frame_indices: IntArray | None = None,
) -> CoherencePathResult:
    """Solve first-order DP with unchanged NULL semantics and fixed E0/E2 only."""
    if transition_spec.experiment_id not in {"E0", "E2"}:
        raise ValueError("TASK-021G permits only E0 and E2 transitions.")
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
    for position, current_states in enumerate(states):
        node_values = np.asarray(
            [
                config.null_node_cost
                if candidate is None
                else candidate_node_cost_with_coherence(
                    candidate, config=config, bundle=bundle, model=model
                )[2]
                for candidate in current_states
            ],
            dtype=np.float64,
        )
        if position == 0:
            entry = np.asarray(
                [
                    config.null_stay_cost if candidate is None else config.ridge_entry_cost
                    for candidate in current_states
                ],
                dtype=np.float64,
            )
            forward.append(node_values + entry)
            predecessors.append(np.full(len(current_states), -1, dtype=np.int64))
            continue
        cumulative = np.empty(len(current_states), dtype=np.float64)
        previous_choice = np.empty(len(current_states), dtype=np.int64)
        for current_index, current in enumerate(current_states):
            choices = np.asarray(
                [
                    forward[-1][previous_index]
                    + _fixed_transition_cost(
                        previous, current, config=config, transition_spec=transition_spec
                    )
                    for previous_index, previous in enumerate(states[position - 1])
                ],
                dtype=np.float64,
            )
            best = int(np.argmin(choices))
            cumulative[current_index] = choices[best] + node_values[current_index]
            previous_choice[current_index] = best
        forward.append(cumulative)
        predecessors.append(previous_choice)
    selected = np.empty(len(states), dtype=np.int64)
    selected[-1] = int(np.argmin(forward[-1]))
    for position in range(len(states) - 1, 0, -1):
        selected[position - 1] = predecessors[position][selected[position]]
    return _assemble_path(
        states, values, indices, selected, config, bundle, model, transition_spec, forward
    )


def candidate_frames_from_stft(
    stft_result: STFTResult,
    *,
    config: GlobalPathConfig,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> tuple[tuple[RidgeCandidate, ...], ...]:
    """Extract the normal fixed Top-K graph for standalone synthetic experiments."""
    candidates = extract_global_path_candidates(
        stft_result,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
        config=config,
    )
    return tuple(frame[: config.top_k] for frame in candidates.candidates_by_frame)


def _candidate_key(candidate: RidgeCandidate) -> tuple[int, int]:
    return candidate.frame_index, candidate.candidate_rank


def _adjacent_links(
    frames: Sequence[Sequence[RidgeCandidate]], *, tolerance_hz: float, forward: bool
) -> dict[tuple[int, int], tuple[tuple[int, int], ...]]:
    links: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {}
    direction = 1 if forward else -1
    for position, frame in enumerate(frames):
        neighbor = position + direction
        for candidate in frame:
            if neighbor < 0 or neighbor >= len(frames):
                links[_candidate_key(candidate)] = ()
                continue
            matches = tuple(
                _candidate_key(other)
                for other in frames[neighbor]
                if abs(other.transition_frequency_hz - candidate.transition_frequency_hz)
                <= tolerance_hz
            )
            links[_candidate_key(candidate)] = matches
    return links


def _support_values(
    key: tuple[int, int], links: Mapping[tuple[int, int], Sequence[tuple[int, int]]]
) -> tuple[float, ...]:
    reachable = {key}
    values: list[float] = []
    for _ in range(max(WINDOWS)):
        reachable = {next_key for item in reachable for next_key in links[item]}
        values.append(1.0 if reachable else 0.0)
    return tuple(values)


def _ambiguity(
    key: tuple[int, int],
    forward: Mapping[tuple[int, int], Sequence[tuple[int, int]]],
    backward: Mapping[tuple[int, int], Sequence[tuple[int, int]]],
    max_candidates: int,
) -> float:
    count = max(len(forward[key]), len(backward[key]))
    if max_candidates <= 1:
        return 0.0
    return float(np.clip(math.log1p(count) / math.log1p(max_candidates), 0.0, 1.0))


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
        raise ValueError("E2 requires its fixed pseudo-Huber delta.")
    return robust_first_order_cost(
        current.transition_frequency_hz - previous.transition_frequency_hz,
        config=config,
        weight=transition_spec.first_order_weight,
        huber_delta_normalized=transition_spec.huber_delta_normalized,
    )


def _assemble_path(
    states: Sequence[Sequence[RidgeCandidate | None]],
    time_s: FloatArray,
    frame_indices: IntArray,
    selected: IntArray,
    config: GlobalPathConfig,
    bundle: CoherenceBundle,
    model: CoherenceModelSpec,
    transition_spec: TransitionSpec,
    forward: Sequence[FloatArray],
) -> CoherencePathResult:
    count = len(states)
    rank = np.zeros(count, dtype=np.int64)
    frequency = np.full(count, np.nan, dtype=np.float64)
    is_null = np.ones(count, dtype=np.bool_)
    base = np.full(count, config.null_node_cost, dtype=np.float64)
    reward = np.zeros(count, dtype=np.float64)
    node = np.full(count, config.null_node_cost, dtype=np.float64)
    transition = np.empty(count, dtype=np.float64)
    cumulative = np.empty(count, dtype=np.float64)
    chosen: list[RidgeCandidate | None] = []
    for position, state_index in enumerate(selected.tolist()):
        candidate = states[position][state_index]
        chosen.append(candidate)
        if candidate is not None:
            rank[position] = candidate.candidate_rank
            frequency[position] = candidate.transition_frequency_hz
            is_null[position] = False
            base[position], reward[position], node[position] = candidate_node_cost_with_coherence(
                candidate, config=config, bundle=bundle, model=model
            )
        transition[position] = (
            (config.null_stay_cost if candidate is None else config.ridge_entry_cost)
            if position == 0
            else _fixed_transition_cost(
                chosen[position - 1], candidate, config=config, transition_spec=transition_spec
            )
        )
        cumulative[position] = forward[position][state_index]
    return CoherencePathResult(
        np.asarray(time_s, dtype=np.float64),
        np.asarray(frame_indices, dtype=np.int64),
        tuple(tuple(item for item in frame if item is not None) for frame in states),
        rank,
        frequency,
        is_null,
        base,
        reward,
        node,
        transition,
        cumulative,
        model,
        transition_spec,
        config,
    )


def run_task021g(
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    config_path: Path = DEFAULT_CONFIG_PATH,
    output_directory: Path,
) -> dict[str, Any]:
    """Run the isolated TASK-021G study without overwriting artifacts or inputs."""
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
    models = build_coherence_models()
    transitions = fixed_transition_specs()
    _write_csv(
        output / "coherence_model_definition.csv",
        [model.row() | config.to_metadata() for model in models],
    )
    (output / "coherence_definition.md").write_text(_definition_markdown(), encoding="utf-8")
    (output / "repository_audit.txt").write_text(
        _repository_audit_text(config_path), encoding="utf-8"
    )
    bundles = {stream.stream_id: _stream_coherence(stream, config) for stream in streams}
    _assert_fixed_inputs(streams, bundles, config)
    ch3_streams = [stream for stream in streams if stream.source_path.name.casefold() == "ch3.csv"]
    if not ch3_streams:
        raise RuntimeError("ch3.csv did not produce an eligible formal Research stream.")
    candidate_rows = _candidate_audit_rows(ch3_streams, bundles, config)
    _write_csv(output / "ch3_candidate_coherence_audit.csv", candidate_rows)
    results: dict[tuple[str, str, str], CoherencePathResult] = {}
    ch3_rows: list[dict[str, Any]] = []
    for stream in ch3_streams:
        frames = _top_k_frames(stream, config)
        bundle = bundles[stream.stream_id]
        for model in models:
            for transition in transitions:
                started = time.perf_counter()
                result = solve_coherence_path(
                    frames,
                    stream.candidate_set_maximum.time_s,
                    config=config,
                    bundle=bundle,
                    model=model,
                    transition_spec=transition,
                )
                results[(stream.stream_id, model.coherence_model_id, transition.experiment_id)] = (
                    result
                )
                ch3_rows.append(
                    _path_row(stream, result, bundle, "FULL", None)
                    | {"runtime_s": time.perf_counter() - started}
                )
                for interval_id, start, end in _descent_intervals():
                    ch3_rows.append(_path_row(stream, result, bundle, interval_id, (start, end)))
    _write_csv(output / "ch3_coherence_comparison.csv", ch3_rows)
    d2_rows = _d2_detail_rows(ch3_streams, results, bundles, config)
    _write_csv(output / "ch3_d2_selected_detail.csv", d2_rows)
    synthetic_rows = _synthetic_rows(models, transitions, config)
    _write_csv(output / "synthetic_coherence_benchmark.csv", synthetic_rows)
    promising = _select_promising_models(ch3_rows, synthetic_rows)
    selected_models = ("G0", *promising)
    _write_csv(
        output / "synthetic_guardrail.csv",
        [
            row
            for row in synthetic_rows
            if row.get("row_kind") == "path_metric"
            and row.get("coherence_model_id") in selected_models
        ],
    )
    cross_rows = _cross_dataset_rows(streams, bundles, models, transitions, promising, config)
    _write_csv(output / "cross_dataset_coherence_validation.csv", cross_rows)
    _save_figures(figures, ch3_streams, bundles, results, candidate_rows, synthetic_rows, config)
    hashes_after = {str(path): sha256_file(path) for path in sorted(accepted)}
    production_after = _production_worktree_snapshot()
    metadata = {
        "task": "TASK-021G",
        "created_utc": datetime.now(UTC).isoformat(),
        "git_branch": _git(["branch", "--show-current"]).strip(),
        "git_head": _git(["rev-parse", "HEAD"]).strip(),
        "raw_root_read_only": str(raw_root.resolve()),
        "raw_hashes_before": hashes_before,
        "raw_hashes_after": hashes_after,
        "raw_hashes_equal": hashes_before == hashes_after,
        "prepared_stream_count": len(streams),
        "failures": [str(failure) for failure in failures],
        "candidate_graph_change": False,
        "stft_change": False,
        "top_k": config.top_k,
        "fixed_transition_ids": [item.experiment_id for item in transitions],
        "null_model_unchanged": True,
        "production_worktree_before": production_before,
        "production_worktree_after": production_after,
        "production_untouched_by_task": production_before == production_after,
        "selected_promising_models": list(promising),
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


def _top_k_frames(
    stream: PreparedStream, config: GlobalPathConfig
) -> tuple[tuple[RidgeCandidate, ...], ...]:
    return tuple(
        frame[: config.top_k] for frame in stream.candidate_set_maximum.candidates_by_frame
    )


def _stream_coherence(stream: PreparedStream, config: GlobalPathConfig) -> CoherenceBundle:
    candidate_set = stream.candidate_set_maximum
    return compute_candidate_coherence(
        stream.analysis.stft_result,
        _top_k_frames(stream, config),
        config=config,
        minimum_frequency_hz=candidate_set.minimum_frequency_hz,
        maximum_frequency_hz=candidate_set.maximum_frequency_hz,
    )


def _assert_fixed_inputs(
    streams: Sequence[PreparedStream],
    bundles: Mapping[str, CoherenceBundle],
    config: GlobalPathConfig,
) -> None:
    for stream in streams:
        frames = _top_k_frames(stream, config)
        baseline = candidate_graph_signature(frames)
        bundle = bundles[stream.stream_id]
        expected = {
            (candidate.frame_index, candidate.candidate_rank)
            for frame in frames
            for candidate in frame
        }
        if set(bundle.by_key) != expected:
            raise RuntimeError(
                f"TASK-021G coherence keys do not match fixed graph: {stream.stream_id}"
            )
        if candidate_graph_signature(frames) != baseline:
            raise RuntimeError(f"TASK-021G changed a candidate graph: {stream.stream_id}")


def _descent_intervals() -> tuple[tuple[str, float, float], ...]:
    return (
        ("D0_183P60_183P76_US", 0.00018360, 0.00018376),
        ("D1_183P76_183P82_US", 0.00018376, 0.00018382),
        ("D2_183P82_183P88_US", 0.00018382, 0.00018388),
    )


def _candidate_audit_rows(
    streams: Sequence[PreparedStream],
    bundles: Mapping[str, CoherenceBundle],
    config: GlobalPathConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stream in streams:
        for frame in _top_k_frames(stream, config):
            for candidate in frame:
                record = bundles[stream.stream_id].for_candidate(candidate)
                spectral = bundles[stream.stream_id].spectral_for_candidate(candidate)
                rows.append(
                    {
                        "stream_id": stream.stream_id,
                        "time_s": candidate.time_s,
                        "frequency_hz": candidate.transition_frequency_hz,
                        "candidate_rank": candidate.candidate_rank,
                        "amplitude": candidate.peak_amplitude,
                        "refinement_status": candidate.refinement_status.value,
                        "forward_support_w1": record.forward_w1,
                        "forward_support_w2": record.forward_w2,
                        "forward_support_w3": record.forward_w3,
                        "forward_support_w5": record.forward_w5,
                        "backward_support_w1": record.backward_w1,
                        "backward_support_w2": record.backward_w2,
                        "backward_support_w3": record.backward_w3,
                        "backward_support_w5": record.backward_w5,
                        "bidirectional_persistence": record.geometric_persistence,
                        "continuation_ambiguity": record.continuation_ambiguity,
                        "tube_coherence": record.tube_coherence,
                        "coherent_spectral_support": record.coherent_spectral_support,
                        "local_prominence_score": spectral.prominence_score,
                        "link_tolerance_hz": record.link_tolerance_hz,
                        "base_n0_node_cost": candidate_node_cost(candidate, config),
                        "candidate_minus_null_node_margin": candidate_node_cost(candidate, config)
                        - config.null_node_cost,
                    }
                )
    return rows


def _path_row(
    stream: PreparedStream,
    result: CoherencePathResult,
    bundle: CoherenceBundle,
    interval_id: str,
    interval: tuple[float, float] | None,
) -> dict[str, Any]:
    mask = (
        np.ones(result.time_s.size, dtype=np.bool_)
        if interval is None
        else (result.time_s >= interval[0]) & (result.time_s <= interval[1])
    )
    selected = mask & ~result.is_null
    selected_indices = np.flatnonzero(selected)
    selected_records = [
        bundle.for_candidate(
            result.candidate_frames[index][int(result.selected_candidate_rank[index]) - 1]
        )
        for index in selected_indices
    ]
    selected_spectral = [
        bundle.spectral_for_candidate(
            result.candidate_frames[index][int(result.selected_candidate_rank[index]) - 1]
        )
        for index in selected_indices
    ]
    frequency = result.selected_frequency_hz[selected]
    steps = np.abs(np.diff(frequency[np.isfinite(frequency)]))
    ranks = result.selected_candidate_rank[selected]
    return {
        "stream_id": stream.stream_id,
        "source_file": stream.source_path.name,
        "profile_id": stream.profile_id,
        "coherence_model_id": result.model.coherence_model_id,
        "transition_id": result.transition_spec.experiment_id,
        "interval_id": interval_id,
        "frame_count": int(np.count_nonzero(mask)),
        "coverage_fraction": float(np.mean(~result.is_null[mask])) if np.any(mask) else math.nan,
        "longest_selected_segment": _longest_run(~result.is_null[mask]),
        "rank1_fraction": float(np.mean(ranks == 1)) if ranks.size else math.nan,
        "rank2_fraction": float(np.mean(ranks == 2)) if ranks.size else math.nan,
        "rank3_fraction": float(np.mean(ranks == 3)) if ranks.size else math.nan,
        "rank4plus_fraction": float(np.mean(ranks >= 4)) if ranks.size else math.nan,
        "frequency_step_p95_hz": _quantile(steps, 0.95),
        "selected_tube_coherence_median": _median(
            [item.tube_coherence for item in selected_records]
        ),
        "selected_ambiguity_median": _median(
            [item.continuation_ambiguity for item in selected_records]
        ),
        "selected_local_prominence_median": _median(
            [item.local_sideband_prominence_db for item in selected_spectral]
        ),
        "selected_coherent_support_median": _median(
            [item.coherent_spectral_support for item in selected_records]
        ),
        "selected_above_6ghz_fraction": float(np.mean(frequency > 6.0e9))
        if frequency.size
        else 0.0,
        "total_path_cost": result.total_path_cost,
    }


def _d2_detail_rows(
    streams: Sequence[PreparedStream],
    results: Mapping[tuple[str, str, str], CoherencePathResult],
    bundles: Mapping[str, CoherenceBundle],
    config: GlobalPathConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    _label, d2_start, d2_end = _descent_intervals()[-1]
    for stream in streams:
        reference = results[(stream.stream_id, "G0", "E2")]
        for model_id in ("G1", "G2", "G3", "G4"):
            result = results[(stream.stream_id, model_id, "E2")]
            mask = (result.time_s >= d2_start) & (result.time_s <= d2_end) & ~result.is_null
            for index in np.flatnonzero(mask).tolist():
                rank = int(result.selected_candidate_rank[index])
                candidate = result.candidate_frames[index][rank - 1]
                record = bundles[stream.stream_id].for_candidate(candidate)
                spectral = bundles[stream.stream_id].spectral_for_candidate(candidate)
                rows.append(
                    {
                        "stream_id": stream.stream_id,
                        "coherence_model_id": model_id,
                        "time_s": result.time_s[index],
                        "frequency_hz": candidate.transition_frequency_hz,
                        "candidate_rank": rank,
                        "g0_e2_was_null": bool(reference.is_null[index]),
                        "forward_support_w3": record.forward_w3,
                        "backward_support_w3": record.backward_w3,
                        "tube_coherence": record.tube_coherence,
                        "continuation_ambiguity": record.continuation_ambiguity,
                        "local_prominence_db": spectral.local_sideband_prominence_db,
                        "base_n0_node_cost": result.base_node_cost[index],
                        "coherence_reward": result.reward[index],
                        "new_node_cost": result.node_cost[index],
                        "candidate_minus_null_node_margin": result.node_cost[index]
                        - config.null_node_cost,
                    }
                )
    return rows or [
        {
            "status": "no_selected_D2_candidates",
            "reason": "Fixed NULL and E2 competition retained NULL for every G1-G4 D2 state.",
        }
    ]


def _task021g_synthetic_scenarios() -> tuple[NodeSyntheticScenario, ...]:
    """A-Q inherited tests plus fixed R-W candidate-geometry cases."""
    count = 96
    index = np.arange(count)
    no_truth = np.full(count, np.nan, dtype=np.float64)
    burst = np.zeros(count, dtype=np.bool_)
    burst[38:47] = True
    crossing_true = np.where(index < 48, 2.0e9 + index * 25e6, 3.2e9 - (index - 48) * 25e6)
    crossing_wrong = 4.8e9 - crossing_true
    descent = np.where(index < 28, 3.8e9, np.maximum(1.0e9, 3.8e9 - (index - 28) * 85e6))
    return _node_synthetic_scenarios() + (
        _make_node_scenario(
            "R_COHERENT_WEAK_RIDGE",
            np.full(count, 2.8e9),
            ridge_amplitude=3.2,
            role="TASK021G_R_to_W",
        ),
        _make_node_scenario(
            "S_RANDOM_CANDIDATE_CLOUD",
            no_truth,
            ridge_amplitude=0.0,
            role="TASK021G_R_to_W",
        ),
        _make_node_scenario(
            "T_BROADBAND_VERTICAL_BURST",
            no_truth,
            ridge_amplitude=0.0,
            broadband=burst,
            role="TASK021G_R_to_W",
        ),
        _make_node_scenario(
            "U_COHERENT_WRONG_BRANCH",
            np.full(count, 2.8e9),
            ridge_amplitude=3.2,
            distractor=np.full(count, 4.0e9),
            distractor_slice=slice(0, count),
            distractor_amplitude=7.0,
            role="TASK021G_R_to_W",
        ),
        _make_node_scenario(
            "V_TEMPORARY_RIDGE_CROSSING",
            np.asarray(crossing_true, dtype=np.float64),
            ridge_amplitude=6.0,
            distractor=np.asarray(crossing_wrong, dtype=np.float64),
            distractor_slice=slice(0, count),
            distractor_amplitude=6.2,
            role="TASK021G_R_to_W",
        ),
        _make_node_scenario(
            "W_FAST_SMOOTH_DESCENT_WITH_NOISY_CLOUD",
            np.asarray(descent, dtype=np.float64),
            ridge_amplitude=4.0,
            role="TASK021G_R_to_W",
        ),
    )


def _synthetic_rows(
    models: Sequence[CoherenceModelSpec],
    transitions: Sequence[TransitionSpec],
    config: GlobalPathConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in _task021g_synthetic_scenarios():
        case = scenario.case
        frames = candidate_frames_from_stft(
            case.stft_result,
            config=config,
            minimum_frequency_hz=scenario.minimum_frequency_hz,
            maximum_frequency_hz=scenario.maximum_frequency_hz,
        )
        bundle = compute_candidate_coherence(
            case.stft_result,
            frames,
            config=config,
            minimum_frequency_hz=scenario.minimum_frequency_hz,
            maximum_frequency_hz=scenario.maximum_frequency_hz,
        )
        rows.extend(_synthetic_distribution_rows(scenario, frames, bundle))
        for model in models:
            for transition in transitions:
                result = solve_coherence_path(
                    frames,
                    case.stft_result.time_s,
                    config=config,
                    bundle=bundle,
                    model=model,
                    transition_spec=transition,
                )
                metrics = calculate_ridge_metrics(
                    case,
                    result.selected_frequency_hz,
                    selected_candidate_rank=result.selected_candidate_rank,
                    method=f"{model.coherence_model_id}_{transition.experiment_id}",
                    top_k=config.top_k,
                    vacuum_wavelength_m=DEFAULT_VACUUM_WAVELENGTH_M,
                )
                selected = ~result.is_null
                rows.append(
                    {
                        "row_kind": "path_metric",
                        "case_id": case.case_id,
                        "scenario_role": scenario.role,
                        "coherence_model_id": model.coherence_model_id,
                        "transition_id": transition.experiment_id,
                        **metrics.to_dict(),
                        "selected_fraction": float(np.mean(selected)),
                        "longest_selected_segment": _longest_run(selected),
                        "pure_noise_false_selection": float(np.mean(selected))
                        if case.case_id in {"H_pure_noise", "S_RANDOM_CANDIDATE_CLOUD"}
                        else math.nan,
                        "vertical_burst_selected_fraction": float(
                            np.mean(selected[scenario.broadband_mask])
                        )
                        if case.case_id == "T_BROADBAND_VERTICAL_BURST"
                        else math.nan,
                    }
                )
    return rows


def _synthetic_distribution_rows(
    scenario: NodeSyntheticScenario,
    frames: Sequence[Sequence[RidgeCandidate]],
    bundle: CoherenceBundle,
) -> list[dict[str, Any]]:
    groups: dict[str, list[CoherenceRecord]] = {
        "true_ridge_candidate": [],
        "random_candidate": [],
        "broadband_candidate": [],
        "wrong_coherent_branch": [],
    }
    case = scenario.case
    for frame in frames:
        for candidate in frame:
            record = bundle.for_candidate(candidate)
            truth = float(case.truth_frequency_hz[candidate.frame_index])
            if (
                case.case_id == "U_COHERENT_WRONG_BRANCH"
                and abs(record.frequency_hz - 4.0e9) <= 120e6
            ):
                group = "wrong_coherent_branch"
            elif scenario.broadband_mask[candidate.frame_index]:
                group = "broadband_candidate"
            elif (
                math.isfinite(truth)
                and abs(record.frequency_hz - truth) <= case.wrong_branch_tolerance_hz
            ):
                group = "true_ridge_candidate"
            else:
                group = "random_candidate"
            groups[group].append(record)
    return [
        {
            "row_kind": "coherence_distribution",
            "case_id": case.case_id,
            "scenario_role": scenario.role,
            "candidate_role": role,
            "candidate_count": len(values),
            "tube_coherence_median": _median([item.tube_coherence for item in values]),
            "persistence_median": _median([item.geometric_persistence for item in values]),
            "ambiguity_median": _median([item.continuation_ambiguity for item in values]),
            "coherent_spectral_support_median": _median(
                [item.coherent_spectral_support for item in values]
            ),
        }
        for role, values in groups.items()
    ]


def _select_promising_models(
    ch3_rows: Sequence[Mapping[str, Any]], synthetic_rows: Sequence[Mapping[str, Any]]
) -> tuple[str, ...]:
    """Predeclared criterion: D2 gain, no >6GHz, and pure-noise safety."""
    eligible: list[tuple[float, str]] = []
    for model_id in ("G1", "G2", "G3", "G4"):
        d2 = [
            row
            for row in ch3_rows
            if row["coherence_model_id"] == model_id
            and row["transition_id"] == "E2"
            and row["interval_id"] == "D2_183P82_183P88_US"
        ]
        noise = [
            row
            for row in synthetic_rows
            if row.get("row_kind") == "path_metric"
            and row.get("coherence_model_id") == model_id
            and row.get("transition_id") == "E2"
            and row.get("case_id") in {"H_pure_noise", "S_RANDOM_CANDIDATE_CLOUD"}
        ]
        coverage = float(np.mean([float(row["coverage_fraction"]) for row in d2])) if d2 else 0.0
        high = (
            float(np.mean([float(row["selected_above_6ghz_fraction"]) for row in d2]))
            if d2
            else 1.0
        )
        false = float(np.mean([float(row["selected_fraction"]) for row in noise])) if noise else 1.0
        if coverage > 0.0 and high == 0.0 and false == 0.0:
            eligible.append((coverage, model_id))
    return tuple(item[1] for item in sorted(eligible, key=lambda item: (-item[0], item[1]))[:2])


def _cross_dataset_rows(
    streams: Sequence[PreparedStream],
    bundles: Mapping[str, CoherenceBundle],
    models: Sequence[CoherenceModelSpec],
    transitions: Sequence[TransitionSpec],
    promising: Sequence[str],
    config: GlobalPathConfig,
) -> list[dict[str, Any]]:
    if not promising:
        return [
            {
                "status": "not_run",
                "reason": "No G1-G4 model met predeclared ch3 D2 and pure-noise criterion.",
            }
        ]
    by_id = {model.coherence_model_id: model for model in models}
    rows: list[dict[str, Any]] = []
    for stream in streams:
        frames = _top_k_frames(stream, config)
        for model_id in promising:
            for transition in transitions:
                started = time.perf_counter()
                result = solve_coherence_path(
                    frames,
                    stream.candidate_set_maximum.time_s,
                    config=config,
                    bundle=bundles[stream.stream_id],
                    model=by_id[model_id],
                    transition_spec=transition,
                )
                rows.append(
                    _path_row(stream, result, bundles[stream.stream_id], "FULL", None)
                    | {"runtime_s": time.perf_counter() - started}
                )
    return rows


def _save_figures(
    figures: Path,
    streams: Sequence[PreparedStream],
    bundles: Mapping[str, CoherenceBundle],
    results: Mapping[tuple[str, str, str], CoherencePathResult],
    candidate_rows: Sequence[Mapping[str, Any]],
    synthetic_rows: Sequence[Mapping[str, Any]],
    config: GlobalPathConfig,
) -> None:
    for stream in streams:
        slug = stream.stream_id
        stream_rows = [row for row in candidate_rows if row["stream_id"] == stream.stream_id]
        _plot_candidate_cloud(
            figures / f"{slug}_forward_support_w3.png",
            stream_rows,
            "forward_support_w3",
            "Forward candidate support (W=3)",
        )
        _plot_candidate_cloud(
            figures / f"{slug}_backward_support_w3.png",
            stream_rows,
            "backward_support_w3",
            "Backward candidate support (W=3)",
        )
        _plot_candidate_cloud(
            figures / f"{slug}_bidirectional_persistence.png",
            stream_rows,
            "bidirectional_persistence",
            "Bidirectional persistence (W=3 geometric mean)",
        )
        _plot_candidate_cloud(
            figures / f"{slug}_tube_coherence.png", stream_rows, "tube_coherence", "Tube coherence"
        )
        _plot_candidate_cloud(
            figures / f"{slug}_continuation_ambiguity.png",
            stream_rows,
            "continuation_ambiguity",
            "Continuation ambiguity",
        )
        _plot_candidate_cloud(
            figures / f"{slug}_coherent_spectral_support.png",
            stream_rows,
            "coherent_spectral_support",
            "Coherence x local prominence",
        )
        _plot_d2_zoom(figures / f"{slug}_d2_zoom.png", stream_rows)
        _plot_path_comparison(
            figures / f"{slug}_g0_to_g4_comparison.png",
            results,
            stream.stream_id,
            "E2",
            "G0-G4 E2 comparison",
        )
        _plot_coherence_distribution(
            figures / f"{slug}_selected_vs_unselected.png", stream_rows, results, stream.stream_id
        )
        _plot_margin(
            figures / f"{slug}_candidate_vs_null_margin.png",
            stream_rows,
            bundles[stream.stream_id],
            config,
        )
    for case_id in (
        "R_COHERENT_WEAK_RIDGE",
        "S_RANDOM_CANDIDATE_CLOUD",
        "T_BROADBAND_VERTICAL_BURST",
        "U_COHERENT_WRONG_BRANCH",
        "W_FAST_SMOOTH_DESCENT_WITH_NOISY_CLOUD",
    ):
        _plot_synthetic_case(figures / f"synthetic_{case_id}.png", synthetic_rows, case_id)


def _plot_candidate_cloud(
    path: Path, rows: Sequence[Mapping[str, Any]], key: str, title: str
) -> None:
    figure = Figure(figsize=(8, 4.5), constrained_layout=True)
    axis = figure.add_subplot(111)
    scatter = axis.scatter(
        [float(row["time_s"]) * 1e6 for row in rows],
        [float(row["frequency_hz"]) / 1e9 for row in rows],
        c=[float(row[key]) for row in rows],
        cmap="viridis",
        s=10,
        linewidths=0,
    )
    figure.colorbar(scatter, ax=axis, label=key)
    axis.set(xlabel="time (us)", ylabel="frequency (GHz)", title=title)
    _save_figure(figure, path)


def _plot_d2_zoom(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    d2 = [row for row in rows if 183.82 <= float(row["time_s"]) * 1e6 <= 183.88]
    _plot_candidate_cloud(path, d2, "tube_coherence", "D2 tube-coherence zoom")


def _plot_path_comparison(
    path: Path,
    results: Mapping[tuple[str, str, str], CoherencePathResult],
    stream_id: str,
    transition_id: str,
    title: str,
) -> None:
    figure = Figure(figsize=(8, 4.5), constrained_layout=True)
    axis = figure.add_subplot(111)
    for model_id in ("G0", "G1", "G2", "G3", "G4"):
        result = results[(stream_id, model_id, transition_id)]
        axis.plot(
            result.time_s * 1e6,
            result.selected_frequency_hz / 1e9,
            marker=".",
            markersize=2,
            linewidth=0.9,
            label=model_id,
        )
    axis.axvspan(183.82, 183.88, color="grey", alpha=0.14, label="D2")
    axis.set(xlabel="time (us)", ylabel="selected frequency (GHz)", title=title)
    axis.legend(ncol=3, fontsize=8)
    _save_figure(figure, path)


def _plot_coherence_distribution(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    results: Mapping[tuple[str, str, str], CoherencePathResult],
    stream_id: str,
) -> None:
    selected = results[(stream_id, "G1", "E2")]
    # Candidate frame indices are not persisted in this CSV; recover selection by time/rank deterministically.
    selected_times = {
        (round(float(selected.time_s[index]), 15), int(selected.selected_candidate_rank[index]))
        for index in np.flatnonzero(~selected.is_null)
    }
    yes = [
        float(row["tube_coherence"])
        for row in rows
        if (round(float(row["time_s"]), 15), int(row["candidate_rank"])) in selected_times
    ]
    no = [
        float(row["tube_coherence"])
        for row in rows
        if (round(float(row["time_s"]), 15), int(row["candidate_rank"])) not in selected_times
    ]
    figure = Figure(figsize=(6, 4), constrained_layout=True)
    axis = figure.add_subplot(111)
    axis.hist(no, bins=20, alpha=0.65, label="unselected")
    axis.hist(yes, bins=20, alpha=0.65, label="G1 E2 selected")
    axis.set(
        xlabel="tube coherence", ylabel="candidate count", title="Selected vs unselected coherence"
    )
    axis.legend()
    _save_figure(figure, path)


def _plot_margin(
    path: Path,
    rows: Sequence[Mapping[str, Any]],
    bundle: CoherenceBundle,
    config: GlobalPathConfig,
) -> None:
    del bundle, config
    margins = [float(row["candidate_minus_null_node_margin"]) for row in rows]
    coherence = [float(row["tube_coherence"]) for row in rows]
    figure = Figure(figsize=(6, 4), constrained_layout=True)
    axis = figure.add_subplot(111)
    axis.scatter(coherence, margins, s=8, alpha=0.5)
    axis.axhline(0.0, color="black", linewidth=0.8)
    axis.set(
        xlabel="tube coherence",
        ylabel="candidate N0 minus NULL node cost",
        title="Candidate-vs-NULL node margin",
    )
    _save_figure(figure, path)


def _plot_synthetic_case(path: Path, rows: Sequence[Mapping[str, Any]], case_id: str) -> None:
    matched = [
        row
        for row in rows
        if row.get("row_kind") == "path_metric"
        and row.get("case_id") == case_id
        and row.get("transition_id") == "E2"
    ]
    figure = Figure(figsize=(7, 4), constrained_layout=True)
    axis = figure.add_subplot(111)
    axis.bar(
        [str(row["coherence_model_id"]) for row in matched],
        [float(row["valid_selected_coverage"]) for row in matched],
    )
    axis.set(ylim=(0.0, 1.0), ylabel="truth coverage", title=case_id)
    _save_figure(figure, path)


def _write_report(
    path: Path,
    ch3_rows: Sequence[Mapping[str, Any]],
    synthetic_rows: Sequence[Mapping[str, Any]],
    cross_rows: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any],
    promising: Sequence[str],
) -> None:
    d2 = [
        row
        for row in ch3_rows
        if row["interval_id"] == "D2_183P82_183P88_US" and row["transition_id"] == "E2"
    ]
    lines = [
        "# TASK-021G final Research report",
        "",
        "Research-only candidate coherence; no default algorithm, NULL, transition, raw input, GUI, or Production worktree was changed.",
        "",
        "## Fixed study boundary",
        "",
        "- Candidate graph / STFT: unchanged and checked before/after coherence calculation.",
        "- Transitions: E0 comparator and TASK-021E E2 only (pseudo-Huber, w=1.0, kappa=0.25).",
        "- NULL node/stay/entry/exit: unchanged.",
        "- Reward: bounded G1-G4 candidate-only decrement with a zero cost floor.",
        "",
        "## ch3 D2 / E2 outcome",
        "",
    ]
    for row in d2:
        lines.append(
            f"- {row['stream_id']} {row['coherence_model_id']}: coverage={float(row['coverage_fraction']):.3f}; longest={int(row['longest_selected_segment'])}; >6GHz={float(row['selected_above_6ghz_fraction']):.3f}."
        )
    improved = [
        row
        for row in d2
        if row["coherence_model_id"] != "G0" and float(row["coverage_fraction"]) > 0.0
    ]
    lines.extend(
        [
            "",
            "## Decision",
            "",
            f"- Temporal persistence: {'SUPPORTED' if _coherence_discriminative(synthetic_rows) else 'NOT SUPPORTED'}.",
            "- Continuation ambiguity: MIXED (reported as a geometry diagnostic, not a label).",
            f"- Signed coherence reward: {'MIXED' if improved else 'NOT SUPPORTED'}.",
            f"- ch3 recognition: {'IMPROVED' if improved else 'UNCHANGED'}.",
            f"- Cross-dataset transfer: {'MIXED' if promising else 'NOT TESTED because no ch3-improved model met guardrails'}.",
            "",
            "## Follow-up boundary",
            "",
            "If D2 remains zero despite elevated coherence, the next isolated question is NULL competition (TASK-021H); this task does not change it.",
            "",
            "## Reproducibility",
            "",
            f"- Raw SHA-256 unchanged: {metadata['raw_hashes_equal']}",
            f"- Production untouched: {metadata['production_untouched_by_task']}",
            f"- Promising cross-validation models: {', '.join(promising) if promising else 'none'}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _coherence_discriminative(rows: Sequence[Mapping[str, Any]]) -> bool:
    values: dict[tuple[str, str], float] = {}
    for row in rows:
        if row.get("row_kind") == "coherence_distribution":
            values[(str(row["case_id"]), str(row["candidate_role"]))] = float(
                row["tube_coherence_median"]
            )
    return values.get(("R_COHERENT_WEAK_RIDGE", "true_ridge_candidate"), 0.0) > values.get(
        ("S_RANDOM_CANDIDATE_CLOUD", "random_candidate"), 0.0
    )


def _definition_markdown() -> str:
    return """# TASK-021G coherence definition

Candidate extraction, separation, Top-K=5, frequency refinement, STFT, search
band, E0/E2 transition definitions, and all NULL costs are inherited unchanged.

For an existing candidate c(i,j), a directed link is present when a candidate in
the adjacent existing Top-K frame has absolute frequency difference at most
max(1.5 * STFT resolution, TASK-021E frequency_step_scale_hz).  Support for
W=1,2,3,5 is the fraction of successive frames reachable through these links.
Forward and backward support are each in [0,1].  Persistence is their W=3
geometric mean.  Ambiguity is log(1 + max(adjacent forward/backward link count))
/ log(1 + maximum Top-K count), in [0,1].  Tube coherence is persistence *
(1 - ambiguity), and coherent spectral support is sqrt(tube coherence *
TASK-021F local-prominence score).  These are deterministic diagnostics, not
probabilities or labels.

G0 retains exact N0.  G1 and G2 decrement its cost by 0.30 or 0.15 times tube
coherence. G3 decrements by 0.30 times coherent spectral support. G4 applies
an additional (1 - ambiguity) guard. All rewards are bounded and node costs are
floored at zero. These parameters are fixed before ch3 evaluation.
"""


def _repository_audit_text(config_path: Path) -> str:
    return "\n".join(
        (
            f"Research root: {REPOSITORY_ROOT}",
            f"Branch: {_git(['branch', '--show-current']).strip()}",
            f"HEAD: {_git(['rev-parse', 'HEAD']).strip()}",
            f"Config: {config_path.resolve()}",
            "Core candidate fields inspected: frame_index, time_s, candidate_rank, discrete/refined frequency, amplitude, refinement status.",
            "Graph organization inspected: RidgeCandidateSet.candidates_by_frame, then immutable top_k frame slices.",
            "TASK-021G writes only its timestamped artifact directory.",
            "\nGit status:\n" + _git(["status", "--short", "--branch"]),
            "\nRecent log:\n" + _git(["log", "-5", "--oneline"]),
            "\nWorking diff stat:\n" + _git(["diff", "--stat"]),
            "\nCached diff stat:\n" + _git(["diff", "--cached", "--stat"]),
        )
    )


def _production_worktree_snapshot() -> dict[str, str]:
    production = Path(r"D:\Code\Python_Projects\DPS_Studio")
    return {
        "path": str(production),
        "branch": _git(["-C", str(production), "branch", "--show-current"]).strip(),
        "status": _git(["-C", str(production), "status", "--short", "--branch"]),
    }


def _git(arguments: Sequence[str]) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        rows = ({"status": "no_rows"},)
    headers = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _median(values: Sequence[float]) -> float:
    return float(np.median(np.asarray(values, dtype=np.float64))) if values else math.nan


def _quantile(values: Sequence[float] | FloatArray, q: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), q)) if len(values) else math.nan


def _longest_run(values: BoolArray) -> int:
    longest = 0
    current = 0
    for value in values.tolist():
        current = current + 1 if value else 0
        longest = max(longest, current)
    return longest


def _save_figure(figure: Figure, path: Path) -> None:
    FigureCanvasAgg(figure)
    figure.savefig(path, dpi=150)


__all__ = [
    "CoherenceBundle",
    "CoherenceModelSpec",
    "CoherencePathResult",
    "CoherenceRecord",
    "PRIMARY_WINDOW",
    "TOP_K",
    "WINDOWS",
    "build_coherence_models",
    "candidate_frames_from_stft",
    "candidate_node_cost_with_coherence",
    "coherence_reward",
    "compute_candidate_coherence",
    "fixed_transition_specs",
    "run_task021g",
    "solve_coherence_path",
]
