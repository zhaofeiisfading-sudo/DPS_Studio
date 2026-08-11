"""Explicit time-coordinate construction for formal result exports."""

from __future__ import annotations

import math
from numbers import Real

import numpy as np
from numpy.typing import NDArray


FloatArray = NDArray[np.float64]


def event_relative_time_s(
    absolute_time_s: object,
    event_reference_time_s: float | None,
) -> FloatArray:
    """Return ``absolute_time_s - event_reference_time_s`` in SI seconds.

    When no formal event reference exists, an equally shaped all-NaN array is
    returned.  This lets diagnostic exports retain an explicit relative-time
    column without silently adopting an automatic candidate.
    """
    try:
        absolute = np.array(absolute_time_s, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("absolute_time_s must be convertible to float64.") from exc
    if absolute.ndim != 1:
        raise ValueError("absolute_time_s must be one-dimensional.")
    if not np.all(np.isfinite(absolute)):
        raise ValueError("absolute_time_s must contain only finite values.")
    if event_reference_time_s is None:
        return np.full(absolute.shape, np.nan, dtype=np.float64)
    if isinstance(event_reference_time_s, bool) or not isinstance(
        event_reference_time_s, Real
    ):
        raise TypeError("event_reference_time_s must be finite or None.")
    reference = float(event_reference_time_s)
    if not math.isfinite(reference):
        raise ValueError("event_reference_time_s must be finite or None.")
    return np.asarray(absolute - reference, dtype=np.float64)


__all__ = ["event_relative_time_s"]
