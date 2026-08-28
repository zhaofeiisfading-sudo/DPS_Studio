"""Background adapter for the public formal core workflow."""

from __future__ import annotations

import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import RidgeSearchConstraint
from dps_studio.core.time_frequency import STFTResult
from dps_studio.core.workflow import (
    ChannelAnalysis,
    analyze_stft_results,
    compute_configuration_stfts,
)
from dps_studio.gui.analysis_session import (
    AnalysisRange,
    AnalysisRunConfiguration,
    RidgeSearchRegion,
)


class AnalysisResultSource(str, Enum):
    """Source identity retained across the shared background adapter."""

    SPECTROGRAM = "spectrogram"
    AUTOMATIC = "automatic"
    GUIDED = "guided"


def _empty_constraints() -> Mapping[str, RidgeSearchConstraint]:
    return MappingProxyType({})


def _empty_stft_results() -> Mapping[str, STFTResult]:
    return MappingProxyType({})


def _empty_analyses() -> Mapping[str, ChannelAnalysis]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """Immutable arguments captured before a background workflow run."""

    generation_id: int
    records: Mapping[str, SignalRecord]
    analysis_range: AnalysisRange
    configuration: AnalysisRunConfiguration
    result_source: AnalysisResultSource = AnalysisResultSource.AUTOMATIC
    ridge_constraints: Mapping[str, RidgeSearchConstraint] = field(
        default_factory=_empty_constraints
    )
    stft_results: Mapping[str, STFTResult] = field(
        default_factory=_empty_stft_results
    )
    event_reference_time_s: float | None = None
    ridge_search_region: RidgeSearchRegion | None = None


@dataclass(frozen=True, slots=True)
class AnalysisRunResult:
    """One completed generation of per-channel formal results."""

    generation_id: int
    channel_analyses: Mapping[str, ChannelAnalysis]
    result_source: AnalysisResultSource = AnalysisResultSource.AUTOMATIC
    stft_results: Mapping[str, STFTResult] = field(
        default_factory=_empty_stft_results
    )
    ridge_search_region: RidgeSearchRegion | None = None


class _WorkerSignals(QObject):
    started = Signal(int)
    finished = Signal(object)
    failed = Signal(int, str, str, str)


class _AnalysisWorker(QRunnable):
    def __init__(self, request: AnalysisRequest) -> None:
        super().__init__()
        self.request = request
        self.signals = _WorkerSignals()

    @Slot()
    def run(self) -> None:
        """Call only the public core workflow; never touch a QWidget."""
        request = self.request
        self.signals.started.emit(request.generation_id)
        region: RidgeSearchRegion | None = None
        try:
            configuration = request.configuration
            parameters = configuration.parameters
            event_reference_time_s = (
                request.event_reference_time_s
                if request.event_reference_time_s is not None
                else configuration.event_reference_time_s
            )
            if request.result_source is AnalysisResultSource.SPECTROGRAM:
                stft_results = compute_configuration_stfts(
                    request.records,
                    window_length_samples=parameters.window_length_samples,
                    overlap_samples=parameters.overlap_samples,
                    nfft=parameters.nfft,
                    window_name=parameters.window_name,
                )
                analyses = _empty_analyses()
            else:
                stft_results = (
                    request.stft_results
                    if request.stft_results
                    else compute_configuration_stfts(
                        request.records,
                        window_length_samples=parameters.window_length_samples,
                        overlap_samples=parameters.overlap_samples,
                        nfft=parameters.nfft,
                        window_name=parameters.window_name,
                    )
                )
                region = request.ridge_search_region or _default_ridge_search_region(
                    stft_results,
                    minimum_frequency_hz=parameters.minimum_frequency_hz,
                    maximum_frequency_hz=parameters.maximum_frequency_hz,
                )
                analyses = analyze_stft_results(
                    stft_results,
                    minimum_frequency_hz=region.frequency_min_hz,
                    maximum_frequency_hz=region.frequency_max_hz,
                    profile_name=parameters.provenance_name,
                    analysis_start_time_s=region.time_start_s,
                    analysis_end_time_s=region.time_end_s,
                    manual_event_reference_time_s=event_reference_time_s,
                    vacuum_wavelength_m=configuration.vacuum_wavelength_m,
                    detection_config=configuration.detection_config,
                    event_candidate_config=configuration.event_candidate_config,
                    automatic_ridge_selection_config=(
                        configuration.automatic_ridge_selection_config
                    ),
                    velocity_correction_config=(
                        configuration.velocity_correction_config
                    ),
                    background_guard_window_scale=(
                        configuration.background_guard_window_scale
                    ),
                    minimum_background_bin_count=(
                        configuration.minimum_background_bin_count
                    ),
                    assume_pre_event_zero_for_display=(
                        configuration.enable_pre_event_display
                    ),
                    pre_event_display_velocity_m_s=(
                        configuration.pre_event_display_velocity_m_s
                    ),
                    ridge_constraints=request.ridge_constraints,
                )
        except Exception as exc:
            self.signals.failed.emit(
                request.generation_id,
                type(exc).__name__,
                str(exc),
                traceback.format_exc(),
            )
            return
        self.signals.finished.emit(
            AnalysisRunResult(
                request.generation_id,
                analyses,
                request.result_source,
                stft_results,
                region,
            )
        )


def _default_ridge_search_region(
    stft_results: Mapping[str, STFTResult],
    *,
    minimum_frequency_hz: float,
    maximum_frequency_hz: float,
) -> RidgeSearchRegion:
    """Resolve the same clamped default used after an explicit STFT run."""
    time_start = max(float(result.time_s[0]) for result in stft_results.values())
    time_end = min(float(result.time_s[-1]) for result in stft_results.values())
    axis_min = max(float(result.frequency_hz[0]) for result in stft_results.values())
    axis_max = min(float(result.frequency_hz[-1]) for result in stft_results.values())
    frequency_min = max(float(minimum_frequency_hz), axis_min)
    frequency_max = min(float(maximum_frequency_hz), axis_max)
    if frequency_min >= frequency_max:
        frequency_min, frequency_max = axis_min, axis_max
    return RidgeSearchRegion(
        time_start_s=time_start,
        time_end_s=time_end,
        frequency_min_hz=frequency_min,
        frequency_max_hz=frequency_max,
    )


class AutomaticAnalysisAdapter(QObject):
    """Own a single background run and forward results to the GUI thread."""

    started = Signal(int)
    finished = Signal(object)
    failed = Signal(int, str, str, str)
    busy_changed = Signal(bool)

    def __init__(
        self,
        parent: QObject | None = None,
        *,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(parent)
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._worker: _AnalysisWorker | None = None
        self._busy = False

    @property
    def busy(self) -> bool:
        """Return whether the adapter currently owns an unfinished run."""
        return self._busy

    def start(self, request: AnalysisRequest) -> bool:
        """Start one run and reject duplicate launches while it is active."""
        if self._busy:
            return False
        if not isinstance(request, AnalysisRequest):
            raise TypeError("request must be an AnalysisRequest.")
        worker = _AnalysisWorker(request)
        worker.signals.started.connect(self.started)
        worker.signals.finished.connect(self._handle_finished)
        worker.signals.failed.connect(self._handle_failed)
        self._worker = worker
        self._busy = True
        self.busy_changed.emit(True)
        self._thread_pool.start(worker)
        return True

    @Slot(object)
    def _handle_finished(self, result: object) -> None:
        self._complete()
        self.finished.emit(result)

    @Slot(int, str, str, str)
    def _handle_failed(
        self,
        generation_id: int,
        error_type: str,
        message: str,
        traceback_text: str,
    ) -> None:
        self._complete()
        self.failed.emit(generation_id, error_type, message, traceback_text)

    def _complete(self) -> None:
        self._worker = None
        self._busy = False
        self.busy_changed.emit(False)


__all__ = [
    "AnalysisRequest",
    "AnalysisResultSource",
    "AnalysisRunResult",
    "AutomaticAnalysisAdapter",
]
