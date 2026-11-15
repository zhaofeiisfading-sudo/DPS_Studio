"""Cooperative diagnostic job with a GUI-owned, fully joined thread lifetime."""

from __future__ import annotations

import gc
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from dps_studio.core.diagnostics import (
    DiagnosticBundle,
    DiagnosticCancelledError,
    DiagnosticComputeMode,
    StageSegment,
    compute_diagnostic_bundle,
    load_precomputed_bundle,
)
from dps_studio.core.models import SignalRecord

_collection_holds = 0
_collection_was_enabled = False


def _hold_collection() -> None:
    """Keep cyclic Qt wrapper finalizers out of the numerical Python thread.

    Pyqtgraph scenes can leave Python cycles after Qt deferred deletion. Automatic
    GC runs in whichever Python thread allocates next, including a core estimator.
    Reference counting remains active; defer only cyclic collection until join.
    All callers are GUI-owned. The counter supports multiple standalone runners.
    """
    global _collection_holds, _collection_was_enabled
    if _collection_holds == 0:
        _collection_was_enabled = gc.isenabled()
        gc.collect()
        gc.disable()
    _collection_holds += 1


def _release_collection() -> None:
    global _collection_holds
    _collection_holds -= 1
    if _collection_holds == 0:
        if _collection_was_enabled:
            gc.enable()
        gc.collect()


class DiagnosticWorker(QObject):
    progress = Signal(str)
    finished = Signal(object)
    cancelled = Signal()
    failed = Signal(str)
    stopped = Signal()

    def __init__(
        self,
        record: SignalRecord,
        channel: str,
        source_path: Path | None,
        mode: DiagnosticComputeMode,
        stages: tuple[StageSegment, ...],
        repo_root: Path,
        cancel_event: Event,
        frozen: bool,
    ) -> None:
        super().__init__()
        self.record, self.channel, self.source_path = record, channel, source_path
        self.mode, self.stages, self.repo_root = mode, stages, repo_root
        self.cancel_event, self.frozen = cancel_event, frozen

    @Slot()
    def run(self) -> None:
        try:
            if self.cancel_event.is_set():
                raise DiagnosticCancelledError()
            if self.frozen:
                self.progress.emit("载入 TASK-018 冻结共识栈")
                result = load_precomputed_bundle(
                    self.channel,
                    self.record.time_s,
                    self.record.voltage_v,
                    repo_root=self.repo_root,
                    source_path=self.source_path,
                )
                if result is None:
                    raise ValueError("所选通道无冻结共识栈，请运行实时诊断。")
            else:
                result = compute_diagnostic_bundle(
                    self.record,
                    channel_name=self.channel,
                    source_path=self.source_path,
                    mode=self.mode,
                    stages=self.stages,
                    cancel_event=self.cancel_event,
                    progress_callback=self.progress.emit,
                )
            if self.cancel_event.is_set():
                raise DiagnosticCancelledError()
            self.finished.emit(result)
        except DiagnosticCancelledError:
            self.cancelled.emit()
        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")
        finally:
            self.stopped.emit()


class DiagnosticRunner(QObject):
    progress = Signal(str)
    finished = Signal(object)
    cancelled = Signal()
    failed = Signal(str)
    busyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: QThread | None = None
        self.worker: DiagnosticWorker | None = None
        self.cancel_event = Event()
        self._outcome: tuple[str, object] | None = None
        self._disposed = False
        self._collection_held = False

    @property
    def busy(self) -> bool:
        return self._thread is not None

    def start(
        self,
        record: SignalRecord,
        channel: str,
        source_path: Path | None,
        mode: DiagnosticComputeMode,
        stages: tuple[StageSegment, ...],
        repo_root: Path,
        *,
        frozen: bool = False,
    ) -> bool:
        if self.busy or self._disposed:
            return False
        self.cancel_event = Event()
        self._outcome = None
        thread = QThread(self)
        worker = DiagnosticWorker(
            record, channel, source_path, mode, stages, repo_root, self.cancel_event, frozen
        )
        self._thread, self.worker = thread, worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self.progress)
        worker.finished.connect(self._finished)
        worker.cancelled.connect(self._cancelled)
        worker.failed.connect(self._failed)
        # quit must execute even while GUI disposal is blocked in wait().
        worker.stopped.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._retire)
        _hold_collection()
        self._collection_held = True
        self.busyChanged.emit(True)
        thread.start()
        return True

    @Slot(object)
    def _finished(self, bundle: DiagnosticBundle) -> None:
        self._outcome = ("finished", bundle)

    @Slot()
    def _cancelled(self) -> None:
        self._outcome = ("cancelled", None)

    @Slot(str)
    def _failed(self, message: str) -> None:
        self._outcome = ("failed", message)

    @Slot()
    def _retire(self) -> None:
        if self._thread is None:
            return
        self._thread.wait()
        self._thread.deleteLater()
        self._thread, self.worker = None, None
        self._restore_collection()
        if self._disposed:
            return
        # Publish before unlocking file/channel controls.
        if self.cancel_event.is_set() or self._outcome is None:
            self.cancelled.emit()
        elif self._outcome[0] == "finished":
            self.finished.emit(self._outcome[1])
        elif self._outcome[0] == "failed":
            self.failed.emit(str(self._outcome[1]))
        else:
            self.cancelled.emit()
        self.busyChanged.emit(False)

    def cancel(self) -> None:
        self.cancel_event.set()

    def _restore_collection(self) -> None:
        if self._collection_held:
            self._collection_held = False
            _release_collection()

    def dispose(self) -> None:
        self._disposed = True
        self.cancel()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread.deleteLater()
            self._thread, self.worker = None, None
        self._restore_collection()
