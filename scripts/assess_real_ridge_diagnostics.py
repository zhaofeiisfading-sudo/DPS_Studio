"""Development-only TASK-008B continuity and related-frequency diagnostics."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from numpy.typing import NDArray

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from assess_real_ridge_quality import (  # noqa: E402
    MINIMUM_BACKGROUND_BIN_COUNT,
    _finite_summary,
    _hann_first_zero_guard_hz,
)
from compare_real_ridge_refinement import (  # noqa: E402
    ANALYSIS_END_TIME_S,
    DATA_PATH,
    DECLINE_END_RELATIVE_S,
    DECLINE_START_RELATIVE_S,
    HOP_SAMPLES,
    NFFT,
    OVERLAP_SAMPLES,
    PLATEAU_END_RELATIVE_S,
    PLATEAU_START_RELATIVE_S,
    PRESENTATION_PRE_EVENT_DURATION_S,
    RIDGE_START_TIME_S,
    WINDOW_LENGTH_SAMPLES,
    WINDOW_NAME,
    ChannelAnalysis,
    _analyze_configuration,
    _relative_stft_magnitude_db,
    _sha256,
)
from dps_studio.core.io import read_delimited_signals  # noqa: E402
from dps_studio.core.ridge import (  # noqa: E402
    RelatedFrequencyEvidenceResult,
    RelatedFrequencyEvidenceStatus,
    RidgeContinuityResult,
    RidgeContinuityStatus,
    RidgeSpectralQualityResult,
    assess_related_frequency_evidence,
    assess_ridge_continuity,
    assess_ridge_spectral_quality,
)
from dps_studio.core.time_frequency import STFTResult  # noqa: E402


FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]
FIGURE_SIZE_INCHES = (11.0, 8.2)
SAVE_DPI = 220
DIAGNOSTIC_NOTICE = (
    "diagnostic evidence only; no smoothing, interpolation, ridge replacement, "
    "branch switching, point deletion, channel selection/fusion, LiF correction, "
    "or physical-accuracy claim"
)
PLOT_NOTICE = (
    "Diagnostic evidence only; no smoothing, thresholds, ridge change, channel "
    "selection/fusion, or physical-accuracy claim."
)


def _related_search_half_width_hz(stft_result: STFTResult) -> float:
    """Use one unpadded-window DFT bin as a documented development scale.

    The explicit width is ``sample_rate_hz / window_length_samples``. It is a
    reproducible diagnostic choice for this fixed Hann-window demo, not a final
    scientific standard and not an automatic frequency-relation decision rule.
    """
    return stft_result.sample_rate_hz / stft_result.window_length_samples


def _write_continuity_csv(
    output_directory: Path,
    channel_name: str,
    stft_result: STFTResult,
    result: RidgeContinuityResult,
) -> Path:
    output_path = output_directory / f"{channel_name}_ridge_continuity.csv"
    pd.DataFrame(
        {
            "channel_name": channel_name,
            "time_s": result.time_s,
            "time_relative_to_ridge_start_s": result.time_s - RIDGE_START_TIME_S,
            "ridge_quality_flag": [flag.value for flag in result.quality_flags],
            "refinement_status": [
                status.value for status in result.refinement_statuses
            ],
            "continuity_status": [
                status.value for status in result.continuity_statuses
            ],
            "refined_frequency_hz": result.refined_frequency_hz,
            "previous_refined_frequency_hz": (
                result.previous_refined_frequency_hz
            ),
            "frame_interval_s": result.frame_interval_s,
            "frequency_step_hz": result.frequency_step_hz,
            "absolute_frequency_step_hz": result.absolute_frequency_step_hz,
            "frequency_slope_hz_s": result.frequency_slope_hz_s,
            "frequency_second_difference_hz": (
                result.frequency_second_difference_hz
            ),
            "window_name": stft_result.window_name,
            "window_length_samples": stft_result.window_length_samples,
            "overlap_samples": stft_result.overlap_samples,
            "hop_samples": stft_result.hop_samples,
            "nfft": stft_result.nfft,
            "sample_rate_hz": stft_result.sample_rate_hz,
            "search_minimum_frequency_hz": result.minimum_frequency_hz,
            "search_maximum_frequency_hz": result.maximum_frequency_hz,
            "event_start_time_s": result.event_start_time_s,
            "analysis_end_time_s": result.analysis_end_time_s,
            "continuity_method": result.continuity_method,
            "source_path": (
                "" if result.source_path is None else str(result.source_path)
            ),
        }
    ).to_csv(output_path, index=False)
    return output_path


def _write_related_csv(
    output_directory: Path,
    channel_name: str,
    stft_result: STFTResult,
    result: RelatedFrequencyEvidenceResult,
) -> Path:
    output_path = output_directory / f"{channel_name}_related_frequency_evidence.csv"
    pd.DataFrame(
        {
            "channel_name": channel_name,
            "time_s": result.time_s,
            "time_relative_to_ridge_start_s": result.time_s - RIDGE_START_TIME_S,
            "ridge_quality_flag": [flag.value for flag in result.quality_flags],
            "refinement_status": [
                status.value for status in result.refinement_statuses
            ],
            "spectral_assessment_status": [
                status.value for status in result.spectral_quality_statuses
            ],
            "double_frequency_status": [
                status.value for status in result.double_frequency_statuses
            ],
            "half_frequency_status": [
                status.value for status in result.half_frequency_statuses
            ],
            "discrete_frequency_bin_index": result.discrete_frequency_bin_index,
            "refined_frequency_hz": result.refined_frequency_hz,
            "main_peak_magnitude": result.main_peak_magnitude,
            "double_frequency_target_hz": result.double_frequency_target_hz,
            "double_frequency_peak_hz": result.double_frequency_peak_hz,
            "double_frequency_peak_magnitude": (
                result.double_frequency_peak_magnitude
            ),
            "double_frequency_peak_offset_hz": (
                result.double_frequency_peak_offset_hz
            ),
            "main_to_double_frequency_db": result.main_to_double_frequency_db,
            "half_frequency_target_hz": result.half_frequency_target_hz,
            "half_frequency_peak_hz": result.half_frequency_peak_hz,
            "half_frequency_peak_magnitude": result.half_frequency_peak_magnitude,
            "half_frequency_peak_offset_hz": result.half_frequency_peak_offset_hz,
            "main_to_half_frequency_db": result.main_to_half_frequency_db,
            "related_search_half_width_hz": result.search_half_width_hz,
            "window_name": stft_result.window_name,
            "window_length_samples": stft_result.window_length_samples,
            "overlap_samples": stft_result.overlap_samples,
            "hop_samples": stft_result.hop_samples,
            "nfft": stft_result.nfft,
            "sample_rate_hz": stft_result.sample_rate_hz,
            "search_minimum_frequency_hz": result.minimum_frequency_hz,
            "search_maximum_frequency_hz": result.maximum_frequency_hz,
            "event_start_time_s": result.event_start_time_s,
            "analysis_end_time_s": result.analysis_end_time_s,
            "evidence_method": result.evidence_method,
            "source_path": (
                "" if result.source_path is None else str(result.source_path)
            ),
        }
    ).to_csv(output_path, index=False)
    return output_path


def _relative_time_us(time_s: FloatArray) -> FloatArray:
    return (time_s - RIDGE_START_TIME_S) * 1.0e6


def _shade_intervals(axis: plt.Axes) -> None:
    axis.axvspan(
        PLATEAU_START_RELATIVE_S * 1.0e6,
        PLATEAU_END_RELATIVE_S * 1.0e6,
        color="#2ca02c",
        alpha=0.07,
        label="diagnostic plateau interval",
    )
    axis.axvspan(
        DECLINE_START_RELATIVE_S * 1.0e6,
        DECLINE_END_RELATIVE_S * 1.0e6,
        color="#d62728",
        alpha=0.06,
        label="diagnostic decline interval",
    )


def _scatter_finite(
    axis: plt.Axes,
    x: FloatArray,
    y: FloatArray,
    *,
    label: str,
    color: str,
    size: float = 10.0,
) -> None:
    finite = np.isfinite(x) & np.isfinite(y)
    axis.scatter(
        x[finite],
        y[finite],
        s=size,
        alpha=0.75,
        linewidths=0.0,
        color=color,
        label=label,
    )


def _save_continuity_plot(
    output_directory: Path,
    channel_name: str,
    result: RidgeContinuityResult,
) -> Path:
    output_path = output_directory / f"{channel_name}_continuity_diagnostics.png"
    relative_time_us = _relative_time_us(result.time_s)
    figure, axes = plt.subplots(
        3,
        1,
        figsize=FIGURE_SIZE_INCHES,
        sharex=True,
        constrained_layout=True,
    )
    _scatter_finite(
        axes[0],
        relative_time_us,
        result.refined_frequency_hz / 1.0e9,
        label="refined ridge samples",
        color="#1f77b4",
    )
    _scatter_finite(
        axes[1],
        relative_time_us,
        result.frequency_step_hz / 1.0e6,
        label="adjacent frequency step",
        color="#ff7f0e",
    )
    _scatter_finite(
        axes[2],
        relative_time_us,
        result.frequency_slope_hz_s / 1.0e12,
        label="adjacent frequency slope",
        color="#9467bd",
    )
    axes[0].set_ylabel("Refined frequency (GHz)")
    axes[1].set_ylabel("Frequency step (MHz)")
    axes[2].set_ylabel("Frequency slope (THz/s)")
    axes[2].set_xlabel("Time relative to ridge start (µs)")
    for axis in axes:
        _shade_intervals(axis)
        axis.grid(alpha=0.23)
        axis.legend(loc="best")
    figure.suptitle(
        f"{channel_name}: adjacent-frame ridge continuity evidence\n{PLOT_NOTICE}",
        fontsize=11.0,
    )
    figure.savefig(output_path, dpi=SAVE_DPI)
    plt.close(figure)
    return output_path


def _save_related_contrast_plot(
    output_directory: Path,
    channel_name: str,
    result: RelatedFrequencyEvidenceResult,
) -> Path:
    output_path = (
        output_directory / f"{channel_name}_related_frequency_contrasts.png"
    )
    relative_time_us = _relative_time_us(result.time_s)
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(11.0, 6.8),
        sharex=True,
        constrained_layout=True,
    )
    _scatter_finite(
        axes[0],
        relative_time_us,
        result.main_to_double_frequency_db,
        label="main-to-double-frequency contrast",
        color="#d62728",
    )
    _scatter_finite(
        axes[1],
        relative_time_us,
        result.main_to_half_frequency_db,
        label="main-to-half-frequency contrast",
        color="#2ca02c",
    )
    axes[0].set_ylabel("Main / double-frequency (dB)")
    axes[1].set_ylabel("Main / half-frequency (dB)")
    axes[1].set_xlabel("Time relative to ridge start (µs)")
    for axis in axes:
        _shade_intervals(axis)
        axis.grid(alpha=0.23)
        axis.legend(loc="best")
    figure.suptitle(
        f"{channel_name}: explicit related-frequency-band evidence\n{PLOT_NOTICE}",
        fontsize=11.0,
    )
    figure.savefig(output_path, dpi=SAVE_DPI)
    plt.close(figure)
    return output_path


def _save_stft_related_plot(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    result: RelatedFrequencyEvidenceResult,
) -> Path:
    output_path = (
        output_directory / f"{channel_name}_stft_related_frequency_evidence.png"
    )
    stft = analysis.stft_result
    time_mask = (stft.time_s >= RIDGE_START_TIME_S - PRESENTATION_PRE_EVENT_DURATION_S) & (
        stft.time_s <= ANALYSIS_END_TIME_S
    )
    frequency_mask = (stft.frequency_hz >= result.minimum_frequency_hz) & (
        stft.frequency_hz <= result.maximum_frequency_hz
    )
    magnitude = np.abs(stft.spectrum[np.ix_(frequency_mask, time_mask)])
    display_db = _relative_stft_magnitude_db(magnitude, floor_db=-60.0)
    time_us = _relative_time_us(stft.time_s[time_mask])
    frequency_ghz = stft.frequency_hz[frequency_mask] / 1.0e9
    figure, axis = plt.subplots(
        figsize=(12.0, 6.4),
        constrained_layout=True,
    )
    mesh = axis.pcolormesh(
        time_us,
        frequency_ghz,
        display_db,
        shading="auto",
        cmap="magma",
        vmin=-60.0,
        vmax=0.0,
    )
    relative_all_us = _relative_time_us(result.time_s)
    _scatter_finite(
        axis,
        relative_all_us,
        result.refined_frequency_hz / 1.0e9,
        label="selected refined ridge",
        color="#00ffff",
        size=8.0,
    )
    _scatter_finite(
        axis,
        relative_all_us,
        result.double_frequency_peak_hz / 1.0e9,
        label="double-frequency local peak",
        color="#ffffff",
        size=7.0,
    )
    _scatter_finite(
        axis,
        relative_all_us,
        result.half_frequency_peak_hz / 1.0e9,
        label="half-frequency local peak",
        color="#7fff00",
        size=7.0,
    )
    axis.set_xlabel("Time relative to ridge start (µs)")
    axis.set_ylabel("Frequency (GHz)")
    axis.set_title(
        f"{channel_name}: STFT with diagnostic related-frequency local maxima\n"
        + PLOT_NOTICE,
        fontsize=11.0,
    )
    axis.legend(loc="upper right", markerscale=1.5)
    colorbar = figure.colorbar(mesh, ax=axis)
    colorbar.set_label("Relative STFT magnitude (dB)")
    figure.savefig(output_path, dpi=SAVE_DPI)
    plt.close(figure)
    return output_path


def _save_two_channel_continuity_plot(
    output_directory: Path,
    results: Mapping[str, RidgeContinuityResult],
) -> Path:
    output_path = output_directory / "two_channel_continuity_comparison.png"
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(11.5, 7.2),
        sharex=True,
        constrained_layout=True,
    )
    colors = ("#1f77b4", "#ff7f0e")
    for color, (channel_name, result) in zip(colors, results.items()):
        relative_time_us = _relative_time_us(result.time_s)
        _scatter_finite(
            axes[0],
            relative_time_us,
            result.absolute_frequency_step_hz / 1.0e6,
            label=channel_name,
            color=color,
        )
        _scatter_finite(
            axes[1],
            relative_time_us,
            result.frequency_slope_hz_s / 1.0e12,
            label=channel_name,
            color=color,
        )
    axes[0].set_ylabel("Absolute step (MHz)")
    axes[1].set_ylabel("Frequency slope (THz/s)")
    axes[1].set_xlabel("Time relative to ridge start (µs)")
    for axis in axes:
        _shade_intervals(axis)
        axis.grid(alpha=0.23)
        axis.legend(loc="best")
    figure.suptitle(
        "Two acquisition channels: ridge continuity evidence\n" + PLOT_NOTICE,
        fontsize=11.0,
    )
    figure.savefig(output_path, dpi=SAVE_DPI)
    plt.close(figure)
    return output_path


def _save_two_channel_related_plot(
    output_directory: Path,
    results: Mapping[str, RelatedFrequencyEvidenceResult],
) -> Path:
    output_path = output_directory / "two_channel_related_frequency_comparison.png"
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(11.5, 7.2),
        sharex=True,
        constrained_layout=True,
    )
    colors = ("#1f77b4", "#ff7f0e")
    for color, (channel_name, result) in zip(colors, results.items()):
        relative_time_us = _relative_time_us(result.time_s)
        _scatter_finite(
            axes[0],
            relative_time_us,
            result.main_to_double_frequency_db,
            label=channel_name,
            color=color,
        )
        _scatter_finite(
            axes[1],
            relative_time_us,
            result.main_to_half_frequency_db,
            label=channel_name,
            color=color,
        )
    axes[0].set_ylabel("Main / double-frequency (dB)")
    axes[1].set_ylabel("Main / half-frequency (dB)")
    axes[1].set_xlabel("Time relative to ridge start (µs)")
    for axis in axes:
        _shade_intervals(axis)
        axis.grid(alpha=0.23)
        axis.legend(loc="best")
    figure.suptitle(
        "Two acquisition channels: related-frequency-band evidence\n" + PLOT_NOTICE,
        fontsize=11.0,
    )
    figure.savefig(output_path, dpi=SAVE_DPI)
    plt.close(figure)
    return output_path


def _interval_mask(
    time_s: FloatArray,
    *,
    start_relative_s: float,
    end_relative_s: float,
    include_end: bool,
) -> BoolArray:
    relative_time_s = time_s - RIDGE_START_TIME_S
    if include_end:
        return (relative_time_s >= start_relative_s) & (
            relative_time_s <= end_relative_s
        )
    return (relative_time_s >= start_relative_s) & (
        relative_time_s < end_relative_s
    )


def _print_metric_summary(label: str, values: FloatArray, unit: str) -> None:
    summary = _finite_summary(values)
    print(
        f"    {label}: n={summary['count']}, min={summary['min']:.9g}, "
        f"median={summary['median']:.9g}, p05={summary['p05']:.9g}, "
        f"p95={summary['p95']:.9g}, max={summary['max']:.9g} {unit}"
    )


def _print_continuity_statistics(
    channel_name: str,
    result: RidgeContinuityResult,
) -> None:
    flag_counts = Counter(flag.value for flag in result.quality_flags)
    status_counts = Counter(status.value for status in result.continuity_statuses)
    print(f"\n  {channel_name} ridge continuity evidence:")
    print(
        f"    total={result.time_s.size}, PRE_EVENT={flag_counts['pre_event']}, "
        f"CANDIDATE={flag_counts['candidate']}, "
        f"OUTSIDE={flag_counts['outside_analysis_window']}"
    )
    for status in RidgeContinuityStatus:
        print(f"    {status.value}={status_counts[status.value]}")
    _print_metric_summary("frequency_step_hz", result.frequency_step_hz, "Hz")
    _print_metric_summary(
        "absolute_frequency_step_hz",
        result.absolute_frequency_step_hz,
        "Hz",
    )
    _print_metric_summary(
        "frequency_slope_hz_s",
        result.frequency_slope_hz_s,
        "Hz/s",
    )
    _print_metric_summary(
        "frequency_second_difference_hz",
        result.frequency_second_difference_hz,
        "Hz",
    )
    interval_specs = (
        (
            "plateau",
            PLATEAU_START_RELATIVE_S,
            PLATEAU_END_RELATIVE_S,
            False,
        ),
        (
            "decline",
            DECLINE_START_RELATIVE_S,
            DECLINE_END_RELATIVE_S,
            True,
        ),
    )
    for label, start_s, end_s, include_end in interval_specs:
        mask = _interval_mask(
            result.time_s,
            start_relative_s=start_s,
            end_relative_s=end_s,
            include_end=include_end,
        )
        print(
            f"    {label} interval="
            f"{'['}{start_s * 1e6:.6g}, {end_s * 1e6:.6g}"
            f"{']' if include_end else ')'} us"
        )
        _print_metric_summary(
            f"{label} absolute_frequency_step_hz",
            result.absolute_frequency_step_hz[mask],
            "Hz",
        )
        _print_metric_summary(
            f"{label} frequency_slope_hz_s",
            result.frequency_slope_hz_s[mask],
            "Hz/s",
        )
    finite_step = np.isfinite(result.absolute_frequency_step_hz)
    if np.any(finite_step):
        finite_indices = np.flatnonzero(finite_step)
        order = np.argsort(result.absolute_frequency_step_hz[finite_indices])[-5:][::-1]
        print("    five largest adjacent absolute steps:")
        for ordered_index in order:
            frame_index = int(finite_indices[int(ordered_index)])
            print(
                f"      t_rel={_relative_time_us(result.time_s)[frame_index]:.9g} us, "
                f"step={result.frequency_step_hz[frame_index]:.9g} Hz, "
                f"abs_step={result.absolute_frequency_step_hz[frame_index]:.9g} Hz"
            )


def _print_related_statistics(
    channel_name: str,
    result: RelatedFrequencyEvidenceResult,
    quality: RidgeSpectralQualityResult,
) -> None:
    print(f"\n  {channel_name} related-frequency-band evidence:")
    for branch_name, statuses in (
        ("double_frequency", result.double_frequency_statuses),
        ("half_frequency", result.half_frequency_statuses),
    ):
        counts = Counter(status.value for status in statuses)
        print(f"    {branch_name} status counts:")
        for status in RelatedFrequencyEvidenceStatus:
            print(f"      {status.value}={counts[status.value]}")
    _print_metric_summary(
        "main_to_double_frequency_db",
        result.main_to_double_frequency_db,
        "dB",
    )
    _print_metric_summary(
        "double_frequency_peak_offset_hz",
        result.double_frequency_peak_offset_hz,
        "Hz",
    )
    _print_metric_summary(
        "main_to_half_frequency_db",
        result.main_to_half_frequency_db,
        "dB",
    )
    _print_metric_summary(
        "half_frequency_peak_offset_hz",
        result.half_frequency_peak_offset_hz,
        "Hz",
    )
    for label, start_s, end_s, include_end in (
        (
            "plateau",
            PLATEAU_START_RELATIVE_S,
            PLATEAU_END_RELATIVE_S,
            False,
        ),
        (
            "decline",
            DECLINE_START_RELATIVE_S,
            DECLINE_END_RELATIVE_S,
            True,
        ),
    ):
        mask = _interval_mask(
            result.time_s,
            start_relative_s=start_s,
            end_relative_s=end_s,
            include_end=include_end,
        )
        _print_metric_summary(
            f"{label} main_to_double_frequency_db",
            result.main_to_double_frequency_db[mask],
            "dB",
        )
        _print_metric_summary(
            f"{label} main_to_half_frequency_db",
            result.main_to_half_frequency_db[mask],
            "dB",
        )

    step_proxy = np.abs(np.diff(result.refined_frequency_hz, prepend=np.nan))
    valid_steps = np.isfinite(step_proxy)
    low_quality = np.isfinite(quality.peak_to_background_db)
    if np.any(valid_steps) and np.any(low_quality):
        step_boundary = float(np.percentile(step_proxy[valid_steps], 95.0))
        quality_boundary = float(
            np.percentile(quality.peak_to_background_db[low_quality], 5.0)
        )
        high_step = valid_steps & (step_proxy >= step_boundary)
        quality_lower_tail = low_quality & (
            quality.peak_to_background_db <= quality_boundary
        )
        overlap = high_step & quality_lower_tail
        print(
            "    descriptive co-occurrence with TASK-008A peak-to-background "
            f"lower tail: high-step frames={np.count_nonzero(high_step)}, "
            f"lower-tail frames={np.count_nonzero(quality_lower_tail)}, "
            f"overlap={np.count_nonzero(overlap)}"
        )
        print(
            f"    descriptive boundaries only: step p95={step_boundary:.9g} Hz; "
            f"quality p05={quality_boundary:.9g} dB; no GOOD/BAD decision"
        )


def _print_two_channel_differences(
    continuity_results: Mapping[str, RidgeContinuityResult],
    related_results: Mapping[str, RelatedFrequencyEvidenceResult],
) -> None:
    if len(continuity_results) != 2 or len(related_results) != 2:
        print("\n  Two-channel diagnostic comparison unavailable: expected two channels.")
        return
    (first_name, first_cont), (second_name, second_cont) = tuple(
        continuity_results.items()
    )
    (_, first_related), (_, second_related) = tuple(related_results.items())
    print(
        f"\n  Cross-acquisition-channel diagnostic differences: "
        f"{first_name} minus {second_name}"
    )
    if not np.array_equal(first_cont.time_s, second_cont.time_s):
        print("    unavailable: the two channel time axes do not match exactly")
        return
    for label, first_values, second_values, unit in (
        (
            "absolute_frequency_step",
            first_cont.absolute_frequency_step_hz,
            second_cont.absolute_frequency_step_hz,
            "Hz",
        ),
        (
            "main_to_double_frequency",
            first_related.main_to_double_frequency_db,
            second_related.main_to_double_frequency_db,
            "dB",
        ),
        (
            "main_to_half_frequency",
            first_related.main_to_half_frequency_db,
            second_related.main_to_half_frequency_db,
            "dB",
        ),
    ):
        paired = np.isfinite(first_values) & np.isfinite(second_values)
        differences = first_values[paired] - second_values[paired]
        if differences.size == 0:
            print(f"    {label}: no paired finite frames")
            continue
        print(
            f"    {label}: paired={differences.size}, "
            f"signed_median={np.median(differences):.9g} {unit}, "
            f"absolute_median={np.median(np.abs(differences)):.9g} {unit}, "
            f"absolute_p95={np.percentile(np.abs(differences), 95.0):.9g} {unit}, "
            f"absolute_max={np.max(np.abs(differences)):.9g} {unit}"
        )
    print(
        "    These values describe cross-acquisition-channel repeatability only; "
        "no averaging, fusion, or automatic channel preference was applied."
    )


def run_ridge_diagnostics_demo(output_directory: Path) -> list[Path]:
    """Run TASK-008B for the fixed 768/640/4096 development configuration."""
    print("\nDPS Studio TASK-008B: ridge continuity and related-frequency evidence")
    print(DIAGNOSTIC_NOTICE)
    print(f"Input file: {DATA_PATH}")
    print(f"Output directory: {output_directory}")
    print(
        f"Fixed parameters: window_name={WINDOW_NAME}, "
        f"window_length_samples={WINDOW_LENGTH_SAMPLES}, "
        f"overlap_samples={OVERLAP_SAMPLES}, hop_samples={HOP_SAMPLES}, nfft={NFFT}"
    )
    if not DATA_PATH.is_file():
        raise FileNotFoundError(f"Input data file does not exist: {DATA_PATH}")
    source_hash_before = _sha256(DATA_PATH)
    print(f"TASK-008B source SHA-256 before: {source_hash_before}")

    generated_paths: list[Path] = []
    try:
        loaded = read_delimited_signals(
            DATA_PATH,
            time_column=0,
            voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
            delimiter=",",
            has_header=False,
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        analyses, runtime_s = _analyze_configuration(
            loaded.records,
            WINDOW_LENGTH_SAMPLES,
            OVERLAP_SAMPLES,
            NFFT,
        )
        print(f"TASK-008B two-channel recomputation runtime: {runtime_s:.6f} s")

        continuity_results: dict[str, RidgeContinuityResult] = {}
        related_results: dict[str, RelatedFrequencyEvidenceResult] = {}
        quality_results: dict[str, RidgeSpectralQualityResult] = {}
        for channel_name, analysis in analyses.items():
            guard_hz = _hann_first_zero_guard_hz(analysis.stft_result)
            search_half_width_hz = _related_search_half_width_hz(
                analysis.stft_result
            )
            print(
                f"  {channel_name}: related-frequency diagnostic half-width = "
                f"sample_rate/window_length = "
                f"{analysis.stft_result.sample_rate_hz:.12g} Hz / "
                f"{analysis.stft_result.window_length_samples} = "
                f"{search_half_width_hz:.12g} Hz"
            )
            quality = assess_ridge_spectral_quality(
                analysis.stft_result,
                analysis.refined_result,
                background_exclusion_half_width_hz=guard_hz,
                minimum_background_bin_count=MINIMUM_BACKGROUND_BIN_COUNT,
            )
            continuity = assess_ridge_continuity(analysis.refined_result)
            related = assess_related_frequency_evidence(
                analysis.stft_result,
                analysis.refined_result,
                quality,
                search_half_width_hz=search_half_width_hz,
            )
            quality_results[channel_name] = quality
            continuity_results[channel_name] = continuity
            related_results[channel_name] = related
            generated_paths.extend(
                [
                    _write_continuity_csv(
                        output_directory,
                        channel_name,
                        analysis.stft_result,
                        continuity,
                    ),
                    _write_related_csv(
                        output_directory,
                        channel_name,
                        analysis.stft_result,
                        related,
                    ),
                    _save_continuity_plot(
                        output_directory,
                        channel_name,
                        continuity,
                    ),
                    _save_related_contrast_plot(
                        output_directory,
                        channel_name,
                        related,
                    ),
                    _save_stft_related_plot(
                        output_directory,
                        channel_name,
                        analysis,
                        related,
                    ),
                ]
            )
            _print_continuity_statistics(channel_name, continuity)
            _print_related_statistics(channel_name, related, quality)

        generated_paths.extend(
            [
                _save_two_channel_continuity_plot(
                    output_directory,
                    continuity_results,
                ),
                _save_two_channel_related_plot(
                    output_directory,
                    related_results,
                ),
            ]
        )
        _print_two_channel_differences(continuity_results, related_results)
    finally:
        source_hash_after = _sha256(DATA_PATH)
        print(f"TASK-008B source SHA-256 after:  {source_hash_after}")
        if source_hash_after != source_hash_before:
            raise RuntimeError("Raw source SHA-256 changed during TASK-008B.")
        print("TASK-008B source SHA-256 unchanged: yes")

    print("TASK-008B generated diagnostic files:")
    for path in generated_paths:
        print(f"  {path.resolve()}")
    print(
        "TASK-008B interpretation guard: outputs are continuity, "
        "related-frequency-band, and cross-acquisition-channel evidence only. "
        "No ridge positions, frequencies, or velocities were changed."
    )
    return generated_paths


def main() -> None:
    from compare_real_ridge_refinement import OUTPUT_DIRECTORY

    run_ridge_diagnostics_demo(OUTPUT_DIRECTORY)


if __name__ == "__main__":
    main()
