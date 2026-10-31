"""Existing GUI -> cached STFT -> wide ridge -> export, without product changes."""

import json
from pathlib import Path
from typing import Callable

import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from dps_studio.core.export import (
    ResultAnalysisMode, ResultExportOptions, export_formal_results,
)
from dps_studio.core.io import read_delimited_signals
from dps_studio.gui.app import translation_manager
from dps_studio.gui.main_window import MainWindow


def _wait(window: MainWindow, launch: Callable[[], bool]) -> None:
    loop = QEventLoop()
    errors: list[str] = []
    timer = QTimer()
    timer.setSingleShot(True)

    def fail(_generation: int, kind: str, message: str, _traceback: str) -> None:
        errors.append(kind + ": " + message)
        loop.quit()

    def timeout() -> None:
        errors.append("timeout")
        loop.quit()

    window._analysis_adapter.finished.connect(loop.quit)
    window._analysis_adapter.failed.connect(fail)
    timer.timeout.connect(timeout)
    timer.start(20000)
    try:
        assert launch()
        loop.exec()
        assert not errors
    finally:
        timer.stop()
        window._analysis_adapter.finished.disconnect(loop.quit)
        window._analysis_adapter.failed.disconnect(fail)


def test_gui_high_frequency_parameter_display_and_export(
    qapp: QApplication, tmp_path: Path,
) -> None:
    t = np.arange(4096) / 40e9
    source = tmp_path / "synthetic_8GHz.csv"
    np.savetxt(source, np.column_stack((t, .04*np.cos(2*np.pi*8e9*t))), delimiter=",")
    original = source.read_bytes()
    loaded = read_delimited_signals(
        source, time_column=0, voltage_columns={"ch1": 1}, delimiter=",",
        has_header=False, encoding="utf-8", time_scale=1., voltage_scales={"ch1": 1.},
        original_time_unit="s", original_voltage_units={"ch1": "V"},
    )
    window = MainWindow(translation_manager=translation_manager())
    try:
        window.set_loaded_result(loaded)
        window.analysis_range_panel.use_full_range()
        _wait(window, window.run_stft_analysis)
        stft = window.analysis_session.stft_results["ch1"]
        assert stft.frequency_hz[-1] == pytest.approx(20e9)
        window.maximum_frequency_spin.setValue(19.5)
        qapp.processEvents()
        config = window.analysis_session.run_configuration
        assert config is not None
        # The staged UI stores its effective band in the search-region object;
        # preset/run parameters retain the base 6 GHz value for provenance.
        region = window.analysis_session.ridge_search_region
        assert region is not None
        assert region.frequency_max_hz == pytest.approx(19.5e9, abs=10e6)
        assert window.analysis_session.stft_results["ch1"] is stft
        window.spectrogram_view.show_full_spectrum()
        assert window.spectrogram_view.plot_widget.viewRange()[1][1] >= 19.9
        _wait(window, window.run_staged_automatic_analysis)
        analyses = window.analysis_session.channel_analyses
        assert analyses
        np.testing.assert_allclose(analyses["ch1"].ridge_result.frequency_hz, 8e9, atol=10e6)
        (tmp_path / "export").mkdir()
        export_formal_results(ResultExportOptions(
            output_directory=tmp_path / "export", analysis_mode=ResultAnalysisMode.AUTOMATIC,
            channel_analyses=analyses, source_path=source,
        ))
        metadata_paths = list((tmp_path / "export").rglob("*.metadata.json"))
        assert metadata_paths
        metadata = json.loads(metadata_paths[0].read_text(encoding="utf-8"))
        assert metadata["ridge_configuration"]["search_maximum_frequency_hz"] == pytest.approx(
            region.frequency_max_hz)
        details = list((tmp_path / "export").rglob("*detail*.csv"))
        assert details
        assert source.read_bytes() == original
    finally:
        window.close()
        qapp.processEvents()
