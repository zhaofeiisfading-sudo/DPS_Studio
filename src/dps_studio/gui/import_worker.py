"""Parse a selected data file without blocking the workstation."""

from __future__ import annotations

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from dps_studio.gui.data_controller import DataImportController, SignalLoadRequest


class _ImportSignals(QObject):
    finished = Signal(object)
    failed = Signal(str, str)


class ImportWorker(QRunnable):
    def __init__(self, controller: DataImportController, request: SignalLoadRequest) -> None:
        super().__init__()
        self.signals = _ImportSignals()
        self._controller = controller
        self._request = request

    @Slot()
    def run(self) -> None:
        try:
            result = self._controller.load(self._request)
        except Exception as exc:
            self.signals.failed.emit(type(exc).__name__, str(exc))
        else:
            self.signals.finished.emit(result)
