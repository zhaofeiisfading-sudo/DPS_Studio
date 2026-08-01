"""In-memory GUI session state for formal automatic analysis."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType

from dps_studio.core.analysis_profiles import AnalysisProfile
from dps_studio.core.event_candidates import EventCandidateConfig
from dps_studio.core.models import SignalRecord
from dps_studio.core.quality import SignalDetectionConfig
from dps_studio.core.workflow import ChannelAnalysis, WorkflowConfiguration


@dataclass(frozen=True, slots=True)
class AnalysisRange:
    """A confirmed non-destructive time range in SI seconds."""

    start_time_s: float
    end_time_s: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.start_time_s) or not math.isfinite(self.end_time_s):
            raise ValueError("Analysis range endpoints must be finite seconds.")
        if self.start_time_s >= self.end_time_s:
            raise ValueError("start_time_s must be smaller than end_time_s.")


@dataclass(frozen=True, slots=True)
class AnalysisRunConfiguration:
    """Exact public-workflow arguments selected for the next GUI run."""

    profile: AnalysisProfile
    vacuum_wavelength_m: float
    detection_config: SignalDetectionConfig
    event_candidate_config: EventCandidateConfig
    background_guard_window_scale: float
    minimum_background_bin_count: int
    manual_event_reference_time_s: float | None
    assume_pre_event_zero_for_display: bool
    relative_db_floor: float
    source_path: Path


def _empty_records() -> Mapping[str, SignalRecord]:
    return MappingProxyType({})


def _empty_analyses() -> Mapping[str, ChannelAnalysis]:
    return MappingProxyType({})


@dataclass(slots=True)
class AnalysisSession:
    """Own the current source, configuration, results, and generation id."""

    source_path: Path | None = None
    records: Mapping[str, SignalRecord] = field(default_factory=_empty_records)
    analysis_range: AnalysisRange | None = None
    workflow_configuration: WorkflowConfiguration | None = None
    run_configuration: AnalysisRunConfiguration | None = None
    channel_analyses: Mapping[str, ChannelAnalysis] = field(
        default_factory=_empty_analyses
    )
    results_valid: bool = False
    generation_id: int = 0

    def load_records(
        self,
        *,
        source_path: Path,
        records: Mapping[str, SignalRecord],
    ) -> None:
        """Replace source records while retaining their immutable core objects."""
        if not records or not all(
            isinstance(name, str) and isinstance(record, SignalRecord)
            for name, record in records.items()
        ):
            raise TypeError("records must contain named SignalRecord values.")
        self.source_path = Path(source_path)
        self.records = MappingProxyType(dict(records))
        self.analysis_range = None
        self._invalidate()

    def set_analysis_range(self, value: AnalysisRange) -> None:
        """Confirm one range without slicing or replacing the raw records."""
        if not isinstance(value, AnalysisRange):
            raise TypeError("value must be an AnalysisRange.")
        start_bound, end_bound = self.data_bounds_s()
        tolerance = max(abs(end_bound - start_bound), 1.0) * 1e-12
        if (
            value.start_time_s < start_bound - tolerance
            or value.end_time_s > end_bound + tolerance
        ):
            raise ValueError("Analysis range must stay inside every channel.")
        normalized = AnalysisRange(
            max(value.start_time_s, start_bound),
            min(value.end_time_s, end_bound),
        )
        if normalized == self.analysis_range:
            return
        self.analysis_range = normalized
        self._invalidate()

    def set_workflow_configuration(
        self,
        configuration: WorkflowConfiguration,
        *,
        profile: AnalysisProfile,
    ) -> None:
        """Select explicit formal configuration while ignoring its input path."""
        if not isinstance(configuration, WorkflowConfiguration):
            raise TypeError("configuration must be a WorkflowConfiguration.")
        if profile not in configuration.analysis.profiles:
            raise ValueError("profile must be present in the workflow configuration.")
        self.workflow_configuration = configuration
        self.run_configuration = AnalysisRunConfiguration(
            profile=profile,
            vacuum_wavelength_m=configuration.analysis.vacuum_wavelength_m,
            detection_config=configuration.quality.signal_detection,
            event_candidate_config=configuration.event_candidate,
            background_guard_window_scale=(
                configuration.quality.background_guard_window_scale
            ),
            minimum_background_bin_count=(
                configuration.quality.minimum_background_bin_count
            ),
            manual_event_reference_time_s=(
                configuration.analysis.manual_event_reference_time_s
            ),
            assume_pre_event_zero_for_display=(
                configuration.plot.assume_pre_event_zero_for_display
            ),
            relative_db_floor=configuration.plot.relative_db_floor,
            source_path=configuration.config_path,
        )
        self._invalidate()

    def set_profile(self, profile: AnalysisProfile) -> None:
        """Change the formal profile and invalidate every downstream result."""
        if self.workflow_configuration is None or self.run_configuration is None:
            return
        if profile not in self.workflow_configuration.analysis.profiles:
            raise ValueError("profile must be present in the workflow configuration.")
        if profile == self.run_configuration.profile:
            return
        self.run_configuration = replace(self.run_configuration, profile=profile)
        self._invalidate()

    def set_vacuum_wavelength_m(self, value: float) -> None:
        """Change the explicit wavelength and invalidate downstream results."""
        if self.run_configuration is None:
            return
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("vacuum wavelength must be finite and positive.")
        if value == self.run_configuration.vacuum_wavelength_m:
            return
        self.run_configuration = replace(
            self.run_configuration,
            vacuum_wavelength_m=float(value),
        )
        self._invalidate()

    def accept_results(
        self,
        *,
        generation_id: int,
        analyses: Mapping[str, ChannelAnalysis],
    ) -> bool:
        """Accept only complete results from the current generation."""
        if generation_id != self.generation_id:
            return False
        if set(analyses) != set(self.records) or not all(
            isinstance(value, ChannelAnalysis) for value in analyses.values()
        ):
            raise ValueError("Analysis results must match every loaded channel.")
        self.channel_analyses = MappingProxyType(dict(analyses))
        self.results_valid = True
        return True

    def invalidate_results(self) -> None:
        """Publicly invalidate results after an upstream parameter change."""
        self._invalidate()

    def data_bounds_s(self) -> tuple[float, float]:
        """Return the common time-domain intersection for all channels."""
        if not self.records:
            raise RuntimeError("No records are loaded.")
        start = max(record.start_time_s for record in self.records.values())
        end = min(record.end_time_s for record in self.records.values())
        if start >= end:
            raise ValueError("Loaded channels do not share a non-empty time range.")
        return float(start), float(end)

    def _invalidate(self) -> None:
        self.generation_id += 1
        self.channel_analyses = _empty_analyses()
        self.results_valid = False


__all__ = [
    "AnalysisRange",
    "AnalysisRunConfiguration",
    "AnalysisSession",
]
