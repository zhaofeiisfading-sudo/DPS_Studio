from __future__ import annotations

import csv
import hashlib
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from dps_studio.core.io import DelimitedSignalLoadResult, read_delimited_signals
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import (
    ApparentVelocityResult,
    convert_ridge_to_apparent_velocity,
)
from dps_studio.core.ridge import RidgeQualityFlag, extract_peak_ridge
from dps_studio.core.time_frequency import compute_stft


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "raw" / "20260607.csv"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "velocity_preview"

# Development preview parameters only; not final research parameters.
WINDOW_LENGTH_SAMPLES = 1024
OVERLAP_SAMPLES = 768
NFFT = 2048
WINDOW_NAME = "hann"
RIDGE_MINIMUM_FREQUENCY_HZ = 0.1e9
RIDGE_MAXIMUM_FREQUENCY_HZ = 2.0e9
RIDGE_START_TIME_S = 554.668e-6
ANALYSIS_END_TIME_S = 555.45e-6
TIME_ZERO_S = RIDGE_START_TIME_S

# Must be set only from confirmed experiment or instrument records.
VACUUM_WAVELENGTH_M = 1550e-9

FIGURE_SIZE_INCHES = (12.0, 6.0)
SAVE_DPI = 220

MISSING_WAVELENGTH_MESSAGE = (
    "VACUUM_WAVELENGTH_M is unknown. Set it from confirmed experiment or "
    "instrument records before generating physical velocity results."
)


def load_records() -> DelimitedSignalLoadResult:
    """Load the two real PDV voltage channels without modifying source data."""
    return read_delimited_signals(
        DATA_PATH,
        time_column=0,
        voltage_columns={
            "pdv_channel_1": 1,
            "pdv_channel_2": 2,
        },
        delimiter=",",
        has_header=False,
        encoding="utf-8",
        time_scale=1.0,
        voltage_scales={
            "pdv_channel_1": 1.0,
            "pdv_channel_2": 1.0,
        },
    )


def compute_channel_velocity(
    record: SignalRecord,
    *,
    vacuum_wavelength_m: float,
) -> ApparentVelocityResult:
    """Compute one channel's unsmoothed baseline candidate apparent velocity."""
    stft_result = compute_stft(
        record,
        window_length_samples=WINDOW_LENGTH_SAMPLES,
        overlap_samples=OVERLAP_SAMPLES,
        nfft=NFFT,
        window_name=WINDOW_NAME,
    )
    ridge_result = extract_peak_ridge(
        stft_result,
        minimum_frequency_hz=RIDGE_MINIMUM_FREQUENCY_HZ,
        maximum_frequency_hz=RIDGE_MAXIMUM_FREQUENCY_HZ,
        event_start_time_s=RIDGE_START_TIME_S,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
    )
    return convert_ridge_to_apparent_velocity(
        ridge_result,
        vacuum_wavelength_m=vacuum_wavelength_m,
    )


def write_velocity_csv(
    *,
    channel_name: str,
    result: ApparentVelocityResult,
    output_path: Path,
) -> None:
    """Write every result frame in SI units, including masked NaN frames."""
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            (
                "channel_name",
                "time_absolute_s",
                "time_relative_s",
                "beat_frequency_hz",
                "apparent_velocity_m_s",
                "quality_flag",
            )
        )
        for time_s, frequency_hz, velocity_m_s, quality_flag in zip(
            result.time_s,
            result.beat_frequency_hz,
            result.apparent_velocity_m_s,
            result.quality_flags,
            strict=True,
        ):
            writer.writerow(
                (
                    channel_name,
                    format(float(time_s), ".17g"),
                    format(float(time_s - TIME_ZERO_S), ".17g"),
                    format(float(frequency_hz), ".17g"),
                    format(float(velocity_m_s), ".17g"),
                    quality_flag.value,
                )
            )
    print(f"Saved candidate CSV: {output_path}")


def plot_channel_velocity(
    *,
    channel_name: str,
    result: ApparentVelocityResult,
    output_path: Path,
) -> None:
    """Save one channel's complete unsmoothed candidate trace."""
    time_relative_us = (result.time_s - TIME_ZERO_S) * 1.0e6
    figure, axes = plt.subplots(
        figsize=FIGURE_SIZE_INCHES,
        constrained_layout=True,
    )
    axes.plot(
        time_relative_us,
        result.apparent_velocity_m_s,
        linewidth=0.8,
        color="tab:blue",
        label="Independent baseline-ridge conversion",
    )
    axes.scatter(
        time_relative_us,
        result.apparent_velocity_m_s,
        s=8,
        color="tab:blue",
        alpha=0.75,
        zorder=3,
    )
    axes.axvline(
        0.0,
        color="black",
        linestyle="--",
        linewidth=0.8,
        label="RIDGE_START_TIME_S / relative zero",
    )
    _label_velocity_axes(axes, title_prefix=channel_name)
    axes.legend(loc="best")
    figure.savefig(output_path, dpi=SAVE_DPI, bbox_inches="tight")
    plt.close(figure)
    print(f"Saved candidate PNG: {output_path}")


def plot_velocity_comparison(
    results: dict[str, ApparentVelocityResult],
    *,
    output_path: Path,
) -> None:
    """Overlay two independent channel results without alignment or averaging."""
    figure, axes = plt.subplots(
        figsize=FIGURE_SIZE_INCHES,
        constrained_layout=True,
    )
    colors = ("tab:blue", "tab:orange")
    for (channel_name, result), color in zip(results.items(), colors, strict=True):
        time_relative_us = (result.time_s - TIME_ZERO_S) * 1.0e6
        axes.plot(
            time_relative_us,
            result.apparent_velocity_m_s,
            linewidth=0.8,
            color=color,
            label=channel_name,
        )
        axes.scatter(
            time_relative_us,
            result.apparent_velocity_m_s,
            s=7,
            color=color,
            alpha=0.6,
            zorder=3,
        )
    axes.axvline(0.0, color="black", linestyle="--", linewidth=0.8)
    _label_velocity_axes(axes, title_prefix="Two-channel independent comparison")
    axes.legend(loc="best")
    figure.savefig(output_path, dpi=SAVE_DPI, bbox_inches="tight")
    plt.close(figure)
    print(f"Saved candidate comparison PNG: {output_path}")


def _label_velocity_axes(axes: plt.Axes, *, title_prefix: str) -> None:
    axes.set_xlabel("Relative time from RIDGE_START_TIME_S (µs)")
    axes.set_ylabel("Candidate apparent velocity (m/s)")
    axes.set_title(
        f"{title_prefix} — Candidate apparent velocity\n"
        "no LiF correction | unsigned magnitude | baseline ridge | development preview"
    )
    axes.grid(True, linewidth=0.5, alpha=0.3)


def print_configuration() -> None:
    """Print the full development configuration without implying reliability."""
    print("Candidate apparent velocity development preview")
    print(f"vacuum_wavelength_m={VACUUM_WAVELENGTH_M!r}")
    print(f"conversion_formula={ApparentVelocityResult.CONVERSION_MODEL}")
    print("is_signed=False")
    print(
        "STFT parameters: "
        f"window={WINDOW_NAME!r}, window_length_samples={WINDOW_LENGTH_SAMPLES}, "
        f"overlap_samples={OVERLAP_SAMPLES}, nfft={NFFT}"
    )
    print(
        "Ridge frequency range (Hz): "
        f"[{RIDGE_MINIMUM_FREQUENCY_HZ}, {RIDGE_MAXIMUM_FREQUENCY_HZ}]"
    )
    print(f"RIDGE_START_TIME_S={RIDGE_START_TIME_S}")
    print(f"ANALYSIS_END_TIME_S={ANALYSIS_END_TIME_S}")
    print(f"TIME_ZERO_S={TIME_ZERO_S}")
    print(f"Output directory (created only after wavelength validation): {OUTPUT_DIR}")


def print_channel_statistics(
    channel_name: str,
    result: ApparentVelocityResult,
) -> None:
    """Print descriptive candidate statistics without a reliability claim."""
    finite_velocity = result.apparent_velocity_m_s[
        np.isfinite(result.apparent_velocity_m_s)
    ]
    nan_count = int(np.count_nonzero(np.isnan(result.apparent_velocity_m_s)))
    print(f"{channel_name}: candidate statistics only; no reliability claim")
    print(f"  finite_velocity_count={finite_velocity.size}")
    if finite_velocity.size:
        print(f"  velocity_min_m_s={float(np.min(finite_velocity)):.12g}")
        print(f"  velocity_median_m_s={float(np.median(finite_velocity)):.12g}")
        print(f"  velocity_max_m_s={float(np.max(finite_velocity)):.12g}")
    else:
        print("  velocity_min_m_s=nan")
        print("  velocity_median_m_s=nan")
        print("  velocity_max_m_s=nan")
    print(f"  velocity_nan_count={nan_count}")
    quality_counts = Counter(result.quality_flags)
    for quality_flag in RidgeQualityFlag:
        print(f"  quality_{quality_flag.value}_count={quality_counts[quality_flag]}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _verify_and_print_raw_hash(raw_hash_before: str) -> None:
    raw_hash_after = _sha256(DATA_PATH)
    print(f"Raw SHA-256 before: {raw_hash_before}")
    print(f"Raw SHA-256 after:  {raw_hash_after}")
    if raw_hash_before != raw_hash_after:
        raise RuntimeError("raw data SHA-256 changed during velocity preview")


def main() -> None:
    """Generate candidate velocity previews only when wavelength is confirmed."""
    raw_hash_before = _sha256(DATA_PATH)
    try:
        print_configuration()
        load_result = load_records()
        print(
            f"Loaded {load_result.row_count} rows for channels: "
            f"{', '.join(load_result.channel_names)}"
        )

        if VACUUM_WAVELENGTH_M is None:
            raise SystemExit(MISSING_WAVELENGTH_MESSAGE)

        results = {
            channel_name: compute_channel_velocity(
                load_result.records[channel_name],
                vacuum_wavelength_m=VACUUM_WAVELENGTH_M,
            )
            for channel_name in load_result.channel_names
        }

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        for channel_name, result in results.items():
            csv_path = OUTPUT_DIR / f"{channel_name}_candidate_apparent_velocity.csv"
            png_path = OUTPUT_DIR / f"{channel_name}_candidate_apparent_velocity.png"
            write_velocity_csv(
                channel_name=channel_name,
                result=result,
                output_path=csv_path,
            )
            plot_channel_velocity(
                channel_name=channel_name,
                result=result,
                output_path=png_path,
            )
            print_channel_statistics(channel_name, result)

        comparison_path = OUTPUT_DIR / "candidate_apparent_velocity_comparison.png"
        plot_velocity_comparison(results, output_path=comparison_path)
    finally:
        _verify_and_print_raw_hash(raw_hash_before)


if __name__ == "__main__":
    main()
