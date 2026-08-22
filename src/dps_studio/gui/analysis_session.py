"""In-memory GUI session state for formal automatic analysis."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from dps_studio.core.analysis_profiles import (
    AnalysisParameterOverrides,
    AnalysisProfile,
    AnalysisRunParameters,
    build_analysis_run_parameters,
)
from dps_studio.core.event_candidates import EventCandidateConfig
from dps_studio.core.export import ExportTimeOrigin
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics import VelocityCorrectionConfig
from dps_studio.core.quality import SignalDetectionConfig
from dps_studio.core.ridge import (
    AutomaticRidgeExtractionMode,
    AutomaticRidgeSelectionConfig,
    ManualFrequencyRegion,
    RidgeCorridorConstraint,
    RidgeSearchConstraint,
)
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import (
    ChannelAnalysis,
    WorkflowConfiguration,
    configure_channel_display_velocity,
    configure_channel_event_reference,
    configure_channel_velocity_correction,
)


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


class RidgeExtractionMode(str, Enum):
    """The explicit GUI-selected source for the ridge workspace."""

    AUTOMATIC = "automatic"
    GUIDED = "guided"


class EventTimeSource(str, Enum):
    """User-selected source for the resolved event-time workflow."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class AnalysisRunConfiguration:
    """Exact public-workflow arguments selected for the next GUI run."""

    parameters: AnalysisRunParameters
    detection_config: SignalDetectionConfig
    event_candidate_config: EventCandidateConfig
    automatic_ridge_selection_config: AutomaticRidgeSelectionConfig
    velocity_correction_config: VelocityCorrectionConfig
    background_guard_window_scale: float
    minimum_background_bin_count: int
    event_reference_time_s: float | None
    enable_pre_event_display: bool
    pre_event_display_velocity_m_s: float
    relative_db_floor: float
    source_path: Path

    @property
    def base_profile(self) -> AnalysisProfile:
        """Return the immutable preset on which this run is based."""
        return self.parameters.base_profile

    @property
    def profile(self) -> AnalysisProfile | None:
        """Return the exact preset only when no custom overrides are active."""
        return None if self.parameters.is_custom else self.parameters.base_profile

    @property
    def preset_name(self) -> str:
        """Return the immutable base preset name for provenance."""
        return self.parameters.preset_name

    @property
    def custom_status(self) -> bool:
        """Return whether the current run has explicit per-session overrides."""
        return self.parameters.is_custom

    @property
    def custom_overrides(self) -> Mapping[str, int | float | str]:
        """Return immutable explicit override values."""
        return self.parameters.custom_overrides

    @property
    def final_run_configuration(self) -> AnalysisRunParameters:
        """Return the validated values captured by the next request."""
        return self.parameters

    @property
    def vacuum_wavelength_m(self) -> float:
        """Return the validated per-run wavelength in SI metres."""
        return self.parameters.vacuum_wavelength_m

    @property
    def manual_event_reference_time_s(self) -> float | None:
        """Compatibility alias used only when calling the current core API."""
        return self.event_reference_time_s


def _empty_records() -> Mapping[str, SignalRecord]:
    return MappingProxyType({})


def _empty_analyses() -> Mapping[str, ChannelAnalysis]:
    return MappingProxyType({})


def _empty_constraints() -> Mapping[str, RidgeSearchConstraint]:
    return MappingProxyType({})


def _empty_stft_results() -> Mapping[str, STFTResult]:
    return MappingProxyType({})


@dataclass(slots=True)
class AnalysisSession:
    """Own the current source, configuration, results, and generation id."""

    source_path: Path | None = None
    records: Mapping[str, SignalRecord] = field(default_factory=_empty_records)
    analysis_range: AnalysisRange | None = None
    workflow_configuration: WorkflowConfiguration | None = None
    run_configuration: AnalysisRunConfiguration | None = None
    stft_results: Mapping[str, STFTResult] = field(
        default_factory=_empty_stft_results
    )
    channel_analyses: Mapping[str, ChannelAnalysis] = field(
        default_factory=_empty_analyses
    )
    guided_channel_analyses: Mapping[str, ChannelAnalysis] = field(
        default_factory=_empty_analyses
    )
    ridge_constraints: Mapping[str, RidgeSearchConstraint] = field(
        default_factory=_empty_constraints
    )
    stft_valid: bool = False
    results_valid: bool = False
    guided_results_valid: bool = False
    guided_results_stale: bool = False
    guided_result_valid_channels: frozenset[str] = field(default_factory=frozenset)
    guided_result_stale_channels: frozenset[str] = field(default_factory=frozenset)
    ridge_extraction_mode: RidgeExtractionMode = RidgeExtractionMode.AUTOMATIC
    event_time_source: EventTimeSource = EventTimeSource.AUTOMATIC
    automatic_event_reference_times_s: Mapping[str, float | None] = field(
        default_factory=dict
    )
    automatic_event_reference_sources: Mapping[str, str | None] = field(
        default_factory=dict
    )
    generation_id: int = 0
    guided_generation_id: int = 0
    event_reference_source: str | None = None
    rejected_event_reference_time_s: float | None = None
    export_time_origin: ExportTimeOrigin = ExportTimeOrigin.EVENT

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
        self.ridge_constraints = _empty_constraints()
        self.event_time_source = EventTimeSource.AUTOMATIC
        self.automatic_event_reference_times_s = MappingProxyType({})
        self.automatic_event_reference_sources = MappingProxyType({})
        self.export_time_origin = ExportTimeOrigin.EVENT
        self._reset_event_reference_for_current_records()
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
        self._clear_reference_outside_current_domain()
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
            parameters=build_analysis_run_parameters(
                base_profile=profile,
                base_vacuum_wavelength_m=(
                    configuration.analysis.vacuum_wavelength_m
                ),
            ),
            detection_config=configuration.quality.signal_detection,
            event_candidate_config=configuration.event_candidate,
            automatic_ridge_selection_config=(
                configuration.automatic_ridge_selection
            ),
            velocity_correction_config=configuration.velocity_correction,
            background_guard_window_scale=(
                configuration.quality.background_guard_window_scale
            ),
            minimum_background_bin_count=(
                configuration.quality.minimum_background_bin_count
            ),
            event_reference_time_s=(
                configuration.analysis.event_reference_time_s
            ),
            enable_pre_event_display=(
                configuration.plot.assume_pre_event_zero_for_display
            ),
            pre_event_display_velocity_m_s=(
                configuration.plot.pre_event_display_velocity_m_s
            ),
            relative_db_floor=configuration.plot.relative_db_floor,
            source_path=configuration.config_path,
        )
        self.event_reference_source = (
            "configuration"
            if configuration.analysis.event_reference_time_s is not None
            else None
        )
        self.event_time_source = (
            EventTimeSource.MANUAL
            if configuration.analysis.event_reference_time_s is not None
            else EventTimeSource.AUTOMATIC
        )
        self.rejected_event_reference_time_s = None
        self._reset_event_reference_for_current_records()
        self._invalidate()

    def set_profile(self, profile: AnalysisProfile) -> None:
        """Restore one immutable profile and clear all per-run overrides."""
        if self.workflow_configuration is None or self.run_configuration is None:
            return
        if profile not in self.workflow_configuration.analysis.profiles:
            raise ValueError("profile must be present in the workflow configuration.")
        parameters = build_analysis_run_parameters(
            base_profile=profile,
            base_vacuum_wavelength_m=(
                self.workflow_configuration.analysis.vacuum_wavelength_m
            ),
        )
        if parameters == self.run_configuration.parameters:
            return
        self.run_configuration = replace(
            self.run_configuration,
            parameters=parameters,
        )
        self._invalidate()

    def set_analysis_overrides(
        self,
        overrides: AnalysisParameterOverrides,
    ) -> bool:
        """Resolve explicit session overrides without mutating their base preset."""
        if self.run_configuration is None:
            return False
        if not isinstance(overrides, AnalysisParameterOverrides):
            raise TypeError("overrides must be an AnalysisParameterOverrides.")
        current = self.run_configuration.parameters
        parameters = build_analysis_run_parameters(
            base_profile=current.base_profile,
            base_vacuum_wavelength_m=current.base_vacuum_wavelength_m,
            overrides=overrides,
        )
        if parameters == current:
            return False
        self.run_configuration = replace(
            self.run_configuration,
            parameters=parameters,
        )
        stft_fields = (
            "window_length_samples",
            "overlap_samples",
            "nfft",
            "window_name",
        )
        if any(getattr(parameters, name) != getattr(current, name) for name in stft_fields):
            self._invalidate()
        else:
            self._invalidate_downstream()
        return True

    def set_automatic_ridge_extraction_mode(
        self,
        mode: AutomaticRidgeExtractionMode,
    ) -> bool:
        """Change Automatic selection mode and invalidate downstream products."""
        if self.run_configuration is None:
            return False
        if not isinstance(mode, AutomaticRidgeExtractionMode):
            raise TypeError("mode must be an AutomaticRidgeExtractionMode.")
        current = self.run_configuration.automatic_ridge_selection_config
        if mode is current.mode:
            return False
        self.run_configuration = replace(
            self.run_configuration,
            automatic_ridge_selection_config=replace(current, mode=mode),
        )
        self._invalidate_downstream()
        return True

    def set_vacuum_wavelength_m(self, value: float) -> None:
        """Compatibility helper for one explicit wavelength override."""
        if self.run_configuration is None:
            return
        if not math.isfinite(value) or value <= 0.0:
            raise ValueError("vacuum wavelength must be finite and positive.")
        current = self.run_configuration.parameters.overrides
        self.set_analysis_overrides(
            replace(current, vacuum_wavelength_m=float(value)),
        )

    def set_velocity_correction_config(
        self,
        config: VelocityCorrectionConfig,
    ) -> bool:
        """Rebuild correction/display arrays without rerunning upstream analysis."""
        if self.run_configuration is None:
            return False
        if not isinstance(config, VelocityCorrectionConfig):
            raise TypeError("config must be a VelocityCorrectionConfig.")
        if config == self.run_configuration.velocity_correction_config:
            return False
        self.run_configuration = replace(
            self.run_configuration,
            velocity_correction_config=config,
        )
        self._refresh_velocity_correction_results()
        return True

    def set_export_time_origin(self, time_origin: ExportTimeOrigin) -> bool:
        """Store the session's explicit export/display time-coordinate choice."""
        if not isinstance(time_origin, ExportTimeOrigin):
            raise TypeError("time_origin must be an ExportTimeOrigin.")
        if time_origin is self.export_time_origin:
            return False
        self.export_time_origin = time_origin
        return True

    def set_display_velocity_configuration(
        self,
        *,
        enabled: bool,
        pre_event_display_velocity_m_s: float,
    ) -> bool:
        """Refresh only display arrays without invalidating formal results."""
        if self.run_configuration is None:
            return False
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean.")
        if (
            isinstance(pre_event_display_velocity_m_s, bool)
            or not math.isfinite(pre_event_display_velocity_m_s)
        ):
            raise ValueError(
                "pre-event display velocity must be a finite value in m/s."
            )
        value = float(pre_event_display_velocity_m_s)
        changed = (
            enabled != self.run_configuration.enable_pre_event_display
            or value
            != self.run_configuration.pre_event_display_velocity_m_s
        )
        if not changed:
            return False
        self.run_configuration = replace(
            self.run_configuration,
            enable_pre_event_display=enabled,
            pre_event_display_velocity_m_s=value,
        )
        self._refresh_display_velocity_only()
        return True

    @property
    def event_reference_time_s(self) -> float | None:
        """Return the current resolved reference for the first available channel."""
        if self.run_configuration is None:
            return None
        if self.event_time_source is EventTimeSource.MANUAL:
            return self.run_configuration.event_reference_time_s
        return next(
            (
                value
                for value in self.automatic_event_reference_times_s.values()
                if value is not None
            ),
            None,
        )

    def resolved_event_time_s(self, channel_name: str) -> float | None:
        """Return the manual override or production shared automatic event."""
        if self.run_configuration is None:
            return None
        if self.event_time_source is EventTimeSource.MANUAL:
            return self.run_configuration.event_reference_time_s
        return self.automatic_event_reference_times_s.get(channel_name)

    def resolved_event_source(self, channel_name: str) -> str | None:
        """Return auditable manual/formal/fallback event provenance."""
        if self.event_time_source is EventTimeSource.MANUAL:
            return self.event_reference_source
        return self.automatic_event_reference_sources.get(channel_name)

    @property
    def manual_event_override_enabled(self) -> bool:
        return self.event_time_source is EventTimeSource.MANUAL

    def set_event_reference_time_s(
        self,
        value: float,
        *,
        source: str = "manual",
    ) -> bool:
        """Set a validated display/review reference without rerunning STFT."""
        if self.run_configuration is None:
            raise RuntimeError("Analysis configuration is not loaded.")
        if isinstance(value, bool) or not math.isfinite(value):
            raise ValueError("Event reference time must be finite seconds.")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("Event reference source must be a non-empty string.")
        reference = float(value)
        if not self._reference_is_valid_for_current_records(reference):
            raise ValueError(
                "Event reference time must stay inside the current data and "
                "confirmed analysis ranges."
            )
        reference_changed = (
            reference != self.run_configuration.event_reference_time_s
        )
        mode_changed = self.event_time_source is not EventTimeSource.MANUAL
        normalized_source = source.strip()
        source_changed = normalized_source != self.event_reference_source
        self.run_configuration = replace(
            self.run_configuration,
            event_reference_time_s=reference,
        )
        self.event_time_source = EventTimeSource.MANUAL
        self.event_reference_source = normalized_source
        self.rejected_event_reference_time_s = None
        if reference_changed or source_changed or mode_changed:
            self._refresh_display_results()
        return reference_changed or source_changed or mode_changed

    def clear_event_reference(self) -> bool:
        """Unset the display/review reference without changing formal results."""
        if self.run_configuration is None:
            return False
        previous = self.run_configuration.event_reference_time_s
        was_manual = self.event_time_source is EventTimeSource.MANUAL
        if previous is None and not was_manual:
            return False
        self.run_configuration = replace(
            self.run_configuration,
            event_reference_time_s=None,
        )
        self.event_reference_source = None
        self.event_time_source = EventTimeSource.AUTOMATIC
        self.rejected_event_reference_time_s = None
        self._refresh_display_results()
        return previous is not None or was_manual

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
        self.stft_results = MappingProxyType(
            {name: analysis.stft_result for name, analysis in analyses.items()}
        )
        self.stft_valid = True
        self.results_valid = True
        reference_channel = (
            "pdv_channel_1" if "pdv_channel_1" in analyses else next(iter(analyses))
        )
        shared_reference, shared_source = _automatic_event_resolution(
            analyses[reference_channel],
            reference_channel=reference_channel,
        )
        self.automatic_event_reference_times_s = MappingProxyType(
            {channel_name: shared_reference for channel_name in analyses}
        )
        self.automatic_event_reference_sources = MappingProxyType(
            {channel_name: shared_source for channel_name in analyses}
        )
        self._refresh_display_results()
        return True

    def accept_stft_results(
        self,
        *,
        generation_id: int,
        stft_results: Mapping[str, STFTResult],
    ) -> bool:
        """Accept only complete STFT results from the current generation."""
        if generation_id != self.generation_id:
            return False
        if set(stft_results) != set(self.records) or not all(
            isinstance(value, STFTResult) for value in stft_results.values()
        ):
            raise ValueError("STFT results must match every loaded channel.")
        self.stft_results = MappingProxyType(dict(stft_results))
        self.stft_valid = True
        return True

    @property
    def automatic_channel_analyses(self) -> Mapping[str, ChannelAnalysis]:
        """Return formal automatic results under an explicit source name."""
        return self.channel_analyses

    @property
    def valid_guided_channel_analyses(self) -> Mapping[str, ChannelAnalysis]:
        """Return only channels whose current Guided result is still valid."""
        return MappingProxyType(
            {
                channel_name: analysis
                for channel_name, analysis in self.guided_channel_analyses.items()
                if channel_name in self.guided_result_valid_channels
            }
        )

    @property
    def automatic_results_available(self) -> bool:
        """Return whether a complete current automatic result set exists."""
        return self.results_valid and bool(self.channel_analyses)

    @property
    def guided_results_available(self) -> bool:
        """Return whether any channel has a current Guided result."""
        return bool(self.guided_result_valid_channels)

    @property
    def any_formal_results_available(self) -> bool:
        """Return whether either independent result source is currently usable."""
        return self.automatic_results_available or self.guided_results_available

    def guided_result_is_valid(self, channel_name: str) -> bool:
        """Return whether one channel has a current Guided result."""
        return channel_name in self.guided_result_valid_channels

    def guided_result_is_stale(self, channel_name: str) -> bool:
        """Return whether one channel's prior Guided result needs rerunning."""
        return channel_name in self.guided_result_stale_channels

    def set_ridge_extraction_mode(self, value: RidgeExtractionMode) -> bool:
        """Store the mode selected by the Ridge UI without changing science data."""
        if not isinstance(value, RidgeExtractionMode):
            raise TypeError("value must be a RidgeExtractionMode.")
        if value is self.ridge_extraction_mode:
            return False
        self.ridge_extraction_mode = value
        return True

    def accept_guided_results(
        self,
        *,
        generation_id: int,
        analyses: Mapping[str, ChannelAnalysis],
    ) -> bool:
        """Accept guided results without replacing the automatic result set."""
        if generation_id != self.guided_generation_id:
            return False
        if not analyses or not set(analyses).issubset(self.records) or not all(
            isinstance(value, ChannelAnalysis) for value in analyses.values()
        ):
            raise ValueError("Guided results must match constrained loaded channels.")
        merged = dict(self.guided_channel_analyses)
        merged.update(analyses)
        self.guided_channel_analyses = MappingProxyType(merged)
        if self.event_time_source is EventTimeSource.AUTOMATIC:
            references = dict(self.automatic_event_reference_times_s)
            sources = dict(self.automatic_event_reference_sources)
            for channel_name, analysis in analyses.items():
                references.setdefault(
                    channel_name,
                    analysis.signal_detection_result.manual_event_reference_time_s,
                )
                sources.setdefault(
                    channel_name,
                    analysis.event_aware_continuity_result.event_reference_source,
                )
            self.automatic_event_reference_times_s = MappingProxyType(references)
            self.automatic_event_reference_sources = MappingProxyType(sources)
        valid_channels = set(self.guided_result_valid_channels)
        valid_channels.update(analyses)
        stale_channels = set(self.guided_result_stale_channels)
        stale_channels.difference_update(analyses)
        self._set_guided_result_state(valid_channels, stale_channels)
        return True

    def set_ridge_constraint(
        self,
        channel_name: str,
        constraint: RidgeSearchConstraint,
    ) -> bool:
        """Set one channel-local search constraint and stale only its result."""
        if channel_name not in self.records:
            raise ValueError(f"Unknown channel {channel_name!r}.")
        if not isinstance(
            constraint,
            (RidgeCorridorConstraint, ManualFrequencyRegion),
        ):
            raise TypeError(
                "constraint must be a RidgeCorridorConstraint or "
                "ManualFrequencyRegion."
            )
        previous = self.ridge_constraints.get(channel_name)
        if previous is constraint:
            return False
        constraints = dict(self.ridge_constraints)
        constraints[channel_name] = constraint
        self.ridge_constraints = MappingProxyType(constraints)
        self._stale_guided_result(channel_name)
        return True

    def clear_ridge_constraint(self, channel_name: str) -> bool:
        """Remove one channel-local corridor and stale only guided results."""
        if channel_name not in self.records:
            raise ValueError(f"Unknown channel {channel_name!r}.")
        if channel_name not in self.ridge_constraints:
            return False
        constraints = dict(self.ridge_constraints)
        del constraints[channel_name]
        self.ridge_constraints = MappingProxyType(constraints)
        self._stale_guided_result(channel_name)
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
        self.guided_generation_id += 1
        self.stft_results = _empty_stft_results()
        self.channel_analyses = _empty_analyses()
        self.guided_channel_analyses = _empty_analyses()
        self.automatic_event_reference_times_s = MappingProxyType({})
        self.automatic_event_reference_sources = MappingProxyType({})
        self.stft_valid = False
        self.results_valid = False
        self._set_guided_result_state((), ())

    def _invalidate_downstream(self) -> None:
        """Invalidate ridge/velocity products while preserving reusable STFT."""
        self.generation_id += 1
        self.guided_generation_id += 1
        self.channel_analyses = _empty_analyses()
        self.guided_channel_analyses = _empty_analyses()
        self.automatic_event_reference_times_s = MappingProxyType({})
        self.automatic_event_reference_sources = MappingProxyType({})
        self.results_valid = False
        self._set_guided_result_state((), ())

    def _stale_guided_results(self) -> None:
        """Mark every extant Guided result stale after a shared dependency change."""
        self.guided_generation_id += 1
        self._set_guided_result_state(
            (),
            self.guided_channel_analyses,
        )

    def _stale_guided_result(self, channel_name: str) -> None:
        """Invalidate one channel without hiding independent Guided channels."""
        self.guided_generation_id += 1
        valid_channels = set(self.guided_result_valid_channels)
        valid_channels.discard(channel_name)
        stale_channels = set(self.guided_result_stale_channels)
        if channel_name in self.guided_channel_analyses:
            stale_channels.add(channel_name)
        self._set_guided_result_state(valid_channels, stale_channels)

    def _set_guided_result_state(
        self,
        valid_channels: Iterable[str],
        stale_channels: Iterable[str],
    ) -> None:
        """Synchronize legacy aggregate flags with channel-local status sets."""
        valid = frozenset(valid_channels)
        stale = frozenset(stale_channels)
        self.guided_result_valid_channels = valid
        self.guided_result_stale_channels = stale
        self.guided_results_valid = bool(valid)
        self.guided_results_stale = bool(stale)

    def _refresh_display_results(self) -> None:
        configuration = self.run_configuration
        if configuration is None:
            return

        def resolved_reference(
            channel_name: str,
            analysis: ChannelAnalysis,
        ) -> float | None:
            if self.event_time_source is EventTimeSource.MANUAL:
                return configuration.event_reference_time_s
            automatic = self.automatic_event_reference_times_s.get(channel_name)
            if automatic is not None:
                return automatic
            return analysis.signal_detection_result.manual_event_reference_time_s

        if self.channel_analyses:
            self.channel_analyses = MappingProxyType(
                {
                    channel_name: configure_channel_event_reference(
                        analysis,
                        event_reference_time_s=resolved_reference(
                            channel_name, analysis
                        ),
                        event_reference_source=(
                            self.event_reference_source
                            if self.event_time_source is EventTimeSource.MANUAL
                            else self.automatic_event_reference_sources.get(
                                channel_name
                            )
                        ),
                        enable_pre_event_display=(
                            configuration.enable_pre_event_display
                        ),
                        pre_event_display_velocity_m_s=(
                            configuration.pre_event_display_velocity_m_s
                        ),
                    )
                    for channel_name, analysis in self.channel_analyses.items()
                }
            )
        if self.guided_channel_analyses:
            self.guided_channel_analyses = MappingProxyType(
                {
                    channel_name: configure_channel_event_reference(
                        analysis,
                        event_reference_time_s=resolved_reference(
                            channel_name, analysis
                        ),
                        event_reference_source=(
                            self.event_reference_source
                            if self.event_time_source is EventTimeSource.MANUAL
                            else self.automatic_event_reference_sources.get(
                                channel_name
                            )
                        ),
                        enable_pre_event_display=(
                            configuration.enable_pre_event_display
                        ),
                        pre_event_display_velocity_m_s=(
                            configuration.pre_event_display_velocity_m_s
                        ),
                    )
                    for channel_name, analysis in self.guided_channel_analyses.items()
                }
            )

    def _refresh_display_velocity_only(self) -> None:
        """Rebuild display arrays while preserving every upstream object."""
        configuration = self.run_configuration
        if configuration is None:
            return

        def refreshed(analysis: ChannelAnalysis) -> ChannelAnalysis:
            return configure_channel_display_velocity(
                analysis,
                enable_pre_event_display=configuration.enable_pre_event_display,
                pre_event_display_velocity_m_s=(
                    configuration.pre_event_display_velocity_m_s
                ),
            )

        if self.channel_analyses:
            self.channel_analyses = MappingProxyType(
                {
                    channel_name: refreshed(analysis)
                    for channel_name, analysis in self.channel_analyses.items()
                }
            )
        if self.guided_channel_analyses:
            self.guided_channel_analyses = MappingProxyType(
                {
                    channel_name: refreshed(analysis)
                    for channel_name, analysis in self.guided_channel_analyses.items()
                }
            )

    def _refresh_velocity_correction_results(self) -> None:
        configuration = self.run_configuration
        if configuration is None:
            return

        def refreshed(analysis: ChannelAnalysis) -> ChannelAnalysis:
            return configure_channel_velocity_correction(
                analysis,
                velocity_correction_config=(
                    configuration.velocity_correction_config
                ),
                vacuum_wavelength_m=configuration.vacuum_wavelength_m,
                enable_pre_event_display=configuration.enable_pre_event_display,
                pre_event_display_velocity_m_s=(
                    configuration.pre_event_display_velocity_m_s
                ),
            )

        if self.channel_analyses:
            self.channel_analyses = MappingProxyType(
                {
                    channel_name: refreshed(analysis)
                    for channel_name, analysis in self.channel_analyses.items()
                }
            )
        if self.guided_channel_analyses:
            self.guided_channel_analyses = MappingProxyType(
                {
                    channel_name: refreshed(analysis)
                    for channel_name, analysis in self.guided_channel_analyses.items()
                }
            )

    def _reset_event_reference_for_current_records(self) -> None:
        configuration = self.workflow_configuration
        run_configuration = self.run_configuration
        if configuration is None or run_configuration is None:
            self.event_reference_source = None
            self.rejected_event_reference_time_s = None
            return
        configured = configuration.analysis.event_reference_time_s
        if configured is None:
            self.run_configuration = replace(
                run_configuration,
                event_reference_time_s=None,
            )
            self.event_reference_source = None
            self.event_time_source = EventTimeSource.AUTOMATIC
            self.rejected_event_reference_time_s = None
            return
        if self.records and not self._reference_is_valid_for_current_records(
            configured
        ):
            self.run_configuration = replace(
                run_configuration,
                event_reference_time_s=None,
            )
            self.event_reference_source = None
            self.event_time_source = EventTimeSource.AUTOMATIC
            self.rejected_event_reference_time_s = configured
            return
        self.run_configuration = replace(
            run_configuration,
            event_reference_time_s=configured,
        )
        self.event_reference_source = "configuration"
        self.event_time_source = EventTimeSource.MANUAL
        self.rejected_event_reference_time_s = None

    def _clear_reference_outside_current_domain(self) -> None:
        run_configuration = self.run_configuration
        if run_configuration is None:
            return
        reference = run_configuration.event_reference_time_s
        if reference is None or self._reference_is_valid_for_current_records(
            reference
        ):
            return
        self.run_configuration = replace(
            run_configuration,
            event_reference_time_s=None,
        )
        self.event_reference_source = None
        self.event_time_source = EventTimeSource.AUTOMATIC
        self.rejected_event_reference_time_s = reference

    def _reference_is_valid_for_current_records(self, value: float) -> bool:
        if not self.records:
            return True
        start, end = self.data_bounds_s()
        tolerance = max(abs(end - start), 1.0) * 1e-12
        if value < start - tolerance or value > end + tolerance:
            return False
        if self.analysis_range is None:
            return True
        return (
            self.analysis_range.start_time_s - tolerance
            <= value
            <= self.analysis_range.end_time_s + tolerance
        )


def _automatic_event_resolution(
    analysis: ChannelAnalysis,
    *,
    reference_channel: str,
) -> tuple[float | None, str | None]:
    """Resolve an existing formal event or detector candidate without invention."""
    formal = analysis.stream_event_candidates.primary_candidate_time_s
    if formal is not None:
        return formal, f"automatic_formal_event:{reference_channel}"
    fallback = analysis.signal_detection_result.detected_event_candidate_time_s
    if fallback is not None:
        return fallback, f"automatic_low_confidence_fallback:{reference_channel}"
    return None, None


__all__ = [
    "AnalysisRange",
    "AnalysisRunConfiguration",
    "AnalysisSession",
    "EventTimeSource",
    "RidgeExtractionMode",
]
