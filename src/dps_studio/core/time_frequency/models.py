"""Immutable results produced by time-frequency analysis."""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Integral
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from dps_studio.core.time_frequency.exceptions import STFTConfigurationError


FloatArray = NDArray[np.float64]
ComplexArray = NDArray[np.complex128]


@dataclass(frozen=True, slots=True, eq=False)
class STFTResult:
    """Reproducible one-sided STFT coefficients and their physical axes."""

    time_s: FloatArray
    frequency_hz: FloatArray
    spectrum: ComplexArray
    window_name: str
    window_length_samples: int
    overlap_samples: int
    hop_samples: int
    nfft: int
    sample_rate_hz: float
    source_path: Path | None
    scaling: str
    is_one_sided: bool
    detrend_applied: bool
    boundary_padding_applied: bool

    def __post_init__(self) -> None:
        """Validate result invariants and detach arrays into immutable buffers."""
        time_s = _as_float64_array(self.time_s, field_name="time_s")
        frequency_hz = _as_float64_array(
            self.frequency_hz,
            field_name="frequency_hz",
        )
        spectrum = _as_complex128_array(self.spectrum, field_name="spectrum")

        if time_s.ndim != 1:
            raise STFTConfigurationError(
                f"time_s must be one-dimensional; got shape {time_s.shape}."
            )
        if frequency_hz.ndim != 1:
            raise STFTConfigurationError(
                "frequency_hz must be one-dimensional; "
                f"got shape {frequency_hz.shape}."
            )
        if spectrum.ndim != 2:
            raise STFTConfigurationError(
                f"spectrum must be two-dimensional; got shape {spectrum.shape}."
            )
        if time_s.size == 0 or frequency_hz.size == 0:
            raise STFTConfigurationError(
                "time_s and frequency_hz must each contain at least one value."
            )
        expected_shape = (frequency_hz.size, time_s.size)
        if spectrum.shape != expected_shape:
            raise STFTConfigurationError(
                f"spectrum shape must be {expected_shape}; got {spectrum.shape}."
            )
        if not np.all(np.isfinite(time_s)):
            raise STFTConfigurationError("time_s must contain only finite values.")
        if not np.all(np.isfinite(frequency_hz)):
            raise STFTConfigurationError(
                "frequency_hz must contain only finite values."
            )
        if not np.all(np.isfinite(spectrum)):
            raise STFTConfigurationError("spectrum must contain only finite values.")
        if time_s.size > 1 and not np.all(np.diff(time_s) > 0.0):
            raise STFTConfigurationError("time_s must be strictly increasing.")
        if frequency_hz[0] < 0.0 or (
            frequency_hz.size > 1
            and not np.all(np.diff(frequency_hz) > 0.0)
        ):
            raise STFTConfigurationError(
                "frequency_hz must be non-negative and strictly increasing."
            )

        _validate_reproducibility_metadata(self)

        object.__setattr__(self, "time_s", _store_float64_immutable(time_s))
        object.__setattr__(
            self,
            "frequency_hz",
            _store_float64_immutable(frequency_hz),
        )
        object.__setattr__(
            self,
            "spectrum",
            _store_complex128_immutable(spectrum),
        )


def _as_float64_array(value: object, *, field_name: str) -> FloatArray:
    try:
        return np.array(value, dtype=np.float64, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise STFTConfigurationError(
            f"{field_name} could not be converted to a float64 array."
        ) from exc


def _as_complex128_array(value: object, *, field_name: str) -> ComplexArray:
    try:
        return np.array(value, dtype=np.complex128, copy=True, order="C")
    except (TypeError, ValueError, OverflowError) as exc:
        raise STFTConfigurationError(
            f"{field_name} could not be converted to a complex128 array."
        ) from exc


def _store_float64_immutable(array: FloatArray) -> FloatArray:
    immutable_buffer = array.tobytes(order="C")
    stored = np.frombuffer(immutable_buffer, dtype=np.float64).reshape(array.shape)
    stored.setflags(write=False)
    return stored


def _store_complex128_immutable(array: ComplexArray) -> ComplexArray:
    immutable_buffer = array.tobytes(order="C")
    stored = np.frombuffer(immutable_buffer, dtype=np.complex128).reshape(array.shape)
    stored.setflags(write=False)
    return stored


def _validate_reproducibility_metadata(result: STFTResult) -> None:
    if not isinstance(result.window_name, str) or not result.window_name.strip():
        raise STFTConfigurationError("window_name must be a non-empty string.")
    window_length = _require_integer(
        result.window_length_samples,
        field_name="window_length_samples",
    )
    overlap = _require_integer(result.overlap_samples, field_name="overlap_samples")
    hop = _require_integer(result.hop_samples, field_name="hop_samples")
    nfft = _require_integer(result.nfft, field_name="nfft")
    if window_length < 2:
        raise STFTConfigurationError("window_length_samples must be at least 2.")
    if overlap < 0 or overlap >= window_length:
        raise STFTConfigurationError(
            "overlap_samples must satisfy 0 <= overlap_samples < "
            "window_length_samples."
        )
    if hop != window_length - overlap:
        raise STFTConfigurationError(
            "hop_samples must equal window_length_samples - overlap_samples."
        )
    if nfft < window_length:
        raise STFTConfigurationError(
            "nfft must be greater than or equal to window_length_samples."
        )
    if isinstance(result.sample_rate_hz, bool):
        raise STFTConfigurationError("sample_rate_hz must be finite and positive.")
    try:
        sample_rate_hz = float(result.sample_rate_hz)
    except (TypeError, ValueError, OverflowError) as exc:
        raise STFTConfigurationError(
            "sample_rate_hz must be finite and positive."
        ) from exc
    if not math.isfinite(sample_rate_hz) or sample_rate_hz <= 0.0:
        raise STFTConfigurationError("sample_rate_hz must be finite and positive.")
    if result.source_path is not None and not isinstance(result.source_path, Path):
        raise STFTConfigurationError("source_path must be pathlib.Path or None.")
    if result.scaling != "spectrum":
        raise STFTConfigurationError("scaling must be 'spectrum'.")
    if result.is_one_sided is not True:
        raise STFTConfigurationError("is_one_sided must be True.")
    if result.detrend_applied is not False:
        raise STFTConfigurationError("detrend_applied must be False.")
    if result.boundary_padding_applied is not False:
        raise STFTConfigurationError("boundary_padding_applied must be False.")


def _require_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise STFTConfigurationError(f"{field_name} must be an integer and cannot be bool.")
    return int(value)
