"""Event-aware, I/O-free temporal continuity classification for a ridge."""

from __future__ import annotations

import math

import numpy as np

from dps_studio.core.ridge.continuity_models import (
    EventAwareContinuityConfig,
    EventAwareContinuityResult,
)
from dps_studio.core.ridge.diagnostic_models import RidgeContinuityStatus
from dps_studio.core.ridge.exceptions import RidgeConfigurationError
from dps_studio.core.ridge.models import RefinedRidgeResult


def assess_event_aware_ridge_continuity(
    refined_ridge_result: RefinedRidgeResult,
    *,
    event_reference_time_s: float | None,
    event_reference_source: str | None,
    stft_window_duration_s: float,
    config: EventAwareContinuityConfig,
) -> EventAwareContinuityResult:
    """Classify isolated jumps while exempting windows that contain the event.

    NaN/refinement failures remain gaps. Metrics are calculated only from
    immediately adjacent finite frames, so a gap is never bridged.
    """
    if not isinstance(refined_ridge_result, RefinedRidgeResult):
        raise RidgeConfigurationError(
            "refined_ridge_result must be a RefinedRidgeResult."
        )
    if not isinstance(config, EventAwareContinuityConfig):
        raise RidgeConfigurationError(
            "config must be an EventAwareContinuityConfig."
        )
    if isinstance(stft_window_duration_s, bool):
        raise RidgeConfigurationError(
            "stft_window_duration_s must be finite and strictly positive."
        )
    try:
        window_duration_s = float(stft_window_duration_s)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RidgeConfigurationError(
            "stft_window_duration_s must be finite and strictly positive."
        ) from exc
    if not math.isfinite(window_duration_s) or window_duration_s <= 0.0:
        raise RidgeConfigurationError(
            "stft_window_duration_s must be finite and strictly positive."
        )
    if event_reference_time_s is None:
        event_time_s = None
        if event_reference_source is not None:
            raise RidgeConfigurationError(
                "event_reference_source must be None when event time is None."
            )
    else:
        if isinstance(event_reference_time_s, bool):
            raise RidgeConfigurationError("event_reference_time_s must be finite.")
        try:
            event_time_s = float(event_reference_time_s)
        except (TypeError, ValueError, OverflowError) as exc:
            raise RidgeConfigurationError(
                "event_reference_time_s must be finite."
            ) from exc
        if not math.isfinite(event_time_s):
            raise RidgeConfigurationError("event_reference_time_s must be finite.")
        if not isinstance(event_reference_source, str) or not event_reference_source.strip():
            raise RidgeConfigurationError(
                "event_reference_source must identify the supplied event time."
            )

    time_s = refined_ridge_result.time_s
    frequency_hz = refined_ridge_result.refined_frequency_hz
    frame_count = time_s.size
    delta_previous_hz = np.full(frame_count, np.nan, dtype=np.float64)
    delta_next_hz = np.full(frame_count, np.nan, dtype=np.float64)
    local_slope_hz_per_s = np.full(frame_count, np.nan, dtype=np.float64)
    recovery_hz = np.full(frame_count, np.nan, dtype=np.float64)

    finite = np.isfinite(frequency_hz)
    for index in range(frame_count):
        if index > 0 and finite[index] and finite[index - 1]:
            delta_previous_hz[index] = frequency_hz[index] - frequency_hz[index - 1]
        if index + 1 < frame_count and finite[index] and finite[index + 1]:
            delta_next_hz[index] = frequency_hz[index + 1] - frequency_hz[index]
        if index == 0 or index + 1 >= frame_count:
            continue
        if not (finite[index - 1] and finite[index] and finite[index + 1]):
            continue
        neighbor_interval_s = float(time_s[index + 1] - time_s[index - 1])
        if not math.isfinite(neighbor_interval_s) or neighbor_interval_s <= 0.0:
            raise RidgeConfigurationError(
                "refined ridge time_s must be finite and strictly increasing."
            )
        local_slope_hz_per_s[index] = (
            frequency_hz[index + 1] - frequency_hz[index - 1]
        ) / neighbor_interval_s
        recovery_hz[index] = abs(frequency_hz[index + 1] - frequency_hz[index - 1])

    event_half_support_s = 0.5 * window_duration_s
    boundary_relative_tolerance = 8.0 * np.finfo(np.float64).eps
    statuses: list[RidgeContinuityStatus] = []
    for index in range(frame_count):
        if not finite[index]:
            statuses.append(RidgeContinuityStatus.GAP)
            continue
        event_distance_s = (
            abs(float(time_s[index]) - event_time_s)
            if event_time_s is not None
            else math.inf
        )
        if event_time_s is not None and (
            event_distance_s <= event_half_support_s
            or math.isclose(
                event_distance_s,
                event_half_support_s,
                rel_tol=boundary_relative_tolerance,
                abs_tol=0.0,
            )
        ):
            statuses.append(RidgeContinuityStatus.EVENT_TRANSITION)
            continue
        if index == 0 or index + 1 >= frame_count or not (
            finite[index - 1] and finite[index + 1]
        ):
            statuses.append(RidgeContinuityStatus.INSUFFICIENT_CONTEXT)
            continue
        previous_deviation_hz = abs(float(delta_previous_hz[index]))
        next_deviation_hz = abs(float(delta_next_hz[index]))
        if (
            previous_deviation_hz > config.isolated_jump_threshold_hz
            and next_deviation_hz > config.isolated_jump_threshold_hz
            and recovery_hz[index] <= config.neighbor_recovery_tolerance_hz
        ):
            statuses.append(RidgeContinuityStatus.ISOLATED_JUMP)
        else:
            statuses.append(RidgeContinuityStatus.NORMAL_CONTINUITY)

    return EventAwareContinuityResult(
        time_s=time_s,
        frequency_hz=frequency_hz,
        delta_frequency_from_previous_hz=delta_previous_hz,
        delta_frequency_to_next_hz=delta_next_hz,
        local_frequency_slope_hz_per_s=local_slope_hz_per_s,
        neighbor_recovery_difference_hz=recovery_hz,
        statuses=tuple(statuses),
        event_reference_time_s=event_time_s,
        event_reference_source=event_reference_source,
        stft_window_duration_s=window_duration_s,
        config=config,
        method=EventAwareContinuityResult.METHOD,
        source_path=refined_ridge_result.source_path,
    )


__all__ = ["assess_event_aware_ridge_continuity"]
