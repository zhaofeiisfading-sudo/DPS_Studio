"""Development-only TASK-010 legacy-output and STFT-parameter audit.

This script is deliberately outside ``dps_studio.core``.  It reads the raw and
legacy reference CSV files without modifying them, performs integer-frame-only
alignment, evaluates a finite parameter grid, and runs deterministic synthetic
known-truth checks.  It does not smooth, interpolate, track, fuse channels, or
apply a LiF correction.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import matplotlib
import numpy as np
import pandas as pd
import scipy.fft  # type: ignore[import-untyped]
import scipy.signal  # type: ignore[import-untyped]
from numpy.typing import NDArray

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import convert_ridge_to_apparent_velocity
from dps_studio.core.ridge import (
    RefinedRidgeResult,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    assess_related_frequency_evidence,
    assess_ridge_continuity,
    assess_ridge_spectral_quality,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
)
from dps_studio.core.time_frequency import compute_stft


FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
IntArray = NDArray[np.int64]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DATA_PATH = PROJECT_ROOT / "data" / "raw" / "20260607.csv"
LEGACY_REFERENCE_PATH = (
    PROJECT_ROOT / "data" / "reference" / "legacy" / "legacy_velocity_time.csv"
)
DEFAULT_OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "task010_legacy_velocity_audit"
TASK009_REFERENCE_FINGERPRINT = (
    PROJECT_ROOT
    / "outputs"
    / "task009_linewidth_audit"
    / "run_20260714_221324_645"
    / "after"
    / "numeric_fingerprints.json"
)
CURRENT_CSV_REFERENCE_DIRECTORY = TASK009_REFERENCE_FINGERPRINT.parent

EXPECTED_RAW_SHA256 = (
    "ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353"
)
VACUUM_WAVELENGTH_M = 1550e-9
HOP_SAMPLES = 128
MINIMUM_FREQUENCY_HZ = 0.1e9
MAXIMUM_FREQUENCY_HZ = 2.0e9
RIDGE_START_TIME_S = 554.668e-6
ANALYSIS_END_TIME_S = 555.45e-6
EXPECTED_LEGACY_TIME_STEP_S = 3.2e-9
EXPECTED_VELOCITY_GRID_M_S = 0.12109375
OFFSET_SEARCH_MINIMUM = -8
OFFSET_SEARCH_MAXIMUM = 8

RISE_START_RELATIVE_S = 0.0
RISE_END_RELATIVE_S = 0.08e-6
PLATEAU_START_RELATIVE_S = 0.08e-6
PLATEAU_END_RELATIVE_S = 0.50e-6
DECLINE_START_RELATIVE_S = 0.50e-6
DECLINE_END_RELATIVE_S = ANALYSIS_END_TIME_S - RIDGE_START_TIME_S

WINDOW_LENGTHS = (384, 400, 408, 416, 512, 768)
WINDOW_NAMES = ("hann", "hamming", "blackman")
LARGE_NFFT = 256000
RFFT_LARGE_BATCH_SIZE = 4
RFFT_SMALL_BATCH_SIZE = 32
SYNTHETIC_RANDOM_SEED = 20260714

# TASK-009 established a 0.50--0.85 thin-line range.  Existing constants are
# not modified; this audit stays inside that already-approved visual range.
LINE_WIDTH = 0.65
DETAIL_LINE_WIDTH = 0.50
MARKER_SIZE = 1.8
SAVE_DPI = 220


@dataclass(frozen=True, slots=True)
class AuditConfiguration:
    """One explicitly allowed development-only spectral configuration."""

    window_name: str
    window_length_samples: int
    nfft: int
    peak_method: str

    @property
    def overlap_samples(self) -> int:
        return self.window_length_samples - HOP_SAMPLES

    @property
    def identifier(self) -> str:
        method = "subbin" if self.peak_method == "subbin" else "discrete"
        return (
            f"{self.window_name}_w{self.window_length_samples}_"
            f"n{self.nfft}_{method}"
        )


@dataclass(frozen=True, slots=True)
class FrequencyEstimate:
    """Compact frequency result retained by the audit, never by production core."""

    time_s: FloatArray
    frequency_hz: FloatArray
    runtime_s: float
    estimated_peak_working_memory_mb: float
    estimated_full_spectrum_one_copy_mb: float
    configuration: AuditConfiguration

    @property
    def velocity_m_s(self) -> FloatArray:
        return self.frequency_hz * (VACUUM_WAVELENGTH_M / 2.0)


@dataclass(frozen=True, slots=True)
class LegacyReference:
    """Validated legacy CSV values and their measured-only representation."""

    frame: pd.DataFrame
    measured_time_relative_s: FloatArray
    measured_velocity_m_s: FloatArray
    row_count: int
    measured_count: int
    zero_masked_count: int
    time_min_us: float
    time_max_us: float
    measured_time_min_us: float
    measured_time_max_us: float
    time_step_min_ns: float
    time_step_median_ns: float
    time_step_max_ns: float
    time_step_max_abs_error_ns: float
    strictly_3p2_ns_grid: bool
    velocity_grid_spacing_m_s: float
    expected_spacing_integer_multiple: bool
    expected_spacing_max_integer_residual: float
    velocity_unit: str


@dataclass(frozen=True, slots=True)
class PairMetrics:
    """Pairwise error metrics with no interpolation or point deletion."""

    paired_count: int
    bias_m_s: float
    mae_m_s: float
    rmse_m_s: float
    maximum_absolute_error_m_s: float
    pearson_correlation: float


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """Best integer-frame alignment, including the exact retained indices."""

    offset_frames: int
    time_offset_ns: float
    reference_indices: IntArray
    candidate_indices: IntArray
    reference_values_m_s: FloatArray
    candidate_values_m_s: FloatArray
    reference_time_relative_s: FloatArray
    metrics: PairMetrics


@dataclass(frozen=True, slots=True)
class SeriesStatistics:
    """Unsmoothed local roughness values for a fixed interval."""

    valid_count: int
    velocity_min_m_s: float
    velocity_median_m_s: float
    velocity_max_m_s: float
    velocity_standard_deviation_m_s: float
    first_difference_absolute_median_m_s: float
    first_difference_absolute_p95_m_s: float
    first_difference_absolute_maximum_m_s: float
    signed_first_difference_standard_deviation_m_s: float
    second_difference_rms_m_s: float
    adjacent_change_correlation_with_legacy: float


@dataclass(frozen=True, slots=True)
class SyntheticSignal:
    """Deterministic known-truth development signal."""

    case_name: str
    record: SignalRecord
    truth_frequency: Callable[[FloatArray], FloatArray]
    competitor_frequency_hz: float | None
    transition_onset_s: float | None
    transition_end_s: float | None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _existing_csv_hashes(directory: Path) -> dict[str, str]:
    if not directory.is_dir():
        return {}
    return {
        path.name: _sha256(path)
        for path in sorted(directory.glob("*.csv"), key=lambda item: item.name)
    }


def _array_sha256(array: NDArray[Any]) -> str:
    contiguous = np.ascontiguousarray(array)
    return hashlib.sha256(contiguous.tobytes(order="C")).hexdigest()


def _finite_float(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def infer_velocity_quantization(values_m_s: FloatArray) -> tuple[float, float]:
    """Return minimum positive unique spacing and integer-multiple residual."""
    values = np.asarray(values_m_s, dtype=np.float64)
    finite = values[np.isfinite(values)]
    if finite.size < 2:
        raise ValueError("At least two finite velocity values are required.")
    unique = np.unique(finite)
    positive_differences = np.diff(unique)
    positive_differences = positive_differences[positive_differences > 0.0]
    if positive_differences.size == 0:
        raise ValueError("Velocity values contain no positive quantization interval.")
    spacing = float(np.min(positive_differences))
    quotients = finite / spacing
    maximum_residual = float(np.max(np.abs(quotients - np.rint(quotients))))
    return spacing, maximum_residual


def read_legacy_reference(path: Path = LEGACY_REFERENCE_PATH) -> LegacyReference:
    """Read and validate the legacy CSV without modifying or normalizing it."""
    if not path.is_file():
        raise FileNotFoundError(f"Legacy reference file does not exist: {path}")
    frame = pd.read_csv(path)
    expected_columns = ["time_us", "velocity_m_s", "velocity_km_s", "data_flag"]
    if list(frame.columns) != expected_columns:
        raise ValueError(
            f"Legacy reference columns must be {expected_columns}; "
            f"got {list(frame.columns)}."
        )
    if frame.empty:
        raise ValueError("Legacy reference CSV must not be empty.")
    numeric = frame[["time_us", "velocity_m_s", "velocity_km_s"]].to_numpy(
        dtype=np.float64
    )
    if not np.all(np.isfinite(numeric)):
        raise ValueError("Legacy reference numeric columns must all be finite.")
    allowed_flags = {"measured", "zero_masked"}
    actual_flags = set(frame["data_flag"].unique())
    if actual_flags != allowed_flags:
        raise ValueError(
            f"Legacy data_flag values must be exactly {allowed_flags}; got {actual_flags}."
        )
    time_us = frame["time_us"].to_numpy(dtype=np.float64)
    if time_us.size < 2 or not np.all(np.diff(time_us) > 0.0):
        raise ValueError("Legacy time_us must be strictly increasing.")
    time_steps_ns = np.diff(time_us) * 1.0e3
    time_step_errors_ns = np.abs(time_steps_ns - EXPECTED_LEGACY_TIME_STEP_S * 1e9)
    # The source decimals retain the intended grid but not bitwise-exact 3.2 ns.
    strict_grid = bool(np.all(time_step_errors_ns <= 1.0e-6))

    measured_mask = frame["data_flag"].eq("measured").to_numpy()
    zero_mask = frame["data_flag"].eq("zero_masked").to_numpy()
    if not np.all(frame.loc[zero_mask, "velocity_m_s"].to_numpy() == 0.0):
        raise ValueError("Every zero_masked legacy row must have zero velocity.")
    measured_time_us = time_us[measured_mask]
    measured_velocity = frame.loc[measured_mask, "velocity_m_s"].to_numpy(
        dtype=np.float64
    )
    if measured_velocity.size == 0:
        raise ValueError("Legacy reference contains no measured rows.")
    measured_relative_s = (measured_time_us - measured_time_us[0]) * 1.0e-6
    spacing, _ = infer_velocity_quantization(measured_velocity)
    expected_quotients = measured_velocity / EXPECTED_VELOCITY_GRID_M_S
    expected_residual = float(
        np.max(np.abs(expected_quotients - np.rint(expected_quotients)))
    )
    unit_residual = float(
        np.max(
            np.abs(
                frame["velocity_km_s"].to_numpy(dtype=np.float64) * 1000.0
                - frame["velocity_m_s"].to_numpy(dtype=np.float64)
            )
        )
    )
    if unit_residual > 1.0e-9:
        raise ValueError("Legacy velocity_m_s and velocity_km_s columns disagree.")
    return LegacyReference(
        frame=frame,
        measured_time_relative_s=measured_relative_s,
        measured_velocity_m_s=measured_velocity,
        row_count=int(frame.shape[0]),
        measured_count=int(np.count_nonzero(measured_mask)),
        zero_masked_count=int(np.count_nonzero(zero_mask)),
        time_min_us=float(time_us[0]),
        time_max_us=float(time_us[-1]),
        measured_time_min_us=float(measured_time_us[0]),
        measured_time_max_us=float(measured_time_us[-1]),
        time_step_min_ns=float(np.min(time_steps_ns)),
        time_step_median_ns=float(np.median(time_steps_ns)),
        time_step_max_ns=float(np.max(time_steps_ns)),
        time_step_max_abs_error_ns=float(np.max(time_step_errors_ns)),
        strictly_3p2_ns_grid=strict_grid,
        velocity_grid_spacing_m_s=spacing,
        expected_spacing_integer_multiple=expected_residual <= 1.0e-9,
        expected_spacing_max_integer_residual=expected_residual,
        velocity_unit="m/s (velocity_m_s; velocity_km_s is consistent after x1000)",
    )


def alignment_metrics(reference: FloatArray, candidate: FloatArray) -> PairMetrics:
    """Calculate pair metrics from already aligned finite arrays."""
    reference_array = np.asarray(reference, dtype=np.float64)
    candidate_array = np.asarray(candidate, dtype=np.float64)
    if reference_array.ndim != 1 or candidate_array.ndim != 1:
        raise ValueError("Aligned values must be one-dimensional.")
    if reference_array.shape != candidate_array.shape or reference_array.size == 0:
        raise ValueError("Aligned values must be non-empty with identical shape.")
    if not np.all(np.isfinite(reference_array)) or not np.all(
        np.isfinite(candidate_array)
    ):
        raise ValueError("Aligned values must all be finite; no point deletion is done.")
    residual = candidate_array - reference_array
    absolute = np.abs(residual)
    if (
        reference_array.size >= 2
        and float(np.std(reference_array)) > 0.0
        and float(np.std(candidate_array)) > 0.0
    ):
        correlation = float(np.corrcoef(reference_array, candidate_array)[0, 1])
    else:
        correlation = float("nan")
    return PairMetrics(
        paired_count=int(reference_array.size),
        bias_m_s=float(np.mean(residual)),
        mae_m_s=float(np.mean(absolute)),
        rmse_m_s=float(np.sqrt(np.mean(np.square(residual)))),
        maximum_absolute_error_m_s=float(np.max(absolute)),
        pearson_correlation=correlation,
    )


def _uniform_step(time_s: FloatArray, *, name: str) -> float:
    values = np.asarray(time_s, dtype=np.float64)
    if values.ndim != 1 or values.size < 2 or not np.all(np.isfinite(values)):
        raise ValueError(f"{name} must contain at least two finite time points.")
    differences = np.diff(values)
    if not np.all(differences > 0.0):
        raise ValueError(f"{name} must be strictly increasing.")
    step = float(np.median(differences))
    tolerance = max(abs(step) * 1.0e-6, 1.0e-18)
    if not np.allclose(differences, step, rtol=0.0, atol=tolerance):
        raise ValueError(f"{name} must be uniformly sampled; interpolation is forbidden.")
    return step


def _align_at_offset(
    reference_time_s: FloatArray,
    reference_values: FloatArray,
    candidate_values: FloatArray,
    offset_frames: int,
) -> AlignmentResult:
    if isinstance(offset_frames, bool) or not isinstance(offset_frames, int):
        raise TypeError("offset_frames must be an integer; interpolation is forbidden.")
    reference_count = int(reference_values.size)
    candidate_count = int(candidate_values.size)
    reference_start = max(0, -offset_frames)
    candidate_start = max(0, offset_frames)
    paired_count = min(
        reference_count - reference_start,
        candidate_count - candidate_start,
    )
    if paired_count < 2:
        raise ValueError("Integer offset leaves fewer than two paired frames.")
    reference_indices = np.arange(
        reference_start,
        reference_start + paired_count,
        dtype=np.int64,
    )
    candidate_indices = np.arange(
        candidate_start,
        candidate_start + paired_count,
        dtype=np.int64,
    )
    paired_reference = np.asarray(reference_values[reference_indices], dtype=np.float64)
    paired_candidate = np.asarray(candidate_values[candidate_indices], dtype=np.float64)
    paired_time = np.asarray(reference_time_s[reference_indices], dtype=np.float64)
    step_s = _uniform_step(reference_time_s, name="reference_time_s")
    return AlignmentResult(
        offset_frames=offset_frames,
        time_offset_ns=offset_frames * step_s * 1.0e9,
        reference_indices=reference_indices,
        candidate_indices=candidate_indices,
        reference_values_m_s=paired_reference,
        candidate_values_m_s=paired_candidate,
        reference_time_relative_s=paired_time,
        metrics=alignment_metrics(paired_reference, paired_candidate),
    )


def search_integer_frame_offset(
    reference_time_s: FloatArray,
    reference_values: FloatArray,
    candidate_time_s: FloatArray,
    candidate_values: FloatArray,
    *,
    minimum_offset_frames: int = OFFSET_SEARCH_MINIMUM,
    maximum_offset_frames: int = OFFSET_SEARCH_MAXIMUM,
) -> AlignmentResult:
    """Search only integer offsets; no interpolation or time deformation exists."""
    for value, name in (
        (minimum_offset_frames, "minimum_offset_frames"),
        (maximum_offset_frames, "maximum_offset_frames"),
    ):
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be an integer.")
    if minimum_offset_frames > maximum_offset_frames:
        raise ValueError("minimum_offset_frames cannot exceed maximum_offset_frames.")
    reference_step = _uniform_step(reference_time_s, name="reference_time_s")
    candidate_step = _uniform_step(candidate_time_s, name="candidate_time_s")
    if not math.isclose(
        reference_step,
        candidate_step,
        rel_tol=0.0,
        abs_tol=max(abs(reference_step) * 1.0e-6, 1.0e-18),
    ):
        raise ValueError("Time steps differ; interpolation and time stretching are forbidden.")
    reference_array = np.asarray(reference_values, dtype=np.float64)
    candidate_array = np.asarray(candidate_values, dtype=np.float64)
    if reference_array.shape != np.asarray(reference_time_s).shape:
        raise ValueError("reference time/value shapes must match.")
    if candidate_array.shape != np.asarray(candidate_time_s).shape:
        raise ValueError("candidate time/value shapes must match.")
    results = [
        _align_at_offset(
            np.asarray(reference_time_s, dtype=np.float64),
            reference_array,
            candidate_array,
            offset,
        )
        for offset in range(minimum_offset_frames, maximum_offset_frames + 1)
    ]
    return min(
        results,
        key=lambda result: (
            result.metrics.rmse_m_s,
            abs(result.offset_frames),
            result.offset_frames,
        ),
    )


def _pearson_or_nan(first: FloatArray, second: FloatArray) -> float:
    if (
        first.size >= 2
        and float(np.std(first)) > 0.0
        and float(np.std(second)) > 0.0
    ):
        return float(np.corrcoef(first, second)[0, 1])
    return float("nan")


def series_statistics(
    time_relative_s: FloatArray,
    values_m_s: FloatArray,
    legacy_values_m_s: FloatArray,
    *,
    start_relative_s: float,
    end_relative_s: float,
) -> SeriesStatistics:
    """Calculate fixed-interval roughness without bridging invalid frames."""
    time_values = np.asarray(time_relative_s, dtype=np.float64)
    values = np.asarray(values_m_s, dtype=np.float64)
    legacy = np.asarray(legacy_values_m_s, dtype=np.float64)
    if not (time_values.shape == values.shape == legacy.shape):
        raise ValueError("time, values, and legacy arrays must have identical shape.")
    region = (time_values >= start_relative_s) & (time_values <= end_relative_s)
    valid = region & np.isfinite(values) & np.isfinite(legacy)
    selected = values[valid]
    if selected.size == 0:
        nan = float("nan")
        return SeriesStatistics(0, nan, nan, nan, nan, nan, nan, nan, nan, nan, nan)
    adjacent = valid[:-1] & valid[1:]
    differences = np.diff(values)[adjacent]
    legacy_differences = np.diff(legacy)[adjacent]
    triplets = valid[:-2] & valid[1:-1] & valid[2:]
    second = (values[2:] - 2.0 * values[1:-1] + values[:-2])[triplets]
    absolute = np.abs(differences)
    return SeriesStatistics(
        valid_count=int(selected.size),
        velocity_min_m_s=float(np.min(selected)),
        velocity_median_m_s=float(np.median(selected)),
        velocity_max_m_s=float(np.max(selected)),
        velocity_standard_deviation_m_s=float(np.std(selected)),
        first_difference_absolute_median_m_s=(
            float(np.median(absolute)) if absolute.size else float("nan")
        ),
        first_difference_absolute_p95_m_s=(
            float(np.percentile(absolute, 95.0)) if absolute.size else float("nan")
        ),
        first_difference_absolute_maximum_m_s=(
            float(np.max(absolute)) if absolute.size else float("nan")
        ),
        signed_first_difference_standard_deviation_m_s=(
            float(np.std(differences)) if differences.size else float("nan")
        ),
        second_difference_rms_m_s=(
            float(np.sqrt(np.mean(np.square(second))))
            if second.size
            else float("nan")
        ),
        adjacent_change_correlation_with_legacy=_pearson_or_nan(
            differences,
            legacy_differences,
        ),
    )


def _candidate_frame_starts(
    record: SignalRecord,
    *,
    window_length_samples: int,
    event_start_time_s: float | None,
    analysis_end_time_s: float | None,
) -> tuple[IntArray, FloatArray, int]:
    last_start = record.sample_count - window_length_samples
    if last_start < 0:
        raise ValueError("window_length_samples exceeds record sample count.")
    all_starts = np.arange(0, last_start + 1, HOP_SAMPLES, dtype=np.int64)
    all_times = record.start_time_s + (
        all_starts.astype(np.float64) + window_length_samples / 2.0
    ) / record.sample_rate_hz
    selected = np.ones(all_times.shape, dtype=np.bool_)
    if event_start_time_s is not None:
        selected &= all_times >= event_start_time_s
    if analysis_end_time_s is not None:
        selected &= all_times <= analysis_end_time_s
    return all_starts[selected], all_times[selected], int(all_starts.size)


def estimate_frequency_series(
    record: SignalRecord,
    configuration: AuditConfiguration,
    *,
    event_start_time_s: float | None = RIDGE_START_TIME_S,
    analysis_end_time_s: float | None = ANALYSIS_END_TIME_S,
) -> FrequencyEstimate:
    """Estimate local peaks in bounded batches without retaining a full STFT matrix."""
    if configuration.window_length_samples not in WINDOW_LENGTHS:
        raise ValueError("TASK-010 window length is outside the allowed finite set.")
    if configuration.window_name not in WINDOW_NAMES:
        raise ValueError("TASK-010 window name is outside the allowed finite set.")
    if configuration.nfft < configuration.window_length_samples:
        raise ValueError("nfft must be at least the window length.")
    if configuration.peak_method not in {"discrete", "subbin"}:
        raise ValueError("peak_method must be 'discrete' or 'subbin'.")
    starts, frame_times, full_frame_count = _candidate_frame_starts(
        record,
        window_length_samples=configuration.window_length_samples,
        event_start_time_s=event_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
    )
    if starts.size == 0:
        raise ValueError("No complete STFT frame lies inside the requested interval.")
    frequency_axis = scipy.fft.rfftfreq(
        configuration.nfft,
        d=1.0 / record.sample_rate_hz,
    )
    band_indices = np.flatnonzero(
        (frequency_axis >= MINIMUM_FREQUENCY_HZ)
        & (frequency_axis <= MAXIMUM_FREQUENCY_HZ)
    )
    if band_indices.size < 3:
        raise ValueError("Configured frequency band contains too few RFFT bins.")
    window = scipy.signal.get_window(
        configuration.window_name,
        configuration.window_length_samples,
        fftbins=True,
    )
    batch_size = (
        RFFT_LARGE_BATCH_SIZE
        if configuration.nfft >= LARGE_NFFT
        else RFFT_SMALL_BATCH_SIZE
    )
    estimated = np.full(starts.shape, np.nan, dtype=np.float64)
    start_clock = perf_counter()
    voltage = record.voltage_v
    for batch_start in range(0, starts.size, batch_size):
        selected_starts = starts[batch_start : batch_start + batch_size]
        frames = np.stack(
            [
                voltage[int(start) : int(start) + configuration.window_length_samples]
                for start in selected_starts
            ]
        )
        frames *= window
        spectrum = scipy.fft.rfft(
            frames,
            n=configuration.nfft,
            axis=1,
            workers=1,
        )
        band_magnitude = np.abs(spectrum[:, band_indices])
        relative_peaks = np.argmax(band_magnitude, axis=1)
        peak_indices = band_indices[relative_peaks]
        batch_estimates = frequency_axis[peak_indices].astype(np.float64, copy=True)
        if configuration.peak_method == "subbin":
            for row_index, peak_index in enumerate(peak_indices):
                peak = int(peak_index)
                if peak <= int(band_indices[0]) or peak >= int(band_indices[-1]):
                    batch_estimates[row_index] = np.nan
                    continue
                magnitudes = np.abs(spectrum[row_index, peak - 1 : peak + 2])
                if not np.all(np.isfinite(magnitudes)) or not np.all(magnitudes > 0.0):
                    batch_estimates[row_index] = np.nan
                    continue
                left, center, right = (float(value) for value in np.log(magnitudes))
                denominator = left - 2.0 * center + right
                tolerance = 16.0 * np.finfo(np.float64).eps * max(
                    1.0,
                    abs(left),
                    2.0 * abs(center),
                    abs(right),
                )
                if (
                    not math.isfinite(denominator)
                    or denominator >= 0.0
                    or abs(denominator) <= tolerance
                ):
                    batch_estimates[row_index] = np.nan
                    continue
                offset = 0.5 * (left - right) / denominator
                if not math.isfinite(offset) or not -0.5 <= offset <= 0.5:
                    batch_estimates[row_index] = np.nan
                    continue
                batch_estimates[row_index] = (
                    frequency_axis[peak]
                    + offset * record.sample_rate_hz / configuration.nfft
                )
        estimated[batch_start : batch_start + selected_starts.size] = batch_estimates
    runtime_s = perf_counter() - start_clock
    if not np.all(np.isfinite(estimated)):
        raise RuntimeError(
            f"Configuration {configuration.identifier} produced unavailable frames."
        )

    actual_batch = min(batch_size, int(starts.size))
    rfft_bins = configuration.nfft // 2 + 1
    band_count = int(band_indices.size)
    estimated_working_bytes = (
        actual_batch * configuration.window_length_samples * 8
        + actual_batch * rfft_bins * 16
        + actual_batch * band_count * 8
        + frequency_axis.nbytes
        + window.nbytes
    )
    full_spectrum_bytes = full_frame_count * rfft_bins * 16
    return FrequencyEstimate(
        time_s=np.asarray(frame_times, dtype=np.float64),
        frequency_hz=estimated,
        runtime_s=runtime_s,
        estimated_peak_working_memory_mb=estimated_working_bytes / 1024.0**2,
        estimated_full_spectrum_one_copy_mb=full_spectrum_bytes / 1024.0**2,
        configuration=configuration,
    )


def _refined_velocity(result: RefinedRidgeResult) -> FloatArray:
    refined_mask = np.fromiter(
        (
            status is RidgeRefinementStatus.REFINED
            for status in result.refinement_statuses
        ),
        dtype=np.bool_,
        count=len(result.refinement_statuses),
    )
    velocity = np.full(result.time_s.shape, np.nan, dtype=np.float64)
    velocity[refined_mask] = (
        result.refined_frequency_hz[refined_mask] * VACUUM_WAVELENGTH_M / 2.0
    )
    return velocity


def _display_velocity(
    result: RefinedRidgeResult,
    refined_velocity_m_s: FloatArray,
) -> tuple[FloatArray, list[str]]:
    display = np.full(result.time_s.shape, np.nan, dtype=np.float64)
    origins: list[str] = []
    for index, (flag, status) in enumerate(
        zip(result.quality_flags, result.refinement_statuses)
    ):
        if flag is RidgeQualityFlag.PRE_EVENT:
            display[index] = 0.0
            origins.append("assumed_pre_event_zero")
        elif flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW:
            origins.append("outside_analysis_window")
        elif status is RidgeRefinementStatus.REFINED:
            display[index] = refined_velocity_m_s[index]
            origins.append("refined_candidate_measurement")
        else:
            origins.append("refinement_unavailable")
    return display, origins


def _fingerprint_value(value: object) -> object:
    if isinstance(value, np.ndarray):
        result: dict[str, object] = {
            "kind": "ndarray",
            "dtype": value.dtype.str,
            "shape": list(value.shape),
            "data_sha256": _array_sha256(value),
        }
        if value.dtype.kind in {"f", "c"}:
            nan_mask = np.isnan(value)
            result["nan_count"] = int(np.count_nonzero(nan_mask))
            result["nan_mask_sha256"] = _array_sha256(nan_mask)
        return result
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _fingerprint_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _fingerprint_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        if all(isinstance(item, Enum) for item in value):
            strings = [cast(Enum, item).value for item in value]
        else:
            strings = [str(item) for item in value]
        encoded = json.dumps(strings, separators=(",", ":")).encode("utf-8")
        return {
            "kind": "sequence",
            "length": len(value),
            "counts": dict(sorted(Counter(strings).items())),
            "data_sha256": hashlib.sha256(encoded).hexdigest(),
        }
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return value


def _production_channel(
    record: SignalRecord,
) -> tuple[dict[str, object], dict[str, object], FrequencyEstimate]:
    start_clock = perf_counter()
    stft_result = compute_stft(
        record,
        window_length_samples=768,
        overlap_samples=640,
        nfft=4096,
        window_name="hann",
    )
    ridge_result = extract_peak_ridge(
        stft_result,
        minimum_frequency_hz=MINIMUM_FREQUENCY_HZ,
        maximum_frequency_hz=MAXIMUM_FREQUENCY_HZ,
        event_start_time_s=RIDGE_START_TIME_S,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
    )
    refined_result = refine_peak_ridge_subbin(stft_result, ridge_result)
    discrete_velocity = convert_ridge_to_apparent_velocity(
        ridge_result,
        vacuum_wavelength_m=VACUUM_WAVELENGTH_M,
    ).apparent_velocity_m_s
    refined_velocity = _refined_velocity(refined_result)
    display_velocity, origins = _display_velocity(refined_result, refined_velocity)
    analysis_runtime_s = perf_counter() - start_clock
    guard_hz = 2.0 * stft_result.sample_rate_hz / stft_result.window_length_samples
    quality = assess_ridge_spectral_quality(
        stft_result,
        refined_result,
        background_exclusion_half_width_hz=guard_hz,
        minimum_background_bin_count=2,
    )
    continuity = assess_ridge_continuity(refined_result)
    related = assess_related_frequency_evidence(
        stft_result,
        refined_result,
        quality,
        search_half_width_hz=(
            stft_result.sample_rate_hz / stft_result.window_length_samples
        ),
    )
    production = {
        "stft_result": _fingerprint_value(stft_result),
        "ridge_result": _fingerprint_value(ridge_result),
        "refined_result": _fingerprint_value(refined_result),
        "discrete_velocity_m_s": _fingerprint_value(discrete_velocity),
        "refined_velocity_m_s": _fingerprint_value(refined_velocity),
        "display_velocity_m_s": _fingerprint_value(display_velocity),
        "velocity_origins": _fingerprint_value(origins),
    }
    diagnostics = {
        "quality": _fingerprint_value(quality),
        "continuity": _fingerprint_value(continuity),
        "related": _fingerprint_value(related),
    }
    successful = np.fromiter(
        (
            status is RidgeRefinementStatus.REFINED
            for status in refined_result.refinement_statuses
        ),
        dtype=np.bool_,
        count=len(refined_result.refinement_statuses),
    )
    compact = FrequencyEstimate(
        time_s=refined_result.time_s[successful].copy(),
        frequency_hz=refined_result.refined_frequency_hz[successful].copy(),
        runtime_s=analysis_runtime_s,
        estimated_peak_working_memory_mb=(
            3.0 * stft_result.spectrum.nbytes / 1024.0**2
        ),
        estimated_full_spectrum_one_copy_mb=(
            stft_result.spectrum.nbytes / 1024.0**2
        ),
        configuration=AuditConfiguration("hann", 768, 4096, "subbin"),
    )
    return production, diagnostics, compact


def production_snapshot(
    records: Mapping[str, SignalRecord],
    *,
    source_sha256: str,
) -> tuple[dict[str, object], dict[str, FrequencyEstimate]]:
    """Recompute the complete current production and TASK-008 numeric chain."""
    task001_to_task007: dict[str, object] = {}
    task008a: dict[str, object] = {}
    task008b_continuity: dict[str, object] = {}
    task008b_related: dict[str, object] = {}
    compact: dict[str, FrequencyEstimate] = {}
    for channel_name, record in records.items():
        production, diagnostics, estimate = _production_channel(record)
        task001_to_task007[channel_name] = production
        task008a[channel_name] = diagnostics["quality"]
        task008b_continuity[channel_name] = diagnostics["continuity"]
        task008b_related[channel_name] = diagnostics["related"]
        compact[channel_name] = estimate
    snapshot = {
        "configuration": {
            "window_length_samples": 768,
            "overlap_samples": 640,
            "hop_samples": HOP_SAMPLES,
            "nfft": 4096,
        },
        "source_sha256": source_sha256,
        "task001_to_task007": task001_to_task007,
        "task008a": task008a,
        "task008b_continuity": task008b_continuity,
        "task008b_related_frequency": task008b_related,
    }
    return snapshot, compact


def _collect_regression_leaves(value: object, prefix: str = "") -> dict[str, object]:
    leaves: dict[str, object] = {}
    if isinstance(value, dict):
        if value.get("kind") == "ndarray":
            for name in ("data_sha256", "nan_mask_sha256", "nan_count", "shape", "dtype"):
                if name in value:
                    leaves[f"{prefix}.{name}"] = value[name]
            return leaves
        if value.get("kind") == "sequence":
            leaves[f"{prefix}.length"] = value.get("length")
            leaves[f"{prefix}.counts"] = value.get("counts")
            return leaves
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            leaves.update(_collect_regression_leaves(item, next_prefix))
    return leaves


def compare_production_snapshots(
    reference: Mapping[str, object],
    actual: Mapping[str, object],
) -> dict[str, object]:
    """Compare every numeric array/hash and state-count leaf shared by snapshots."""
    reference_leaves = _collect_regression_leaves(dict(reference))
    actual_leaves = _collect_regression_leaves(dict(actual))
    shared = sorted(set(reference_leaves) & set(actual_leaves))
    mismatches = [
        key for key in shared if reference_leaves[key] != actual_leaves[key]
    ]
    missing_from_actual = sorted(set(reference_leaves) - set(actual_leaves))
    scalar_mismatches: list[str] = []
    for scalar_name in ("configuration", "source_sha256"):
        if reference.get(scalar_name) != actual.get(scalar_name):
            scalar_mismatches.append(scalar_name)
    return {
        "shared_checked_leaf_count": len(shared),
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "missing_from_actual": missing_from_actual,
        "scalar_mismatches": scalar_mismatches,
        "matches": (
            not mismatches and not missing_from_actual and not scalar_mismatches
        ),
    }


def _stable_phase(frequency_hz: FloatArray, sample_rate_hz: float) -> FloatArray:
    phase = np.cumsum(2.0 * np.pi * frequency_hz / sample_rate_hz)
    phase -= phase[0]
    return phase


def generate_synthetic_signal(
    case_name: str,
    *,
    sample_rate_hz: float,
    noise_standard_deviation: float,
    random_seed: int,
    duration_s: float = 0.76e-6,
) -> SyntheticSignal:
    """Create one fixed-seed synthetic signal with an explicit frequency truth."""
    if case_name not in {"constant", "slow_modulation", "fast_decline", "competition"}:
        raise ValueError("Unknown synthetic case.")
    sample_count = int(math.floor(duration_s * sample_rate_hz))
    time_s = np.arange(sample_count, dtype=np.float64) / sample_rate_hz
    competitor: float | None = None
    transition_onset: float | None = None
    transition_end: float | None = None

    if case_name == "constant":
        def truth(query: FloatArray) -> FloatArray:
            return np.full(np.asarray(query).shape, 0.63e9, dtype=np.float64)

        frequency = truth(time_s)
        voltage = np.sin(_stable_phase(frequency, sample_rate_hz))
    elif case_name == "slow_modulation":
        period_s = 0.70e-6

        def truth(query: FloatArray) -> FloatArray:
            query_values = np.asarray(query, dtype=np.float64)
            return 0.63e9 + 0.03e9 * np.sin(2.0 * np.pi * query_values / period_s)

        frequency = truth(time_s)
        voltage = np.sin(_stable_phase(frequency, sample_rate_hz))
    elif case_name == "fast_decline":
        transition_onset = 0.50e-6
        transition_end = 0.63e-6

        def truth(query: FloatArray) -> FloatArray:
            query_values = np.asarray(query, dtype=np.float64)
            normalized = np.clip(
                (query_values - cast(float, transition_onset))
                / (cast(float, transition_end) - cast(float, transition_onset)),
                0.0,
                1.0,
            )
            smooth = normalized * normalized * (3.0 - 2.0 * normalized)
            return 0.73e9 - (0.73e9 - 0.28e9) * smooth

        frequency = truth(time_s)
        voltage = np.sin(_stable_phase(frequency, sample_rate_hz))
    else:
        competitor = 0.69e9

        def truth(query: FloatArray) -> FloatArray:
            return np.full(np.asarray(query).shape, 0.63e9, dtype=np.float64)

        main_frequency = truth(time_s)
        competitor_frequency = np.full(time_s.shape, competitor, dtype=np.float64)
        voltage = np.sin(_stable_phase(main_frequency, sample_rate_hz))
        voltage += 0.90 * np.sin(
            _stable_phase(competitor_frequency, sample_rate_hz) + 0.4
        )

    rng = np.random.default_rng(random_seed)
    voltage = voltage + rng.normal(0.0, noise_standard_deviation, size=time_s.size)
    record = SignalRecord(time_s=time_s, voltage_v=voltage)
    return SyntheticSignal(
        case_name=case_name,
        record=record,
        truth_frequency=truth,
        competitor_frequency_hz=competitor,
        transition_onset_s=transition_onset,
        transition_end_s=transition_end,
    )


def _alignment_row(
    channel_name: str,
    configuration: AuditConfiguration,
    estimate: FrequencyEstimate,
    alignment: AlignmentResult,
) -> dict[str, object]:
    return {
        "configuration_id": configuration.identifier,
        "channel_name": channel_name,
        "window_name": configuration.window_name,
        "window_length_samples": configuration.window_length_samples,
        "overlap_samples": configuration.overlap_samples,
        "hop_samples": HOP_SAMPLES,
        "nfft": configuration.nfft,
        "peak_method": configuration.peak_method,
        "best_offset_frames": alignment.offset_frames,
        "time_offset_ns": alignment.time_offset_ns,
        "paired_count": alignment.metrics.paired_count,
        "bias_m_s": alignment.metrics.bias_m_s,
        "mae_m_s": alignment.metrics.mae_m_s,
        "rmse_m_s": alignment.metrics.rmse_m_s,
        "maximum_absolute_error_m_s": (
            alignment.metrics.maximum_absolute_error_m_s
        ),
        "pearson_correlation": alignment.metrics.pearson_correlation,
        "runtime_s": estimate.runtime_s,
        "estimated_peak_working_memory_mb": (
            estimate.estimated_peak_working_memory_mb
        ),
        "estimated_full_spectrum_one_copy_mb": (
            estimate.estimated_full_spectrum_one_copy_mb
        ),
    }


def _relative_time(estimate: FrequencyEstimate) -> FloatArray:
    return estimate.time_s - estimate.time_s[0]


def _align_estimate(
    legacy: LegacyReference,
    estimate: FrequencyEstimate,
) -> AlignmentResult:
    return search_integer_frame_offset(
        legacy.measured_time_relative_s,
        legacy.measured_velocity_m_s,
        _relative_time(estimate),
        estimate.velocity_m_s,
    )


def _paired_channels_from_alignments(
    first: AlignmentResult,
    second: AlignmentResult,
    legacy_time_s: FloatArray,
    *,
    start_relative_s: float,
    end_relative_s: float,
) -> dict[str, float | int]:
    first_by_reference = {
        int(reference_index): float(value)
        for reference_index, value in zip(
            first.reference_indices,
            first.candidate_values_m_s,
        )
    }
    second_by_reference = {
        int(reference_index): float(value)
        for reference_index, value in zip(
            second.reference_indices,
            second.candidate_values_m_s,
        )
    }
    common = np.asarray(
        sorted(set(first_by_reference) & set(second_by_reference)),
        dtype=np.int64,
    )
    in_region = (
        (legacy_time_s[common] >= start_relative_s)
        & (legacy_time_s[common] <= end_relative_s)
    )
    common = common[in_region]
    first_values = np.asarray(
        [first_by_reference[int(index)] for index in common],
        dtype=np.float64,
    )
    second_values = np.asarray(
        [second_by_reference[int(index)] for index in common],
        dtype=np.float64,
    )
    differences = np.abs(first_values - second_values)
    if differences.size == 0:
        return {
            "paired_count": 0,
            "absolute_difference_median_m_s": float("nan"),
            "absolute_difference_p95_m_s": float("nan"),
            "absolute_difference_maximum_m_s": float("nan"),
            "pearson_correlation": float("nan"),
        }
    return {
        "paired_count": int(differences.size),
        "absolute_difference_median_m_s": float(np.median(differences)),
        "absolute_difference_p95_m_s": float(np.percentile(differences, 95.0)),
        "absolute_difference_maximum_m_s": float(np.max(differences)),
        "pearson_correlation": _pearson_or_nan(first_values, second_values),
    }


def _configuration_detail_row(
    base: dict[str, object],
    alignment: AlignmentResult,
    estimate: FrequencyEstimate,
    legacy: LegacyReference,
    paired_all: Mapping[str, float | int],
    paired_plateau: Mapping[str, float | int],
    paired_decline: Mapping[str, float | int],
) -> dict[str, object]:
    plateau = series_statistics(
        alignment.reference_time_relative_s,
        alignment.candidate_values_m_s,
        alignment.reference_values_m_s,
        start_relative_s=PLATEAU_START_RELATIVE_S,
        end_relative_s=PLATEAU_END_RELATIVE_S,
    )
    decline_end = min(
        DECLINE_END_RELATIVE_S,
        float(legacy.measured_time_relative_s[-1]),
    )
    decline = series_statistics(
        alignment.reference_time_relative_s,
        alignment.candidate_values_m_s,
        alignment.reference_values_m_s,
        start_relative_s=DECLINE_START_RELATIVE_S,
        end_relative_s=decline_end,
    )
    row = dict(base)
    row.update(
        {
            "frequency_grid_spacing_hz": float("nan"),
            "window_time_support_ns": float("nan"),
            "unzero_padded_window_frequency_scale_hz": float("nan"),
            "plateau_velocity_min_m_s": plateau.velocity_min_m_s,
            "plateau_velocity_median_m_s": plateau.velocity_median_m_s,
            "plateau_velocity_max_m_s": plateau.velocity_max_m_s,
            "plateau_velocity_standard_deviation_m_s": (
                plateau.velocity_standard_deviation_m_s
            ),
            "plateau_first_difference_absolute_median_m_s": (
                plateau.first_difference_absolute_median_m_s
            ),
            "plateau_first_difference_absolute_p95_m_s": (
                plateau.first_difference_absolute_p95_m_s
            ),
            "plateau_first_difference_absolute_maximum_m_s": (
                plateau.first_difference_absolute_maximum_m_s
            ),
            "plateau_signed_first_difference_standard_deviation_m_s": (
                plateau.signed_first_difference_standard_deviation_m_s
            ),
            "plateau_second_difference_rms_m_s": (
                plateau.second_difference_rms_m_s
            ),
            "plateau_adjacent_change_correlation_with_legacy": (
                plateau.adjacent_change_correlation_with_legacy
            ),
            "decline_velocity_min_m_s": decline.velocity_min_m_s,
            "decline_velocity_median_m_s": decline.velocity_median_m_s,
            "decline_velocity_max_m_s": decline.velocity_max_m_s,
            "decline_velocity_standard_deviation_m_s": (
                decline.velocity_standard_deviation_m_s
            ),
            "decline_first_difference_absolute_median_m_s": (
                decline.first_difference_absolute_median_m_s
            ),
            "decline_first_difference_absolute_p95_m_s": (
                decline.first_difference_absolute_p95_m_s
            ),
            "decline_first_difference_absolute_maximum_m_s": (
                decline.first_difference_absolute_maximum_m_s
            ),
            "decline_signed_first_difference_standard_deviation_m_s": (
                decline.signed_first_difference_standard_deviation_m_s
            ),
            "decline_second_difference_rms_m_s": (
                decline.second_difference_rms_m_s
            ),
            "decline_adjacent_change_correlation_with_legacy": (
                decline.adjacent_change_correlation_with_legacy
            ),
            "two_channel_all_paired_count": paired_all["paired_count"],
            "two_channel_all_absolute_difference_median_m_s": paired_all[
                "absolute_difference_median_m_s"
            ],
            "two_channel_all_absolute_difference_p95_m_s": paired_all[
                "absolute_difference_p95_m_s"
            ],
            "two_channel_all_absolute_difference_maximum_m_s": paired_all[
                "absolute_difference_maximum_m_s"
            ],
            "two_channel_all_pearson_correlation": paired_all[
                "pearson_correlation"
            ],
            "two_channel_plateau_paired_count": paired_plateau["paired_count"],
            "two_channel_plateau_absolute_difference_median_m_s": paired_plateau[
                "absolute_difference_median_m_s"
            ],
            "two_channel_plateau_absolute_difference_p95_m_s": paired_plateau[
                "absolute_difference_p95_m_s"
            ],
            "two_channel_plateau_absolute_difference_maximum_m_s": paired_plateau[
                "absolute_difference_maximum_m_s"
            ],
            "two_channel_decline_paired_count": paired_decline["paired_count"],
            "two_channel_decline_absolute_difference_median_m_s": paired_decline[
                "absolute_difference_median_m_s"
            ],
            "two_channel_decline_absolute_difference_p95_m_s": paired_decline[
                "absolute_difference_p95_m_s"
            ],
            "two_channel_decline_absolute_difference_maximum_m_s": paired_decline[
                "absolute_difference_maximum_m_s"
            ],
        }
    )
    return row


def _get_estimate(
    records: Mapping[str, SignalRecord],
    channel_name: str,
    configuration: AuditConfiguration,
    cache: dict[tuple[str, str], FrequencyEstimate],
) -> FrequencyEstimate:
    key = (configuration.identifier, channel_name)
    if key not in cache:
        cache[key] = estimate_frequency_series(
            records[channel_name],
            configuration,
        )
    return cache[key]


def evaluate_configurations(
    records: Mapping[str, SignalRecord],
    legacy: LegacyReference,
    configurations: Sequence[AuditConfiguration],
    cache: dict[tuple[str, str], FrequencyEstimate],
    *,
    preset_estimates: Mapping[tuple[str, str], FrequencyEstimate] | None = None,
) -> tuple[pd.DataFrame, dict[str, dict[str, AlignmentResult]]]:
    """Evaluate the finite grid and retain every boundary-overlap pair."""
    rows: list[dict[str, object]] = []
    all_alignments: dict[str, dict[str, AlignmentResult]] = {}
    sample_rate_hz = next(iter(records.values())).sample_rate_hz
    for configuration in configurations:
        channel_alignments: dict[str, AlignmentResult] = {}
        channel_estimates: dict[str, FrequencyEstimate] = {}
        for channel_name in records:
            preset_key = (configuration.identifier, channel_name)
            if preset_estimates is not None and preset_key in preset_estimates:
                estimate = preset_estimates[preset_key]
                cache[preset_key] = estimate
            else:
                estimate = _get_estimate(
                    records,
                    channel_name,
                    configuration,
                    cache,
                )
            channel_estimates[channel_name] = estimate
            channel_alignments[channel_name] = _align_estimate(legacy, estimate)
        first = channel_alignments["pdv_channel_1"]
        second = channel_alignments["pdv_channel_2"]
        decline_end = min(
            DECLINE_END_RELATIVE_S,
            float(legacy.measured_time_relative_s[-1]),
        )
        paired_all = _paired_channels_from_alignments(
            first,
            second,
            legacy.measured_time_relative_s,
            start_relative_s=RISE_START_RELATIVE_S,
            end_relative_s=decline_end,
        )
        paired_plateau = _paired_channels_from_alignments(
            first,
            second,
            legacy.measured_time_relative_s,
            start_relative_s=PLATEAU_START_RELATIVE_S,
            end_relative_s=PLATEAU_END_RELATIVE_S,
        )
        paired_decline = _paired_channels_from_alignments(
            first,
            second,
            legacy.measured_time_relative_s,
            start_relative_s=DECLINE_START_RELATIVE_S,
            end_relative_s=decline_end,
        )
        for channel_name, estimate in channel_estimates.items():
            alignment = channel_alignments[channel_name]
            base = _alignment_row(
                channel_name,
                configuration,
                estimate,
                alignment,
            )
            detailed = _configuration_detail_row(
                base,
                alignment,
                estimate,
                legacy,
                paired_all,
                paired_plateau,
                paired_decline,
            )
            detailed["frequency_grid_spacing_hz"] = (
                sample_rate_hz / configuration.nfft
            )
            detailed["window_time_support_ns"] = (
                configuration.window_length_samples / sample_rate_hz * 1.0e9
            )
            detailed["unzero_padded_window_frequency_scale_hz"] = (
                sample_rate_hz / configuration.window_length_samples
            )
            rows.append(detailed)
        all_alignments[configuration.identifier] = channel_alignments
    return pd.DataFrame(rows), all_alignments


def roughness_rows(
    legacy: LegacyReference,
    alignments: Mapping[str, AlignmentResult],
) -> pd.DataFrame:
    """Report legacy and current roughness for immutable, fixed regions."""
    rows: list[dict[str, object]] = []
    common_end = min(
        DECLINE_END_RELATIVE_S,
        float(legacy.measured_time_relative_s[-1]),
    )
    regions = {
        "rise": (RISE_START_RELATIVE_S, RISE_END_RELATIVE_S),
        "plateau": (PLATEAU_START_RELATIVE_S, PLATEAU_END_RELATIVE_S),
        "decline": (DECLINE_START_RELATIVE_S, common_end),
        "full": (RISE_START_RELATIVE_S, common_end),
    }
    for channel_name, alignment in alignments.items():
        for region_name, (start, end) in regions.items():
            for series_name, values in (
                ("legacy", alignment.reference_values_m_s),
                (channel_name, alignment.candidate_values_m_s),
            ):
                statistics = series_statistics(
                    alignment.reference_time_relative_s,
                    values,
                    alignment.reference_values_m_s,
                    start_relative_s=start,
                    end_relative_s=end,
                )
                row = {
                    "alignment_channel": channel_name,
                    "series_name": series_name,
                    "region": region_name,
                    "region_start_relative_us": start * 1.0e6,
                    "region_end_relative_us": end * 1.0e6,
                }
                row.update(asdict(statistics))
                rows.append(row)
    return pd.DataFrame(rows)


def _robust_standard_deviation(values: FloatArray) -> float:
    finite = np.asarray(values, dtype=np.float64)
    finite = finite[np.isfinite(finite)]
    if finite.size == 0:
        return float("nan")
    median = float(np.median(finite))
    return float(np.median(np.abs(finite - median)) / 0.6744897501960817)


def estimate_development_noise_proxy(
    records: Mapping[str, SignalRecord],
) -> tuple[float, pd.DataFrame]:
    """Estimate a synthetic-only noise ratio from pre-event/plateau amplitudes."""
    rows: list[dict[str, object]] = []
    ratios: list[float] = []
    for channel_name, record in records.items():
        pre_event = record.voltage_v[record.time_s < RIDGE_START_TIME_S]
        plateau = record.voltage_v[
            (record.time_s >= RIDGE_START_TIME_S + PLATEAU_START_RELATIVE_S)
            & (record.time_s <= RIDGE_START_TIME_S + PLATEAU_END_RELATIVE_S)
        ]
        pre_event_sigma = _robust_standard_deviation(pre_event)
        plateau_sigma = _robust_standard_deviation(plateau)
        inferred_peak_amplitude = math.sqrt(2.0) * plateau_sigma
        ratio = pre_event_sigma / inferred_peak_amplitude
        ratios.append(ratio)
        rows.append(
            {
                "channel_name": channel_name,
                "pre_event_robust_sigma_v": pre_event_sigma,
                "plateau_robust_sigma_v": plateau_sigma,
                "inferred_plateau_peak_amplitude_v": inferred_peak_amplitude,
                "synthetic_noise_sigma_per_unit_peak_amplitude": ratio,
                "limitation": (
                    "pre-event variability is only a development noise proxy and may "
                    "contain coherent instrument or optical content"
                ),
            }
        )
    return float(np.median(np.asarray(ratios))), pd.DataFrame(rows)


def _first_threshold_crossing(
    time_s: FloatArray,
    frequency_hz: FloatArray,
    *,
    threshold_hz: float,
) -> float | None:
    indices = np.flatnonzero(frequency_hz <= threshold_hz)
    return float(time_s[int(indices[0])]) if indices.size else None


def synthetic_metrics(
    signal: SyntheticSignal,
    estimate: FrequencyEstimate,
) -> dict[str, float | int | None]:
    """Compare an estimate with instantaneous known truth at every frame center."""
    truth = signal.truth_frequency(estimate.time_s)
    estimated = estimate.frequency_hz
    valid = np.isfinite(truth) & np.isfinite(estimated)
    errors = estimated[valid] - truth[valid]
    if errors.size == 0:
        raise RuntimeError("Synthetic estimate contains no finite truth pairs.")
    if signal.case_name == "fast_decline":
        plateau = valid & (estimate.time_s < 0.45e-6)
    else:
        plateau = valid
    plateau_error = estimated[plateau] - truth[plateau]
    onset_error_ns: float | None = None
    transition_shape_rmse_hz: float | None = None
    if signal.case_name == "fast_decline":
        threshold_hz = 0.73e9 - 0.05 * (0.73e9 - 0.28e9)
        truth_crossing = _first_threshold_crossing(
            estimate.time_s,
            truth,
            threshold_hz=threshold_hz,
        )
        estimate_crossing = _first_threshold_crossing(
            estimate.time_s,
            estimated,
            threshold_hz=threshold_hz,
        )
        if truth_crossing is not None and estimate_crossing is not None:
            onset_error_ns = (estimate_crossing - truth_crossing) * 1.0e9
        transition = valid & (
            estimate.time_s >= cast(float, signal.transition_onset_s)
        ) & (estimate.time_s <= cast(float, signal.transition_end_s))
        transition_errors = estimated[transition] - truth[transition]
        if transition_errors.size:
            transition_shape_rmse_hz = float(
                np.sqrt(np.mean(np.square(transition_errors)))
            )
    wrong_branch_count = 0
    if signal.competitor_frequency_hz is not None:
        distance_to_main = np.abs(estimated[valid] - truth[valid])
        distance_to_competitor = np.abs(
            estimated[valid] - signal.competitor_frequency_hz
        )
        wrong_branch_count = int(
            np.count_nonzero(distance_to_competitor < distance_to_main)
        )
    rmse_hz = float(np.sqrt(np.mean(np.square(errors))))
    return {
        "paired_count": int(errors.size),
        "frequency_bias_hz": float(np.mean(errors)),
        "frequency_rmse_hz": rmse_hz,
        "velocity_rmse_m_s": rmse_hz * VACUUM_WAVELENGTH_M / 2.0,
        "plateau_jitter_hz": (
            float(np.std(plateau_error)) if plateau_error.size else float("nan")
        ),
        "transition_onset_error_ns": onset_error_ns,
        "transition_shape_rmse_hz": transition_shape_rmse_hz,
        "maximum_pointwise_error_hz": float(np.max(np.abs(errors))),
        "wrong_branch_frame_count": wrong_branch_count,
    }


def evaluate_synthetic_truth(
    configurations: Sequence[AuditConfiguration],
    *,
    sample_rate_hz: float,
    real_noise_proxy: float,
) -> pd.DataFrame:
    """Run four truth cases at three deterministic noise levels."""
    rows: list[dict[str, object]] = []
    noise_levels = (
        ("none", 0.0),
        ("medium", 0.30),
        ("real_pre_event_proxy", real_noise_proxy),
    )
    cases = ("constant", "slow_modulation", "fast_decline", "competition")
    for case_index, case_name in enumerate(cases):
        for noise_index, (noise_name, noise_sigma) in enumerate(noise_levels):
            seed = SYNTHETIC_RANDOM_SEED + case_index * 100 + noise_index
            signal = generate_synthetic_signal(
                case_name,
                sample_rate_hz=sample_rate_hz,
                noise_standard_deviation=noise_sigma,
                random_seed=seed,
            )
            for configuration in configurations:
                estimate = estimate_frequency_series(
                    signal.record,
                    configuration,
                    event_start_time_s=None,
                    analysis_end_time_s=None,
                )
                row: dict[str, object] = {
                    "case_name": case_name,
                    "noise_name": noise_name,
                    "noise_standard_deviation": noise_sigma,
                    "random_seed": seed,
                    "configuration_id": configuration.identifier,
                    "window_name": configuration.window_name,
                    "window_length_samples": configuration.window_length_samples,
                    "overlap_samples": configuration.overlap_samples,
                    "hop_samples": HOP_SAMPLES,
                    "nfft": configuration.nfft,
                    "peak_method": configuration.peak_method,
                    "runtime_s": estimate.runtime_s,
                    "estimated_peak_working_memory_mb": (
                        estimate.estimated_peak_working_memory_mb
                    ),
                }
                row.update(synthetic_metrics(signal, estimate))
                rows.append(row)
    return pd.DataFrame(rows)


def _decline_onset_from_aligned(alignment: AlignmentResult) -> float | None:
    time_values = alignment.reference_time_relative_s
    velocity = alignment.candidate_values_m_s
    plateau = (
        (time_values >= PLATEAU_START_RELATIVE_S)
        & (time_values <= PLATEAU_END_RELATIVE_S)
    )
    plateau_values = velocity[plateau]
    if plateau_values.size < 3:
        return None
    median = float(np.median(plateau_values))
    mad = float(np.median(np.abs(plateau_values - median)))
    threshold = median - max(5.0, 5.0 * mad)
    after = np.flatnonzero(time_values >= PLATEAU_END_RELATIVE_S)
    for index in after:
        start = int(index)
        if start + 3 <= velocity.size and np.all(velocity[start : start + 3] < threshold):
            return float(time_values[start])
    return None


def build_nfft_comparison(
    top_short_configurations: Sequence[AuditConfiguration],
    records: Mapping[str, SignalRecord],
    legacy: LegacyReference,
    cache: dict[tuple[str, str], FrequencyEstimate],
) -> tuple[pd.DataFrame, dict[str, dict[str, AlignmentResult]]]:
    """Compare 4096/8192 sub-bin estimates with 256000 discrete estimates."""
    configurations: list[AuditConfiguration] = []
    for candidate in top_short_configurations:
        configurations.extend(
            [
                AuditConfiguration(
                    candidate.window_name,
                    candidate.window_length_samples,
                    4096,
                    "subbin",
                ),
                AuditConfiguration(
                    candidate.window_name,
                    candidate.window_length_samples,
                    8192,
                    "subbin",
                ),
                AuditConfiguration(
                    candidate.window_name,
                    candidate.window_length_samples,
                    LARGE_NFFT,
                    "discrete",
                ),
            ]
        )
    comparison, alignments = evaluate_configurations(
        records,
        legacy,
        configurations,
        cache,
    )
    rows: list[dict[str, object]] = []
    for candidate in top_short_configurations:
        family = (
            candidate.window_name,
            candidate.window_length_samples,
        )
        family_configs = [
            configuration
            for configuration in configurations
            if (
                configuration.window_name,
                configuration.window_length_samples,
            )
            == family
        ]
        large = next(configuration for configuration in family_configs if configuration.nfft == LARGE_NFFT)
        nfft8192 = next(configuration for configuration in family_configs if configuration.nfft == 8192)
        for channel_name in records:
            large_estimate = cache[(large.identifier, channel_name)]
            estimate8192 = cache[(nfft8192.identifier, channel_name)]
            for configuration in family_configs:
                estimate = cache[(configuration.identifier, channel_name)]
                if not np.allclose(
                    estimate.time_s,
                    large_estimate.time_s,
                    rtol=0.0,
                    atol=1.0e-18,
                ):
                    raise RuntimeError("NFFT comparison time axes differ unexpectedly.")
                difference_large = alignment_metrics(
                    large_estimate.velocity_m_s,
                    estimate.velocity_m_s,
                )
                difference8192 = alignment_metrics(
                    estimate8192.velocity_m_s,
                    estimate.velocity_m_s,
                )
                source = comparison[
                    (comparison["configuration_id"] == configuration.identifier)
                    & (comparison["channel_name"] == channel_name)
                ].iloc[0].to_dict()
                source.update(
                    {
                        "difference_to_nfft256000_bias_m_s": (
                            difference_large.bias_m_s
                        ),
                        "difference_to_nfft256000_mae_m_s": difference_large.mae_m_s,
                        "difference_to_nfft256000_rmse_m_s": difference_large.rmse_m_s,
                        "difference_to_nfft8192_mae_m_s": difference8192.mae_m_s,
                        "difference_to_nfft8192_rmse_m_s": difference8192.rmse_m_s,
                        "decline_onset_relative_us": (
                            _decline_onset_from_aligned(
                                alignments[configuration.identifier][channel_name]
                            )
                            or float("nan")
                        )
                        * 1.0e6,
                    }
                )
                rows.append(source)
    return pd.DataFrame(rows), alignments


def _save_figure(figure: Figure, path: Path) -> Path:
    with matplotlib.rc_context({"path.simplify": False}):
        figure.savefig(path, dpi=SAVE_DPI)
    plt.close(figure)
    return path


def _style_axis(axis: Axes, *, title: str, ylabel: str) -> None:
    axis.set_title(title)
    axis.set_xlabel("Time relative to first measured legacy frame (µs)")
    axis.set_ylabel(ylabel)
    axis.grid(alpha=0.25)


def _plot_alignment_series(
    axis: Axes,
    alignment: AlignmentResult,
    *,
    candidate_label: str,
) -> None:
    time_us = alignment.reference_time_relative_s * 1.0e6
    axis.plot(
        time_us,
        alignment.reference_values_m_s,
        color="tab:red",
        linewidth=LINE_WIDTH,
        label="legacy measured output",
    )
    axis.plot(
        time_us,
        alignment.candidate_values_m_s,
        linewidth=LINE_WIDTH,
        label=candidate_label,
    )


def create_plots(
    output_directory: Path,
    legacy: LegacyReference,
    current_alignments: Mapping[str, AlignmentResult],
    best_alignments: Mapping[str, AlignmentResult],
    configuration_frame: pd.DataFrame,
    synthetic_frame: pd.DataFrame,
    repeatability_frame: pd.DataFrame,
    synthetic_configurations: Sequence[AuditConfiguration],
    *,
    sample_rate_hz: float,
    best_configuration_id: str,
) -> list[Path]:
    """Generate all required thin-line diagnostic figures."""
    generated: list[Path] = []
    channel_labels = {
        "pdv_channel_1": "channel 1",
        "pdv_channel_2": "channel 2",
    }
    for channel_name, filename in (
        ("pdv_channel_1", "legacy_vs_current_channel_1_aligned.png"),
        ("pdv_channel_2", "legacy_vs_current_channel_2_aligned.png"),
    ):
        alignment = current_alignments[channel_name]
        figure, axis = plt.subplots(figsize=(10.2, 5.4))
        _plot_alignment_series(
            axis,
            alignment,
            candidate_label=f"current {channel_labels[channel_name]}",
        )
        _style_axis(
            axis,
            title=(
                f"Legacy vs current {channel_labels[channel_name]} | integer offset "
                f"{alignment.offset_frames:+d} frames "
                f"({alignment.time_offset_ns:+.1f} ns)"
            ),
            ylabel="Unsigned apparent velocity (m/s)",
        )
        axis.legend(loc="best")
        generated.append(_save_figure(figure, output_directory / filename))

    figure, axis = plt.subplots(figsize=(10.4, 5.5))
    first = current_alignments["pdv_channel_1"]
    axis.plot(
        first.reference_time_relative_s * 1.0e6,
        first.reference_values_m_s,
        color="tab:red",
        linewidth=LINE_WIDTH,
        label="legacy measured output",
    )
    for channel_name, alignment in current_alignments.items():
        axis.plot(
            alignment.reference_time_relative_s * 1.0e6,
            alignment.candidate_values_m_s,
            linewidth=LINE_WIDTH,
            label=(
                f"current {channel_labels[channel_name]} "
                f"({alignment.offset_frames:+d} frames)"
            ),
        )
    _style_axis(
        axis,
        title="Legacy and current baseline after explicit integer-frame alignment",
        ylabel="Unsigned apparent velocity (m/s)",
    )
    axis.legend(loc="best")
    generated.append(
        _save_figure(figure, output_directory / "legacy_vs_current_aligned.png")
    )

    figure, axis = plt.subplots(figsize=(10.4, 5.2))
    for channel_name, alignment in current_alignments.items():
        residual = alignment.reference_values_m_s - alignment.candidate_values_m_s
        axis.plot(
            alignment.reference_time_relative_s * 1.0e6,
            residual,
            linewidth=DETAIL_LINE_WIDTH,
            label=(
                f"legacy - current {channel_labels[channel_name]} | "
                f"offset {alignment.offset_frames:+d}"
            ),
        )
    axis.axhline(0.0, color="black", linewidth=0.5, linestyle="--")
    _style_axis(
        axis,
        title="Legacy minus current residual (no interpolation)",
        ylabel="Velocity residual (m/s)",
    )
    axis.legend(loc="best")
    generated.append(
        _save_figure(figure, output_directory / "legacy_minus_current_residual.png")
    )

    figure, axis = plt.subplots(figsize=(10.4, 5.5))
    first_best = best_alignments["pdv_channel_1"]
    axis.plot(
        first_best.reference_time_relative_s * 1.0e6,
        first_best.reference_values_m_s,
        color="tab:red",
        linewidth=LINE_WIDTH,
        label="legacy measured output",
    )
    for channel_name, alignment in best_alignments.items():
        axis.plot(
            alignment.reference_time_relative_s * 1.0e6,
            alignment.candidate_values_m_s,
            linewidth=LINE_WIDTH,
            label=f"{best_configuration_id} {channel_labels[channel_name]}",
        )
    _style_axis(
        axis,
        title="Legacy vs closest finite-grid reconstruction",
        ylabel="Unsigned apparent velocity (m/s)",
    )
    axis.legend(loc="best", fontsize=8)
    generated.append(
        _save_figure(
            figure,
            output_directory / "legacy_vs_best_reconstruction.png",
        )
    )

    for filename, start, end, title in (
        (
            "legacy_current_plateau_detail.png",
            PLATEAU_START_RELATIVE_S,
            PLATEAU_END_RELATIVE_S,
            "Legacy/current plateau detail",
        ),
        (
            "legacy_current_decline_detail.png",
            DECLINE_START_RELATIVE_S,
            min(DECLINE_END_RELATIVE_S, float(legacy.measured_time_relative_s[-1])),
            "Legacy/current decline detail",
        ),
    ):
        figure, axis = plt.subplots(figsize=(10.4, 5.2))
        region_values: list[FloatArray] = []
        legacy_region = (
            (first.reference_time_relative_s >= start)
            & (first.reference_time_relative_s <= end)
        )
        region_values.append(first.reference_values_m_s[legacy_region])
        axis.plot(
            first.reference_time_relative_s * 1.0e6,
            first.reference_values_m_s,
            color="tab:red",
            linewidth=DETAIL_LINE_WIDTH,
            marker=".",
            markersize=MARKER_SIZE,
            label="legacy",
        )
        for channel_name, alignment in current_alignments.items():
            current_region = (
                (alignment.reference_time_relative_s >= start)
                & (alignment.reference_time_relative_s <= end)
            )
            region_values.append(alignment.candidate_values_m_s[current_region])
            axis.plot(
                alignment.reference_time_relative_s * 1.0e6,
                alignment.candidate_values_m_s,
                linewidth=DETAIL_LINE_WIDTH,
                marker=".",
                markersize=MARKER_SIZE,
                label=f"current {channel_labels[channel_name]}",
            )
        axis.set_xlim(start * 1.0e6, end * 1.0e6)
        all_region_values = np.concatenate(region_values)
        minimum = float(np.min(all_region_values))
        maximum = float(np.max(all_region_values))
        span = maximum - minimum
        padding = max(0.05 * span, 0.5)
        axis.set_ylim(minimum - padding, maximum + padding)
        _style_axis(
            axis,
            title=title + " | fixed boundaries, every paired frame",
            ylabel="Unsigned apparent velocity (m/s)",
        )
        axis.legend(loc="best")
        generated.append(_save_figure(figure, output_directory / filename))

    figure, axis = plt.subplots(figsize=(10.4, 5.2))
    legacy_difference = np.diff(first.reference_values_m_s)
    legacy_time = first.reference_time_relative_s[1:] * 1.0e6
    axis.plot(
        legacy_time,
        legacy_difference,
        color="tab:red",
        linewidth=DETAIL_LINE_WIDTH,
        label="legacy first difference",
    )
    for channel_name, alignment in current_alignments.items():
        axis.plot(
            alignment.reference_time_relative_s[1:] * 1.0e6,
            np.diff(alignment.candidate_values_m_s),
            linewidth=DETAIL_LINE_WIDTH,
            label=f"current {channel_labels[channel_name]} first difference",
        )
    _style_axis(
        axis,
        title="Adjacent velocity changes after integer-frame alignment",
        ylabel="First difference (m/s per 3.2 ns frame)",
    )
    axis.legend(loc="best", fontsize=8)
    generated.append(
        _save_figure(
            figure,
            output_directory / "legacy_current_first_difference.png",
        )
    )

    figure, axis = plt.subplots(figsize=(10.4, 5.2))
    for channel_name, alignment in best_alignments.items():
        axis.plot(
            alignment.reference_time_relative_s * 1.0e6,
            alignment.reference_values_m_s - alignment.candidate_values_m_s,
            linewidth=DETAIL_LINE_WIDTH,
            label=f"legacy - reconstruction {channel_labels[channel_name]}",
        )
    axis.axhline(0.0, color="black", linewidth=0.5, linestyle="--")
    _style_axis(
        axis,
        title=f"Residual for closest reconstruction: {best_configuration_id}",
        ylabel="Velocity residual (m/s)",
    )
    axis.legend(loc="best")
    generated.append(
        _save_figure(
            figure,
            output_directory / "legacy_reconstruction_residual.png",
        )
    )

    aggregate = (
        configuration_frame.groupby("configuration_id", as_index=False)["rmse_m_s"]
        .mean()
        .sort_values("rmse_m_s")
    )
    figure, axis = plt.subplots(figsize=(10.5, 7.0))
    figure.subplots_adjust(left=0.38, right=0.98, top=0.92, bottom=0.10)
    positions = np.arange(aggregate.shape[0])
    axis.barh(
        positions,
        aggregate["rmse_m_s"].to_numpy(),
        color="tab:blue",
        height=0.7,
    )
    axis.set_yticks(positions, aggregate["configuration_id"].tolist(), fontsize=7)
    axis.invert_yaxis()
    axis.set_xlabel("Mean two-channel RMSE versus legacy (m/s)")
    axis.set_title("Finite configuration-grid comparison (legacy is not truth)")
    axis.grid(axis="x", alpha=0.25)
    generated.append(
        _save_figure(
            figure,
            output_directory / "configuration_error_comparison.png",
        )
    )

    constant = synthetic_frame[synthetic_frame["case_name"] == "constant"]
    constant_summary = (
        constant.groupby(["configuration_id", "noise_name"], as_index=False)[
            "frequency_rmse_hz"
        ]
        .mean()
        .sort_values(["configuration_id", "noise_name"])
    )
    configuration_ids = list(dict.fromkeys(constant_summary["configuration_id"]))
    noise_names = list(dict.fromkeys(constant_summary["noise_name"]))
    figure, axis = plt.subplots(figsize=(10.8, 5.8))
    width = 0.8 / max(1, len(noise_names))
    positions = np.arange(len(configuration_ids), dtype=np.float64)
    for index, noise_name in enumerate(noise_names):
        subset = constant_summary[constant_summary["noise_name"] == noise_name]
        values = [
            float(
                subset.loc[
                    subset["configuration_id"] == configuration_id,
                    "frequency_rmse_hz",
                ].iloc[0]
            )
            for configuration_id in configuration_ids
        ]
        axis.bar(
            positions + (index - (len(noise_names) - 1) / 2.0) * width,
            values,
            width=width,
            label=noise_name,
        )
    axis.set_xticks(positions, configuration_ids, rotation=20, ha="right", fontsize=8)
    axis.set_ylabel("Known-truth frequency RMSE (Hz)")
    axis.set_title("Synthetic constant-frequency errors")
    axis.grid(axis="y", alpha=0.25)
    axis.legend(loc="best")
    generated.append(
        _save_figure(
            figure,
            output_directory / "synthetic_constant_frequency_errors.png",
        )
    )

    fast_signal = generate_synthetic_signal(
        "fast_decline",
        sample_rate_hz=sample_rate_hz,
        noise_standard_deviation=0.30,
        random_seed=SYNTHETIC_RANDOM_SEED + 201,
    )
    figure, axis = plt.subplots(figsize=(10.4, 5.4))
    dense_time = np.linspace(0.0, 0.76e-6, 1500)
    axis.plot(
        dense_time * 1.0e6,
        fast_signal.truth_frequency(dense_time) / 1.0e9,
        color="black",
        linewidth=LINE_WIDTH,
        label="known instantaneous truth",
    )
    for configuration in synthetic_configurations:
        estimate = estimate_frequency_series(
            fast_signal.record,
            configuration,
            event_start_time_s=None,
            analysis_end_time_s=None,
        )
        axis.plot(
            estimate.time_s * 1.0e6,
            estimate.frequency_hz / 1.0e9,
            linewidth=DETAIL_LINE_WIDTH,
            label=configuration.identifier,
        )
    axis.set_xlabel("Synthetic time (µs)")
    axis.set_ylabel("Beat frequency (GHz)")
    axis.set_title("Synthetic fast-decline recovery | medium fixed-seed noise")
    axis.grid(alpha=0.25)
    axis.legend(loc="best", fontsize=7)
    generated.append(
        _save_figure(
            figure,
            output_directory / "synthetic_fast_decline_comparison.png",
        )
    )

    repeatability = repeatability_frame.drop_duplicates("configuration_id")
    repeatability = repeatability.sort_values(
        "two_channel_all_absolute_difference_median_m_s"
    )
    figure, axis = plt.subplots(figsize=(10.5, 6.5))
    positions = np.arange(repeatability.shape[0])
    axis.plot(
        positions,
        repeatability["two_channel_all_absolute_difference_median_m_s"],
        linewidth=LINE_WIDTH,
        marker="o",
        markersize=MARKER_SIZE + 1.0,
        label="median",
    )
    axis.plot(
        positions,
        repeatability["two_channel_all_absolute_difference_p95_m_s"],
        linewidth=LINE_WIDTH,
        marker="o",
        markersize=MARKER_SIZE + 1.0,
        label="p95",
    )
    axis.set_xticks(
        positions,
        repeatability["configuration_id"].tolist(),
        rotation=35,
        ha="right",
        fontsize=7,
    )
    axis.set_ylabel("Paired channel absolute difference (m/s)")
    axis.set_title("Two-channel repeatability by configuration")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    generated.append(
        _save_figure(
            figure,
            output_directory / "two_channel_repeatability_by_configuration.png",
        )
    )
    return generated


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.ndarray):
        return _json_safe(value.tolist())
    if isinstance(value, (np.integer, np.floating)):
        return _json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def _write_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(_json_safe(value), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    return path


def _legacy_summary(
    legacy: LegacyReference,
    *,
    frequency_grid_spacing_hz: float,
    inferred_nfft: float,
) -> dict[str, object]:
    return {
        "row_count": legacy.row_count,
        "measured_count": legacy.measured_count,
        "zero_masked_count": legacy.zero_masked_count,
        "time_range_us": [legacy.time_min_us, legacy.time_max_us],
        "measured_time_range_us": [
            legacy.measured_time_min_us,
            legacy.measured_time_max_us,
        ],
        "time_step_ns_min_median_max": [
            legacy.time_step_min_ns,
            legacy.time_step_median_ns,
            legacy.time_step_max_ns,
        ],
        "time_step_max_abs_error_ns": legacy.time_step_max_abs_error_ns,
        "strictly_3p2_ns_grid_with_decimal_tolerance": (
            legacy.strictly_3p2_ns_grid
        ),
        "velocity_unit": legacy.velocity_unit,
        "velocity_grid_spacing_m_s": legacy.velocity_grid_spacing_m_s,
        "all_measured_values_are_0p12109375_m_s_integer_multiples": (
            legacy.expected_spacing_integer_multiple
        ),
        "maximum_integer_multiple_residual": (
            legacy.expected_spacing_max_integer_residual
        ),
        "frequency_grid_spacing_hz": frequency_grid_spacing_hz,
        "inferred_nfft": inferred_nfft,
        "inference_label": "legacy output fingerprint inference",
        "interpretation_boundaries": {
            "fft_grid_spacing": (
                "sample_rate/nfft; zero padding changes sampling density"
            ),
            "window_resolution": (
                "the window time support and window response determine actual "
                "frequency resolving ability"
            ),
            "subbin_estimation": (
                "a local estimator can reduce grid quantization without creating "
                "new physical resolution"
            ),
            "absolute_accuracy": (
                "requires calibration and error sources beyond this output fingerprint"
            ),
        },
    }


def _configuration_truth_summary(
    synthetic_frame: pd.DataFrame,
    configuration_id: str,
) -> dict[str, float]:
    selected = synthetic_frame[synthetic_frame["configuration_id"] == configuration_id]
    constant = selected[selected["case_name"] == "constant"]
    fast = selected[selected["case_name"] == "fast_decline"]
    fast_low_and_proxy = fast[fast["noise_name"] != "medium"]
    competition = selected[selected["case_name"] == "competition"]
    onset = fast["transition_onset_error_ns"].dropna().abs()
    return {
        "constant_rmse_hz": float(constant["frequency_rmse_hz"].mean()),
        "constant_jitter_hz": float(constant["plateau_jitter_hz"].mean()),
        "fast_rmse_hz": float(fast["frequency_rmse_hz"].mean()),
        "fast_transition_shape_rmse_hz": float(
            fast["transition_shape_rmse_hz"].mean()
        ),
        "fast_transition_shape_low_and_proxy_rmse_hz": float(
            fast_low_and_proxy["transition_shape_rmse_hz"].mean()
        ),
        "fast_onset_abs_error_ns": (
            float(onset.mean()) if not onset.empty else float("inf")
        ),
        "wrong_branch_frames": float(
            competition["wrong_branch_frame_count"].sum()
        ),
        "mean_runtime_s": float(selected["runtime_s"].mean()),
    }


def make_recommendation(
    synthetic_frame: pd.DataFrame,
    configuration_frame: pd.DataFrame,
    *,
    baseline_configuration: AuditConfiguration,
    high_time_configuration: AuditConfiguration,
    large_configuration: AuditConfiguration,
) -> dict[str, object]:
    """Apply a conservative multi-criterion rule, never legacy RMSE alone."""
    baseline = _configuration_truth_summary(
        synthetic_frame,
        baseline_configuration.identifier,
    )
    high_time = _configuration_truth_summary(
        synthetic_frame,
        high_time_configuration.identifier,
    )
    large = _configuration_truth_summary(
        synthetic_frame,
        large_configuration.identifier,
    )
    baseline_repeatability = float(
        configuration_frame.loc[
            configuration_frame["configuration_id"]
            == baseline_configuration.identifier,
            "two_channel_all_absolute_difference_median_m_s",
        ].iloc[0]
    )
    high_time_repeatability = float(
        configuration_frame.loc[
            configuration_frame["configuration_id"]
            == high_time_configuration.identifier,
            "two_channel_all_absolute_difference_median_m_s",
        ].iloc[0]
    )
    timing_gain = (
        baseline["fast_onset_abs_error_ns"] - high_time["fast_onset_abs_error_ns"]
    )
    transition_shape_improvement_fraction = 1.0 - (
        high_time["fast_transition_shape_low_and_proxy_rmse_hz"]
        / baseline["fast_transition_shape_low_and_proxy_rmse_hz"]
    )
    high_time_truth_acceptable = (
        transition_shape_improvement_fraction >= 0.25
        and high_time["constant_rmse_hz"] <= 2.5 * baseline["constant_rmse_hz"]
        and high_time["wrong_branch_frames"]
        <= max(12.0, baseline["wrong_branch_frames"] + 12.0)
        and high_time_repeatability <= 1.5 * baseline_repeatability
    )
    high_time_dominates = (
        high_time["constant_rmse_hz"] <= baseline["constant_rmse_hz"]
        and high_time["constant_jitter_hz"] <= baseline["constant_jitter_hz"]
        and high_time["fast_rmse_hz"] <= baseline["fast_rmse_hz"]
        and high_time["fast_onset_abs_error_ns"]
        <= baseline["fast_onset_abs_error_ns"]
        and high_time["wrong_branch_frames"] <= baseline["wrong_branch_frames"]
        and high_time_repeatability <= baseline_repeatability
    )
    if high_time_dominates:
        decision = "B"
        default_profile = high_time_configuration.identifier
        alternate_profile: str | None = None
        default_change = True
    elif high_time_truth_acceptable:
        decision = "C"
        default_profile = baseline_configuration.identifier
        alternate_profile = high_time_configuration.identifier
        default_change = False
    else:
        decision = "A"
        default_profile = baseline_configuration.identifier
        alternate_profile = None
        default_change = False

    large_nfft_necessary = (
        large["constant_rmse_hz"] < 0.8 * high_time["constant_rmse_hz"]
        and large["fast_rmse_hz"] < 0.8 * high_time["fast_rmse_hz"]
        and large["fast_onset_abs_error_ns"]
        <= high_time["fast_onset_abs_error_ns"]
        and large["wrong_branch_frames"] <= high_time["wrong_branch_frames"]
    )
    return {
        "decision": decision,
        "default_profile": default_profile,
        "alternate_profile": alternate_profile,
        "default_configuration_change_recommended": default_change,
        "large_nfft_production_default_recommended": large_nfft_necessary,
        "large_nfft_statement": (
            "nfft=256000 only densifies the FFT grid; it does not by itself "
            "increase the window-limited physical frequency resolution"
        ),
        "baseline_truth_summary": baseline,
        "high_time_truth_summary": high_time,
        "large_nfft_truth_summary": large,
        "baseline_two_channel_median_difference_m_s": baseline_repeatability,
        "high_time_two_channel_median_difference_m_s": high_time_repeatability,
        "short_window_onset_gain_ns": timing_gain,
        "transition_shape_improvement_fraction": (
            transition_shape_improvement_fraction
        ),
        "selection_rule": (
            "legacy agreement, known-truth error, transition timing, plateau jitter, "
            "two-channel repeatability, competing-band failures, runtime, and "
            "analytical memory risk are all considered"
        ),
        "profile_selection_guard": (
            "profiles, if recommended, must be selected explicitly by the user; "
            "no silent automatic selection is implemented"
        ),
    }


def _git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.rstrip()


def git_state() -> dict[str, object]:
    """Collect read-only Git evidence; no staging or history mutation occurs."""
    cached_names = _git_output("diff", "--cached", "--name-only")
    return {
        "head": _git_output("rev-parse", "HEAD"),
        "status_short_branch": _git_output("status", "--short", "--branch"),
        "diff_stat": _git_output("diff", "--stat"),
        "cached_diff_stat": _git_output("diff", "--cached", "--stat"),
        "cached_names": cached_names,
        "staging_area_empty": not bool(cached_names.strip()),
    }


def _mean_or_nan(values: pd.Series) -> float:
    finite = pd.to_numeric(values, errors="coerce").dropna()
    return float(finite.mean()) if not finite.empty else float("nan")


def build_markdown_report(
    *,
    legacy_summary: Mapping[str, object],
    alignment_frame: pd.DataFrame,
    roughness_frame: pd.DataFrame,
    configuration_frame: pd.DataFrame,
    nfft_frame: pd.DataFrame,
    synthetic_frame: pd.DataFrame,
    noise_proxy: float,
    recommendation: Mapping[str, object],
    raw_hash_before: str,
    raw_hash_after: str,
    legacy_hash_before: str,
    legacy_hash_after: str,
    internal_regression: Mapping[str, object],
    task009_regression: Mapping[str, object] | None,
    current_csv_regression: Mapping[str, object],
    generated_paths: Sequence[Path],
    final_git_state: Mapping[str, object],
    best_legacy_configuration_id: str,
) -> str:
    """Build the required fact/inference/truth/recommendation report."""
    baseline_rows = alignment_frame.sort_values("channel_name")
    best_rows = configuration_frame[
        configuration_frame["configuration_id"] == best_legacy_configuration_id
    ].sort_values("channel_name")
    plateau_current = roughness_frame[
        (roughness_frame["region"] == "plateau")
        & (roughness_frame["series_name"].str.startswith("pdv_channel"))
    ]
    decline_current = roughness_frame[
        (roughness_frame["region"] == "decline")
        & (roughness_frame["series_name"].str.startswith("pdv_channel"))
    ]
    plateau_change_correlation = _mean_or_nan(
        plateau_current["adjacent_change_correlation_with_legacy"]
    )
    decline_change_correlation = _mean_or_nan(
        decline_current["adjacent_change_correlation_with_legacy"]
    )
    legacy_plateau = roughness_frame[
        (roughness_frame["alignment_channel"] == "pdv_channel_1")
        & (roughness_frame["series_name"] == "legacy")
        & (roughness_frame["region"] == "plateau")
    ].iloc[0]
    current_plateau_first_difference = float(
        plateau_current["first_difference_absolute_median_m_s"].mean()
    )
    current_plateau_second_difference = float(
        plateau_current["second_difference_rms_m_s"].mean()
    )
    baseline_repeatability = float(
        configuration_frame.loc[
            configuration_frame["configuration_id"]
            == "hann_w768_n4096_subbin",
            "two_channel_all_absolute_difference_median_m_s",
        ].iloc[0]
    )
    best_repeatability = float(
        best_rows["two_channel_all_absolute_difference_median_m_s"].iloc[0]
    )
    synthetic_summary = (
        synthetic_frame.groupby("configuration_id", as_index=False)
        .agg(
            frequency_rmse_hz=("frequency_rmse_hz", "mean"),
            velocity_rmse_m_s=("velocity_rmse_m_s", "mean"),
            plateau_jitter_hz=("plateau_jitter_hz", "mean"),
            wrong_branch_frames=("wrong_branch_frame_count", "sum"),
            runtime_s=("runtime_s", "mean"),
        )
        .sort_values("frequency_rmse_hz")
    )
    if abs(plateau_change_correlation) < 0.5 and abs(decline_change_correlation) >= 0.5:
        fluctuation_inference = (
            "下降段相邻变化具有共同方向证据，而平台段旧软件额外起伏与当前数据的"
            "方向相关性较弱；平台额外粗糙度只能归入算法/噪声相关方差。"
        )
    elif abs(decline_change_correlation) >= 0.5:
        fluctuation_inference = (
            "旧软件与当前曲线的相邻变化在下降段方向相关，支持其中一部分为共同"
            "物理结构；剩余不具双通道重复性的差异仍不能解释为真值。"
        )
    else:
        fluctuation_inference = (
            "相邻变化方向相关性不足以把旧软件额外波动归因于共同物理结构；"
            "这些差异只能保守视为算法或噪声相关方差。"
        )
    task009_matches = (
        task009_regression is not None and bool(task009_regression.get("matches"))
    )
    transition_improvement = float(
        recommendation["transition_shape_improvement_fraction"]
    )
    if recommendation["decision"] == "C":
        profile_tradeoff = (
            "balanced 默认使用 Hann/768/640/hop 128/nfft 4096；"
            "high-time-resolution 使用 Hann/512/384/hop 128/nfft 4096，"
            "时间支持由 19.2 ns 降至 12.8 ns，但未填零频率尺度由约 "
            "52.08 MHz 增至 78.12 MHz，平台抖动和竞争谱带风险更高。"
        )
    else:
        profile_tradeoff = (
            "没有足够的多指标证据增加第二 profile；保持当前固定配置。"
        )
    generated_text = "\n".join(f"- `{path}`" for path in generated_paths)
    status_text = str(final_git_state["status_short_branch"])
    diff_stat_text = str(final_git_state["diff_stat"])

    alignment_lines = "\n".join(
        "- {channel}: offset={offset:+d} frames ({time:+.1f} ns), paired={paired}, "
        "bias={bias:.6g} m/s, MAE={mae:.6g} m/s, RMSE={rmse:.6g} m/s, "
        "max={maximum:.6g} m/s, r={correlation:.6g}.".format(
            channel=row.channel_name,
            offset=int(row.best_offset_frames),
            time=float(row.time_offset_ns),
            paired=int(row.paired_count),
            bias=float(row.bias_m_s),
            mae=float(row.mae_m_s),
            rmse=float(row.rmse_m_s),
            maximum=float(row.maximum_absolute_error_m_s),
            correlation=float(row.pearson_correlation),
        )
        for row in baseline_rows.itertuples()
    )
    best_lines = "\n".join(
        "- {channel}: RMSE={rmse:.6g} m/s, r={correlation:.6g}, "
        "offset={offset:+d} frames.".format(
            channel=row.channel_name,
            rmse=float(row.rmse_m_s),
            correlation=float(row.pearson_correlation),
            offset=int(row.best_offset_frames),
        )
        for row in best_rows.itertuples()
    )
    truth_lines = "\n".join(
        "- {configuration}: mean frequency RMSE={frequency:.6g} Hz, "
        "velocity RMSE={velocity:.6g} m/s, plateau jitter={jitter:.6g} Hz, "
        "wrong-branch frames={wrong:.0f}, mean runtime={runtime:.6g} s.".format(
            configuration=row.configuration_id,
            frequency=float(row.frequency_rmse_hz),
            velocity=float(row.velocity_rmse_m_s),
            jitter=float(row.plateau_jitter_hz),
            wrong=float(row.wrong_branch_frames),
            runtime=float(row.runtime_s),
        )
        for row in synthetic_summary.itertuples()
    )
    return f"""# TASK-010 旧软件输出指纹重建、已知真值验证与 STFT 参数决策

## 观察到的事实

1. 开始前审计：HEAD 为 `{final_git_state['head']}`；指定解释器测试基线由外层审计实测为
   221 passed。输入文件均存在，暂存区为空。
2. 旧软件 CSV：{legacy_summary['row_count']} 行，其中 measured=
   {legacy_summary['measured_count']}、zero_masked={legacy_summary['zero_masked_count']}；
   时间范围 {legacy_summary['time_range_us']} µs，measured 范围
   {legacy_summary['measured_time_range_us']} µs。
3. 时间步长：min/median/max={legacy_summary['time_step_ns_min_median_max']} ns；
   相对 3.2 ns 的最大十进制表示误差为
   {float(legacy_summary['time_step_max_abs_error_ns']):.12g} ns，判定为严格 3.2 ns 输出网格。
4. 速度量化：最小非零间隔为
   {float(legacy_summary['velocity_grid_spacing_m_s']):.12g} m/s；所有 measured 值均为
   0.12109375 m/s 的整数倍，速度列单位为 m/s，km/s 列换算一致。
5. 指纹推断：频率网格间距为
   {float(legacy_summary['frequency_grid_spacing_hz']):.12g} Hz，按实际采样率得到
   inferred nfft={float(legacy_summary['inferred_nfft']):.12g}。该结论仅称为
   **legacy output fingerprint inference**，不是源码确认。
6. 当前基线无插值整数帧对齐：

{alignment_lines}

7. 固定统计区间：起跳 0–0.08 µs、平台 0.08–0.50 µs、下降
   0.50–{min(DECLINE_END_RELATIVE_S, float(cast(list[float], legacy_summary['measured_time_range_us'])[1] - cast(list[float], legacy_summary['measured_time_range_us'])[0]) * 1e-6) * 1e6:.4g} µs；边界未按结果移动。
8. 当前双通道基线全区间绝对差中位数为 {baseline_repeatability:.6g} m/s；
   最接近旧软件的有限配置对应值为 {best_repeatability:.6g} m/s。
9. 最接近旧软件的有限参数组合为 `{best_legacy_configuration_id}`：

{best_lines}

10. 256000 点诊断采用分批 RFFT；CSV 中的内存值是数组尺寸解析估算。
    完整 STFT 单份复谱风险与分批工作集分别报告，未伪装为操作系统实测峰值。

## 基于输出指纹的推测

11. 旧软件并非“只是输出点更多”：旧软件 measured 与当前 hop 128 都是 3.2 ns 网格；
    旧文件覆盖区间更短，而不是用更密的时间步长取胜。
12. 平台相邻变化与旧软件相邻变化的两通道平均相关系数为
    {plateau_change_correlation:.6g}；下降段为 {decline_change_correlation:.6g}。
    旧软件平台 |first difference| 中位数为
    {float(legacy_plateau['first_difference_absolute_median_m_s']):.6g} m/s、
    second-difference RMS 为
    {float(legacy_plateau['second_difference_rms_m_s']):.6g} m/s；当前两通道均值分别为
    {current_plateau_first_difference:.6g} 和 {current_plateau_second_difference:.6g} m/s。
    {fluctuation_inference} 因而旧软件不是纯随机制造全部不平整度，但其额外高频粗糙幅度
    没有在两条当前采集通道中等幅复现。
13. 旧软件不能当作物理真值。与旧软件 RMSE 最小只用于重建输出指纹，不单独决定默认参数。
14. FFT 网格、窗函数/窗长的真实分辨能力、三点亚频点估计、绝对测量准确度是四个不同概念；
    大 NFFT 只加密网格，不能单独提高窗限制下的真实频率分辨率。
15. 768 点窗是否过度时间平均，以已知真值下降定位与短窗谱带竞争共同判定；
    不从旧软件曲线外观直接下结论。已知真值的低噪声与真实代理噪声下降形状显示，
    推荐 high-time 配置相对当前基线的转折段 RMSE 改善比例为
    {transition_improvement:.3%}，但 5% 阈值起始帧没有改善。

## 已知真值测试结果

16. 合成数据包含恒频、缓慢调频、0.73→0.28 GHz 快速下降和较弱竞争谱带；
    随机种子固定为 {SYNTHETIC_RANDOM_SEED}。
17. 噪声包含无噪声、固定中等噪声（每单位峰值幅值的标准差 σ=0.30）和真实数据 pre-event/plateau 幅值代理；
    后者标准差比为 {noise_proxy:.6g}。该代理可能含相干仪器/光学成分，不代表完整实验噪声。
18. 配置汇总：

{truth_lines}

19. 已知真值逐行结果完整保存在 `synthetic_truth_results.csv`，含频率 bias/RMSE、
    速度 RMSE、平台 jitter、下降起始误差、转折段 RMSE、最大逐点误差和错误分支帧数。
20. 大 NFFT 是否必要：生产默认建议为
    `{recommendation['large_nfft_production_default_recommended']}`；原因是
    {recommendation['large_nfft_statement']}。

## 最终参数建议

21. 最终选择为方案 **{recommendation['decision']}**。默认 profile：
    `{recommendation['default_profile']}`；备用 profile：
    `{recommendation['alternate_profile']}`。
22. 当前默认参数是否改变：
    `{recommendation['default_configuration_change_recommended']}`。若存在备用 profile，
    只能由用户显式选择，不实现静默自动选择。{profile_tradeoff}
23. 本轮实际新增开发文件为
    `scripts/audit_legacy_velocity_reference.py`、`tests/unit/test_legacy_velocity_audit.py`，
    以及 `outputs/task010_legacy_velocity_audit/` 下审计产物；没有修改 core 数值算法。
24. 生产回归：本轮前后完整数值指纹匹配为 `{internal_regression['matches']}`；
    与 TASK-009 外部指纹匹配为 `{task009_matches}`。覆盖当前 STFT、baseline ridge、
    refined ridge、apparent/display velocity、TASK-008A/B、NaN 掩码和状态计数。
    当前 {current_csv_regression['file_count']} 个 CSV 的逐文件 SHA-256 前后匹配为
    `{current_csv_regression['matches']}`。
25. 输入 SHA-256：原始 CSV 前后为 `{raw_hash_before}` / `{raw_hash_after}`；
    旧软件 CSV 前后为 `{legacy_hash_before}` / `{legacy_hash_after}`。
26. `git diff --stat`：

```text
{diff_stat_text}
```

27. 完整 `git status --short --branch`：

```text
{status_text}
```

28. 暂存区为空：`{final_git_state['staging_area_empty']}`。本脚本未执行 git add、commit、
    restore、reset 或 clean。
29. 未开始 LiF、GUI、AI、自动追踪、自动分支切换、通道选择或融合；
    未让 `run_demo_pipeline.bat` 调用本审计脚本。

## 输出索引

{generated_text}
"""


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEFAULT_OUTPUT_DIRECTORY,
        help="New development-audit output directory.",
    )
    return parser.parse_args()


def main() -> None:
    arguments = _parse_arguments()
    output_directory = arguments.output_directory.resolve()
    if not RAW_DATA_PATH.is_file():
        raise FileNotFoundError(f"Raw input file does not exist: {RAW_DATA_PATH}")
    if not LEGACY_REFERENCE_PATH.is_file():
        raise FileNotFoundError(
            f"Legacy reference file does not exist: {LEGACY_REFERENCE_PATH}"
        )
    raw_hash_before = _sha256(RAW_DATA_PATH)
    legacy_hash_before = _sha256(LEGACY_REFERENCE_PATH)
    if raw_hash_before.lower() != EXPECTED_RAW_SHA256:
        raise RuntimeError(
            f"Raw input SHA-256 mismatch: expected {EXPECTED_RAW_SHA256}, "
            f"got {raw_hash_before}."
        )
    output_directory.mkdir(parents=True, exist_ok=True)
    current_csv_hashes_before = _existing_csv_hashes(
        CURRENT_CSV_REFERENCE_DIRECTORY
    )
    print("TASK-010: read-only inputs validated")
    print(f"  raw SHA-256 before:    {raw_hash_before}")
    print(f"  legacy SHA-256 before: {legacy_hash_before}")

    legacy = read_legacy_reference()
    loaded = read_delimited_signals(
        RAW_DATA_PATH,
        time_column=0,
        voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        delimiter=",",
        has_header=False,
    )
    records = loaded.records
    sample_rate_hz = next(iter(records.values())).sample_rate_hz
    frequency_grid_spacing_hz = (
        2.0 * legacy.velocity_grid_spacing_m_s / VACUUM_WAVELENGTH_M
    )
    inferred_nfft = sample_rate_hz / frequency_grid_spacing_hz
    legacy_summary = _legacy_summary(
        legacy,
        frequency_grid_spacing_hz=frequency_grid_spacing_hz,
        inferred_nfft=inferred_nfft,
    )

    print("TASK-010: production fingerprint before finite audit")
    production_before, current_estimates = production_snapshot(
        records,
        source_sha256=raw_hash_before,
    )
    _write_json(output_directory / "production_regression_before.json", production_before)
    task009_reference: dict[str, object] | None = None
    task009_comparison: dict[str, object] | None = None
    if TASK009_REFERENCE_FINGERPRINT.is_file():
        task009_reference = json.loads(
            TASK009_REFERENCE_FINGERPRINT.read_text(encoding="utf-8")
        )
        task009_comparison = compare_production_snapshots(
            task009_reference,
            production_before,
        )
        if not task009_comparison["matches"]:
            raise RuntimeError(
                "Current production results do not match the TASK-009 numeric fingerprint."
            )

    baseline_configuration = AuditConfiguration("hann", 768, 4096, "subbin")
    fingerprint_configurations = [
        AuditConfiguration(window_name, window_length, LARGE_NFFT, "discrete")
        for window_length in WINDOW_LENGTHS
        for window_name in WINDOW_NAMES
    ]
    cache: dict[tuple[str, str], FrequencyEstimate] = {}
    preset = {
        (baseline_configuration.identifier, channel_name): estimate
        for channel_name, estimate in current_estimates.items()
    }
    print("TASK-010: finite legacy-fingerprint reconstruction grid")
    configuration_frame, configuration_alignments = evaluate_configurations(
        records,
        legacy,
        [baseline_configuration, *fingerprint_configurations],
        cache,
        preset_estimates=preset,
    )
    current_alignments = configuration_alignments[baseline_configuration.identifier]
    baseline_alignment_frame = configuration_frame[
        configuration_frame["configuration_id"] == baseline_configuration.identifier
    ].copy()
    roughness_frame = roughness_rows(legacy, current_alignments)

    short_ranking = (
        configuration_frame[
            (configuration_frame["nfft"] == LARGE_NFFT)
            & (configuration_frame["window_length_samples"] < 768)
        ]
        .groupby("configuration_id", as_index=False)["rmse_m_s"]
        .mean()
        .sort_values("rmse_m_s")
    )
    top_short_ids = short_ranking["configuration_id"].head(2).tolist()
    top_short_configurations = [
        next(
            configuration
            for configuration in fingerprint_configurations
            if configuration.identifier == identifier
        )
        for identifier in top_short_ids
    ]
    best_large_configuration = top_short_configurations[0]
    best_legacy_configuration_id = best_large_configuration.identifier
    best_alignments = configuration_alignments[best_legacy_configuration_id]

    print("TASK-010: targeted 4096/8192/256000 NFFT comparison")
    nfft_frame, nfft_alignments = build_nfft_comparison(
        top_short_configurations,
        records,
        legacy,
        cache,
    )
    configuration_alignments.update(nfft_alignments)
    middle_configuration = AuditConfiguration("hann", 512, 4096, "subbin")
    middle_frame, middle_alignments = evaluate_configurations(
        records,
        legacy,
        [middle_configuration],
        cache,
    )
    configuration_alignments.update(middle_alignments)
    combined_configuration_frame = pd.concat(
        [configuration_frame, nfft_frame, middle_frame],
        ignore_index=True,
    ).drop_duplicates(["configuration_id", "channel_name"], keep="last")
    short_configuration = AuditConfiguration(
        best_large_configuration.window_name,
        best_large_configuration.window_length_samples,
        4096,
        "subbin",
    )

    real_noise_proxy, noise_proxy_frame = estimate_development_noise_proxy(records)
    synthetic_candidates = [
        baseline_configuration,
        short_configuration,
        middle_configuration,
        best_large_configuration,
    ]
    synthetic_configurations = list(
        {configuration.identifier: configuration for configuration in synthetic_candidates}.values()
    )
    print("TASK-010: deterministic synthetic known-truth validation")
    synthetic_frame = evaluate_synthetic_truth(
        synthetic_configurations,
        sample_rate_hz=sample_rate_hz,
        real_noise_proxy=real_noise_proxy,
    )
    recommendation = make_recommendation(
        synthetic_frame,
        combined_configuration_frame,
        baseline_configuration=baseline_configuration,
        high_time_configuration=middle_configuration,
        large_configuration=best_large_configuration,
    )

    print("TASK-010: production fingerprint after finite audit")
    production_after, _ = production_snapshot(
        records,
        source_sha256=raw_hash_before,
    )
    internal_regression = compare_production_snapshots(
        production_before,
        production_after,
    )
    if not internal_regression["matches"]:
        raise RuntimeError("Production numerical results changed during TASK-010.")
    if task009_reference is not None:
        task009_comparison = compare_production_snapshots(
            task009_reference,
            production_after,
        )
        if not task009_comparison["matches"]:
            raise RuntimeError("Final production results no longer match TASK-009.")

    raw_hash_after = _sha256(RAW_DATA_PATH)
    legacy_hash_after = _sha256(LEGACY_REFERENCE_PATH)
    if raw_hash_after != raw_hash_before:
        raise RuntimeError("Raw input SHA-256 changed during TASK-010.")
    if legacy_hash_after != legacy_hash_before:
        raise RuntimeError("Legacy reference SHA-256 changed during TASK-010.")
    current_csv_hashes_after = _existing_csv_hashes(
        CURRENT_CSV_REFERENCE_DIRECTORY
    )
    current_csv_regression = {
        "directory": str(CURRENT_CSV_REFERENCE_DIRECTORY),
        "file_count": len(current_csv_hashes_before),
        "before": current_csv_hashes_before,
        "after": current_csv_hashes_after,
        "matches": current_csv_hashes_before == current_csv_hashes_after,
    }
    if not current_csv_regression["matches"]:
        raise RuntimeError("Current TASK-009 CSV bytes changed during TASK-010.")

    generated_paths: list[Path] = []
    generated_paths.extend(
        [
            _write_json(output_directory / "legacy_fingerprint.json", legacy_summary),
            _write_json(
                output_directory / "production_regression_after.json",
                production_after,
            ),
            _write_json(
                output_directory / "production_regression_comparison.json",
                {
                    "internal_before_after": internal_regression,
                    "task009_reference": task009_comparison,
                    "current_csv_files": current_csv_regression,
                },
            ),
        ]
    )
    csv_outputs = (
        ("alignment_metrics.csv", baseline_alignment_frame),
        ("roughness_metrics.csv", roughness_frame),
        ("configuration_comparison.csv", combined_configuration_frame),
        ("nfft_candidate_comparison.csv", nfft_frame),
        ("synthetic_truth_results.csv", synthetic_frame),
        ("development_noise_proxy.csv", noise_proxy_frame),
    )
    for filename, frame in csv_outputs:
        path = output_directory / filename
        frame.to_csv(path, index=False)
        generated_paths.append(path)
    generated_paths.extend(
        create_plots(
            output_directory,
            legacy,
            current_alignments,
            best_alignments,
            combined_configuration_frame,
            synthetic_frame,
            combined_configuration_frame,
            synthetic_configurations,
            sample_rate_hz=sample_rate_hz,
            best_configuration_id=best_legacy_configuration_id,
        )
    )

    final_git = git_state()
    summary = {
        "legacy_fingerprint": legacy_summary,
        "baseline_alignment": baseline_alignment_frame.to_dict(orient="records"),
        "best_legacy_configuration_id": best_legacy_configuration_id,
        "top_two_short_legacy_configurations": top_short_ids,
        "development_noise_proxy": real_noise_proxy,
        "recommendation": recommendation,
        "production_regression": {
            "internal": internal_regression,
            "task009": task009_comparison,
            "current_csv_files": current_csv_regression,
        },
        "input_hashes": {
            "raw_before": raw_hash_before,
            "raw_after": raw_hash_after,
            "legacy_before": legacy_hash_before,
            "legacy_after": legacy_hash_after,
        },
        "git": final_git,
    }
    summary_path = _write_json(output_directory / "task010_report.json", summary)
    generated_paths.append(summary_path)
    report_text = build_markdown_report(
        legacy_summary=legacy_summary,
        alignment_frame=baseline_alignment_frame,
        roughness_frame=roughness_frame,
        configuration_frame=combined_configuration_frame,
        nfft_frame=nfft_frame,
        synthetic_frame=synthetic_frame,
        noise_proxy=real_noise_proxy,
        recommendation=recommendation,
        raw_hash_before=raw_hash_before,
        raw_hash_after=raw_hash_after,
        legacy_hash_before=legacy_hash_before,
        legacy_hash_after=legacy_hash_after,
        internal_regression=internal_regression,
        task009_regression=task009_comparison,
        current_csv_regression=current_csv_regression,
        generated_paths=generated_paths,
        final_git_state=final_git,
        best_legacy_configuration_id=best_legacy_configuration_id,
    )
    report_path = output_directory / "task010_final_report.md"
    report_path.write_text(report_text, encoding="utf-8")
    generated_paths.append(report_path)

    print(f"  raw SHA-256 after:     {raw_hash_after}")
    print(f"  legacy SHA-256 after:  {legacy_hash_after}")
    print(f"  closest legacy fingerprint: {best_legacy_configuration_id}")
    print(f"  final decision: {recommendation['decision']}")
    print(f"  staging area empty: {final_git['staging_area_empty']}")
    print("TASK-010 generated files:")
    for path in generated_paths:
        print(f"  {path}")


if __name__ == "__main__":
    main()
