"""Pure numerical Top-K extraction and first-order global ridge tracking."""

from __future__ import annotations

import math
from typing import Final

import numpy as np
from scipy.signal import find_peaks  # type: ignore[import-untyped]

from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.global_path_models import (
    GlobalPathConfig,
    GlobalRidgePathResult,
    RidgeCandidate,
    RidgeCandidateSet,
)
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.core.ridge.refinement import refine_three_point_log_magnitude
from dps_studio.core.time_frequency import STFTResult

_NULL_STATE: Final[int] = -1


def extract_global_path_candidates(
    stft_result: STFTResult,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    config: GlobalPathConfig,
) -> RidgeCandidateSet:
    """Extract distinct, weakly gated local maxima from one channel and profile."""
    if not isinstance(stft_result, STFTResult):
        raise RidgeConfigurationError("stft_result must be an STFTResult.")
    if not isinstance(config, GlobalPathConfig):
        raise RidgeConfigurationError("config must be a GlobalPathConfig.")
    minimum = _finite_frequency(minimum_frequency_hz, "minimum_frequency_hz")
    maximum = _finite_frequency(maximum_frequency_hz, "maximum_frequency_hz")
    if maximum <= minimum:
        raise RidgeConfigurationError("maximum_frequency_hz must exceed minimum_frequency_hz.")
    frequency_hz = stft_result.frequency_hz
    if minimum < frequency_hz[0] or maximum > frequency_hz[-1]:
        raise RidgeConfigurationError("Candidate search band must lie within the STFT axis.")
    band_indices = np.flatnonzero((frequency_hz >= minimum) & (frequency_hz <= maximum))
    if band_indices.size < 3:
        raise RidgeConfigurationError("Candidate search band must contain at least three bins.")
    bin_spacing_hz = _uniform_spacing_hz(frequency_hz)
    window_resolution_hz = stft_result.sample_rate_hz / stft_result.window_length_samples
    separation_hz = (
        config.minimum_candidate_separation_hz
        if config.minimum_candidate_separation_hz is not None
        else config.candidate_separation_resolution_factor * window_resolution_hz
    )
    background_guard_hz = (
        config.background_exclusion_half_width_hz
        if config.background_exclusion_half_width_hz is not None
        else config.background_exclusion_resolution_factor * window_resolution_hz
    )
    first_band_index = int(band_indices[0])
    last_band_index = int(band_indices[-1])
    window_duration_s = stft_result.window_length_samples / stft_result.sample_rate_hz
    magnitude = np.abs(stft_result.spectrum)

    frames: list[tuple[RidgeCandidate, ...]] = []
    for frame_index in range(stft_result.time_s.size):
        band_magnitude = magnitude[band_indices, frame_index]
        padded = np.concatenate((np.array([-math.inf]), band_magnitude, np.array([-math.inf])))
        padded_offsets, _ = find_peaks(padded, plateau_size=(1, None))
        local_offsets = [int(value - 1) for value in padded_offsets]
        ranked_offsets = sorted(
            local_offsets,
            key=lambda offset: (-float(band_magnitude[offset]), int(band_indices[offset])),
        )
        retained_offsets: list[int] = []
        for offset in ranked_offsets:
            candidate_frequency_hz = float(frequency_hz[band_indices[offset]])
            if any(
                abs(candidate_frequency_hz - float(frequency_hz[band_indices[other]]))
                < separation_hz
                for other in retained_offsets
            ):
                continue
            retained_offsets.append(offset)
            if len(retained_offsets) == config.top_k:
                break
        frame = tuple(
            _build_candidate(
                stft_result,
                magnitude=magnitude,
                band_indices=band_indices,
                frame_index=frame_index,
                bin_index=int(band_indices[offset]),
                candidate_rank=rank,
                first_band_index=first_band_index,
                last_band_index=last_band_index,
                bin_spacing_hz=bin_spacing_hz,
                window_duration_s=window_duration_s,
                minimum_frequency_hz=minimum,
                maximum_frequency_hz=maximum,
                background_guard_hz=background_guard_hz,
                minimum_background_bin_count=config.minimum_background_bin_count,
            )
            for rank, offset in enumerate(retained_offsets, start=1)
        )
        frames.append(frame)

    return RidgeCandidateSet(
        time_s=stft_result.time_s,
        candidates_by_frame=tuple(frames),
        minimum_frequency_hz=minimum,
        maximum_frequency_hz=maximum,
        effective_candidate_separation_hz=separation_hz,
        effective_background_exclusion_half_width_hz=background_guard_hz,
        config=config,
        source_path=stft_result.source_path,
    )


def candidate_node_cost(candidate: RidgeCandidate, config: GlobalPathConfig) -> float:
    """Return a bounded weighted sum of five independent quality deficits.

    Contrast deficits are clipped linear hinges in ``[0, 1]``. Cycles use the
    same bounded deficit. Boundary and failed-refinement terms are binary.
    Absolute amplitude and plot-relative dB are deliberately absent.
    """
    if not isinstance(candidate, RidgeCandidate) or not isinstance(config, GlobalPathConfig):
        raise RidgeConfigurationError("candidate and config have invalid types.")
    background = _bounded_deficit(
        candidate.peak_to_background_db,
        config.background_reference_db,
        config.background_deficit_scale_db,
    )
    competitor = _bounded_deficit(
        candidate.peak_to_competitor_db,
        config.competitor_reference_db,
        config.competitor_deficit_scale_db,
    )
    cycles = float(
        np.clip(
            (config.target_cycles_in_window - candidate.cycles_in_window)
            / config.target_cycles_in_window,
            0.0,
            1.0,
        )
    )
    return (
        config.background_contrast_weight * background
        + config.competitor_contrast_weight * competitor
        + config.cycles_weight * cycles
        + config.boundary_weight * float(candidate.is_band_boundary)
        + config.refinement_failure_weight
        * float(candidate.refinement_status is not RidgeRefinementStatus.REFINED)
    )


def candidate_transition_cost(
    previous: RidgeCandidate,
    current: RidgeCandidate,
    config: GlobalPathConfig,
) -> float:
    """Return the first-order quadratic frequency-step cost in physical Hz."""
    if not isinstance(previous, RidgeCandidate) or not isinstance(current, RidgeCandidate):
        raise RidgeConfigurationError("Transitions require RidgeCandidate values.")
    if not isinstance(config, GlobalPathConfig):
        raise RidgeConfigurationError("config must be a GlobalPathConfig.")
    normalized_step = (
        abs(current.transition_frequency_hz - previous.transition_frequency_hz)
        / config.frequency_step_scale_hz
    )
    cost = config.continuity_weight * normalized_step * normalized_step
    if not math.isfinite(cost):
        raise RidgeConfigurationError("Candidate transition cost overflowed.")
    return cost


def solve_global_candidate_path(
    candidate_set: RidgeCandidateSet,
    *,
    config: GlobalPathConfig | None = None,
) -> GlobalRidgePathResult:
    """Solve the exact DAG shortest path and backtrack its unique tie-broken path."""
    if not isinstance(candidate_set, RidgeCandidateSet):
        raise RidgeConfigurationError("candidate_set must be a RidgeCandidateSet.")
    resolved_config = candidate_set.config if config is None else config
    if not isinstance(resolved_config, GlobalPathConfig):
        raise RidgeConfigurationError("config must be a GlobalPathConfig.")
    if resolved_config != candidate_set.config:
        raise RidgeConfigurationError("Solver config must match candidate extraction config.")

    frame_states: list[tuple[RidgeCandidate | None, ...]] = [
        (*frame, None) for frame in candidate_set.candidates_by_frame
    ]
    cumulative_by_frame: list[np.ndarray] = []
    predecessor_by_frame: list[np.ndarray] = []
    for frame_index, states in enumerate(frame_states):
        node_costs = np.fromiter(
            (
                resolved_config.null_node_cost
                if state is None
                else candidate_node_cost(state, resolved_config)
                for state in states
            ),
            dtype=np.float64,
            count=len(states),
        )
        if frame_index == 0:
            initial_transition = np.fromiter(
                (
                    resolved_config.null_stay_cost
                    if state is None
                    else resolved_config.ridge_entry_cost
                    for state in states
                ),
                dtype=np.float64,
                count=len(states),
            )
            cumulative_by_frame.append(node_costs + initial_transition)
            predecessor_by_frame.append(np.full(len(states), _NULL_STATE, dtype=np.int64))
            continue

        previous_states = frame_states[frame_index - 1]
        previous_cumulative = cumulative_by_frame[-1]
        cumulative = np.empty(len(states), dtype=np.float64)
        predecessors = np.empty(len(states), dtype=np.int64)
        for state_index, state in enumerate(states):
            alternatives = np.fromiter(
                (
                    previous_cumulative[previous_index]
                    + _transition_cost(previous_state, state, resolved_config)
                    for previous_index, previous_state in enumerate(previous_states)
                ),
                dtype=np.float64,
                count=len(previous_states),
            )
            predecessor = int(np.argmin(alternatives))
            predecessors[state_index] = predecessor
            cumulative[state_index] = node_costs[state_index] + alternatives[predecessor]
        cumulative_by_frame.append(cumulative)
        predecessor_by_frame.append(predecessors)

    selected_state_indices = np.empty(len(frame_states), dtype=np.int64)
    selected_state_indices[-1] = int(np.argmin(cumulative_by_frame[-1]))
    for frame_index in range(len(frame_states) - 1, 0, -1):
        selected_state_indices[frame_index - 1] = predecessor_by_frame[frame_index][
            selected_state_indices[frame_index]
        ]

    frame_count = len(frame_states)
    rank = np.zeros(frame_count, dtype=np.int64)
    discrete_hz = np.full(frame_count, np.nan, dtype=np.float64)
    refined_hz = np.full(frame_count, np.nan, dtype=np.float64)
    is_null = np.ones(frame_count, dtype=np.bool_)
    node = np.empty(frame_count, dtype=np.float64)
    transition = np.empty(frame_count, dtype=np.float64)
    cumulative = np.empty(frame_count, dtype=np.float64)
    for frame_index, selected_index in enumerate(selected_state_indices):
        state = frame_states[frame_index][selected_index]
        if state is None:
            node[frame_index] = resolved_config.null_node_cost
        else:
            rank[frame_index] = state.candidate_rank
            discrete_hz[frame_index] = state.discrete_frequency_hz
            refined_hz[frame_index] = state.refined_frequency_hz
            is_null[frame_index] = False
            node[frame_index] = candidate_node_cost(state, resolved_config)
        if frame_index == 0:
            transition[frame_index] = (
                resolved_config.null_stay_cost
                if state is None
                else resolved_config.ridge_entry_cost
            )
        else:
            previous_state = frame_states[frame_index - 1][
                selected_state_indices[frame_index - 1]
            ]
            transition[frame_index] = _transition_cost(
                previous_state,
                state,
                resolved_config,
            )
        cumulative[frame_index] = cumulative_by_frame[frame_index][selected_index]

    return GlobalRidgePathResult(
        time_s=candidate_set.time_s,
        selected_candidate_rank=rank,
        selected_discrete_frequency_hz=discrete_hz,
        selected_refined_frequency_hz=refined_hz,
        is_null=is_null,
        node_cost=node,
        transition_cost=transition,
        cumulative_cost=cumulative,
        total_path_cost=float(cumulative[-1]),
        candidate_set=candidate_set,
        config=resolved_config,
        provenance={
            "status": GlobalPathConfig.DEVELOPMENT_STATUS,
            "scope": "single profile / single channel",
            "manual_event_reference": "not used",
            "physical_identity": "unreviewed",
        },
    )


def track_global_candidate_path(
    stft_result: STFTResult,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    config: GlobalPathConfig | None = None,
) -> GlobalRidgePathResult:
    """Explicit opt-in convenience API for independent candidate extraction and DP."""
    resolved_config = GlobalPathConfig() if config is None else config
    candidates = extract_global_path_candidates(
        stft_result,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
        config=resolved_config,
    )
    return solve_global_candidate_path(candidates)


def _build_candidate(
    stft_result: STFTResult,
    *,
    magnitude: np.ndarray,
    band_indices: np.ndarray,
    frame_index: int,
    bin_index: int,
    candidate_rank: int,
    first_band_index: int,
    last_band_index: int,
    bin_spacing_hz: float,
    window_duration_s: float,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    background_guard_hz: float,
    minimum_background_bin_count: int,
) -> RidgeCandidate:
    discrete_hz = float(stft_result.frequency_hz[bin_index])
    boundary = bin_index in {
        0,
        stft_result.frequency_hz.size - 1,
        first_band_index,
        last_band_index,
    }
    if 0 < bin_index < stft_result.frequency_hz.size - 1:
        local = magnitude[bin_index - 1 : bin_index + 2, frame_index]
    else:
        local = np.full(3, np.nan, dtype=np.float64)
    refined_hz, _, refinement_status = refine_three_point_log_magnitude(
        left_magnitude=float(local[0]),
        center_magnitude=float(local[1]),
        right_magnitude=float(local[2]),
        discrete_frequency_hz=discrete_hz,
        frequency_spacing_hz=bin_spacing_hz,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
        boundary_peak=boundary,
    )
    peak_amplitude = float(magnitude[bin_index, frame_index])
    retained_background = band_indices[
        np.abs(stft_result.frequency_hz[band_indices] - discrete_hz) > background_guard_hz
    ]
    peak_to_background_db = math.nan
    peak_to_competitor_db = math.nan
    if (
        peak_amplitude > 0.0
        and math.isfinite(peak_amplitude)
        and retained_background.size >= minimum_background_bin_count
    ):
        background_values = magnitude[retained_background, frame_index]
        background = float(np.median(background_values))
        competitor = float(np.max(background_values))
        if math.isfinite(background) and background > 0.0:
            peak_to_background_db = _contrast_db(peak_amplitude, background)
        if math.isfinite(competitor) and competitor > 0.0:
            peak_to_competitor_db = _contrast_db(peak_amplitude, competitor)
    return RidgeCandidate(
        frame_index=frame_index,
        time_s=float(stft_result.time_s[frame_index]),
        candidate_rank=candidate_rank,
        discrete_bin_index=bin_index,
        discrete_frequency_hz=discrete_hz,
        refined_frequency_hz=refined_hz,
        peak_amplitude=peak_amplitude,
        peak_to_background_db=peak_to_background_db,
        peak_to_competitor_db=peak_to_competitor_db,
        cycles_in_window=discrete_hz * window_duration_s,
        is_band_boundary=boundary,
        refinement_status=refinement_status,
    )


def _transition_cost(
    previous: RidgeCandidate | None,
    current: RidgeCandidate | None,
    config: GlobalPathConfig,
) -> float:
    if previous is None and current is None:
        return config.null_stay_cost
    if previous is None:
        return config.ridge_entry_cost
    if current is None:
        return config.ridge_exit_cost
    return candidate_transition_cost(previous, current, config)


def _bounded_deficit(value: float, reference: float, scale: float) -> float:
    if not math.isfinite(value):
        return 1.0
    return float(np.clip((reference - value) / scale, 0.0, 1.0))


def _contrast_db(numerator: float, denominator: float) -> float:
    return 20.0 * (math.log10(numerator) - math.log10(denominator))


def _finite_frequency(value: object, name: str) -> float:
    if isinstance(value, bool):
        raise RidgeConfigurationError(f"{name} must be a finite frequency in Hz.")
    try:
        converted = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(f"{name} must be a finite frequency in Hz.") from exc
    if not math.isfinite(converted) or converted < 0.0:
        raise RidgeConfigurationError(f"{name} must be finite and non-negative.")
    return converted


def _uniform_spacing_hz(frequency_hz: np.ndarray) -> float:
    spacing = np.diff(frequency_hz)
    first = float(spacing[0])
    tolerance = 64.0 * np.finfo(np.float64).eps * max(
        1,
        frequency_hz.size,
    ) * max(1.0, abs(first))
    if not np.all(np.abs(spacing - first) <= tolerance):
        raise RidgeConfigurationError("STFT frequency_hz must be uniformly spaced.")
    return first


__all__ = [
    "candidate_node_cost",
    "candidate_transition_cost",
    "extract_global_path_candidates",
    "solve_global_candidate_path",
    "track_global_candidate_path",
]
