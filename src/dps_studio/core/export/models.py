"""Public models for writing current formal workflow results to disk."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from dps_studio.core.workflow.models import ChannelAnalysis


class ResultAnalysisMode(str, Enum):
    """Identity of one independently calculated analysis result set."""

    AUTOMATIC = "automatic"
    GUIDED = "guided"


class ResultExportError(RuntimeError):
    """Base error raised when a formal result cannot be exported safely."""


class ResultExportValidationError(ResultExportError, ValueError):
    """Raised when an export request cannot represent a complete result."""


class ResultExportWriteError(ResultExportError):
    """Raised when a requested export destination cannot be written safely."""


def _empty_paths() -> tuple[Path, ...]:
    return ()


@dataclass(frozen=True, slots=True)
class ResultExportOptions:
    """Explicit, immutable request to export one result mode and its channels.

    ``channel_analyses`` must contain only results from the selected mode.  The
    exporter never reruns an analysis or combines channels; callers therefore
    pass Automatic and Guided selections in separate requests.
    """

    output_directory: Path
    analysis_mode: ResultAnalysisMode
    channel_analyses: Mapping[str, ChannelAnalysis]
    include_pre_event_display_rows: bool = True
    source_path: Path | None = None
    analysis_profile_name: str | None = None
    pre_event_display_enabled: bool | None = None
    pre_event_display_velocity_m_s: float | None = None
    protected_output_directories: tuple[Path, ...] = field(
        default_factory=_empty_paths
    )
    dps_studio_version: str = "0.1.0"

    def __post_init__(self) -> None:
        output_directory = Path(self.output_directory)
        if not isinstance(self.analysis_mode, ResultAnalysisMode):
            raise ResultExportValidationError(
                "analysis_mode must be a ResultAnalysisMode value."
            )
        if not isinstance(self.include_pre_event_display_rows, bool):
            raise ResultExportValidationError(
                "include_pre_event_display_rows must be a boolean."
            )
        try:
            analyses = dict(self.channel_analyses)
        except (TypeError, ValueError) as exc:
            raise ResultExportValidationError(
                "channel_analyses must be a mapping of channel names to results."
            ) from exc
        if not analyses:
            raise ResultExportValidationError("channel_analyses must not be empty.")
        for channel_name, analysis in analyses.items():
            if not isinstance(channel_name, str) or not channel_name.strip():
                raise ResultExportValidationError(
                    "Each channel name must be a non-empty string."
                )
            if not isinstance(analysis, ChannelAnalysis):
                raise ResultExportValidationError(
                    "channel_analyses must contain ChannelAnalysis values."
                )

        if self.source_path is not None and not isinstance(self.source_path, Path):
            raise ResultExportValidationError(
                "source_path must be pathlib.Path or None."
            )
        profile_name = _optional_text(
            self.analysis_profile_name,
            field_name="analysis_profile_name",
        )
        display_enabled = _optional_bool(
            self.pre_event_display_enabled,
            field_name="pre_event_display_enabled",
        )
        display_velocity = _optional_finite_float(
            self.pre_event_display_velocity_m_s,
            field_name="pre_event_display_velocity_m_s",
        )
        try:
            protected_directories = tuple(
                Path(path) for path in self.protected_output_directories
            )
        except TypeError as exc:
            raise ResultExportValidationError(
                "protected_output_directories must be an iterable of paths."
            ) from exc
        if not isinstance(self.dps_studio_version, str) or not self.dps_studio_version:
            raise ResultExportValidationError(
                "dps_studio_version must be a non-empty string."
            )

        object.__setattr__(self, "output_directory", output_directory)
        object.__setattr__(self, "channel_analyses", MappingProxyType(analyses))
        object.__setattr__(self, "analysis_profile_name", profile_name)
        object.__setattr__(self, "pre_event_display_enabled", display_enabled)
        object.__setattr__(self, "pre_event_display_velocity_m_s", display_velocity)
        object.__setattr__(self, "protected_output_directories", protected_directories)


@dataclass(frozen=True, slots=True)
class ExportedChannelResult:
    """The three files written for one independently analyzed channel."""

    channel_name: str
    csv_path: Path
    detail_csv_path: Path
    metadata_path: Path
    exported_row_count: int


@dataclass(frozen=True, slots=True)
class ResultExportReport:
    """Paths and counts for one completed, non-overwriting export directory."""

    output_directory: Path
    analysis_mode: ResultAnalysisMode
    exported_channels: tuple[ExportedChannelResult, ...]


def _optional_text(value: object, *, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ResultExportValidationError(
            f"{field_name} must be a non-empty string or None."
        )
    return value.strip()


def _optional_bool(value: object, *, field_name: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ResultExportValidationError(
            f"{field_name} must be a boolean or None."
        )
    return value


def _optional_finite_float(value: object, *, field_name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ResultExportValidationError(f"{field_name} must be finite or None.")
    try:
        converted = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResultExportValidationError(
            f"{field_name} must be finite or None."
        ) from exc
    if not math.isfinite(converted):
        raise ResultExportValidationError(f"{field_name} must be finite or None.")
    return converted


__all__ = [
    "ExportedChannelResult",
    "ResultAnalysisMode",
    "ResultExportError",
    "ResultExportOptions",
    "ResultExportReport",
    "ResultExportValidationError",
    "ResultExportWriteError",
]
