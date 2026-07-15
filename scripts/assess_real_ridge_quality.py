"""Development-only TASK-008A spectral-quality evidence for two raw channels."""

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

from compare_real_ridge_refinement import (  # noqa: E402
    DATA_PATH,
    DECLINE_END_RELATIVE_S,
    DECLINE_START_RELATIVE_S,
    HOP_SAMPLES,
    NFFT,
    OVERLAP_SAMPLES,
    PLATEAU_END_RELATIVE_S,
    PLATEAU_START_RELATIVE_S,
    RIDGE_START_TIME_S,
    WINDOW_LENGTH_SAMPLES,
    WINDOW_NAME,
    _analyze_configuration,
    _sha256,
)
from dps_studio.core.io import read_delimited_signals  # noqa: E402
from dps_studio.core.ridge import (  # noqa: E402
    RidgeQualityFlag,
    RidgeSpectralQualityResult,
    RidgeSpectralQualityStatus,
    assess_ridge_spectral_quality,
)
from dps_studio.core.time_frequency import STFTResult  # noqa: E402


FloatArray = NDArray[np.float64]

MINIMUM_BACKGROUND_BIN_COUNT = 2
FIGURE_SIZE_INCHES = (10.5, 5.2)
SAVE_DPI = 220
QUALITY_NOTICE = (
    "frequency-domain spectral-quality evidence only; no SNR claim, thresholds, "
    "point deletion, smoothing, interpolation, branch identification, channel "
    "selection, channel fusion, LiF correction, or physical-accuracy claim"
)
QUALITY_PLOT_NOTICE = (
    "Spectral-quality evidence only; no SNR, trust threshold, or accuracy claim.\n"
    "No smoothing, branch identification, channel selection/fusion, or ridge change."
)


def _hann_first_zero_guard_hz(stft_result: STFTResult) -> float:
    """Return the diagnostic Hann main-lobe half-width to its first zero.

    ``compute_stft`` uses SciPy's periodic Hann window (``fftbins=True``). Its
    main-lobe first zeros are approximately two unpadded-window DFT bins from
    the center, so the diagnostic half-width is ``2 * sample_rate / N``. This
    is recorded as a development guard, not a validated scientific standard.
    """
    if stft_result.window_name != "hann":
        raise ValueError("The development guard derivation is defined only for Hann.")
    return 2.0 * stft_result.sample_rate_hz / stft_result.window_length_samples


def _write_quality_csv(
    output_directory: Path,
    channel_name: str,
    stft_result: STFTResult,
    result: RidgeSpectralQualityResult,
) -> Path:
    output_path = output_directory / f"{channel_name}_spectral_quality.csv"
    frame = pd.DataFrame(
        {
            "channel_name": channel_name,
            "time_s": result.time_s,
            "time_relative_to_ridge_start_s": result.time_s - RIDGE_START_TIME_S,
            "ridge_quality_flag": [flag.value for flag in result.quality_flags],
            "refinement_status": [
                status.value for status in result.refinement_statuses
            ],
            "spectral_assessment_status": [
                status.value for status in result.assessment_statuses
            ],
            "discrete_frequency_bin_index": result.discrete_frequency_bin_index,
            "discrete_frequency_hz": result.discrete_frequency_hz,
            "refined_frequency_hz": result.refined_frequency_hz,
            "peak_magnitude": result.peak_magnitude,
            "background_median_magnitude": result.background_median_magnitude,
            "strongest_competitor_magnitude": (
                result.strongest_competitor_magnitude
            ),
            "peak_to_background_db": result.peak_to_background_db,
            "peak_to_competitor_db": result.peak_to_competitor_db,
            "background_bin_count": result.background_bin_count,
            "background_exclusion_half_width_hz": (
                result.background_exclusion_half_width_hz
            ),
            "minimum_background_bin_count": result.minimum_background_bin_count,
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
            "assessment_method": result.assessment_method,
            "source_path": "" if result.source_path is None else str(result.source_path),
        }
    )
    frame.to_csv(output_path, index=False)
    return output_path


def _save_metric_plot(
    output_directory: Path,
    channel_name: str,
    result: RidgeSpectralQualityResult,
    *,
    values_db: FloatArray,
    metric_name: str,
    filename_suffix: str,
    title_label: str,
) -> Path:
    output_path = output_directory / f"{channel_name}_{filename_suffix}.png"
    relative_time_us = (result.time_s - RIDGE_START_TIME_S) * 1.0e6
    figure, axis = plt.subplots(figsize=FIGURE_SIZE_INCHES, constrained_layout=True)
    finite = np.isfinite(values_db)
    axis.scatter(
        relative_time_us[finite],
        values_db[finite],
        s=13.0,
        alpha=0.82,
        color="#1f77b4",
        linewidths=0.0,
    )
    axis.axvspan(
        PLATEAU_START_RELATIVE_S * 1.0e6,
        PLATEAU_END_RELATIVE_S * 1.0e6,
        color="#2ca02c",
        alpha=0.08,
        label="diagnostic plateau interval",
    )
    axis.axvspan(
        DECLINE_START_RELATIVE_S * 1.0e6,
        DECLINE_END_RELATIVE_S * 1.0e6,
        color="#d62728",
        alpha=0.06,
        label="diagnostic decline interval",
    )
    axis.set_xlabel("Time relative to ridge start (µs)")
    axis.set_ylabel(f"{metric_name} (dB)")
    axis.set_title(
        f"{channel_name}: {title_label}\n{QUALITY_PLOT_NOTICE}",
        fontsize=11.0,
    )
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.savefig(output_path, dpi=SAVE_DPI)
    plt.close(figure)
    return output_path


def _save_two_channel_comparison(
    output_directory: Path,
    results: Mapping[str, RidgeSpectralQualityResult],
) -> Path:
    output_path = output_directory / "two_channel_spectral_quality_comparison.png"
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(11.5, 8.0),
        sharex=True,
        constrained_layout=True,
    )
    metrics = (
        ("peak_to_background_db", "Peak-to-background contrast (dB)"),
        ("peak_to_competitor_db", "Peak-to-competitor advantage (dB)"),
    )
    colors = ("#1f77b4", "#ff7f0e")
    for axis, (field_name, axis_label) in zip(axes, metrics):
        for color, (channel_name, result) in zip(colors, results.items()):
            values = getattr(result, field_name)
            relative_time_us = (result.time_s - RIDGE_START_TIME_S) * 1.0e6
            finite = np.isfinite(values)
            axis.scatter(
                relative_time_us[finite],
                values[finite],
                s=11.0,
                alpha=0.72,
                linewidths=0.0,
                color=color,
                label=channel_name,
            )
        axis.set_ylabel(axis_label)
        axis.grid(alpha=0.25)
        axis.legend(loc="best")
    axes[-1].set_xlabel("Time relative to ridge start (µs)")
    figure.suptitle(
        "Two acquisition channels: per-frame spectral-quality evidence\n"
        + QUALITY_PLOT_NOTICE,
        fontsize=11.0,
    )
    figure.savefig(output_path, dpi=SAVE_DPI)
    plt.close(figure)
    return output_path


def _finite_summary(values: FloatArray) -> dict[str, float | int]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return {
            "count": 0,
            "min": np.nan,
            "median": np.nan,
            "p05": np.nan,
            "p95": np.nan,
            "max": np.nan,
        }
    return {
        "count": int(finite.size),
        "min": float(np.min(finite)),
        "median": float(np.median(finite)),
        "p05": float(np.percentile(finite, 5.0)),
        "p95": float(np.percentile(finite, 95.0)),
        "max": float(np.max(finite)),
    }


def _print_summary(label: str, values: FloatArray) -> None:
    summary = _finite_summary(values)
    print(
        f"    {label}: n={summary['count']}, min={summary['min']:.9g}, "
        f"median={summary['median']:.9g}, p05={summary['p05']:.9g}, "
        f"p95={summary['p95']:.9g}, max={summary['max']:.9g} dB"
    )


def _interval_mask(
    result: RidgeSpectralQualityResult,
    *,
    start_relative_s: float,
    end_relative_s: float,
    include_end: bool,
) -> NDArray[np.bool_]:
    relative_time_s = result.time_s - RIDGE_START_TIME_S
    if include_end:
        return (relative_time_s >= start_relative_s) & (
            relative_time_s <= end_relative_s
        )
    return (relative_time_s >= start_relative_s) & (relative_time_s < end_relative_s)


def _lower_tail_intervals(
    result: RidgeSpectralQualityResult,
    values_db: FloatArray,
) -> tuple[float, list[tuple[float, float]]]:
    finite = np.isfinite(values_db)
    if not np.any(finite):
        return np.nan, []
    threshold = float(np.percentile(values_db[finite], 5.0))
    indices = np.flatnonzero(finite & (values_db <= threshold))
    if indices.size == 0:
        return threshold, []
    intervals: list[tuple[float, float]] = []
    start = int(indices[0])
    previous = start
    for raw_index in indices[1:]:
        index = int(raw_index)
        if index != previous + 1:
            intervals.append(
                (
                    float((result.time_s[start] - RIDGE_START_TIME_S) * 1.0e6),
                    float((result.time_s[previous] - RIDGE_START_TIME_S) * 1.0e6),
                )
            )
            start = index
        previous = index
    intervals.append(
        (
            float((result.time_s[start] - RIDGE_START_TIME_S) * 1.0e6),
            float((result.time_s[previous] - RIDGE_START_TIME_S) * 1.0e6),
        )
    )
    return threshold, intervals


def _print_channel_statistics(
    channel_name: str,
    result: RidgeSpectralQualityResult,
) -> None:
    flag_counts = Counter(flag.value for flag in result.quality_flags)
    status_counts = Counter(status.value for status in result.assessment_statuses)
    total = result.time_s.size
    candidate = flag_counts[RidgeQualityFlag.CANDIDATE.value]
    assessed = status_counts[RidgeSpectralQualityStatus.ASSESSED.value]
    total_ratio = assessed / total if total else np.nan
    candidate_ratio = assessed / candidate if candidate else np.nan
    print(f"\n  {channel_name} spectral-quality evidence:")
    print(
        f"    total={total}, PRE_EVENT={flag_counts['pre_event']}, "
        f"CANDIDATE={candidate}, "
        f"OUTSIDE={flag_counts['outside_analysis_window']}"
    )
    print(
        f"    ASSESSED={assessed}, ASSESSED/total={total_ratio:.6%}, "
        f"ASSESSED/CANDIDATE={candidate_ratio:.6%}"
    )
    for status in (
        RidgeSpectralQualityStatus.INSUFFICIENT_BACKGROUND_BINS,
        RidgeSpectralQualityStatus.INVALID_PEAK_MAGNITUDE,
        RidgeSpectralQualityStatus.INVALID_BACKGROUND,
        RidgeSpectralQualityStatus.INVALID_COMPETITOR,
        RidgeSpectralQualityStatus.INPUT_MISMATCH,
    ):
        print(f"    {status.value}={status_counts[status.value]}")
    _print_summary("peak_to_background_db", result.peak_to_background_db)
    _print_summary("peak_to_competitor_db", result.peak_to_competitor_db)

    plateau_mask = _interval_mask(
        result,
        start_relative_s=PLATEAU_START_RELATIVE_S,
        end_relative_s=PLATEAU_END_RELATIVE_S,
        include_end=False,
    )
    decline_mask = _interval_mask(
        result,
        start_relative_s=DECLINE_START_RELATIVE_S,
        end_relative_s=DECLINE_END_RELATIVE_S,
        include_end=True,
    )
    print(
        f"    plateau interval=[{PLATEAU_START_RELATIVE_S * 1e6:.6g}, "
        f"{PLATEAU_END_RELATIVE_S * 1e6:.6g}) us"
    )
    _print_summary(
        "plateau peak_to_background_db",
        result.peak_to_background_db[plateau_mask],
    )
    _print_summary(
        "plateau peak_to_competitor_db",
        result.peak_to_competitor_db[plateau_mask],
    )
    print(
        f"    decline interval=[{DECLINE_START_RELATIVE_S * 1e6:.6g}, "
        f"{DECLINE_END_RELATIVE_S * 1e6:.6g}] us"
    )
    _print_summary(
        "decline peak_to_background_db",
        result.peak_to_background_db[decline_mask],
    )
    _print_summary(
        "decline peak_to_competitor_db",
        result.peak_to_competitor_db[decline_mask],
    )

    for label, values in (
        ("peak_to_background_db", result.peak_to_background_db),
        ("peak_to_competitor_db", result.peak_to_competitor_db),
    ):
        threshold, intervals = _lower_tail_intervals(result, values)
        formatted = ", ".join(
            f"[{start:.6g}, {end:.6g}] us" for start, end in intervals
        )
        print(
            f"    descriptive lower 5% {label}: boundary={threshold:.9g} dB; "
            f"intervals={formatted or 'none'}"
        )
    print(
        "    Lower-tail intervals are descriptive diagnostics only; they are not "
        "GOOD/BAD or trusted/untrusted thresholds."
    )


def _print_channel_differences(
    results: Mapping[str, RidgeSpectralQualityResult],
) -> None:
    if len(results) != 2:
        print("\n  Two-channel difference statistics unavailable: expected two channels.")
        return
    (first_name, first), (second_name, second) = tuple(results.items())
    print(
        f"\n  Cross-acquisition-channel repeatability: {first_name} minus {second_name}"
    )
    if not np.array_equal(first.time_s, second.time_s):
        print("    unavailable: the two channel time axes do not match exactly")
        return
    for label in ("peak_to_background_db", "peak_to_competitor_db"):
        first_values = getattr(first, label)
        second_values = getattr(second, label)
        paired = np.isfinite(first_values) & np.isfinite(second_values)
        differences = first_values[paired] - second_values[paired]
        absolute_differences = np.abs(differences)
        if differences.size == 0:
            print(f"    {label}: no paired finite frames")
            continue
        print(
            f"    {label}: paired={differences.size}, "
            f"signed_median={np.median(differences):.9g} dB, "
            f"absolute_median={np.median(absolute_differences):.9g} dB, "
            f"absolute_p95={np.percentile(absolute_differences, 95.0):.9g} dB, "
            f"absolute_max={np.max(absolute_differences):.9g} dB"
        )
    print(
        "    These are cross-acquisition-channel differences only; no averaging, "
        "fusion, or automatic channel preference was applied."
    )


def run_spectral_quality_demo(output_directory: Path) -> list[Path]:
    """Run TASK-008A for the fixed 768/640/4096 development configuration."""
    print("\nDPS Studio TASK-008A: selected-peak spectral-quality evidence")
    print(QUALITY_NOTICE)
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
    print(f"TASK-008A source SHA-256 before: {source_hash_before}")

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
        print(f"TASK-008A two-channel recomputation runtime: {runtime_s:.6f} s")

        quality_results: dict[str, RidgeSpectralQualityResult] = {}
        for channel_name, analysis in analyses.items():
            guard_hz = _hann_first_zero_guard_hz(analysis.stft_result)
            print(
                f"  {channel_name}: diagnostic Hann first-zero half-width = "
                f"2 * {analysis.stft_result.sample_rate_hz:.12g} Hz / "
                f"{analysis.stft_result.window_length_samples} = {guard_hz:.12g} Hz"
            )
            result = assess_ridge_spectral_quality(
                analysis.stft_result,
                analysis.refined_result,
                background_exclusion_half_width_hz=guard_hz,
                minimum_background_bin_count=MINIMUM_BACKGROUND_BIN_COUNT,
            )
            quality_results[channel_name] = result
            generated_paths.extend(
                [
                    _write_quality_csv(
                        output_directory,
                        channel_name,
                        analysis.stft_result,
                        result,
                    ),
                    _save_metric_plot(
                        output_directory,
                        channel_name,
                        result,
                        values_db=result.peak_to_background_db,
                        metric_name="Peak-to-background contrast",
                        filename_suffix="peak_to_background_db",
                        title_label="selected peak versus guarded-band background median",
                    ),
                    _save_metric_plot(
                        output_directory,
                        channel_name,
                        result,
                        values_db=result.peak_to_competitor_db,
                        metric_name="Peak-to-competitor advantage",
                        filename_suffix="peak_to_competitor_db",
                        title_label="selected peak versus strongest remaining peak",
                    ),
                ]
            )
            _print_channel_statistics(channel_name, result)

        generated_paths.append(
            _save_two_channel_comparison(output_directory, quality_results)
        )
        _print_channel_differences(quality_results)
    finally:
        source_hash_after = _sha256(DATA_PATH)
        print(f"TASK-008A source SHA-256 after:  {source_hash_after}")
        if source_hash_after != source_hash_before:
            raise RuntimeError("Raw source SHA-256 changed during TASK-008A.")
        print("TASK-008A source SHA-256 unchanged: yes")

    print("TASK-008A generated quality files:")
    for path in generated_paths:
        print(f"  {path.resolve()}")
    print(
        "TASK-008A interpretation guard: metrics are spectral-quality evidence and "
        "cross-acquisition-channel repeatability only. Ridge positions were unchanged."
    )
    return generated_paths


def main() -> None:
    from compare_real_ridge_refinement import OUTPUT_DIRECTORY

    run_spectral_quality_demo(OUTPUT_DIRECTORY)


if __name__ == "__main__":
    main()
