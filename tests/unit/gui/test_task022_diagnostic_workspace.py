"""Diagnostic GUI contracts, actual asynchronous computation and frozen raw replay."""

from __future__ import annotations

import gc
import os
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep

import numpy as np
import pytest
import pyqtgraph as pg  # type: ignore[import-untyped]
from PySide6.QtCore import QEvent, QPointF, QSettings
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from dps_studio.core.diagnostics import (
    CandidateEntry,
    DiagnosticBundle,
    DiagnosticComputeMode,
    inspect_frame,
)
from dps_studio.core.io import read_delimited_signals
from dps_studio.core.models import SignalRecord
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.gui.diagnostic import DiagnosticWorkspace
from dps_studio.gui.diagnostic.plots import LocalSpectrumPlot
from dps_studio.gui.diagnostic.theme import contrast_levels
from dps_studio.gui.research_window import ResearchMainWindow

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module", autouse=True)
def diagnostic_fonts(qapp: QApplication) -> Iterator[None]:
    """Match capture fonts when Windows offscreen cannot enumerate installed fonts."""
    previous = qapp.font()
    font_ids: list[int] = []
    if os.name == "nt" and qapp.platformName() == "offscreen":
        for filename in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf", "seguisym.ttf", "seguiemj.ttf"):
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / filename
            if path.is_file():
                font_ids.append(QFontDatabase.addApplicationFont(str(path)))
        qapp.setFont(QFont("Microsoft YaHei", 9))
    yield
    qapp.setFont(previous)
    for font_id in font_ids:
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)


def wait_idle(workspace: DiagnosticWorkspace, qapp: QApplication) -> None:
    deadline = monotonic() + 90
    while workspace.busy and monotonic() < deadline:
        qapp.processEvents()
        # Release the Python GIL explicitly while the numerical QObject works.
        # Nested QtTest waits can starve Python-heavy estimators on Windows.
        sleep(0.005)
    qapp.processEvents()
    assert not workspace.busy, workspace.properties.stage_label.text()


@pytest.fixture
def window(qapp: QApplication, tmp_path: Path) -> ResearchMainWindow:
    result = ResearchMainWindow(
        settings=QSettings(str(tmp_path / "diagnostic.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(tmp_path / "windows.json"),
    )
    result.resize(1600, 960)
    result.show()
    qapp.processEvents()
    return result


def load_synthetic(window: ResearchMainWindow, tmp_path: Path) -> None:
    t = np.arange(8192) / 40e9
    rng = np.random.default_rng(22)
    y = 8 + rng.normal(0, 0.003, len(t))
    y[2048:] += 0.4 * np.cos(2 * np.pi * 1.7e9 * t[2048:])
    source = tmp_path / "arbitrary_multichannel.dat"
    np.savetxt(source, np.column_stack((t, y, y * 0.8)), delimiter=",")
    window.set_loaded_result(
        read_delimited_signals(
            source, time_column=0, voltage_columns={"custom_A": 1, "custom_B": 2}
        )
    )


def test_three_modes_empty_onboarding_and_geometry(
    window: ResearchMainWindow, qapp: QApplication
) -> None:
    w = window
    assert [w.mode_combo.itemData(i) for i in range(3)] == ["classic", "segmented", "diagnostic"]
    for index in (2, 1, 0, 1, 2, 0, 2):
        w.mode_combo.setCurrentIndex(index)
        qapp.processEvents()
        assert w.mode_stack.currentIndex() == w.properties_stack.currentIndex() == index
        assert w.navigation_panel.isVisible() == (index == 0)
        assert w.segmented_mode == (index == 1)
        assert w.diagnostic_mode == (index == 2)
        assert w.mode_combo.isEnabled()
    assert w.diagnostic_workspace.onboarding.isVisible()
    assert not w.diagnostic_workspace.properties.fast_button.isEnabled()
    d = w.diagnostic_workspace
    for button, arrow in (
        (d.previous_frame_button, "<"),
        (d.previous_key_button, "<"),
        (d.next_frame_button, ">"),
        (d.next_key_button, ">"),
    ):
        assert arrow in button.text()
        assert not any(glyph in button.text() for glyph in ("\u25c0", "\u25b6"))
    waveform_axis = d.inspector.waveform_plot.plot_widget.getAxis("left")
    assert waveform_axis.labelText == "电压(V)" and waveform_axis.width() == 52
    w.workspace_splitter.setSizes([0, 1200, 290])
    qapp.processEvents()
    before = w.workspace_splitter.sizes()
    w.mode_combo.setCurrentIndex(1)
    w.mode_combo.setCurrentIndex(2)
    qapp.processEvents()
    assert abs(w.workspace_splitter.sizes()[2] - before[2]) <= 3


def test_fast_async_candidate_microscope_and_controls(
    window: ResearchMainWindow, qapp: QApplication, tmp_path: Path
) -> None:
    load_synthetic(window, tmp_path)
    window.mode_combo.setCurrentIndex(2)
    d = window.diagnostic_workspace
    collection_enabled = gc.isenabled()
    d.channel_combo.setCurrentIndex(1)
    assert "custom_B" in window.status_channel.text()
    assert "8,192" in d.properties.source_label.text()
    assert "固定前缀" in d.properties.background_label.text()
    assert not d.frozen_available()
    assert d.start_compute()
    assert d.busy and not window.mode_combo.isEnabled() and not window.action_open_data.isEnabled()
    window.mode_combo.setCurrentIndex(0)
    assert window.diagnostic_mode
    assert not d.start_compute()
    wait_idle(d, qapp)
    b = d.bundle
    assert isinstance(b, DiagnosticBundle), d.properties.stage_label.text()
    assert b.compute_mode == "fast_core" and "S2" not in b.curves
    assert window.mode_combo.isEnabled() and window.action_open_data.isEnabled()
    assert gc.isenabled() == collection_enabled
    assert d.inspector.table.rowCount() == 4
    assert d.spectrogram.image.image.shape == b.demeaned_spectrogram.power_db.shape
    assert d.spectrogram.title.text() == (
        "02  去均值 512 STFT 底图 (抑制直流偏置) · C / G / S / 选择"
    )
    accepted = next(
        i for i, frame in enumerate(b.candidates_by_frame) if any(c.s_supported for c in frame)
    )
    rejected = next(
        i for i, frame in enumerate(b.candidates_by_frame) if any(not c.s_supported for c in frame)
    )
    for index in (accepted, rejected, 0):
        d.select_frame(index)
        for row_index, row in enumerate(b.candidates_by_frame[index]):
            d.inspector.table.setCurrentCell(row_index, 0)
            ev = d.inspector.evidence
            assert ev is not None
            exact = inspect_frame(
                b.time_s,
                b.voltage_v,
                row.sample_index,
                b.background_stop_index,
                focus_frequency_hz=row.frequency_hz,
                focus_chirp_hz_s=row.chirp_hz_s,
            )
            np.testing.assert_allclose(ev.detrended_v, exact.detrended_v)
            np.testing.assert_allclose(ev.raw_chirp_r2, exact.raw_chirp_r2, equal_nan=True)
            reason_text = d.inspector.reason_box.toPlainText()
            assert row.native_quality in reason_text
            assert not any(
                glyph in reason_text for glyph in ("\u2713", "\u2717", "\u26a0", "\u25c0", "\u25b6")
            )
            assert d.inspector.spectrum_plot.evidence is ev
            if np.isfinite(row.frequency_hz):
                assert len(d.spectrogram.focus_marker.points()) == 1
    d.select_frame(accepted)
    target = next(c for c in b.candidates_by_frame[accepted] if c.c_present)
    d.spectrogram.timeClicked.emit(target.time_s, target.frequency_hz / 1e9)
    assert d.frame_index == accepted
    assert d.inspector.focus is not None
    np.testing.assert_allclose(d.inspector.focus.raw_frequency_hz, target.raw_frequency_hz)
    d.raw_plot.timeClicked.emit(float(b.common_times_s[10]), 0.0)
    assert d.frame_index == 10
    d.timeline.timeClicked.emit(float(b.common_times_s[accepted]), 0.0)
    assert d.frame_index == accepted
    d.inspector.waveform_mode_combo.setCurrentIndex(1)
    d.inspector.window_combo.setCurrentIndex(1)
    ev = d.inspector.evidence
    assert ev is not None and ev.window_width == 512
    raw_curve = d.inspector.waveform_plot.plot_widget.listDataItems()[0]
    np.testing.assert_array_equal(raw_curve.yData, ev.raw_voltage_v)
    d.backdrop_combo.setCurrentIndex(1)
    np.testing.assert_array_equal(d.spectrogram.image.image, b.raw_spectrogram.power_db)
    assert d.spectrogram.title.text() == (
        "02  传统原始 1024 STFT 底图 (无去均值，可见DC泄漏) · C / G / S / 选择"
    )
    d.backdrop_combo.setCurrentIndex(0)
    assert "去均值 512 STFT" in d.spectrogram.title.text()
    d.contrast_combo.setCurrentIndex(1)
    d.band_combo.setCurrentIndex(1)
    np.testing.assert_allclose(d.spectrogram.plot_widget.viewRange()[1], [0, 6.2])
    d.rejected_checkbox.setChecked(False)
    for items in d.spectrogram.method_items.values():
        assert all(not item.isVisible() for item in items if item.property("rejected"))
    d.method_buttons["B0"].setChecked(False)
    assert all(not item.isVisible() for item in d.spectrogram.method_items["B0"])
    d.cloud_checkbox.setChecked(True)
    assert [label.text() for label in d.timeline.curve_legend_labels] == [
        "—— Tone R²",
        "—— Chirp R²",
    ]
    assert "#0284c7" in d.timeline.curve_legend_labels[0].styleSheet()
    assert "#be123c" in d.timeline.curve_legend_labels[1].styleSheet()
    d.metric_combo.setCurrentIndex(1)
    assert [label.text() for label in d.timeline.curve_legend_labels] == [
        "—— 对比度 dB",
        "—— 背景增益 dB",
    ]
    assert "#059669" in d.timeline.curve_legend_labels[1].styleSheet()
    d.metric_combo.setCurrentIndex(0)
    assert [label.text() for label in d.timeline.curve_legend_labels] == [
        "—— Tone R²",
        "—— Chirp R²",
    ]
    for category in range(d.filter_combo.count()):
        d.filter_combo.setCurrentIndex(category)
        d.jump_key(1)
        d.jump_key(-1)
    d.filter_combo.setCurrentIndex(0)
    d.select_frame(10)
    d.next_frame_button.click()
    assert d.frame_index == 11
    d.previous_frame_button.click()
    assert d.frame_index == 10
    d.zoom_local()
    qapp.processEvents()
    for plot in (d.raw_plot, d.timeline):
        np.testing.assert_allclose(
            plot.plot_widget.viewRange()[0], d.spectrogram.plot_widget.viewRange()[0], atol=0.003
        )
    d.reset_view()
    d.channel_combo.setCurrentIndex(0)
    assert d.bundle is None and not d.inspector.table.rows
    d.channel_combo.setCurrentIndex(1)
    assert d.bundle is b


def test_cancel_and_close_join_thread(
    window: ResearchMainWindow, qapp: QApplication, tmp_path: Path
) -> None:
    load_synthetic(window, tmp_path)
    window.mode_combo.setCurrentIndex(2)
    d = window.diagnostic_workspace
    progress: list[str] = []

    def cancel_after_work_started(stage: str) -> None:
        progress.append(stage)
        if stage == "B1":
            d.cancel_compute()

    d.runner.progress.connect(cancel_after_work_started)
    assert d.start_compute(DiagnosticComputeMode.FULL_S2)
    wait_idle(d, qapp)
    d.runner.progress.disconnect(cancel_after_work_started)
    assert "shared_evidence" in progress and "B1" in progress
    assert d.bundle is None and "已取消" in d.properties.stage_label.text()
    assert d.runner._thread is None and d.runner.worker is None
    assert d.start_compute(DiagnosticComputeMode.FULL_S2)
    qapp.processEvents()
    window.close()
    assert not d.busy and d.runner.worker is None
    window.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_full_live_force_recompute(
    window: ResearchMainWindow, qapp: QApplication, tmp_path: Path
) -> None:
    load_synthetic(window, tmp_path)
    window.mode_combo.setCurrentIndex(2)
    d = window.diagnostic_workspace
    assert d.start_compute(DiagnosticComputeMode.FULL_S2)
    wait_idle(d, qapp)
    assert d.bundle is not None, d.properties.stage_label.text()
    assert d.bundle.compute_mode == "full_s2" and "S2" in d.bundle.curves
    assert d.inspector.table.rowCount() == 9
    assert any(
        c.estimator == "low_glrt" and c.run_status == "RAN"
        for frame in d.bundle.candidates_by_frame
        for c in frame
    )
    for method, curve in d.bundle.curves.items():
        for index in (0, len(curve.time_s) - 2):
            d.inspector.header.set_frame(d.bundle, index)
            if method in ("B+S", "S2"):
                expected = "[已选 S1]" if curve.selected[index] else "[未选 S0]"
            else:
                expected = f"[G{int(curve.g_accepted[index])} S{int(curve.s_supported[index])}]"
            assert expected in d.inspector.header.method_labels[method].text()
    d.select_frame(len(d.bundle.common_times_s) - 2)
    qapp.processEvents()
    table = d.inspector.table
    assert table.columnCount() == 8
    headers = [table.horizontalHeaderItem(i) for i in range(8)]
    assert [item.text() if item is not None else None for item in headers] == [
        "估计器",
        "簇",
        "频率(GHz)",
        "调频(G/μs)",
        "C/G/S",
        "选中",
        "R²(单/调)",
        "比/增/周",
    ]
    assert table.horizontalScrollBar().maximum() == 0
    assert table.horizontalHeader().length() <= table.viewport().width()


@pytest.mark.parametrize("channel", ["ch3_ch1", "20201210m_ch1", "20260630-1_ch2"])
def test_real_preset_frozen_stack_and_key_frame(
    window: ResearchMainWindow, qapp: QApplication, channel: str
) -> None:
    d = window.diagnostic_workspace
    index = next((i for i, p in enumerate(d.properties.presets) if p.channel_id == channel), None)
    if (
        index is None
        or not (ROOT / f"artifacts/TASK-018/data/stack_v1/{channel}__curves.csv.gz").is_file()
    ):
        pytest.skip("Locally supplied raw/frozen inputs unavailable")
    d.properties.preset_combo.setCurrentIndex(index)
    d.properties.prefer_frozen_checkbox.setChecked(True)
    d.properties.load_preset_button.click()
    wait_idle(d, qapp)
    b = d.bundle
    assert b is not None, d.properties.stage_label.text()
    assert b.compute_mode == "precomputed_stack" and window.mode_combo.currentIndex() == 2
    assert channel in window.status_channel.text()
    assert d.inspector.table.rowCount() == 9
    if channel == "ch3_ch1":
        d.select_sample(42752)
        assert d.inspector.select_estimator("B0")
        rejected_text = d.inspector.reason_box.toPlainText()
        assert "S判据(未过)" in rejected_text
        assert "[未]maxR²=0.199" in rejected_text
        assert not any(
            glyph in rejected_text for glyph in ("\u2713", "\u2717", "\u26a0", "\u25c0", "\u25b6")
        )
        assert d.inspector.select_estimator("dechirp")
        ev = d.inspector.evidence
        assert ev is not None and ev.raw_chirp_r2 >= 0.40
        assert "Chirp 调频救回" in d.inspector.reason_box.toPlainText()
        assert d.inspector.spectrum_plot.evidence is ev
    elif channel == "20260630-1_ch2":
        d.select_frame(b.frame_index_for_time(float(b.time_s[0]) + 3254.4e-9))
        assert b.frame_tags.stage[d.frame_index] == "weak_signal"
        assert b.frame_tags.competing_clusters_mask[d.frame_index]
    else:
        d.filter_combo.setCurrentIndex(d.filter_combo.findData("onset"))
        assert d.filtered_indices()
    for i, name in enumerate(METHODS := tuple(d.method_buttons)):
        item = d.properties.summary.table.item(i, 1)
        assert item is not None and item.text() == str(int(b.curves[name].c_present.sum()))
    assert len(METHODS) == 6


def test_missing_presets_and_nan_contrast(qapp: QApplication, tmp_path: Path) -> None:
    d = DiagnosticWorkspace(tmp_path)
    assert not d.properties.preset_combo.isEnabled()
    assert not d.properties.load_preset_button.isEnabled()
    assert not d.start_compute()
    assert contrast_levels(np.full((4, 5), np.nan)) == (-100.0, 0.0)
    d.dispose()
    d.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_failed_input_and_widget_delete_during_job(qapp: QApplication, tmp_path: Path) -> None:
    d = DiagnosticWorkspace(tmp_path)
    d.set_context({"short": SignalRecord(np.arange(512) / 40e9, np.ones(512))}, None)
    assert d.start_compute()
    wait_idle(d, qapp)
    assert "诊断失败" in d.properties.stage_label.text()
    assert "1024" in d.properties.stage_label.text()
    assert d.bundle is None and d.runner._thread is None
    t = np.arange(4096) / 40e9
    d.set_context({"valid": SignalRecord(t, np.cos(2 * np.pi * 1e9 * t))}, None)
    assert d.start_compute(DiagnosticComputeMode.FULL_S2)
    runner = d.runner
    d.deleteLater()
    qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    # Workspace DeferredDelete joined before QObject recursively destroyed its children.
    assert runner._thread is None and runner.worker is None


@pytest.mark.parametrize("prior_visible", [True, False])
@pytest.mark.parametrize("destination", [0, 1, "close"])
def test_diagnostic_mode_restores_prior_dock_visibility(
    window: ResearchMainWindow, qapp: QApplication, prior_visible: bool, destination: int | str
) -> None:
    window.diagnostics_dock.setVisible(prior_visible)
    qapp.processEvents()
    window.mode_combo.setCurrentIndex(2)
    qapp.processEvents()
    assert window.diagnostics_dock.isHidden()
    assert window._dock_visible_before_diagnostic == prior_visible
    if destination == "close":
        assert window.close()
    else:
        assert isinstance(destination, int)
        window.mode_combo.setCurrentIndex(destination)
    qapp.processEvents()
    assert window.diagnostics_dock.isHidden() == (not prior_visible)
    assert window._dock_visible_before_diagnostic is None


@pytest.mark.parametrize("width,height", [(440, 230), (560, 195), (720, 260)])
def test_spectrum_badges_headroom_grouping_and_clear(
    qapp: QApplication, width: int, height: int
) -> None:
    t = np.arange(2048, dtype=np.float64) / 40e9
    ev = inspect_frame(
        t, np.cos(2 * np.pi * 1e9 * t), 1024, 512, focus_frequency_hz=1.16e9, focus_label="dechirp"
    )
    ev = replace(
        ev,
        spectrum_freq_hz=np.array([0, 0.5, 1, 2, 4, 8, 10]) * 1e9,
        local_psd_db=np.array([-20, -40, np.nan, -25, -35, -45, 10000.0]),
        background_psd_db=np.array([-50, -60, -70, -45, -55, -65, -10000.0]),
    )
    candidates = tuple(
        CandidateEntry(
            i, 1024, float(t[1024]), name, "test", raw_frequency_hz=freq * 1e9, native_rank=rank
        )
        for i, (name, freq, rank) in enumerate(
            (
                ("B0", 0.01, 1),
                ("B1", 0.04, 1),
                ("dechirp", 1.16, 1),
                ("varpro", 1.19, 1),
                ("matrix_pencil", 1.30, 2),
                ("low_glrt", 1.45, 1),
                ("B2", 7.99, 1),
                ("missing", np.nan, 1),
            )
        )
    )
    plot = LocalSpectrumPlot()
    plot.resize(width, height)
    plot.show()
    try:
        plot.set_evidence(ev, candidates)
        qapp.processEvents()
        np.testing.assert_allclose(plot.plot_widget.viewRange()[1], [-74.0, 2.0])
        axis = plot.plot_widget.getAxis("left")
        assert axis.labelText == "功率 / dB" and axis.width() == 46
        assert "FFT 功率 (dB re 1 V²)，非每Hz密度" in plot.title.toolTip()
        badges = [item for item in plot.plot_widget.plotItem.items if isinstance(item, pg.TextItem)]
        texts = [item.toPlainText() for item in badges]
        assert set(texts) == {"[聚焦] dechirp", "B0,B1", "dechirp,varpro", "mp#2", "low_glrt", "B2"}
        assert not any("\u25b6" in text for text in texts)
        assert len({round(item.pos().y(), 3) for item in badges}) > 1
        vb = plot.plot_widget.plotItem.vb
        headroom = vb.sceneBoundingRect()
        headroom.setBottom(vb.mapViewToScene(QPointF(0, -19.0)).y())
        for i, badge in enumerate(badges):
            bounds = badge.sceneBoundingRect()
            assert headroom.contains(bounds), (badge.toPlainText(), bounds, headroom)
            assert badge.pos().y() > -19.0
            for other in badges[i + 1 :]:
                assert not bounds.intersects(other.sceneBoundingRect()), (
                    badge.toPlainText(),
                    bounds,
                    other.toPlainText(),
                    other.sceneBoundingRect(),
                )
        markers = [
            item for item in plot.plot_widget.plotItem.items if isinstance(item, pg.InfiniteLine)
        ]
        vertical = [item for item in markers if item.angle == 90]
        assert len(vertical) == 8 and all(getattr(item, "label", None) is None for item in vertical)
        focus_line = next(item for item in vertical if item.pen.widthF() == 2.2)
        assert focus_line.pen.color().name() == "#111827"
        threshold = next(item for item in markers if item.angle == 0)
        assert threshold.label.orthoPos == 0.84
        plot.set_evidence(replace(ev, focus_frequency_hz=np.nan), ())
        qapp.processEvents()
        assert not any(isinstance(item, pg.TextItem) for item in plot.plot_widget.plotItem.items)
        empty = np.full(len(ev.spectrum_freq_hz), np.nan)
        plot.set_evidence(replace(ev, local_psd_db=empty, background_psd_db=empty), candidates)
        qapp.processEvents()
        assert np.isfinite(plot.plot_widget.viewRange()).all()
    finally:
        plot.dispose()
        plot.close()
        plot.deleteLater()
        qapp.sendPostedEvents(None, QEvent.Type.DeferredDelete)
