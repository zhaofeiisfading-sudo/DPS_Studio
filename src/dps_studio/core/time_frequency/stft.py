"""Single-channel short-time Fourier transform computation."""

from __future__ import annotations

from numbers import Integral

import numpy as np
import scipy.signal  # type: ignore[import-untyped]

from dps_studio.core.models import SignalRecord
from dps_studio.core.time_frequency.exceptions import (
    NonUniformSamplingError,
    STFTComputationError,
    STFTConfigurationError,
)
from dps_studio.core.time_frequency.models import STFTResult
from dps_studio.core.time_frequency.windows import validate_stft_window_name


def compute_stft(
    record: SignalRecord,
    *,
    window_length_samples: int,
    overlap_samples: int,
    nfft: int | None = None,
    window_name: str = "hann",
) -> STFTResult:
    """Compute a reproducible, one-sided STFT for one uniform signal record."""
    if not isinstance(record, SignalRecord):
        raise STFTConfigurationError(
            "record must be a SignalRecord instance; "
            f"got {type(record).__name__}."
        )
    if not record.is_uniformly_sampled:
        source_context = (
            f"; source_path={record.source_path!s}"
            if record.source_path is not None
            else ""
        )
        raise NonUniformSamplingError(
            "Standard discrete STFT requires approximately uniformly sampled data; "
            "record is not approximately uniformly sampled: "
            "maximum_relative_interval_deviation="
            f"{record.maximum_relative_interval_deviation!r}; "
            "uniformity_relative_tolerance="
            f"{record.uniformity_relative_tolerance!r}{source_context}."
        )

    validated_window_length = _validate_window_length(
        window_length_samples,
        sample_count=record.sample_count,
    )
    validated_overlap = _validate_overlap(
        overlap_samples,
        window_length_samples=validated_window_length,
    )
    resolved_nfft = _resolve_nfft(
        nfft,
        window_length_samples=validated_window_length,
    )
    validated_window_name = validate_stft_window_name(window_name)

    try:
        window_array = scipy.signal.get_window(
            validated_window_name,
            validated_window_length,
            fftbins=True,
        )
    except (TypeError, ValueError) as exc:
        raise STFTConfigurationError(
            f"Invalid SciPy window_name {validated_window_name!r}."
        ) from exc

    try:
        frequencies_hz, relative_times_s, spectrum = scipy.signal.stft(
            record.voltage_v,
            fs=record.sample_rate_hz,
            window=window_array,
            nperseg=validated_window_length,
            noverlap=validated_overlap,
            nfft=resolved_nfft,
            detrend=False,
            return_onesided=True,
            boundary=None,
            padded=False,
            scaling="spectrum",
        )
    except Exception as exc:
        raise STFTComputationError(
            "SciPy could not compute the STFT for the validated signal and "
            "configuration."
        ) from exc

    absolute_times_s = record.start_time_s + np.asarray(
        relative_times_s,
        dtype=np.float64,
    )
    return STFTResult(
        time_s=absolute_times_s,
        frequency_hz=np.asarray(frequencies_hz, dtype=np.float64),
        spectrum=np.asarray(spectrum, dtype=np.complex128),
        window_name=validated_window_name,
        window_length_samples=validated_window_length,
        overlap_samples=validated_overlap,
        hop_samples=validated_window_length - validated_overlap,
        nfft=resolved_nfft,
        sample_rate_hz=record.sample_rate_hz,
        source_path=record.source_path,
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )


def _validate_window_length(value: object, *, sample_count: int) -> int:
    window_length = _require_integer(value, field_name="window_length_samples")
    if window_length < 2:
        raise STFTConfigurationError(
            "window_length_samples must be at least 2; "
            f"got {window_length}."
        )
    if window_length > sample_count:
        raise STFTConfigurationError(
            "window_length_samples cannot exceed record.sample_count; "
            f"got {window_length} for {sample_count} samples."
        )
    return window_length


def _validate_overlap(value: object, *, window_length_samples: int) -> int:
    overlap = _require_integer(value, field_name="overlap_samples")
    if overlap < 0 or overlap >= window_length_samples:
        raise STFTConfigurationError(
            "overlap_samples must satisfy 0 <= overlap_samples < "
            f"window_length_samples; got {overlap} for window length "
            f"{window_length_samples}."
        )
    return overlap


def _resolve_nfft(value: object, *, window_length_samples: int) -> int:
    if value is None:
        return window_length_samples
    resolved_nfft = _require_integer(value, field_name="nfft")
    if resolved_nfft < window_length_samples:
        raise STFTConfigurationError(
            "nfft must be greater than or equal to window_length_samples; "
            f"got {resolved_nfft} for window length {window_length_samples}."
        )
    return resolved_nfft


def _require_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise STFTConfigurationError(
            f"{field_name} must be an integer and cannot be bool; got {value!r}."
        )
    return int(value)
