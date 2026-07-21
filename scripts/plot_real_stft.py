from __future__ import annotations

import hashlib
from pathlib import Path

import matplotlib.patheffects as path_effects
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import FormatStrFormatter, MultipleLocator
from numpy.typing import NDArray

from dps_studio.core.io import DelimitedSignalLoadResult, read_delimited_signals
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import RidgeResult, extract_peak_ridge
from dps_studio.core.time_frequency import STFTResult, compute_stft


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "raw" / "20260607.csv"
OUTPUT_DIR = PROJECT_ROOT / "outputs" / "stft_preview"

# Development preview parameters only; not final research parameters.
WINDOW_LENGTH_SAMPLES = 1024
OVERLAP_SAMPLES = 768
NFFT = 2048
WINDOW_NAME = "hann"
RIDGE_MINIMUM_FREQUENCY_HZ = 0.1e9
RIDGE_MAXIMUM_FREQUENCY_HZ = 2.0e9

# Manually inspected development window; not an automatic event detector result.
PLOT_START_TIME_S = 554.65e-6
EVENT_START_TIME_S = 554.668e-6
ANALYSIS_END_TIME_S = 555.45e-6

# Display-only scaling. These values do not modify STFT or ridge data.
REFERENCE_PERCENTILE = 99.9
OVERVIEW_MIN_DB = -100.0
OVERVIEW_MAX_DB = 0.0
DETAIL_MIN_DB = -80.0
DETAIL_MAX_DB = 0.0
DETAIL_MAXIMUM_FREQUENCY_HZ = 2.0e9

FIGURE_SIZE_INCHES = (14.0, 7.0)
SAVE_DPI = 220
SHOW_INTERACTIVE = True


FloatArray = NDArray[np.float64]


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


def compute_channel_results(record: SignalRecord) -> tuple[STFTResult, RidgeResult]:
    """Compute unchanged development-preview STFT and baseline ridge results."""
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
        event_start_time_s=EVENT_START_TIME_S,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
    )
    return stft_result, ridge_result


def magnitude_to_relative_db(
    magnitude: FloatArray,
    *,
    reference_percentile: float,
    floor_db: float,
) -> FloatArray:
    """Convert magnitudes to clipped relative dB without modifying the input."""
    magnitude_array = np.asarray(magnitude, dtype=np.float64)
    finite_positive = np.isfinite(magnitude_array) & (magnitude_array > 0.0)
    positive_values = magnitude_array[finite_positive]
    if positive_values.size == 0:
        raise ValueError("magnitude must contain at least one finite positive value")
    if not 0.0 < reference_percentile <= 100.0:
        raise ValueError("reference_percentile must satisfy 0 < value <= 100")
    if not np.isfinite(floor_db) or floor_db >= 0.0:
        raise ValueError("floor_db must be finite and negative")

    reference = float(np.percentile(positive_values, reference_percentile))
    if not np.isfinite(reference) or reference <= 0.0:
        raise ValueError("percentile reference magnitude must be finite and positive")

    relative_db = np.full(magnitude_array.shape, floor_db, dtype=np.float64)
    relative_db[finite_positive] = 20.0 * np.log10(
        magnitude_array[finite_positive] / reference
    )
    return np.clip(relative_db, floor_db, 0.0)


def plot_spectrogram(
    *,
    channel_name: str,
    plot_kind: str,
    stft_result: STFTResult,
    magnitude_db: FloatArray,
    maximum_frequency_hz: float,
    minimum_display_db: float,
    maximum_display_db: float,
    output_path: Path,
    ridge_result: RidgeResult | None = None,
) -> Figure:
    """Render and save one spectrogram without changing numerical results."""
    frequency_mask = stft_result.frequency_hz <= maximum_frequency_hz
    time_us = stft_result.time_s * 1e6
    frequency_ghz = stft_result.frequency_hz[frequency_mask] * 1e-9

    figure, axes = plt.subplots(
        figsize=FIGURE_SIZE_INCHES,
        constrained_layout=True,
    )
    figure.patch.set_facecolor("white")
    axes.set_facecolor("white")

    mesh = axes.pcolormesh(
        time_us,
        frequency_ghz,
        magnitude_db[frequency_mask, :],
        shading="auto",
        cmap="turbo",
        vmin=minimum_display_db,
        vmax=maximum_display_db,
        rasterized=True,
    )
    colorbar = figure.colorbar(mesh, ax=axes, pad=0.015)
    colorbar.set_label("Relative STFT magnitude (dB)")

    axes.axvline(
        EVENT_START_TIME_S * 1e6,
        color="white",
        linestyle="--",
        linewidth=0.8,
        alpha=0.75,
    )
    axes.axvline(
        ANALYSIS_END_TIME_S * 1e6,
        color="white",
        linestyle="--",
        linewidth=0.8,
        alpha=0.75,
    )

    if ridge_result is not None:
        candidate_mask = (
            np.isfinite(ridge_result.frequency_hz)
            & (ridge_result.time_s >= EVENT_START_TIME_S)
            & (ridge_result.time_s <= ANALYSIS_END_TIME_S)
        )
        ridge_frequency_ghz = np.where(
            candidate_mask,
            ridge_result.frequency_hz * 1e-9,
            np.nan,
        )
        (ridge_line,) = axes.plot(
            ridge_result.time_s * 1e6,
            ridge_frequency_ghz,
            color="white",
            linewidth=1.0,
            label="Baseline candidate ridge",
            zorder=4,
        )
        ridge_line.set_path_effects(
            [
                path_effects.Stroke(linewidth=2.2, foreground="black"),
                path_effects.Normal(),
            ]
        )
        axes.legend(loc="upper right", framealpha=0.9)

    maximum_frequency_ghz = maximum_frequency_hz * 1e-9
    axes.set_xlim(PLOT_START_TIME_S * 1e6, ANALYSIS_END_TIME_S * 1e6)
    axes.set_ylim(0.0, maximum_frequency_ghz)
    axes.set_xlabel("Absolute time (µs)")
    axes.set_ylabel("Beat frequency (GHz)")
    axes.set_title(
        f"{channel_name} — STFT {plot_kind}\n"
        "Development preview (not final research parameters): "
        f"window={WINDOW_LENGTH_SAMPLES}, overlap={OVERLAP_SAMPLES}, nfft={NFFT}"
    )

    axes.xaxis.set_major_locator(MultipleLocator(0.1))
    axes.xaxis.set_minor_locator(MultipleLocator(0.05))
    axes.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    if maximum_frequency_ghz > 2.0:
        axes.yaxis.set_major_locator(MultipleLocator(2.0))
        axes.yaxis.set_major_formatter(FormatStrFormatter("%.0f"))
    else:
        axes.yaxis.set_major_locator(MultipleLocator(0.25))
        axes.yaxis.set_minor_locator(MultipleLocator(0.125))
        axes.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    axes.tick_params(axis="both", which="major", labelsize=10)

    figure.savefig(output_path, dpi=SAVE_DPI, bbox_inches="tight")
    print(f"Saved: {output_path}")
    return figure


def plot_channel_outputs(
    channel_name: str,
    stft_result: STFTResult,
    ridge_result: RidgeResult,
) -> Figure:
    """Save overview, detail, and ridge-diagnostic plots for one channel."""
    magnitude = np.abs(stft_result.spectrum)
    overview_db = magnitude_to_relative_db(
        magnitude,
        reference_percentile=REFERENCE_PERCENTILE,
        floor_db=OVERVIEW_MIN_DB,
    )
    detail_db = magnitude_to_relative_db(
        magnitude,
        reference_percentile=REFERENCE_PERCENTILE,
        floor_db=DETAIL_MIN_DB,
    )

    overview_figure = plot_spectrogram(
        channel_name=channel_name,
        plot_kind="overview",
        stft_result=stft_result,
        magnitude_db=overview_db,
        maximum_frequency_hz=float(stft_result.frequency_hz[-1]),
        minimum_display_db=OVERVIEW_MIN_DB,
        maximum_display_db=OVERVIEW_MAX_DB,
        output_path=OUTPUT_DIR / f"{channel_name}_stft_overview.png",
    )
    plt.close(overview_figure)

    detail_figure = plot_spectrogram(
        channel_name=channel_name,
        plot_kind="low-frequency detail",
        stft_result=stft_result,
        magnitude_db=detail_db,
        maximum_frequency_hz=DETAIL_MAXIMUM_FREQUENCY_HZ,
        minimum_display_db=DETAIL_MIN_DB,
        maximum_display_db=DETAIL_MAX_DB,
        output_path=OUTPUT_DIR / f"{channel_name}_stft_detail.png",
    )
    plt.close(detail_figure)

    return plot_spectrogram(
        channel_name=channel_name,
        plot_kind="low-frequency ridge diagnostic",
        stft_result=stft_result,
        magnitude_db=detail_db,
        maximum_frequency_hz=DETAIL_MAXIMUM_FREQUENCY_HZ,
        minimum_display_db=DETAIL_MIN_DB,
        maximum_display_db=DETAIL_MAX_DB,
        output_path=OUTPUT_DIR / f"{channel_name}_stft_ridge.png",
        ridge_result=ridge_result,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    """Generate six development-preview plots and verify raw-data integrity."""
    raw_hash_before = _sha256(DATA_PATH)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    load_result = load_records()

    interactive_figures: list[Figure] = []
    for channel_name in load_result.channel_names:
        stft_result, ridge_result = compute_channel_results(
            load_result.records[channel_name]
        )
        ridge_figure = plot_channel_outputs(
            channel_name,
            stft_result,
            ridge_result,
        )
        if SHOW_INTERACTIVE:
            interactive_figures.append(ridge_figure)
        else:
            plt.close(ridge_figure)

    raw_hash_after = _sha256(DATA_PATH)
    print(f"Raw SHA-256 before: {raw_hash_before}")
    print(f"Raw SHA-256 after:  {raw_hash_after}")
    if raw_hash_before != raw_hash_after:
        raise RuntimeError("raw data SHA-256 changed during plotting")

    if SHOW_INTERACTIVE:
        plt.show()
    else:
        for figure in interactive_figures:
            plt.close(figure)


if __name__ == "__main__":
    main()
