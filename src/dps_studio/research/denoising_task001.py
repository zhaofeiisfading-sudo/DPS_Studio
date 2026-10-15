"""TASK-001: spectral evidence and amplitude-consistent, two-sided candidate repair.

Research only. No truth inputs, generated frequencies, voltage edits, smoothing,
or target-identity certification. All accepted values are original candidates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Callable
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize  # type: ignore[import-untyped]
from scipy.ndimage import median_filter  # type: ignore[import-untyped]

from dps_studio.core.ridge import RidgeCandidateSet
from dps_studio.core.time_frequency import STFTResult

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
IntArray = NDArray[np.int64]


@dataclass(frozen=True)
class EvidenceConfig:
    alpha: float = .01
    minimum_amplitude_ratio: float = .25
    background_half_width_hz: float | None = None

    def __post_init__(self) -> None:
        if not 0 < self.alpha < 1 or not 0 < self.minimum_amplitude_ratio <= 1:
            raise ValueError("Invalid spectral evidence configuration")
        if (self.background_half_width_hz is not None
                and (not np.isfinite(self.background_half_width_hz)
                     or self.background_half_width_hz <= 0)):
            raise ValueError("Background half-width must be finite and positive")


@dataclass(frozen=True)
class SpectralEvidence:
    maximum_log_evidence: FloatArray
    signal_supported: BoolArray
    significant_candidates: IntArray
    states: tuple[str, ...]
    validated_frequency_hz: FloatArray
    candidate_log_evidence: tuple[FloatArray, ...]


def spectral_evidence(stft: STFTResult, peaks: RidgeCandidateSet,
                      config: EvidenceConfig = EvidenceConfig()) -> SpectralEvidence:
    """Plug-in white-noise exponential tail with padded-bin union correction.

    Median power / ln(2) estimates the exponential mean. Estimation, colored
    noise, window leakage and correlated bins preclude exact p-value claims.
    Threshold is fixed in advance; no persistence dilation or zero velocities.
    """
    if not np.array_equal(stft.time_s, peaks.time_s):
        raise ValueError("STFT and candidate axes differ")
    band = ((stft.frequency_hz >= peaks.minimum_frequency_hz)
            & (stft.frequency_hz <= peaks.maximum_frequency_hz))
    power = np.abs(stft.spectrum[band]) ** 2
    if config.background_half_width_hz is None:
        floor = np.broadcast_to(np.median(power, axis=0)[None, :], power.shape) / np.log(2)
    else:
        df = float(np.median(np.diff(stft.frequency_hz)))
        half = int(np.ceil(config.background_half_width_hz / df))
        floor = np.asarray(median_filter(power, size=(2 * half + 1, 1), mode="reflect")) / np.log(2)
    floor = np.maximum(floor, np.finfo(float).tiny)
    first_band_bin = int(np.flatnonzero(band)[0])
    counts = np.zeros(len(peaks.time_s), dtype=np.int64)
    statistic = np.full(len(peaks.time_s), -np.inf)
    candidate_logs: list[FloatArray] = []
    for i, frame in enumerate(peaks.candidates_by_frame):
        if not frame:
            candidate_logs.append(np.empty(0))
            continue
        ratios = np.asarray([c.peak_amplitude**2 / floor[c.discrete_bin_index-first_band_bin, i]
                             for c in frame])
        logs = np.minimum(ratios, 1e12) - np.log(int(band.sum()))
        candidate_logs.append(logs)
        statistic[i] = float(np.max(logs))
        amplitudes = np.asarray([c.peak_amplitude for c in frame])
        counts[i] = int(np.sum((logs >= -np.log(config.alpha))
                              & (amplitudes >= config.minimum_amplitude_ratio * amplitudes[0])))
    supported = statistic >= -np.log(config.alpha)
    states = tuple("NO_INFORMATION" if not supported[i] else
                   "SIGNAL_IDENTITY_UNCERTAIN" if counts[i] > 1 else
                   "SPECTRAL_SUPPORTED_IDENTITY_UNREVIEWED" for i in range(len(supported)))
    return SpectralEvidence(statistic, supported, counts, states,
                            np.full(len(peaks.time_s), np.nan), tuple(candidate_logs))


@dataclass(frozen=True)
class RepairConfig:
    jump_hz: float = 450e6
    maximum_duration_s: float = 180e-9
    anchors_per_side: int = 4
    anchor_residual_hz: float = 35e6
    agreement_hz: float = 80e6
    candidate_tolerance_hz: float = 85e6
    minimum_background_db: float = 12.
    minimum_anchor_amplitude_ratio: float = .55
    maximum_anchor_amplitude_ratio: float = 1.8
    minimum_deviation_hz: float = 300e6
    minimum_bridge_fraction: float = .8

    def __post_init__(self) -> None:
        positive = (self.jump_hz, self.maximum_duration_s, self.anchor_residual_hz,
                    self.agreement_hz, self.candidate_tolerance_hz,
                    self.minimum_anchor_amplitude_ratio, self.minimum_deviation_hz)
        if (not all(np.isfinite(x) and x > 0 for x in positive)
                or self.anchors_per_side < 3 or not 0 < self.minimum_bridge_fraction <= 1
                or self.maximum_anchor_amplitude_ratio < self.minimum_anchor_amplitude_ratio
                or not np.isfinite(self.minimum_background_db)):
            raise ValueError("Invalid repair configuration")


@dataclass(frozen=True)
class Proposal:
    first: int
    stop: int
    frame_indices: IntArray
    candidate_indices: IntArray
    features: FloatArray
    anchor_residual_hz: float
    side_disagreement_hz: float
    prediction_hz: FloatArray
    reference_amplitude_v: float


FEATURE_NAMES = (
    "background_db_over_20", "competitor_db_over_20", "prediction_distance_over_tolerance",
    "absolute_log_anchor_amplitude_ratio", "log_relative_strongest_amplitude",
    "side_disagreement_over_tolerance", "anchor_residual_over_tolerance",
)


def candidate_features(peaks: RidgeCandidateSet, frame_index: int, candidate_index: int,
                       prediction_hz: float, reference_amplitude_v: float,
                       disagreement_hz: float, residual_hz: float) -> FloatArray:
    """Same observation-only features for every candidate in a proposed frame."""
    frame = peaks.candidates_by_frame[frame_index]
    candidate = frame[candidate_index]
    amplitude_ratio = candidate.peak_amplitude / max(reference_amplitude_v, 1e-300)
    return np.asarray([
        candidate.peak_to_background_db / 20, candidate.peak_to_competitor_db / 20,
        abs(candidate.transition_frequency_hz - prediction_hz) / 85e6,
        abs(np.log(max(amplitude_ratio, 1e-12))),
        np.log(max(candidate.peak_amplitude / frame[0].peak_amplitude, 1e-12)),
        disagreement_hz / 80e6, residual_hz / 35e6,
    ])


def _fit_side(time_s: FloatArray, frequency_hz: FloatArray, indices: IntArray,
              reference_s: float) -> tuple[FloatArray, float]:
    design = np.column_stack((np.ones(len(indices)), (time_s[indices] - reference_s) / 1e-9))
    coefficients = np.linalg.lstsq(design, frequency_hz[indices], rcond=None)[0]
    residual = float(np.max(np.abs(design @ coefficients - frequency_hz[indices])))
    return np.asarray(coefficients), residual


def propose_repairs(stft: STFTResult, peaks: RidgeCandidateSet, baseline_hz: FloatArray,
                    config: RepairConfig = RepairConfig()) -> tuple[Proposal, ...]:
    """Pair observed jumps; independently extrapolate disjoint left/right windows.

    Agreement only proposes a tube. Frequency is NEVER filled from that tube.
    Four nonoverlapping windows per side provide amplitude reference and veto
    curvature/rapid transitions. Candidate amplitude must continue both anchors.
    """
    if (baseline_hz.shape != peaks.time_s.shape or not np.all(np.isfinite(baseline_hz))
            or not np.array_equal(stft.time_s, peaks.time_s)):
        raise ValueError("Expected a finite baseline on the unmodified STFT axis")
    if any(not frame for frame in peaks.candidates_by_frame):
        return ()
    time_s = peaks.time_s
    stride = int(np.ceil(stft.window_length_samples / stft.hop_samples))
    jumps = np.flatnonzero(np.abs(np.diff(baseline_hz)) >= config.jump_hz) + 1
    proposals: list[Proposal] = []
    consumed_stop = -1
    for start_position, first in enumerate(jumps):
        if first < consumed_stop:
            continue
        for stop in jumps[start_position + 1:]:
            if time_s[stop] - time_s[first] > config.maximum_duration_s:
                break
            left = first - stride * np.arange(1, config.anchors_per_side + 1)
            right = stop + stride * np.arange(1, config.anchors_per_side + 1)
            if left.min() < 0 or right.max() >= len(time_s):
                continue
            left_fit, left_error = _fit_side(time_s, baseline_hz, left, time_s[first])
            right_fit, right_error = _fit_side(time_s, baseline_hz, right, time_s[first])
            residual = max(left_error, right_error)
            if residual > config.anchor_residual_hz:
                continue
            indices = np.arange(first, stop, dtype=np.int64)
            design = np.column_stack((np.ones(len(indices)),
                                      (time_s[indices] - time_s[first]) / 1e-9))
            left_prediction, right_prediction = design @ left_fit, design @ right_fit
            disagreement = float(np.max(np.abs(left_prediction - right_prediction)))
            if disagreement > config.agreement_hz:
                continue
            prediction = (left_prediction + right_prediction) / 2
            # Every anchor is an observed baseline candidate, never a GT point.
            anchor_amplitudes = []
            anchor_good = True
            for i in np.r_[left, right]:
                candidate = min(peaks.candidates_by_frame[i],
                                key=lambda c: abs(c.transition_frequency_hz - baseline_hz[i]))
                anchor_amplitudes.append(candidate.peak_amplitude)
                anchor_good &= candidate.peak_to_background_db >= config.minimum_background_db
            if not anchor_good:
                continue
            reference_amplitude = float(np.median(anchor_amplitudes))
            frame_indices, candidate_indices, features, predictions = [], [], [], []
            for i, predicted in zip(indices, prediction, strict=True):
                frame = peaks.candidates_by_frame[i]
                position = min(range(len(frame)),
                               key=lambda j: abs(frame[j].transition_frequency_hz - predicted))
                candidate = frame[position]
                distance = abs(candidate.transition_frequency_hz - predicted)
                amplitude_ratio = candidate.peak_amplitude / max(reference_amplitude, 1e-300)
                if (distance > config.candidate_tolerance_hz
                        or candidate.peak_to_background_db < config.minimum_background_db
                        or not config.minimum_anchor_amplitude_ratio <= amplitude_ratio
                        <= config.maximum_anchor_amplitude_ratio):
                    continue
                if abs(candidate.transition_frequency_hz - baseline_hz[i]) < config.minimum_deviation_hz:
                    continue
                frame_indices.append(i)
                candidate_indices.append(position)
                predictions.append(predicted)
                features.append(candidate_features(peaks, int(i), position, float(predicted),
                                                    reference_amplitude, disagreement, residual))
            if len(frame_indices) < max(2, config.minimum_bridge_fraction * len(indices)):
                continue
            proposals.append(Proposal(int(first), int(stop), np.asarray(frame_indices, dtype=np.int64),
                np.asarray(candidate_indices, dtype=np.int64), np.asarray(features), residual,
                disagreement, np.asarray(predictions), reference_amplitude))
            consumed_stop = int(stop)
            break
    return tuple(proposals)


@dataclass(frozen=True)
class LogisticModel:
    mean: FloatArray
    scale: FloatArray
    coefficients: FloatArray
    temperature: float = 1.

    def predict(self, features: FloatArray) -> FloatArray:
        if features.ndim != 2 or features.shape[1] != len(self.mean):
            raise ValueError("Feature dimensions differ")
        design = np.column_stack((np.ones(len(features)), (features - self.mean) / self.scale))
        logits = np.clip(design @ self.coefficients / self.temperature, -40, 40)
        return np.asarray(1 / (1 + np.exp(-logits)))

    def to_dict(self) -> dict[str, Any]:
        return {"mean": self.mean.tolist(), "scale": self.scale.tolist(),
                "coefficients": self.coefficients.tolist(), "temperature": self.temperature,
                "feature_names": list(FEATURE_NAMES)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> LogisticModel:
        return cls(np.asarray(value["mean"]), np.asarray(value["scale"]),
                   np.asarray(value["coefficients"]), float(value["temperature"]))


def fit_logistic(features: FloatArray, labels: BoolArray, weights: FloatArray,
                 *, split: str, penalty: float = .03,
                 iteration_callback: Callable[[FloatArray], None] | None = None,
                 ) -> tuple[LogisticModel, list[float]]:
    """Small supervised candidate classifier; callers supply TRAIN groups only."""
    if split != "TRAIN":
        raise ValueError("Model fitting is TRAIN only")
    if (features.ndim != 2 or len(features) == 0 or labels.shape != (len(features),)
            or weights.shape != labels.shape or not np.all(np.isfinite(features))
            or not np.all(np.isfinite(weights)) or np.any(weights <= 0)
            or len(np.unique(labels)) != 2):
        raise ValueError("Need finite weighted examples from both classes")
    weights = weights / weights.sum()
    mean = np.sum(features * weights[:, None], axis=0)
    scale = np.sqrt(np.sum((features - mean)**2 * weights[:, None], axis=0))
    scale = np.maximum(scale, .1)
    design = np.column_stack((np.ones(len(features)), (features - mean) / scale))
    history: list[float] = []

    def objective(coefficients: FloatArray) -> tuple[float, FloatArray]:
        z = design @ coefficients
        loss = float(np.sum(weights * (np.logaddexp(0, z) - labels * z))
                     + penalty / 2 * np.sum(coefficients[1:]**2))
        p = 1 / (1 + np.exp(-np.clip(z, -40, 40)))
        gradient = design.T @ (weights * (p - labels))
        gradient[1:] += penalty * coefficients[1:]
        return loss, np.asarray(gradient)

    def callback(coefficients: FloatArray) -> None:
        history.append(objective(coefficients)[0])
        if iteration_callback is not None:
            iteration_callback(coefficients.copy())

    fitted = minimize(objective, np.zeros(design.shape[1]), jac=True, method="L-BFGS-B",
                      callback=callback, options={"maxiter": 200, "ftol": 1e-12})
    if not fitted.success:
        raise RuntimeError(f"Logistic optimizer failed: {fitted.message}")
    return LogisticModel(mean, scale, np.asarray(fitted.x)), history


def apply_repairs(peaks: RidgeCandidateSet, baseline_hz: FloatArray,
                  proposals: tuple[Proposal, ...], *, model: LogisticModel | None = None,
                  probability_threshold: float = .95) -> tuple[FloatArray, list[dict[str, Any]]]:
    """Complete candidate hypothesis output; quality is a separate channel."""
    if (baseline_hz.shape != peaks.time_s.shape or not np.all(np.isfinite(baseline_hz))
            or not 0 <= probability_threshold <= 1):
        raise ValueError("Expected finite complete baseline and a probability threshold")
    output = baseline_hz.copy()
    audit: list[dict[str, Any]] = []
    for proposal in proposals:
        probabilities = (model.predict(proposal.features) if model is not None
                         else np.ones(len(proposal.frame_indices)))
        # Whole-window decision prevents arbitrary holes caused by framewise gating.
        accepted = bool(np.min(probabilities) >= probability_threshold)
        for i, j, probability in zip(proposal.frame_indices, proposal.candidate_indices,
                                     probabilities, strict=True):
            candidate = peaks.candidates_by_frame[i][j]
            audit.append(dict(frame=int(i), time_s=float(peaks.time_s[i]),
                previous_hz=float(baseline_hz[i]), proposed_hz=candidate.transition_frequency_hz,
                candidate_rank=candidate.candidate_rank, accepted=accepted,
                probability=float(probability), first=proposal.first, stop=proposal.stop,
                side_disagreement_hz=proposal.side_disagreement_hz,
                anchor_residual_hz=proposal.anchor_residual_hz))
            if accepted:
                output[i] = candidate.transition_frequency_hz
    return output, audit


def configuration() -> dict[str, Any]:
    return {"evidence": asdict(EvidenceConfig()), "repair": asdict(RepairConfig()),
            "model": {"type": "weighted_logistic_numpy_scipy", "l2": .03,
                      "maximum_iterations": 200, "features": list(FEATURE_NAMES)}}
