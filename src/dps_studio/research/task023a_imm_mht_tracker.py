"""Coverage-first IMM / multi-hypothesis ridge tracking (Research only).

The tracker consumes an already extracted :class:`RidgeCandidateSet`.  It does
not call or alter STFT, search-band, candidate-separation, Top-K, or refinement
code.  Trajectory values and quality judgements are deliberately independent:
every frame receives a finite frequency, while flags describe doubtful frames.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.ridge import (
    GlobalPathConfig,
    RidgeCandidate,
    RidgeCandidateSet,
    candidate_node_cost,
)
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.core.time_frequency import STFTResult

FloatArray = NDArray[np.float64]
IntArray = NDArray[np.int64]
BoolArray = NDArray[np.bool_]


class MotionMode(str, Enum):
    """The three declared kinematic regimes in the IMM."""

    STABLE = "STABLE"
    CONSTANT_RATE = "CONSTANT_RATE"
    AGILE = "AGILE"


class QualityFlag(str, Enum):
    """Non-destructive per-frame quality annotations."""

    CANDIDATE_UPDATE = "CANDIDATE_UPDATE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    PREDICTED_GAP = "PREDICTED_GAP"
    STRONGEST_BIN_FALLBACK = "STRONGEST_BIN_FALLBACK"
    LARGE_INNOVATION = "LARGE_INNOVATION"
    POSSIBLE_BRANCH_SWITCH = "POSSIBLE_BRANCH_SWITCH"
    BROADBAND_ELEVATED = "BROADBAND_ELEVATED"
    REFINEMENT_FAILED = "REFINEMENT_FAILED"


@dataclass(frozen=True, slots=True)
class TrackerConfig:
    """Fixed Research-only physical parameters, not fitted to ch3."""

    measurement_std_hz: float = 100.0e6
    initial_frequency_std_hz: float = 120.0e6
    initial_rate_std_hz_per_s: float = 8.0e16
    acceleration_std_hz_per_s2: tuple[float, float, float] = (
        3.0e22,
        8.0e23,
        3.0e25,
    )
    mode_transition_matrix: tuple[tuple[float, float, float], ...] = (
        (0.94, 0.05, 0.01),
        (0.04, 0.92, 0.04),
        (0.02, 0.10, 0.88),
    )
    initial_mode_probability: tuple[float, float, float] = (0.60, 0.30, 0.10)
    rank_log_penalty: float = 0.50
    node_cost_penalty: float = 0.04
    low_confidence_threshold: float = 0.20
    minimum_confident_background_db: float = 15.0
    minimum_confident_competitor_db: float = 6.0
    large_innovation_sigma: float = 3.0
    branch_switch_step_hz: float = 450.0e6
    broadband_robust_z_threshold: float = 3.0
    orientation_time_half_width_s: float = 15.0e-9
    orientation_frequency_half_width_hz: float = 250.0e6

    def __post_init__(self) -> None:
        positive = (
            self.measurement_std_hz,
            self.initial_frequency_std_hz,
            self.initial_rate_std_hz_per_s,
            *self.acceleration_std_hz_per_s2,
            self.large_innovation_sigma,
            self.branch_switch_step_hz,
            self.orientation_time_half_width_s,
            self.orientation_frequency_half_width_hz,
        )
        if any(not math.isfinite(value) or value <= 0.0 for value in positive):
            raise ValueError("Tracker physical scales must be finite and positive.")
        transition = np.asarray(self.mode_transition_matrix, dtype=np.float64)
        probability = np.asarray(self.initial_mode_probability, dtype=np.float64)
        if transition.shape != (3, 3) or probability.shape != (3,):
            raise ValueError("IMM requires a 3x3 transition matrix and 3 probabilities.")
        if np.any(transition < 0.0) or not np.allclose(np.sum(transition, axis=1), 1.0):
            raise ValueError("Every IMM transition row must be a probability vector.")
        if np.any(probability < 0.0) or not math.isclose(float(np.sum(probability)), 1.0):
            raise ValueError("Initial mode probabilities must sum to one.")

    def rows(self) -> list[dict[str, Any]]:
        """Return a reproducible long-form configuration table."""
        rows: list[dict[str, Any]] = []
        modes = tuple(MotionMode)
        for index, mode in enumerate(modes):
            rows.append(
                {
                    "section": "motion_model",
                    "parameter": mode.value,
                    "value": self.acceleration_std_hz_per_s2[index],
                    "unit": "Hz/s^2",
                    "research_only": True,
                }
            )
        scalar_units = {
            "measurement_std_hz": "Hz",
            "initial_frequency_std_hz": "Hz",
            "initial_rate_std_hz_per_s": "Hz/s",
            "rank_log_penalty": "dimensionless",
            "node_cost_penalty": "dimensionless",
            "low_confidence_threshold": "probability-like",
            "minimum_confident_background_db": "dB",
            "minimum_confident_competitor_db": "dB",
            "large_innovation_sigma": "standard deviations",
            "branch_switch_step_hz": "Hz",
            "broadband_robust_z_threshold": "robust standard deviations",
            "orientation_time_half_width_s": "s",
            "orientation_frequency_half_width_hz": "Hz",
        }
        for name, unit in scalar_units.items():
            rows.append(
                {
                    "section": "tracker",
                    "parameter": name,
                    "value": getattr(self, name),
                    "unit": unit,
                    "research_only": True,
                }
            )
        for source, row in zip(modes, self.mode_transition_matrix, strict=True):
            for target, value in zip(modes, row, strict=True):
                rows.append(
                    {
                        "section": "mode_transition",
                        "parameter": f"{source.value}_to_{target.value}",
                        "value": value,
                        "unit": "probability",
                        "research_only": True,
                    }
                )
        return rows


@dataclass(frozen=True, slots=True, eq=False)
class IMMState:
    """Conditional state/covariance for each model plus model probabilities."""

    means: FloatArray
    covariances: FloatArray
    probabilities: FloatArray

    def __post_init__(self) -> None:
        means = np.asarray(self.means, dtype=np.float64)
        covariance = np.asarray(self.covariances, dtype=np.float64)
        probability = np.asarray(self.probabilities, dtype=np.float64)
        if means.shape != (3, 2) or covariance.shape != (3, 2, 2):
            raise ValueError("IMM state must contain three two-state filters.")
        if probability.shape != (3,) or np.any(probability < 0.0):
            raise ValueError("IMM model probability has invalid shape or sign.")
        if not np.all(np.isfinite(means)) or not np.all(np.isfinite(covariance)):
            raise ValueError("IMM means and covariances must be finite.")
        total = float(np.sum(probability))
        if not math.isfinite(total) or total <= 0.0:
            raise ValueError("IMM model probabilities must have positive mass.")
        probability = probability / total
        for matrix in covariance:
            if np.min(np.linalg.eigvalsh(matrix)) < -1.0e-6:
                raise ValueError("IMM covariance must be positive semidefinite.")
        object.__setattr__(self, "means", _immutable(means))
        object.__setattr__(self, "covariances", _immutable(covariance))
        object.__setattr__(self, "probabilities", _immutable(probability))


@dataclass(frozen=True, slots=True)
class IMMUpdateEvidence:
    """Scalar association evidence returned by a measurement update."""

    log_likelihood: float
    normalized_innovation: float
    innovation_hz: float
    innovation_std_hz: float


@dataclass(frozen=True, slots=True)
class TrackStep:
    """One coverage-first trajectory sample and its independent annotations."""

    frequency_hz: float
    frequency_rate_hz_per_s: float
    selected_rank: int
    selected_candidate_index: int
    track_mode: MotionMode
    track_uncertainty_hz: float
    model_probability: tuple[float, float, float]
    innovation_hz: float
    normalized_innovation: float
    association_confidence: float
    quality_flags: tuple[QualityFlag, ...]
    parent_beam_rank: int


@dataclass(frozen=True, slots=True)
class TrackerResult:
    """Recovered best trajectory, including MHT-use and runtime diagnostics."""

    time_s: FloatArray
    steps: tuple[TrackStep, ...]
    beam_width: int
    runtime_s: float
    hypothesis_rescue_count: int
    maximum_live_hypotheses: int

    @property
    def frequency_hz(self) -> FloatArray:
        return np.asarray([step.frequency_hz for step in self.steps], dtype=np.float64)

    @property
    def frequency_rate_hz_per_s(self) -> FloatArray:
        return np.asarray(
            [step.frequency_rate_hz_per_s for step in self.steps], dtype=np.float64
        )

    @property
    def selected_rank(self) -> IntArray:
        return np.asarray([step.selected_rank for step in self.steps], dtype=np.int64)

    @property
    def uncertainty_hz(self) -> FloatArray:
        return np.asarray([step.track_uncertainty_hz for step in self.steps], dtype=np.float64)


@dataclass(frozen=True, slots=True)
class OrientationDiagnostic:
    """Candidate-local structure-tensor output in physical time/frequency scales."""

    local_orientation_rad: float
    local_frequency_rate_hz_per_s: float
    orientation_coherence: float
    ridge_likeness: float
    vertical_likeness: float


@dataclass(slots=True)
class _Hypothesis:
    state: IMMState
    score: float
    steps: tuple[TrackStep, ...] = field(default_factory=tuple)


def initialize_imm(frequency_hz: float, config: TrackerConfig) -> IMMState:
    """Initialize all model-conditioned filters at the first measurement."""
    means = np.tile(np.asarray([frequency_hz, 0.0], dtype=np.float64), (3, 1))
    covariance = np.zeros((3, 2, 2), dtype=np.float64)
    covariance[:, 0, 0] = config.initial_frequency_std_hz**2
    covariance[:, 1, 1] = config.initial_rate_std_hz_per_s**2
    return IMMState(means, covariance, np.asarray(config.initial_mode_probability))


def imm_predict(state: IMMState, delta_time_s: float, config: TrackerConfig) -> IMMState:
    """Perform standard IMM mixing and constant-rate model prediction."""
    if not math.isfinite(delta_time_s) or delta_time_s <= 0.0:
        raise ValueError("delta_time_s must be finite and strictly positive.")
    transition = np.asarray(config.mode_transition_matrix, dtype=np.float64)
    prior = state.probabilities
    destination_probability = prior @ transition
    mixed_means = np.empty((3, 2), dtype=np.float64)
    mixed_covariance = np.empty((3, 2, 2), dtype=np.float64)
    for destination in range(3):
        weights = prior * transition[:, destination] / destination_probability[destination]
        mean = np.sum(weights[:, None] * state.means, axis=0)
        covariance = np.zeros((2, 2), dtype=np.float64)
        for source in range(3):
            delta = state.means[source] - mean
            covariance += weights[source] * (
                state.covariances[source] + np.outer(delta, delta)
            )
        mixed_means[destination] = mean
        mixed_covariance[destination] = covariance
    dt = delta_time_s
    motion = np.asarray([[1.0, dt], [0.0, 1.0]], dtype=np.float64)
    predicted_means = mixed_means @ motion.T
    predicted_covariance = np.empty_like(mixed_covariance)
    for index, acceleration_std in enumerate(config.acceleration_std_hz_per_s2):
        gain = np.asarray([0.5 * dt * dt, dt], dtype=np.float64)
        process = acceleration_std**2 * np.outer(gain, gain)
        predicted_covariance[index] = (
            motion @ mixed_covariance[index] @ motion.T + process
        )
    return IMMState(predicted_means, predicted_covariance, destination_probability)


def imm_update(
    predicted: IMMState,
    measurement_hz: float,
    config: TrackerConfig,
) -> tuple[IMMState, IMMUpdateEvidence]:
    """Perform scalar-frequency Kalman updates and Bayesian mode update."""
    measurement_variance = config.measurement_std_hz**2
    means = np.empty_like(predicted.means)
    covariance = np.empty_like(predicted.covariances)
    likelihood = np.empty(3, dtype=np.float64)
    innovations = np.empty(3, dtype=np.float64)
    innovation_variance = np.empty(3, dtype=np.float64)
    identity = np.eye(2, dtype=np.float64)
    observation = np.asarray([1.0, 0.0], dtype=np.float64)
    for index in range(3):
        innovation = measurement_hz - predicted.means[index, 0]
        variance = predicted.covariances[index, 0, 0] + measurement_variance
        kalman_gain = predicted.covariances[index, :, 0] / variance
        means[index] = predicted.means[index] + kalman_gain * innovation
        # Joseph form keeps finite-precision covariance positive semidefinite.
        reduction = identity - np.outer(kalman_gain, observation)
        covariance[index] = (
            reduction @ predicted.covariances[index] @ reduction.T
            + measurement_variance * np.outer(kalman_gain, kalman_gain)
        )
        innovations[index] = innovation
        innovation_variance[index] = variance
        likelihood[index] = math.exp(-0.5 * innovation * innovation / variance) / math.sqrt(
            2.0 * math.pi * variance
        )
    unnormalized = predicted.probabilities * likelihood
    evidence = float(np.sum(unnormalized))
    if evidence <= np.finfo(np.float64).tiny:
        posterior_probability = np.full(3, 1.0 / 3.0, dtype=np.float64)
        log_likelihood = math.log(np.finfo(np.float64).tiny)
    else:
        posterior_probability = unnormalized / evidence
        log_likelihood = math.log(evidence)
    weighted_innovation = float(np.sum(predicted.probabilities * innovations))
    weighted_variance = float(
        np.sum(
            predicted.probabilities
            * (innovation_variance + np.square(innovations - weighted_innovation))
        )
    )
    normalized = weighted_innovation / math.sqrt(weighted_variance)
    return (
        IMMState(means, covariance, posterior_probability),
        IMMUpdateEvidence(
            log_likelihood=log_likelihood,
            normalized_innovation=normalized,
            innovation_hz=weighted_innovation,
            innovation_std_hz=math.sqrt(weighted_variance),
        ),
    )


def combine_imm_state(state: IMMState) -> tuple[FloatArray, FloatArray]:
    """Moment-match model-conditioned estimates into one mean/covariance."""
    mean = np.sum(state.probabilities[:, None] * state.means, axis=0)
    covariance = np.zeros((2, 2), dtype=np.float64)
    for index in range(3):
        delta = state.means[index] - mean
        covariance += state.probabilities[index] * (
            state.covariances[index] + np.outer(delta, delta)
        )
    return mean, covariance


def track_candidates(
    candidate_set: RidgeCandidateSet,
    *,
    config: TrackerConfig | None = None,
    beam_width: int = 8,
    stft_result: STFTResult | None = None,
) -> TrackerResult:
    """Track a fixed candidate graph with mandatory association and IMM beam search.

    Complexity is ``O(T * B * K * M)`` time and ``O(B * T + B * M)`` retained
    history/state memory, where ``M=3`` models.
    """
    if beam_width < 1:
        raise ValueError("beam_width must be at least one.")
    resolved = TrackerConfig() if config is None else config
    start = time.perf_counter()
    broadband = _broadband_robust_z(stft_result) if stft_result is not None else None
    beam: list[_Hypothesis] = []
    maximum_live = 0
    for frame_index, frame in enumerate(candidate_set.candidates_by_frame):
        children: list[_Hypothesis] = []
        if frame_index == 0:
            seed_candidates = frame
            fallback = False
            if not seed_candidates:
                frequency = _strongest_bin_frequency(candidate_set, 0, stft_result)
                seed_candidates = (_fallback_candidate(candidate_set, 0, frequency),)
                fallback = True
            for candidate_index, candidate in enumerate(seed_candidates):
                state = initialize_imm(candidate.transition_frequency_hz, resolved)
                flags = [QualityFlag.CANDIDATE_UPDATE]
                if fallback:
                    flags = [QualityFlag.STRONGEST_BIN_FALLBACK, QualityFlag.LOW_CONFIDENCE]
                flags.extend(_candidate_flags(candidate, 0.0, 1.0, False, broadband, 0, resolved))
                step = _make_step(
                    state,
                    candidate.transition_frequency_hz,
                    0.0,
                    candidate.candidate_rank if not fallback else 0,
                    candidate_index if not fallback else -1,
                    0.5 if not fallback else 0.0,
                    tuple(dict.fromkeys(flags)),
                    0,
                )
                score = _candidate_prior_score(candidate, resolved) if not fallback else -20.0
                children.append(_Hypothesis(state, score, (step,)))
        else:
            delta_time = float(candidate_set.time_s[frame_index] - candidate_set.time_s[frame_index - 1])
            for parent_rank, hypothesis in enumerate(beam):
                predicted = imm_predict(hypothesis.state, delta_time, resolved)
                if frame:
                    for candidate_index, candidate in enumerate(frame):
                        updated, evidence = imm_update(
                            predicted, candidate.transition_frequency_hz, resolved
                        )
                        confidence = _association_confidence(updated, evidence)
                        combined_previous = hypothesis.steps[-1].frequency_hz
                        flags = [QualityFlag.CANDIDATE_UPDATE]
                        flags.extend(
                            _candidate_flags(
                                candidate,
                                evidence.normalized_innovation,
                                confidence,
                                abs(candidate.transition_frequency_hz - combined_previous)
                                >= resolved.branch_switch_step_hz,
                                broadband,
                                frame_index,
                                resolved,
                            )
                        )
                        if parent_rank > 0:
                            flags.append(QualityFlag.POSSIBLE_BRANCH_SWITCH)
                        step = _make_step(
                            updated,
                            candidate.transition_frequency_hz,
                            evidence.innovation_hz,
                            candidate.candidate_rank,
                            candidate_index,
                            confidence,
                            tuple(dict.fromkeys(flags)),
                            parent_rank,
                            normalized_innovation=evidence.normalized_innovation,
                        )
                        children.append(
                            _Hypothesis(
                                updated,
                                hypothesis.score
                                - 0.5 * evidence.normalized_innovation**2
                                + _candidate_prior_score(candidate, resolved),
                                hypothesis.steps + (step,),
                            )
                        )
                else:
                    mean, covariance = combine_imm_state(predicted)
                    flags = [QualityFlag.PREDICTED_GAP, QualityFlag.LOW_CONFIDENCE]
                    if broadband is not None and broadband[frame_index] >= resolved.broadband_robust_z_threshold:
                        flags.append(QualityFlag.BROADBAND_ELEVATED)
                    step = _make_step(
                        predicted,
                        float(mean[0]),
                        0.0,
                        0,
                        -1,
                        0.0,
                        tuple(flags),
                        parent_rank,
                        uncertainty_override=math.sqrt(max(float(covariance[0, 0]), 0.0)),
                    )
                    children.append(
                        _Hypothesis(predicted, hypothesis.score - 4.0, hypothesis.steps + (step,))
                    )
        children.sort(key=_hypothesis_sort_key)
        beam = children[:beam_width]
        maximum_live = max(maximum_live, len(beam))
    if not beam:
        raise RuntimeError("Tracker did not produce a hypothesis.")
    best = beam[0]
    rescue = sum(step.parent_beam_rank > 0 for step in best.steps[1:])
    frequencies = np.asarray([step.frequency_hz for step in best.steps], dtype=np.float64)
    if not np.all(np.isfinite(frequencies)):
        raise RuntimeError("Coverage-first tracker produced a silent NaN.")
    return TrackerResult(
        time_s=candidate_set.time_s,
        steps=best.steps,
        beam_width=beam_width,
        runtime_s=time.perf_counter() - start,
        hypothesis_rescue_count=rescue,
        maximum_live_hypotheses=maximum_live,
    )


def mandatory_candidate_dp(candidate_set: RidgeCandidateSet) -> tuple[FloatArray, IntArray]:
    """Coverage-first first-order DP comparator with no NULL state."""
    frames = candidate_set.candidates_by_frame
    if any(not frame for frame in frames):
        raise ValueError("Mandatory DP comparator requires a candidate in every frame.")
    scale = candidate_set.config.frequency_step_scale_hz
    cumulative = np.asarray(
        [candidate_node_cost(candidate, candidate_set.config) for candidate in frames[0]],
        dtype=np.float64,
    )
    predecessors: list[IntArray] = [np.full(len(frames[0]), -1, dtype=np.int64)]
    for frame_index in range(1, len(frames)):
        current = np.empty(len(frames[frame_index]), dtype=np.float64)
        parent = np.empty(len(frames[frame_index]), dtype=np.int64)
        for current_index, candidate in enumerate(frames[frame_index]):
            alternatives = cumulative + np.asarray(
                [
                    ((candidate.transition_frequency_hz - previous.transition_frequency_hz) / scale) ** 2
                    for previous in frames[frame_index - 1]
                ],
                dtype=np.float64,
            )
            parent[current_index] = int(np.argmin(alternatives))
            current[current_index] = (
                alternatives[parent[current_index]]
                + candidate_node_cost(candidate, candidate_set.config)
            )
        predecessors.append(parent)
        cumulative = current
    indices = np.empty(len(frames), dtype=np.int64)
    indices[-1] = int(np.argmin(cumulative))
    for frame_index in range(len(frames) - 1, 0, -1):
        indices[frame_index - 1] = predecessors[frame_index][indices[frame_index]]
    frequency = np.asarray(
        [frames[index][selected].transition_frequency_hz for index, selected in enumerate(indices)],
        dtype=np.float64,
    )
    rank = np.asarray(
        [frames[index][selected].candidate_rank for index, selected in enumerate(indices)],
        dtype=np.int64,
    )
    return frequency, rank


def structure_tensor_diagnostic(
    stft_result: STFTResult,
    *,
    time_s: float,
    frequency_hz: float,
    config: TrackerConfig | None = None,
) -> OrientationDiagnostic:
    """Measure local direction from a structure tensor on physical-axis support."""
    resolved = TrackerConfig() if config is None else config
    time_mask = np.abs(stft_result.time_s - time_s) <= resolved.orientation_time_half_width_s
    frequency_mask = (
        np.abs(stft_result.frequency_hz - frequency_hz)
        <= resolved.orientation_frequency_half_width_hz
    )
    time_indices = np.flatnonzero(time_mask)
    frequency_indices = np.flatnonzero(frequency_mask)
    if time_indices.size < 3 or frequency_indices.size < 3:
        return OrientationDiagnostic(math.nan, math.nan, 0.0, 0.0, 0.0)
    patch = np.log1p(np.abs(stft_result.spectrum[np.ix_(frequency_indices, time_indices)]))
    # Dimensionless physical coordinates prevent pixel aspect ratio from setting orientation.
    derivative_frequency, derivative_time = np.gradient(
        patch,
        stft_result.frequency_hz[frequency_indices] / resolved.orientation_frequency_half_width_hz,
        stft_result.time_s[time_indices] / resolved.orientation_time_half_width_s,
    )
    j_tt = float(np.mean(np.square(derivative_time)))
    j_tf = float(np.mean(derivative_time * derivative_frequency))
    j_ff = float(np.mean(np.square(derivative_frequency)))
    tensor = np.asarray([[j_tt, j_tf], [j_tf, j_ff]], dtype=np.float64)
    eigenvalue, eigenvector = np.linalg.eigh(tensor)
    tangent = eigenvector[:, 0]
    if tangent[0] < 0.0:
        tangent = -tangent
    angle = math.atan2(float(tangent[1]), float(tangent[0]))
    denominator = max(float(np.sum(eigenvalue)), np.finfo(np.float64).eps)
    coherence = float(np.clip((eigenvalue[1] - eigenvalue[0]) / denominator, 0.0, 1.0))
    slope = (
        math.copysign(math.inf, float(tangent[1]))
        if abs(float(tangent[0])) < 1.0e-12
        else float(tangent[1] / tangent[0])
        * resolved.orientation_frequency_half_width_hz
        / resolved.orientation_time_half_width_s
    )
    local_center = patch[frequency_indices.size // 2, time_indices.size // 2]
    contrast = max(float(local_center - np.median(patch)), 0.0)
    ridge_likeness = coherence * (1.0 - math.exp(-contrast))
    vertical = coherence * abs(math.sin(angle))
    return OrientationDiagnostic(angle, slope, coherence, ridge_likeness, vertical)


def _candidate_prior_score(candidate: RidgeCandidate, config: TrackerConfig) -> float:
    rank_term = -config.rank_log_penalty * math.log(float(candidate.candidate_rank))
    return rank_term - config.node_cost_penalty * candidate_node_cost(
        candidate, GlobalPathConfig(top_k=max(candidate.candidate_rank, 1))
    )


def _association_confidence(state: IMMState, evidence: IMMUpdateEvidence) -> float:
    innovation_term = math.exp(-0.5 * evidence.normalized_innovation**2)
    return float(np.clip(innovation_term * np.max(state.probabilities), 0.0, 1.0))


def _candidate_flags(
    candidate: RidgeCandidate,
    normalized_innovation: float,
    confidence: float,
    branch_switch: bool,
    broadband: FloatArray | None,
    frame_index: int,
    config: TrackerConfig,
) -> list[QualityFlag]:
    flags: list[QualityFlag] = []
    spectral_confidence_low = (
        not math.isfinite(candidate.peak_to_background_db)
        or not math.isfinite(candidate.peak_to_competitor_db)
        or candidate.peak_to_background_db < config.minimum_confident_background_db
        or candidate.peak_to_competitor_db < config.minimum_confident_competitor_db
    )
    if confidence < config.low_confidence_threshold or spectral_confidence_low:
        flags.append(QualityFlag.LOW_CONFIDENCE)
    if abs(normalized_innovation) >= config.large_innovation_sigma:
        flags.append(QualityFlag.LARGE_INNOVATION)
    if branch_switch:
        flags.append(QualityFlag.POSSIBLE_BRANCH_SWITCH)
    if broadband is not None and broadband[frame_index] >= config.broadband_robust_z_threshold:
        flags.append(QualityFlag.BROADBAND_ELEVATED)
    if candidate.refinement_status is not RidgeRefinementStatus.REFINED:
        flags.append(QualityFlag.REFINEMENT_FAILED)
    return flags


def _make_step(
    state: IMMState,
    output_frequency_hz: float,
    innovation_hz: float,
    selected_rank: int,
    selected_candidate_index: int,
    confidence: float,
    flags: tuple[QualityFlag, ...],
    parent_beam_rank: int,
    *,
    normalized_innovation: float = 0.0,
    uncertainty_override: float | None = None,
) -> TrackStep:
    mean, covariance = combine_imm_state(state)
    uncertainty = (
        math.sqrt(max(float(covariance[0, 0]), 0.0))
        if uncertainty_override is None
        else uncertainty_override
    )
    mode = tuple(MotionMode)[int(np.argmax(state.probabilities))]
    return TrackStep(
        frequency_hz=float(output_frequency_hz),
        frequency_rate_hz_per_s=float(mean[1]),
        selected_rank=selected_rank,
        selected_candidate_index=selected_candidate_index,
        track_mode=mode,
        track_uncertainty_hz=uncertainty,
        model_probability=(
            float(state.probabilities[0]),
            float(state.probabilities[1]),
            float(state.probabilities[2]),
        ),
        innovation_hz=innovation_hz,
        normalized_innovation=normalized_innovation,
        association_confidence=confidence,
        quality_flags=flags,
        parent_beam_rank=parent_beam_rank,
    )


def _hypothesis_sort_key(hypothesis: _Hypothesis) -> tuple[float, tuple[int, ...]]:
    ranks = tuple(step.selected_rank for step in hypothesis.steps)
    return (-hypothesis.score, ranks)


def _broadband_robust_z(stft_result: STFTResult) -> FloatArray:
    power = np.sum(np.square(np.abs(stft_result.spectrum)), axis=0)
    median = float(np.median(power))
    mad = float(np.median(np.abs(power - median)))
    scale = max(1.4826 * mad, np.finfo(np.float64).eps * max(abs(median), 1.0))
    return np.asarray((power - median) / scale, dtype=np.float64)


def _strongest_bin_frequency(
    candidate_set: RidgeCandidateSet,
    frame_index: int,
    stft_result: STFTResult | None,
) -> float:
    if stft_result is None:
        raise ValueError("An initial empty candidate frame requires the real STFT fallback.")
    mask = (stft_result.frequency_hz >= candidate_set.minimum_frequency_hz) & (
        stft_result.frequency_hz <= candidate_set.maximum_frequency_hz
    )
    indices = np.flatnonzero(mask)
    strongest = int(indices[int(np.argmax(np.abs(stft_result.spectrum[indices, frame_index])))])
    return float(stft_result.frequency_hz[strongest])


def _fallback_candidate(
    candidate_set: RidgeCandidateSet,
    frame_index: int,
    frequency_hz: float,
) -> RidgeCandidate:
    return RidgeCandidate(
        frame_index=frame_index,
        time_s=float(candidate_set.time_s[frame_index]),
        candidate_rank=1,
        discrete_bin_index=0,
        discrete_frequency_hz=frequency_hz,
        refined_frequency_hz=math.nan,
        peak_amplitude=0.0,
        peak_to_background_db=math.nan,
        peak_to_competitor_db=math.nan,
        cycles_in_window=0.0,
        is_band_boundary=False,
        refinement_status=RidgeRefinementStatus.INVALID_LOCAL_PEAK,
    )


def _immutable(value: FloatArray) -> FloatArray:
    array = np.array(value, dtype=np.float64, copy=True, order="C")
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.float64).reshape(array.shape)
    stored.setflags(write=False)
    return stored


__all__ = [
    "IMMState",
    "IMMUpdateEvidence",
    "MotionMode",
    "OrientationDiagnostic",
    "QualityFlag",
    "TrackStep",
    "TrackerConfig",
    "TrackerResult",
    "combine_imm_state",
    "imm_predict",
    "imm_update",
    "initialize_imm",
    "mandatory_candidate_dp",
    "structure_tensor_diagnostic",
    "track_candidates",
]
