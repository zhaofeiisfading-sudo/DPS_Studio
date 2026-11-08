"""Formal dual-profile production file and plot outputs."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import matplotlib
import numpy as np
import pandas as pd
import scipy

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from dps_studio.core.analysis_profiles import AnalysisProfile  # noqa: E402
from dps_studio.core.event_candidates import (  # noqa: E402
    CrossProfileConsensusResult,
    EventCandidateConfig,
    EventConsensusConfig,
    PhysicalBranchReviewStatus,
    ProfileConsensusResult,
    StreamEventCandidates,
    build_cross_profile_consensus,
    build_profile_consensus,
    build_stream_event_candidates,
)
from dps_studio.core.models import SignalRecord  # noqa: E402
from dps_studio.core.physics import (  # noqa: E402
    convert_ridge_to_apparent_velocity,
    velocity_correction_metadata,
)
from dps_studio.core.quality import SignalDetectionConfig, SignalState  # noqa: E402
from dps_studio.core.ridge import (  # noqa: E402
    RidgeResult,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    extract_peak_ridge,
)
from dps_studio.core.workflow import (  # noqa: E402
    ChannelAnalysis,
    WorkflowConfiguration,
    analyze_profile,
)


DETAILED_DIAGNOSTIC_FILENAMES = (
    "apparent_velocity_diagnostics.csv",
)
CHANNEL_PLOT_FILENAMES = (
    "stft_full_band.png",
    "stft_analysis_band_with_ridge.png",
    "apparent_velocity_full_overview.png",
    "apparent_velocity_full_time_reviewed.png",
    "apparent_velocity_full_time_formal.png",
    "apparent_velocity_event_detail.png",
    "apparent_velocity_state_diagnostics.png",
    "signal_detection_diagnostics.png",
)
CHANNEL_FILENAMES = (*DETAILED_DIAGNOSTIC_FILENAMES, *CHANNEL_PLOT_FILENAMES)
PROFILE_FILENAMES = (
    "quality_summary.csv",
    "detected_event_candidates.png",
    "profile_manifest.json",
)
COMPARISON_FILENAMES = (
    "all_measured_segments_timeline.png",
    "band_boundary_fraction_comparison.png",
    "cross_profile_consensus.png",
    "event_candidate_sensitivity.csv",
    "measured_segments.csv",
    "spectral_contrast_distribution_comparison.png",
    "threshold_calibration.csv",
    "threshold_transferability_audit.csv",
)
PRODUCTION_SUPPORT_ROOT_ENTRIES = (
    "README.txt",
    "comparisons",
    "event_consensus.json",
    "run.log",
    "run_manifest.json",
    "simple_exports",
)
SIMPLE_EXPORT_README_FILENAME = "README.txt"
THRESHOLD_CALIBRATION_CANDIDATES_DB = (
    (10.0, 3.0),
    (12.0, 4.0),
    (14.0, 5.0),
    (16.0, 6.0),
)
THRESHOLD_CALIBRATION_PROVENANCE = (
    "development-calibrated for the current production record; not an absolute "
    "experimental standard"
)
THRESHOLD_CALIBRATION_FILENAME = "threshold_calibration.csv"
MAIN_EVENT_MINIMUM_RETENTION_FRACTION = 0.98

INTERPRETATION_GUARDS = (
    "unsigned apparent velocity",
    "configured wavelength is a demonstration value not confirmed by experiment records",
    "no LiF, refractive-index, or incidence-angle correction",
    "no channel selection, averaging, or fusion",
    "no profile selection, averaging, or fusion",
    "no smoothing, interpolation, filtering, resampling, or invented low-speed data",
    "pre-event display zero is disabled by default; if enabled it is display-only",
    "high-overlap frames are not independent measurements",
    "high-time profile is not a higher-accuracy claim",
    "quality metrics do not automatically validate physical branch identity",
    "MEASURED means spectrally qualified; physical branch identity remains unreviewed",
    "quality-unfiltered argmax preview is not a measurement",
    "lower-bound argmax is not zero velocity",
    "event candidates and consensus do not modify formal per-frame arrays",
    "display-only bridge has two endpoints and writes no intermediate CSV data",
    "simple-export zero is a pre-consensus plotting convention and not measured",
)
QUALITY_UNFILTERED_PREVIEW_LABEL = (
    "quality-unfiltered argmax preview; not a measurement"
)
LOWER_BOUND_ARGMAX_NOTE = "lower-bound argmax is not zero velocity"


@dataclass(frozen=True, slots=True)
class PreviewVelocitySeries:
    """Quality-unfiltered full-STFT-frame preview kept separate from formal values."""

    time_s: np.ndarray[Any, np.dtype[np.float64]]
    frequency_hz: np.ndarray[Any, np.dtype[np.float64]]
    apparent_velocity_m_s: np.ndarray[Any, np.dtype[np.float64]]
    velocity_origins: tuple[str, ...]
    quality_flags: tuple[str, ...]
    uses_refined_frequency: np.ndarray[Any, np.dtype[np.bool_]]
    is_formal_candidate: np.ndarray[Any, np.dtype[np.bool_]]


@dataclass(frozen=True, slots=True)
class VelocityPlotSeries:
    """Formal plot series plus a separate two-endpoint display bridge."""

    pre_event_velocity_m_s: np.ndarray[Any, np.dtype[np.float64]]
    formal_candidate_velocity_m_s: np.ndarray[Any, np.dtype[np.float64]]
    bridge_time_s: np.ndarray[Any, np.dtype[np.float64]]
    bridge_velocity_m_s: np.ndarray[Any, np.dtype[np.float64]]


@dataclass(frozen=True, slots=True)
class ReviewedVelocitySeries:
    """The simple-export plotting series split only at consensus time."""

    simple_export_velocity_m_s: np.ndarray[Any, np.dtype[np.float64]]
    pre_event_zero_velocity_m_s: np.ndarray[Any, np.dtype[np.float64]]
    post_event_velocity_m_s: np.ndarray[Any, np.dtype[np.float64]]


@dataclass(frozen=True, slots=True)
class ThresholdCalibrationResult:
    """Deterministic comparison and selection across the approved thresholds."""

    rows: tuple[dict[str, Any], ...]
    candidate_summaries: tuple[dict[str, Any], ...]
    selected_peak_to_background_db: float
    selected_peak_to_competitor_db: float
    selection_status: str
    baseline_consensus_event_time_s: float | None
    selected_consensus_event_time_s: float | None


def run_production_outputs(
    output_directory: Path,
    records: Mapping[str, SignalRecord],
    *,
    configuration: WorkflowConfiguration,
    source_sha256: str,
) -> list[Path]:
    """Write one complete, non-overwriting dual-profile production run."""
    start_clock = perf_counter()
    _validate_run_inputs(
        output_directory,
        records,
        configuration=configuration,
        source_sha256=source_sha256,
    )
    threshold_calibration = _calibrate_detection_thresholds(
        records,
        configuration=configuration,
    )
    _validate_configured_detection_thresholds(
        configuration.quality.signal_detection,
        calibration=threshold_calibration,
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    profile_names = tuple(
        profile.profile_id.value for profile in configuration.analysis.profiles
    )
    channel_names = tuple(sorted(records))
    comparisons_directory = output_directory / "comparisons"
    comparisons_directory.mkdir()
    simple_exports_directory = output_directory / "simple_exports"
    simple_exports_directory.mkdir()
    expected_paths = _expected_paths(
        output_directory,
        configuration.analysis.profiles,
        channel_names=channel_names,
    )
    generated_paths: list[Path] = []
    profile_manifests: dict[str, dict[str, Any]] = {}
    analyses_by_profile: dict[str, Mapping[str, ChannelAnalysis]] = {}
    previews_by_profile: dict[str, dict[str, PreviewVelocitySeries]] = {}
    profile_consensus_results: dict[str, ProfileConsensusResult] = {}
    log_lines = [
        "DPS Studio formal dual-profile production run",
        f"config_path={configuration.config_path}",
        f"source_path={configuration.input.path}",
        f"source_sha256={source_sha256}",
        "profiles=balanced,high_time_resolution",
    ]

    for profile in configuration.analysis.profiles:
        profile_start = perf_counter()
        profile_name = profile.profile_id.value
        profile_directory = output_directory / profile_name
        profile_directory.mkdir()
        analyses = analyze_profile(
            records,
            profile=profile,
            analysis_start_time_s=(
                configuration.analysis.analysis_start_time_s
            ),
            analysis_end_time_s=configuration.analysis.analysis_end_time_s,
            manual_event_reference_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
            vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
            velocity_correction_config=configuration.velocity_correction,
            detection_config=configuration.quality.signal_detection,
            event_candidate_config=configuration.event_candidate,
            background_guard_window_scale=(
                configuration.quality.background_guard_window_scale
            ),
            minimum_background_bin_count=(
                configuration.quality.minimum_background_bin_count
            ),
            assume_pre_event_zero_for_display=(
                configuration.plot.assume_pre_event_zero_for_display
            ),
        )
        analyses_by_profile[profile_name] = analyses
        previews_by_profile[profile_name] = {}
        profile_consensus = build_profile_consensus(
            {
                name: analysis.stream_event_candidates
                for name, analysis in analyses.items()
            },
            profile_name=profile_name,
            config=configuration.event_consensus,
        )
        profile_consensus_results[profile_name] = profile_consensus
        channel_summaries: dict[str, dict[str, Any]] = {}
        onset_diagnostics: dict[str, dict[str, Any]] = {}
        for channel_name in sorted(analyses):
            channel_directory = profile_directory / channel_name
            channel_directory.mkdir()
            analysis = analyses[channel_name]
            preview = _build_full_range_preview(
                analysis,
                minimum_frequency_hz=profile.minimum_frequency_hz,
                maximum_frequency_hz=profile.maximum_frequency_hz,
                vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
            )
            previews_by_profile[profile_name][channel_name] = preview
            generated_paths.extend(
                _write_channel_outputs(
                    channel_directory,
                    channel_name,
                    analysis,
                    preview=preview,
                    profile=profile,
                    configuration=configuration,
                )
            )
            summary = _channel_summary(
                channel_name,
                analysis,
                profile=profile,
                event_start_time_s=(
                    configuration.analysis.manual_event_reference_time_s
                ),
                source_sha256=source_sha256,
            )
            channel_summaries[channel_name] = summary
            onset_diagnostics[channel_name] = _event_onset_diagnostic(
                analysis,
                event_start_time_s=(
                    configuration.analysis.manual_event_reference_time_s
                ),
            )

        quality_summary_path = profile_directory / "quality_summary.csv"
        pd.DataFrame(channel_summaries.values()).to_csv(
            quality_summary_path,
            index=False,
        )
        generated_paths.append(quality_summary_path)
        event_candidates_path = _save_event_candidate_comparison(
            profile_directory,
            analyses,
            profile=profile,
            manual_event_reference_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
            profile_consensus=profile_consensus,
        )
        generated_paths.append(event_candidates_path)
        profile_runtime_s = perf_counter() - profile_start
        profile_manifest = _profile_manifest(
            profile_directory,
            profile,
            analyses,
            channel_summaries=channel_summaries,
            onset_diagnostics=onset_diagnostics,
            profile_consensus=profile_consensus,
            configuration=configuration,
            source_sha256=source_sha256,
            runtime_s=profile_runtime_s,
        )
        profile_manifest_path = profile_directory / "profile_manifest.json"
        _write_json(profile_manifest_path, profile_manifest)
        generated_paths.append(profile_manifest_path)
        profile_manifests[profile_name] = profile_manifest
        for channel_name, summary in channel_summaries.items():
            log_lines.append(
                f"{profile_name}/{channel_name}: "
                f"measured={summary['measured_frame_count']}, "
                f"no_detectable={summary['no_detectable_beat_frame_count']}, "
                f"ambiguous={summary['ambiguous_peak_frame_count']}, "
                f"detected_event_candidate_time_s="
                f"{summary['detected_event_candidate_time_s']}"
            )
        log_lines.append(f"{profile_name}_runtime_s={profile_runtime_s:.9f}")

    cross_profile_consensus = build_cross_profile_consensus(
        profile_consensus_results,
        config=configuration.event_consensus,
        manual_event_reference_time_s=(
            configuration.analysis.manual_event_reference_time_s
        ),
    )
    for profile in configuration.analysis.profiles:
        profile_name = profile.profile_id.value
        for channel_name in sorted(analyses_by_profile[profile_name]):
            generated_paths.extend(
                _write_consensus_velocity_outputs(
                    output_directory / profile_name / channel_name,
                    channel_name,
                    analyses_by_profile[profile_name][channel_name],
                    preview=previews_by_profile[profile_name][channel_name],
                    profile=profile,
                    cross_profile_consensus=cross_profile_consensus,
                )
            )
            generated_paths.append(
                _write_simple_velocity_csv(
                    simple_exports_directory,
                    profile_name,
                    channel_name,
                    analyses_by_profile[profile_name][channel_name],
                    zero_before_time_s=(
                        cross_profile_consensus.consensus_event_candidate_time_s
                    ),
                )
            )
    generated_paths.append(
        _write_simple_exports_readme(
            simple_exports_directory,
            profile_names=profile_names,
            channel_names=channel_names,
            zero_before_time_s=(
                cross_profile_consensus.consensus_event_candidate_time_s
            ),
            detection_config=configuration.quality.signal_detection,
        )
    )
    generated_paths.append(
        _write_run_readme(
            output_directory,
            profile_names=profile_names,
            channel_names=channel_names,
            detection_config=configuration.quality.signal_detection,
        )
    )
    generated_paths.extend(
        _write_run_level_event_outputs(
            output_directory,
            comparisons_directory,
            analyses_by_profile,
            profile_consensus_results=profile_consensus_results,
            cross_profile_consensus=cross_profile_consensus,
            configuration=configuration,
            threshold_calibration=threshold_calibration,
        )
    )
    manifest_path = output_directory / "run_manifest.json"
    run_manifest = _run_manifest(
        output_directory,
        configuration=configuration,
        source_sha256=source_sha256,
        profile_manifests=profile_manifests,
        profile_consensus_results=profile_consensus_results,
        cross_profile_consensus=cross_profile_consensus,
        threshold_calibration=threshold_calibration,
        expected_paths=expected_paths,
    )
    _write_json(manifest_path, run_manifest)
    generated_paths.append(manifest_path)

    log_lines.extend(
        (
            f"total_runtime_s={perf_counter() - start_clock:.9f}",
            "threshold_calibration_selected_db="
            f"{threshold_calibration.selected_peak_to_background_db:g},"
            f"{threshold_calibration.selected_peak_to_competitor_db:g}",
            "threshold_calibration_status="
            f"{threshold_calibration.selection_status}",
            f"threshold_provenance={THRESHOLD_CALIBRATION_PROVENANCE}",
            f"consensus_event_status={cross_profile_consensus.consensus_event_status.value}",
            "consensus_event_candidate_time_s="
            f"{cross_profile_consensus.consensus_event_candidate_time_s}",
            "interpretation_guards:",
            *(f"- {guard}" for guard in INTERPRETATION_GUARDS),
        )
    )
    log_path = output_directory / "run.log"
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    generated_paths.append(log_path)

    source_hash_after = _sha256(configuration.input.path)
    if source_hash_after != source_sha256:
        raise RuntimeError("Source SHA-256 changed during production analysis.")
    _validate_output_contract(
        output_directory,
        expected_paths,
        profiles=configuration.analysis.profiles,
        channel_names=channel_names,
    )
    if set(generated_paths) != set(expected_paths):
        raise RuntimeError("Returned generated paths differ from the output contract.")
    return generated_paths


def _validate_run_inputs(
    output_directory: Path,
    records: Mapping[str, SignalRecord],
    *,
    configuration: WorkflowConfiguration,
    source_sha256: str,
) -> None:
    if not isinstance(output_directory, Path):
        raise TypeError("output_directory must be pathlib.Path.")
    if output_directory.exists() and any(output_directory.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_directory}")
    if not isinstance(configuration, WorkflowConfiguration):
        raise TypeError("configuration must be a WorkflowConfiguration.")
    actual_profiles = tuple(
        profile.profile_id.value for profile in configuration.analysis.profiles
    )
    if len(actual_profiles) != 2 or len(set(actual_profiles)) != 2:
        raise ValueError("Formal production requires two distinct configured profiles.")
    if tuple(sorted(records)) != ("pdv_channel_1", "pdv_channel_2"):
        raise ValueError("Production requires the two explicit PDV acquisition channels.")
    if not configuration.input.path.is_file():
        raise FileNotFoundError(
            f"Configured source file does not exist: {configuration.input.path}"
        )
    if _sha256(configuration.input.path) != source_sha256:
        raise RuntimeError("source_sha256 does not match the configured input path.")
    for channel_name, record in records.items():
        if not isinstance(record, SignalRecord):
            raise TypeError(f"{channel_name} must map to SignalRecord.")
        if record.source_path != configuration.input.path:
            raise ValueError(
                "Every channel source_path must match configuration.input.path."
            )


def _write_channel_outputs(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    preview: PreviewVelocitySeries,
    profile: AnalysisProfile,
    configuration: WorkflowConfiguration,
) -> list[Path]:
    diagnostic_paths = _write_apparent_velocity_csv(
        output_directory,
        analysis,
        preview=preview,
        event_start_time_s=(
            configuration.analysis.manual_event_reference_time_s
        ),
    )
    return [
        *diagnostic_paths,
        _save_stft_full_band(
            output_directory,
            channel_name,
            analysis,
            profile=profile,
            event_start_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
            relative_db_floor=configuration.plot.relative_db_floor,
        ),
        _save_stft_analysis_band_with_ridge(
            output_directory,
            channel_name,
            analysis,
            profile=profile,
            event_start_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
            display_minimum_frequency_hz=(
                configuration.plot.analysis_display_minimum_frequency_hz
            ),
            display_maximum_frequency_hz=(
                configuration.plot.analysis_display_maximum_frequency_hz
            ),
            relative_db_floor=configuration.plot.relative_db_floor,
        ),
        _save_apparent_velocity_full_time_formal(
            output_directory,
            channel_name,
            analysis,
            profile=profile,
            event_start_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
        ),
        _save_apparent_velocity_event_detail(
            output_directory,
            channel_name,
            analysis,
            profile=profile,
            event_start_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
            event_detail_before_s=configuration.plot.event_detail_before_s,
            event_detail_after_s=configuration.plot.event_detail_after_s,
        ),
        _save_apparent_velocity_state_diagnostics(
            output_directory,
            channel_name,
            analysis,
            preview=preview,
            profile=profile,
            event_start_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
        ),
        _save_signal_detection_diagnostics(
            output_directory,
            channel_name,
            analysis,
            profile=profile,
            manual_event_reference_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
        ),
    ]


def _write_consensus_velocity_outputs(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    preview: PreviewVelocitySeries,
    profile: AnalysisProfile,
    cross_profile_consensus: CrossProfileConsensusResult,
) -> list[Path]:
    consensus_time_s = cross_profile_consensus.consensus_event_candidate_time_s
    reviewed = _build_reviewed_velocity_series(
        analysis,
        consensus_event_time_s=consensus_time_s,
    )
    return [
        _save_apparent_velocity_full_overview(
            output_directory,
            channel_name,
            analysis,
            preview=preview,
            profile=profile,
            consensus_event_time_s=consensus_time_s,
        ),
        _save_apparent_velocity_full_time_reviewed(
            output_directory,
            channel_name,
            analysis,
            reviewed=reviewed,
            profile=profile,
            consensus_event_time_s=consensus_time_s,
        ),
    ]


def _write_apparent_velocity_csv(
    output_directory: Path,
    analysis: ChannelAnalysis,
    *,
    preview: PreviewVelocitySeries,
    event_start_time_s: float | None,
) -> list[Path]:
    refined = analysis.refined_result
    quality = analysis.spectral_quality_result
    continuity = analysis.continuity_result
    detection = analysis.signal_detection_result
    segment_id, segment_eligible, segment_reasons = _segment_frame_metadata(
        analysis
    )
    frame = pd.DataFrame(
        {
            "time_s": refined.time_s,
            "time_relative_to_event_s": _relative_time_s(
                refined.time_s,
                event_start_time_s,
            ),
            "discrete_frequency_hz": refined.discrete_frequency_hz,
            "coarse_peak_frequency_hz": detection.coarse_peak_frequency_hz,
            "provisional_refined_frequency_hz": refined.refined_frequency_hz,
            "refined_frequency_hz": detection.refined_frequency_hz,
            "discrete_apparent_velocity_m_s": analysis.discrete_velocity_m_s,
            "apparent_velocity_m_s": analysis.refined_velocity_m_s,
            "angle_corrected_apparent_velocity_m_s": (
                analysis.angle_corrected_apparent_velocity_m_s
            ),
            "corrected_velocity_m_s": analysis.corrected_velocity_m_s,
            "display_velocity_m_s": analysis.display_velocity_m_s,
            "velocity_origin": analysis.velocity_origins,
            "quality_flag": [flag.value for flag in refined.quality_flags],
            "signal_state": [state.value for state in detection.signal_states],
            "minimum_peak_to_background_threshold_db": (
                detection.detection_config.minimum_peak_to_background_db
            ),
            "minimum_peak_to_competitor_threshold_db": (
                detection.detection_config.minimum_peak_to_competitor_db
            ),
            "threshold_provenance": THRESHOLD_CALIBRATION_PROVENANCE,
            "measured_semantics": [
                (
                    "spectrally qualified under configured detection rules; "
                    "physical branch identity is not confirmed"
                )
                for _ in detection.signal_states
            ],
            "physical_branch_review_status": [
                PhysicalBranchReviewStatus.UNREVIEWED.value
                for _ in detection.signal_states
            ],
            "event_segment_id": segment_id,
            "event_segment_candidate_eligible": segment_eligible,
            "event_segment_rejection_reasons": segment_reasons,
            "refinement_status": [
                status.value for status in refined.refinement_statuses
            ],
            "peak_magnitude": refined.peak_magnitude,
            "peak_amplitude": detection.peak_amplitude,
            "peak_bin_index": detection.peak_bin_index,
            "peak_is_at_band_boundary": detection.peak_is_at_band_boundary,
            "frequency_bin_offset": refined.frequency_bin_offset,
            "peak_to_background_db": detection.peak_to_background_db,
            "peak_to_competitor_db": detection.peak_to_competitor_db,
            "cycles_in_window": detection.cycles_in_window,
            "spectral_assessment_status": [
                status.value for status in quality.assessment_statuses
            ],
            "background_median_magnitude": quality.background_median_magnitude,
            "background_level": detection.background_level,
            "strongest_competitor_magnitude": (
                quality.strongest_competitor_magnitude
            ),
            "strongest_competitor_level": (
                detection.strongest_competitor_level
            ),
            "background_bin_count": quality.background_bin_count,
            "continuity_status": [
                status.value for status in continuity.continuity_statuses
            ],
            "frequency_step_hz": continuity.frequency_step_hz,
            "frequency_slope_hz_s": continuity.frequency_slope_hz_s,
            "preview_frequency_hz": preview.frequency_hz,
            "preview_apparent_velocity_m_s": preview.apparent_velocity_m_s,
            "preview_velocity_origin": preview.velocity_origins,
            "preview_quality_flag": preview.quality_flags,
            "preview_signal_state": [
                state.value for state in detection.signal_states
            ],
            "preview_uses_refined_frequency": preview.uses_refined_frequency,
            "preview_is_formal_candidate": preview.is_formal_candidate,
        }
    )
    path = output_directory / DETAILED_DIAGNOSTIC_FILENAMES[0]
    frame.to_csv(path, index=False, float_format="%.18e")
    return [path]


def _simple_export_filename(profile_name: str, channel_name: str) -> str:
    return f"{profile_name}__{channel_name}__velocity_time.csv"


def _write_simple_velocity_csv(
    output_directory: Path,
    profile_name: str,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    zero_before_time_s: float | None,
) -> Path:
    """Write the two-column Origin/Excel plotting series."""
    time_s = analysis.refined_result.time_s
    if time_s.ndim != 1 or not np.all(np.diff(time_s) > 0.0):
        raise RuntimeError("Simple-export time_s must be one-dimensional and increasing.")
    if time_s.shape != analysis.refined_velocity_m_s.shape:
        raise RuntimeError("Simple-export time and formal velocity shapes differ.")
    velocity_m_s = _simple_export_velocity_m_s(
        analysis,
        zero_before_time_s=zero_before_time_s,
    )
    path = output_directory / _simple_export_filename(profile_name, channel_name)
    pd.DataFrame(
        {
            "time_s": time_s,
            "corrected_velocity_m_s": velocity_m_s,
        }
    ).to_csv(path, index=False, float_format="%.18e")
    return path


def _simple_export_velocity_m_s(
    analysis: ChannelAnalysis,
    *,
    zero_before_time_s: float | None,
) -> np.ndarray[Any, np.dtype[np.float64]]:
    """Copy formal values and define every pre-consensus plotting value as zero."""
    velocity_m_s = analysis.corrected_velocity_m_s.copy()
    if zero_before_time_s is None:
        return velocity_m_s
    if not math.isfinite(zero_before_time_s):
        raise ValueError("zero_before_time_s must be finite or None.")
    zero_mask = analysis.refined_result.time_s < zero_before_time_s
    velocity_m_s[zero_mask] = 0.0
    return velocity_m_s


def _write_simple_exports_readme(
    output_directory: Path,
    *,
    profile_names: Sequence[str],
    channel_names: Sequence[str],
    zero_before_time_s: float | None,
    detection_config: SignalDetectionConfig,
) -> Path:
    path = output_directory / SIMPLE_EXPORT_README_FILENAME
    file_lines = [
        f"- {_simple_export_filename(profile_name, channel_name)}"
        for profile_name in profile_names
        for channel_name in channel_names
    ]
    consensus_availability = (
        "This run uses cross-profile consensus time "
        f"{zero_before_time_s:.18e} s."
        if zero_before_time_s is not None
        else "For this run, cross-profile consensus is unavailable; no manual "
        "reference is substituted and the formal quality-gated array is copied "
        "unchanged."
    )
    path.write_text(
        "\n".join(
            (
                "DPS Studio simple corrected-velocity exports",
                "",
                "This directory contains one independent file for every actual "
                "configured profile/channel stream:",
                *file_lines,
                "",
                "Filename fields identify the configured analysis profile and the "
                "independent PDV acquisition channel.",
                "Columns: time_s is absolute STFT frame-center time in seconds; "
                "corrected_velocity_m_s is the final angle- and window-corrected "
                "velocity in m/s.",
                "When cross-profile consensus is available, every frame with "
                "time_s before it is written as exactly 0 m/s, regardless of "
                "its formal diagnostic signal state.",
                consensus_availability,
                "The complete pre-event zero platform is a plotting convention for "
                "direct use in Origin or Excel; it is not a measured velocity.",
                "At and after the consensus time, formal quality-gated corrected "
                "velocity is copied exactly and invalid frames remain NaN.",
                "All original STFT frames and times are retained. No row is removed "
                "and no value is interpolated, smoothed, bridged, or resampled.",
                "The corrected values use the configured observation-angle and "
                "window correction; apparent velocity remains available separately "
                "in the detailed diagnostics.",
                "Configured development-calibrated thresholds: "
                f"peak/background >= "
                f"{detection_config.minimum_peak_to_background_db:g} dB and "
                "peak/competitor >= "
                f"{detection_config.minimum_peak_to_competitor_db:g} dB.",
                f"Threshold provenance: {THRESHOLD_CALIBRATION_PROVENANCE}.",
                "The detailed apparent_velocity_diagnostics.csv files preserve "
                "apparent, angle-corrected apparent, corrected, and display "
                "velocities separately and are never pre-event zero-filled.",
                "The physical identities of spectral branches near the record tail "
                "remain unconfirmed.",
                "Do not directly average the two raw voltage channels or the four "
                "velocity curves.",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def _write_run_readme(
    output_directory: Path,
    *,
    profile_names: Sequence[str],
    channel_names: Sequence[str],
    detection_config: SignalDetectionConfig,
) -> Path:
    path = output_directory / "README.txt"
    path.write_text(
        "\n".join(
            (
                "DPS Studio formal production run",
                "",
                f"Profiles: {', '.join(profile_names)}",
                f"Independent channels: {', '.join(channel_names)}",
                "simple_exports/ contains strict two-column Origin-ready files.",
                "Every pre-consensus simple-export frame is written as plotting "
                "zero; post-consensus formal NaN gaps remain NaN.",
                "Each profile/channel apparent_velocity_diagnostics.csv is the "
                "complete detailed diagnostic table.",
                "Detailed formal apparent_velocity_m_s is never pre-event "
                "zero-filled.",
                "Configured detection thresholds are "
                f"{detection_config.minimum_peak_to_background_db:g} dB "
                "peak/background and "
                f"{detection_config.minimum_peak_to_competitor_db:g} dB "
                "peak/competitor.",
                f"Threshold provenance: {THRESHOLD_CALIBRATION_PROVENANCE}.",
                "comparisons/threshold_calibration.csv records the four approved "
                "candidate comparisons and deterministic selection.",
                "No duplicate apparent_velocity.csv compatibility alias is generated.",
                "apparent_velocity_full_overview.png is the primary full-range "
                "preview/formal comparison.",
                "apparent_velocity_full_time_reviewed.png is display-only and never "
                "changes or exports formal velocity values.",
                "comparisons/ contains cross-stream validation and event diagnostics.",
                "event_consensus.json records event-candidate consensus metadata.",
                "Detailed apparent velocities remain unsigned and unmodified; "
                "simple exports use the configured formal corrected velocity. "
                "Neither represents profile/channel fusion or physical branch "
                "selection.",
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def _build_full_range_preview(
    analysis: ChannelAnalysis,
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    vacuum_wavelength_m: float,
) -> PreviewVelocitySeries:
    """Build a full-range peak preview without changing the formal quality gate."""
    preview_ridge = extract_peak_ridge(
        analysis.stft_result,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
    )
    detection = analysis.signal_detection_result
    uses_refined = np.zeros(preview_ridge.time_s.size, dtype=np.bool_)
    frequency_hz = preview_ridge.frequency_hz.copy()
    selected_ridge = RidgeResult(
        time_s=preview_ridge.time_s,
        frequency_hz=frequency_hz,
        peak_magnitude=preview_ridge.peak_magnitude,
        quality_flags=preview_ridge.quality_flags,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
        event_start_time_s=None,
        analysis_end_time_s=None,
        source_path=preview_ridge.source_path,
    )
    preview_velocity = convert_ridge_to_apparent_velocity(
        selected_ridge,
        vacuum_wavelength_m=vacuum_wavelength_m,
    ).apparent_velocity_m_s
    is_formal_candidate = np.fromiter(
        (state is SignalState.MEASURED for state in detection.signal_states),
        dtype=np.bool_,
        count=preview_ridge.time_s.size,
    )
    origins = tuple(
        "quality_unfiltered_discrete_argmax_not_measurement"
        for _ in detection.signal_states
    )
    preview_quality = tuple(
        _preview_quality_flag(state, is_formal=bool(is_formal))
        for state, is_formal in zip(
            detection.signal_states,
            is_formal_candidate,
        )
    )
    return PreviewVelocitySeries(
        time_s=preview_ridge.time_s,
        frequency_hz=frequency_hz,
        apparent_velocity_m_s=preview_velocity,
        velocity_origins=origins,
        quality_flags=preview_quality,
        uses_refined_frequency=uses_refined,
        is_formal_candidate=is_formal_candidate,
    )


def _preview_quality_flag(
    signal_state: SignalState,
    *,
    is_formal: bool,
) -> str:
    if is_formal:
        return "formal_measured_overlap"
    if signal_state is SignalState.OUTSIDE_ANALYSIS_WINDOW:
        return "preview_only_outside_formal_window"
    return f"preview_only_{signal_state.value}"


def _save_stft_full_band(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    profile: AnalysisProfile,
    event_start_time_s: float | None,
    relative_db_floor: float,
) -> Path:
    path = output_directory / "stft_full_band.png"
    stft = analysis.stft_result
    display_db = _relative_stft_magnitude_db(
        np.abs(stft.spectrum),
        floor_db=relative_db_floor,
    )
    figure, axis = plt.subplots(figsize=(11.0, 6.5), constrained_layout=True)
    mesh = axis.pcolormesh(
        _plot_time_us(stft.time_s, event_start_time_s),
        stft.frequency_hz * 1.0e-9,
        display_db,
        shading="auto",
        cmap="viridis",
        vmin=relative_db_floor,
        vmax=0.0,
        rasterized=True,
    )
    figure.colorbar(mesh, ax=axis, label="Relative STFT magnitude (dB)")
    axis.set_ylim(stft.frequency_hz[0] * 1.0e-9, stft.frequency_hz[-1] * 1.0e-9)
    axis.set_xlabel(_time_axis_label(event_start_time_s))
    axis.set_ylabel("Frequency (GHz)")
    axis.set_title(f"{profile.display_name} / {channel_name}: full one-sided STFT")
    _save_figure(figure, path)
    return path


def _save_stft_analysis_band_with_ridge(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    profile: AnalysisProfile,
    event_start_time_s: float | None,
    display_minimum_frequency_hz: float,
    display_maximum_frequency_hz: float,
    relative_db_floor: float,
) -> Path:
    path = output_directory / "stft_analysis_band_with_ridge.png"
    stft = analysis.stft_result
    frequency_mask = (stft.frequency_hz >= display_minimum_frequency_hz) & (
        stft.frequency_hz <= display_maximum_frequency_hz
    )
    display_db = _relative_stft_magnitude_db(
        np.abs(stft.spectrum[frequency_mask, :]),
        floor_db=relative_db_floor,
    )
    relative_time_us = _plot_time_us(stft.time_s, event_start_time_s)
    figure, axis = plt.subplots(figsize=(11.0, 6.5), constrained_layout=True)
    mesh = axis.pcolormesh(
        relative_time_us,
        stft.frequency_hz[frequency_mask] * 1.0e-9,
        display_db,
        shading="auto",
        cmap="viridis",
        vmin=relative_db_floor,
        vmax=0.0,
        rasterized=True,
    )
    axis.plot(
        relative_time_us,
        analysis.signal_detection_result.refined_frequency_hz * 1.0e-9,
        color="white",
        linewidth=0.8,
        label="quality-gated measured ridge",
    )
    if event_start_time_s is not None:
        axis.axvline(
            0.0,
            color="#ff7f0e",
            linewidth=0.9,
            label="manual event reference",
        )
    axis.axhline(
        profile.minimum_frequency_hz * 1.0e-9,
        color="#ffcc00",
        linewidth=0.8,
        linestyle="--",
        label="formal search lower bound",
    )
    figure.colorbar(mesh, ax=axis, label="Relative STFT magnitude (dB)")
    axis.set_ylim(
        display_minimum_frequency_hz * 1.0e-9,
        display_maximum_frequency_hz * 1.0e-9,
    )
    axis.set_xlabel(_time_axis_label(event_start_time_s))
    axis.set_ylabel("Frequency (GHz)")
    axis.set_title(
        f"{profile.display_name} / {channel_name}: 0–2 GHz display; "
        "0.05–2 GHz ridge search"
    )
    axis.legend(loc="upper right")
    _save_figure(figure, path)
    return path


def _save_apparent_velocity_full_overview(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    preview: PreviewVelocitySeries,
    profile: AnalysisProfile,
    consensus_event_time_s: float | None,
) -> Path:
    """Plot the complete fixed-band preview over the unchanged formal series."""
    path = output_directory / "apparent_velocity_full_overview.png"
    relative_time_us = _plot_time_us(preview.time_s, consensus_event_time_s)
    figure, axis = plt.subplots(figsize=(11.0, 6.5), constrained_layout=True)
    axis.plot(
        relative_time_us,
        preview.apparent_velocity_m_s,
        color="#d62728",
        linewidth=0.65,
        alpha=0.86,
        label=QUALITY_UNFILTERED_PREVIEW_LABEL,
    )
    axis.plot(
        relative_time_us,
        analysis.refined_velocity_m_s,
        color="#1f77b4",
        linewidth=1.0,
        label="quality-gated formal apparent velocity",
    )
    axis.text(
        0.015,
        0.975,
        "Red preview is diagnostic only.\n"
        "Lower-bound argmax is not zero velocity.",
        transform=axis.transAxes,
        va="top",
        ha="left",
        fontsize=9.0,
        bbox={
            "boxstyle": "round,pad=0.3",
            "facecolor": "white",
            "edgecolor": "#bdbdbd",
            "alpha": 0.85,
        },
    )
    axis.set_xlim(relative_time_us[0], relative_time_us[-1])
    axis.set_xlabel(_consensus_time_axis_label(consensus_event_time_s))
    axis.set_ylabel("Unsigned apparent velocity (m/s)")
    axis.set_title(
        f"{profile.display_name} / {channel_name}: full-range overview"
    )
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    _save_figure(figure, path)
    return path


def _save_apparent_velocity_full_time_reviewed(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    reviewed: ReviewedVelocitySeries,
    profile: AnalysisProfile,
    consensus_event_time_s: float | None,
) -> Path:
    """Plot the exact simple-export series without interpolation or bridging."""
    path = output_directory / "apparent_velocity_full_time_reviewed.png"
    relative_time_us = _plot_time_us(
        analysis.refined_result.time_s,
        consensus_event_time_s,
    )
    figure, axis = plt.subplots(figsize=(11.0, 6.5), constrained_layout=True)
    axis.plot(
        relative_time_us,
        np.where(
            np.isfinite(reviewed.pre_event_zero_velocity_m_s),
            reviewed.simple_export_velocity_m_s,
            np.nan,
        ),
        color="#7f7f7f",
        linestyle="--",
        linewidth=1.0,
        label="pre-event baseline defined as zero for plotting",
    )
    axis.plot(
        relative_time_us,
        np.where(
            np.isfinite(reviewed.post_event_velocity_m_s),
            reviewed.simple_export_velocity_m_s,
            np.nan,
        ),
        color="#1f77b4",
        linewidth=1.1,
        label="quality-gated corrected velocity after event",
    )
    axis.set_xlim(relative_time_us[0], relative_time_us[-1])
    axis.set_xlabel(_consensus_time_axis_label(consensus_event_time_s))
    axis.set_ylabel("Corrected velocity (m/s)")
    axis.set_title(
        f"{profile.display_name} / {channel_name}: full-time reviewed display"
    )
    axis.text(
        0.01,
        0.02,
        "Pre-event zero is a plotting convention based on the consensus event time.",
        transform=axis.transAxes,
        fontsize=8.5,
        va="bottom",
    )
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    _save_figure(figure, path)
    return path


def _save_apparent_velocity_full_time_formal(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    profile: AnalysisProfile,
    event_start_time_s: float | None,
) -> Path:
    path = output_directory / "apparent_velocity_full_time_formal.png"
    relative_time_us = _plot_time_us(
        analysis.refined_result.time_s,
        event_start_time_s,
    )
    series = _velocity_plot_series(analysis)
    figure, axis = plt.subplots(figsize=(11.0, 6.5), constrained_layout=True)
    axis.plot(
        relative_time_us,
        series.pre_event_velocity_m_s,
        color="#7f7f7f",
        linestyle="--",
        linewidth=1.0,
        label=(
            "assumed pre-event zero (display only)"
            if np.isfinite(series.pre_event_velocity_m_s).any()
            else "_nolegend_"
        ),
    )
    axis.plot(
        _plot_time_us(series.bridge_time_s, event_start_time_s),
        series.bridge_velocity_m_s,
        color="#7f7f7f",
        linewidth=1.0,
        label=(
            "display-only bridge (not measured; no intermediate frames)"
            if series.bridge_time_s.size
            else "_nolegend_"
        ),
    )
    axis.plot(
        relative_time_us,
        series.formal_candidate_velocity_m_s,
        color="#1f77b4",
        linewidth=0.8,
        label="quality-gated formal apparent velocity",
    )
    _add_event_start_reference(axis, available=event_start_time_s is not None)
    axis.set_xlabel(_time_axis_label(event_start_time_s))
    axis.set_ylabel("Unsigned apparent velocity (m/s)")
    axis.set_title(f"{profile.display_name} / {channel_name}: full STFT-frame time")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    _save_figure(figure, path)
    return path


def _save_apparent_velocity_event_detail(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    profile: AnalysisProfile,
    event_start_time_s: float | None,
    event_detail_before_s: float,
    event_detail_after_s: float,
) -> Path:
    path = output_directory / "apparent_velocity_event_detail.png"
    relative_time_us = _plot_time_us(
        analysis.refined_result.time_s,
        event_start_time_s,
    )
    series = _velocity_plot_series(analysis)
    figure, axis = plt.subplots(figsize=(11.0, 6.5), constrained_layout=True)
    axis.plot(
        relative_time_us,
        series.pre_event_velocity_m_s,
        color="#7f7f7f",
        linestyle="--",
        marker=".",
        markersize=3.0,
        linewidth=0.8,
        label=(
            "assumed pre-event zero (display only)"
            if np.isfinite(series.pre_event_velocity_m_s).any()
            else "_nolegend_"
        ),
    )
    axis.plot(
        _plot_time_us(series.bridge_time_s, event_start_time_s),
        series.bridge_velocity_m_s,
        color="#7f7f7f",
        linewidth=1.0,
        label=(
            "display-only bridge (not measured; no intermediate frames)"
            if series.bridge_time_s.size
            else "_nolegend_"
        ),
    )
    axis.plot(
        relative_time_us,
        series.formal_candidate_velocity_m_s,
        color="#1f77b4",
        marker=".",
        markersize=3.0,
        linewidth=0.8,
        label="quality-gated formal frames (no time interpolation)",
    )
    _add_event_start_reference(axis, available=event_start_time_s is not None)
    axis.set_xlim(-event_detail_before_s * 1.0e6, event_detail_after_s * 1.0e6)
    axis.set_xlabel(_time_axis_label(event_start_time_s))
    axis.set_ylabel("Unsigned apparent velocity (m/s)")
    axis.set_title(f"{profile.display_name} / {channel_name}: event detail")
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    _save_figure(figure, path)
    return path


def _save_apparent_velocity_state_diagnostics(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    preview: PreviewVelocitySeries,
    profile: AnalysisProfile,
    event_start_time_s: float | None,
) -> Path:
    path = output_directory / "apparent_velocity_state_diagnostics.png"
    relative_time_us = _plot_time_us(preview.time_s, event_start_time_s)
    series = _velocity_plot_series(analysis)
    preview_visible = np.where(
        np.isfinite(series.pre_event_velocity_m_s),
        np.nan,
        preview.apparent_velocity_m_s,
    )
    states = analysis.signal_detection_result.signal_states
    measured_mask = np.fromiter(
        (state is SignalState.MEASURED for state in states),
        dtype=np.bool_,
        count=len(states),
    )
    connected_preview = np.where(measured_mask, preview_visible, np.nan)
    figure, axis = plt.subplots(figsize=(11.0, 6.5), constrained_layout=True)
    axis.plot(
        relative_time_us,
        series.pre_event_velocity_m_s,
        color="#7f7f7f",
        linestyle="--",
        linewidth=1.0,
        label=(
            "assumed pre-event zero (display only)"
            if np.isfinite(series.pre_event_velocity_m_s).any()
            else "_nolegend_"
        ),
    )
    axis.plot(
        relative_time_us,
        connected_preview,
        color="#d62728",
        linewidth=0.8,
        alpha=0.82,
        label=QUALITY_UNFILTERED_PREVIEW_LABEL,
    )
    state_layers = (
        (SignalState.PEAK_AT_BAND_BOUNDARY, "s", "#ffbf00", "boundary argmax diagnostic"),
        (SignalState.NO_DETECTABLE_BEAT, "x", "#7f7f7f", "no detectable beat argmax"),
        (SignalState.AMBIGUOUS_PEAK, "^", "#9467bd", "ambiguous peak argmax"),
        (SignalState.REFINEMENT_FAILED, "D", "#8c564b", "refinement-failed argmax"),
        (SignalState.INSUFFICIENT_CYCLES, "v", "#17becf", "insufficient-cycle argmax"),
        (SignalState.UNSTABLE_DETECTION, "+", "#ff7f0e", "unstable-detection argmax"),
        (SignalState.OUTSIDE_ANALYSIS_WINDOW, ".", "#bdbdbd", "outside-window argmax"),
    )
    for state, marker, color, label in state_layers:
        mask = np.fromiter(
            (item is state for item in states),
            dtype=np.bool_,
            count=len(states),
        )
        mask &= np.isfinite(preview_visible)
        if np.any(mask):
            axis.scatter(
                relative_time_us[mask],
                preview_visible[mask],
                marker=marker,
                s=16.0,
                color=color,
                alpha=0.72,
                label=label,
                zorder=2,
            )
    axis.plot(
        relative_time_us,
        series.formal_candidate_velocity_m_s,
        color="#1f77b4",
        linewidth=1.0,
        label="quality-gated formal apparent velocity",
    )
    axis.plot(
        _plot_time_us(series.bridge_time_s, event_start_time_s),
        series.bridge_velocity_m_s,
        color="#7f7f7f",
        linewidth=1.0,
        label=(
            "display-only bridge (not measured; no intermediate frames)"
            if series.bridge_time_s.size
            else "_nolegend_"
        ),
    )
    _add_event_start_reference(axis, available=event_start_time_s is not None)
    band_indices = np.flatnonzero(
        analysis.stft_result.frequency_hz >= profile.minimum_frequency_hz
    )
    lower_grid_frequency_hz = float(
        analysis.stft_result.frequency_hz[int(band_indices[0])]
    )
    lower_grid_velocity_m_s = (
        analysis.discrete_velocity_result.vacuum_wavelength_m
        * lower_grid_frequency_hz
        / 2.0
    )
    axis.axhline(
        lower_grid_velocity_m_s,
        color="#ffbf00",
        linestyle=":",
        linewidth=0.8,
        label=(
            f"search lower-grid argmax diagnostic "
            f"({lower_grid_velocity_m_s:.6f} m/s; not zero)"
        ),
    )
    axis.set_xlabel(_time_axis_label(event_start_time_s))
    axis.set_ylabel("Unsigned apparent velocity (m/s)")
    axis.set_title(
        f"{profile.display_name} / {channel_name}: "
        f"state-layered development diagnostic\n{LOWER_BOUND_ARGMAX_NOTE}"
    )
    axis.grid(alpha=0.25)
    axis.legend(loc="best")
    _save_figure(figure, path)
    return path


def _build_reviewed_velocity_series(
    analysis: ChannelAnalysis,
    *,
    consensus_event_time_s: float | None,
) -> ReviewedVelocitySeries:
    """Split the exact simple-export series without changing formal velocity."""
    time_s = analysis.refined_result.time_s
    simple_export = _simple_export_velocity_m_s(
        analysis,
        zero_before_time_s=consensus_event_time_s,
    )
    pre_event_zero = np.full(simple_export.shape, np.nan, dtype=np.float64)
    post_event = np.full(simple_export.shape, np.nan, dtype=np.float64)
    if consensus_event_time_s is None:
        post_event[:] = simple_export
    else:
        pre_mask = time_s < consensus_event_time_s
        pre_event_zero[pre_mask] = simple_export[pre_mask]
        post_event[~pre_mask] = simple_export[~pre_mask]

    return ReviewedVelocitySeries(
        simple_export_velocity_m_s=simple_export,
        pre_event_zero_velocity_m_s=pre_event_zero,
        post_event_velocity_m_s=post_event,
    )


def _velocity_plot_series(
    analysis: ChannelAnalysis,
) -> VelocityPlotSeries:
    states = analysis.signal_detection_result.signal_states
    pre_mask = np.fromiter(
        (
            origin == "assumed_pre_event_zero_display_only"
            for origin in analysis.velocity_origins
        ),
        dtype=np.bool_,
        count=len(states),
    )
    measured_mask = np.fromiter(
        (state is SignalState.MEASURED for state in states),
        dtype=np.bool_,
        count=len(states),
    )
    pre_event = np.where(pre_mask, 0.0, np.nan)
    formal_candidate = np.where(
        measured_mask,
        analysis.refined_velocity_m_s,
        np.nan,
    )
    pre_indices = np.flatnonzero(pre_mask)
    formal_indices = np.flatnonzero(measured_mask)
    if pre_indices.size and formal_indices.size:
        last_pre_index = int(pre_indices[-1])
        first_formal_index = int(formal_indices[0])
        bridge_time_s = np.asarray(
            [
                analysis.refined_result.time_s[last_pre_index],
                analysis.refined_result.time_s[first_formal_index],
            ],
            dtype=np.float64,
        )
        bridge_velocity_m_s = np.asarray(
            [0.0, analysis.refined_velocity_m_s[first_formal_index]],
            dtype=np.float64,
        )
    else:
        bridge_time_s = np.asarray([], dtype=np.float64)
        bridge_velocity_m_s = np.asarray([], dtype=np.float64)
    return VelocityPlotSeries(
        pre_event_velocity_m_s=pre_event,
        formal_candidate_velocity_m_s=formal_candidate,
        bridge_time_s=bridge_time_s,
        bridge_velocity_m_s=bridge_velocity_m_s,
    )


def _add_event_start_reference(axis: Any, *, available: bool) -> None:
    if not available:
        return
    axis.axvline(
        0.0,
        color="#c7a600",
        linestyle=":",
        linewidth=0.55,
        alpha=0.55,
        zorder=0,
        label="manual event reference",
    )


def _save_signal_detection_diagnostics(
    output_directory: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    profile: AnalysisProfile,
    manual_event_reference_time_s: float | None,
) -> Path:
    """Plot formal states and the three configured numerical quality gates."""
    path = output_directory / "signal_detection_diagnostics.png"
    detection = analysis.signal_detection_result
    time_us = _plot_time_us(
        detection.time_s,
        manual_event_reference_time_s,
    )
    state_order = tuple(SignalState)
    state_codes = np.asarray(
        [state_order.index(state) for state in detection.signal_states],
        dtype=np.float64,
    )
    figure, axes = plt.subplots(
        4,
        1,
        figsize=(12.0, 10.0),
        sharex=True,
        constrained_layout=True,
    )
    axes[0].scatter(time_us, state_codes, s=8.0, color="#1f77b4")
    axes[0].set_yticks(
        np.arange(len(state_order)),
        labels=[state.value for state in state_order],
        fontsize=7,
    )
    axes[0].set_ylabel("Signal state")
    axes[1].plot(time_us, detection.peak_to_background_db, linewidth=0.75)
    axes[1].axhline(
        detection.detection_config.minimum_peak_to_background_db,
        color="#d62728",
        linestyle="--",
        label="configured threshold",
    )
    axes[1].set_ylabel("Peak/background (dB)")
    axes[1].legend(loc="best")
    axes[2].plot(time_us, detection.peak_to_competitor_db, linewidth=0.75)
    axes[2].axhline(
        detection.detection_config.minimum_peak_to_competitor_db,
        color="#d62728",
        linestyle="--",
        label="configured threshold",
    )
    axes[2].set_ylabel("Peak/competitor (dB)")
    axes[2].legend(loc="best")
    axes[3].plot(time_us, detection.cycles_in_window, linewidth=0.75)
    axes[3].axhline(
        detection.detection_config.minimum_cycles_in_window,
        color="#d62728",
        linestyle="--",
        label="configured cycle rule",
    )
    axes[3].set_ylabel("Cycles/window")
    axes[3].set_xlabel(_time_axis_label(manual_event_reference_time_s))
    axes[3].legend(loc="best")
    for axis in axes:
        axis.grid(alpha=0.2)
    figure.suptitle(
        f"{profile.display_name} / {channel_name}: spectral detection evidence"
    )
    _save_figure(figure, path)
    return path


def _save_event_candidate_comparison(
    profile_directory: Path,
    analyses: Mapping[str, ChannelAnalysis],
    *,
    profile: AnalysisProfile,
    manual_event_reference_time_s: float | None,
    profile_consensus: ProfileConsensusResult,
) -> Path:
    """Plot every stream segment and the selected cross-channel consensus."""
    path = profile_directory / "detected_event_candidates.png"
    names = sorted(analyses)
    supporting_ids = {
        item.segment_id for item in profile_consensus.supporting_channel_segments
    }
    figure, axis = plt.subplots(figsize=(11.0, 5.5), constrained_layout=True)
    for row, name in enumerate(names):
        assessments = analyses[name].stream_event_candidates.segment_assessments
        for assessment in assessments:
            segment = assessment.segment
            start = _plot_scalar_time_us(
                segment.start_time_s,
                manual_event_reference_time_s,
            )
            end = _plot_scalar_time_us(
                segment.end_time_s,
                manual_event_reference_time_s,
            )
            selected = segment.segment_id in supporting_ids
            color = (
                "#2ca02c"
                if selected
                else "#1f77b4"
                if assessment.candidate_eligible
                else "#9e9e9e"
            )
            axis.plot(
                (start, end),
                (row, row),
                color=color,
                linewidth=4.0 if selected else 2.0,
                solid_capstyle="butt",
            )
            axis.scatter(
                start,
                row,
                marker="o" if assessment.candidate_eligible else "x",
                s=42.0 if selected else 25.0,
                color=color,
                zorder=3,
            )
    candidate = profile_consensus.profile_consensus_candidate_time_s
    if candidate is not None:
        axis.axvline(
            _plot_scalar_time_us(candidate, manual_event_reference_time_s),
            color="#111111",
            linestyle="--",
            linewidth=1.2,
            label="dual-channel profile consensus",
        )
    if manual_event_reference_time_s is not None:
        axis.axvline(
            0.0,
            color="#c7a600",
            linestyle=":",
            linewidth=0.9,
            label="manual reference (diagnostic only)",
        )
    axis.set_yticks(np.arange(len(names)), labels=names)
    axis.set_xlabel(_time_axis_label(manual_event_reference_time_s))
    axis.set_ylabel("Channel")
    axis.set_title(
        f"{profile.display_name}: all MEASURED segments and channel matching\n"
        f"status={profile_consensus.profile_consensus_status.value}"
    )
    axis.grid(axis="x", alpha=0.25)
    axis.plot(
        [],
        [],
        color="#1f77b4",
        linewidth=3.0,
        label="event-level eligible segment",
    )
    axis.plot(
        [],
        [],
        color="#9e9e9e",
        linewidth=3.0,
        label="enumerated but event-level rejected",
    )
    axis.legend(loc="best")
    _save_figure(figure, path)
    return path


def _calibrate_detection_thresholds(
    records: Mapping[str, SignalRecord],
    *,
    configuration: WorkflowConfiguration,
) -> ThresholdCalibrationResult:
    """Compare exactly the approved threshold pairs against a 10/3 baseline."""
    baseline_pair = THRESHOLD_CALIBRATION_CANDIDATES_DB[0]
    baseline_detection_config = _threshold_candidate_detection_config(
        configuration.quality.signal_detection,
        peak_to_background_db=baseline_pair[0],
        peak_to_competitor_db=baseline_pair[1],
    )
    baseline_analyses = _analyze_threshold_candidate(
        records,
        configuration=configuration,
        detection_config=baseline_detection_config,
    )
    baseline_profiles, baseline_cross = _threshold_candidate_consensus(
        baseline_analyses,
        configuration=configuration,
    )

    rows: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for peak_to_background_db, peak_to_competitor_db in (
        THRESHOLD_CALIBRATION_CANDIDATES_DB
    ):
        if (peak_to_background_db, peak_to_competitor_db) == baseline_pair:
            candidate_analyses = baseline_analyses
            candidate_profiles = baseline_profiles
            candidate_cross = baseline_cross
        else:
            detection_config = _threshold_candidate_detection_config(
                configuration.quality.signal_detection,
                peak_to_background_db=peak_to_background_db,
                peak_to_competitor_db=peak_to_competitor_db,
            )
            candidate_analyses = _analyze_threshold_candidate(
                records,
                configuration=configuration,
                detection_config=detection_config,
            )
            candidate_profiles, candidate_cross = (
                _threshold_candidate_consensus(
                    candidate_analyses,
                    configuration=configuration,
                )
            )
        candidate_rows = _threshold_candidate_rows(
            baseline_analyses,
            candidate_analyses,
            baseline_profile_consensus=baseline_profiles,
            candidate_profile_consensus=candidate_profiles,
            baseline_cross_profile_consensus=baseline_cross,
            candidate_cross_profile_consensus=candidate_cross,
            peak_to_background_db=peak_to_background_db,
            peak_to_competitor_db=peak_to_competitor_db,
        )
        summary = _threshold_candidate_summary(
            candidate_rows,
            baseline_cross_profile_consensus=baseline_cross,
            candidate_cross_profile_consensus=candidate_cross,
            candidate_profile_consensus=candidate_profiles,
            consensus_config=configuration.event_consensus,
            minimum_consecutive_frames=(
                configuration.quality.signal_detection.minimum_consecutive_frames
            ),
            peak_to_background_db=peak_to_background_db,
            peak_to_competitor_db=peak_to_competitor_db,
        )
        for row in candidate_rows:
            row["candidate_qualifies"] = summary["qualifies"]
            row["candidate_rejection_reasons"] = "|".join(
                summary["rejection_reasons"]
            )
        rows.extend(candidate_rows)
        summaries.append(summary)

    selected_background, selected_competitor, selection_status = (
        _select_threshold_candidate(summaries)
    )
    selected_rows = tuple(
        {
            **row,
            "selected": (
                row["peak_to_background_threshold_db"]
                == selected_background
                and row["peak_to_competitor_threshold_db"]
                == selected_competitor
            ),
        }
        for row in rows
    )
    selected_summaries = tuple(
        {
            **summary,
            "selected": (
                summary["peak_to_background_threshold_db"]
                == selected_background
                and summary["peak_to_competitor_threshold_db"]
                == selected_competitor
            ),
        }
        for summary in summaries
    )
    selected_summary = next(
        summary for summary in selected_summaries if summary["selected"]
    )
    return ThresholdCalibrationResult(
        rows=selected_rows,
        candidate_summaries=selected_summaries,
        selected_peak_to_background_db=selected_background,
        selected_peak_to_competitor_db=selected_competitor,
        selection_status=selection_status,
        baseline_consensus_event_time_s=(
            baseline_cross.consensus_event_candidate_time_s
        ),
        selected_consensus_event_time_s=(
            selected_summary["cross_profile_consensus_event_time_s"]
        ),
    )


def _threshold_candidate_detection_config(
    base: SignalDetectionConfig,
    *,
    peak_to_background_db: float,
    peak_to_competitor_db: float,
) -> SignalDetectionConfig:
    """Change only the two approved spectral-contrast thresholds."""
    return SignalDetectionConfig(
        minimum_peak_to_background_db=peak_to_background_db,
        minimum_peak_to_competitor_db=peak_to_competitor_db,
        peak_exclusion_half_width_bins=base.peak_exclusion_half_width_bins,
        minimum_consecutive_frames=base.minimum_consecutive_frames,
        minimum_cycles_in_window=base.minimum_cycles_in_window,
        enabled=base.enabled,
    )


def _analyze_threshold_candidate(
    records: Mapping[str, SignalRecord],
    *,
    configuration: WorkflowConfiguration,
    detection_config: SignalDetectionConfig,
) -> dict[str, Mapping[str, ChannelAnalysis]]:
    return {
        profile.profile_id.value: analyze_profile(
            records,
            profile=profile,
            analysis_start_time_s=(
                configuration.analysis.analysis_start_time_s
            ),
            analysis_end_time_s=configuration.analysis.analysis_end_time_s,
            manual_event_reference_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
            vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
            velocity_correction_config=configuration.velocity_correction,
            detection_config=detection_config,
            event_candidate_config=configuration.event_candidate,
            background_guard_window_scale=(
                configuration.quality.background_guard_window_scale
            ),
            minimum_background_bin_count=(
                configuration.quality.minimum_background_bin_count
            ),
            assume_pre_event_zero_for_display=(
                configuration.plot.assume_pre_event_zero_for_display
            ),
        )
        for profile in configuration.analysis.profiles
    }


def _threshold_candidate_consensus(
    analyses_by_profile: Mapping[str, Mapping[str, ChannelAnalysis]],
    *,
    configuration: WorkflowConfiguration,
) -> tuple[dict[str, ProfileConsensusResult], CrossProfileConsensusResult]:
    profile_consensus_results = {
        profile_name: build_profile_consensus(
            {
                channel_name: analysis.stream_event_candidates
                for channel_name, analysis in analyses.items()
            },
            profile_name=profile_name,
            config=configuration.event_consensus,
        )
        for profile_name, analyses in analyses_by_profile.items()
    }
    cross_profile_consensus = build_cross_profile_consensus(
        profile_consensus_results,
        config=configuration.event_consensus,
        manual_event_reference_time_s=(
            configuration.analysis.manual_event_reference_time_s
        ),
    )
    return profile_consensus_results, cross_profile_consensus


def _threshold_candidate_rows(
    baseline_analyses: Mapping[str, Mapping[str, ChannelAnalysis]],
    candidate_analyses: Mapping[str, Mapping[str, ChannelAnalysis]],
    *,
    baseline_profile_consensus: Mapping[str, ProfileConsensusResult],
    candidate_profile_consensus: Mapping[str, ProfileConsensusResult],
    baseline_cross_profile_consensus: CrossProfileConsensusResult,
    candidate_cross_profile_consensus: CrossProfileConsensusResult,
    peak_to_background_db: float,
    peak_to_competitor_db: float,
) -> list[dict[str, Any]]:
    baseline_time_s = (
        baseline_cross_profile_consensus.consensus_event_candidate_time_s
    )
    candidate_time_s = (
        candidate_cross_profile_consensus.consensus_event_candidate_time_s
    )
    consensus_change_s = (
        None
        if baseline_time_s is None or candidate_time_s is None
        else candidate_time_s - baseline_time_s
    )
    rows: list[dict[str, Any]] = []
    for profile_name in sorted(baseline_analyses):
        baseline_profile = baseline_profile_consensus[profile_name]
        candidate_profile = candidate_profile_consensus[profile_name]
        for channel_name in sorted(baseline_analyses[profile_name]):
            baseline = baseline_analyses[profile_name][channel_name]
            candidate = candidate_analyses[profile_name][channel_name]
            baseline_measured = _measured_mask(baseline)
            candidate_measured = _measured_mask(candidate)
            if not np.array_equal(
                baseline.refined_result.time_s,
                candidate.refined_result.time_s,
            ):
                raise RuntimeError(
                    "Threshold scan candidates must retain the identical STFT axis."
                )
            reference_support = next(
                (
                    support
                    for support in baseline_profile.supporting_channel_segments
                    if support.channel_name == channel_name
                ),
                None,
            )
            reference_segment = (
                _segment_by_id(baseline, reference_support.segment_id)
                if reference_support is not None
                else None
            )
            main_mask = np.zeros(baseline_measured.shape, dtype=np.bool_)
            plateau_mask = np.zeros(baseline_measured.shape, dtype=np.bool_)
            falling_mask = np.zeros(baseline_measured.shape, dtype=np.bool_)
            tail_mask = np.zeros(baseline_measured.shape, dtype=np.bool_)
            if reference_segment is not None:
                start = reference_segment.start_frame_index
                stop = reference_segment.end_frame_index + 1
                split = start + (stop - start + 1) // 2
                main_mask[start:stop] = True
                plateau_mask[start:split] = True
                falling_mask[split:stop] = True
                for assessment in (
                    baseline.stream_event_candidates.segment_assessments
                ):
                    segment = assessment.segment
                    if segment.start_frame_index > reference_segment.end_frame_index:
                        tail_mask[
                            segment.start_frame_index : segment.end_frame_index + 1
                        ] = True

            pre_event_mask = (
                np.zeros(baseline_measured.shape, dtype=np.bool_)
                if baseline_time_s is None
                else baseline.refined_result.time_s < baseline_time_s
            )
            post_event_mask = (
                np.zeros(baseline_measured.shape, dtype=np.bool_)
                if baseline_time_s is None
                else baseline.refined_result.time_s >= baseline_time_s
            )
            main_baseline_count = int(np.count_nonzero(baseline_measured & main_mask))
            main_retained_count = int(
                np.count_nonzero(
                    baseline_measured & candidate_measured & main_mask
                )
            )
            plateau_baseline_count = int(
                np.count_nonzero(baseline_measured & plateau_mask)
            )
            plateau_retained_count = int(
                np.count_nonzero(
                    baseline_measured & candidate_measured & plateau_mask
                )
            )
            falling_baseline_count = int(
                np.count_nonzero(baseline_measured & falling_mask)
            )
            falling_retained_count = int(
                np.count_nonzero(
                    baseline_measured & candidate_measured & falling_mask
                )
            )
            tail_baseline_count = int(
                np.count_nonzero(baseline_measured & tail_mask)
            )
            tail_retained_count = int(
                np.count_nonzero(
                    baseline_measured & candidate_measured & tail_mask
                )
            )
            main_loss = baseline_measured & ~candidate_measured & main_mask
            rows.append(
                {
                    "peak_to_background_threshold_db": peak_to_background_db,
                    "peak_to_competitor_threshold_db": peak_to_competitor_db,
                    "profile": profile_name,
                    "channel": channel_name,
                    "pre_event_measured_count": int(
                        np.count_nonzero(candidate_measured & pre_event_mask)
                    ),
                    "main_event_baseline_count": main_baseline_count,
                    "main_event_retained_count": main_retained_count,
                    "main_event_retention_fraction": _retention_fraction(
                        main_retained_count,
                        main_baseline_count,
                    ),
                    "main_plateau_baseline_count": plateau_baseline_count,
                    "main_plateau_retained_count": plateau_retained_count,
                    "main_plateau_retention_fraction": _retention_fraction(
                        plateau_retained_count,
                        plateau_baseline_count,
                    ),
                    "falling_segment_baseline_count": falling_baseline_count,
                    "falling_segment_retained_count": falling_retained_count,
                    "falling_segment_retention_fraction": _retention_fraction(
                        falling_retained_count,
                        falling_baseline_count,
                    ),
                    "post_event_nan_count": int(
                        np.count_nonzero(~candidate_measured & post_event_mask)
                    ),
                    "post_event_added_nan_count": int(
                        np.count_nonzero(
                            baseline_measured
                            & ~candidate_measured
                            & post_event_mask
                        )
                    ),
                    "maximum_new_nan_gap_frames": _maximum_true_run(main_loss),
                    "tail_unreviewed_baseline_count": tail_baseline_count,
                    "tail_unreviewed_retained_count": tail_retained_count,
                    "tail_unreviewed_retention_fraction": _retention_fraction(
                        tail_retained_count,
                        tail_baseline_count,
                    ),
                    "consensus_status": (
                        candidate_profile.profile_consensus_status.value
                    ),
                    "cross_profile_consensus_status": (
                        candidate_cross_profile_consensus
                        .consensus_event_status.value
                    ),
                    "cross_profile_consensus_event_time_s": candidate_time_s,
                    "cross_profile_consensus_time_change_s": consensus_change_s,
                    "pre_event_reference_available": baseline_time_s is not None,
                    "main_segment_reference_available": (
                        reference_segment is not None
                    ),
                    "selected": False,
                }
            )
    return rows


def _threshold_candidate_summary(
    rows: Sequence[Mapping[str, Any]],
    *,
    baseline_cross_profile_consensus: CrossProfileConsensusResult,
    candidate_cross_profile_consensus: CrossProfileConsensusResult,
    candidate_profile_consensus: Mapping[str, ProfileConsensusResult],
    consensus_config: EventConsensusConfig,
    minimum_consecutive_frames: int,
    peak_to_background_db: float,
    peak_to_competitor_db: float,
) -> dict[str, Any]:
    rejection_reasons: list[str] = []
    if (
        baseline_cross_profile_consensus.consensus_event_candidate_time_s
        is None
    ):
        rejection_reasons.append("baseline_cross_profile_consensus_unavailable")
    if any(int(row["pre_event_measured_count"]) != 0 for row in rows):
        rejection_reasons.append("pre_event_measured_frames_remain")
    if any(
        not math.isfinite(float(row["main_event_retention_fraction"]))
        or float(row["main_event_retention_fraction"])
        < MAIN_EVENT_MINIMUM_RETENTION_FRACTION
        for row in rows
    ):
        rejection_reasons.append("main_event_retention_below_98_percent")
    if any(
        int(row["maximum_new_nan_gap_frames"]) >= minimum_consecutive_frames
        for row in rows
    ):
        rejection_reasons.append("new_long_nan_gap_in_main_event")
    if any(
        result.profile_consensus_status.value != "dual_channel_consensus"
        for result in candidate_profile_consensus.values()
    ):
        rejection_reasons.append("profile_dual_channel_consensus_lost")
    baseline_time_s = (
        baseline_cross_profile_consensus.consensus_event_candidate_time_s
    )
    candidate_time_s = (
        candidate_cross_profile_consensus.consensus_event_candidate_time_s
    )
    if baseline_time_s is None or candidate_time_s is None:
        rejection_reasons.append("cross_profile_consensus_time_unavailable")
    elif (
        abs(candidate_time_s - baseline_time_s)
        > consensus_config.cross_profile_time_tolerance_s
    ):
        rejection_reasons.append("cross_profile_consensus_time_drift")
    if any(
        int(row["tail_unreviewed_baseline_count"]) > 0
        and int(row["tail_unreviewed_retained_count"]) == 0
        for row in rows
    ):
        rejection_reasons.append("tail_unreviewed_branch_removed")
    return {
        "peak_to_background_threshold_db": peak_to_background_db,
        "peak_to_competitor_threshold_db": peak_to_competitor_db,
        "qualifies": not rejection_reasons,
        "rejection_reasons": tuple(rejection_reasons),
        "cross_profile_consensus_status": (
            candidate_cross_profile_consensus.consensus_event_status.value
        ),
        "cross_profile_consensus_event_time_s": candidate_time_s,
        "cross_profile_consensus_time_change_s": (
            None
            if baseline_time_s is None or candidate_time_s is None
            else candidate_time_s - baseline_time_s
        ),
    }


def _select_threshold_candidate(
    candidate_summaries: Sequence[Mapping[str, Any]],
) -> tuple[float, float, str]:
    """Select the smallest approved qualifying pair, else retain 10/3."""
    summaries_by_pair = {
        (
            float(summary["peak_to_background_threshold_db"]),
            float(summary["peak_to_competitor_threshold_db"]),
        ): summary
        for summary in candidate_summaries
    }
    if set(summaries_by_pair) != set(THRESHOLD_CALIBRATION_CANDIDATES_DB):
        raise ValueError("Threshold summaries must cover exactly the approved pairs.")
    for pair in THRESHOLD_CALIBRATION_CANDIDATES_DB:
        if bool(summaries_by_pair[pair]["qualifies"]):
            return (*pair, "smallest_candidate_meeting_all_criteria")
    return (
        *THRESHOLD_CALIBRATION_CANDIDATES_DB[0],
        "no_candidate_met_all_criteria_fallback_to_10_3",
    )


def _validate_configured_detection_thresholds(
    detection_config: SignalDetectionConfig,
    *,
    calibration: ThresholdCalibrationResult,
) -> None:
    configured = (
        detection_config.minimum_peak_to_background_db,
        detection_config.minimum_peak_to_competitor_db,
    )
    selected = (
        calibration.selected_peak_to_background_db,
        calibration.selected_peak_to_competitor_db,
    )
    if configured != selected:
        raise RuntimeError(
            "Configured detection thresholds do not match deterministic "
            f"calibration selection: configured={configured}, selected={selected}."
        )


def _measured_mask(
    analysis: ChannelAnalysis,
) -> np.ndarray[Any, np.dtype[np.bool_]]:
    states = analysis.signal_detection_result.signal_states
    return np.fromiter(
        (state is SignalState.MEASURED for state in states),
        dtype=np.bool_,
        count=len(states),
    )


def _segment_by_id(analysis: ChannelAnalysis, segment_id: str) -> Any:
    for assessment in analysis.stream_event_candidates.segment_assessments:
        if assessment.segment.segment_id == segment_id:
            return assessment.segment
    raise RuntimeError(f"Consensus-supporting segment is absent: {segment_id}")


def _retention_fraction(retained_count: int, baseline_count: int) -> float:
    return (
        float(retained_count / baseline_count)
        if baseline_count > 0
        else math.nan
    )


def _maximum_true_run(mask: np.ndarray[Any, np.dtype[np.bool_]]) -> int:
    maximum = 0
    current = 0
    for value in mask:
        if bool(value):
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _write_run_level_event_outputs(
    output_directory: Path,
    comparisons_directory: Path,
    analyses_by_profile: Mapping[str, Mapping[str, ChannelAnalysis]],
    *,
    profile_consensus_results: Mapping[str, ProfileConsensusResult],
    cross_profile_consensus: CrossProfileConsensusResult,
    configuration: WorkflowConfiguration,
    threshold_calibration: ThresholdCalibrationResult,
) -> list[Path]:
    segment_rows = _all_segment_rows(analyses_by_profile)
    measured_segments_path = comparisons_directory / "measured_segments.csv"
    pd.DataFrame(segment_rows).to_csv(measured_segments_path, index=False)

    event_consensus_path = output_directory / "event_consensus.json"
    _write_json(
        event_consensus_path,
        {
            "segment_time_definitions": {
                "span_duration_s": (
                    "last STFT frame center minus first STFT frame center"
                ),
                "support_duration_s": (
                    "frame-center span plus one complete STFT window; union of "
                    "overlapping window supports; not a physical event-duration claim"
                ),
            },
            "event_candidate_config": _event_candidate_config_dict(
                configuration.event_candidate
            ),
            "event_consensus_config": _event_consensus_config_dict(
                configuration.event_consensus
            ),
            "detection_thresholds": {
                "minimum_peak_to_background_db": (
                    configuration.quality.signal_detection
                    .minimum_peak_to_background_db
                ),
                "minimum_peak_to_competitor_db": (
                    configuration.quality.signal_detection
                    .minimum_peak_to_competitor_db
                ),
                "provenance": THRESHOLD_CALIBRATION_PROVENANCE,
                "calibration_filename": THRESHOLD_CALIBRATION_FILENAME,
            },
            "segments": segment_rows,
            "profile_consensus_results": {
                name: _profile_consensus_dict(result)
                for name, result in profile_consensus_results.items()
            },
            "cross_profile_consensus": _cross_profile_consensus_dict(
                cross_profile_consensus
            ),
            "manual_event_reference_role": (
                "diagnostic line and difference only; never used for selection"
            ),
            "measured_semantics": (
                "MEASURED means spectrally qualified under the configured detection "
                "rules. It does not confirm the physical identity of the selected "
                "branch."
            ),
            "physical_branch_review_status": (
                PhysicalBranchReviewStatus.UNREVIEWED.value
            ),
        },
    )

    threshold_audit = _threshold_transferability_audit(
        analyses_by_profile,
        manual_event_reference_time_s=(
            configuration.analysis.manual_event_reference_time_s
        ),
    )
    threshold_path = comparisons_directory / "threshold_transferability_audit.csv"
    threshold_audit.to_csv(threshold_path, index=False)

    calibration_path = comparisons_directory / THRESHOLD_CALIBRATION_FILENAME
    pd.DataFrame(threshold_calibration.rows).to_csv(
        calibration_path,
        index=False,
    )

    sensitivity_path = comparisons_directory / "event_candidate_sensitivity.csv"
    _event_candidate_sensitivity(
        analyses_by_profile,
        consensus_config=configuration.event_consensus,
        manual_event_reference_time_s=(
            configuration.analysis.manual_event_reference_time_s
        ),
    ).to_csv(sensitivity_path, index=False)

    return [
        measured_segments_path,
        event_consensus_path,
        _save_all_segments_timeline(
            comparisons_directory,
            analyses_by_profile,
            profile_consensus_results=profile_consensus_results,
            manual_event_reference_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
        ),
        _save_cross_profile_consensus_plot(
            comparisons_directory,
            profile_consensus_results,
            cross_profile_consensus=cross_profile_consensus,
            manual_event_reference_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
        ),
        threshold_path,
        calibration_path,
        _save_spectral_contrast_distribution_comparison(
            comparisons_directory,
            analyses_by_profile,
            manual_event_reference_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
        ),
        _save_band_boundary_fraction_comparison(
            comparisons_directory,
            threshold_audit,
        ),
        sensitivity_path,
    ]


def _all_segment_rows(
    analyses_by_profile: Mapping[str, Mapping[str, ChannelAnalysis]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for profile_name in sorted(analyses_by_profile):
        for channel_name in sorted(analyses_by_profile[profile_name]):
            candidates = analyses_by_profile[profile_name][
                channel_name
            ].stream_event_candidates
            for assessment in candidates.segment_assessments:
                segment = assessment.segment
                rows.append(
                    {
                        "segment_id": segment.segment_id,
                        "profile_name": segment.profile_name,
                        "channel_name": segment.channel_name,
                        "start_frame_index": segment.start_frame_index,
                        "end_frame_index": segment.end_frame_index,
                        "start_time_s": segment.start_time_s,
                        "end_time_s": segment.end_time_s,
                        "frame_count": segment.frame_count,
                        "span_duration_s": segment.span_duration_s,
                        "support_duration_s": segment.support_duration_s,
                        "start_frequency_hz": segment.start_frequency_hz,
                        "median_frequency_hz": segment.median_frequency_hz,
                        "minimum_frequency_hz": segment.minimum_frequency_hz,
                        "maximum_frequency_hz": segment.maximum_frequency_hz,
                        "maximum_adjacent_frequency_step_hz": (
                            segment.maximum_adjacent_frequency_step_hz
                        ),
                        "median_peak_to_background_db": (
                            segment.median_peak_to_background_db
                        ),
                        "median_peak_to_competitor_db": (
                            segment.median_peak_to_competitor_db
                        ),
                        "minimum_peak_to_background_db": (
                            segment.minimum_peak_to_background_db
                        ),
                        "minimum_peak_to_competitor_db": (
                            segment.minimum_peak_to_competitor_db
                        ),
                        "candidate_eligible": assessment.candidate_eligible,
                        "rejection_reasons": "|".join(
                            reason.value
                            for reason in assessment.rejection_reasons
                        ),
                        "physical_branch_review_status": (
                            segment.physical_branch_review_status.value
                        ),
                    }
                )
    return rows


def _save_all_segments_timeline(
    output_directory: Path,
    analyses_by_profile: Mapping[str, Mapping[str, ChannelAnalysis]],
    *,
    profile_consensus_results: Mapping[str, ProfileConsensusResult],
    manual_event_reference_time_s: float | None,
) -> Path:
    path = output_directory / "all_measured_segments_timeline.png"
    streams = [
        (profile_name, channel_name, analyses_by_profile[profile_name][channel_name])
        for profile_name in sorted(analyses_by_profile)
        for channel_name in sorted(analyses_by_profile[profile_name])
    ]
    supporting_ids = {
        support.segment_id
        for result in profile_consensus_results.values()
        for support in result.supporting_channel_segments
    }
    figure, axis = plt.subplots(figsize=(12.0, 6.2), constrained_layout=True)
    for row, (_, _, analysis) in enumerate(streams):
        for assessment in analysis.stream_event_candidates.segment_assessments:
            segment = assessment.segment
            selected = segment.segment_id in supporting_ids
            color = (
                "#2ca02c"
                if selected
                else "#1f77b4"
                if assessment.candidate_eligible
                else "#9e9e9e"
            )
            axis.plot(
                (
                    _plot_scalar_time_us(
                        segment.start_time_s,
                        manual_event_reference_time_s,
                    ),
                    _plot_scalar_time_us(
                        segment.end_time_s,
                        manual_event_reference_time_s,
                    ),
                ),
                (row, row),
                color=color,
                linewidth=4.0 if selected else 2.0,
                solid_capstyle="butt",
            )
    if manual_event_reference_time_s is not None:
        axis.axvline(
            0.0,
            color="#c7a600",
            linestyle=":",
            label="manual reference (diagnostic only)",
        )
    axis.set_yticks(
        np.arange(len(streams)),
        labels=[f"{profile}/{channel}" for profile, channel, _ in streams],
    )
    axis.set_xlabel(_time_axis_label(manual_event_reference_time_s))
    axis.set_title(
        "All exact MEASURED segments: eligible, rejected, and consensus support"
    )
    axis.plot([], [], color="#2ca02c", linewidth=4.0, label="consensus support")
    axis.plot([], [], color="#1f77b4", linewidth=3.0, label="eligible")
    axis.plot([], [], color="#9e9e9e", linewidth=3.0, label="event-level rejected")
    axis.grid(axis="x", alpha=0.25)
    axis.legend(loc="best")
    _save_figure(figure, path)
    return path


def _save_cross_profile_consensus_plot(
    output_directory: Path,
    profile_results: Mapping[str, ProfileConsensusResult],
    *,
    cross_profile_consensus: CrossProfileConsensusResult,
    manual_event_reference_time_s: float | None,
) -> Path:
    path = output_directory / "cross_profile_consensus.png"
    names = sorted(profile_results)
    figure, axis = plt.subplots(figsize=(9.5, 5.2), constrained_layout=True)
    for row, name in enumerate(names):
        value = profile_results[name].profile_consensus_candidate_time_s
        if value is not None:
            axis.scatter(
                _plot_scalar_time_us(value, manual_event_reference_time_s),
                row,
                s=65.0,
                color="#1f77b4",
                label="profile dual-channel consensus" if row == 0 else "_nolegend_",
            )
    final_time = cross_profile_consensus.consensus_event_candidate_time_s
    if final_time is not None:
        axis.axvline(
            _plot_scalar_time_us(final_time, manual_event_reference_time_s),
            color="#2ca02c",
            linestyle="--",
            linewidth=1.4,
            label="final cross-profile candidate",
        )
    if manual_event_reference_time_s is not None:
        axis.axvline(
            0.0,
            color="#c7a600",
            linestyle=":",
            linewidth=0.9,
            label="manual reference (diagnostic only)",
        )
    axis.set_yticks(np.arange(len(names)), labels=names)
    axis.set_xlabel(_time_axis_label(manual_event_reference_time_s))
    axis.set_title(
        "Cross-profile consensus metadata\n"
        f"status={cross_profile_consensus.consensus_event_status.value}"
    )
    axis.grid(axis="x", alpha=0.25)
    axis.legend(loc="best")
    _save_figure(figure, path)
    return path


def _threshold_regions(
    manual_event_reference_time_s: float | None,
) -> tuple[tuple[str, float, float], ...]:
    if manual_event_reference_time_s is None:
        return (("complete_record", -math.inf, math.inf),)
    reference = manual_event_reference_time_s
    return (
        ("pre_manual_reference", -math.inf, reference),
        ("main_plateau_0.08_to_0.50_us", reference + 0.08e-6, reference + 0.50e-6),
        ("decline_0.50_to_0.782_us", reference + 0.50e-6, reference + 0.782e-6),
        ("record_tail_from_0.782_us", reference + 0.782e-6, math.inf),
    )


def _threshold_transferability_audit(
    analyses_by_profile: Mapping[str, Mapping[str, ChannelAnalysis]],
    *,
    manual_event_reference_time_s: float | None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for profile_name in sorted(analyses_by_profile):
        for channel_name in sorted(analyses_by_profile[profile_name]):
            analysis = analyses_by_profile[profile_name][channel_name]
            detection = analysis.signal_detection_result
            stft = analysis.stft_result
            main_lobe_width_hz = (
                4.0 * stft.sample_rate_hz / stft.window_length_samples
            )
            guard_half_width_hz = (
                analysis.spectral_quality_result
                .background_exclusion_half_width_hz
            )
            lower_grid_frequency_hz = float(
                stft.frequency_hz[
                    np.flatnonzero(
                        stft.frequency_hz
                        >= analysis.refined_result.minimum_frequency_hz
                    )[0]
                ]
            )
            for region_name, start, stop in _threshold_regions(
                manual_event_reference_time_s
            ):
                mask = (detection.time_s >= start) & (detection.time_s < stop)
                states = np.asarray(
                    [state.value for state in detection.signal_states],
                    dtype=object,
                )
                frame_count = int(np.count_nonzero(mask))
                p2b = detection.peak_to_background_db[mask]
                p2c = detection.peak_to_competitor_db[mask]
                finite_p2b = p2b[np.isfinite(p2b)]
                finite_p2c = p2c[np.isfinite(p2c)]
                coarse = detection.coarse_peak_frequency_hz[mask]
                rows.append(
                    {
                        "profile_name": profile_name,
                        "channel_name": channel_name,
                        "region": region_name,
                        "frame_count": frame_count,
                        "peak_to_background_db_p05": _percentile_or_nan(
                            finite_p2b,
                            5.0,
                        ),
                        "peak_to_background_db_median": _percentile_or_nan(
                            finite_p2b,
                            50.0,
                        ),
                        "peak_to_background_db_p95": _percentile_or_nan(
                            finite_p2b,
                            95.0,
                        ),
                        "peak_to_competitor_db_p05": _percentile_or_nan(
                            finite_p2c,
                            5.0,
                        ),
                        "peak_to_competitor_db_median": _percentile_or_nan(
                            finite_p2c,
                            50.0,
                        ),
                        "peak_to_competitor_db_p95": _percentile_or_nan(
                            finite_p2c,
                            95.0,
                        ),
                        "band_boundary_fraction": _state_fraction(
                            states,
                            mask,
                            SignalState.PEAK_AT_BAND_BOUNDARY.value,
                        ),
                        "ambiguous_fraction": _state_fraction(
                            states,
                            mask,
                            SignalState.AMBIGUOUS_PEAK.value,
                        ),
                        "measured_fraction": _state_fraction(
                            states,
                            mask,
                            SignalState.MEASURED.value,
                        ),
                        "no_detectable_beat_fraction": _state_fraction(
                            states,
                            mask,
                            SignalState.NO_DETECTABLE_BEAT.value,
                        ),
                        "lower_grid_argmax_fraction": (
                            float(
                                np.count_nonzero(
                                    np.isclose(
                                        coarse,
                                        lower_grid_frequency_hz,
                                        rtol=0.0,
                                        atol=0.5,
                                    )
                                )
                                / frame_count
                            )
                            if frame_count
                            else math.nan
                        ),
                        "frequency_bin_spacing_hz": float(
                            stft.frequency_hz[1] - stft.frequency_hz[0]
                        ),
                        "guard_half_width_hz": guard_half_width_hz,
                        "guard_full_width_hz": 2.0 * guard_half_width_hz,
                        "hann_main_lobe_zero_to_zero_hz": main_lobe_width_hz,
                        "guard_to_main_lobe_width_ratio": (
                            2.0 * guard_half_width_hz / main_lobe_width_hz
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _save_spectral_contrast_distribution_comparison(
    output_directory: Path,
    analyses_by_profile: Mapping[str, Mapping[str, ChannelAnalysis]],
    *,
    manual_event_reference_time_s: float | None,
) -> Path:
    path = output_directory / "spectral_contrast_distribution_comparison.png"
    streams = [
        (profile_name, channel_name, analyses_by_profile[profile_name][channel_name])
        for profile_name in sorted(analyses_by_profile)
        for channel_name in sorted(analyses_by_profile[profile_name])
    ]
    regions = _threshold_regions(manual_event_reference_time_s)
    figure, axes = plt.subplots(
        2,
        1,
        figsize=(14.0, 9.0),
        sharex=True,
        constrained_layout=True,
    )
    for axis, field_name, title in (
        (axes[0], "peak_to_background_db", "Peak/background magnitude contrast"),
        (axes[1], "peak_to_competitor_db", "Peak/competitor magnitude contrast"),
    ):
        values: list[np.ndarray[Any, np.dtype[np.float64]]] = []
        labels: list[str] = []
        for region_name, start, stop in regions:
            for profile_name, channel_name, analysis in streams:
                detection = analysis.signal_detection_result
                mask = (detection.time_s >= start) & (detection.time_s < stop)
                selected = getattr(detection, field_name)[mask]
                values.append(selected[np.isfinite(selected)])
                labels.append(
                    f"{region_name}\n{profile_name}/{channel_name[-1]}"
                )
        axis.boxplot(values, tick_labels=labels, showfliers=False)
        axis.set_ylabel("Magnitude contrast (dB)")
        axis.set_title(title)
        axis.grid(axis="y", alpha=0.2)
    axes[1].tick_params(axis="x", rotation=75, labelsize=7)
    figure.suptitle(
        "Four-stream threshold-transferability evidence; descriptive, not formal SNR"
    )
    _save_figure(figure, path)
    return path


def _save_band_boundary_fraction_comparison(
    output_directory: Path,
    threshold_audit: pd.DataFrame,
) -> Path:
    path = output_directory / "band_boundary_fraction_comparison.png"
    streams = sorted(
        {
            f"{row.profile_name}/{row.channel_name}"
            for row in threshold_audit.itertuples()
        }
    )
    regions = list(dict.fromkeys(threshold_audit["region"].tolist()))
    x = np.arange(len(regions), dtype=np.float64)
    width = 0.18
    figure, axis = plt.subplots(figsize=(12.0, 6.0), constrained_layout=True)
    for index, stream in enumerate(streams):
        profile_name, channel_name = stream.split("/", maxsplit=1)
        selected = threshold_audit.loc[
            threshold_audit.profile_name.eq(profile_name)
            & threshold_audit.channel_name.eq(channel_name)
        ]
        fractions = [
            float(selected.loc[selected.region.eq(region), "band_boundary_fraction"].iloc[0])
            for region in regions
        ]
        axis.bar(
            x + (index - 1.5) * width,
            fractions,
            width,
            label=stream,
        )
    axis.set_xticks(x, labels=regions, rotation=20, ha="right")
    axis.set_ylabel("PEAK_AT_BAND_BOUNDARY fraction")
    axis.set_ylim(0.0, 1.0)
    axis.set_title("Band-boundary rejection differs by profile and channel")
    axis.grid(axis="y", alpha=0.2)
    axis.legend(loc="best")
    _save_figure(figure, path)
    return path


def _event_candidate_sensitivity(
    analyses_by_profile: Mapping[str, Mapping[str, ChannelAnalysis]],
    *,
    consensus_config: EventConsensusConfig,
    manual_event_reference_time_s: float | None,
) -> pd.DataFrame:
    variants = (
        ("default_8_frames_20ns_100MHz", EventCandidateConfig()),
        (
            "permissive_3_frames_0ns_100MHz",
            EventCandidateConfig(
                minimum_segment_frames=3,
                minimum_segment_duration_s=0.0,
            ),
        ),
        (
            "5_frames_10ns_100MHz",
            EventCandidateConfig(
                minimum_segment_frames=5,
                minimum_segment_duration_s=10.0e-9,
            ),
        ),
        (
            "8_frames_20ns_50MHz",
            EventCandidateConfig(maximum_adjacent_frequency_step_hz=50.0e6),
        ),
        (
            "8_frames_20ns_200MHz",
            EventCandidateConfig(maximum_adjacent_frequency_step_hz=200.0e6),
        ),
        (
            "12_frames_30ns_100MHz",
            EventCandidateConfig(
                minimum_segment_frames=12,
                minimum_segment_duration_s=30.0e-9,
            ),
        ),
    )
    rows: list[dict[str, Any]] = []
    for variant_name, candidate_config in variants:
        profile_results: dict[str, ProfileConsensusResult] = {}
        streams_by_profile: dict[str, dict[str, StreamEventCandidates]] = {}
        for profile_name in sorted(analyses_by_profile):
            streams_by_profile[profile_name] = {}
            for channel_name in sorted(analyses_by_profile[profile_name]):
                analysis = analyses_by_profile[profile_name][channel_name]
                stream = build_stream_event_candidates(
                    analysis.signal_detection_result,
                    profile_name=profile_name,
                    channel_name=channel_name,
                    config=candidate_config,
                )
                streams_by_profile[profile_name][channel_name] = stream
            profile_results[profile_name] = build_profile_consensus(
                streams_by_profile[profile_name],
                profile_name=profile_name,
                config=consensus_config,
            )
        cross = build_cross_profile_consensus(
            profile_results,
            config=consensus_config,
            manual_event_reference_time_s=manual_event_reference_time_s,
        )
        for profile_name in sorted(streams_by_profile):
            for channel_name in sorted(streams_by_profile[profile_name]):
                stream = streams_by_profile[profile_name][channel_name]
                rows.append(
                    {
                        "variant": variant_name,
                        "minimum_segment_frames": (
                            candidate_config.minimum_segment_frames
                        ),
                        "minimum_segment_duration_s": (
                            candidate_config.minimum_segment_duration_s
                        ),
                        "maximum_adjacent_frequency_step_hz": (
                            candidate_config.maximum_adjacent_frequency_step_hz
                        ),
                        "profile_name": profile_name,
                        "channel_name": channel_name,
                        "eligible_segment_count": len(stream.eligible_segments),
                        "primary_candidate_time_s": (
                            stream.primary_candidate_time_s
                        ),
                        "profile_consensus_status": (
                            profile_results[
                                profile_name
                            ].profile_consensus_status.value
                        ),
                        "profile_consensus_candidate_time_s": (
                            profile_results[
                                profile_name
                            ].profile_consensus_candidate_time_s
                        ),
                        "cross_profile_consensus_status": (
                            cross.consensus_event_status.value
                        ),
                        "cross_profile_candidate_time_s": (
                            cross.consensus_event_candidate_time_s
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _state_fraction(
    states: np.ndarray[Any, Any],
    mask: np.ndarray[Any, np.dtype[np.bool_]],
    state: str,
) -> float:
    count = int(np.count_nonzero(mask))
    return float(np.count_nonzero(states[mask] == state) / count) if count else math.nan


def _percentile_or_nan(
    values: np.ndarray[Any, np.dtype[np.float64]],
    percentile: float,
) -> float:
    return float(np.percentile(values, percentile)) if values.size else math.nan


def _channel_summary(
    channel_name: str,
    analysis: ChannelAnalysis,
    *,
    profile: AnalysisProfile,
    event_start_time_s: float | None,
    source_sha256: str,
) -> dict[str, Any]:
    refined = analysis.refined_result
    quality = analysis.spectral_quality_result
    continuity = analysis.continuity_result
    detection = analysis.signal_detection_result
    stream_candidates = analysis.stream_event_candidates
    flags = refined.quality_flags
    candidate_indices = np.asarray(
        [index for index, flag in enumerate(flags) if flag is RidgeQualityFlag.CANDIDATE],
        dtype=np.int64,
    )
    refined_indices = np.asarray(
        [
            index
            for index, status in enumerate(refined.refinement_statuses)
            if status is RidgeRefinementStatus.REFINED
        ],
        dtype=np.int64,
    )
    measured_indices = np.asarray(
        [
            index
            for index, state in enumerate(detection.signal_states)
            if state is SignalState.MEASURED
        ],
        dtype=np.int64,
    )
    first_index = int(measured_indices[0]) if measured_indices.size else None
    finite_refined = measured_indices[
        np.isfinite(detection.refined_frequency_hz[measured_indices])
    ]
    finite_steps = continuity.absolute_frequency_step_hz[
        np.isfinite(continuity.absolute_frequency_step_hz)
    ]
    return {
        "channel_name": channel_name,
        "profile_id": profile.profile_id.value,
        "total_frame_count": int(refined.time_s.size),
        "pre_event_frame_count": sum(
            flag is RidgeQualityFlag.PRE_EVENT for flag in flags
        ),
        "candidate_frame_count": int(candidate_indices.size),
        "outside_frame_count": sum(
            flag is RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW for flag in flags
        ),
        "refined_frame_count": int(refined_indices.size),
        **{
            f"{state.value}_frame_count": sum(
                item is state for item in detection.signal_states
            )
            for state in SignalState
        },
        "detected_event_candidate_time_s": (
            stream_candidates.primary_candidate_time_s
        ),
        "detected_event_candidate_segment_id": (
            stream_candidates.primary_candidate_segment_id
        ),
        "detected_event_candidate_source": (
            "event_level_eligible_measured_segment"
        ),
        "legacy_task013_first_measured_run_time_s": (
            detection.detected_event_candidate_time_s
        ),
        "legacy_task013_first_measured_run_frame_count": (
            detection.detected_event_candidate_run_frame_count
        ),
        "legacy_task013_first_measured_run_source": (
            "first_final_measured_run_compatibility_metadata"
        ),
        "measured_segment_count": len(stream_candidates.segment_assessments),
        "event_level_eligible_segment_count": len(
            stream_candidates.eligible_segments
        ),
        "measured_semantics": (
            "spectrally qualified under configured detection rules; "
            "physical branch identity is not confirmed"
        ),
        "physical_branch_review_status": (
            PhysicalBranchReviewStatus.UNREVIEWED.value
        ),
        "manual_event_reference_time_s": event_start_time_s,
        "first_candidate_time_relative_s": _array_value(
            _relative_time_s(refined.time_s, event_start_time_s),
            first_index,
        ),
        "first_candidate_discrete_frequency_hz": _array_value(
            refined.discrete_frequency_hz,
            first_index,
        ),
        "first_candidate_refined_frequency_hz": _array_value(
            detection.refined_frequency_hz,
            first_index,
        ),
        "first_candidate_apparent_velocity_m_s": _array_value(
            analysis.refined_velocity_m_s,
            first_index,
        ),
        "first_candidate_peak_magnitude": _array_value(
            refined.peak_magnitude,
            first_index,
        ),
        "first_candidate_peak_to_background_db": _array_value(
            quality.peak_to_background_db,
            first_index,
        ),
        "first_candidate_peak_to_competitor_db": _array_value(
            quality.peak_to_competitor_db,
            first_index,
        ),
        "minimum_candidate_refined_frequency_hz": _minimum_at_indices(
            detection.refined_frequency_hz,
            finite_refined,
        ),
        "minimum_candidate_apparent_velocity_m_s": _minimum_at_indices(
            analysis.refined_velocity_m_s,
            finite_refined,
        ),
        "peak_to_background_db_median": _finite_percentile(
            detection.peak_to_background_db,
            50.0,
        ),
        "peak_to_background_db_p05": _finite_percentile(
            quality.peak_to_background_db,
            5.0,
        ),
        "peak_to_competitor_db_median": _finite_percentile(
            detection.peak_to_competitor_db,
            50.0,
        ),
        "peak_to_competitor_db_p05": _finite_percentile(
            quality.peak_to_competitor_db,
            5.0,
        ),
        "finite_continuity_step_count": int(finite_steps.size),
        "maximum_absolute_frequency_step_hz": (
            float(np.max(finite_steps)) if finite_steps.size else None
        ),
        "source_path": str(refined.source_path) if refined.source_path else "",
        "source_sha256": source_sha256,
    }


def _event_onset_diagnostic(
    analysis: ChannelAnalysis,
    *,
    event_start_time_s: float | None,
) -> dict[str, Any]:
    stft = analysis.stft_result
    refined = analysis.refined_result
    window_duration_s = stft.window_length_samples / stft.sample_rate_hz
    if event_start_time_s is None:
        return {
            "manual_event_reference_time_s": None,
            "status": "manual reference not configured",
            "stft_window_duration_s": window_duration_s,
        }
    candidate_indices = [
        index
        for index, flag in enumerate(refined.quality_flags)
        if flag is RidgeQualityFlag.CANDIDATE
    ]
    first_index = candidate_indices[0] if candidate_indices else None
    first_center = _array_value(stft.time_s, first_index)
    support_start = (
        first_center - window_duration_s / 2.0 if first_center is not None else None
    )
    support_end = (
        first_center + window_duration_s / 2.0 if first_center is not None else None
    )
    intervals = {
        "pre_event_one_window": (
            stft.time_s >= event_start_time_s - window_duration_s
        )
        & (stft.time_s < event_start_time_s),
        "post_event_one_window": (stft.time_s >= event_start_time_s)
        & (stft.time_s <= event_start_time_s + window_duration_s),
    }
    bands = {
        "0_to_0_05_ghz": (0.0, 0.05e9),
        "0_05_to_0_1_ghz": (0.05e9, 0.1e9),
        "0_1_to_0_8_ghz": (0.1e9, 0.8e9),
    }
    spectral_evidence: dict[str, Any] = {}
    for interval_name, time_mask in intervals.items():
        spectral_evidence[interval_name] = {
            band_name: _spectral_band_evidence(
                stft.time_s,
                stft.frequency_hz,
                stft.spectrum,
                time_mask=time_mask,
                minimum_frequency_hz=minimum,
                maximum_frequency_hz=maximum,
                event_start_time_s=event_start_time_s,
            )
            for band_name, (minimum, maximum) in bands.items()
        }
    return {
        "stft_window_duration_s": window_duration_s,
        "stft_window_half_support_s": window_duration_s / 2.0,
        "first_candidate_window_center_s": first_center,
        "first_candidate_window_support_start_s": support_start,
        "first_candidate_window_support_end_s": support_end,
        "first_candidate_window_support_crosses_event_start": (
            support_start is not None
            and support_end is not None
            and support_start < event_start_time_s < support_end
        ),
        "spectral_evidence": spectral_evidence,
    }


def _spectral_band_evidence(
    time_s: np.ndarray[Any, Any],
    frequency_hz: np.ndarray[Any, Any],
    spectrum: np.ndarray[Any, Any],
    *,
    time_mask: np.ndarray[Any, np.dtype[np.bool_]],
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    event_start_time_s: float,
) -> dict[str, Any]:
    frequency_mask = (frequency_hz >= minimum_frequency_hz) & (
        frequency_hz < maximum_frequency_hz
    )
    frame_indices = np.flatnonzero(time_mask)
    frequency_indices = np.flatnonzero(frequency_mask)
    if frame_indices.size == 0 or frequency_indices.size == 0:
        return {
            "frame_count": int(frame_indices.size),
            "frequency_bin_count": int(frequency_indices.size),
            "squared_magnitude_sum": 0.0,
            "local_peak_frequency_hz": None,
            "local_peak_magnitude": None,
            "local_peak_time_relative_s": None,
        }
    magnitude = np.abs(spectrum[np.ix_(frequency_indices, frame_indices)])
    flat_index = int(np.argmax(magnitude))
    frequency_offset, time_offset = np.unravel_index(flat_index, magnitude.shape)
    frequency_index = int(frequency_indices[frequency_offset])
    time_index = int(frame_indices[time_offset])
    return {
        "frame_count": int(frame_indices.size),
        "frequency_bin_count": int(frequency_indices.size),
        "squared_magnitude_sum": float(np.sum(np.square(magnitude))),
        "local_peak_frequency_hz": float(frequency_hz[frequency_index]),
        "local_peak_magnitude": float(magnitude[frequency_offset, time_offset]),
        "local_peak_time_relative_s": float(time_s[time_index] - event_start_time_s),
    }


def _profile_manifest(
    profile_directory: Path,
    profile: AnalysisProfile,
    analyses: Mapping[str, ChannelAnalysis],
    *,
    channel_summaries: Mapping[str, Mapping[str, Any]],
    onset_diagnostics: Mapping[str, Mapping[str, Any]],
    profile_consensus: ProfileConsensusResult,
    configuration: WorkflowConfiguration,
    source_sha256: str,
    runtime_s: float,
) -> dict[str, Any]:
    generated_files = [
        str(path.relative_to(profile_directory)).replace("\\", "/")
        for path in _expected_profile_paths(
            profile_directory,
            channel_names=tuple(sorted(analyses)),
        )
    ]
    return {
        "profile_id": profile.profile_id.value,
        "profile": _profile_dict(profile),
        "search_frequency_range_hz": [
            profile.minimum_frequency_hz,
            profile.maximum_frequency_hz,
        ],
        "full_range_preview": {
            "frequency_range_hz": [
                profile.minimum_frequency_hz,
                profile.maximum_frequency_hz,
            ],
            "frame_scope": "complete_stft_time_axis",
            "formal_quality_gate_applied": False,
            "frequency_selection": (
                "strongest discrete argmax in the fixed search band for every frame"
            ),
            "rendering": (
                "state-layered markers; invalid states are not connected as a "
                "physical curve"
            ),
            "overview_rendering": (
                "complete fixed-band argmax preview in red over the unchanged "
                "quality-gated formal series in blue; no state markers"
            ),
            "overview_time_reference": (
                "cross-profile consensus event candidate when available"
            ),
            "state_diagnostics_filename": (
                "apparent_velocity_state_diagnostics.png"
            ),
            "legend": QUALITY_UNFILTERED_PREVIEW_LABEL,
            "lower_bound_note": LOWER_BOUND_ARGMAX_NOTE,
            "plot_pre_event_value": (
                "assumed pre-event zero, display only"
                if configuration.plot.assume_pre_event_zero_for_display
                else "disabled"
            ),
            "status": QUALITY_UNFILTERED_PREVIEW_LABEL,
        },
        "analysis_display_frequency_range_hz": [
            configuration.plot.analysis_display_minimum_frequency_hz,
            configuration.plot.analysis_display_maximum_frequency_hz,
        ],
        "full_band_frequency_range_hz_by_channel": {
            name: [
                float(analysis.stft_result.frequency_hz[0]),
                float(analysis.stft_result.frequency_hz[-1]),
            ]
            for name, analysis in analyses.items()
        },
        "nyquist_frequency_hz_by_channel": {
            name: float(analysis.stft_result.sample_rate_hz / 2.0)
            for name, analysis in analyses.items()
        },
        "vacuum_wavelength_m": configuration.analysis.vacuum_wavelength_m,
        "velocity_correction": velocity_correction_metadata(
            next(iter(analyses.values())).velocity_correction_result
        ),
        "wavelength_status": (
            "demonstration value; not confirmed by experiment records"
        ),
        "analysis_start_time_s": (
            configuration.analysis.analysis_start_time_s
        ),
        "analysis_end_time_s": configuration.analysis.analysis_end_time_s,
        "manual_event_reference_time_s": (
            configuration.analysis.manual_event_reference_time_s
        ),
        "event_reference_source": "manual_review_reference_only",
        "quality": {
            "background_guard_window_scale": (
                configuration.quality.background_guard_window_scale
            ),
            "minimum_background_bin_count": (
                configuration.quality.minimum_background_bin_count
            ),
            "signal_detection": _detection_config_dict(
                configuration.quality.signal_detection
            ),
            "guard_status": (
                "configured descriptive diagnostic; not a universal validated standard"
            ),
        },
        "event_candidate": _event_candidate_config_dict(
            configuration.event_candidate
        ),
        "event_consensus_config": _event_consensus_config_dict(
            configuration.event_consensus
        ),
        "profile_consensus": _profile_consensus_dict(profile_consensus),
        "measured_semantics": (
            "MEASURED means spectrally qualified under the configured detection "
            "rules. It does not confirm the physical identity of the selected branch."
        ),
        "physical_branch_review_status": (
            PhysicalBranchReviewStatus.UNREVIEWED.value
        ),
        "source_path": str(configuration.input.path),
        "source_sha256": source_sha256,
        "analysis_runtime_s": runtime_s,
        "generated_files": generated_files,
        "channel_summaries": {
            name: dict(summary) for name, summary in channel_summaries.items()
        },
        "event_onset_diagnostics": {
            name: dict(diagnostic)
            for name, diagnostic in onset_diagnostics.items()
        },
        "detection_capability_by_channel": {
            name: {
                "window_duration_s": (
                    analysis.signal_detection_result.window_duration_s
                ),
                "hop_duration_s": (
                    analysis.signal_detection_result.hop_duration_s
                ),
                "minimum_resolvable_frequency_by_cycle_rule_hz": (
                    analysis.signal_detection_result
                    .minimum_resolvable_frequency_by_cycle_rule_hz
                ),
                "corresponding_apparent_velocity_m_s": (
                    analysis.signal_detection_result
                    .corresponding_apparent_velocity_m_s
                ),
                "detected_event_candidate_time_s": (
                    analysis.stream_event_candidates.primary_candidate_time_s
                ),
                "detected_event_candidate_source": (
                    "event_level_eligible_measured_segment"
                ),
                "legacy_task013_first_measured_run_time_s": (
                    analysis.signal_detection_result
                    .detected_event_candidate_time_s
                ),
            }
            for name, analysis in analyses.items()
        },
        "profile_consensus_candidate_time_s": (
            profile_consensus.profile_consensus_candidate_time_s
        ),
        "interpretation_guards": list(INTERPRETATION_GUARDS),
    }


def _run_manifest(
    output_directory: Path,
    *,
    configuration: WorkflowConfiguration,
    source_sha256: str,
    profile_manifests: Mapping[str, Mapping[str, Any]],
    profile_consensus_results: Mapping[str, ProfileConsensusResult],
    cross_profile_consensus: CrossProfileConsensusResult,
    threshold_calibration: ThresholdCalibrationResult,
    expected_paths: Sequence[Path],
) -> dict[str, Any]:
    return {
        "output_contract": "dual-profile-task013c-r-v1",
        "root_entries": list(
            _production_root_entries(configuration.analysis.profiles)
        ),
        "profiles": [
            profile.profile_id.value for profile in configuration.analysis.profiles
        ],
        "config_path": str(configuration.config_path),
        "source_path": str(configuration.input.path),
        "source_sha256": source_sha256,
        "input": {
            "time_column": configuration.input.time_column,
            "voltage_columns": dict(configuration.input.voltage_columns),
            "delimiter": configuration.input.delimiter,
            "has_header": configuration.input.has_header,
            "encoding": configuration.input.encoding,
            "time_scale": configuration.input.time_scale,
            "voltage_scales": dict(configuration.input.voltage_scales),
        },
        "analysis": {
            "analysis_start_time_s": (
                configuration.analysis.analysis_start_time_s
            ),
            "analysis_end_time_s": configuration.analysis.analysis_end_time_s,
            "manual_event_reference_time_s": (
                configuration.analysis.manual_event_reference_time_s
            ),
            "event_reference_source": "manual_review_reference_only",
            "vacuum_wavelength_m": configuration.analysis.vacuum_wavelength_m,
            "wavelength_status": (
                "demonstration value; not confirmed by experiment records"
            ),
        },
        "velocity_correction": dict(
            cast(
                "Mapping[str, Any]",
                next(iter(profile_manifests.values()))["velocity_correction"],
            )
        ),
        "quality": {
            "background_guard_window_scale": (
                configuration.quality.background_guard_window_scale
            ),
            "minimum_background_bin_count": (
                configuration.quality.minimum_background_bin_count
            ),
            "signal_detection": _detection_config_dict(
                configuration.quality.signal_detection
            ),
            "threshold_calibration": {
                "candidate_pairs_db": [
                    list(pair) for pair in THRESHOLD_CALIBRATION_CANDIDATES_DB
                ],
                "selected_peak_to_background_db": (
                    threshold_calibration.selected_peak_to_background_db
                ),
                "selected_peak_to_competitor_db": (
                    threshold_calibration.selected_peak_to_competitor_db
                ),
                "selection_status": threshold_calibration.selection_status,
                "baseline_consensus_event_time_s": (
                    threshold_calibration.baseline_consensus_event_time_s
                ),
                "selected_consensus_event_time_s": (
                    threshold_calibration.selected_consensus_event_time_s
                ),
                "candidate_summaries": [
                    dict(summary)
                    for summary in threshold_calibration.candidate_summaries
                ],
                "minimum_main_event_retention_fraction": (
                    MAIN_EVENT_MINIMUM_RETENTION_FRACTION
                ),
                "plateau_and_falling_definition": (
                    "first and second time halves of each baseline "
                    "consensus-supporting main segment"
                ),
                "pre_event_reference": (
                    "fixed 10/3 cross-profile consensus time so a candidate "
                    "cannot hide false peaks by shifting consensus"
                ),
                "provenance": THRESHOLD_CALIBRATION_PROVENANCE,
                "filename": (
                    f"comparisons/{THRESHOLD_CALIBRATION_FILENAME}"
                ),
            },
        },
        "event_candidate": _event_candidate_config_dict(
            configuration.event_candidate
        ),
        "event_consensus_config": _event_consensus_config_dict(
            configuration.event_consensus
        ),
        "profile_consensus_results": {
            name: _profile_consensus_dict(result)
            for name, result in profile_consensus_results.items()
        },
        "cross_profile_consensus": _cross_profile_consensus_dict(
            cross_profile_consensus
        ),
        "measured_semantics": (
            "MEASURED means spectrally qualified under the configured detection "
            "rules. It does not confirm the physical identity of the selected branch."
        ),
        "physical_branch_review_status": (
            PhysicalBranchReviewStatus.UNREVIEWED.value
        ),
        "plot": {
            "relative_db_floor": configuration.plot.relative_db_floor,
            "analysis_display_minimum_frequency_hz": (
                configuration.plot.analysis_display_minimum_frequency_hz
            ),
            "analysis_display_maximum_frequency_hz": (
                configuration.plot.analysis_display_maximum_frequency_hz
            ),
            "event_detail_before_s": configuration.plot.event_detail_before_s,
            "event_detail_after_s": configuration.plot.event_detail_after_s,
            "assume_pre_event_zero_for_display": (
                configuration.plot.assume_pre_event_zero_for_display
            ),
            "reviewed_display": {
                "formal_array_modified": False,
                "same_array_as_simple_export": True,
                "pre_consensus_zero_semantics": (
                    "all frames are zero by plotting convention"
                ),
                "post_consensus_semantics": (
                    "formal corrected velocity with original NaN gaps"
                ),
                "interpolation_or_bridge": False,
            },
        },
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "dps-studio": _package_version(),
        },
        "git_head": _git_output("rev-parse", "HEAD"),
        "git_worktree_dirty": bool(_git_output("status", "--porcelain")),
        "generated_files": [
            str(path.relative_to(output_directory)).replace("\\", "/")
            for path in expected_paths
        ],
        "simple_exports": {
            "columns": ["time_s", "corrected_velocity_m_s"],
            "filename_pattern": "<profile>__<channel>__velocity_time.csv",
            "time_semantics": "absolute STFT frame-center time in seconds",
            "velocity_semantics": (
                "pre-consensus plotting zero, followed by unchanged formal "
                "quality-gated angle- and window-corrected velocity in m/s"
            ),
            "all_stft_frames_retained": True,
            "post_consensus_unreliable_frames_remain_nan": True,
            "display_or_preview_values_used": False,
            "pre_consensus_zero_fill": "unconditional for every frame",
            "consensus_unavailable_fallback": (
                "formal array unchanged; manual reference is not substituted"
            ),
            "zero_fill_is_measurement": False,
            "zero_fill_requirements": [
                "time_s < cross-profile consensus event candidate time",
            ],
            "interpolation_or_smoothing": False,
            "formal_diagnostics_modified": False,
        },
        "detailed_diagnostic_csv_filenames": list(
            DETAILED_DIAGNOSTIC_FILENAMES
        ),
        "profile_manifests": {
            name: dict(manifest) for name, manifest in profile_manifests.items()
        },
        "interpretation_guards": list(INTERPRETATION_GUARDS),
    }


def _profile_dict(profile: AnalysisProfile) -> dict[str, Any]:
    return {
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
    }


def _detection_config_dict(
    config: SignalDetectionConfig,
) -> dict[str, Any]:
    return {
        "minimum_peak_to_background_db": (
            config.minimum_peak_to_background_db
        ),
        "minimum_peak_to_competitor_db": (
            config.minimum_peak_to_competitor_db
        ),
        "peak_exclusion_half_width_bins": (
            config.peak_exclusion_half_width_bins
        ),
        "minimum_consecutive_frames": config.minimum_consecutive_frames,
        "minimum_cycles_in_window": config.minimum_cycles_in_window,
        "enabled": config.enabled,
        "default_status": SignalDetectionConfig.DEFAULT_STATUS,
    }


def _event_candidate_config_dict(
    config: EventCandidateConfig,
) -> dict[str, Any]:
    return {
        "minimum_segment_frames": config.minimum_segment_frames,
        "minimum_segment_duration_s": config.minimum_segment_duration_s,
        "duration_definition": (
            "last STFT frame center minus first STFT frame center"
        ),
        "maximum_adjacent_frequency_step_hz": (
            config.maximum_adjacent_frequency_step_hz
        ),
        "minimum_median_peak_to_background_db": (
            config.minimum_median_peak_to_background_db
        ),
        "minimum_median_peak_to_competitor_db": (
            config.minimum_median_peak_to_competitor_db
        ),
        "default_status": EventCandidateConfig.DEFAULT_STATUS,
        "formal_per_frame_arrays_modified": False,
    }


def _event_consensus_config_dict(
    config: EventConsensusConfig,
) -> dict[str, Any]:
    return {
        "channel_start_time_tolerance_s": (
            config.channel_start_time_tolerance_s
        ),
        "minimum_interval_overlap_fraction": (
            config.minimum_interval_overlap_fraction
        ),
        "channel_start_frequency_tolerance_hz": (
            config.channel_start_frequency_tolerance_hz
        ),
        "frequency_agreement_metric": (
            "absolute difference between supporting segment start-frame "
            "refined frequencies"
        ),
        "cross_profile_time_tolerance_s": (
            config.cross_profile_time_tolerance_s
        ),
        "default_status": EventConsensusConfig.DEFAULT_STATUS,
        "manual_reference_used_for_selection": False,
        "voltage_or_velocity_fusion": False,
    }


def _profile_consensus_dict(
    result: ProfileConsensusResult,
) -> dict[str, Any]:
    return {
        "profile_name": result.profile_name,
        "profile_consensus_candidate_time_s": (
            result.profile_consensus_candidate_time_s
        ),
        "profile_consensus_status": result.profile_consensus_status.value,
        "supporting_channel_segments": [
            {
                "profile_name": item.profile_name,
                "channel_name": item.channel_name,
                "segment_id": item.segment_id,
                "start_time_s": item.start_time_s,
                "end_time_s": item.end_time_s,
            }
            for item in result.supporting_channel_segments
        ],
        "channel_start_time_difference_s": (
            result.channel_start_time_difference_s
        ),
        "interval_overlap_fraction": result.interval_overlap_fraction,
        "frequency_agreement_metric_hz": (
            result.frequency_agreement_metric_hz
        ),
        "rejection_reason": result.rejection_reason,
        "candidate_time_method": result.candidate_time_method,
    }


def _cross_profile_consensus_dict(
    result: CrossProfileConsensusResult,
) -> dict[str, Any]:
    return {
        "consensus_event_candidate_time_s": (
            result.consensus_event_candidate_time_s
        ),
        "consensus_event_status": result.consensus_event_status.value,
        "supporting_profiles": list(result.supporting_profiles),
        "supporting_channels": list(result.supporting_channels),
        "candidate_time_spread_s": result.candidate_time_spread_s,
        "reference_time_difference_s": result.reference_time_difference_s,
        "reference_time_role": "diagnostic only; never used for selection",
        "rejection_reason": result.rejection_reason,
        "candidate_time_method": result.candidate_time_method,
    }


def _expected_paths(
    output_directory: Path,
    profiles: Sequence[AnalysisProfile],
    *,
    channel_names: Sequence[str],
) -> list[Path]:
    paths: list[Path] = []
    for profile in profiles:
        paths.extend(
            _expected_profile_paths(
                output_directory / profile.profile_id.value,
                channel_names=channel_names,
            )
        )
    paths.extend(
        output_directory / filename
        for filename in (
            "README.txt",
            "event_consensus.json",
            "run.log",
            "run_manifest.json",
        )
    )
    paths.extend(
        output_directory / "comparisons" / filename
        for filename in COMPARISON_FILENAMES
    )
    paths.append(
        output_directory / "simple_exports" / SIMPLE_EXPORT_README_FILENAME
    )
    paths.extend(
        output_directory
        / "simple_exports"
        / _simple_export_filename(profile.profile_id.value, channel_name)
        for profile in profiles
        for channel_name in channel_names
    )
    return paths


def _expected_profile_paths(
    profile_directory: Path,
    *,
    channel_names: Sequence[str],
) -> list[Path]:
    paths = [
        profile_directory / channel_name / filename
        for channel_name in channel_names
        for filename in CHANNEL_FILENAMES
    ]
    paths.extend(profile_directory / filename for filename in PROFILE_FILENAMES)
    return paths


def _validate_output_contract(
    output_directory: Path,
    expected_paths: Sequence[Path],
    *,
    profiles: Sequence[AnalysisProfile],
    channel_names: Sequence[str],
) -> None:
    actual_root_entries = {path.name for path in output_directory.iterdir()}
    if actual_root_entries != set(_production_root_entries(profiles)):
        raise RuntimeError("Production root entries differ from the explicit contract.")
    actual_files = {path for path in output_directory.rglob("*") if path.is_file()}
    if actual_files != set(expected_paths):
        raise RuntimeError("Production file tree differs from the explicit contract.")
    profile_names = tuple(profile.profile_id.value for profile in profiles)
    for profile_name in profile_names:
        profile_directory = output_directory / profile_name
        actual_profile_entries = tuple(
            sorted(path.name for path in profile_directory.iterdir())
        )
        expected_profile_entries = (*channel_names, *PROFILE_FILENAMES)
        if actual_profile_entries != tuple(sorted(expected_profile_entries)):
            raise RuntimeError(f"{profile_name} entries differ from the contract.")
        for channel_name in channel_names:
            channel_directory = profile_directory / channel_name
            actual_channel_files = tuple(
                sorted(path.name for path in channel_directory.iterdir())
            )
            if actual_channel_files != tuple(sorted(CHANNEL_FILENAMES)):
                raise RuntimeError(
                    f"{profile_name}/{channel_name} differs from the contract."
                )


def _production_root_entries(
    profiles: Sequence[AnalysisProfile],
) -> tuple[str, ...]:
    return (
        *(profile.profile_id.value for profile in profiles),
        *PRODUCTION_SUPPORT_ROOT_ENTRIES,
    )


def _relative_stft_magnitude_db(
    magnitude: np.ndarray[Any, Any],
    *,
    floor_db: float,
) -> np.ndarray[Any, np.dtype[np.float64]]:
    maximum = float(np.max(magnitude))
    if not np.isfinite(maximum) or maximum <= 0.0:
        raise ValueError("STFT magnitude reference must be finite and positive.")
    if not np.isfinite(floor_db) or floor_db >= 0.0:
        raise ValueError("STFT display floor must be finite and negative.")
    display_floor = maximum * float(np.power(10.0, floor_db / 20.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        return 20.0 * np.log10(np.maximum(magnitude, display_floor) / maximum)


def _save_figure(figure: Any, path: Path) -> None:
    with matplotlib.rc_context({"path.simplify": False}):
        figure.savefig(path, dpi=220)
    plt.close(figure)


def _array_value(values: np.ndarray[Any, Any], index: int | None) -> float | None:
    if index is None:
        return None
    value = float(values[index])
    return value if np.isfinite(value) else None


def _relative_time_s(
    values: np.ndarray[Any, Any],
    reference_time_s: float | None,
) -> np.ndarray[Any, np.dtype[np.float64]]:
    if reference_time_s is None:
        return np.full(values.shape, np.nan, dtype=np.float64)
    return np.asarray(values - reference_time_s, dtype=np.float64)


def _plot_time_us(
    values: np.ndarray[Any, Any],
    reference_time_s: float | None,
) -> np.ndarray[Any, np.dtype[np.float64]]:
    if values.size == 0:
        return np.asarray([], dtype=np.float64)
    reference = float(values[0]) if reference_time_s is None else reference_time_s
    return np.asarray((values - reference) * 1.0e6, dtype=np.float64)


def _plot_scalar_time_us(
    value_s: float,
    reference_time_s: float | None,
) -> float:
    reference = 0.0 if reference_time_s is None else reference_time_s
    return (value_s - reference) * 1.0e6


def _time_axis_label(reference_time_s: float | None) -> str:
    if reference_time_s is None:
        return "Time from first STFT frame (µs)"
    return "Time relative to manual event reference (µs)"


def _consensus_time_axis_label(reference_time_s: float | None) -> str:
    if reference_time_s is None:
        return "Time from first STFT frame; consensus unavailable (µs)"
    return "Time relative to cross-profile consensus event candidate (µs)"


def _segment_frame_metadata(
    analysis: ChannelAnalysis,
) -> tuple[list[str], list[bool | None], list[str]]:
    frame_count = analysis.signal_detection_result.time_s.size
    segment_ids = [""] * frame_count
    eligible: list[bool | None] = [None] * frame_count
    reasons = [""] * frame_count
    for assessment in analysis.stream_event_candidates.segment_assessments:
        segment = assessment.segment
        reason_text = "|".join(
            reason.value for reason in assessment.rejection_reasons
        )
        for index in range(
            segment.start_frame_index,
            segment.end_frame_index + 1,
        ):
            segment_ids[index] = segment.segment_id
            eligible[index] = assessment.candidate_eligible
            reasons[index] = reason_text
    return segment_ids, eligible, reasons


def _minimum_at_indices(
    values: np.ndarray[Any, Any],
    indices: np.ndarray[Any, np.dtype[np.int64]],
) -> float | None:
    return float(np.min(values[indices])) if indices.size else None


def _finite_percentile(values: np.ndarray[Any, Any], percentile: float) -> float | None:
    finite = values[np.isfinite(values)]
    return float(np.percentile(finite, percentile)) if finite.size else None


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


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
    "CHANNEL_FILENAMES",
    "CHANNEL_PLOT_FILENAMES",
    "COMPARISON_FILENAMES",
    "DETAILED_DIAGNOSTIC_FILENAMES",
    "INTERPRETATION_GUARDS",
    "LOWER_BOUND_ARGMAX_NOTE",
    "PRODUCTION_SUPPORT_ROOT_ENTRIES",
    "PROFILE_FILENAMES",
    "QUALITY_UNFILTERED_PREVIEW_LABEL",
    "run_production_outputs",
]
