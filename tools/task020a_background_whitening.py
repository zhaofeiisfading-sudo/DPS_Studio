"""Pure numerical helpers for the isolated TASK-020A whitening experiment.

This module is deliberately located under ``tools``.  It is not part of the
``dps_studio`` package or its public production API.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


FloatArray = NDArray[np.float64]


class BackgroundWhiteningError(ValueError):
    """Raised when an auditable background model cannot be constructed."""


@dataclass(frozen=True, slots=True, eq=False)
class SpectralWhiteningResult:
    """Detached, immutable arrays from one frequency-background estimate."""

    time_s: FloatArray
    frequency_hz: FloatArray
    raw_spectral_quantity: FloatArray
    background_frame_mask: NDArray[np.bool_]
    background_frequency_profile: FloatArray
    background_mad_frequency_profile: FloatArray
    whitened_ratio: FloatArray
    background_contrast_db: FloatArray
    epsilon: float
    background_start_s: float
    background_end_s: float


@dataclass(frozen=True, slots=True)
class BackgroundUniformityMetrics:
    """Frequency nonuniformity measured over explicitly selected frames."""

    raw_nonuniformity_db: float
    whitened_nonuniformity_db: float
    reduction_db: float
    definition: str


def compute_frequency_background_whitening(
    raw_spectral_quantity: object,
    *,
    time_s: object,
    frequency_hz: object,
    background_start_s: float,
    background_end_s: float,
    minimum_background_frames: int = 3,
) -> SpectralWhiteningResult:
    """Estimate ``N(f)`` by time-median and return ``P/(N+epsilon)``.

    ``raw_spectral_quantity`` must be a finite, non-negative, linear-scale
    array with shape ``(frequency, time)``.  Non-finite input is rejected
    instead of being ignored.  The closed background interval is explicit.

    ``epsilon`` has the same units as the spectral quantity and is defined as
    ``max(float64.eps * max(N), float64.smallest_subnormal)``.  It is therefore
    deterministic, scale-aware, strictly positive, and contains no
    acquisition-specific tuning constant.
    """
    quantity = _finite_float_array(
        raw_spectral_quantity,
        field_name="raw_spectral_quantity",
        dimensions=2,
    )
    times = _finite_float_array(time_s, field_name="time_s", dimensions=1)
    frequencies = _finite_float_array(
        frequency_hz,
        field_name="frequency_hz",
        dimensions=1,
    )
    if quantity.shape != (frequencies.size, times.size):
        raise BackgroundWhiteningError(
            "raw_spectral_quantity shape must equal (frequency_hz.size, "
            "time_s.size)."
        )
    if np.any(quantity < 0.0):
        raise BackgroundWhiteningError(
            "raw_spectral_quantity must be non-negative on its linear scale."
        )
    if times.size == 0 or frequencies.size == 0:
        raise BackgroundWhiteningError("time_s and frequency_hz must be non-empty.")
    if times.size > 1 and np.any(np.diff(times) <= 0.0):
        raise BackgroundWhiteningError("time_s must be strictly increasing.")
    if frequencies[0] < 0.0 or (
        frequencies.size > 1 and np.any(np.diff(frequencies) <= 0.0)
    ):
        raise BackgroundWhiteningError(
            "frequency_hz must be non-negative and strictly increasing."
        )
    start = _finite_scalar(background_start_s, "background_start_s")
    end = _finite_scalar(background_end_s, "background_end_s")
    if end < start:
        raise BackgroundWhiteningError(
            "background_end_s must be greater than or equal to background_start_s."
        )
    if (
        isinstance(minimum_background_frames, bool)
        or not isinstance(minimum_background_frames, int)
        or minimum_background_frames < 1
    ):
        raise BackgroundWhiteningError(
            "minimum_background_frames must be a positive integer."
        )
    mask = (times >= start) & (times <= end)
    frame_count = int(np.count_nonzero(mask))
    if frame_count == 0:
        raise BackgroundWhiteningError(
            "The explicit background interval contains no STFT frames."
        )
    if frame_count < minimum_background_frames:
        raise BackgroundWhiteningError(
            "The explicit background interval contains "
            f"{frame_count} frames; at least {minimum_background_frames} are required."
        )

    background_samples = quantity[:, mask]
    profile = np.median(background_samples, axis=1)
    mad = np.median(np.abs(background_samples - profile[:, np.newaxis]), axis=1)
    if not np.all(np.isfinite(profile)) or np.any(profile <= 0.0):
        raise BackgroundWhiteningError(
            "The median background profile must be finite and strictly positive "
            "at every frequency bin."
        )
    if not np.all(np.isfinite(mad)) or np.any(mad < 0.0):
        raise BackgroundWhiteningError(
            "The background MAD profile must be finite and non-negative."
        )
    scale = float(np.max(profile))
    float_info = np.finfo(np.float64)
    epsilon = max(float_info.eps * scale, float_info.smallest_subnormal)
    denominator = profile[:, np.newaxis] + epsilon
    if not np.all(np.isfinite(denominator)):
        raise BackgroundWhiteningError(
            "N(f) + epsilon overflowed; whitening was not generated."
        )
    ratio = quantity / denominator
    contrast_db = 10.0 * np.log10((quantity + epsilon) / denominator)
    if not np.all(np.isfinite(ratio)) or not np.all(np.isfinite(contrast_db)):
        raise BackgroundWhiteningError(
            "Whitening produced a non-finite result; no result was returned."
        )
    return SpectralWhiteningResult(
        time_s=_immutable(times),
        frequency_hz=_immutable(frequencies),
        raw_spectral_quantity=_immutable(quantity),
        background_frame_mask=_immutable_bool(mask),
        background_frequency_profile=_immutable(profile),
        background_mad_frequency_profile=_immutable(mad),
        whitened_ratio=_immutable(ratio),
        background_contrast_db=_immutable(contrast_db),
        epsilon=epsilon,
        background_start_s=start,
        background_end_s=end,
    )


def assess_background_uniformity(
    result: SpectralWhiteningResult,
) -> BackgroundUniformityMetrics:
    """Return a robust frequency-spread diagnostic before and after whitening.

    The diagnostic is the 95th-minus-5th percentile spread, in dB, of the
    per-frequency background time median.  It is a nonuniformity diagnostic,
    not a confidence interval and not a calibrated SNR.
    """
    if not isinstance(result, SpectralWhiteningResult):
        raise TypeError("result must be a SpectralWhiteningResult.")
    mask = result.background_frame_mask
    raw_profile = np.median(result.raw_spectral_quantity[:, mask], axis=1)
    whitened_profile = np.median(result.whitened_ratio[:, mask], axis=1)
    raw_db = 10.0 * np.log10(raw_profile)
    whitened_db = 10.0 * np.log10(whitened_profile)
    raw_spread = _percentile_spread(raw_db)
    whitened_spread = _percentile_spread(whitened_db)
    return BackgroundUniformityMetrics(
        raw_nonuniformity_db=raw_spread,
        whitened_nonuniformity_db=whitened_spread,
        reduction_db=raw_spread - whitened_spread,
        definition=(
            "P95-P5 spread across frequency of 10*log10(per-frequency "
            "background time median)"
        ),
    )


def frame_median_contrast_db(
    quantity: object,
    *,
    frequency_hz: object,
    ridge_frequency_hz: object,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> FloatArray:
    """Contrast of ridge-nearest bins to each frame's search-band median.

    Invalid/non-finite ridge locations return NaN.  The input spectrum must be
    finite and strictly positive within the evaluated search band.
    """
    values = _finite_float_array(quantity, field_name="quantity", dimensions=2)
    frequencies = _finite_float_array(
        frequency_hz,
        field_name="frequency_hz",
        dimensions=1,
    )
    ridge = np.array(ridge_frequency_hz, dtype=np.float64, copy=True)
    if ridge.ndim != 1 or values.shape != (frequencies.size, ridge.size):
        raise BackgroundWhiteningError(
            "quantity, frequency_hz, and ridge_frequency_hz shapes are inconsistent."
        )
    minimum = _finite_scalar(minimum_frequency_hz, "minimum_frequency_hz")
    maximum = _finite_scalar(maximum_frequency_hz, "maximum_frequency_hz")
    band_indices = np.flatnonzero(
        (frequencies >= minimum) & (frequencies <= maximum)
    )
    if band_indices.size == 0:
        raise BackgroundWhiteningError("The requested contrast band has no bins.")
    band = values[band_indices]
    if np.any(band <= 0.0):
        raise BackgroundWhiteningError(
            "quantity must be strictly positive in the contrast search band."
        )
    frame_background = np.median(band, axis=0)
    output = np.full(ridge.shape, np.nan, dtype=np.float64)
    for frame_index in np.flatnonzero(np.isfinite(ridge)):
        index = int(frame_index)
        nearest = int(np.argmin(np.abs(frequencies - ridge[index])))
        output[index] = 10.0 * np.log10(
            values[nearest, index] / frame_background[index]
        )
    return _immutable(output)


def _percentile_spread(values: FloatArray) -> float:
    percentiles = np.percentile(values, (5.0, 95.0))
    return float(percentiles[1] - percentiles[0])


def _finite_float_array(
    value: object,
    *,
    field_name: str,
    dimensions: int,
) -> FloatArray:
    try:
        array = np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise BackgroundWhiteningError(
            f"{field_name} must be convertible to float64."
        ) from exc
    if array.ndim != dimensions:
        raise BackgroundWhiteningError(
            f"{field_name} must have {dimensions} dimensions; got {array.ndim}."
        )
    if not np.all(np.isfinite(array)):
        raise BackgroundWhiteningError(
            f"{field_name} must contain only finite values."
        )
    return array


def _finite_scalar(value: object, field_name: str) -> float:
    if isinstance(value, bool):
        raise BackgroundWhiteningError(f"{field_name} must be finite.")
    try:
        converted = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise BackgroundWhiteningError(f"{field_name} must be finite.") from exc
    if not np.isfinite(converted):
        raise BackgroundWhiteningError(f"{field_name} must be finite.")
    return converted


def _immutable(array: FloatArray) -> FloatArray:
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.float64).reshape(
        array.shape
    )
    stored.setflags(write=False)
    return stored


def _immutable_bool(array: NDArray[np.bool_]) -> NDArray[np.bool_]:
    stored = np.frombuffer(array.tobytes(order="C"), dtype=np.bool_).reshape(array.shape)
    stored.setflags(write=False)
    return stored


__all__ = [
    "BackgroundUniformityMetrics",
    "BackgroundWhiteningError",
    "SpectralWhiteningResult",
    "assess_background_uniformity",
    "compute_frequency_background_whitening",
    "frame_median_contrast_db",
]
