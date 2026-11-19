"""A GUI-owned, cooperatively cancelled and joined comparison thread."""
from __future__ import annotations

from pathlib import Path
from threading import Event

from PySide6.QtCore import QThread, Signal

from dps_studio.core.models import SignalRecord
from dps_studio.core.stft_m4 import (
    ComparisonCancelledError,
    StftM4ComparisonBundle,
    compute_comparison_bundle,
)


class ComparisonWorker(QThread):
    progress = Signal(int, str)

    def __init__(
        self, record: SignalRecord, channel: str, source_path: Path | None,
        fmin_hz: float, fmax_hz: float, matched: bool,
    ) -> None:
        super().__init__()
        self._record, self._channel, self._path = record, channel, source_path
        self._fmin, self._fmax, self._matched = fmin_hz, fmax_hz, matched
        self.cancel_event = Event()
        self.result: StftM4ComparisonBundle | None = None
        self.error: str | None = None

    def run(self) -> None:
        try:
            self.result = compute_comparison_bundle(
                self._record, channel_name=self._channel, source_path=self._path,
                fmin_hz=self._fmin, fmax_hz=self._fmax, include_matched_stft=self._matched,
                cancel_event=self.cancel_event, progress_callback=self.progress.emit,
            )
        except ComparisonCancelledError:
            self.cancel_event.set()
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
