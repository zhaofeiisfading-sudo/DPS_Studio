"""Development-only comparison of discrete and locally refined real-data ridges."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import matplotlib
import numpy as np
import pandas as pd
from numpy.typing import NDArray

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.axes import Axes  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import convert_ridge_to_apparent_velocity
from dps_studio.core.ridge import (
    RefinedRidgeResult,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeResult,
    extract_peak_ridge,
    refine_peak_ridge_subbin,
)
from dps_studio.core.time_frequency import STFTResult, compute_stft


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "raw" / "20260607.csv"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "ridge_refinement_preview"

WINDOW_LENGTH_SAMPLES = 768
SPARSE_OVERLAP_SAMPLES = 768
OVERLAP_SAMPLES = 640
NFFT = 4096
NFFT_STABILITY_VALUES = (2048, 4096, 8192)
WINDOW_NAME = "hann"
HOP_SAMPLES = 128
WINDOW_LENGTH_CONFIGURATIONS = ((512, 384), (768, 640), (1024, 896))

RIDGE_MINIMUM_FREQUENCY_HZ = 0.1e9
RIDGE_MAXIMUM_FREQUENCY_HZ = 2.0e9
RIDGE_START_TIME_S = 554.668e-6
ANALYSIS_END_TIME_S = 555.45e-6
PRESENTATION_PRE_EVENT_DURATION_S = 0.08e-6
STFT_DETAIL_MINIMUM_FREQUENCY_HZ = 0.2e9
STFT_DETAIL_MAXIMUM_FREQUENCY_HZ = 0.9e9
PLATEAU_START_RELATIVE_S = 0.08e-6
PLATEAU_END_RELATIVE_S = 0.50e-6
DECLINE_START_RELATIVE_S = PLATEAU_END_RELATIVE_S
DECLINE_END_RELATIVE_S = ANALYSIS_END_TIME_S - RIDGE_START_TIME_S

DEMO_VACUUM_WAVELENGTH_M = 1550e-9
DEMO_NOTICE = (
    "temporary demo wavelength 1550 nm; not a confirmed experiment parameter; "
    "unsigned apparent velocity; no LiF correction; development preview only"
)
PRESENTATION_NOTICE = (
    "temporary 1550 nm; unsigned apparent velocity; no LiF correction"
)
SPECTROGRAM_NOTICE = (
    "no preprocessing; no temporal smoothing; development preview"
)

FULL_DISPLAY_LINE_WIDTH = 0.80
PRESENTATION_LINE_WIDTH = 0.80
TWO_CHANNEL_LINE_WIDTH = 0.75
DISCRETE_REFINED_LINE_WIDTH = 0.70
PLATEAU_DETAIL_LINE_WIDTH = 0.50
PLATEAU_DETAIL_MARKER_SIZE = 1.5
DECLINE_DETAIL_LINE_WIDTH = 0.50
DECLINE_DETAIL_MARKER_SIZE = 1.5
STFT_DISCRETE_RIDGE_LINE_WIDTH = 0.70
STFT_REFINED_RIDGE_LINE_WIDTH = 0.85
MAIN_DISPLAY_DPI = 300

FloatArray = NDArray[np.float64]


@dataclass(frozen=True, slots=True)
class ChannelAnalysis:
    """Development-only results needed for plots and reporting."""

    stft_result: STFTResult
    ridge_result: RidgeResult
    refined_result: RefinedRidgeResult
    discrete_velocity_m_s: FloatArray
    refined_velocity_m_s: FloatArray
    display_velocity_m_s: FloatArray
    velocity_origins: list[str]


@dataclass(frozen=True, slots=True)
class SeriesDetailStatistics:
    """Development-only local variation statistics for one velocity series."""

    valid_frame_count: int
    first_difference_absolute_median_m_s: float
    first_difference_absolute_p95_m_s: float
    first_difference_standard_deviation_m_s: float
    second_difference_rms_m_s: float
    velocity_min_m_s: float
    velocity_max_m_s: float
    velocity_span_m_s: float


@dataclass(frozen=True, slots=True)
class PairedChannelStatistics:
    """Development-only repeatability statistics for two acquisition channels."""

    paired_frame_count: int
    absolute_difference_median_m_s: float
    absolute_difference_p95_m_s: float
    absolute_difference_maximum_m_s: float
    pearson_correlation: float


def _plot_complete_series(
    axis: Axes,
    x_values: FloatArray,
    y_values: FloatArray,
    *,
    linewidth: float,
    label: str | None = None,
    color: str | None = None,
    linestyle: str | None = None,
    marker: str | None = None,
    markersize: float | None = None,
) -> Line2D:
    """Plot one complete display array without dropping or replacing points."""
    x_array = np.asarray(x_values)
    y_array = np.asarray(y_values)
    if x_array.ndim != 1 or y_array.ndim != 1 or x_array.shape != y_array.shape:
        raise ValueError("Plot x/y arrays must be one-dimensional with identical shape.")

    (line,) = axis.plot(x_array, y_array)
    line.set_linewidth(linewidth)
    if label is not None:
        line.set_label(label)
    if color is not None:
        line.set_color(color)
    if linestyle is not None:
        line.set_linestyle(linestyle)
    if marker is not None:
        line.set_marker(marker)
    if markersize is not None:
        line.set_markersize(markersize)

    plotted_x = np.asarray(line.get_xdata(orig=True))
    plotted_y = np.asarray(line.get_ydata(orig=True))
    if not np.array_equal(plotted_x, x_array, equal_nan=True) or not np.array_equal(
        plotted_y,
        y_array,
        equal_nan=True,
    ):
        raise RuntimeError("Matplotlib Line2D did not retain every supplied display point.")
    return line


def _save_figure_without_path_simplification(
    figure: Figure,
    output_path: Path,
    *,
    dpi: int,
) -> None:
    """Render a line figure with path simplification disabled only for this save."""
    with matplotlib.rc_context({"path.simplify": False}):
        figure.savefig(output_path, dpi=dpi)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_stft_magnitude_db(
    magnitude: FloatArray,
    *,
    reference_maximum: float | None = None,
    floor_db: float = -60.0,
) -> FloatArray:
    """Build a plot-only relative-dB array without mutating STFT data."""
    maximum = (
        float(np.max(magnitude))
        if reference_maximum is None
        else float(reference_maximum)
    )
    if not np.isfinite(maximum) or maximum <= 0.0:
        raise ValueError("STFT magnitude reference must be finite and positive.")
    if not np.isfinite(floor_db) or floor_db >= 0.0:
        raise ValueError("STFT display floor must be finite and negative.")
    display_floor = maximum * float(np.power(10.0, floor_db / 20.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        return 20.0 * np.log10(np.maximum(magnitude, display_floor) / maximum)


def _convert_refined_velocity(result: RefinedRidgeResult) -> FloatArray:
    """Use TASK-006 while preserving NaN for unavailable candidate refinements."""
    candidate_mask = np.fromiter(
        (flag is RidgeQualityFlag.CANDIDATE for flag in result.quality_flags),
        dtype=np.bool_,
        count=len(result.quality_flags),
    )
    refined_mask = np.fromiter(
        (
            status is RidgeRefinementStatus.REFINED
            for status in result.refinement_statuses
        ),
        dtype=np.bool_,
        count=len(result.refinement_statuses),
    )
    if np.all(~candidate_mask | refined_mask):
        refined_frequency_as_ridge = RidgeResult(
            time_s=result.time_s,
            frequency_hz=result.refined_frequency_hz,
            peak_magnitude=result.peak_magnitude,
            quality_flags=result.quality_flags,
            minimum_frequency_hz=result.minimum_frequency_hz,
            maximum_frequency_hz=result.maximum_frequency_hz,
            event_start_time_s=result.event_start_time_s,
            analysis_end_time_s=result.analysis_end_time_s,
            source_path=result.source_path,
        )
        converted = convert_ridge_to_apparent_velocity(
            refined_frequency_as_ridge,
            vacuum_wavelength_m=DEMO_VACUUM_WAVELENGTH_M,
        )
        return converted.apparent_velocity_m_s.copy()

    velocity_m_s = np.full(result.time_s.shape, np.nan, dtype=np.float64)
    for frame_index in np.flatnonzero(refined_mask):
        index = int(frame_index)
        refined_frequency_as_ridge = RidgeResult(
            time_s=result.time_s[index : index + 1],
            frequency_hz=result.refined_frequency_hz[index : index + 1],
            peak_magnitude=result.peak_magnitude[index : index + 1],
            quality_flags=(RidgeQualityFlag.CANDIDATE,),
            minimum_frequency_hz=result.minimum_frequency_hz,
            maximum_frequency_hz=result.maximum_frequency_hz,
            event_start_time_s=None,
            analysis_end_time_s=None,
            source_path=result.source_path,
        )
        converted = convert_ridge_to_apparent_velocity(
            refined_frequency_as_ridge,
            vacuum_wavelength_m=DEMO_VACUUM_WAVELENGTH_M,
        )
        velocity_m_s[index] = converted.apparent_velocity_m_s[0]
    return velocity_m_s


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


def _finite_unique_count(values: FloatArray) -> int:
    return int(np.unique(values[np.isfinite(values)]).size)


def _three_number_summary(label: str, values: FloatArray) -> None:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        print(f"  {label}: unavailable (no finite paired values)")
        return
    print(
        f"  {label}: min={float(np.min(finite)):.12g}, "
        f"median={float(np.median(finite)):.12g}, "
        f"max={float(np.max(finite)):.12g}"
    )


def _print_channel_statistics(
    channel_name: str,
    result: RefinedRidgeResult,
    discrete_velocity_m_s: FloatArray,
    refined_velocity_m_s: FloatArray,
) -> None:
    candidate_count = sum(
        flag is RidgeQualityFlag.CANDIDATE for flag in result.quality_flags
    )
    refined_count = sum(
        status is RidgeRefinementStatus.REFINED
        for status in result.refinement_statuses
    )
    status_counts = Counter(status.value for status in result.refinement_statuses)
    success_rate = 100.0 * refined_count / candidate_count if candidate_count else np.nan
    paired_frequency_mask = np.isfinite(result.refined_frequency_hz)
    paired_velocity_mask = np.isfinite(refined_velocity_m_s)

    print(f"\n{channel_name}")
    print(f"  total frames: {result.time_s.size}")
    print(f"  CANDIDATE frames: {candidate_count}")
    print(f"  REFINED successes: {refined_count}")
    print(f"  refinement status counts: {dict(sorted(status_counts.items()))}")
    print(f"  refined success rate: {success_rate:.6f}%")
    print(
        "  discrete/refined frequency unique finite values: "
        f"{_finite_unique_count(result.discrete_frequency_hz)}/"
        f"{_finite_unique_count(result.refined_frequency_hz)}"
    )
    print(
        "  discrete/refined velocity unique finite values: "
        f"{_finite_unique_count(discrete_velocity_m_s)}/"
        f"{_finite_unique_count(refined_velocity_m_s)}"
    )
    _three_number_summary("frequency_bin_offset", result.frequency_bin_offset)
    _three_number_summary(
        "refined - discrete frequency (Hz)",
        result.refined_frequency_hz[paired_frequency_mask]
        - result.discrete_frequency_hz[paired_frequency_mask],
    )
    _three_number_summary(
        "refined - discrete velocity (m/s)",
        refined_velocity_m_s[paired_velocity_mask]
        - discrete_velocity_m_s[paired_velocity_mask],
    )
    _three_number_summary("refined velocity (m/s)", refined_velocity_m_s)


def _write_csv(
    output_directory: Path,
    channel_name: str,
    stft_result: STFTResult,
    result: RefinedRidgeResult,
    discrete_velocity_m_s: FloatArray,
    refined_velocity_m_s: FloatArray,
    display_velocity_m_s: FloatArray,
    velocity_origins: list[str],
) -> Path:
    output_path = output_directory / f"{channel_name}_refined_ridge_velocity.csv"
    frame = pd.DataFrame(
        {
            "channel_name": channel_name,
            "window_name": stft_result.window_name,
            "window_length_samples": stft_result.window_length_samples,
            "overlap_samples": stft_result.overlap_samples,
            "hop_samples": stft_result.hop_samples,
            "nfft": stft_result.nfft,
            "time_absolute_s": result.time_s,
            "time_relative_s": result.time_s - RIDGE_START_TIME_S,
            "quality_flag": [flag.value for flag in result.quality_flags],
            "refinement_status": [
                status.value for status in result.refinement_statuses
            ],
            "discrete_frequency_bin_index": result.discrete_frequency_bin_index,
            "discrete_frequency_hz": result.discrete_frequency_hz,
            "refined_frequency_hz": result.refined_frequency_hz,
            "frequency_bin_offset": result.frequency_bin_offset,
            "peak_magnitude": result.peak_magnitude,
            "discrete_apparent_velocity_m_s": discrete_velocity_m_s,
            "refined_apparent_velocity_m_s": refined_velocity_m_s,
            "display_velocity_m_s": display_velocity_m_s,
            "velocity_origin": velocity_origins,
        }
    )
    frame.to_csv(output_path, index=False)
    return output_path


def _save_frequency_plot(
    output_directory: Path,
    channel_name: str,
    result: RefinedRidgeResult,
) -> Path:
    output_path = (
        output_directory / f"{channel_name}_discrete_vs_refined_frequency.png"
    )
    time_us = (result.time_s - RIDGE_START_TIME_S) * 1.0e6
    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.90, bottom=0.20)
    _plot_complete_series(
        axis,
        time_us,
        result.discrete_frequency_hz / 1.0e9,
        label="discrete bin frequency",
        linewidth=DISCRETE_REFINED_LINE_WIDTH,
        marker=".",
        markersize=PLATEAU_DETAIL_MARKER_SIZE,
    )
    _plot_complete_series(
        axis,
        time_us,
        result.refined_frequency_hz / 1.0e9,
        label="refined sub-bin frequency",
        linewidth=DISCRETE_REFINED_LINE_WIDTH,
    )
    axis.set_title(f"{channel_name}: discrete vs refined frequency")
    axis.set_xlabel("Time relative to configured ridge start (µs)")
    axis.set_ylabel("Beat frequency (GHz)")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.text(0.5, 0.025, DEMO_NOTICE, ha="center", fontsize=7)
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=MAIN_DISPLAY_DPI,
    )
    plt.close(figure)
    return output_path


def _save_velocity_plot(
    output_directory: Path,
    channel_name: str,
    result: RefinedRidgeResult,
    discrete_velocity_m_s: FloatArray,
    refined_velocity_m_s: FloatArray,
    display_velocity_m_s: FloatArray,
) -> Path:
    output_path = (
        output_directory / f"{channel_name}_discrete_vs_refined_velocity.png"
    )
    time_us = (result.time_s - RIDGE_START_TIME_S) * 1.0e6
    pre_event_mask = np.fromiter(
        (flag is RidgeQualityFlag.PRE_EVENT for flag in result.quality_flags),
        dtype=np.bool_,
        count=len(result.quality_flags),
    )
    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.90, bottom=0.20)
    _plot_complete_series(
        axis,
        time_us,
        discrete_velocity_m_s,
        label="discrete candidate apparent velocity",
        linewidth=DISCRETE_REFINED_LINE_WIDTH,
        marker=".",
        markersize=PLATEAU_DETAIL_MARKER_SIZE,
    )
    _plot_complete_series(
        axis,
        time_us,
        refined_velocity_m_s,
        label="refined candidate apparent velocity",
        linewidth=DISCRETE_REFINED_LINE_WIDTH,
    )
    _plot_complete_series(
        axis,
        time_us[pre_event_mask],
        display_velocity_m_s[pre_event_mask],
        label="assumed pre-event zero (display only)",
        linestyle="--",
        linewidth=DISCRETE_REFINED_LINE_WIDTH,
    )
    axis.set_title(f"{channel_name}: discrete vs refined unsigned apparent velocity")
    axis.set_xlabel("Time relative to configured ridge start (µs)")
    axis.set_ylabel("Unsigned apparent velocity (m/s)")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.text(0.5, 0.025, DEMO_NOTICE, ha="center", fontsize=7)
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=MAIN_DISPLAY_DPI,
    )
    plt.close(figure)
    return output_path


def _display_interval_mask(result: RefinedRidgeResult) -> NDArray[np.bool_]:
    return np.fromiter(
        (
            flag is not RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW
            for flag in result.quality_flags
        ),
        dtype=np.bool_,
        count=len(result.quality_flags),
    )


def _save_full_display_plot(
    output_directory: Path,
    channel_name: str,
    result: RefinedRidgeResult,
    display_velocity_m_s: FloatArray,
) -> Path:
    """Plot every display frame without changing masked core values."""
    output_path = output_directory / f"{channel_name}_full_display_velocity.png"
    time_us = (result.time_s - result.time_s[0]) * 1.0e6

    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.20)
    _plot_complete_series(
        axis,
        time_us,
        display_velocity_m_s,
        color="tab:blue",
        linewidth=FULL_DISPLAY_LINE_WIDTH,
        label="full display velocity",
    )
    axis.set_xlim(float(time_us[0]), float(time_us[-1]))
    axis.set_title(f"{channel_name}: full display velocity")
    axis.set_xlabel("Time from first displayed frame (µs)")
    axis.set_ylabel("Display velocity (m/s)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.text(0.5, 0.025, DEMO_NOTICE, ha="center", fontsize=7)
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=MAIN_DISPLAY_DPI,
    )
    plt.close(figure)
    return output_path


def _presentation_interval_mask(result: RefinedRidgeResult) -> NDArray[np.bool_]:
    flags = result.quality_flags
    pre_event = np.fromiter(
        (flag is RidgeQualityFlag.PRE_EVENT for flag in flags),
        dtype=np.bool_,
        count=len(flags),
    )
    candidate = np.fromiter(
        (flag is RidgeQualityFlag.CANDIDATE for flag in flags),
        dtype=np.bool_,
        count=len(flags),
    )
    recent_pre_event = pre_event & (
        result.time_s >= RIDGE_START_TIME_S - PRESENTATION_PRE_EVENT_DURATION_S
    )
    return recent_pre_event | candidate


def _save_presentation_velocity_plot(
    output_directory: Path,
    channel_name: str,
    result: RefinedRidgeResult,
    display_velocity_m_s: FloatArray,
) -> Path:
    """Apply a display-only 0.08 µs pre-event viewport in km/s."""
    output_path = output_directory / f"{channel_name}_presentation_velocity.png"
    selected = _presentation_interval_mask(result)
    selected_time_s = result.time_s[selected]
    time_us = (selected_time_s - selected_time_s[0]) * 1.0e6

    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.90, bottom=0.20)
    _plot_complete_series(
        axis,
        time_us,
        display_velocity_m_s[selected] / 1.0e3,
        color="tab:blue",
        linewidth=PRESENTATION_LINE_WIDTH,
        label="display apparent velocity",
    )
    axis.set_xlim(left=0.0)
    axis.set_title(f"{channel_name} apparent velocity")
    axis.set_xlabel("Time from first displayed frame (µs)")
    axis.set_ylabel("Unsigned apparent velocity (km/s)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.text(0.5, 0.025, PRESENTATION_NOTICE, ha="center", fontsize=8)
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=MAIN_DISPLAY_DPI,
    )
    plt.close(figure)
    return output_path


def _save_presentation_with_plateau_detail(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
) -> Path:
    """Show the main 768-point presentation and its raw plateau frames."""
    output_path = (
        output_directory
        / f"{channel_name}_presentation_with_plateau_detail.png"
    )
    result = analysis.refined_result
    selected = _presentation_interval_mask(result)
    selected_time_s = result.time_s[selected]
    presentation_time_us = (selected_time_s - selected_time_s[0]) * 1.0e6
    presentation_velocity_km_s = analysis.display_velocity_m_s[selected] / 1.0e3

    relative_time_us = (result.time_s - RIDGE_START_TIME_S) * 1.0e6
    plateau_mask = (
        (relative_time_us >= PLATEAU_START_RELATIVE_S * 1.0e6)
        & (relative_time_us <= PLATEAU_END_RELATIVE_S * 1.0e6)
        & _refined_frame_mask(result)
        & np.isfinite(analysis.refined_velocity_m_s)
    )
    plateau_velocity_km_s = analysis.refined_velocity_m_s[plateau_mask] / 1.0e3
    if plateau_velocity_km_s.size == 0:
        raise RuntimeError(f"No refined plateau frames available for {channel_name}.")
    plateau_minimum = float(np.min(plateau_velocity_km_s))
    plateau_maximum = float(np.max(plateau_velocity_km_s))
    plateau_span = plateau_maximum - plateau_minimum
    plateau_padding = max(
        plateau_span * 0.08,
        abs(plateau_maximum) * 0.002,
        1.0e-4,
    )
    presentation_maximum = float(
        np.nanmax(presentation_velocity_km_s)
    )

    figure, axes = plt.subplots(2, 1, figsize=(10.0, 8.0))
    figure.subplots_adjust(
        left=0.10,
        right=0.98,
        top=0.90,
        bottom=0.12,
        hspace=0.30,
    )
    _plot_complete_series(
        axes[0],
        presentation_time_us,
        presentation_velocity_km_s,
        color="tab:blue",
        linewidth=PRESENTATION_LINE_WIDTH,
        label="display apparent velocity",
    )
    axes[0].set_xlim(left=0.0)
    axes[0].set_ylim(0.0, max(0.6, presentation_maximum * 1.05))
    axes[0].set_title("Presentation velocity with pre-event zero platform")
    axes[0].set_xlabel("Time from first displayed frame (\N{MICRO SIGN}s)")
    axes[0].set_ylabel("Unsigned apparent velocity (km/s)")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best")

    _plot_complete_series(
        axes[1],
        relative_time_us[plateau_mask],
        plateau_velocity_km_s,
        color="tab:blue",
        linewidth=PLATEAU_DETAIL_LINE_WIDTH,
        marker="o",
        markersize=PLATEAU_DETAIL_MARKER_SIZE,
        label="raw refined frames",
    )
    axes[1].set_xlim(
        PLATEAU_START_RELATIVE_S * 1.0e6,
        PLATEAU_END_RELATIVE_S * 1.0e6,
    )
    axes[1].set_ylim(
        plateau_minimum - plateau_padding,
        plateau_maximum + plateau_padding,
    )
    axes[1].set_title("Plateau detail: every marker is one refined frame")
    axes[1].set_xlabel(
        "Time relative to configured ridge start (\N{MICRO SIGN}s)"
    )
    axes[1].set_ylabel("Unsigned apparent velocity (km/s)")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best")
    figure.suptitle(
        f"{channel_name} | window 768 | overlap 640 | hop 128 | nfft 4096"
    )
    figure.text(
        0.5,
        0.025,
        PRESENTATION_NOTICE + "; no smoothing or interpolation",
        ha="center",
        fontsize=8,
    )
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=MAIN_DISPLAY_DPI,
    )
    plt.close(figure)
    return output_path


def _save_decline_detail(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
) -> Path:
    """Show every refined point in the fixed decline viewport without data changes."""
    output_path = output_directory / f"{channel_name}_decline_detail.png"
    result = analysis.refined_result
    relative_time_us = (result.time_s - RIDGE_START_TIME_S) * 1.0e6
    decline_mask = (
        (relative_time_us >= DECLINE_START_RELATIVE_S * 1.0e6)
        & (relative_time_us <= DECLINE_END_RELATIVE_S * 1.0e6)
        & _refined_frame_mask(result)
        & np.isfinite(analysis.refined_velocity_m_s)
    )
    decline_velocity_km_s = analysis.refined_velocity_m_s[decline_mask] / 1.0e3
    if decline_velocity_km_s.size == 0:
        raise RuntimeError(f"No refined decline frames available for {channel_name}.")
    decline_minimum = float(np.min(decline_velocity_km_s))
    decline_maximum = float(np.max(decline_velocity_km_s))
    decline_span = decline_maximum - decline_minimum
    decline_padding = max(
        decline_span * 0.05,
        abs(decline_maximum) * 0.002,
        1.0e-4,
    )

    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.10, right=0.98, top=0.88, bottom=0.20)
    _plot_complete_series(
        axis,
        relative_time_us[decline_mask],
        decline_velocity_km_s,
        color="tab:blue",
        linewidth=DECLINE_DETAIL_LINE_WIDTH,
        marker="o",
        markersize=DECLINE_DETAIL_MARKER_SIZE,
        label="raw refined frames",
    )
    axis.set_xlim(
        DECLINE_START_RELATIVE_S * 1.0e6,
        DECLINE_END_RELATIVE_S * 1.0e6,
    )
    axis.set_ylim(
        decline_minimum - decline_padding,
        decline_maximum + decline_padding,
    )
    axis.set_title(f"{channel_name}: decline detail (every refined frame)")
    axis.set_xlabel("Time relative to configured ridge start (\N{MICRO SIGN}s)")
    axis.set_ylabel("Unsigned apparent velocity (km/s)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.text(
        0.5,
        0.025,
        PRESENTATION_NOTICE + "; viewport only; no smoothing or interpolation",
        ha="center",
        fontsize=8,
    )
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=MAIN_DISPLAY_DPI,
    )
    plt.close(figure)
    return output_path


def _save_stft_spectrogram(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
) -> Path:
    """Render the already-computed main STFT without spectral image smoothing."""
    output_path = (
        output_directory
        / f"{channel_name}_stft_spectrogram_with_refined_ridge.png"
    )
    stft_result = analysis.stft_result
    band_mask = (
        (stft_result.frequency_hz >= RIDGE_MINIMUM_FREQUENCY_HZ)
        & (stft_result.frequency_hz <= RIDGE_MAXIMUM_FREQUENCY_HZ)
    )
    magnitude = np.abs(stft_result.spectrum[band_mask, :])
    maximum_magnitude = float(np.max(magnitude))
    if not np.isfinite(maximum_magnitude) or maximum_magnitude <= 0.0:
        raise RuntimeError(
            f"Cannot render {channel_name} STFT: displayed magnitude has no "
            "finite positive maximum."
        )
    relative_db = _relative_stft_magnitude_db(magnitude)

    time_us = (stft_result.time_s - RIDGE_START_TIME_S) * 1.0e6
    frequency_ghz = stft_result.frequency_hz[band_mask] * 1.0e-9
    ridge_time_us = (
        analysis.refined_result.time_s - RIDGE_START_TIME_S
    ) * 1.0e6
    discrete_frequency_ghz = (
        analysis.refined_result.discrete_frequency_hz * 1.0e-9
    )
    refined_frequency_ghz = (
        analysis.refined_result.refined_frequency_hz * 1.0e-9
    )
    analysis_end_us = (ANALYSIS_END_TIME_S - RIDGE_START_TIME_S) * 1.0e6

    figure, axes = plt.subplots(
        2,
        1,
        figsize=(11.0, 8.0),
        sharex=True,
        gridspec_kw={"height_ratios": (1.0, 1.0)},
    )
    figure.subplots_adjust(
        left=0.09,
        right=0.88,
        top=0.89,
        bottom=0.12,
        hspace=0.18,
    )
    mesh = None
    for panel_index, axis in enumerate(axes):
        mesh = axis.pcolormesh(
            time_us,
            frequency_ghz,
            relative_db,
            shading="auto",
            cmap="viridis",
            vmin=-60.0,
            vmax=0.0,
        )
        _plot_complete_series(
            axis,
            ridge_time_us,
            discrete_frequency_ghz,
            color="white",
            linestyle="--",
            linewidth=STFT_DISCRETE_RIDGE_LINE_WIDTH,
            marker=".",
            markersize=PLATEAU_DETAIL_MARKER_SIZE,
            label="TASK-005 discrete ridge" if panel_index == 1 else None,
        )
        _plot_complete_series(
            axis,
            ridge_time_us,
            refined_frequency_ghz,
            color="red",
            linewidth=STFT_REFINED_RIDGE_LINE_WIDTH,
            label="TASK-007 refined ridge" if panel_index == 1 else None,
        )
        axis.axvline(
            0.0,
            color="white",
            linestyle=":",
            linewidth=1.0,
            label="configured ridge start" if panel_index == 1 else None,
        )
        axis.axvline(
            analysis_end_us,
            color="white",
            linestyle="-.",
            linewidth=1.0,
            label="analysis end" if panel_index == 1 else None,
        )
        axis.set_ylabel("Beat frequency (GHz)")

    axes[0].set_ylim(
        RIDGE_MINIMUM_FREQUENCY_HZ * 1.0e-9,
        RIDGE_MAXIMUM_FREQUENCY_HZ * 1.0e-9,
    )
    axes[0].set_title("Full analysis band: 0.1–2.0 GHz")
    axes[1].set_ylim(
        STFT_DETAIL_MINIMUM_FREQUENCY_HZ * 1.0e-9,
        STFT_DETAIL_MAXIMUM_FREQUENCY_HZ * 1.0e-9,
    )
    axes[1].set_title("Main ridge detail: 0.2–0.9 GHz")
    axes[1].set_xlabel("Time relative to configured ridge start (µs)")
    axes[1].legend(loc="upper right", fontsize=8)
    figure.suptitle(
        f"{channel_name} STFT | {stft_result.window_name.title()} window | "
        f"window length {stft_result.window_length_samples} | "
        f"overlap {stft_result.overlap_samples} | nfft {stft_result.nfft}"
    )
    if mesh is None:
        raise RuntimeError("STFT spectrogram rendering did not create a mesh.")
    colorbar = figure.colorbar(mesh, ax=axes, pad=0.02)
    colorbar.set_label("Relative STFT magnitude (dB)")
    figure.text(0.5, 0.025, SPECTROGRAM_NOTICE, ha="center", fontsize=8)
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=MAIN_DISPLAY_DPI,
    )
    plt.close(figure)
    return output_path


def _save_clean_stft_detail(
    output_directory: Path,
    channel_name: str,
    stft_result: STFTResult,
) -> Path:
    """Render the main STFT alone on an absolute-time axis."""
    output_path = output_directory / f"{channel_name}_stft_detail.png"
    band_mask = (
        (stft_result.frequency_hz >= 0.0)
        & (stft_result.frequency_hz <= RIDGE_MAXIMUM_FREQUENCY_HZ)
    )
    magnitude = np.abs(stft_result.spectrum[band_mask, :])
    relative_db = _relative_stft_magnitude_db(magnitude)
    absolute_time_us = stft_result.time_s * 1.0e6
    frequency_ghz = stft_result.frequency_hz[band_mask] * 1.0e-9

    figure, axis = plt.subplots(figsize=(10.5, 5.8))
    figure.subplots_adjust(left=0.09, right=0.87, top=0.88, bottom=0.18)
    mesh = axis.pcolormesh(
        absolute_time_us,
        frequency_ghz,
        relative_db,
        shading="auto",
        cmap="viridis",
        vmin=-60.0,
        vmax=0.0,
    )
    axis.set_ylim(0.0, 2.0)
    axis.set_title(
        f"{channel_name} STFT | {stft_result.window_name.title()} | "
        f"window {stft_result.window_length_samples} | "
        f"overlap {stft_result.overlap_samples} | nfft {stft_result.nfft}"
    )
    axis.set_xlabel("Absolute time (\N{MICRO SIGN}s)")
    axis.set_ylabel("Beat frequency (GHz)")
    colorbar = figure.colorbar(mesh, ax=axis, pad=0.02)
    colorbar.set_label("STFT magnitude (dB)")
    figure.text(
        0.5,
        0.035,
        "relative to displayed maximum; no ridge overlay; no smoothing, "
        "interpolation, filtering, or denoising; development preview",
        ha="center",
        fontsize=8,
    )
    figure.savefig(output_path, dpi=220)
    plt.close(figure)
    return output_path


def _save_overlap_density_plot(
    output_directory: Path,
    channel_name: str,
    analyses_by_overlap: Mapping[int, Mapping[str, ChannelAnalysis]],
) -> Path:
    output_path = (
        output_directory
        / f"{channel_name}_overlap_768_vs_896_display_velocity.png"
    )
    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.20)
    for overlap_samples, channel_analyses in analyses_by_overlap.items():
        analysis = channel_analyses[channel_name]
        selected = _display_interval_mask(analysis.refined_result)
        selected_time_s = analysis.refined_result.time_s[selected]
        time_us = (selected_time_s - selected_time_s[0]) * 1.0e6
        time_step_ns = _time_step_ns(analysis.stft_result)
        axis.plot(
            time_us,
            analysis.display_velocity_m_s[selected],
            linewidth=1.2,
            label=(
                f"overlap={overlap_samples}, "
                f"frame step={time_step_ns:.6g} ns"
            ),
        )
    axis.set_xlim(left=0.0)
    axis.set_title(
        f"{channel_name}: frame-density comparison\n"
        "Higher overlap increases time sampling density, not true time resolution"
    )
    axis.set_xlabel("Time from first displayed frame (µs)")
    axis.set_ylabel("Display velocity (m/s)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.text(0.5, 0.025, DEMO_NOTICE, ha="center", fontsize=7)
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=180,
    )
    plt.close(figure)
    return output_path


def _save_two_channel_presentation_plot(
    output_directory: Path,
    analyses: Mapping[str, ChannelAnalysis],
) -> Path:
    output_path = output_directory / "two_channel_presentation_velocity.png"
    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.90, bottom=0.20)
    for channel_name, analysis in analyses.items():
        result = analysis.refined_result
        selected = _presentation_interval_mask(result)
        selected_time_s = result.time_s[selected]
        time_us = (selected_time_s - selected_time_s[0]) * 1.0e6
        _plot_complete_series(
            axis,
            time_us,
            analysis.display_velocity_m_s[selected] / 1.0e3,
            label=channel_name,
            linewidth=TWO_CHANNEL_LINE_WIDTH,
        )
    axis.set_xlim(left=0.0)
    axis.set_title("Two acquisition channels: apparent velocity comparison")
    axis.set_xlabel("Time from first displayed frame (µs)")
    axis.set_ylabel("Unsigned apparent velocity (km/s)")
    axis.grid(alpha=0.25)
    axis.legend()
    figure.text(0.5, 0.025, PRESENTATION_NOTICE, ha="center", fontsize=8)
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=MAIN_DISPLAY_DPI,
    )
    plt.close(figure)
    return output_path


def _time_step_ns(stft_result: STFTResult) -> float:
    if stft_result.time_s.size < 2:
        return float("nan")
    return float(np.median(np.diff(stft_result.time_s)) * 1.0e9)


def _candidate_count(result: RefinedRidgeResult) -> int:
    return sum(flag is RidgeQualityFlag.CANDIDATE for flag in result.quality_flags)


def _refined_count(result: RefinedRidgeResult) -> int:
    return sum(
        status is RidgeRefinementStatus.REFINED
        for status in result.refinement_statuses
    )


def _analyze_configuration(
    records: Mapping[str, SignalRecord],
    window_length_samples: int,
    overlap_samples: int,
    nfft: int,
) -> tuple[dict[str, ChannelAnalysis], float]:
    start_time = perf_counter()
    analyses: dict[str, ChannelAnalysis] = {}
    for channel_name, record in records.items():
        stft_result = compute_stft(
            record,
            window_length_samples=window_length_samples,
            overlap_samples=overlap_samples,
            nfft=nfft,
            window_name=WINDOW_NAME,
        )
        ridge_result = extract_peak_ridge(
            stft_result,
            minimum_frequency_hz=RIDGE_MINIMUM_FREQUENCY_HZ,
            maximum_frequency_hz=RIDGE_MAXIMUM_FREQUENCY_HZ,
            event_start_time_s=RIDGE_START_TIME_S,
            analysis_end_time_s=ANALYSIS_END_TIME_S,
        )
        refined_result = refine_peak_ridge_subbin(stft_result, ridge_result)
        discrete_velocity_m_s = convert_ridge_to_apparent_velocity(
            ridge_result,
            vacuum_wavelength_m=DEMO_VACUUM_WAVELENGTH_M,
        ).apparent_velocity_m_s
        refined_velocity_m_s = _convert_refined_velocity(refined_result)
        display_velocity_m_s, velocity_origins = _display_velocity(
            refined_result,
            refined_velocity_m_s,
        )
        analyses[channel_name] = ChannelAnalysis(
            stft_result=stft_result,
            ridge_result=ridge_result,
            refined_result=refined_result,
            discrete_velocity_m_s=discrete_velocity_m_s,
            refined_velocity_m_s=refined_velocity_m_s,
            display_velocity_m_s=display_velocity_m_s,
            velocity_origins=velocity_origins,
        )
    return analyses, perf_counter() - start_time


def _print_overlap_statistics(
    overlap_samples: int,
    analyses: Mapping[str, ChannelAnalysis],
    runtime_s: float,
) -> None:
    print(f"\nOverlap configuration: {overlap_samples} samples")
    print(f"  two-channel analysis runtime: {runtime_s:.6f} s")
    for channel_name, analysis in analyses.items():
        print(
            f"  {channel_name}: total STFT frames={analysis.stft_result.time_s.size}, "
            f"CANDIDATE frames={_candidate_count(analysis.refined_result)}, "
            f"time step={_time_step_ns(analysis.stft_result):.9g} ns, "
            f"REFINED frames={_refined_count(analysis.refined_result)}"
        )


def _write_overlap_statistics_csv(
    output_directory: Path,
    analyses_by_overlap: Mapping[int, Mapping[str, ChannelAnalysis]],
    runtimes_by_overlap: Mapping[int, float],
) -> Path:
    output_path = output_directory / "overlap_density_comparison.csv"
    rows: list[dict[str, object]] = []
    for overlap_samples, channel_analyses in analyses_by_overlap.items():
        for channel_name, analysis in channel_analyses.items():
            rows.append(
                {
                    "overlap_samples": overlap_samples,
                    "channel_name": channel_name,
                    "total_stft_frames": analysis.stft_result.time_s.size,
                    "candidate_frames": _candidate_count(analysis.refined_result),
                    "time_step_ns": _time_step_ns(analysis.stft_result),
                    "refined_frames": _refined_count(analysis.refined_result),
                    "two_channel_analysis_runtime_s": runtimes_by_overlap[
                        overlap_samples
                    ],
                }
            )
    pd.DataFrame(rows).to_csv(output_path, index=False)
    return output_path


def _frequency_bin_spacing_hz(stft_result: STFTResult) -> float:
    if stft_result.frequency_hz.size < 2:
        return float("nan")
    return float(np.median(np.diff(stft_result.frequency_hz)))


def _finite_three_number_values(values: FloatArray) -> tuple[float, float, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return (float("nan"),) * 3
    return (
        float(np.min(finite)),
        float(np.median(finite)),
        float(np.max(finite)),
    )


def _absolute_difference_values(
    compared: FloatArray,
    reference: FloatArray,
) -> tuple[int, float, float, float]:
    paired = np.isfinite(compared) & np.isfinite(reference)
    differences = np.abs(compared[paired] - reference[paired])
    if differences.size == 0:
        return (0, float("nan"), float("nan"), float("nan"))
    return (
        int(differences.size),
        float(np.median(differences)),
        float(np.percentile(differences, 95.0)),
        float(np.max(differences)),
    )


def _nfft_stability_rows(
    analyses_by_nfft: Mapping[int, Mapping[str, ChannelAnalysis]],
    runtimes_by_nfft: Mapping[int, float],
) -> list[dict[str, object]]:
    reference_analyses = analyses_by_nfft[NFFT]
    rows: list[dict[str, object]] = []
    for nfft, channel_analyses in analyses_by_nfft.items():
        for channel_name, analysis in channel_analyses.items():
            reference = reference_analyses[channel_name]
            if not np.array_equal(
                analysis.refined_result.time_s,
                reference.refined_result.time_s,
            ):
                raise RuntimeError(
                    f"nfft={nfft} and nfft={NFFT} time axes do not match for "
                    f"{channel_name}."
                )
            frequency_min, frequency_median, frequency_max = (
                _finite_three_number_values(
                    analysis.refined_result.refined_frequency_hz
                )
            )
            velocity_min, velocity_median, velocity_max = (
                _finite_three_number_values(analysis.refined_velocity_m_s)
            )
            (
                paired_frequency_frames,
                median_frequency_difference,
                p95_frequency_difference,
                maximum_frequency_difference,
            ) = _absolute_difference_values(
                analysis.refined_result.refined_frequency_hz,
                reference.refined_result.refined_frequency_hz,
            )
            (
                paired_velocity_frames,
                median_velocity_difference,
                p95_velocity_difference,
                maximum_velocity_difference,
            ) = _absolute_difference_values(
                analysis.refined_velocity_m_s,
                reference.refined_velocity_m_s,
            )
            rows.append(
                {
                    "channel_name": channel_name,
                    "nfft": nfft,
                    "reference_nfft": NFFT,
                    "total_stft_frames": analysis.stft_result.time_s.size,
                    "candidate_frames": _candidate_count(analysis.refined_result),
                    "refined_frames": _refined_count(analysis.refined_result),
                    "frequency_bin_spacing_hz": _frequency_bin_spacing_hz(
                        analysis.stft_result
                    ),
                    "two_channel_analysis_runtime_s": runtimes_by_nfft[nfft],
                    "refined_frequency_min_hz": frequency_min,
                    "refined_frequency_median_hz": frequency_median,
                    "refined_frequency_max_hz": frequency_max,
                    "refined_velocity_min_m_s": velocity_min,
                    "refined_velocity_median_m_s": velocity_median,
                    "refined_velocity_max_m_s": velocity_max,
                    "paired_frequency_frames": paired_frequency_frames,
                    "median_absolute_frequency_difference_hz": (
                        median_frequency_difference
                    ),
                    "p95_absolute_frequency_difference_hz": p95_frequency_difference,
                    "maximum_absolute_frequency_difference_hz": (
                        maximum_frequency_difference
                    ),
                    "paired_velocity_frames": paired_velocity_frames,
                    "median_absolute_velocity_difference_m_s": (
                        median_velocity_difference
                    ),
                    "p95_absolute_velocity_difference_m_s": p95_velocity_difference,
                    "maximum_absolute_velocity_difference_m_s": (
                        maximum_velocity_difference
                    ),
                }
            )
    return rows


def _print_nfft_statistics(rows: list[dict[str, object]]) -> None:
    print("\nnfft frequency-grid stability (reference nfft=4096)")
    for row in rows:
        print(
            f"  {row['channel_name']} nfft={row['nfft']}: "
            f"frames={row['total_stft_frames']}, "
            f"CANDIDATE={row['candidate_frames']}, "
            f"REFINED={row['refined_frames']}, "
            f"bin spacing={float(row['frequency_bin_spacing_hz']):.12g} Hz, "
            f"two-channel runtime={float(row['two_channel_analysis_runtime_s']):.6f} s"
        )
        print(
            "    refined frequency min/median/max (Hz): "
            f"{float(row['refined_frequency_min_hz']):.12g} / "
            f"{float(row['refined_frequency_median_hz']):.12g} / "
            f"{float(row['refined_frequency_max_hz']):.12g}"
        )
        print(
            "    refined velocity min/median/max (m/s): "
            f"{float(row['refined_velocity_min_m_s']):.12g} / "
            f"{float(row['refined_velocity_median_m_s']):.12g} / "
            f"{float(row['refined_velocity_max_m_s']):.12g}"
        )
        if int(row["nfft"]) != NFFT:
            print(
                "    |frequency - nfft4096| median/p95/max (Hz): "
                f"{float(row['median_absolute_frequency_difference_hz']):.12g} / "
                f"{float(row['p95_absolute_frequency_difference_hz']):.12g} / "
                f"{float(row['maximum_absolute_frequency_difference_hz']):.12g}"
            )
            print(
                "    |velocity - nfft4096| median/p95/max (m/s): "
                f"{float(row['median_absolute_velocity_difference_m_s']):.12g} / "
                f"{float(row['p95_absolute_velocity_difference_m_s']):.12g} / "
                f"{float(row['maximum_absolute_velocity_difference_m_s']):.12g}"
            )


def _write_nfft_stability_csv(
    output_directory: Path,
    rows: list[dict[str, object]],
) -> Path:
    output_path = output_directory / "nfft_refinement_stability.csv"
    pd.DataFrame(rows).to_csv(output_path, index=False)
    return output_path


def _save_nfft_stability_plot(
    output_directory: Path,
    channel_name: str,
    analyses_by_nfft: Mapping[int, Mapping[str, ChannelAnalysis]],
) -> Path:
    output_path = (
        output_directory
        / f"{channel_name}_nfft_2048_vs_4096_vs_8192_refined_velocity.png"
    )
    reference_stft = analyses_by_nfft[NFFT][channel_name].stft_result
    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.20)
    for nfft in NFFT_STABILITY_VALUES:
        analysis = analyses_by_nfft[nfft][channel_name]
        time_us = (
            analysis.refined_result.time_s - RIDGE_START_TIME_S
        ) * 1.0e6
        axis.plot(
            time_us,
            analysis.refined_velocity_m_s,
            linewidth=1.1,
            label=f"nfft={nfft}",
        )
    axis.set_title(
        f"{channel_name}: nfft frequency-grid stability\n"
        f"Fixed window length {reference_stft.window_length_samples} and "
        f"overlap {reference_stft.overlap_samples}"
    )
    axis.set_xlabel("Time relative to configured ridge start (µs)")
    axis.set_ylabel("Refined unsigned apparent velocity (m/s)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.text(
        0.5,
        0.025,
        "frequency-grid stability check only; not a physical-accuracy ranking; "
        + PRESENTATION_NOTICE,
        ha="center",
        fontsize=7,
    )
    figure.savefig(output_path, dpi=200)
    plt.close(figure)
    return output_path


def _refined_frame_mask(result: RefinedRidgeResult) -> NDArray[np.bool_]:
    return np.fromiter(
        (
            status is RidgeRefinementStatus.REFINED
            for status in result.refinement_statuses
        ),
        dtype=np.bool_,
        count=len(result.refinement_statuses),
    )


def _pre_event_count(result: RefinedRidgeResult) -> int:
    return sum(
        flag is RidgeQualityFlag.PRE_EVENT for flag in result.quality_flags
    )


def _refinement_failure_counts(result: RefinedRidgeResult) -> dict[str, int]:
    status_counts = Counter(status.value for status in result.refinement_statuses)
    failure_statuses = (
        RidgeRefinementStatus.BOUNDARY_PEAK,
        RidgeRefinementStatus.INVALID_LOCAL_PEAK,
        RidgeRefinementStatus.OFFSET_OUT_OF_RANGE,
    )
    return {
        status.value: status_counts.get(status.value, 0)
        for status in failure_statuses
    }


def _series_detail_statistics(
    time_relative_s: FloatArray,
    velocity_m_s: FloatArray,
    valid_frame_mask: NDArray[np.bool_],
    *,
    start_relative_s: float,
    end_relative_s: float,
) -> SeriesDetailStatistics:
    """Calculate local unsmoothed differences without bridging invalid frames."""
    if (
        time_relative_s.shape != velocity_m_s.shape
        or valid_frame_mask.shape != velocity_m_s.shape
    ):
        raise ValueError("time, velocity, and valid-frame mask shapes must match.")
    region_mask = (
        (time_relative_s >= start_relative_s)
        & (time_relative_s <= end_relative_s)
    )
    valid = region_mask & valid_frame_mask & np.isfinite(velocity_m_s)
    finite_values = velocity_m_s[valid]
    if finite_values.size == 0:
        velocity_min = float("nan")
        velocity_max = float("nan")
        velocity_span = float("nan")
    else:
        velocity_min = float(np.min(finite_values))
        velocity_max = float(np.max(finite_values))
        velocity_span = velocity_max - velocity_min

    adjacent_valid = valid[:-1] & valid[1:]
    first_differences = np.diff(velocity_m_s)[adjacent_valid]
    if first_differences.size == 0:
        first_median = float("nan")
        first_p95 = float("nan")
        first_std = float("nan")
    else:
        absolute_first_differences = np.abs(first_differences)
        first_median = float(np.median(absolute_first_differences))
        first_p95 = float(np.percentile(absolute_first_differences, 95.0))
        first_std = float(np.std(first_differences))

    triplet_valid = valid[:-2] & valid[1:-1] & valid[2:]
    second_differences = (
        velocity_m_s[2:] - 2.0 * velocity_m_s[1:-1] + velocity_m_s[:-2]
    )[triplet_valid]
    second_rms = (
        float(np.sqrt(np.mean(np.square(second_differences))))
        if second_differences.size
        else float("nan")
    )
    return SeriesDetailStatistics(
        valid_frame_count=int(np.count_nonzero(valid)),
        first_difference_absolute_median_m_s=first_median,
        first_difference_absolute_p95_m_s=first_p95,
        first_difference_standard_deviation_m_s=first_std,
        second_difference_rms_m_s=second_rms,
        velocity_min_m_s=velocity_min,
        velocity_max_m_s=velocity_max,
        velocity_span_m_s=velocity_span,
    )


def _paired_channel_statistics(
    time_relative_s: FloatArray,
    first_velocity_m_s: FloatArray,
    first_refined_mask: NDArray[np.bool_],
    second_velocity_m_s: FloatArray,
    second_refined_mask: NDArray[np.bool_],
    *,
    start_relative_s: float,
    end_relative_s: float,
) -> PairedChannelStatistics:
    """Compare same-frame measurements from two gain/range acquisition channels."""
    if not (
        time_relative_s.shape
        == first_velocity_m_s.shape
        == first_refined_mask.shape
        == second_velocity_m_s.shape
        == second_refined_mask.shape
    ):
        raise ValueError("paired-channel inputs must have matching shapes.")
    paired = (
        (time_relative_s >= start_relative_s)
        & (time_relative_s <= end_relative_s)
        & first_refined_mask
        & second_refined_mask
        & np.isfinite(first_velocity_m_s)
        & np.isfinite(second_velocity_m_s)
    )
    first_values = first_velocity_m_s[paired]
    second_values = second_velocity_m_s[paired]
    absolute_differences = np.abs(first_values - second_values)
    if absolute_differences.size == 0:
        difference_median = float("nan")
        difference_p95 = float("nan")
        difference_maximum = float("nan")
    else:
        difference_median = float(np.median(absolute_differences))
        difference_p95 = float(np.percentile(absolute_differences, 95.0))
        difference_maximum = float(np.max(absolute_differences))

    if (
        first_values.size >= 2
        and float(np.std(first_values)) > 0.0
        and float(np.std(second_values)) > 0.0
    ):
        pearson_correlation = float(np.corrcoef(first_values, second_values)[0, 1])
    else:
        pearson_correlation = float("nan")
    return PairedChannelStatistics(
        paired_frame_count=int(absolute_differences.size),
        absolute_difference_median_m_s=difference_median,
        absolute_difference_p95_m_s=difference_p95,
        absolute_difference_maximum_m_s=difference_maximum,
        pearson_correlation=pearson_correlation,
    )


def _paired_statistics_for_window(
    analyses: Mapping[str, ChannelAnalysis],
    *,
    start_relative_s: float,
    end_relative_s: float,
) -> PairedChannelStatistics:
    first = analyses["pdv_channel_1"]
    second = analyses["pdv_channel_2"]
    if not np.array_equal(
        first.refined_result.time_s,
        second.refined_result.time_s,
    ):
        raise RuntimeError("Two channel STFT time axes do not match exactly.")
    time_relative_s = first.refined_result.time_s - RIDGE_START_TIME_S
    return _paired_channel_statistics(
        time_relative_s,
        first.refined_velocity_m_s,
        _refined_frame_mask(first.refined_result),
        second.refined_velocity_m_s,
        _refined_frame_mask(second.refined_result),
        start_relative_s=start_relative_s,
        end_relative_s=end_relative_s,
    )


def _window_length_sensitivity_rows(
    analyses_by_window: Mapping[int, Mapping[str, ChannelAnalysis]],
    runtimes_by_window: Mapping[int, float],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for window_length_samples, overlap_samples in WINDOW_LENGTH_CONFIGURATIONS:
        analyses = analyses_by_window[window_length_samples]
        paired_all = _paired_statistics_for_window(
            analyses,
            start_relative_s=0.0,
            end_relative_s=DECLINE_END_RELATIVE_S,
        )
        paired_plateau = _paired_statistics_for_window(
            analyses,
            start_relative_s=PLATEAU_START_RELATIVE_S,
            end_relative_s=PLATEAU_END_RELATIVE_S,
        )
        paired_decline = _paired_statistics_for_window(
            analyses,
            start_relative_s=DECLINE_START_RELATIVE_S,
            end_relative_s=DECLINE_END_RELATIVE_S,
        )
        for channel_name, analysis in analyses.items():
            stft_result = analysis.stft_result
            result = analysis.refined_result
            if stft_result.hop_samples != HOP_SAMPLES:
                raise RuntimeError(
                    f"Unexpected hop for window {window_length_samples}: "
                    f"{stft_result.hop_samples}."
                )
            plateau = _series_detail_statistics(
                result.time_s - RIDGE_START_TIME_S,
                analysis.refined_velocity_m_s,
                _refined_frame_mask(result),
                start_relative_s=PLATEAU_START_RELATIVE_S,
                end_relative_s=PLATEAU_END_RELATIVE_S,
            )
            frequency_min, frequency_median, frequency_max = (
                _finite_three_number_values(result.refined_frequency_hz)
            )
            velocity_min, velocity_median, velocity_max = (
                _finite_three_number_values(analysis.refined_velocity_m_s)
            )
            rows.append(
                {
                    "channel_name": channel_name,
                    "window_length_samples": window_length_samples,
                    "overlap_samples": overlap_samples,
                    "hop_samples": stft_result.hop_samples,
                    "sample_rate_hz": stft_result.sample_rate_hz,
                    "window_duration_s": (
                        window_length_samples / stft_result.sample_rate_hz
                    ),
                    "window_frequency_scale_hz": (
                        stft_result.sample_rate_hz / window_length_samples
                    ),
                    "stft_time_step_s": _time_step_ns(stft_result) * 1.0e-9,
                    "stft_frame_count": stft_result.time_s.size,
                    "pre_event_count": _pre_event_count(result),
                    "candidate_count": _candidate_count(result),
                    "refined_count": _refined_count(result),
                    "refinement_failure_counts": json.dumps(
                        _refinement_failure_counts(result),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                    "refined_frequency_min_hz": frequency_min,
                    "refined_frequency_median_hz": frequency_median,
                    "refined_frequency_max_hz": frequency_max,
                    "refined_velocity_min_m_s": velocity_min,
                    "refined_velocity_median_m_s": velocity_median,
                    "refined_velocity_max_m_s": velocity_max,
                    "plateau_valid_frame_count": plateau.valid_frame_count,
                    "plateau_first_difference_median_m_s": (
                        plateau.first_difference_absolute_median_m_s
                    ),
                    "plateau_first_difference_p95_m_s": (
                        plateau.first_difference_absolute_p95_m_s
                    ),
                    "plateau_first_difference_standard_deviation_m_s": (
                        plateau.first_difference_standard_deviation_m_s
                    ),
                    "plateau_second_difference_rms_m_s": (
                        plateau.second_difference_rms_m_s
                    ),
                    "plateau_velocity_min_m_s": plateau.velocity_min_m_s,
                    "plateau_velocity_max_m_s": plateau.velocity_max_m_s,
                    "plateau_velocity_span_m_s": plateau.velocity_span_m_s,
                    "paired_channel_frame_count": paired_all.paired_frame_count,
                    "paired_channel_difference_median_m_s": (
                        paired_all.absolute_difference_median_m_s
                    ),
                    "paired_channel_difference_p95_m_s": (
                        paired_all.absolute_difference_p95_m_s
                    ),
                    "paired_channel_difference_maximum_m_s": (
                        paired_all.absolute_difference_maximum_m_s
                    ),
                    "paired_channel_correlation": paired_all.pearson_correlation,
                    "plateau_paired_channel_frame_count": (
                        paired_plateau.paired_frame_count
                    ),
                    "plateau_paired_channel_difference_median_m_s": (
                        paired_plateau.absolute_difference_median_m_s
                    ),
                    "plateau_paired_channel_difference_p95_m_s": (
                        paired_plateau.absolute_difference_p95_m_s
                    ),
                    "plateau_paired_channel_difference_maximum_m_s": (
                        paired_plateau.absolute_difference_maximum_m_s
                    ),
                    "plateau_paired_channel_correlation": (
                        paired_plateau.pearson_correlation
                    ),
                    "decline_paired_channel_frame_count": (
                        paired_decline.paired_frame_count
                    ),
                    "decline_paired_channel_difference_median_m_s": (
                        paired_decline.absolute_difference_median_m_s
                    ),
                    "decline_paired_channel_difference_p95_m_s": (
                        paired_decline.absolute_difference_p95_m_s
                    ),
                    "decline_paired_channel_difference_maximum_m_s": (
                        paired_decline.absolute_difference_maximum_m_s
                    ),
                    "decline_paired_channel_correlation": (
                        paired_decline.pearson_correlation
                    ),
                    "analysis_runtime_s": runtimes_by_window[
                        window_length_samples
                    ],
                }
            )
    return rows


def _print_window_length_sensitivity_statistics(
    rows: list[dict[str, object]],
) -> None:
    print("\nFixed-hop STFT window-length sensitivity statistics")
    for window_length_samples, overlap_samples in WINDOW_LENGTH_CONFIGURATIONS:
        matching_rows = [
            row
            for row in rows
            if int(row["window_length_samples"]) == window_length_samples
        ]
        first_row = matching_rows[0]
        print(
            f"\nWindow={window_length_samples}, overlap={overlap_samples}, "
            f"hop={HOP_SAMPLES}, "
            f"duration={float(first_row['window_duration_s']) * 1.0e9:.9g} ns, "
            f"time step={float(first_row['stft_time_step_s']) * 1.0e9:.9g} ns, "
            f"two-channel runtime={float(first_row['analysis_runtime_s']):.6f} s"
        )
        print(
            "  fs/window frequency scale: "
            f"{float(first_row['window_frequency_scale_hz']):.12g} Hz; "
            "this is not the final beat-frequency measurement error"
        )
        for row in matching_rows:
            print(
                f"  {row['channel_name']}: STFT={row['stft_frame_count']}, "
                f"PRE_EVENT={row['pre_event_count']}, "
                f"CANDIDATE={row['candidate_count']}, "
                f"REFINED={row['refined_count']}, "
                f"failures={row['refinement_failure_counts']}"
            )
            print(
                "    refined frequency min/median/max (Hz): "
                f"{float(row['refined_frequency_min_hz']):.12g} / "
                f"{float(row['refined_frequency_median_hz']):.12g} / "
                f"{float(row['refined_frequency_max_hz']):.12g}"
            )
            print(
                "    apparent velocity min/median/max (m/s): "
                f"{float(row['refined_velocity_min_m_s']):.12g} / "
                f"{float(row['refined_velocity_median_m_s']):.12g} / "
                f"{float(row['refined_velocity_max_m_s']):.12g}"
            )
            print(
                "    plateau |first diff| median/p95, signed first-diff std, "
                "second-diff RMS (m/s): "
                f"{float(row['plateau_first_difference_median_m_s']):.12g} / "
                f"{float(row['plateau_first_difference_p95_m_s']):.12g} / "
                f"{float(row['plateau_first_difference_standard_deviation_m_s']):.12g} / "
                f"{float(row['plateau_second_difference_rms_m_s']):.12g}"
            )
            print(
                "    plateau velocity min/max/span (m/s): "
                f"{float(row['plateau_velocity_min_m_s']):.12g} / "
                f"{float(row['plateau_velocity_max_m_s']):.12g} / "
                f"{float(row['plateau_velocity_span_m_s']):.12g}"
            )
        print(
            "  paired channels, all candidates: "
            f"frames={first_row['paired_channel_frame_count']}, "
            "|difference| median/p95/max="
            f"{float(first_row['paired_channel_difference_median_m_s']):.12g} / "
            f"{float(first_row['paired_channel_difference_p95_m_s']):.12g} / "
            f"{float(first_row['paired_channel_difference_maximum_m_s']):.12g} m/s, "
            f"Pearson r={float(first_row['paired_channel_correlation']):.12g}"
        )
        for region_name in ("plateau", "decline"):
            print(
                f"  paired channels, {region_name}: "
                f"frames={first_row[f'{region_name}_paired_channel_frame_count']}, "
                "|difference| median/p95/max="
                f"{float(first_row[f'{region_name}_paired_channel_difference_median_m_s']):.12g} / "
                f"{float(first_row[f'{region_name}_paired_channel_difference_p95_m_s']):.12g} / "
                f"{float(first_row[f'{region_name}_paired_channel_difference_maximum_m_s']):.12g} m/s, "
                f"Pearson r={float(first_row[f'{region_name}_paired_channel_correlation']):.12g}"
            )


def _write_window_length_sensitivity_csv(
    output_directory: Path,
    rows: list[dict[str, object]],
) -> Path:
    output_path = output_directory / "window_length_sensitivity_summary.csv"
    pd.DataFrame(rows).to_csv(output_path, index=False)
    return output_path


def _save_window_length_velocity_plot(
    output_directory: Path,
    channel_name: str,
    analyses_by_window: Mapping[int, Mapping[str, ChannelAnalysis]],
) -> Path:
    output_path = (
        output_directory
        / f"{channel_name}_window_512_vs_768_vs_1024_velocity.png"
    )
    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.20)
    for window_length_samples, _ in WINDOW_LENGTH_CONFIGURATIONS:
        analysis = analyses_by_window[window_length_samples][channel_name]
        time_us = (
            analysis.refined_result.time_s - RIDGE_START_TIME_S
        ) * 1.0e6
        duration_ns = (
            window_length_samples / analysis.stft_result.sample_rate_hz * 1.0e9
        )
        axis.plot(
            time_us,
            analysis.refined_velocity_m_s,
            linewidth=0.8,
            label=(
                f"window={window_length_samples} "
                f"({duration_ns:.3g} ns support)"
            ),
        )
    axis.set_title(f"{channel_name}: fixed-hop STFT window-length comparison")
    axis.set_xlabel("Time relative to configured ridge start (\N{MICRO SIGN}s)")
    axis.set_ylabel("Raw refined apparent velocity (m/s)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.text(
        0.5,
        0.025,
        "raw refined candidates; no smoothing, filtering, interpolation, or tracking; "
        + PRESENTATION_NOTICE,
        ha="center",
        fontsize=7,
    )
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=200,
    )
    plt.close(figure)
    return output_path


def _save_window_plateau_detail_plot(
    output_directory: Path,
    channel_name: str,
    analyses_by_window: Mapping[int, Mapping[str, ChannelAnalysis]],
) -> Path:
    output_path = output_directory / f"{channel_name}_window_plateau_detail.png"
    finite_plateau_values: list[FloatArray] = []
    for window_length_samples, _ in WINDOW_LENGTH_CONFIGURATIONS:
        analysis = analyses_by_window[window_length_samples][channel_name]
        time_relative_s = analysis.refined_result.time_s - RIDGE_START_TIME_S
        in_plateau = (
            (time_relative_s >= PLATEAU_START_RELATIVE_S)
            & (time_relative_s <= PLATEAU_END_RELATIVE_S)
            & _refined_frame_mask(analysis.refined_result)
            & np.isfinite(analysis.refined_velocity_m_s)
        )
        finite_plateau_values.append(analysis.refined_velocity_m_s[in_plateau])
    all_values = np.concatenate(finite_plateau_values)
    if all_values.size == 0:
        raise RuntimeError(f"No refined plateau values available for {channel_name}.")
    common_minimum = float(np.min(all_values))
    common_maximum = float(np.max(all_values))
    common_span = common_maximum - common_minimum
    padding = max(common_span * 0.05, abs(common_maximum) * 0.002, 0.1)

    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.20)
    for window_length_samples, _ in WINDOW_LENGTH_CONFIGURATIONS:
        analysis = analyses_by_window[window_length_samples][channel_name]
        time_us = (
            analysis.refined_result.time_s - RIDGE_START_TIME_S
        ) * 1.0e6
        in_plateau = (
            (time_us >= PLATEAU_START_RELATIVE_S * 1.0e6)
            & (time_us <= PLATEAU_END_RELATIVE_S * 1.0e6)
        )
        plotted_velocity = np.where(
            in_plateau,
            analysis.refined_velocity_m_s,
            np.nan,
        )
        axis.plot(
            time_us,
            plotted_velocity,
            linewidth=0.65,
            marker="o",
            markersize=1.8,
            label=f"window={window_length_samples}",
        )
    axis.set_xlim(
        PLATEAU_START_RELATIVE_S * 1.0e6,
        PLATEAU_END_RELATIVE_S * 1.0e6,
    )
    axis.set_ylim(common_minimum - padding, common_maximum + padding)
    axis.set_title(f"{channel_name}: plateau detail diagnostic")
    axis.set_xlabel("Time relative to configured ridge start (\N{MICRO SIGN}s)")
    axis.set_ylabel("Raw refined apparent velocity (m/s)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.text(
        0.5,
        0.025,
        "0.08-0.50 microsecond diagnostic viewport; every marker is one refined "
        "frame; no interpolation",
        ha="center",
        fontsize=7,
    )
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=220,
    )
    plt.close(figure)
    return output_path


def _save_window_two_channel_comparison(
    output_directory: Path,
    window_length_samples: int,
    analyses: Mapping[str, ChannelAnalysis],
) -> Path:
    output_path = (
        output_directory
        / f"window_{window_length_samples}_two_channel_comparison.png"
    )
    first_analysis = next(iter(analyses.values()))
    duration_ns = (
        window_length_samples / first_analysis.stft_result.sample_rate_hz * 1.0e9
    )
    figure, axis = plt.subplots(figsize=(10.0, 5.2))
    figure.subplots_adjust(left=0.09, right=0.98, top=0.88, bottom=0.20)
    for channel_name, analysis in analyses.items():
        time_us = (
            analysis.refined_result.time_s - RIDGE_START_TIME_S
        ) * 1.0e6
        axis.plot(
            time_us,
            analysis.refined_velocity_m_s,
            linewidth=0.9,
            label=channel_name,
        )
    axis.set_title(
        f"Two gain/range acquisition channels | window={window_length_samples} "
        f"({duration_ns:.3g} ns support)"
    )
    axis.set_xlabel("Time relative to configured ridge start (\N{MICRO SIGN}s)")
    axis.set_ylabel("Raw refined apparent velocity (m/s)")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.text(
        0.5,
        0.025,
        "two acquisition channels; no averaging, fusion, smoothing, interpolation, "
        "or continuity tracking",
        ha="center",
        fontsize=7,
    )
    _save_figure_without_path_simplification(
        figure,
        output_path,
        dpi=200,
    )
    plt.close(figure)
    return output_path


def _save_window_length_stft_comparison(
    output_directory: Path,
    channel_name: str,
    analyses_by_window: Mapping[int, Mapping[str, ChannelAnalysis]],
) -> Path:
    output_path = (
        output_directory / f"{channel_name}_window_length_stft_comparison.png"
    )
    magnitudes_by_window: dict[int, FloatArray] = {}
    frequency_ghz_by_window: dict[int, FloatArray] = {}
    time_us_by_window: dict[int, FloatArray] = {}
    maximum_magnitude = 0.0
    for window_length_samples, _ in WINDOW_LENGTH_CONFIGURATIONS:
        analysis = analyses_by_window[window_length_samples][channel_name]
        stft_result = analysis.stft_result
        band_mask = (
            (stft_result.frequency_hz >= STFT_DETAIL_MINIMUM_FREQUENCY_HZ)
            & (stft_result.frequency_hz <= STFT_DETAIL_MAXIMUM_FREQUENCY_HZ)
        )
        magnitude = np.abs(stft_result.spectrum[band_mask, :])
        magnitudes_by_window[window_length_samples] = magnitude
        frequency_ghz_by_window[window_length_samples] = (
            stft_result.frequency_hz[band_mask] * 1.0e-9
        )
        time_us_by_window[window_length_samples] = (
            stft_result.time_s - RIDGE_START_TIME_S
        ) * 1.0e6
        maximum_magnitude = max(maximum_magnitude, float(np.max(magnitude)))
    if not np.isfinite(maximum_magnitude) or maximum_magnitude <= 0.0:
        raise RuntimeError(f"No finite positive STFT magnitude for {channel_name}.")

    common_time_minimum = min(float(time[0]) for time in time_us_by_window.values())
    common_time_maximum = max(float(time[-1]) for time in time_us_by_window.values())
    figure, axes = plt.subplots(
        3,
        1,
        figsize=(11.0, 10.0),
        sharex=True,
        sharey=True,
    )
    figure.subplots_adjust(
        left=0.09,
        right=0.88,
        top=0.91,
        bottom=0.10,
        hspace=0.22,
    )
    mesh = None
    for axis, (window_length_samples, _) in zip(
        axes,
        WINDOW_LENGTH_CONFIGURATIONS,
    ):
        analysis = analyses_by_window[window_length_samples][channel_name]
        magnitude = magnitudes_by_window[window_length_samples]
        relative_db = _relative_stft_magnitude_db(
            magnitude,
            reference_maximum=maximum_magnitude,
        )
        mesh = axis.pcolormesh(
            time_us_by_window[window_length_samples],
            frequency_ghz_by_window[window_length_samples],
            relative_db,
            shading="auto",
            cmap="viridis",
            vmin=-60.0,
            vmax=0.0,
        )
        duration_ns = (
            window_length_samples / analysis.stft_result.sample_rate_hz * 1.0e9
        )
        axis.set_title(
            f"window length {window_length_samples} | duration {duration_ns:.3g} ns "
            f"| hop 128 | nfft 4096"
        )
        axis.set_xlim(common_time_minimum, common_time_maximum)
        axis.set_ylim(
            STFT_DETAIL_MINIMUM_FREQUENCY_HZ * 1.0e-9,
            STFT_DETAIL_MAXIMUM_FREQUENCY_HZ * 1.0e-9,
        )
        axis.set_ylabel("Beat frequency (GHz)")
    axes[-1].set_xlabel(
        "Time relative to configured ridge start (\N{MICRO SIGN}s)"
    )
    figure.suptitle(
        f"{channel_name}: clean STFT window-length comparison | common dB reference"
    )
    if mesh is None:
        raise RuntimeError("STFT comparison did not create a pcolormesh.")
    colorbar = figure.colorbar(mesh, ax=axes, pad=0.02)
    colorbar.set_label("Relative STFT magnitude (dB; common maximum)")
    figure.text(
        0.5,
        0.025,
        "viridis; -60 to 0 dB; no ridge overlay; no image smoothing, filtering, "
        "or interpolation; development preview",
        ha="center",
        fontsize=8,
    )
    figure.savefig(output_path, dpi=220)
    plt.close(figure)
    return output_path


def run_demo(
    output_directory: Path = OUTPUT_DIRECTORY,
    *,
    run_window_diagnostics: bool = False,
) -> list[Path]:
    """Run the explicit 768-point main preview and optional window diagnostics."""
    print(DEMO_NOTICE)
    print(f"Input file: {DATA_PATH}")
    print(f"Output directory: {output_directory}")
    print(
        f"Main development parameters: window_name={WINDOW_NAME}, "
        f"window_length_samples={WINDOW_LENGTH_SAMPLES}, "
        f"overlap_samples={OVERLAP_SAMPLES}, hop_samples={HOP_SAMPLES}, "
        f"nfft={NFFT}"
    )
    print(f"Window diagnostics enabled: {run_window_diagnostics}")
    print("[STAGE 1/7] Validate input and calculate source SHA-256")
    if not DATA_PATH.is_file():
        raise FileNotFoundError(f"Input data file does not exist: {DATA_PATH}")
    source_hash_before = _sha256(DATA_PATH)
    print(f"Source SHA-256 before: {source_hash_before}")

    generated_paths: list[Path] = []
    try:
        print("[STAGE 2/7] Load two raw signal channels without modifying source data")
        loaded = read_delimited_signals(
            DATA_PATH,
            time_column=0,
            voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
            delimiter=",",
            has_header=False,
        )
        output_directory.mkdir(parents=True, exist_ok=True)

        print("[STAGE 3/7] Run explicit 768/640/4096 main analysis once")
        main_analyses, main_runtime_s = _analyze_configuration(
            loaded.records,
            WINDOW_LENGTH_SAMPLES,
            OVERLAP_SAMPLES,
            NFFT,
        )

        print("[STAGE 4/7] Report actual main configuration and channel statistics")
        print(f"Main two-acquisition-channel runtime: {main_runtime_s:.6f} s")
        for channel_name, analysis in main_analyses.items():
            stft_result = analysis.stft_result
            print(
                f"  {channel_name}: window_name={stft_result.window_name}, "
                f"window_length_samples={stft_result.window_length_samples}, "
                f"overlap_samples={stft_result.overlap_samples}, "
                f"hop_samples={stft_result.hop_samples}, nfft={stft_result.nfft}, "
                f"STFT frames={stft_result.time_s.size}, "
                f"time step={_time_step_ns(stft_result):.9g} ns, "
                f"CANDIDATE={_candidate_count(analysis.refined_result)}, "
                f"REFINED={_refined_count(analysis.refined_result)}"
            )
            _print_channel_statistics(
                channel_name,
                analysis.refined_result,
                analysis.discrete_velocity_m_s,
                analysis.refined_velocity_m_s,
            )

        print("[STAGE 5/7] Save main CSV, diagnostics, presentations, and STFT plots")
        for channel_name, analysis in main_analyses.items():
            generated_paths.extend(
                [
                    _write_csv(
                        output_directory,
                        channel_name,
                        analysis.stft_result,
                        analysis.refined_result,
                        analysis.discrete_velocity_m_s,
                        analysis.refined_velocity_m_s,
                        analysis.display_velocity_m_s,
                        analysis.velocity_origins,
                    ),
                    _save_frequency_plot(
                        output_directory,
                        channel_name,
                        analysis.refined_result,
                    ),
                    _save_velocity_plot(
                        output_directory,
                        channel_name,
                        analysis.refined_result,
                        analysis.discrete_velocity_m_s,
                        analysis.refined_velocity_m_s,
                        analysis.display_velocity_m_s,
                    ),
                    _save_full_display_plot(
                        output_directory,
                        channel_name,
                        analysis.refined_result,
                        analysis.display_velocity_m_s,
                    ),
                    _save_presentation_velocity_plot(
                        output_directory,
                        channel_name,
                        analysis.refined_result,
                        analysis.display_velocity_m_s,
                    ),
                    _save_presentation_with_plateau_detail(
                        output_directory,
                        channel_name,
                        analysis,
                    ),
                    _save_decline_detail(
                        output_directory,
                        channel_name,
                        analysis,
                    ),
                    _save_clean_stft_detail(
                        output_directory,
                        channel_name,
                        analysis.stft_result,
                    ),
                    _save_stft_spectrogram(
                        output_directory,
                        channel_name,
                        analysis,
                    ),
                ]
            )

        generated_paths.append(
            _save_two_channel_presentation_plot(
                output_directory,
                main_analyses,
            )
        )

        print("[STAGE 6/7] Handle optional fixed-hop window diagnostics")
        if run_window_diagnostics:
            analyses_by_window: dict[int, Mapping[str, ChannelAnalysis]] = {
                WINDOW_LENGTH_SAMPLES: main_analyses
            }
            runtimes_by_window = {WINDOW_LENGTH_SAMPLES: main_runtime_s}
            for window_length_samples, overlap_samples in (
                WINDOW_LENGTH_CONFIGURATIONS
            ):
                if window_length_samples == WINDOW_LENGTH_SAMPLES:
                    continue
                analyses, runtime_s = _analyze_configuration(
                    loaded.records,
                    window_length_samples,
                    overlap_samples,
                    NFFT,
                )
                analyses_by_window[window_length_samples] = analyses
                runtimes_by_window[window_length_samples] = runtime_s
            window_rows = _window_length_sensitivity_rows(
                analyses_by_window,
                runtimes_by_window,
            )
            _print_window_length_sensitivity_statistics(window_rows)
            generated_paths.append(
                _write_window_length_sensitivity_csv(
                    output_directory,
                    window_rows,
                )
            )
            for channel_name in main_analyses:
                generated_paths.extend(
                    [
                        _save_window_length_velocity_plot(
                            output_directory,
                            channel_name,
                            analyses_by_window,
                        ),
                        _save_window_plateau_detail_plot(
                            output_directory,
                            channel_name,
                            analyses_by_window,
                        ),
                        _save_window_length_stft_comparison(
                            output_directory,
                            channel_name,
                            analyses_by_window,
                        ),
                    ]
                )
            for window_length_samples, _ in WINDOW_LENGTH_CONFIGURATIONS:
                generated_paths.append(
                    _save_window_two_channel_comparison(
                        output_directory,
                        window_length_samples,
                        analyses_by_window[window_length_samples],
                    )
                )
        else:
            print(
                "  Window diagnostics skipped. Use --window-diagnostics for the "
                "512/768/1024 development audit."
            )
    finally:
        print("[STAGE 7/7] Verify raw source SHA-256")
        source_hash_after = _sha256(DATA_PATH)
        print(f"Source SHA-256 after:  {source_hash_after}")
        if source_hash_after != source_hash_before:
            raise RuntimeError("Raw source SHA-256 changed during read-only comparison.")
        print("Source SHA-256 unchanged: yes")

    print("Generated files:")
    for path in generated_paths:
        print(f"  {path.resolve()}")
    print(
        "Interpretation guard: the explicit development main configuration is "
        "window 768, overlap 640, hop 128, nfft 4096, Hann. The 19.2 ns window "
        "support is a time-frequency tradeoff and does not establish improved "
        "physical accuracy."
    )
    print(
        "The 1024/896/4096 configuration remains available only through the explicit "
        "window-diagnostics audit; the 512-point configuration is not selected."
    )
    return generated_paths


def main() -> None:
    run_demo()


if __name__ == "__main__":
    main()
