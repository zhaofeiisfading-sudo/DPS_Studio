"""Headless command line entry point for PDV Studio Production."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio import __version__
from dps_studio.cli_config import (
    OPTIONAL_ANALYSIS_PARAMETERS,
    REQUIRED_EXPERIMENT_PARAMETERS,
    TIME_SCALES,
    VOLTAGE_SCALES,
    Experiment,
    analysis_overrides,
    delimiter_value,
    optional_bool,
    optional_number,
    optional_text,
    read_config,
    read_experiment,
)
from dps_studio.core.analysis_profiles import AnalysisRunParameters, build_analysis_run_parameters
from dps_studio.core.export import (
    ExportTimeOrigin,
    ResultAnalysisMode,
    ResultBundleOptions,
    ResultBundleReport,
    ResultExportError,
    export_result_bundle,
)
from dps_studio.core.io.delimited import read_delimited_signals
from dps_studio.core.io.delimited_preview import (
    DelimitedFilePreview,
    DelimitedPreviewError,
    preview_delimited_file,
)
from dps_studio.core.models.exceptions import DPSStudioError
from dps_studio.core.quality import SignalState
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import (
    ChannelAnalysis,
    WorkflowConfiguration,
    analyze_stft_results,
    compute_configuration_stfts,
    configure_channel_event_reference,
    load_workflow_config,
)
from dps_studio.runtime_paths import (
    RuntimeStorageError,
    application_resource_path,
    application_resource_root,
    initialize_runtime_storage,
    installation_root,
    package_resource_path,
    userdata_root,
)

_COMMAND_ERRORS = (DPSStudioError, ResultExportError, OSError, ValueError, LookupError, OverflowError)
_LOW_FREQ_RETRY_STEPS_HZ = (0.20e9, 0.35e9, 0.50e9)
_EXPECTED_SAMPLE_RATE_MIN_HZ = 1.0e8
_EXPECTED_SAMPLE_RATE_MAX_HZ = 1.0e12


def _parser() -> argparse.ArgumentParser:
    invoked_as = Path(sys.argv[0]).stem
    program = invoked_as if invoked_as in {"pdv", "dps-studio"} else "dps-studio"
    parser = argparse.ArgumentParser(prog=program, description="Headless PDV signal analysis.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    inspect = commands.add_parser("inspect", help="Preview a delimited input file.")
    inspect.add_argument("input_file", type=Path)
    inspect.add_argument("--delimiter", help="Delimiter character, tab, or whitespace.")
    inspect.add_argument("--encoding", default="utf-8")
    inspect.add_argument("--max-rows", type=int, default=4)
    inspect.add_argument("--out", type=Path, help="Also save the preview as JSON.")

    analyze = commands.add_parser("analyze", help="Analyze one file and export 5-file bundle.")
    analyze.add_argument("input_file", type=Path)
    analyze.add_argument("--config", type=Path, help="Experimental parameters in JSON or TOML.")
    analyze.add_argument("--out", type=Path, required=True, help="Result bundle directory.")
    experiment = analyze.add_argument_group("experimental parameters (required in config or CLI)")
    experiment.add_argument("--time-column", type=int, help="Zero-based time column index.")
    experiment.add_argument("--time-unit", choices=TIME_SCALES)
    experiment.add_argument("--voltage-columns", help="Column index or channel=index pairs.")
    experiment.add_argument("--voltage-units", help="V, mV, or channel=unit pairs.")
    experiment.add_argument("--wavelength-m", dest="vacuum_wavelength_m", type=float)
    experiment.add_argument("--angle-deg", dest="measurement_angle_deg", type=float)
    experiment.add_argument("--window-material", help="LiF, none, or a saved window preset.")
    analyze.add_argument(
        "--auto-columns",
        action="store_true",
        default=None,
        help="Auto-detect delimiter, header, col 0 time, and 1-3 voltage columns (cols 1..N).",
    )
    analyze.add_argument("--delimiter", help="Delimiter character, tab, or whitespace.")
    analyze.add_argument("--encoding")
    header = analyze.add_mutually_exclusive_group()
    header.add_argument("--has-header", action="store_true", default=None)
    header.add_argument("--no-header", dest="has_header", action="store_false")
    analyze.add_argument("--profile", help="Configured STFT profile (default: balanced).")
    analyze.add_argument("--start-time-s", dest="analysis_start_time_s", type=float)
    analyze.add_argument("--end-time-s", dest="analysis_end_time_s", type=float)
    analyze.add_argument("--min-freq-hz", dest="minimum_frequency_hz", type=float)
    analyze.add_argument("--max-freq-hz", dest="maximum_frequency_hz", type=float)
    analyze.add_argument(
        "--no-auto-band-retry",
        dest="auto_band_retry",
        action="store_false",
        default=None,
        help="Disable automatic stepped low-frequency band retry.",
    )
    analyze.add_argument("--window-length", dest="window_length_samples", type=int)
    analyze.add_argument("--overlap", dest="overlap_samples", type=int)
    analyze.add_argument("--nfft", type=int)
    analyze.add_argument("--window-name")
    analyze.add_argument(
        "--event-time-s",
        "--event-reference-time-s",
        dest="event_reference_time_s",
        type=float,
    )
    analyze.add_argument("--time-origin", choices=("absolute", "event"), default=None)
    analyze.add_argument(
        "--no-pre-event-display",
        dest="pre_event_display",
        action="store_false",
        default=None,
        help="Disable zero pre-event display plateau in velocity_display.csv.",
    )
    analyze.add_argument(
        "--full-diagnostics",
        action="store_true",
        default=None,
        help="Also emit legacy per-channel *_detail.csv diagnostic files.",
    )
    acceleration = analyze.add_mutually_exclusive_group()
    acceleration.add_argument(
        "--include-acceleration",
        "--acceleration",
        dest="include_acceleration",
        action="store_true",
        default=None,
    )
    acceleration.add_argument("--no-acceleration", dest="include_acceleration", action="store_false")
    analyze.add_argument("--acceleration-fit-window-s", type=float)

    batch = commands.add_parser("batch", help="Analyze matching files in a directory.")
    batch.add_argument("input_dir", type=Path)
    batch.add_argument("--config", type=Path, required=True)
    batch.add_argument("--out", type=Path, required=True, help="Root for per-file result directories.")
    batch.add_argument("--pattern", default="*.csv", help="File glob (default: *.csv).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command is None:
        return 0
    try:
        _writable_path(userdata_root())
        initialize_runtime_storage(redirect_process_temp=bool(getattr(sys, "frozen", False)))
        match args.command:
            case "inspect":
                _inspect(args)
            case "analyze":
                config = read_config(args.config)
                for key, value in vars(args).items():
                    if key not in {"command", "input_file", "config", "out"} and value is not None:
                        config[key] = value
                if args.measurement_angle_deg is not None:
                    config.pop("measurement_angle_rad", None)
                _analyze(args.input_file, args.out, config, emit_stdout=True)
            case "batch":
                return _batch(args.input_dir, args.out, read_config(args.config), args.pattern)
    except (*_COMMAND_ERRORS, RuntimeStorageError) as exc:
        print(f"pdv {args.command}: {exc}", file=sys.stderr)
        return 2
    return 0


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise ValueError(f"Input must be a regular file: {path}")
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _verify_source(path: Path, expected_hash: str) -> None:
    if _sha256(path) != expected_hash:
        raise ValueError(f"Input changed during processing: {path}")


def _raw_directories() -> tuple[Path, ...]:
    return (application_resource_root() / "data/raw", installation_root() / "data/raw")


def _writable_path(path: Path) -> Path:
    expanded = path.expanduser()
    resolved = expanded.resolve()
    raw = [directory.resolve() for directory in _raw_directories()]
    for candidate in (expanded, resolved):
        parts = tuple(part.casefold() for part in candidate.parts)
        if any(part == ("data", "raw") for part in zip(parts, parts[1:], strict=False)):
            raise ValueError(f"Cannot write inside data/raw: {path}")
    if any(resolved.is_relative_to(directory) for directory in raw):
        raise ValueError(f"Cannot write inside data/raw: {path}")
    return expanded.absolute()


def _json(document: Mapping[str, object]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def _write_json(path: Path, document: Mapping[str, object]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(_json(document))


def _inspect(args: argparse.Namespace) -> None:
    source = args.input_file.expanduser().resolve()
    source_hash = _sha256(source)
    size = source.stat().st_size
    try:
        preview = preview_delimited_file(
            source,
            delimiter=delimiter_value(args.delimiter),
            encoding=args.encoding,
            max_data_rows=args.max_rows,
        )
    except DelimitedPreviewError as exc:
        raise ValueError(f"Cannot preview {source} as delimited text: {exc}") from exc
    finally:
        _verify_source(source, source_hash)
    document = {
        "command": "inspect",
        "software_version": __version__,
        "source_path": str(source),
        "source_sha256": source_hash,
        "input_unchanged": True,
        "size_bytes": size,
        "column_count": preview.column_count,
        "delimiter": preview.delimiter,
        "encoding": preview.encoding,
        "has_header": preview.has_header,
        "header": preview.header,
        "sample_rows": preview.rows,
        "required_experiment_parameters": REQUIRED_EXPERIMENT_PARAMETERS,
        "optional_analysis_parameters": OPTIONAL_ANALYSIS_PARAMETERS,
        "notes": [
            "Column indices are zero-based. Header detection is tentative.",
            "Confirm units, wavelength, angle and window with the researcher before analysis.",
            "measurement_angle_rad may be supplied instead of measurement_angle_deg in config.",
            "--auto-columns maps col 0 to time and cols 1..N (2..4 cols total) to pdv_channel_1..3.",
        ],
    }
    if args.out is not None:
        output = _writable_path(args.out)
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_json(output, document)
    sys.stdout.write(_json(document))


@dataclass(frozen=True, slots=True)
class _SearchRegion:
    time_start_s: float
    time_end_s: float
    frequency_min_hz: float
    frequency_max_hz: float


def _search_region(
    stfts: Mapping[str, STFTResult],
    parameters: AnalysisRunParameters,
    requested_start: float,
    requested_end: float,
) -> _SearchRegion:
    start = max(requested_start, *(float(stft.time_s[0]) for stft in stfts.values()))
    end = min(requested_end, *(float(stft.time_s[-1]) for stft in stfts.values()))
    if start >= end or any(
        not np.any((start <= stft.time_s) & (stft.time_s <= end)) for stft in stfts.values()
    ):
        raise ValueError("Analysis time range must contain STFT frame centers in every channel.")
    axis_min = max(float(stft.frequency_hz[0]) for stft in stfts.values())
    axis_max = min(float(stft.frequency_hz[-1]) for stft in stfts.values())
    low = max(parameters.minimum_frequency_hz, axis_min)
    high = min(parameters.maximum_frequency_hz, axis_max)
    if low >= high or any(
        np.count_nonzero((low <= stft.frequency_hz) & (stft.frequency_hz <= high)) < 2
        for stft in stfts.values()
    ):
        low, high = axis_min, axis_max
    return _SearchRegion(start, end, low, high)


def _measured_fraction(analysis: ChannelAnalysis) -> tuple[int, int, float]:
    states = analysis.signal_detection_result.signal_states
    total = len(states)
    measured = sum(state is SignalState.MEASURED for state in states)
    return measured, total, (measured / total if total else 0.0)


def _should_retry_low_freq_band(
    analysis: ChannelAnalysis,
    bound_min_hz: float,
) -> tuple[bool, dict[str, object]]:
    states = analysis.signal_detection_result.signal_states
    in_window = [
        idx for idx, state in enumerate(states) if state is not SignalState.OUTSIDE_ANALYSIS_WINDOW
    ]
    measured, total, measured_fraction = _measured_fraction(analysis)
    if not in_window or measured_fraction >= 0.05:
        return False, {
            "in_window_frames": len(in_window),
            "boundary_peaked_frames": 0,
            "boundary_peaked_fraction": 0.0,
            "measured_fraction": measured_fraction,
        }
    freqs = analysis.stft_result.frequency_hz
    df_hz = float(freqs[1] - freqs[0]) if freqs.size > 1 else 0.0
    threshold_hz = bound_min_hz + 3.0 * df_hz + 1e-6
    boundary_count = 0
    working = analysis.working_frequency_hz
    for idx in in_window:
        val = float(working[idx])
        if (
            states[idx] is SignalState.PEAK_AT_BAND_BOUNDARY
            and math.isfinite(val)
            and val <= threshold_hz
        ):
            boundary_count += 1
    boundary_fraction = boundary_count / len(in_window)
    return boundary_fraction >= 0.50, {
        "in_window_frames": len(in_window),
        "boundary_peaked_frames": boundary_count,
        "boundary_peaked_fraction": boundary_fraction,
        "measured_frames": measured,
        "total_frames": total,
        "measured_fraction": measured_fraction,
    }


def _evaluate_band(
    *,
    stfts: Mapping[str, STFTResult],
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
    time_start_s: float,
    time_end_s: float,
    reference: float | None,
    reference_source: str | None,
    pre_event_enabled: bool,
    parameters: AnalysisRunParameters,
    base: WorkflowConfiguration,
    experiment: Experiment,
) -> dict[str, ChannelAnalysis]:
    raw_analyses = analyze_stft_results(
        stfts,
        minimum_frequency_hz=minimum_frequency_hz,
        maximum_frequency_hz=maximum_frequency_hz,
        analysis_start_time_s=time_start_s,
        analysis_end_time_s=time_end_s,
        manual_event_reference_time_s=reference,
        vacuum_wavelength_m=parameters.vacuum_wavelength_m,
        detection_config=base.quality.signal_detection,
        event_candidate_config=base.event_candidate,
        profile_name=parameters.provenance_name,
        background_guard_window_scale=base.quality.background_guard_window_scale,
        minimum_background_bin_count=base.quality.minimum_background_bin_count,
        assume_pre_event_zero_for_display=pre_event_enabled,
        pre_event_display_velocity_m_s=base.plot.pre_event_display_velocity_m_s,
        automatic_ridge_selection_config=base.automatic_ridge_selection,
        velocity_correction_config=experiment.correction,
    )
    return {
        name: configure_channel_event_reference(
            analysis,
            event_reference_time_s=reference,
            event_reference_source=reference_source,
            enable_pre_event_display=pre_event_enabled,
            pre_event_display_velocity_m_s=base.plot.pre_event_display_velocity_m_s,
        )
        for name, analysis in raw_analyses.items()
    }


def _run_auto_band_retry(
    *,
    analyses: dict[str, ChannelAnalysis],
    stfts: Mapping[str, STFTResult],
    region: _SearchRegion,
    retry_enabled: bool,
    explicit_min_freq: bool,
    reference: float | None,
    reference_source: str | None,
    pre_event_enabled: bool,
    parameters: AnalysisRunParameters,
    base: WorkflowConfiguration,
    experiment: Experiment,
) -> tuple[dict[str, ChannelAnalysis], dict[str, tuple[float, float]], dict[str, object]]:
    channel_bounds: dict[str, tuple[float, float]] = {
        name: (region.frequency_min_hz, region.frequency_max_hz) for name in analyses
    }
    if not retry_enabled:
        reason = (
            "explicit_minimum_frequency_hz"
            if explicit_min_freq
            else "disabled_by_caller"
        )
        return analyses, channel_bounds, {
            "enabled": False,
            "reason": reason,
            "triggered": False,
            "channels": {
                name: {
                    "triggered": False,
                    "baseline_min_freq_hz": region.frequency_min_hz,
                    "selected_min_freq_hz": region.frequency_min_hz,
                    "baseline_measured_fraction": _measured_fraction(analysis)[2],
                    "final_measured_fraction": _measured_fraction(analysis)[2],
                    "attempts": [],
                    "accepted": False,
                }
                for name, analysis in analyses.items()
            },
        }

    updated = dict(analyses)
    channel_reports: dict[str, object] = {}
    any_triggered = False

    for name, baseline in analyses.items():
        base_measured, base_total, base_fraction = _measured_fraction(baseline)
        trigger_ok, trigger_diag = _should_retry_low_freq_band(baseline, region.frequency_min_hz)
        if not trigger_ok:
            channel_reports[name] = {
                "triggered": False,
                "baseline_min_freq_hz": region.frequency_min_hz,
                "selected_min_freq_hz": region.frequency_min_hz,
                "baseline_measured_fraction": base_fraction,
                "final_measured_fraction": base_fraction,
                "trigger_diagnostics": trigger_diag,
                "attempts": [],
                "accepted": False,
            }
            continue

        any_triggered = True
        stft = stfts[name]
        attempts: list[dict[str, object]] = []
        chosen_analysis = baseline
        chosen_min_hz = region.frequency_min_hz
        accepted_reason = "kept_baseline"

        best_cand: tuple[float, float, ChannelAnalysis] | None = None
        for cand_min in _LOW_FREQ_RETRY_STEPS_HZ:
            if cand_min <= region.frequency_min_hz + 1e-6 or cand_min >= region.frequency_max_hz:
                continue
            bins_in_band = int(
                np.count_nonzero(
                    (stft.frequency_hz >= cand_min) & (stft.frequency_hz <= region.frequency_max_hz)
                )
            )
            if bins_in_band < 2:
                continue
            cand_analysis = _evaluate_band(
                stfts={name: stft},
                minimum_frequency_hz=cand_min,
                maximum_frequency_hz=region.frequency_max_hz,
                time_start_s=region.time_start_s,
                time_end_s=region.time_end_s,
                reference=reference,
                reference_source=reference_source,
                pre_event_enabled=pre_event_enabled,
                parameters=parameters,
                base=base,
                experiment=experiment,
            )[name]
            cand_measured, cand_total, cand_fraction = _measured_fraction(cand_analysis)
            improvement = cand_fraction - base_fraction
            attempts.append(
                {
                    "min_freq_hz": cand_min,
                    "measured": cand_measured,
                    "total_frames": cand_total,
                    "measured_fraction": cand_fraction,
                    "improvement": improvement,
                }
            )
            if best_cand is None or cand_fraction > best_cand[0]:
                best_cand = (cand_fraction, cand_min, cand_analysis)
            if cand_fraction >= 0.15 and improvement >= 0.10:
                chosen_analysis = cand_analysis
                chosen_min_hz = cand_min
                accepted_reason = "first_ge_0.15_and_delta_ge_0.10"
                break
        else:
            if best_cand is not None and (best_cand[0] - base_fraction) >= 0.05:
                chosen_analysis = best_cand[2]
                chosen_min_hz = best_cand[1]
                accepted_reason = "best_delta_ge_0.05"
            else:
                accepted_reason = "insufficient_improvement"

        updated[name] = chosen_analysis
        channel_bounds[name] = (chosen_min_hz, region.frequency_max_hz)
        final_measured, _, final_fraction = _measured_fraction(chosen_analysis)
        channel_reports[name] = {
            "triggered": True,
            "baseline_min_freq_hz": region.frequency_min_hz,
            "selected_min_freq_hz": chosen_min_hz,
            "baseline_measured_frames": base_measured,
            "baseline_measured_fraction": base_fraction,
            "final_measured_frames": final_measured,
            "final_measured_fraction": final_fraction,
            "trigger_diagnostics": trigger_diag,
            "attempts": attempts,
            "accepted": accepted_reason in {"first_ge_0.15_and_delta_ge_0.10", "best_delta_ge_0.05"},
            "accepted_reason": accepted_reason,
            "total_frames": base_total,
        }

    return updated, channel_bounds, {
        "enabled": True,
        "candidate_steps_hz": list(_LOW_FREQ_RETRY_STEPS_HZ),
        "triggered": any_triggered,
        "channels": channel_reports,
    }


def _resolve_config_and_preview(
    source: Path,
    config: Mapping[str, object],
) -> tuple[dict[str, object], DelimitedFilePreview | None, str | None, bool, str, bool]:
    resolved_config = dict(config)
    auto_columns = optional_bool(resolved_config, "auto_columns") is True
    delimiter_raw = resolved_config.get("delimiter")
    if delimiter_raw is not None and not isinstance(delimiter_raw, str):
        raise ValueError("delimiter must be text.")
    delimiter = delimiter_value(delimiter_raw)
    encoding = optional_text(resolved_config, "encoding") or "utf-8"
    has_header = optional_bool(resolved_config, "has_header")

    if auto_columns:
        if resolved_config.get("time_column") is not None or resolved_config.get("voltage_columns") is not None:
            raise ValueError(
                "--auto-columns cannot be combined with explicit time_column or voltage_columns."
            )
        if not source.is_file():
            raise ValueError(f"Input must be a regular file: {source}")
        preview = preview_delimited_file(source, delimiter=delimiter, encoding=encoding)
        if not (2 <= preview.column_count <= 4):
            raise ValueError(
                f"--auto-columns supports 2 to 4 columns (time + 1-3 voltage channels), "
                f"found {preview.column_count}. Specify --time-column and --voltage-columns explicitly."
            )
        resolved_config["time_column"] = 0
        resolved_config["voltage_columns"] = {
            f"pdv_channel_{idx}": idx for idx in range(1, preview.column_count)
        }
        return (
            resolved_config,
            preview,
            delimiter if delimiter is not None else preview.delimiter,
            preview.has_header if has_header is None else has_header,
            encoding,
            True,
        )

    # Validate explicit config parameters before reading missing files to preserve fast fail.
    return resolved_config, None, delimiter, bool(has_header) if has_header is not None else False, encoding, False


def _analyze(
    source: Path,
    output: Path,
    config: Mapping[str, object],
    *,
    emit_stdout: bool = False,
) -> ResultBundleReport:
    source_resolved = source.expanduser().resolve()
    (
        resolved_config,
        preview,
        delimiter,
        resolved_has_header,
        encoding,
        auto_columns,
    ) = _resolve_config_and_preview(source_resolved, config)

    experiment = read_experiment(resolved_config)
    output_resolved = _writable_path(output).resolve()
    source_hash = _sha256(source_resolved)
    defaults = application_resource_path("configs", "pdv_studio_defaults.toml")
    if not defaults.is_file() and not getattr(sys, "frozen", False):
        defaults = package_resource_path("resources", defaults.name)
    base = load_workflow_config(defaults, repository_root=application_resource_root())
    profile_id = optional_text(resolved_config, "profile") or "balanced"
    profiles = {profile.profile_id.value: profile for profile in base.analysis.profiles}
    if profile_id not in profiles:
        raise ValueError(f"Unknown profile {profile_id!r}. Choose from: {', '.join(profiles)}.")

    has_header_opt = optional_bool(resolved_config, "has_header")
    if preview is None and (delimiter is None or has_header_opt is None):
        preview = preview_delimited_file(source_resolved, delimiter=delimiter, encoding=encoding)
        if delimiter is None:
            delimiter = preview.delimiter
        resolved_has_header = preview.has_header if has_header_opt is None else has_header_opt
    assert delimiter is not None

    records = read_delimited_signals(
        source_resolved,
        time_column=experiment.time_column,
        voltage_columns=experiment.voltage_columns,
        delimiter=delimiter,
        has_header=resolved_has_header,
        encoding=encoding,
        time_scale=TIME_SCALES[experiment.time_unit],
        original_time_unit=experiment.time_unit,
        voltage_scales={name: VOLTAGE_SCALES[unit] for name, unit in experiment.voltage_units.items()},
        original_voltage_units=experiment.voltage_units,
    ).records

    extra_warnings: list[str] = []
    first_record = next(iter(records.values()))
    dt_array = np.diff(first_record.time_s)
    inferred_sample_rate_hz = float(1.0 / np.median(dt_array)) if dt_array.size else 0.0
    if not (_EXPECTED_SAMPLE_RATE_MIN_HZ <= inferred_sample_rate_hz <= _EXPECTED_SAMPLE_RATE_MAX_HZ):
        msg = (
            f"Inferred sample rate {inferred_sample_rate_hz:.6g} Hz is outside "
            "the expected PDV range [1e8, 1e12] Hz; check --time-unit."
        )
        extra_warnings.append(msg)
        print(f"pdv analyze: warning: {msg}", file=sys.stderr)

    record_start = max(record.start_time_s for record in records.values())
    record_end = min(record.end_time_s for record in records.values())
    start = optional_number(resolved_config, "analysis_start_time_s")
    end = optional_number(resolved_config, "analysis_end_time_s")
    start = record_start if start is None else start
    end = record_end if end is None else end
    tolerance = max(abs(record_end - record_start), 1.0) * 1e-12
    if start < record_start - tolerance or end > record_end + tolerance or start >= end:
        raise ValueError(
            f"Analysis range must stay inside the common input range [{record_start}, "
            f"{record_end}] s and have positive duration."
        )
    start, end = max(start, record_start), min(end, record_end)
    reference = optional_number(resolved_config, "event_reference_time_s")
    if reference is not None and not start - tolerance <= reference <= end + tolerance:
        raise ValueError("Event reference time must stay inside the common input and analysis range.")
    reference_source = "manual" if reference is not None else None

    time_origin_text = optional_text(resolved_config, "time_origin") or "absolute"
    if time_origin_text not in {"absolute", "event"}:
        raise ValueError("time_origin must be 'absolute' or 'event'.")
    time_origin = ExportTimeOrigin(time_origin_text)
    if time_origin is ExportTimeOrigin.EVENT and reference is None:
        raise ValueError("time_origin='event' requires --event-reference-time-s / event_reference_time_s.")

    pre_event_opt = optional_bool(resolved_config, "pre_event_display")
    pre_event_enabled = (
        base.plot.assume_pre_event_zero_for_display
        if pre_event_opt is None
        else pre_event_opt
    )
    include_acceleration = optional_bool(resolved_config, "include_acceleration") is True
    fit_window = optional_number(resolved_config, "acceleration_fit_window_s")
    if fit_window is not None and (not include_acceleration or fit_window <= 0):
        raise ValueError("A positive acceleration fit window requires acceleration export.")
    include_full_diagnostics = optional_bool(resolved_config, "full_diagnostics") is True

    explicit_min_freq = optional_number(resolved_config, "minimum_frequency_hz") is not None
    auto_band_retry_opt = optional_bool(resolved_config, "auto_band_retry")
    retry_enabled = (auto_band_retry_opt is not False) and (not explicit_min_freq)

    parameters = build_analysis_run_parameters(
        base_profile=profiles[profile_id],
        base_vacuum_wavelength_m=experiment.vacuum_wavelength_m,
        overrides=analysis_overrides(resolved_config),
    )
    stfts = compute_configuration_stfts(
        records,
        window_length_samples=parameters.window_length_samples,
        overlap_samples=parameters.overlap_samples,
        nfft=parameters.nfft,
        window_name=parameters.window_name,
    )
    region = _search_region(stfts, parameters, start, end)
    baseline_analyses = _evaluate_band(
        stfts=stfts,
        minimum_frequency_hz=region.frequency_min_hz,
        maximum_frequency_hz=region.frequency_max_hz,
        time_start_s=region.time_start_s,
        time_end_s=region.time_end_s,
        reference=reference,
        reference_source=reference_source,
        pre_event_enabled=pre_event_enabled,
        parameters=parameters,
        base=base,
        experiment=experiment,
    )
    analyses, channel_bounds, retry_report = _run_auto_band_retry(
        analyses=baseline_analyses,
        stfts=stfts,
        region=region,
        retry_enabled=retry_enabled,
        explicit_min_freq=explicit_min_freq,
        reference=reference,
        reference_source=reference_source,
        pre_event_enabled=pre_event_enabled,
        parameters=parameters,
        base=base,
        experiment=experiment,
    )

    from dps_studio.cli_plots import headless_plot_application, render_bundle_spectrogram_ridge

    with headless_plot_application():
        report = export_result_bundle(
            ResultBundleOptions(
                output_directory=output_resolved,
                analysis_mode=ResultAnalysisMode.AUTOMATIC,
                channel_analyses=analyses,
                time_origin=time_origin,
                source_path=source_resolved,
                source_sha256=source_hash,
                analysis_profile_name=parameters.provenance_name,
                pre_event_display_enabled=pre_event_enabled,
                pre_event_display_velocity_m_s=base.plot.pre_event_display_velocity_m_s,
                event_reference_source=reference_source,
                event_time_source="manual" if reference is not None else "unset",
                include_acceleration=include_acceleration,
                acceleration_fit_window_s=fit_window,
                include_full_diagnostics=include_full_diagnostics,
                input_format={
                    "delimiter": delimiter,
                    "encoding": encoding,
                    "has_header": resolved_has_header,
                    "auto_columns": auto_columns,
                    "inferred_sample_rate_hz": inferred_sample_rate_hz,
                },
                experimental_conditions={
                    "time_column": experiment.time_column,
                    "time_unit": experiment.time_unit,
                    "voltage_columns": experiment.voltage_columns,
                    "voltage_units": experiment.voltage_units,
                    "vacuum_wavelength_m": experiment.vacuum_wavelength_m,
                    "measurement_angle_deg": math.degrees(experiment.correction.measurement_angle_rad),
                    "measurement_angle_rad": experiment.correction.measurement_angle_rad,
                    "window_material": experiment.window_material,
                    "window_model": (
                        asdict(experiment.correction.lif_model)
                        if experiment.correction.window_correction_enabled
                        else None
                    ),
                },
                analysis_parameters={
                    **asdict(parameters),
                    "profile": profile_id,
                    "profile_name": parameters.provenance_name,
                    "hop_samples": parameters.window_length_samples - parameters.overlap_samples,
                    "analysis_start_time_s": start,
                    "analysis_end_time_s": end,
                    "ridge_search_region": asdict(region),
                    "resolved_channel_frequency_bounds_hz": {
                        name: {"min_hz": bounds[0], "max_hz": bounds[1]}
                        for name, bounds in channel_bounds.items()
                    },
                    "event_reference_time_s": reference,
                    "automatic_ridge_selection": asdict(base.automatic_ridge_selection),
                    "signal_detection": asdict(base.quality.signal_detection),
                    "event_candidate": asdict(base.event_candidate),
                    "background_guard_window_scale": base.quality.background_guard_window_scale,
                    "minimum_background_bin_count": base.quality.minimum_background_bin_count,
                    "include_acceleration": include_acceleration,
                    "acceleration_fit_window_s": fit_window,
                    "full_diagnostics": include_full_diagnostics,
                },
                auto_band_retry=retry_report,
                extra_warnings=tuple(extra_warnings),
                protected_output_directories=_raw_directories(),
                spectrogram_renderer=lambda plot_dst: render_bundle_spectrogram_ridge(
                    analyses,
                    plot_dst,
                    channel_frequency_bounds_hz=channel_bounds,
                    relative_db_floor=base.plot.relative_db_floor,
                ),
                pre_publish_hook=lambda: _verify_source(source_resolved, source_hash),
            )
        )

    channel_summary: dict[str, dict[str, object]] = {}
    for name, analysis in analyses.items():
        measured, total, measured_fraction = _measured_fraction(analysis)
        if measured == 0:
            print(
                f"pdv analyze: warning: channel {name} produced 0/{total} measured frames.",
                file=sys.stderr,
            )
        channel_summary[name] = {
            "token": report.channel_tokens[name],
            "measured_frames": measured,
            "total_frames": total,
            "measured_fraction": measured_fraction,
            "resolved_min_freq_hz": channel_bounds[name][0],
            "resolved_max_freq_hz": channel_bounds[name][1],
        }

    if emit_stdout:
        stdout_doc: dict[str, Any] = {
            "command": "analyze",
            "software_version": __version__,
            "source_path": str(source_resolved),
            "output_directory": str(report.output_directory),
            "channels": channel_summary,
            "auto_band_retry": retry_report,
            "warnings": list(report.warnings),
            "outputs": {
                "velocity_raw_csv": report.velocity_raw_csv_path.name,
                "velocity_gated_csv": report.velocity_gated_csv_path.name,
                "velocity_display_csv": report.velocity_display_csv_path.name,
                "run_summary_json": report.run_summary_json_path.name,
                "spectrogram_ridge_png": (
                    report.spectrogram_ridge_png_path.name
                    if report.spectrogram_ridge_png_path is not None
                    else None
                ),
                "acceleration_csv": (
                    report.acceleration_csv_path.name
                    if report.acceleration_csv_path is not None
                    else None
                ),
            },
        }
        sys.stdout.write(_json(stdout_doc))
    return report


def _batch(directory: Path, output_root: Path, config: Mapping[str, object], pattern: str) -> int:
    source_dir = directory.expanduser().resolve()
    if not source_dir.is_dir():
        raise ValueError(f"Batch input directory does not exist: {source_dir}")
    sources = sorted(source for source in source_dir.glob(pattern) if source.is_file())
    output = _writable_path(output_root)
    output.mkdir(parents=True, exist_ok=True)
    summary_path = output / "batch_summary.json"
    if summary_path.exists() or summary_path.is_symlink():
        raise FileExistsError(f"Batch summary already exists: {summary_path}")
    stems = Counter(source.stem.casefold() for source in sources)
    items = []
    failed = 0
    for source in sources:
        destination = output / source.stem
        try:
            if source.stem.casefold() == summary_path.name:
                raise ValueError(f"Output stem {source.stem!r} is reserved for the batch summary.")
            if stems[source.stem.casefold()] > 1:
                raise ValueError(f"Multiple batch inputs share output stem {source.stem!r}.")
            _analyze(source, destination, config, emit_stdout=False)
        except _COMMAND_ERRORS as exc:
            failed += 1
            items.append(
                {
                    "source_path": str(source),
                    "output_directory": str(destination),
                    "status": "failed",
                    "error": str(exc),
                }
            )
            print(f"pdv batch: {source}: {exc}", file=sys.stderr)
        else:
            items.append(
                {
                    "source_path": str(source),
                    "output_directory": str(destination),
                    "status": "ok",
                }
            )
    _write_json(
        summary_path,
        {
            "command": "batch",
            "software_version": __version__,
            "input_directory": str(source_dir),
            "pattern": pattern,
            "total": len(sources),
            "succeeded": len(sources) - failed,
            "failed": failed,
            "results": items,
        },
    )
    return int(failed > 0)


if __name__ == "__main__":
    raise SystemExit(main())
