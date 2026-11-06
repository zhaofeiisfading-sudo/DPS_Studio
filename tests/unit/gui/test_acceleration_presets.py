from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtWidgets import QApplication, QMessageBox, QInputDialog

from test_task017_result_export import _window, _wait

from dps_studio.core.physics import LIF_RIGG_2014_1550NM
from dps_studio.core.workflow.acceleration import channel_acceleration
from dps_studio.core.workflow import load_workflow_config
from dps_studio.gui.main_window import MainWindow
from dps_studio.gui.result_views import VelocityView
from dps_studio.core.physics.window_presets import WindowPresetRepository


def _isolated_window(qapp: QApplication, tmp_path: Path, monkeypatch: Any) -> MainWindow:
    monkeypatch.setattr("dps_studio.gui.main_window.window_preset_path",
                        lambda: tmp_path / "window_presets.json")
    return _window(qapp, tmp_path)[0]


def _assert_curve(view: VelocityView, analysis: Any) -> None:
    assert view.acceleration_curve is not None
    np.testing.assert_allclose(view.acceleration_curve.getData()[1],
                              channel_acceleration(analysis).acceleration_m_s2 * 1e-9,
                              equal_nan=True)


def test_local_fit_refresh_preserves_zoom_and_velocity(qapp: QApplication, tmp_path: Path,
                                                       monkeypatch: Any) -> None:
    window = _isolated_window(qapp, tmp_path, monkeypatch)
    try:
        _wait(window, window.run_automatic_analysis)
        view = window.velocity_view
        view.select_result_target("automatic", "pdv_channel_1")
        analysis = window.analysis_session.channel_analyses["pdv_channel_1"]
        before = analysis.plot_velocity_m_s.copy()
        view.quantity_combo.setCurrentIndex(1)
        view.acceleration_method_combo.setCurrentIndex(1)
        view.acceleration_window_spin.setValue(80)
        np.testing.assert_allclose(view.acceleration_curve.getData()[1],
            channel_acceleration(analysis, window_s=80e-9).acceleration_m_s2*1e-9, equal_nan=True)
        np.testing.assert_array_equal(analysis.plot_velocity_m_s, before)
        view.plot_widget.setXRange(.6, .8, padding=0)
        view.plot_widget.setYRange(-3, 4, padding=0)
        ranges = view.plot_widget.viewRange()
        window.lif_b1_spin.setValue(.8)
        np.testing.assert_allclose(view.plot_widget.viewRange(), ranges)
        after = window.analysis_session.channel_analyses["pdv_channel_1"]
        np.testing.assert_allclose(view.acceleration_curve.getData()[1],
            channel_acceleration(after, window_s=80e-9).acceleration_m_s2*1e-9, equal_nan=True)
        view.fit_result_range()
        assert view.plot_widget.viewRange() != ranges
        view.acceleration_method_combo.setCurrentIndex(0)
        _assert_curve(view, after)
        view.acceleration_method_combo.setCurrentIndex(1)
        view.acceleration_window_spin.setValue(.001)
        assert np.isnan(view.acceleration_curve.getData()[1]).all()
        assert "0/" in view.acceleration_notice.text()
    finally:
        window.close()
        qapp.processEvents()


def test_acceleration_tracks_channel_corrections_rename_export_and_clear(
    qapp: QApplication, tmp_path: Path, monkeypatch: Any,
) -> None:
    window = _isolated_window(qapp, tmp_path, monkeypatch)
    try:
        view = window.velocity_view
        view.quantity_combo.setCurrentIndex(1)
        assert view.acceleration_curve is None
        _wait(window, window.run_automatic_analysis)
        view.select_result_target("automatic", "pdv_channel_1")
        session = window.analysis_session
        before = session.channel_analyses["pdv_channel_1"]
        _assert_curve(view, before)
        assert "无符号" in view.acceleration_notice.text()
        window.lif_b1_spin.setValue(.8)
        after = session.channel_analyses["pdv_channel_1"]
        assert after.stft_result is before.stft_result
        assert after.ridge_result is before.ridge_result
        _assert_curve(view, after)
        assert "自定义" in window.window_material_combo.currentText()
        editor = window.window_preset_editor
        editor.name_edit.setText("测试窗口甲")
        assert editor._rename()
        renamed = session.channel_analyses["pdv_channel_1"]
        np.testing.assert_array_equal(after.plot_velocity_m_s, renamed.plot_velocity_m_s)
        np.testing.assert_array_equal(channel_acceleration(after).acceleration_m_s2,
                                      channel_acceleration(renamed).acceleration_m_s2)
        assert "测试窗口甲" in view.acceleration_notice.text()
        assert not view.plot_widget.getAxis("left").autoSIPrefix
        assert view.plot_widget.getAxis("left").autoSIPrefixScale == 1.
        view.quantity_combo.setCurrentIndex(0)
        assert view.acceleration_curve is None
        assert view.plot_widget.getAxis("left").autoSIPrefix
        view.quantity_combo.setCurrentIndex(1)
        assert editor.save_current()
        view.channel_combo.setCurrentIndex(view.channel_combo.findData("pdv_channel_2"))
        _assert_curve(view, session.channel_analyses["pdv_channel_2"])
        window.export_absolute_time_origin_radio.click()
        window.export_acceleration_check.setChecked(True)
        window._set_export_output_directory(tmp_path)
        monkeypatch.setattr(QMessageBox, "information", lambda *_args: None)
        assert window._export_current_result()
        metadata = json.loads(next(tmp_path.glob("*.metadata.json")).read_text(encoding="utf-8"))
        snapshot = metadata["acceleration_export"]["velocity_correction"]["window"]
        assert snapshot["configuration_name"] == "测试窗口甲"
        assert snapshot["b1"] == .8
        window._clear_result_presentation("invalidated")
        assert view.acceleration_curve is None
        assert not view.acceleration_notice.text()
    finally:
        window.close()
        qapp.processEvents()


def test_saved_presets_reopen_edit_rename_and_save_as_without_touching_builtin(
    qapp: QApplication, tmp_path: Path, monkeypatch: Any,
) -> None:
    window = _isolated_window(qapp, tmp_path, monkeypatch)
    try:
        editor = window.window_preset_editor
        window.lif_b2_spin.setValue(1.02)
        assert editor.name_edit.text() == "新材料1"
        assert editor.save_current()
        window._restore_lif_defaults()
        assert window.analysis_session.run_configuration.velocity_correction_config.lif_model == LIF_RIGG_2014_1550NM
        window.lif_b1_spin.setValue(.82)
        assert editor.name_edit.text() == "新材料2"
        assert editor.save_current()
    finally:
        window.close()
    reopened = MainWindow(window_preset_repository=WindowPresetRepository(tmp_path / "window_presets.json"))
    try:
        editor = reopened.window_preset_editor
        editor.preset_combo.setCurrentIndex(editor.preset_combo.findData("user:新材料1"))
        assert reopened.lif_b2_spin.value() == 1.02
        editor.name_edit.setText("改名后的窗口")
        assert editor.save_current()
        assert "新材料1" not in editor.repository.load()
        reopened.lif_b1_spin.setValue(.83)
        monkeypatch.setattr(QInputDialog, "getText", lambda *_args, **_kwargs: ("另存配置", True))
        editor._save_as()
        saved = editor.repository.load()
        assert saved["改名后的窗口"].b1 == .7895
        assert saved["另存配置"].b1 == .83
        editor.name_edit.setText("新材料2")
        assert not editor.save_current()
        assert saved == editor.repository.load()
        reopened._restore_lif_defaults()
        assert reopened.lif_b1_spin.value() == .7895
        assert not editor.name_edit.isEnabled()
    finally:
        reopened.close()
        qapp.processEvents()


def test_parameter_overflow_keeps_result_and_configuration_consistent(
    qapp: QApplication, tmp_path: Path, monkeypatch: Any,
) -> None:
    window = _isolated_window(qapp, tmp_path, monkeypatch)
    try:
        _wait(window, window.run_automatic_analysis)
        before = window.analysis_session.run_configuration
        # Force a failure independent of the sample's particular speed values.
        def failed(*_args: object, **_kwargs: object) -> Any:
            raise ValueError("unsafe coefficients")
        monkeypatch.setattr("dps_studio.gui.analysis_session.configure_channel_velocity_correction", failed)
        window.lif_b2_spin.setValue(1e6)
        assert window.analysis_session.run_configuration == before
        assert window.lif_b2_spin.value() == before.velocity_correction_config.lif_model.b2
        assert "unsafe" in window.analysis_status_label.text()
    finally:
        window.close()
        qapp.processEvents()


def test_switch_to_missing_source_clears_derivative(
    qapp: QApplication, tmp_path: Path, monkeypatch: Any,
) -> None:
    window = _isolated_window(qapp, tmp_path, monkeypatch)
    try:
        _wait(window, window.run_automatic_analysis)
        analyses = window.analysis_session.channel_analyses
        view = window.velocity_view
        view.quantity_combo.setCurrentIndex(1)
        view.set_result_sets(analyses, {"pdv_channel_1": analyses["pdv_channel_1"]},
                             relative_db_floor=-60, available_channel_names=tuple(analyses))
        view.select_result_target("guided", "pdv_channel_1")
        _assert_curve(view, analyses["pdv_channel_1"])
        view.channel_combo.setCurrentIndex(view.channel_combo.findData("pdv_channel_2"))
        assert view.acceleration_curve is None
    finally:
        window.close()
        qapp.processEvents()


def test_corrupt_library_disables_saving_and_preserves_file(
    qapp: QApplication, tmp_path: Path,
) -> None:
    path = tmp_path / "broken.json"
    path.write_text("broken library", encoding="utf-8")
    window = MainWindow(window_preset_repository=WindowPresetRepository(path))
    try:
        window.lif_b1_spin.setValue(.8)
        editor = window.window_preset_editor
        assert not editor.save_button.isEnabled()
        assert not editor.save_as_button.isEnabled()
        assert str(path) in editor.status.text()
        assert path.read_text(encoding="utf-8") == "broken library"
    finally:
        window.close()


def test_upstream_parameter_change_invalidates_acceleration_and_editor_is_locked_when_busy(
    qapp: QApplication, tmp_path: Path, monkeypatch: Any,
) -> None:
    window = _isolated_window(qapp, tmp_path, monkeypatch)
    try:
        _wait(window, window.run_automatic_analysis)
        view = window.velocity_view
        view.quantity_combo.setCurrentIndex(1)
        assert view.acceleration_curve is not None
        def launch() -> bool:
            started = window.run_automatic_analysis()
            assert not window.window_preset_editor.isEnabled()
            return started

        _wait(window, launch)
        assert window.window_preset_editor.isEnabled()
        window.nfft_spin.setValue(window.nfft_spin.value() * 2)
        assert view.acceleration_curve is None
        assert not window.analysis_session.any_formal_results_available
        _wait(window, window.run_automatic_analysis)
        channel = view.channel_combo.currentData()
        _assert_curve(view, window.analysis_session.channel_analyses[channel])
    finally:
        window.close()
        qapp.processEvents()


def test_imported_configuration_cannot_overwrite_previous_selected_preset(
    qapp: QApplication, tmp_path: Path, monkeypatch: Any,
) -> None:
    window = _isolated_window(qapp, tmp_path, monkeypatch)
    try:
        window.lif_b1_spin.setValue(.8)
        editor = window.window_preset_editor
        assert editor.save_current()
        saved = editor.repository.load()
        root = Path(__file__).resolve().parents[3]
        config = load_workflow_config(root / "configs/pdv_studio_defaults.toml", repository_root=root)
        window.set_analysis_configuration(config)
        window.lif_b1_spin.setValue(.82)
        assert editor.save_current()
        entries = editor.repository.load()
        assert entries["新材料1"] == saved["新材料1"]
        assert entries["新材料2"].b1 == .82
    finally:
        window.close()
        qapp.processEvents()


def test_legacy_parameter_precision_survives_unrelated_edits(
    qapp: QApplication, tmp_path: Path, monkeypatch: Any,
) -> None:
    window = _isolated_window(qapp, tmp_path, monkeypatch)
    try:
        model = replace(LIF_RIGG_2014_1550NM, b1=.812345678912345,
                        reference_wavelength_m=1.550000000000123e-6)
        window._select_window_model(model)
        window.measurement_angle_spin.setValue(5.)
        current = window.analysis_session.run_configuration.velocity_correction_config.lif_model
        assert current.b1 == model.b1
        assert current.reference_wavelength_m == model.reference_wavelength_m
        assert window.window_preset_editor.save_current()
        saved = next(iter(window.window_preset_editor.repository.load().values()))
        assert saved.b1 == model.b1
        assert saved.reference_wavelength_m == model.reference_wavelength_m
    finally:
        window.close()
        qapp.processEvents()
