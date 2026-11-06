import csv
import json
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from dps_studio.gui.app import translation_manager
from dps_studio.gui.research_window import ResearchMainWindow
from test_task015c_r_event_reference_views import _run, _shifted_event_result


@pytest.mark.parametrize("adopt_candidate", [False, True])
def test_confirmed_reference_survives_workspace_and_channel_switch(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, adopt_candidate: bool,
) -> None:
    window = ResearchMainWindow(translation_manager=translation_manager())
    monkeypatch.setattr(QMessageBox, "information", lambda *args: QMessageBox.StandardButton.Ok)
    try:
        window.set_loaded_result(_shifted_event_result(tmp_path))
        _run(window)
        assert not window.export_event_time_origin_radio.isEnabled()
        if adopt_candidate:
            window.analysis_range_panel.candidate_buttons["pdv_channel_1"].click()
        else:
            start, end = window.analysis_session.data_bounds_s()
            window.analysis_range_panel.event_reference_spin.setValue((start + end) * .5e6)
            window.analysis_range_panel.apply_event_reference_button.click()
        reference = window.analysis_session.event_reference_time_s
        assert reference is not None
        window.mode_combo.setCurrentIndex(1)
        window.mode_combo.setCurrentIndex(0)
        window.export_channel_combo.setCurrentIndex(1)
        channel = window.export_channel_combo.currentData()
        assert channel == "pdv_channel_2"
        assert window.export_event_time_origin_radio.isEnabled()
        for radio, column in ((window.export_event_time_origin_radio, "time_from_event_s"),
                              (window.export_absolute_time_origin_radio, "time_s")):
            radio.click()
            directory = tmp_path / column
            directory.mkdir()
            window._set_export_output_directory(directory)
            assert window._export_current_result()
            metadata = json.loads(next(directory.glob("*.json")).read_text("utf-8"))
            assert metadata["event_reference_time_s"] == pytest.approx(reference, abs=1e-15)
            assert metadata["event_reference_source"] == window.analysis_session.event_reference_source
            assert metadata["source_channel"] == channel
            simple = next(p for p in directory.glob("*.csv") if "_detail" not in p.stem)
            with simple.open(encoding="utf-8-sig") as handle:
                values = [float(row[column]) for row in csv.DictReader(handle)]
            assert values
            if column == "time_from_event_s":
                relative = np.asarray(values)
            else:
                np.testing.assert_allclose(values, relative + reference, rtol=0., atol=1e-14)
    finally:
        window.close()
        qapp.processEvents()
