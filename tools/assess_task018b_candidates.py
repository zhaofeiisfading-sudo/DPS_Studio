"""Generate TASK-018B read-only candidate/reselection A/B artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
import matplotlib
import numpy as np

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

from assess_task018a_continuity import (  # noqa: E402
    _analyze_source,
    _load_baseline_summary,
    _regression_row,
    _sha256,
)
from dps_studio.core.export import (  # noqa: E402
    ResultAnalysisMode,
    ResultExportOptions,
    export_formal_results,
)
from dps_studio.core.ridge import (  # noqa: E402
    ContinuityReselectionConfig,
    LocalPeakCandidateConfig,
    RidgeContinuityStatus,
    extract_local_peak_candidates,
    reselect_isolated_jump_candidates,
)
from dps_studio.core.workflow import (  # noqa: E402
    ChannelAnalysis,
    WorkflowConfiguration,
    load_workflow_config,
)


def _write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows are available for {path.name}.")
    with path.open("x", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _candidate_rows(
    source: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
) -> list[dict[str, object]]:
    candidates = analysis.local_peak_candidates
    reselection = analysis.experimental_reselection_result
    if candidates is None or reselection is None:
        raise RuntimeError("Automatic analysis did not retain TASK-018B diagnostics.")
    rows: list[dict[str, object]] = []
    for frame_index, frame_candidates in enumerate(candidates.candidates_by_frame):
        evidence_by_rank = {
            item.candidate_rank: item
            for item in reselection.evidence_by_frame[frame_index]
        }
        legacy_bin = int(analysis.refined_result.discrete_frequency_bin_index[frame_index])
        for candidate in frame_candidates:
            evidence = evidence_by_rank[candidate.amplitude_rank]
            rows.append(
                {
                    "source": source.name,
                    "channel": channel_name,
                    "frame_index": frame_index,
                    "time_s": float(candidates.time_s[frame_index]),
                    "candidate_rank": candidate.amplitude_rank,
                    "candidate_bin_index": candidate.bin_index,
                    "candidate_discrete_frequency_hz": candidate.discrete_frequency_hz,
                    "candidate_refined_frequency_hz": candidate.refined_frequency_hz,
                    "candidate_refinement_status": candidate.refinement_status.value,
                    "candidate_magnitude": candidate.magnitude,
                    "candidate_background_median_magnitude": (
                        candidate.background_median_magnitude
                    ),
                    "candidate_strongest_competitor_magnitude": (
                        candidate.strongest_competitor_magnitude
                    ),
                    "candidate_peak_to_background_db": (
                        candidate.peak_to_background_db
                    ),
                    "candidate_peak_to_competitor_db": (
                        candidate.peak_to_competitor_db
                    ),
                    "candidate_spectral_quality_status": (
                        candidate.spectral_quality_status.value
                    ),
                    "distance_to_previous_hz": evidence.distance_to_previous_hz,
                    "distance_to_next_hz": evidence.distance_to_next_hz,
                    "neighbor_recovery_hz": evidence.neighbor_recovery_hz,
                    "event_transition": evidence.event_transition,
                    "legacy_selected": candidate.bin_index == legacy_bin,
                    "experimental_selected": evidence.experimental_selected,
                    "reselection_reason": evidence.reselection_reason.value,
                }
            )
    return rows


def _reselection_rows(
    source: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
) -> list[dict[str, object]]:
    result = analysis.experimental_reselection_result
    if result is None:
        raise RuntimeError("Automatic analysis did not retain reselection diagnostics.")
    return [
        {
            "source": source.name,
            "channel": channel_name,
            "frame_index": frame_index,
            "time_s": float(result.time_s[frame_index]),
            "legacy_continuity_status": (
                analysis.event_aware_continuity_result.statuses[frame_index].value
            ),
            "reselection_frame_status": result.frame_statuses[frame_index].value,
            "legacy_frequency_hz": float(result.legacy_frequency_hz[frame_index]),
            "experimental_frequency_hz": float(
                result.experimental_frequency_hz[frame_index]
            ),
            "experimental_reselected": (
                frame_index in result.reselected_frame_indices
            ),
            "legacy_nan": bool(math.isnan(result.legacy_frequency_hz[frame_index])),
            "experimental_nan": bool(
                math.isnan(result.experimental_frequency_hz[frame_index])
            ),
        }
        for frame_index in range(result.time_s.size)
    ]


def _event_row(
    source: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
) -> dict[str, object]:
    compatibility_s = (
        analysis.signal_detection_result.detected_event_candidate_time_s
    )
    primary_s = analysis.stream_event_candidates.primary_candidate_time_s
    return {
        "source": source.name,
        "channel": channel_name,
        "compatibility_event_candidate_time_s": compatibility_s,
        "primary_event_candidate_time_s": primary_s,
        "primary_minus_compatibility_s": (
            None
            if compatibility_s is None or primary_s is None
            else primary_s - compatibility_s
        ),
        "compatibility_event_candidate_time_us_display_only": (
            None if compatibility_s is None else compatibility_s * 1.0e6
        ),
        "primary_event_candidate_time_us_display_only": (
            None if primary_s is None else primary_s * 1.0e6
        ),
        "gui_default_candidate_source": "event_level_primary",
        "compatibility_is_gui_default": False,
    }


def _k_assessment(
    analysis: ChannelAnalysis,
    maximum_candidates: int,
) -> dict[str, object]:
    quality = analysis.spectral_quality_result
    candidates = extract_local_peak_candidates(
        analysis.stft_result,
        minimum_frequency_hz=analysis.ridge_result.minimum_frequency_hz,
        maximum_frequency_hz=analysis.ridge_result.maximum_frequency_hz,
        background_exclusion_half_width_hz=(
            quality.background_exclusion_half_width_hz
        ),
        minimum_background_bin_count=quality.minimum_background_bin_count,
        config=LocalPeakCandidateConfig(maximum_candidates),
    )
    result = reselect_isolated_jump_candidates(
        analysis.refined_result,
        candidates,
        analysis.event_aware_continuity_result,
        config=ContinuityReselectionConfig(),
    )
    isolated = [
        index
        for index, status in enumerate(
            analysis.event_aware_continuity_result.statuses
        )
        if status is RidgeContinuityStatus.ISOLATED_JUMP
    ]
    return {
        "maximum_candidates_per_frame": maximum_candidates,
        "isolated_jump_frames": isolated,
        "isolated_frames_with_alternative": [
            index
            for index in isolated
            if len(candidates.candidates_by_frame[index]) > 1
        ],
        "reselected_frames": list(result.reselected_frame_indices),
    }


def _json_number(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def _focus_record(analysis: ChannelAnalysis, frame_index: int) -> dict[str, object]:
    candidates = analysis.local_peak_candidates
    result = analysis.experimental_reselection_result
    if candidates is None or result is None:
        raise RuntimeError("TASK-018B diagnostics are unavailable.")
    return {
        "source": "20260630-1.csv",
        "channel": "pdv_channel_2",
        "frame_index": frame_index,
        "time_s": float(analysis.stft_result.time_s[frame_index]),
        "legacy_previous_frequency_hz": _json_number(
            analysis.refined_result.refined_frequency_hz[frame_index - 1]
        ),
        "legacy_frequency_hz": _json_number(
            analysis.refined_result.refined_frequency_hz[frame_index]
        ),
        "legacy_next_frequency_hz": _json_number(
            analysis.refined_result.refined_frequency_hz[frame_index + 1]
        ),
        "experimental_frequency_hz": _json_number(
            result.experimental_frequency_hz[frame_index]
        ),
        "experimental_reselected": frame_index in result.reselected_frame_indices,
        "candidates": [
            {
                "rank": candidate.amplitude_rank,
                "bin_index": candidate.bin_index,
                "discrete_frequency_hz": candidate.discrete_frequency_hz,
                "refined_frequency_hz": _json_number(
                    candidate.refined_frequency_hz
                ),
                "refinement_status": candidate.refinement_status.value,
                "magnitude": candidate.magnitude,
                "peak_to_background_db": _json_number(
                    candidate.peak_to_background_db
                ),
                "peak_to_competitor_db": _json_number(
                    candidate.peak_to_competitor_db
                ),
                "spectral_quality_status": (
                    candidate.spectral_quality_status.value
                ),
                "evidence": {
                    "distance_to_previous_hz": _json_number(
                        result.evidence_by_frame[frame_index][
                            candidate.amplitude_rank - 1
                        ].distance_to_previous_hz
                    ),
                    "distance_to_next_hz": _json_number(
                        result.evidence_by_frame[frame_index][
                            candidate.amplitude_rank - 1
                        ].distance_to_next_hz
                    ),
                    "reason": result.evidence_by_frame[frame_index][
                        candidate.amplitude_rank - 1
                    ].reselection_reason.value,
                    "selected": result.evidence_by_frame[frame_index][
                        candidate.amplitude_rank - 1
                    ].experimental_selected,
                },
            }
            for candidate in candidates.candidates_by_frame[frame_index]
        ],
    }


def _plot_reselection(
    source: Path,
    channel_name: str,
    analysis: ChannelAnalysis,
    frame_index: int,
    output_path: Path,
) -> None:
    candidates = analysis.local_peak_candidates
    result = analysis.experimental_reselection_result
    if candidates is None or result is None:
        raise RuntimeError("TASK-018B diagnostics are unavailable for plotting.")
    stft = analysis.stft_result
    band = (stft.frequency_hz >= analysis.ridge_result.minimum_frequency_hz) & (
        stft.frequency_hz <= analysis.ridge_result.maximum_frequency_hz
    )
    magnitude = np.abs(stft.spectrum[band])
    positive = magnitude[magnitude > 0.0]
    floor = float(np.min(positive)) if positive.size else np.finfo(np.float64).tiny
    relative_db = 20.0 * np.log10(np.maximum(magnitude, floor))
    relative_db -= float(np.max(relative_db))
    time_us = stft.time_s * 1.0e6
    frequency_mhz = stft.frequency_hz[band] * 1.0e-6
    figure, axes = plt.subplots(2, 1, figsize=(13.0, 9.0), constrained_layout=True)
    for axis in axes:
        mesh = axis.pcolormesh(
            time_us,
            frequency_mhz,
            relative_db,
            shading="auto",
            cmap="viridis",
            vmin=-60.0,
            vmax=0.0,
        )
        axis.plot(
            time_us,
            result.legacy_frequency_hz * 1.0e-6,
            color="white",
            linewidth=1.0,
            label="legacy refined ridge",
        )
        axis.plot(
            time_us,
            result.experimental_frequency_hz * 1.0e-6,
            color="cyan",
            linewidth=1.1,
            linestyle="--",
            label="experimental continuity-assisted ridge",
        )
        for rank in range(1, candidates.config.maximum_candidates_per_frame + 1):
            points = [
                (index, candidate)
                for index, frame in enumerate(candidates.candidates_by_frame)
                for candidate in frame
                if candidate.amplitude_rank == rank
                and math.isfinite(candidate.refined_frequency_hz)
            ]
            if points:
                axis.scatter(
                    [time_us[index] for index, _ in points],
                    [candidate.refined_frequency_hz * 1.0e-6 for _, candidate in points],
                    s=5.0,
                    alpha=0.35,
                    label=f"local candidate rank {rank}",
                )
        event_s = analysis.event_aware_continuity_result.event_reference_time_s
        if event_s is not None:
            axis.axvline(
                event_s * 1.0e6,
                color="magenta",
                linewidth=1.1,
                linestyle=":",
                label="event reference/candidate",
            )
        axis.scatter(
            [time_us[frame_index]],
            [result.experimental_frequency_hz[frame_index] * 1.0e-6],
            color="red",
            marker="x",
            s=70.0,
            linewidth=1.8,
            label=f"reselected frame {frame_index}",
        )
        axis.set_ylabel("frequency (MHz)")
    figure.colorbar(mesh, ax=axes, label="relative magnitude (dB)")
    axes[0].set_title(f"{source.name} — {channel_name} — full A/B")
    left = max(0, frame_index - 8)
    right = min(time_us.size - 1, frame_index + 8)
    local_candidates = candidates.candidates_by_frame[frame_index]
    local_frequency = [
        result.legacy_frequency_hz[frame_index - 1],
        result.legacy_frequency_hz[frame_index],
        result.legacy_frequency_hz[frame_index + 1],
        *(candidate.refined_frequency_hz for candidate in local_candidates),
    ]
    finite_local = np.asarray(local_frequency)[np.isfinite(local_frequency)] * 1.0e-6
    axes[1].set_xlim(time_us[left], time_us[right])
    axes[1].set_ylim(float(np.min(finite_local) - 50.0), float(np.max(finite_local) + 50.0))
    axes[1].set_title("local frame zoom (no smoothing or interpolation)")
    axes[1].set_xlabel("absolute time (µs)")
    handles, labels = axes[0].get_legend_handles_labels()
    unique = dict(zip(labels, handles, strict=True))
    axes[0].legend(unique.values(), unique.keys(), loc="upper right", fontsize="x-small")
    figure.savefig(output_path, dpi=170)
    plt.close(figure)


def _formal_export(
    output_directory: Path,
    source: Path,
    analysis: ChannelAnalysis,
    configuration: WorkflowConfiguration,
) -> dict[str, object]:
    output_directory.mkdir()
    reference_s = analysis.signal_detection_result.manual_event_reference_time_s
    report = export_formal_results(
        ResultExportOptions(
            output_directory=output_directory,
            analysis_mode=ResultAnalysisMode.AUTOMATIC,
            channel_analyses={"pdv_channel_1": analysis},
            source_path=source,
            analysis_profile_name=(
                configuration.analysis.default_profile.profile_id.value
            ),
            pre_event_display_enabled=(
                configuration.plot.assume_pre_event_zero_for_display
            ),
            pre_event_display_velocity_m_s=(
                configuration.plot.pre_event_display_velocity_m_s
            ),
            event_reference_source=(
                "configuration" if reference_s is not None else None
            ),
            protected_output_directories=(source.parent,),
        )
    )
    exported = report.exported_channels[0]
    files = sorted(path.name for path in output_directory.iterdir() if path.is_file())
    metadata = json.loads(exported.metadata_path.read_text(encoding="utf-8"))
    expected_fields = {
        "automatic_event_candidate_time_s",
        "compatibility_event_candidate_time_s",
        "event_reference_time_s",
        "event_reference_source",
    }
    if len(files) != 3 or len(list(output_directory.glob("*.metadata.json"))) != 1:
        raise RuntimeError("Formal TASK-018B export did not contain exactly three files.")
    if not expected_fields.issubset(metadata):
        raise RuntimeError("Formal metadata is missing TASK-018B event fields.")
    if metadata["automatic_event_candidate_time_s"] != (
        analysis.stream_event_candidates.primary_candidate_time_s
    ):
        raise RuntimeError("Exported automatic candidate does not match the model.")
    return {
        "directory": str(output_directory),
        "files": files,
        "file_count": len(files),
        "metadata_json_count": len(list(output_directory.glob("*.metadata.json"))),
        "metadata_event_fields": {
            field: metadata[field] for field in sorted(expected_fields)
        },
        "schema": metadata["export_schema_version"],
        "preserved_top_level_fields": sorted(metadata),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=Path("artifacts/task018b/assessment"),
    )
    parser.add_argument(
        "--baseline-directory",
        type=Path,
        default=Path("artifacts/task018a/baseline"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repository_root = Path(__file__).resolve().parents[1]
    output_directory = (repository_root / arguments.output_directory).resolve()
    baseline_directory = (repository_root / arguments.baseline_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=False)
    figure_directory = output_directory / "figures"
    figure_directory.mkdir()
    raw_directory = repository_root / "data" / "raw"
    sources = sorted(raw_directory.glob("*.csv"))
    configuration = load_workflow_config(
        repository_root / "configs" / "pdv_studio_defaults.toml",
        repository_root=repository_root,
    )
    baseline_summary = _load_baseline_summary(baseline_directory / "summary.json")
    raw_files = sorted(path for path in raw_directory.iterdir() if path.is_file())
    raw_hashes_before = {path.name: _sha256(path) for path in raw_files}
    candidate_rows: list[dict[str, object]] = []
    reselection_rows: list[dict[str, object]] = []
    event_rows: list[dict[str, object]] = []
    regression_rows: list[dict[str, object]] = []
    k_rows: list[dict[str, object]] = []
    reselected: list[dict[str, object]] = []
    focus: dict[str, object] | None = None
    formal_export: dict[str, object] | None = None

    for source in sources:
        analyses, _range_source, _start_s, _end_s, _reference_s = _analyze_source(
            source,
            configuration,
        )
        for channel_name, analysis in analyses.items():
            candidate_rows.extend(_candidate_rows(source, channel_name, analysis))
            reselection_rows.extend(_reselection_rows(source, channel_name, analysis))
            event_rows.append(_event_row(source, channel_name, analysis))
            regression_rows.append(
                _regression_row(
                    source,
                    channel_name,
                    analysis,
                    baseline_directory,
                    baseline_summary,
                )
            )
            for maximum_candidates in (2, 3, 5):
                k_rows.append(
                    {
                        "source": source.name,
                        "channel": channel_name,
                        **_k_assessment(analysis, maximum_candidates),
                    }
                )
            result = analysis.experimental_reselection_result
            if result is None:
                raise RuntimeError("Automatic experimental result is absent.")
            for frame_index in result.reselected_frame_indices:
                record = {
                    "source": source.name,
                    "channel": channel_name,
                    "frame_index": frame_index,
                    "time_s": float(result.time_s[frame_index]),
                    "legacy_frequency_hz": float(
                        result.legacy_frequency_hz[frame_index]
                    ),
                    "experimental_frequency_hz": float(
                        result.experimental_frequency_hz[frame_index]
                    ),
                }
                reselected.append(record)
                _plot_reselection(
                    source,
                    channel_name,
                    analysis,
                    frame_index,
                    figure_directory
                    / f"{source.stem}__{channel_name}__frame_{frame_index}.png",
                )
            if source.name == "20260630-1.csv" and channel_name == "pdv_channel_2":
                focus = _focus_record(analysis, 1015)
            if source.name == "20260701.csv" and channel_name == "pdv_channel_1":
                formal_export = _formal_export(
                    output_directory / "formal_export",
                    source,
                    analysis,
                    configuration,
                )

    raw_hashes_after = {path.name: _sha256(path) for path in raw_files}
    if raw_hashes_after != raw_hashes_before:
        raise RuntimeError("A data/raw SHA-256 changed during TASK-018B assessment.")
    if focus is None or formal_export is None:
        raise RuntimeError("Required focus case or formal export was not produced.")
    _write_csv(output_directory / "candidate_assessment.csv", candidate_rows)
    _write_csv(output_directory / "reselection_assessment.csv", reselection_rows)
    _write_csv(output_directory / "event_candidate_comparison.csv", event_rows)
    manifest = {
        "sources": [source.name for source in sources],
        "source_count": len(sources),
        "channel_assessment_count": len(event_rows),
        "candidate_configuration": {
            "selected_maximum_candidates_per_frame": 3,
            "evaluated_values": [2, 3, 5],
            "selection_reason": (
                "K=2, K=3, and K=5 found the same sole eligible reselection; "
                "K=3 preserves one additional diagnostic peak without K=5 noise tails."
            ),
        },
        "reselection_configuration": {
            "minimum_peak_to_background_db": 6.0,
            "minimum_peak_to_competitor_db": -6.0,
            "maximum_neighbor_distance_source": (
                "EventAwareContinuityConfig.neighbor_recovery_tolerance_hz"
            ),
            "production_enabled": False,
        },
        "k_assessment": k_rows,
        "focus_case": focus,
        "experimental_reselection_count": len(reselected),
        "experimental_reselections": reselected,
        "production_regression": regression_rows,
        "all_production_results_unchanged": all(
            bool(row["all_formal_results_unchanged"])
            for row in regression_rows
        ),
        "guided_candidate_system_enabled": False,
        "formal_export": formal_export,
        "raw_sha256_before": raw_hashes_before,
        "raw_sha256_after": raw_hashes_after,
        "raw_unchanged": True,
    }
    (output_directory / "assessment.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
