"""Exercise actual stage/algorithm controls, manual override, and prior display."""
from pathlib import Path
from time import monotonic, sleep

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QComboBox

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.gui.research_window import ResearchMainWindow
from dps_studio.gui.segment_workspace import RECOMMENDATIONS, STAGE_LABELS


def test_stage_change_resets_manual_choice_and_refresh_preserves_it(qapp, tmp_path: Path) -> None:
    t = np.arange(4096)/40e9
    source = tmp_path/"wave.csv"
    np.savetxt(source, np.column_stack((t, np.cos(2*np.pi*100e6*t))), delimiter=",")
    w = ResearchMainWindow(settings=QSettings(str(tmp_path/"layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(tmp_path/"presets.json"))
    w.set_loaded_result(read_delimited_signals(source, time_column=0, voltage_columns={"ch": 1}))
    w.analysis_range_panel.use_full_range()
    w.mode_combo.setCurrentIndex(1)
    s = w.segment_workspace
    assert STAGE_LABELS["noise"] == "噪声干扰"
    s.stage_combo.setCurrentIndex(s.stage_combo.findData("stationary"))
    s.algorithm_combo.setCurrentIndex(s.algorithm_combo.findData("low_glrt"))
    assert s.plan[0].algorithm == "low_glrt"
    assert ("ch", s.plan[0].id) in s.manual_choices
    s._rebuild()
    assert s.plan[0].algorithm == "low_glrt"
    assert s.add_boundary(t[2048])
    table_stage = s.table.cellWidget(1, 3)
    assert isinstance(table_stage, QComboBox)
    table_stage.setCurrentIndex(table_stage.findData("noise"))
    assert s.plan[1].algorithm == RECOMMENDATIONS.get("noise", "stft")
    assert s.plan[0].algorithm == "low_glrt"
    assert ("ch", s.plan[1].id) not in s.manual_choices
    s.interval_combo.setCurrentIndex(1)
    s.algorithm_combo.setCurrentIndex(s.algorithm_combo.findData("stft_short"))
    s.move_boundary(0, t[2040])
    s._rebuild()
    assert s.plan[1].algorithm == "stft_short"
    path = tmp_path/"plan.json"
    s.save_plan(path)
    s.load_plan(path)
    assert s.plan[1].algorithm == "stft_short"
    # Legacy Chinese noise labels load into the unchanged stable internal ID.
    text = path.read_text(encoding="utf-8").replace('"stage": "noise"', '"stage": "噪声"')
    legacy = tmp_path/"legacy.json"
    legacy.write_text(text, encoding="utf-8")
    s.load_plan(legacy)
    assert s.plan[1].stage == "noise"
    qapp.processEvents()
    assert s.run_analysis()
    deadline = monotonic() + 30
    while s.busy and monotonic() < deadline:
        qapp.processEvents()
        sleep(.01)  # Release the GIL for the Python analysis worker, as in native acceptance.
    assert not s.busy and "ch" in s.results
    s.field_combo.setCurrentIndex(s.field_combo.findData("apparent"))
    qapp.processEvents()
    labels = [item.textItem.toPlainText() for item in s.result_plot.items()
              if isinstance(item, pg.TextItem)]
    assert any("人工静止先验" in text and "非测量" in text for text in labels)
    result = s.results["ch"]
    assert np.all(result.apparent_velocity_m_s[result.valid] > 0.)
