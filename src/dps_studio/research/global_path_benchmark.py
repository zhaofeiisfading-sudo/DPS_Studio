"""Fixed-seed synthetic benchmark for TASK-021A global ridge research."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.quality import SignalDetectionConfig
from dps_studio.core.ridge import (
    GlobalPathConfig,
    GlobalRidgePathResult,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
    track_global_candidate_path,
)
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import analyze_stft_results

FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
IntArray = NDArray[np.int64]


@dataclass(frozen=True, slots=True, eq=False)
class SyntheticGlobalPathCase:
    """One STFT-domain scenario with explicit frequency ground truth."""

    case_id: str
    description: str
    stft_result: STFTResult
    truth_frequency_hz: FloatArray
    pre_event_mask: BoolArray
    dropout_mask: BoolArray
    wrong_branch_tolerance_hz: float

    def __post_init__(self) -> None:
        truth = _immutable_float(self.truth_frequency_hz)
        pre_event = _immutable_bool(self.pre_event_mask)
        dropout = _immutable_bool(self.dropout_mask)
        expected = self.stft_result.time_s.shape
        if truth.shape != expected or pre_event.shape != expected or dropout.shape != expected:
            raise ValueError("Synthetic truth masks must match the STFT time axis.")
        if np.any(np.isinf(truth)):
            raise ValueError("Synthetic truth may be finite or NaN, never infinity.")
        if not self.case_id or not self.description:
            raise ValueError("Synthetic case identity and description are required.")
        if not math.isfinite(self.wrong_branch_tolerance_hz) or (
            self.wrong_branch_tolerance_hz <= 0.0
        ):
            raise ValueError("wrong_branch_tolerance_hz must be positive.")
        object.__setattr__(self, "truth_frequency_hz", truth)
        object.__setattr__(self, "pre_event_mask", pre_event)
        object.__setattr__(self, "dropout_mask", dropout)


@dataclass(frozen=True, slots=True)
class RidgeBenchmarkMetrics:
    """Ground-truth metrics for one case and one ridge estimator."""

    case_id: str
    method: str
    top_k: int | None
    frequency_rmse_hz: float
    velocity_rmse_m_s: float
    wrong_branch_frame_count: int
    wrong_branch_fraction: float
    valid_selected_coverage: float
    null_false_negative_count: int
    false_pre_event_detection_count: int
    recovery_after_dropout_frames: int | None
    rank_1_fraction: float
    rank_2_fraction: float
    rank_3_fraction: float
    rank_4_plus_fraction: float
    null_fraction: float

    def to_dict(self) -> dict[str, str | int | float | None]:
        """Return a flat artifact row."""
        return {
            field_name: getattr(self, field_name)
            for field_name in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True, eq=False)
class SyntheticBenchmarkResult:
    """All baselines and audit arrays for one fixed synthetic case."""

    case: SyntheticGlobalPathCase
    argmax_frequency_hz: FloatArray
    production_frequency_hz: FloatArray
    production_candidate_rank: IntArray
    global_path: GlobalRidgePathResult
    metrics: tuple[RidgeBenchmarkMetrics, ...]

    def __post_init__(self) -> None:
        expected = self.case.stft_result.time_s.shape
        argmax = _immutable_float(self.argmax_frequency_hz)
        production = _immutable_float(self.production_frequency_hz)
        ranks = _immutable_int(self.production_candidate_rank)
        if argmax.shape != expected or production.shape != expected or ranks.shape != expected:
            raise ValueError("Benchmark arrays must match the case time axis.")
        object.__setattr__(self, "argmax_frequency_hz", argmax)
        object.__setattr__(self, "production_frequency_hz", production)
        object.__setattr__(self, "production_candidate_rank", ranks)


DEFAULT_SYNTHETIC_SEED: int = 21021
DEFAULT_VACUUM_WAVELENGTH_M: float = 1.55e-6


def generate_synthetic_global_path_cases(
    *,
    seed: int = DEFAULT_SYNTHETIC_SEED,
) -> tuple[SyntheticGlobalPathCase, ...]:
    """Generate deterministic A–H spectra without event-reference information."""
    rng = np.random.default_rng(seed)
    definitions = _case_definitions()
    cases: list[SyntheticGlobalPathCase] = []
    for case_index, definition in enumerate(definitions):
        case_rng = np.random.default_rng(rng.integers(0, 2**32) + case_index)
        cases.append(_build_case(case_rng, **definition))
    return tuple(cases)


def run_synthetic_global_path_benchmark(
    *,
    config: GlobalPathConfig,
    seed: int = DEFAULT_SYNTHETIC_SEED,
    vacuum_wavelength_m: float = DEFAULT_VACUUM_WAVELENGTH_M,
) -> tuple[SyntheticBenchmarkResult, ...]:
    """Run raw argmax, current production, and TASK-021A for all A–H cases."""
    results: list[SyntheticBenchmarkResult] = []
    for case in generate_synthetic_global_path_cases(seed=seed):
        stft = case.stft_result
        minimum_hz = 0.4e9
        maximum_hz = 2.8e9
        raw_ridge = extract_peak_ridge(
            stft,
            minimum_frequency_hz=minimum_hz,
            maximum_frequency_hz=maximum_hz,
        )
        raw_refined = refine_peak_ridge_subbin(stft, raw_ridge)
        argmax = np.where(
            np.isfinite(raw_refined.refined_frequency_hz),
            raw_refined.refined_frequency_hz,
            raw_refined.discrete_frequency_hz,
        )
        production = analyze_stft_results(
            {"synthetic_channel": stft},
            minimum_frequency_hz=minimum_hz,
            maximum_frequency_hz=maximum_hz,
            vacuum_wavelength_m=vacuum_wavelength_m,
            detection_config=SignalDetectionConfig(minimum_consecutive_frames=1),
            profile_name="task021a_synthetic",
        )["synthetic_channel"]
        production_frequency = production.signal_detection_result.refined_frequency_hz
        production_rank = production.automatic_ridge_selection_result.selected_candidate_rank.copy()
        production_rank[~np.isfinite(production_frequency)] = 0
        global_path = track_global_candidate_path(
            stft,
            minimum_frequency_hz=minimum_hz,
            maximum_frequency_hz=maximum_hz,
            config=config,
        )
        metrics = (
            calculate_ridge_metrics(
                case,
                argmax,
                selected_candidate_rank=np.ones(argmax.size, dtype=np.int64),
                method="raw_framewise_argmax",
                top_k=None,
                vacuum_wavelength_m=vacuum_wavelength_m,
            ),
            calculate_ridge_metrics(
                case,
                production_frequency,
                selected_candidate_rank=production_rank,
                method="current_production_ridge",
                top_k=None,
                vacuum_wavelength_m=vacuum_wavelength_m,
            ),
            calculate_ridge_metrics(
                case,
                global_path.selected_refined_frequency_hz,
                selected_candidate_rank=global_path.selected_candidate_rank,
                method="task021a_global_path",
                top_k=config.top_k,
                vacuum_wavelength_m=vacuum_wavelength_m,
            ),
        )
        results.append(
            SyntheticBenchmarkResult(
                case=case,
                argmax_frequency_hz=argmax,
                production_frequency_hz=production_frequency,
                production_candidate_rank=production_rank,
                global_path=global_path,
                metrics=metrics,
            )
        )
    return tuple(results)


def calculate_ridge_metrics(
    case: SyntheticGlobalPathCase,
    estimated_frequency_hz: FloatArray,
    *,
    selected_candidate_rank: IntArray,
    method: str,
    top_k: int | None,
    vacuum_wavelength_m: float,
) -> RidgeBenchmarkMetrics:
    """Calculate explicit branch, NULL, recovery, and rank metrics."""
    estimate = np.asarray(estimated_frequency_hz, dtype=np.float64)
    ranks = np.asarray(selected_candidate_rank, dtype=np.int64)
    if estimate.shape != case.truth_frequency_hz.shape or ranks.shape != estimate.shape:
        raise ValueError("Metric inputs must match synthetic truth.")
    truth_valid = np.isfinite(case.truth_frequency_hz)
    selected = np.isfinite(estimate)
    comparable = truth_valid & selected
    errors = estimate[comparable] - case.truth_frequency_hz[comparable]
    frequency_rmse = (
        float(np.sqrt(np.mean(np.square(errors)))) if errors.size else math.nan
    )
    wrong = comparable & (
        np.abs(estimate - case.truth_frequency_hz) > case.wrong_branch_tolerance_hz
    )
    true_count = int(np.count_nonzero(truth_valid))
    coverage = float(np.count_nonzero(comparable) / true_count) if true_count else 1.0
    wrong_fraction = float(np.count_nonzero(wrong) / true_count) if true_count else 0.0
    recovery = _dropout_recovery_frames(case, selected)
    fractions = _rank_fractions(ranks, selected)
    return RidgeBenchmarkMetrics(
        case_id=case.case_id,
        method=method,
        top_k=top_k,
        frequency_rmse_hz=frequency_rmse,
        velocity_rmse_m_s=frequency_rmse * vacuum_wavelength_m / 2.0,
        wrong_branch_frame_count=int(np.count_nonzero(wrong)),
        wrong_branch_fraction=wrong_fraction,
        valid_selected_coverage=coverage,
        null_false_negative_count=int(np.count_nonzero(truth_valid & ~selected)),
        false_pre_event_detection_count=int(np.count_nonzero(case.pre_event_mask & selected)),
        recovery_after_dropout_frames=recovery,
        rank_1_fraction=fractions[0],
        rank_2_fraction=fractions[1],
        rank_3_fraction=fractions[2],
        rank_4_plus_fraction=fractions[3],
        null_fraction=fractions[4],
    )


def _case_definitions() -> tuple[dict[str, object], ...]:
    frame_count = 80
    constant = np.full(frame_count, 1.2e9, dtype=np.float64)
    no_mask = np.zeros(frame_count, dtype=np.bool_)
    dropout = no_mask.copy()
    dropout[32:38] = True
    shock_truth = np.full(frame_count, np.nan, dtype=np.float64)
    shock_truth[20:] = 1.8e9
    shock_pre_event = np.zeros(frame_count, dtype=np.bool_)
    shock_pre_event[:20] = True
    unloading = np.full(frame_count, 1.6e9, dtype=np.float64)
    unloading[40:] = np.round(
        np.linspace(1.6e9, 0.9e9, frame_count - 40) / 25.0e6
    ) * 25.0e6
    no_truth = np.full(frame_count, np.nan, dtype=np.float64)
    return (
        {
            "case_id": "A_clean_ridge",
            "description": "True ridge is strongest in every frame.",
            "truth_frequency_hz": constant,
            "pre_event_mask": no_mask,
            "dropout_mask": no_mask,
            "distractor": None,
            "weak_slice": None,
        },
        {
            "case_id": "B_isolated_stronger_distractor",
            "description": "A remote distractor is strongest for two isolated frames.",
            "truth_frequency_hz": constant,
            "pre_event_mask": no_mask,
            "dropout_mask": no_mask,
            "distractor": (slice(35, 37), 2.2e9, 18.0),
            "weak_slice": None,
        },
        {
            "case_id": "C_sustained_competing_branch",
            "description": "A long parallel branch is strongest over its central interval.",
            "truth_frequency_hz": constant,
            "pre_event_mask": no_mask,
            "dropout_mask": no_mask,
            "distractor": (slice(15, 65), 2.0e9, 14.0),
            "weak_slice": None,
        },
        {
            "case_id": "D_temporarily_weak_true_ridge",
            "description": "True ridge weakens while a remote competing peak remains.",
            "truth_frequency_hz": constant,
            "pre_event_mask": no_mask,
            "dropout_mask": no_mask,
            "distractor": (slice(28, 38), 2.0e9, 7.0),
            "weak_slice": (slice(28, 38), 4.0),
        },
        {
            "case_id": "E_temporary_dropout",
            "description": "True ridge is absent for six frames and must remain NULL.",
            "truth_frequency_hz": np.where(dropout, np.nan, constant),
            "pre_event_mask": no_mask,
            "dropout_mask": dropout,
            "distractor": None,
            "weak_slice": None,
        },
        {
            "case_id": "F_shock_like_onset",
            "description": "Noise-only pre-event frames precede an abrupt high-frequency ridge.",
            "truth_frequency_hz": shock_truth,
            "pre_event_mask": shock_pre_event,
            "dropout_mask": no_mask,
            "distractor": None,
            "weak_slice": None,
        },
        {
            "case_id": "G_plateau_and_unloading",
            "description": "A stable plateau transitions into a real continuous decline.",
            "truth_frequency_hz": unloading,
            "pre_event_mask": no_mask,
            "dropout_mask": no_mask,
            "distractor": None,
            "weak_slice": None,
        },
        {
            "case_id": "H_pure_noise",
            "description": "No physical ridge exists in any frame.",
            "truth_frequency_hz": no_truth,
            "pre_event_mask": np.ones(frame_count, dtype=np.bool_),
            "dropout_mask": no_mask,
            "distractor": None,
            "weak_slice": None,
        },
    )


def _build_case(
    rng: np.random.Generator,
    *,
    case_id: object,
    description: object,
    truth_frequency_hz: object,
    pre_event_mask: object,
    dropout_mask: object,
    distractor: object,
    weak_slice: object,
) -> SyntheticGlobalPathCase:
    frequency_hz = np.arange(129, dtype=np.float64) * 25.0e6
    truth = np.asarray(truth_frequency_hz, dtype=np.float64)
    frame_count = truth.size
    magnitudes = rng.lognormal(mean=math.log(0.18), sigma=0.35, size=(129, frame_count))
    phases = rng.uniform(-math.pi, math.pi, size=magnitudes.shape)
    true_amplitude = np.full(frame_count, 12.0, dtype=np.float64)
    if isinstance(weak_slice, tuple):
        selected_slice, amplitude = weak_slice
        assert isinstance(selected_slice, slice)
        true_amplitude[selected_slice] = float(amplitude)
    for frame_index, truth_hz in enumerate(truth):
        if math.isfinite(float(truth_hz)):
            _add_gaussian_peak(
                magnitudes[:, frame_index],
                frequency_hz,
                float(truth_hz),
                float(true_amplitude[frame_index]),
            )
    if isinstance(distractor, tuple):
        selected_slice, distractor_hz, amplitude = distractor
        assert isinstance(selected_slice, slice)
        for frame_index in range(*selected_slice.indices(frame_count)):
            _add_gaussian_peak(
                magnitudes[:, frame_index],
                frequency_hz,
                float(distractor_hz),
                float(amplitude),
            )
    spectrum = magnitudes * np.exp(1j * phases)
    stft = STFTResult(
        time_s=np.arange(frame_count, dtype=np.float64) * 2.5e-9,
        frequency_hz=frequency_hz,
        spectrum=np.asarray(spectrum, dtype=np.complex128),
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
    return SyntheticGlobalPathCase(
        case_id=str(case_id),
        description=str(description),
        stft_result=stft,
        truth_frequency_hz=truth,
        pre_event_mask=np.asarray(pre_event_mask, dtype=np.bool_),
        dropout_mask=np.asarray(dropout_mask, dtype=np.bool_),
        wrong_branch_tolerance_hz=100.0e6,
    )


def _add_gaussian_peak(
    magnitudes: FloatArray,
    frequency_hz: FloatArray,
    center_hz: float,
    amplitude: float,
) -> None:
    sigma_hz = 22.0e6
    magnitudes += amplitude * np.exp(
        -0.5 * np.square((frequency_hz - center_hz) / sigma_hz)
    )


def _dropout_recovery_frames(
    case: SyntheticGlobalPathCase,
    selected: BoolArray,
) -> int | None:
    dropout_indices = np.flatnonzero(case.dropout_mask)
    if dropout_indices.size == 0:
        return None
    after = int(dropout_indices[-1]) + 1
    following = np.flatnonzero(selected[after:] & np.isfinite(case.truth_frequency_hz[after:]))
    return int(following[0]) if following.size else -1


def _rank_fractions(ranks: IntArray, selected: BoolArray) -> tuple[float, float, float, float, float]:
    count = ranks.size
    normalized = ranks.copy()
    normalized[~selected] = 0
    return (
        float(np.count_nonzero(normalized == 1) / count),
        float(np.count_nonzero(normalized == 2) / count),
        float(np.count_nonzero(normalized == 3) / count),
        float(np.count_nonzero(normalized >= 4) / count),
        float(np.count_nonzero(normalized == 0) / count),
    )


def _immutable_float(value: object) -> FloatArray:
    array = np.array(value, dtype=np.float64, copy=True, order="C")
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.float64).reshape(array.shape)
    stored.setflags(write=False)
    return stored


def _immutable_int(value: object) -> IntArray:
    array = np.array(value, dtype=np.int64, copy=True, order="C")
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.int64).reshape(array.shape)
    stored.setflags(write=False)
    return stored


def _immutable_bool(value: object) -> BoolArray:
    array = np.array(value, dtype=np.bool_, copy=True, order="C")
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.bool_).reshape(array.shape)
    stored.setflags(write=False)
    return stored


__all__ = [
    "DEFAULT_SYNTHETIC_SEED",
    "DEFAULT_VACUUM_WAVELENGTH_M",
    "RidgeBenchmarkMetrics",
    "SyntheticBenchmarkResult",
    "SyntheticGlobalPathCase",
    "calculate_ridge_metrics",
    "generate_synthetic_global_path_cases",
    "run_synthetic_global_path_benchmark",
]
