"""Finite differences of reconstructed velocity, in SI, without gap bridging."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class VelocityDerivative:
    """Aligned derivative and numerical status (never a confidence estimate)."""

    acceleration_m_s2: FloatArray
    numerical_flags: tuple[str, ...]


def differentiate_velocity(
    time_s: object,
    velocity_m_s: object,
    *,
    valid_mask: object | None = None,
    break_before: object | None = None,
) -> VelocityDerivative:
    """Differentiate each finite, eligible, connected run independently.

    Empty input is valid. Singletons give NaN. Two points share their secant.
    Runs of >=3 points use the nonuniform three-point central formula inside
    and first-order forward/backward secants at the edges. ``break_before[i]``
    cuts the edge i-1 -> i without removing either sample. No sorting, fitting,
    smoothing, resampling or interpolation takes place.
    """
    time = np.asarray(time_s, dtype=np.float64)
    velocity = np.asarray(velocity_m_s, dtype=np.float64)
    if time.ndim != 1 or velocity.ndim != 1 or time.shape != velocity.shape:
        raise ValueError("time_s and velocity_m_s must be aligned 1D arrays.")
    if not np.all(np.isfinite(time)) or np.any(np.diff(time) <= 0.0):
        raise ValueError("time_s must be finite and strictly increasing.")

    def boolean_axis(value: object | None, default: bool) -> NDArray[np.bool_]:
        if value is None:
            return np.full(time.shape, default, dtype=np.bool_)
        array = np.asarray(value)
        if array.shape != time.shape or array.dtype != np.bool_:
            raise ValueError("Masks must be boolean arrays aligned with time_s.")
        return array.copy()

    eligible = boolean_axis(valid_mask, True) & np.isfinite(velocity)
    breaks = boolean_axis(break_before, False)
    output = np.full(time.shape, np.nan, dtype=np.float64)
    flags = ["invalid_or_masked" if not value else "insufficient_points" for value in eligible]
    index = 0
    while index < time.size:
        if not eligible[index]:
            index += 1
            continue
        end = index + 1
        while end < time.size and eligible[end] and not breaks[end]:
            end += 1
        count = end - index
        if count >= 2:
            # np.gradient(edge_order=1) uses actual coordinates and the
            # nonuniform three-point central formula; edges are secants.
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                output[index:end] = np.gradient(velocity[index:end], time[index:end], edge_order=1)
            flags[index:end] = ["central_nonuniform"] * count
            flags[index] = flags[end - 1] = "one_sided_secant"
        index = end
    for invalid_index in np.flatnonzero(~np.isfinite(output) & eligible):
        index = int(invalid_index)
        if flags[index] != "insufficient_points":
            flags[index] = "nonfinite_derivative"
            output[index] = np.nan
    output.setflags(write=False)
    return VelocityDerivative(output, tuple(flags))


def local_linear_acceleration(
    time_s: object,
    velocity_m_s: object,
    *,
    window_s: float,
    valid_mask: object | None = None,
    break_before: object | None = None,
) -> VelocityDerivative:
    """Unweighted local least-squares slope within a full-width time window.

    At least three connected eligible samples are required. Windows truncate
    at segment edges (flagged), never shift or bridge gaps. Actual, centered
    time coordinates support irregular sampling without changing the velocity.
    This is an optional estimator, not a temporal-resolution improvement.
    """
    if not np.isfinite(window_s) or window_s <= 0:
        raise ValueError("window_s must be finite and positive.")
    raw = differentiate_velocity(time_s, velocity_m_s,
                                 valid_mask=valid_mask, break_before=break_before)
    time = np.asarray(time_s, dtype=np.float64)
    velocity = np.asarray(velocity_m_s, dtype=np.float64)
    eligible = np.array([flag != "invalid_or_masked" for flag in raw.numerical_flags])
    breaks = np.zeros(time.size, dtype=bool) if break_before is None else np.asarray(break_before)
    output = np.full(time.shape, np.nan, dtype=np.float64)
    flags = ["insufficient_points" if value else "invalid_or_masked" for value in eligible]
    start = 0
    while start < time.size:
        if not eligible[start]:
            start += 1
            continue
        end = start + 1
        while end < time.size and eligible[end] and not breaks[end]:
            end += 1
        segment_time = time[start:end] - time[start]
        half = window_s / 2
        # Include samples on the nominal boundary consistently after subtracting
        # an absolute experiment time. This tolerance is only floating-point
        # roundoff, not an extension by a frame or an inferred gap policy.
        tolerance = 8 * np.finfo(np.float64).eps * max(
            float(np.max(np.abs(time[start:end]))), window_s,
        )
        left_edges = np.searchsorted(segment_time, segment_time - half - tolerance, side="left")
        right_edges = np.searchsorted(segment_time, segment_time + half + tolerance, side="right")
        for offset, center in enumerate(segment_time):
            left, right = left_edges[offset], right_edges[offset]
            if right - left < 3:
                continue
            x = (segment_time[left:right] - center) / window_s
            x = x - x.mean()
            y = velocity[start + left:start + right]
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                delta = y - y[0]
                slope = float(np.dot(x, delta - delta.mean()) / np.dot(x, x) / window_s)
            index = start + offset
            if not np.isfinite(slope):
                flags[index] = "nonfinite_derivative"
                continue
            output[index] = slope
            truncated = (center - half < -tolerance
                         or center + half > segment_time[-1] + tolerance)
            flags[index] = "local_linear_truncated" if truncated else "local_linear"
        start = end
    output.setflags(write=False)
    return VelocityDerivative(output, tuple(flags))
