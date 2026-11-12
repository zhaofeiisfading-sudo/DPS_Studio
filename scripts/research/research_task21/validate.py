"""Run Production on three unchanged records and capture numerical and desktop evidence."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from time import monotonic, perf_counter
from typing import Any

import matplotlib
import numpy as np
from PySide6.QtCore import QEventLoop, QPoint, QSettings, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from dps_studio.core.models import SignalRecord
from dps_studio.core.physics.dechirp import DechirpResult, DechirpSettings
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.core.workflow import ChannelAnalysis
from dps_studio.core.workflow.acceleration import channel_acceleration, channel_dechirp
from dps_studio.gui.app import create_application, translation_manager
from dps_studio.gui.import_dialog import ImportSettingsDialog
from dps_studio.gui.main_window import MainWindow
from scripts.dev.research_task19_acceptance import capture, wait_for_idle

matplotlib.use("Agg")
from matplotlib import pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
CASES = (("20260607", "pdv_channel_1"), ("20260630-1", "pdv_channel_2"),
         ("20260701", "pdv_channel_1"))


def click_tab(window: MainWindow, view: Any) -> None:
    tab = window.science_tabs.tabBar()
    QTest.mouseClick(tab, Qt.MouseButton.LeftButton,
                     pos=tab.tabRect(window.science_tabs.indexOf(view)).center())
    assert window.science_tabs.currentWidget() is view


def describe(t: Any, y: Any, select: Any) -> dict[str, Any]:
    indices = np.flatnonzero(select & np.isfinite(y))
    if not len(indices):
        return {"n": 0}
    best = indices[int(np.argmax(np.abs(y[indices])))]
    values = y[indices]
    median = float(np.median(values))
    return {"n": len(indices), "first_ns": float(t[indices[0]]), "peak_ns": float(t[best]),
            "peak_m_s2": float(y[best]), "median_m_s2": median,
            "mad_m_s2": float(np.median(np.abs(values-median)))}


def compare(
    record: SignalRecord, analysis: ChannelAnalysis, output: Path,
) -> tuple[dict[str, Any], DechirpResult]:
    start = perf_counter()
    a = channel_acceleration(analysis).acceleration_m_s2
    elapsed = perf_counter() - start
    local = channel_acceleration(analysis, window_s=50e-9).acceleration_m_s2
    fits = {}
    times = {}
    for length in (256, 512, 768):
        start = perf_counter()
        fits[length] = channel_dechirp(record, analysis, settings=DechirpSettings(length))
        times[length] = perf_counter() - start
    fit = fits[512]
    event = analysis.signal_detection_result.detected_event_candidate_time_s
    origin = event if event is not None else record.start_time_s
    t = (fit.time_s - origin) * 1e9
    raw_t = (record.time_s - origin) * 1e9
    modes = {"difference": a, "local_50ns": local}
    modes.update({f"dechirp_{n}": x.apparent_acceleration_m_s2 for n, x in fits.items()})
    with (output / "frames.csv").open("x", encoding="utf-8", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["absolute_time_s", "relative_to_candidate_ns", "working_frequency_hz",
                         "working_apparent_m_s", "formal_apparent_m_s", "signal_state",
                         *[f"{key}_m_s2" for key in modes], "dechirp_512_flag", "dechirp_512_r2"])
        for i, x in enumerate(t):
            writer.writerow([
                fit.time_s[i], x, analysis.working_frequency_hz[i],
                analysis.working_apparent_velocity_m_s[i], analysis.apparent_velocity_m_s[i],
                analysis.signal_detection_result.signal_states[i].value,
                *(values[i] for values in modes.values()), fit.flags[i], fit.r2[i],
            ])

    stft = analysis.stft_result
    stft_db = 20 * np.log10(np.maximum(np.abs(stft.spectrum), 1e-30))
    top = float(np.max(stft_db))
    fig, ax = plt.subplots(4, 2, figsize=(13, 9), sharex="col", layout="constrained")
    for j, (lo, hi) in enumerate(((float(t[0]), float(t[-1])), (-55, 110))):
        bins = (raw_t >= lo) & (raw_t <= hi)
        ax[0, j].plot(raw_t[bins], record.voltage_v[bins] * 1e3, lw=.45)
        ax[0, j].set_ylabel("Voltage (mV)")
        mask = stft.frequency_hz <= min(8e9, record.nyquist_frequency_hz)
        ax[1, j].pcolormesh(t, stft.frequency_hz[mask] / 1e9, stft_db[mask],
                            vmin=top-45, vmax=top, shading="auto", cmap="magma", rasterized=True)
        ax[1, j].plot(t, analysis.working_frequency_hz / 1e9, color="cyan", lw=.65, alpha=.8)
        ax[1, j].scatter(t, fit.frequency_hz / 1e9, c="white", s=2)
        ax[1, j].set_ylabel("Beat frequency (GHz)")
        ax[2, j].plot(t, analysis.plot_velocity_m_s, lw=.9, label="Working speed")
        ax[2, j].plot(t, analysis.apparent_velocity_m_s, lw=1.0, label="Formal apparent")
        ax[2, j].scatter(t, fit.apparent_velocity_m_s, s=4, color="#b35806", label="Dechirp")
        ax[2, j].set_ylabel("Apparent speed (m/s)")
        ax[3, j].plot(t, a / 1e9, lw=.8, label="Velocity difference")
        ax[3, j].plot(t, local / 1e9, lw=.8, label="Local linear (50 ns)")
        ax[3, j].plot(t, fit.apparent_acceleration_m_s2 / 1e9, lw=.8, marker=".", ms=2,
                      label="Dechirp (512)")
        ax[3, j].set_ylabel("Acceleration (10⁹ m/s²)")
        ax[3, j].set_xlabel("Time from candidate (ns)" if event else "Time from start (ns)")
        ax[3, j].set_xlim(lo, hi)
        visible = (t >= lo) & (t <= hi)
        values = np.abs(np.concatenate([a[visible], local[visible],
                                        fit.apparent_acceleration_m_s2[visible]]))
        if np.isfinite(values).any():
            limit = 1.1 * float(np.nanmax(values)) / 1e9
            if limit > 0:
                ax[3, j].set_ylim(-limit, limit)
        for axis in ax[:, j]:
            if event is not None:
                axis.axvline(0, color="#808080", linestyle=":", lw=.85)
    for row in (2, 3):
        ax[row, 0].legend(loc="best", fontsize=8)
    fig.suptitle(output.name)
    fig.savefig(output / "comparison.png", dpi=175)
    plt.close(fig)

    report = {
        "candidate_event_s": event, "n_frames": t.size, "sample_rate_hz": stft.sample_rate_hz,
        "difference_s": elapsed, "dechirp_s": times,
        "flags": {n: dict(Counter(result.flags)) for n, result in fits.items()},
        "accepted_by_stft_signal_state": dict(Counter(
            state.value for state, flag in zip(analysis.signal_detection_result.signal_states,
                                               fit.flags, strict=True) if flag == "accepted"
        )),
        "statistics": {
            label: {key: describe(t, values, span) for key, values in modes.items()}
            for label, span in (("full", np.ones_like(t, dtype=bool)),
                                ("onset_-25_60ns", (t >= -25) & (t <= 60)),
                                ("post_100_250ns", (t >= 100) & (t <= 250)),
                                ("pre_-250_-70ns", (t >= -250) & (t <= -70)))
        },
    }
    return report, fit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--desktop", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    app = create_application([], language_code="zh_CN")
    if args.desktop and app.platformName() != "windows":
        raise RuntimeError("Native Windows display is required.")
    window = MainWindow(
        settings=QSettings(str(output / "layout.ini"), QSettings.Format.IniFormat),
        translation_manager=translation_manager(),
        window_preset_repository=WindowPresetRepository(output / "presets.json"),
    )
    window.resize(1320, 780)
    window.show()
    reports = {}
    shots = {}
    try:
        for stem, channel in CASES:
            case = output / stem
            case.mkdir()
            dialog = ImportSettingsDialog(ROOT / "data/raw" / f"{stem}.csv", window)
            request = dialog.load_request()
            dialog.close()
            assert window._start_import(request)
            wait_for_idle(window)
            window.compute_stft_button.click()
            wait_for_idle(window)
            assert window.confirm_search_region_and_continue()
            wait_for_idle(window)
            window.window_material_combo.setCurrentIndex(window.window_material_combo.findData("none"))
            assert window.select_workflow_step(2)
            window.export_absolute_time_origin_radio.click()
            window.velocity_view.select_result_target("automatic", channel)
            analysis = window.analysis_session.channel_analyses[channel]
            record = window.analysis_session.records[channel]
            reports[stem], direct = compare(record, analysis, case)
            if stem != CASES[0][0]:
                continue
            if args.desktop:
                shots["velocity"] = capture(window, output / "velocity.png")
            view = window.acceleration_view
            click_tab(window, view)
            assert view.channel_combo.currentData() == channel
            assert view.acceleration_curve is not None
            x, y = view.acceleration_curve.getData()
            np.testing.assert_array_equal(x, analysis.stft_result.time_s * 1e6)
            np.testing.assert_array_equal(y, channel_acceleration(analysis).acceleration_m_s2*1e-9)
            if args.desktop:
                shots["difference"] = capture(window, output / "difference.png")
            view.method_combo.setCurrentIndex(view.method_combo.findData("dechirp"))
            assert view.acceleration_curve is None
            deadline = monotonic() + 40
            while view.acceleration_curve is None and monotonic() < deadline:
                loop = QEventLoop()
                QTimer.singleShot(50, loop.quit)
                loop.exec()
            assert view.acceleration_curve is not None, view.acceleration_notice.text()
            np.testing.assert_array_equal(
                view.acceleration_curve.getData()[1], direct.apparent_acceleration_m_s2*1e-9,
            )
            event = reports[stem]["candidate_event_s"]
            if event is not None:
                view.plot_widget.setXRange(event * 1e6 - .035, event * 1e6 + .18, padding=0)
                view._fit_visible()
            plot_point = view.plot_widget.mapFromScene(
                view.plot_widget.getViewBox().sceneBoundingRect().center(),
            )
            QTest.mouseMove(view.plot_widget.viewport(), QPoint(plot_point.x(), plot_point.y()))
            QTest.qWait(80)
            if args.desktop:
                shots["dechirp"] = capture(window, output / "dechirp.png")
                view.settings_toggle.click()
                shots["dechirp_settings"] = capture(window, output / "dechirp_settings.png")
                view.settings_toggle.click()
            view.method_combo.setCurrentIndex(0)
            np.testing.assert_array_equal(
                view.acceleration_curve.getData()[1], channel_acceleration(analysis).acceleration_m_s2*1e-9,
            )
            click_tab(window, window.velocity_view)
            np.testing.assert_allclose(window.velocity_view.plot_widget.viewRange()[0],
                                       view.plot_widget.viewRange()[0])
            assert window.select_workflow_step(3)
            window.export_channel_combo.setCurrentIndex(window.export_channel_combo.findData(channel))
            window.export_acceleration_check.setChecked(True)
            window.export_acceleration_fit_check.setChecked(True)
            window.export_dechirp_check.setChecked(True)
            window._set_export_output_directory(case)
            QTest.qWait(100)
            if args.desktop:
                shots["export"] = capture(window, output / "export.png")
            old_message = QMessageBox.information
            try:
                QMessageBox.information = staticmethod(lambda *_args: QMessageBox.StandardButton.Ok)
                assert window._export_current_result()
            finally:
                QMessageBox.information = old_message
            metadata = json.loads(next(case.glob("*.metadata.json")).read_text(encoding="utf-8"))
            entry = metadata["acceleration_dechirp"]
            assert entry["window_samples"] == 512
            with (case / entry["csv_file"]).open(encoding="utf-8") as handle:
                exported = list(csv.DictReader(handle))
            np.testing.assert_array_equal(
                [float(row["dechirp_apparent_acceleration_m_s2"]) for row in exported],
                direct.apparent_acceleration_m_s2,
            )
            assert tuple(row["dechirp_flag"] for row in exported) == direct.flags
            assert "local_linear_acceleration_m_s2" in exported[0]
    finally:
        window.close()
    (output / "comparison.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    (output / "desktop.json").write_text(
        json.dumps({"platform": app.platformName(), "shots": shots}, indent=2), encoding="utf-8",
    )


if __name__ == "__main__":
    main()
