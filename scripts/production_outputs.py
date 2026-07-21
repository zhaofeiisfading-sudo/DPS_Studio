"""Practical production outputs composed from the existing analysis algorithms."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter

import matplotlib
import numpy as np
import pandas as pd
import scipy

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from compare_real_ridge_refinement import (  # noqa: E402
    ChannelAnalysis,
    _analyze_configuration,
    _relative_stft_magnitude_db,
)
from dps_studio.core import AnalysisProfile, OutputMode  # noqa: E402
from dps_studio.core.models import SignalRecord  # noqa: E402
from dps_studio.core.ridge import (  # noqa: E402
    RidgeContinuityResult,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeSpectralQualityResult,
    assess_ridge_continuity,
    assess_ridge_spectral_quality,
)


PRODUCTION_FILENAMES = (
    "pdv_channel_1_apparent_velocity.csv",
    "pdv_channel_2_apparent_velocity.csv",
    "two_channel_apparent_velocity_comparison.png",
    "pdv_channel_1_stft_with_ridge.png",
    "pdv_channel_2_stft_with_ridge.png",
    "quality_summary.csv",
    "run_manifest.json",
    "run.log",
)

INTERPRETATION_GUARDS = (
    "unsigned apparent velocity",
    "no LiF correction",
    "no channel selection or fusion",
    "no smoothing or interpolation",
    "high-overlap frames are not independent measurements",
    "high-time profile is not a higher-accuracy claim",
    "quality metrics do not automatically validate physical branch identity",
)


def run_production_outputs(
    output_directory: Path,
    records: Mapping[str, SignalRecord],
    *,
    profile: AnalysisProfile,
    vacuum_wavelength_m: float,
    event_start_time_s: float,
    analysis_end_time_s: float,
    source_path: Path,
    source_sha256: str,
) -> list[Path]:
    """Generate exactly eight practical files without changing analysis results."""
    start_clock = perf_counter()
    _validate_run_inputs(
        output_directory,
        records,
        profile=profile,
        vacuum_wavelength_m=vacuum_wavelength_m,
        event_start_time_s=event_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        source_path=source_path,
        source_sha256=source_sha256,
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    log_lines = [
        "DPS Studio production run",
        f"profile_id={profile.profile_id.value}",
        f"output_mode={OutputMode.PRODUCTION.value}",
        f"source_path={source_path}",
        f"source_sha256={source_sha256}",
    ]

    analyses, analysis_runtime_s = _analyze_configuration(
        records,
        profile.window_length_samples,
        profile.overlap_samples,
        profile.nfft,
        window_name=profile.window_name,
        minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz,
        event_start_time_s=event_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        vacuum_wavelength_m=vacuum_wavelength_m,
    )
    quality_results: dict[str, RidgeSpectralQualityResult] = {}
    continuity_results: dict[str, RidgeContinuityResult] = {}
    for channel_name, analysis in analyses.items():
        guard_hz = (
            2.0
            * analysis.stft_result.sample_rate_hz
            / analysis.stft_result.window_length_samples
        )
        quality = assess_ridge_spectral_quality(
            analysis.stft_result,
            analysis.refined_result,
            background_exclusion_half_width_hz=guard_hz,
            minimum_background_bin_count=2,
        )
        continuity = assess_ridge_continuity(analysis.refined_result)
        _validate_channel_results(analysis, quality, continuity)
        quality_results[channel_name] = quality
        continuity_results[channel_name] = continuity

    generated_paths: list[Path] = []
    for channel_name in sorted(analyses):
        generated_paths.append(
            _write_apparent_velocity_csv(
                output_directory,
                channel_name,
                analyses[channel_name],
                quality_results[channel_name],
                continuity_results[channel_name],
                event_start_time_s=event_start_time_s,
            )
        )
    generated_paths.append(
        _save_two_channel_comparison(
            output_directory,
            analyses,
            event_start_time_s=event_start_time_s,
        )
    )
    for channel_name in sorted(analyses):
        generated_paths.append(
            _save_stft_with_ridge(
                output_directory,
                channel_name,
                analyses[channel_name],
                profile=profile,
                event_start_time_s=event_start_time_s,
            )
        )
    summary_path, channel_summaries = _write_quality_summary(
        output_directory,
        analyses,
        quality_results,
        continuity_results,
        profile=profile,
        source_sha256=source_sha256,
    )
    generated_paths.append(summary_path)

    expected_paths = [output_directory / name for name in PRODUCTION_FILENAMES]
    manifest_path = output_directory / "run_manifest.json"
    manifest = _build_manifest(
        profile=profile,
        vacuum_wavelength_m=vacuum_wavelength_m,
        event_start_time_s=event_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        analyses=analyses,
        source_path=source_path,
        source_sha256=source_sha256,
        generated_paths=expected_paths,
        channel_summaries=channel_summaries,
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    generated_paths.append(manifest_path)

    for channel_name, summary in channel_summaries.items():
        log_lines.append(
            f"{channel_name}: candidate={summary['candidate_frame_count']}, "
            f"refined={summary['refined_frame_count']}"
        )
    log_lines.extend(
        (
            f"analysis_runtime_s={analysis_runtime_s:.9f}",
            f"total_runtime_s={perf_counter() - start_clock:.9f}",
            "interpretation_guards:",
            *(f"- {guard}" for guard in INTERPRETATION_GUARDS),
        )
    )
    log_path = output_directory / "run.log"
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    generated_paths.append(log_path)

    source_hash_after = _sha256(source_path)
    if source_hash_after != source_sha256:
        raise RuntimeError("Source SHA-256 changed during production analysis.")
    actual_names = tuple(sorted(path.name for path in output_directory.iterdir()))
    if actual_names != tuple(sorted(PRODUCTION_FILENAMES)):
        raise RuntimeError(
            "Production output set differs from the explicit eight-file contract."
        )
    return generated_paths


def _validate_run_inputs(
    output_directory: Path,
    records: Mapping[str, SignalRecord],
    *,
    profile: AnalysisProfile,
    vacuum_wavelength_m: float,
    event_start_time_s: float,
    analysis_end_time_s: float,
    source_path: Path,
    source_sha256: str,
) -> None:
    if not isinstance(output_directory, Path):
        raise TypeError("output_directory must be pathlib.Path.")
    if output_directory.exists() and any(output_directory.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_directory}")
    if not isinstance(profile, AnalysisProfile):
        raise TypeError("profile must be an AnalysisProfile.")
    if tuple(sorted(records)) != ("pdv_channel_1", "pdv_channel_2"):
        raise ValueError("Production requires the two explicit PDV acquisition channels.")
    if not np.isfinite(vacuum_wavelength_m) or vacuum_wavelength_m <= 0.0:
        raise ValueError("vacuum_wavelength_m must be finite and positive.")
    if not np.isfinite(event_start_time_s) or not np.isfinite(analysis_end_time_s):
        raise ValueError("Event and analysis times must be finite.")
    if event_start_time_s > analysis_end_time_s:
        raise ValueError("event_start_time_s cannot exceed analysis_end_time_s.")
    if not isinstance(source_path, Path) or not source_path.is_file():
        raise FileNotFoundError(f"Source file does not exist: {source_path}")
    if _sha256(source_path) != source_sha256:
        raise RuntimeError("source_sha256 does not match source_path.")
    for channel_name, record in records.items():
        if not isinstance(record, SignalRecord):
            raise TypeError(f"{channel_name} must map to SignalRecord.")
        if record.source_path != source_path:
            raise ValueError("Every channel source_path must match source_path exactly.")


def _validate_channel_results(
    analysis: ChannelAnalysis,
    quality: RidgeSpectralQualityResult,
    continuity: RidgeContinuityResult,
) -> None:
    time_axis = analysis.stft_result.time_s
    source_path = analysis.stft_result.source_path
    results = (analysis.ridge_result, analysis.refined_result, quality, continuity)
    for result in results:
        if not np.array_equal(result.time_s, time_axis):
            raise RuntimeError("Production result time axes must match exactly.")
        if result.source_path != source_path:
            raise RuntimeError("Production result source_path values must match exactly.")
    frame_count = time_axis.size
    if any(
        values.size != frame_count
        for values in (
            analysis.refined_velocity_m_s,
            analysis.display_velocity_m_s,
            quality.peak_to_background_db,
            quality.peak_to_competitor_db,
            continuity.frequency_step_hz,
            continuity.frequency_slope_hz_s,
        )
    ):
        raise RuntimeError("Production result frame counts must match exactly.")
    if len(analysis.velocity_origins) != frame_count:
        raise RuntimeError("velocity_origins must match the time axis.")
    if quality.quality_flags != analysis.refined_result.quality_flags:
        raise RuntimeError("Spectral-quality flags must match the refined ridge.")
    if continuity.quality_flags != analysis.refined_result.quality_flags:
        raise RuntimeError("Continuity flags must match the refined ridge.")
    if quality.refinement_statuses != analysis.refined_result.refinement_statuses:
        raise RuntimeError("Spectral-quality refinement statuses must match.")
    if continuity.refinement_statuses != analysis.refined_result.refinement_statuses:
        raise RuntimeError("Continuity refinement statuses must match.")


def _write_apparent_velocity_csv(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    quality: RidgeSpectralQualityResult,
    continuity: RidgeContinuityResult,
    *,
    event_start_time_s: float,
) -> Path:
    path = output_directory / f"{channel_name}_apparent_velocity.csv"
    refined = analysis.refined_result
    pd.DataFrame(
        {
            "time_s": refined.time_s,
            "time_relative_to_event_s": refined.time_s - event_start_time_s,
            "refined_frequency_hz": refined.refined_frequency_hz,
            "apparent_velocity_m_s": analysis.refined_velocity_m_s,
            "display_velocity_m_s": analysis.display_velocity_m_s,
            "velocity_origin": analysis.velocity_origins,
            "quality_flag": [flag.value for flag in refined.quality_flags],
            "refinement_status": [
                status.value for status in refined.refinement_statuses
            ],
            "peak_to_background_db": quality.peak_to_background_db,
            "peak_to_competitor_db": quality.peak_to_competitor_db,
            "continuity_status": [
                status.value for status in continuity.continuity_statuses
            ],
            "frequency_step_hz": continuity.frequency_step_hz,
            "frequency_slope_hz_s": continuity.frequency_slope_hz_s,
        }
    ).to_csv(path, index=False)
    return path


def _write_quality_summary(
    output_directory: Path,
    analyses: Mapping[str, ChannelAnalysis],
    quality_results: Mapping[str, RidgeSpectralQualityResult],
    continuity_results: Mapping[str, RidgeContinuityResult],
    *,
    profile: AnalysisProfile,
    source_sha256: str,
) -> tuple[Path, dict[str, dict[str, object]]]:
    rows: list[dict[str, object]] = []
    summaries: dict[str, dict[str, object]] = {}
    for channel_name in sorted(analyses):
        analysis = analyses[channel_name]
        refined = analysis.refined_result
        quality = quality_results[channel_name]
        continuity = continuity_results[channel_name]
        candidate_count = sum(
            flag is RidgeQualityFlag.CANDIDATE for flag in refined.quality_flags
        )
        refined_count = sum(
            status is RidgeRefinementStatus.REFINED
            for status in refined.refinement_statuses
        )
        finite_steps = continuity.absolute_frequency_step_hz[
            np.isfinite(continuity.absolute_frequency_step_hz)
        ]
        row = {
            "channel_name": channel_name,
            "profile_id": profile.profile_id.value,
            "candidate_frame_count": candidate_count,
            "refined_frame_count": refined_count,
            "peak_to_background_db_median": _finite_percentile(
                quality.peak_to_background_db, 50.0
            ),
            "peak_to_background_db_p05": _finite_percentile(
                quality.peak_to_background_db, 5.0
            ),
            "peak_to_competitor_db_median": _finite_percentile(
                quality.peak_to_competitor_db, 50.0
            ),
            "peak_to_competitor_db_p05": _finite_percentile(
                quality.peak_to_competitor_db, 5.0
            ),
            "finite_continuity_step_count": int(finite_steps.size),
            "maximum_absolute_frequency_step_hz": (
                float(np.max(finite_steps)) if finite_steps.size else float("nan")
            ),
            "source_path": str(refined.source_path) if refined.source_path else "",
            "source_sha256": source_sha256,
        }
        rows.append(row)
        summaries[channel_name] = dict(row)
    path = output_directory / "quality_summary.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return path, summaries


def _save_two_channel_comparison(
    output_directory: Path,
    analyses: Mapping[str, ChannelAnalysis],
    *,
    event_start_time_s: float,
) -> Path:
    path = output_directory / "two_channel_apparent_velocity_comparison.png"
    figure, axis = plt.subplots(figsize=(11.0, 6.5), constrained_layout=True)
    for channel_name, color in zip(sorted(analyses), ("#1f77b4", "#ff7f0e"), strict=True):
        analysis = analyses[channel_name]
        axis.plot(
            (analysis.refined_result.time_s - event_start_time_s) * 1.0e6,
            analysis.refined_velocity_m_s,
            linewidth=0.8,
            color=color,
            label=channel_name,
        )
    axis.set_xlabel("Time relative to event (µs)")
    axis.set_ylabel("Unsigned apparent velocity (m/s)")
    axis.set_title("Independent acquisition-channel apparent velocities")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    figure.savefig(path, dpi=220)
    plt.close(figure)
    return path


def _save_stft_with_ridge(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    profile: AnalysisProfile,
    event_start_time_s: float,
) -> Path:
    path = output_directory / f"{channel_name}_stft_with_ridge.png"
    stft = analysis.stft_result
    frequency_mask = (stft.frequency_hz >= profile.minimum_frequency_hz) & (
        stft.frequency_hz <= profile.maximum_frequency_hz
    )
    magnitude = np.abs(stft.spectrum[frequency_mask, :])
    display_db = _relative_stft_magnitude_db(magnitude, floor_db=-60.0)
    figure, axis = plt.subplots(figsize=(11.0, 6.5), constrained_layout=True)
    mesh = axis.pcolormesh(
        (stft.time_s - event_start_time_s) * 1.0e6,
        stft.frequency_hz[frequency_mask] * 1.0e-9,
        display_db,
        shading="auto",
        cmap="viridis",
        vmin=-60.0,
        vmax=0.0,
        rasterized=True,
    )
    axis.plot(
        (analysis.refined_result.time_s - event_start_time_s) * 1.0e6,
        analysis.refined_result.refined_frequency_hz * 1.0e-9,
        color="white",
        linewidth=0.8,
        label="refined candidate ridge",
    )
    figure.colorbar(mesh, ax=axis, label="Relative STFT magnitude (dB)")
    axis.set_xlabel("Time relative to event (µs)")
    axis.set_ylabel("Frequency (GHz)")
    axis.set_title(f"{channel_name} — {profile.display_name} STFT and ridge")
    axis.legend(loc="best")
    figure.savefig(path, dpi=220)
    plt.close(figure)
    return path


def _build_manifest(
    *,
    profile: AnalysisProfile,
    vacuum_wavelength_m: float,
    event_start_time_s: float,
    analysis_end_time_s: float,
    analyses: Mapping[str, ChannelAnalysis],
    source_path: Path,
    source_sha256: str,
    generated_paths: list[Path],
    channel_summaries: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    sample_rates = {analysis.stft_result.sample_rate_hz for analysis in analyses.values()}
    if len(sample_rates) != 1:
        raise RuntimeError("Production channels must have one common sample rate.")
    return {
        "profile_id": profile.profile_id.value,
        "profile": {
            "display_name": profile.display_name,
            "window_name": profile.window_name,
            "window_length_samples": profile.window_length_samples,
            "overlap_samples": profile.overlap_samples,
            "hop_samples": profile.hop_samples,
            "nfft": profile.nfft,
            "minimum_frequency_hz": profile.minimum_frequency_hz,
            "maximum_frequency_hz": profile.maximum_frequency_hz,
            "ridge_refinement": profile.ridge_refinement,
            "tradeoff_note": profile.tradeoff_note,
        },
        "output_mode": OutputMode.PRODUCTION.value,
        "wavelength_m": vacuum_wavelength_m,
        "event_start_time_s": event_start_time_s,
        "analysis_end_time_s": analysis_end_time_s,
        "sample_rate_hz": next(iter(sample_rates)),
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "dps-studio": _package_version(),
        },
        "git_head": _git_output("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git_output("status", "--porcelain")),
        "generated_files": [path.name for path in generated_paths],
        "channel_summaries": {
            name: dict(summary) for name, summary in channel_summaries.items()
        },
        "interpretation_guards": list(INTERPRETATION_GUARDS),
    }


def _finite_percentile(values: np.ndarray, percentile: float) -> float:
    finite = values[np.isfinite(values)]
    return float(np.percentile(finite, percentile)) if finite.size else float("nan")


def _package_version() -> str:
    try:
        return version("dps-studio")
    except PackageNotFoundError:
        return "0.1.0+source"


def _git_output(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "INTERPRETATION_GUARDS",
    "PRODUCTION_FILENAMES",
    "run_production_outputs",
]
