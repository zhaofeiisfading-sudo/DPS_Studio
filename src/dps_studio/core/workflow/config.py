"""Immutable TOML configuration for the formal dual-profile workflow."""

from __future__ import annotations

import codecs
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Integral, Real
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from dps_studio.core.analysis_profiles import (
    BALANCED_PROFILE,
    HIGH_FREQUENCY_RESOLUTION_PROFILE,
    HIGH_TIME_RESOLUTION_PROFILE,
    VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE,
    VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE,
    AnalysisProfile,
    get_analysis_profile,
)
from dps_studio.core.event_candidates import (
    EventCandidateConfig,
    EventConsensusConfig,
)
from dps_studio.core.quality import SignalDetectionConfig


class WorkflowConfigurationError(ValueError):
    """Raised when a formal workflow configuration field is invalid."""


@dataclass(frozen=True, slots=True, eq=False)
class InputConfiguration:
    """Explicit file and column mapping in SI-oriented reader units."""

    path: Path
    time_column: int
    delimiter: str
    has_header: bool
    encoding: str
    time_scale: float
    voltage_columns: Mapping[str, int]
    voltage_scales: Mapping[str, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "voltage_columns",
            MappingProxyType(dict(self.voltage_columns)),
        )
        object.__setattr__(
            self,
            "voltage_scales",
            MappingProxyType(dict(self.voltage_scales)),
        )


@dataclass(frozen=True, slots=True, eq=False)
class AnalysisConfiguration:
    """Formal profiles and shared experiment-time analysis parameters."""

    profiles: tuple[AnalysisProfile, ...]
    default_profile: AnalysisProfile
    analysis_start_time_s: float | None
    analysis_end_time_s: float | None
    manual_event_reference_time_s: float | None
    vacuum_wavelength_m: float

    @property
    def event_start_time_s(self) -> float | None:
        """Deprecated compatibility alias for the display-only manual reference."""
        return self.manual_event_reference_time_s

    @property
    def event_reference_time_s(self) -> float | None:
        """Return the explicit per-experiment display/review reference."""
        return self.manual_event_reference_time_s


@dataclass(frozen=True, slots=True, eq=False)
class QualityConfiguration:
    """Spectral diagnostics and formal signal-detection thresholds."""

    background_guard_window_scale: float
    minimum_background_bin_count: int
    signal_detection: SignalDetectionConfig


@dataclass(frozen=True, slots=True, eq=False)
class PlotConfiguration:
    """Presentation-only ranges; these values do not alter ridge extraction."""

    relative_db_floor: float
    analysis_display_minimum_frequency_hz: float
    analysis_display_maximum_frequency_hz: float
    event_detail_before_s: float
    event_detail_after_s: float
    assume_pre_event_zero_for_display: bool
    pre_event_display_velocity_m_s: float


@dataclass(frozen=True, slots=True, eq=False)
class OutputConfiguration:
    """Configured parent directory for new, non-overwriting production runs."""

    root: Path


@dataclass(frozen=True, slots=True, eq=False)
class WorkflowConfiguration:
    """Complete immutable formal-workflow configuration."""

    input: InputConfiguration
    analysis: AnalysisConfiguration
    quality: QualityConfiguration
    event_candidate: EventCandidateConfig
    event_consensus: EventConsensusConfig
    plot: PlotConfiguration
    output: OutputConfiguration
    repository_root: Path
    config_path: Path


def load_workflow_config(
    config_path: str | Path,
    *,
    repository_root: str | Path,
) -> WorkflowConfiguration:
    """Load and validate one TOML file without guessing units or paths."""
    root = _resolved_path(repository_root, field_name="repository_root")
    path = _resolve_relative_path(
        config_path,
        repository_root=root,
        field_name="config_path",
    )
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise WorkflowConfigurationError(
            f"config_path does not exist: {path}."
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise WorkflowConfigurationError(f"config_path is invalid TOML: {exc}.") from exc

    input_table = _table(document, "input")
    analysis_table = _table(document, "analysis")
    quality_table = _table(document, "quality")
    event_candidate_table = _table(document, "event_candidate")
    event_consensus_table = _table(document, "event_consensus")
    plot_table = _table(document, "plot")
    output_table = _table(document, "output")

    voltage_columns_table = _table(input_table, "voltage_columns", parent="input")
    voltage_scales_table = _table(input_table, "voltage_scales", parent="input")
    voltage_columns = _channel_columns(voltage_columns_table)
    voltage_scales = _channel_scales(voltage_scales_table, voltage_columns)
    time_column = _integer(
        _required(input_table, "time_column", parent="input"),
        field_name="input.time_column",
        minimum=0,
    )
    if time_column in voltage_columns.values():
        raise WorkflowConfigurationError(
            "input.time_column must not duplicate any input.voltage_columns value."
        )
    if len(set(voltage_columns.values())) != len(voltage_columns):
        raise WorkflowConfigurationError(
            "input.voltage_columns values must be distinct."
        )

    delimiter = _string(
        _required(input_table, "delimiter", parent="input"),
        field_name="input.delimiter",
    )
    if len(delimiter) != 1 or delimiter in {"\r", "\n"}:
        raise WorkflowConfigurationError(
            "input.delimiter must be exactly one non-newline character."
        )
    encoding = _string(
        _required(input_table, "encoding", parent="input"),
        field_name="input.encoding",
    )
    try:
        codecs.lookup(encoding)
    except LookupError as exc:
        raise WorkflowConfigurationError(
            f"input.encoding is unknown: {encoding!r}."
        ) from exc

    input_configuration = InputConfiguration(
        path=_resolve_relative_path(
            _string(
                _required(input_table, "path", parent="input"),
                field_name="input.path",
            ),
            repository_root=root,
            field_name="input.path",
        ),
        time_column=time_column,
        delimiter=delimiter,
        has_header=_boolean(
            _required(input_table, "has_header", parent="input"),
            field_name="input.has_header",
        ),
        encoding=encoding,
        time_scale=_positive_float(
            _required(input_table, "time_scale", parent="input"),
            field_name="input.time_scale",
        ),
        voltage_columns=voltage_columns,
        voltage_scales=voltage_scales,
    )

    profiles = _profiles(
        _required(analysis_table, "profiles", parent="analysis")
    )
    default_profile = _default_profile(analysis_table, profiles=profiles)
    analysis_start_time_s = _optional_table_float(
        analysis_table,
        "analysis_start_time_s",
        parent="analysis",
    )
    analysis_end_time_s = _optional_table_float(
        analysis_table,
        "analysis_end_time_s",
        parent="analysis",
    )
    manual_reference = _manual_event_reference(analysis_table)
    if (
        analysis_start_time_s is not None
        and analysis_end_time_s is not None
        and analysis_start_time_s > analysis_end_time_s
    ):
        raise WorkflowConfigurationError(
            "analysis.analysis_start_time_s must not exceed "
            "analysis.analysis_end_time_s."
        )
    analysis_configuration = AnalysisConfiguration(
        profiles=profiles,
        default_profile=default_profile,
        analysis_start_time_s=analysis_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        manual_event_reference_time_s=manual_reference,
        vacuum_wavelength_m=_positive_float(
            _required(analysis_table, "vacuum_wavelength_m", parent="analysis"),
            field_name="analysis.vacuum_wavelength_m",
        ),
    )

    quality_configuration = QualityConfiguration(
        background_guard_window_scale=_positive_float(
            _required(
                quality_table,
                "background_guard_window_scale",
                parent="quality",
            ),
            field_name="quality.background_guard_window_scale",
        ),
        minimum_background_bin_count=_integer(
            _required(
                quality_table,
                "minimum_background_bin_count",
                parent="quality",
            ),
            field_name="quality.minimum_background_bin_count",
            minimum=1,
        ),
        signal_detection=SignalDetectionConfig(
            minimum_peak_to_background_db=_nonnegative_float(
                _required(
                    quality_table,
                    "minimum_peak_to_background_db",
                    parent="quality",
                ),
                field_name="quality.minimum_peak_to_background_db",
            ),
            minimum_peak_to_competitor_db=_nonnegative_float(
                _required(
                    quality_table,
                    "minimum_peak_to_competitor_db",
                    parent="quality",
                ),
                field_name="quality.minimum_peak_to_competitor_db",
            ),
            peak_exclusion_half_width_bins=_integer(
                _required(
                    quality_table,
                    "peak_exclusion_half_width_bins",
                    parent="quality",
                ),
                field_name="quality.peak_exclusion_half_width_bins",
                minimum=0,
            ),
            minimum_consecutive_frames=_integer(
                _required(
                    quality_table,
                    "minimum_consecutive_frames",
                    parent="quality",
                ),
                field_name="quality.minimum_consecutive_frames",
                minimum=1,
            ),
            minimum_cycles_in_window=_positive_float(
                _required(
                    quality_table,
                    "minimum_cycles_in_window",
                    parent="quality",
                ),
                field_name="quality.minimum_cycles_in_window",
            ),
            enabled=_boolean(
                _required(quality_table, "enabled", parent="quality"),
                field_name="quality.enabled",
            ),
        ),
    )
    event_candidate_configuration = EventCandidateConfig(
        minimum_segment_frames=_integer(
            _required(
                event_candidate_table,
                "minimum_segment_frames",
                parent="event_candidate",
            ),
            field_name="event_candidate.minimum_segment_frames",
            minimum=1,
        ),
        minimum_segment_duration_s=_nonnegative_float(
            _required(
                event_candidate_table,
                "minimum_segment_duration_s",
                parent="event_candidate",
            ),
            field_name="event_candidate.minimum_segment_duration_s",
        ),
        maximum_adjacent_frequency_step_hz=_positive_float(
            _required(
                event_candidate_table,
                "maximum_adjacent_frequency_step_hz",
                parent="event_candidate",
            ),
            field_name="event_candidate.maximum_adjacent_frequency_step_hz",
        ),
        minimum_median_peak_to_background_db=_optional_table_float(
            event_candidate_table,
            "minimum_median_peak_to_background_db",
            parent="event_candidate",
        ),
        minimum_median_peak_to_competitor_db=_optional_table_float(
            event_candidate_table,
            "minimum_median_peak_to_competitor_db",
            parent="event_candidate",
        ),
    )
    event_consensus_configuration = EventConsensusConfig(
        channel_start_time_tolerance_s=_positive_float(
            _required(
                event_consensus_table,
                "channel_start_time_tolerance_s",
                parent="event_consensus",
            ),
            field_name="event_consensus.channel_start_time_tolerance_s",
        ),
        minimum_interval_overlap_fraction=_closed_unit_interval(
            _required(
                event_consensus_table,
                "minimum_interval_overlap_fraction",
                parent="event_consensus",
            ),
            field_name="event_consensus.minimum_interval_overlap_fraction",
        ),
        channel_start_frequency_tolerance_hz=_positive_float(
            _required(
                event_consensus_table,
                "channel_start_frequency_tolerance_hz",
                parent="event_consensus",
            ),
            field_name="event_consensus.channel_start_frequency_tolerance_hz",
        ),
        cross_profile_time_tolerance_s=_positive_float(
            _required(
                event_consensus_table,
                "cross_profile_time_tolerance_s",
                parent="event_consensus",
            ),
            field_name="event_consensus.cross_profile_time_tolerance_s",
        ),
    )

    relative_db_floor = _finite_float(
        _required(plot_table, "relative_db_floor", parent="plot"),
        field_name="plot.relative_db_floor",
    )
    if relative_db_floor >= 0.0:
        raise WorkflowConfigurationError(
            "plot.relative_db_floor must be finite and smaller than zero."
        )
    display_minimum = _nonnegative_float(
        _required(
            plot_table,
            "analysis_display_minimum_frequency_hz",
            parent="plot",
        ),
        field_name="plot.analysis_display_minimum_frequency_hz",
    )
    display_maximum = _positive_float(
        _required(
            plot_table,
            "analysis_display_maximum_frequency_hz",
            parent="plot",
        ),
        field_name="plot.analysis_display_maximum_frequency_hz",
    )
    if display_maximum <= display_minimum:
        raise WorkflowConfigurationError(
            "plot.analysis_display_maximum_frequency_hz must be greater than "
            "plot.analysis_display_minimum_frequency_hz."
        )
    plot_configuration = PlotConfiguration(
        relative_db_floor=relative_db_floor,
        analysis_display_minimum_frequency_hz=display_minimum,
        analysis_display_maximum_frequency_hz=display_maximum,
        event_detail_before_s=_nonnegative_float(
            _required(plot_table, "event_detail_before_s", parent="plot"),
            field_name="plot.event_detail_before_s",
        ),
        event_detail_after_s=_nonnegative_float(
            _required(plot_table, "event_detail_after_s", parent="plot"),
            field_name="plot.event_detail_after_s",
        ),
        assume_pre_event_zero_for_display=_boolean(
            _required(
                plot_table,
                "assume_pre_event_zero_for_display",
                parent="plot",
            ),
            field_name="plot.assume_pre_event_zero_for_display",
        ),
        pre_event_display_velocity_m_s=_finite_float(
            plot_table.get("pre_event_display_velocity_m_s", 0.0),
            field_name="plot.pre_event_display_velocity_m_s",
        ),
    )

    output_configuration = OutputConfiguration(
        root=_resolve_relative_path(
            _string(
                _required(output_table, "root", parent="output"),
                field_name="output.root",
            ),
            repository_root=root,
            field_name="output.root",
        )
    )
    return WorkflowConfiguration(
        input=input_configuration,
        analysis=analysis_configuration,
        quality=quality_configuration,
        event_candidate=event_candidate_configuration,
        event_consensus=event_consensus_configuration,
        plot=plot_configuration,
        output=output_configuration,
        repository_root=root,
        config_path=path,
    )


def _profiles(value: object) -> tuple[AnalysisProfile, ...]:
    if not isinstance(value, list) or not value:
        raise WorkflowConfigurationError(
            "analysis.profiles must be a non-empty TOML array of profile identifiers."
        )
    identifiers: list[str] = []
    profiles: list[AnalysisProfile] = []
    for index, item in enumerate(value):
        identifier = _string(item, field_name=f"analysis.profiles[{index}]")
        try:
            profile = get_analysis_profile(identifier)
        except (TypeError, ValueError) as exc:
            raise WorkflowConfigurationError(
                f"analysis.profiles[{index}] is invalid: {identifier!r}."
            ) from exc
        identifiers.append(identifier)
        profiles.append(profile)
    if len(set(identifiers)) != len(identifiers):
        raise WorkflowConfigurationError("analysis.profiles must not contain duplicates.")
    legacy_required = (
        BALANCED_PROFILE.profile_id.value,
        HIGH_TIME_RESOLUTION_PROFILE.profile_id.value,
    )
    expanded_required = (
        *legacy_required,
        HIGH_FREQUENCY_RESOLUTION_PROFILE.profile_id.value,
    )
    experimental_required = (
        VERY_HIGH_TIME_RESOLUTION_EXPERIMENTAL_PROFILE.profile_id.value,
        HIGH_TIME_RESOLUTION_PROFILE.profile_id.value,
        BALANCED_PROFILE.profile_id.value,
        HIGH_FREQUENCY_RESOLUTION_PROFILE.profile_id.value,
        VERY_HIGH_FREQUENCY_RESOLUTION_EXPERIMENTAL_PROFILE.profile_id.value,
    )
    if tuple(identifiers) not in (
        legacy_required,
        expanded_required,
        experimental_required,
    ):
        raise WorkflowConfigurationError(
            "analysis.profiles must be the ordered legacy pair ['balanced', "
            "'high_time_resolution'] or that pair followed by "
            "'high_frequency_resolution', or the ordered five-profile "
            "experimental time-to-frequency sequence."
        )
    return tuple(profiles)


def _default_profile(
    analysis_table: Mapping[str, Any],
    *,
    profiles: tuple[AnalysisProfile, ...],
) -> AnalysisProfile:
    value = analysis_table.get("default_profile")
    if value is None:
        return profiles[0]
    identifier = _string(value, field_name="analysis.default_profile")
    try:
        profile = get_analysis_profile(identifier)
    except (TypeError, ValueError) as exc:
        raise WorkflowConfigurationError(
            f"analysis.default_profile is invalid: {identifier!r}."
        ) from exc
    if profile not in profiles:
        raise WorkflowConfigurationError(
            "analysis.default_profile must also be listed in analysis.profiles."
        )
    return profile


def _channel_columns(table: Mapping[str, Any]) -> dict[str, int]:
    required = ("pdv_channel_1", "pdv_channel_2")
    if tuple(table) != required:
        raise WorkflowConfigurationError(
            "input.voltage_columns must contain exactly pdv_channel_1 and "
            "pdv_channel_2 in that order."
        )
    return {
        name: _integer(
            table[name],
            field_name=f"input.voltage_columns.{name}",
            minimum=0,
        )
        for name in required
    }


def _channel_scales(
    table: Mapping[str, Any],
    columns: Mapping[str, int],
) -> dict[str, float]:
    if tuple(table) != tuple(columns):
        raise WorkflowConfigurationError(
            "input.voltage_scales keys and order must exactly match "
            "input.voltage_columns."
        )
    scales: dict[str, float] = {}
    for name in columns:
        scale = _finite_float(
            table[name],
            field_name=f"input.voltage_scales.{name}",
        )
        if scale == 0.0:
            raise WorkflowConfigurationError(
                f"input.voltage_scales.{name} must be non-zero."
            )
        scales[name] = scale
    return scales


def _table(
    document: Mapping[str, Any],
    name: str,
    *,
    parent: str | None = None,
) -> Mapping[str, Any]:
    field_name = f"{parent}.{name}" if parent else name
    value = document.get(name)
    if not isinstance(value, dict):
        raise WorkflowConfigurationError(f"{field_name} must be a TOML table.")
    return cast("Mapping[str, Any]", value)


def _required(
    table: Mapping[str, Any],
    name: str,
    *,
    parent: str,
) -> object:
    if name not in table:
        raise WorkflowConfigurationError(f"{parent}.{name} is required.")
    return table[name]


def _optional_table_float(
    table: Mapping[str, Any],
    name: str,
    *,
    parent: str,
) -> float | None:
    if name not in table:
        return None
    return _finite_float(table[name], field_name=f"{parent}.{name}")


def _manual_event_reference(table: Mapping[str, Any]) -> float | None:
    explicit = _optional_table_float(
        table,
        "manual_event_reference_time_s",
        parent="analysis",
    )
    legacy = _optional_table_float(
        table,
        "event_start_time_s",
        parent="analysis",
    )
    if explicit is not None and legacy is not None and explicit != legacy:
        raise WorkflowConfigurationError(
            "analysis.event_start_time_s is a deprecated manual-reference alias "
            "and must match analysis.manual_event_reference_time_s when both exist."
        )
    return explicit if explicit is not None else legacy


def _string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkflowConfigurationError(f"{field_name} must be a non-empty string.")
    return value


def _boolean(value: object, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise WorkflowConfigurationError(f"{field_name} must be a boolean.")
    return value


def _integer(value: object, *, field_name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise WorkflowConfigurationError(
            f"{field_name} must be an integer greater than or equal to {minimum}."
        )
    converted = int(value)
    if converted < minimum:
        raise WorkflowConfigurationError(
            f"{field_name} must be greater than or equal to {minimum}."
        )
    return converted


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise WorkflowConfigurationError(
            f"{field_name} must be a finite numeric value in documented SI units."
        )
    converted = float(value)
    if not math.isfinite(converted):
        raise WorkflowConfigurationError(f"{field_name} must be finite.")
    return converted


def _positive_float(value: object, *, field_name: str) -> float:
    converted = _finite_float(value, field_name=field_name)
    if converted <= 0.0:
        raise WorkflowConfigurationError(
            f"{field_name} must be finite and strictly positive."
        )
    return converted


def _closed_unit_interval(value: object, *, field_name: str) -> float:
    converted = _finite_float(value, field_name=field_name)
    if not 0.0 <= converted <= 1.0:
        raise WorkflowConfigurationError(
            f"{field_name} must lie in the closed interval [0, 1]."
        )
    return converted


def _nonnegative_float(value: object, *, field_name: str) -> float:
    converted = _finite_float(value, field_name=field_name)
    if converted < 0.0:
        raise WorkflowConfigurationError(
            f"{field_name} must be finite and non-negative."
        )
    return converted


def _resolved_path(value: str | Path, *, field_name: str) -> Path:
    if not isinstance(value, (str, Path)):
        raise WorkflowConfigurationError(f"{field_name} must be a filesystem path.")
    try:
        return Path(value).resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise WorkflowConfigurationError(
            f"{field_name} could not be resolved."
        ) from exc


def _resolve_relative_path(
    value: str | Path,
    *,
    repository_root: Path,
    field_name: str,
) -> Path:
    if not isinstance(value, (str, Path)):
        raise WorkflowConfigurationError(f"{field_name} must be a filesystem path.")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repository_root / candidate
    return _resolved_path(candidate, field_name=field_name)


__all__ = [
    "AnalysisConfiguration",
    "InputConfiguration",
    "OutputConfiguration",
    "PlotConfiguration",
    "QualityConfiguration",
    "WorkflowConfiguration",
    "WorkflowConfigurationError",
    "load_workflow_config",
]
