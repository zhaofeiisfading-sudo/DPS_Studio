"""Opt-in real-window capture driven by an explicit JSON specification."""
from __future__ import annotations

import json
import sys
from math import isfinite
from pathlib import Path
from typing import Any

from PySide6.QtCore import QBuffer, QIODevice, QSettings, QTemporaryDir, QTimer

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.core.stft_m4 import StftM4ComparisonBundle, convert_frequency_for_display

from .workspace import ComparisonWorkspace


def _select(combo: Any, key: str) -> None:
    index = combo.findData(key)
    if index < 0 or not combo.model().item(index).isEnabled():
        raise ValueError(f"Unavailable capture option: {key}")
    combo.setCurrentIndex(index)


def _apply_view(workspace: ComparisonWorkspace, shot: dict[str, Any]) -> None:
    for field, combo in (("layout", workspace.layout_combo), ("contrast", workspace.contrast_combo),
                         ("background", workspace.background_combo)):
        if field in shot:
            _select(combo, str(shot[field]))
    if "display" in shot:
        workspace.view_buttons[shot["display"]].click()
    for name, box in zip(("final", "rejected", "candidates", "secondary", "matched"),
                         workspace.layer_boxes, strict=True):
        if name in shot.get("layers", {}):
            box.setChecked(bool(shot["layers"][name]))
    if "wavelength_nm" in shot:
        panel = workspace.properties
        value = float(shot["wavelength_nm"])
        if not isfinite(value) or not .001 <= value <= panel.wavelength_nm.maximum():
            raise ValueError("Invalid capture wavelength in nm")
        panel.confirm_wavelength.setChecked(True)
        panel.wavelength_nm.setValue(value)
    if "unit" in shot:
        _select(workspace.unit_combo, str(shot["unit"]))
    if "region" in shot:
        _select(workspace.region_combo, str(shot["region"]))
    if "frame_index" in shot:
        frame = int(shot["frame_index"])
        if workspace.bundle is None or not 0 <= frame < len(workspace.bundle.q):
            raise ValueError("Capture frame_index lies outside the comparison")
        workspace.select_frame(frame)
    elif "time_us" in shot:
        workspace.select_time(float(shot["time_us"])*1e-6)
    if "frequency_range_ghz" in shot:
        low, high = map(float, shot["frequency_range_ghz"])
        if not 0. <= low < high or not isfinite(high):
            raise ValueError("Invalid capture frequency_range_ghz")
        scale = workspace.plots.wavelength_m
        factor = 1. if scale is None else scale*0.5e9
        workspace.plots.left_plot.setYRange(low*factor, high*factor, padding=0.)
    if "zoom_ns" in shot:
        zoom = float(shot["zoom_ns"])
        if not isfinite(zoom) or zoom <= 0.:
            raise ValueError("Capture zoom_ns must be a positive half-width")
        workspace.zoom_selected(zoom)
    if "time_range_us" in shot:
        low, high = map(float, shot["time_range_us"])
        if not isfinite(low) or not isfinite(high) or low >= high:
            raise ValueError("Invalid capture time_range_us")
        workspace.plots.left_plot.setXRange(low, high, padding=0.)
    if "waveform" in shot:
        workspace.inspector.waveform_mode_combo.setCurrentIndex(
            {"residual": 0, "raw": 1}[shot["waveform"]]
        )


def _evidence(workspace: ComparisonWorkspace, bundle: StftM4ComparisonBundle) -> dict[str, Any]:
    def finite(value: float) -> float | None:
        return float(value) if isfinite(value) else None

    frame = workspace.inspector.current
    if frame is None:
        return {}
    i = frame.frame_index
    evidence = {
        key: {
            "accepted_hz": finite(point.accepted_hz),
            "candidate_hz": finite(point.candidate_hz),
            "secondary_hz": finite(point.secondary_hz),
            "raw_chirp_r2_6p4ns": finite(point.raw_chirp_r2_64ns),
            "quality_flag": point.quality_flag,
        }
        for key, point in (("b1", frame.b1), ("m4", frame.m4))
    }
    plots = workspace.plots
    (xlo, xhi), (ylo, yhi) = plots.curve_plot.viewRange()
    times_us = bundle.frame_time_s * 1e6
    m4_hz = bundle.m4.accepted_hz
    m4_y = convert_frequency_for_display(m4_hz, confirmed_wavelength_m=plots.wavelength_m)[0]
    visible = m4_hz[(times_us >= xlo) & (times_us <= xhi) & (m4_y >= ylo) & (m4_y <= yhi)]
    return {
        "frame_evidence": evidence,
        "matched_stft_accepted_hz": (
            finite(bundle.matched_stft.accepted_hz[i]) if bundle.matched_stft is not None else None
        ),
        "waveform_events": {"dc_steps": len(frame.dc_step_time_s), "rail_points": len(frame.rail_time_s),
                            "rail_exits": len(frame.rail_exit_time_s)},
        "visible_m4_published_hz": {
            "count": len(visible),
            "range": [float(visible.min()), float(visible.max())] if len(visible) else None,
        },
    }


def run_capture_spec(path: Path) -> int:
    """Load, compute on the real QThread, render each shot and exit the Qt loop."""
    from dps_studio.gui.app import create_application, translation_manager
    from dps_studio.gui.research_safety import protected_path
    from dps_studio.gui.research_window import ResearchMainWindow

    spec = json.loads(path.read_text(encoding="utf-8"))
    base = path.resolve().parent
    report = base / spec["report"]
    shots: list[dict[str, Any]] = spec["captures"]
    if not shots:
        raise ValueError("Capture spec requires at least one screenshot")
    destinations = [report, *(base / shot["screenshot"] for shot in shots)]
    if len({target.resolve() for target in destinations}) != len(destinations):
        raise ValueError("Capture output paths must be distinct")
    for target in destinations:
        if protected_path(target) or target.exists():
            raise ValueError(f"Capture output must be a new writable file: {target}")

    temp = QTemporaryDir()
    if not temp.isValid():
        raise OSError("Cannot create temporary capture preferences directory")
    temporary = Path(temp.path())
    app = create_application(("PDV Studio Research",))
    window = ResearchMainWindow(
        translation_manager=translation_manager(),
        settings=QSettings(str(temporary / "layout.ini"), QSettings.Format.IniFormat),
        window_preset_repository=WindowPresetRepository(temporary / "window_presets.json"),
    )
    window.mode_combo.setCurrentIndex(3)
    workspace = window.comparison_workspace
    window.show()
    captures: list[dict[str, Any]] = []
    completed = False
    progress: list[dict[str, int | str]] = []

    def finish(error: str | None, bundle: StftM4ComparisonBundle | None = None) -> None:
        nonlocal completed
        if completed:
            return
        completed = True
        data: dict[str, Any] = {"event_loop_entered": True, "captures": captures,
                                "executable": sys.executable, "frozen": bool(getattr(sys, "frozen", False)),
                                "mode": window.mode_combo.currentData(), "progress": progress}
        if error is not None:
            data["error"] = error
        if bundle is not None:
            data.update(channel=bundle.channel_name, sample_rate_hz=bundle.sample_rate_hz,
                        frames=len(bundle.q), b1_wall_s=bundle.b1_wall_s, m4_wall_s=bundle.m4_wall_s,
                        matched_stft_wall_s=bundle.matched_stft_wall_s, total_wall_s=bundle.total_wall_s,
                        fmin_hz=bundle.fmin_hz, fmax_hz=bundle.fmax_hz)
        exit_code = int(error is not None)
        try:
            report.parent.mkdir(parents=True, exist_ok=True)
            with report.open("x", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
        except OSError:
            exit_code = 1
        finally:
            window.close()
            app.exit(exit_code)

    def save_shot(i: int, bundle: StftM4ComparisonBundle) -> None:
        if completed:
            return
        try:
            shot = shots[i]
            out = base / shot["screenshot"]
            out.parent.mkdir(parents=True, exist_ok=True)
            buffer = QBuffer()
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            pixmap = window.grab()
            if not pixmap.save(buffer, "PNG"):
                raise OSError(f"Cannot encode window screenshot: {out}")
            with out.open("xb") as stream:
                stream.write(buffer.data().data())
            inspected = workspace.inspector.current
            handle = window.windowHandle()
            captures.append({
                "screenshot": str(out.resolve()), "width": pixmap.width(), "height": pixmap.height(),
                "logical_size": [window.width(), window.height()],
                "device_pixel_ratio": pixmap.devicePixelRatio(),
                "window_visible": window.isVisible(), "window_exposed": handle is not None and handle.isExposed(),
                "qt_platform": app.platformName(), "selected_frame": workspace.selected_frame,
                "frame_time_s": inspected.center_time_s if inspected else None,
                "category": inspected.category.value if inspected else None,
                "m4_rejection_reason_code": inspected.reason.value if inspected else None,
                "view_ranges": [plot.viewRange() for plot in workspace.plots.linked_plots],
                "left_levels_db": workspace.plots.left_image.getLevels().tolist(),
                "right_levels_db": workspace.plots.right_image.getLevels().tolist(),
                **_evidence(workspace, bundle),
            })
        except Exception as exc:
            finish(f"{type(exc).__name__}: {exc}", bundle)
            return
        capture(i+1, bundle)

    def capture(i: int, bundle: StftM4ComparisonBundle) -> None:
        if i == len(shots):
            finish(None, bundle)
            return
        try:
            shot = shots[i]
            width, height = shot.get("size", [1600, 960])
            window.resize(int(width), int(height))
            _apply_view(workspace, shot)
            QTimer.singleShot(120, lambda: save_shot(i, bundle))
        except Exception as exc:
            finish(f"{type(exc).__name__}: {exc}", bundle)

    def start() -> None:
        try:
            source = base / spec["input"]
            channel = str(spec.get("channel", "ch1"))
            loaded = read_delimited_signals(
                source, time_column=int(spec.get("time_column", 0)),
                voltage_columns={channel: int(spec.get("voltage_column", 1))},
                delimiter=str(spec.get("delimiter", ",")), has_header=bool(spec.get("has_header", False)),
                time_scale=float(spec.get("time_scale", 1.)),
                voltage_scales={channel: float(spec.get("voltage_scale", 1.))},
            )
            window.set_loaded_result(loaded)
            panel = workspace.properties
            panel.fmin_spin.setValue(float(spec.get("fmin_mhz", 50.)))
            panel.fmax_spin.setValue(float(spec.get("fmax_mhz", 6000.)))
            panel.matched_checkbox.setChecked(bool(spec.get("include_matched_stft", False)))
            if not workspace.start():
                raise RuntimeError("Comparison could not start")
        except Exception as exc:
            finish(f"{type(exc).__name__}: {exc}")

    workspace.stateChanged.connect(lambda stage: progress.append({
        "percent": workspace.properties.progress_bar.value(), "stage": stage,
    }))
    workspace.finished.connect(lambda bundle: capture(0, bundle))
    workspace.failed.connect(finish)
    workspace.cancelled.connect(lambda: finish("Comparison cancelled"))
    QTimer.singleShot(0, start)
    return app.exec()
