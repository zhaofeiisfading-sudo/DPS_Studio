"""Background adapter for the public formal core workflow."""

from __future__ import annotations

import traceback
from collections.abc import Mapping
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from dps_studio.core.models import SignalRecord
from dps_studio.core.workflow import ChannelAnalysis, analyze_profile
from dps_studio.gui.analysis_session import (
    AnalysisRange,
    AnalysisRunConfiguration,
)


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """Immutable arguments captured before a background workflow run."""

    generation_id: int
    records: Mapping[str, SignalRecord]
    analysis_range: AnalysisRange
    configuration: AnalysisRunConfiguration


@dataclass(frozen=True, slots=True)
class AnalysisRunResult:
    """One completed generation of per-channel formal results."""

    generation_id: int
    channel_analyses: Mapping[str, ChannelAnalysis]


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
        try:
            configuration = request.configuration
            analyses = analyze_profile(
                request.records,
                profile=configuration.profile,
                analysis_start_time_s=request.analysis_range.start_time_s,
                analysis_end_time_s=request.analysis_range.end_time_s,
                manual_event_reference_time_s=(
                    configuration.manual_event_reference_time_s
                ),
                vacuum_wavelength_m=configuration.vacuum_wavelength_m,
                detection_config=configuration.detection_config,
                event_candidate_config=configuration.event_candidate_config,
                background_guard_window_scale=(
                    configuration.background_guard_window_scale
                ),
                minimum_background_bin_count=(
                    configuration.minimum_background_bin_count
                ),
                assume_pre_event_zero_for_display=(
                    configuration.assume_pre_event_zero_for_display
                ),
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
            AnalysisRunResult(request.generation_id, analyses)
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
    "AnalysisRunResult",
    "AutomaticAnalysisAdapter",
]
