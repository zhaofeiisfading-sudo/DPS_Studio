"""Headless Qt raster plots of the resolved Production analysis arrays."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import QCoreApplication, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
)

from dps_studio.core.export.bundle import channel_token
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow.acceleration import channel_acceleration
from dps_studio.core.workflow.models import ChannelAnalysis, FloatArray

PLOT_NAMES = ("spectrogram", "ridge", "velocity", "acceleration")
_AXES = QRectF(111, 92, 821, 441)
_INK = "#233447"
_MUTED = "#546477"
_BLUE = "#005e91"
_ORANGE = "#b44a17"


@dataclass(frozen=True, slots=True)
class _Trace:
    label: str
    values: FloatArray
    color: str
    style: Qt.PenStyle = Qt.PenStyle.SolidLine


@contextmanager
def headless_plot_application() -> Iterator[None]:
    # Keep an existing application in charge of its own Qt platform and lifetime.
    application = None
    if QCoreApplication.instance() is None:
        application = QGuiApplication(["pdv", "-platform", "offscreen"])
    font_id = -1
    try:
        if isinstance(QCoreApplication.instance(), QGuiApplication):
            font_id = _load_platform_font()
        yield
    finally:
        if font_id >= 0:
            QFontDatabase.removeApplicationFont(font_id)
        if application is not None:
            application.shutdown()


def _load_platform_font() -> int:
    # Some offscreen Qt platforms start with an empty font database.
    if QFontMetricsF(QFont()).inFont("A"):
        return -1
    match sys.platform:
        case "win32":
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
        case "darwin":
            path = Path("/System/Library/Fonts/Supplemental/Arial.ttf")
        case _:
            path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    return QFontDatabase.addApplicationFont(str(path)) if path.is_file() else -1


def render_channel_figures(
    analysis: ChannelAnalysis,
    directory: Path,
    *,
    prefix: str,
    frequency_bounds_hz: tuple[float, float],
    relative_db_floor: float,
    include_acceleration: bool,
    acceleration_fit_window_s: float | None,
) -> dict[str, str]:
    names = {name: f"{prefix}{name}.png" for name in PLOT_NAMES}
    stft = analysis.stft_result
    time_ns = (stft.time_s - stft.time_s[0]) * 1e9
    time_label = f"Time since {stft.time_s[0]:.10g} s (ns)"
    low, high = frequency_bounds_hz
    _spectrogram(
        analysis, directory / names["spectrogram"], time_ns, time_label,
        (low / 1e9, high / 1e9), relative_db_floor,
    )
    _line_plot(
        directory / names["ridge"], "Working ridge", time_ns, time_label,
        "Beat frequency (GHz)",
        (_Trace("Selected ridge", analysis.working_frequency_hz / 1e9, _BLUE),),
    )
    _line_plot(
        directory / names["velocity"], "Reconstructed velocity", time_ns, time_label,
        "Velocity (m/s)",
        (
            _Trace("Display velocity", analysis.display_velocity_m_s, _MUTED,
                   Qt.PenStyle.DotLine),
            _Trace("Formal apparent", analysis.apparent_velocity_m_s, _BLUE),
            _Trace("Formal corrected", analysis.corrected_velocity_m_s, _ORANGE,
                   Qt.PenStyle.DashLine),
        ),
    )
    acceleration: tuple[_Trace, ...] = ()
    if include_acceleration:
        acceleration = (_Trace("Finite difference", channel_acceleration(analysis).acceleration_m_s2,
                               _BLUE),)
        if acceleration_fit_window_s is not None:
            fit = channel_acceleration(analysis, window_s=acceleration_fit_window_s)
            acceleration += (_Trace("Local linear fit", fit.acceleration_m_s2, _ORANGE),)
    _line_plot(
        directory / names["acceleration"], "Velocity-derived acceleration", time_ns, time_label,
        "Acceleration (m/s^2)", acceleration, empty_message=(
            "No finite velocity derivative" if include_acceleration else "Acceleration disabled"
        ),
    )
    return names


def _canvas(title: str, x_label: str, y_label: str) -> QImage:
    image = QImage(1060, 620, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    image.setDotsPerMeterX(5906)
    image.setDotsPerMeterY(5906)
    image.setText("Title", title)
    image.setText("Axes", f"{x_label}, {y_label}")
    return image


def _label(
    painter: QPainter, x: float, y: float, label: str, size: int = 13, *, anchor: float = 0.0,
) -> None:
    # Qt's font database requires a GUI application. PNG metadata retains the
    # labels and bounds even for a caller that supplied a core-only application.
    if isinstance(QCoreApplication.instance(), QGuiApplication):
        font = QFont()
        font.setPixelSize(size)
        painter.setFont(font)
        if anchor:
            x -= anchor * QFontMetricsF(font).horizontalAdvance(label)
        painter.drawText(QPointF(x, y), label)


def _axes(
    painter: QPainter, title: str, x_label: str, y_label: str,
    x_limits: tuple[float, float], y_limits: tuple[float, float], *, grid: bool,
) -> None:
    painter.setPen(QColor(_INK))
    _label(painter, _AXES.left(), 36, title, 24)
    _label(painter, _AXES.center().x(), 593, x_label, 15, anchor=0.5)
    painter.save()
    painter.translate(24, _AXES.center().y())
    painter.rotate(-90)
    _label(painter, 0, 0, y_label, 15, anchor=0.5)
    painter.restore()
    for fraction in np.linspace(0.0, 1.0, 6):
        x = _AXES.left() + float(fraction) * _AXES.width()
        y = _AXES.bottom() - float(fraction) * _AXES.height()
        if grid:
            painter.setPen(QColor("#e4eaf0"))
            painter.drawLine(QPointF(x, _AXES.top()), QPointF(x, _AXES.bottom()))
            painter.drawLine(QPointF(_AXES.left(), y), QPointF(_AXES.right(), y))
        painter.setPen(QColor(_INK))
        painter.drawLine(QPointF(x, _AXES.bottom()), QPointF(x, _AXES.bottom() + 5))
        painter.drawLine(QPointF(_AXES.left() - 5, y), QPointF(_AXES.left(), y))
        x_value = x_limits[0] + fraction * (x_limits[1] - x_limits[0])
        y_value = y_limits[0] + fraction * (y_limits[1] - y_limits[0])
        _label(painter, x, _AXES.bottom() + 22, f"{x_value:.4g}", anchor=0.5)
        _label(painter, _AXES.left() - 10, y + 4, f"{y_value:.4g}", anchor=1.0)
    painter.drawRect(_AXES)


def _spectrogram(
    analysis: ChannelAnalysis, path: Path, time_ns: FloatArray, time_label: str,
    band_ghz: tuple[float, float], db_floor: float,
) -> None:
    stft = analysis.stft_result
    image = _canvas("STFT magnitude spectrum", time_label, "Frequency (GHz)")
    frequencies = stft.frequency_hz / 1e9
    rows = np.flatnonzero((frequencies >= band_ghz[0]) & (frequencies <= band_ghz[1]))
    values = np.abs(stft.spectrum[rows, :])
    y_indices = np.linspace(len(rows) - 1, 0, int(_AXES.height())).round().astype(int)
    x_indices = np.linspace(0, time_ns.size - 1, int(_AXES.width())).round().astype(int)
    sampled = values[np.ix_(y_indices, x_indices)]
    peak = float(values.max())
    relative_db = np.full(sampled.shape, db_floor)
    if peak > 0.0:
        with np.errstate(divide="ignore"):
            relative_db = 20 * np.log10(sampled / peak)
    colors = _heatmap(np.clip((relative_db - db_floor) / -db_floor, 0.0, 1.0))
    bar = _heatmap(np.linspace(1.0, 0.0, int(_AXES.height()))[:, None])
    time_bounds = (0.0, float(time_ns[-1]))
    band = (float(frequencies[rows[0]]), float(frequencies[rows[-1]]))
    image.setText("Scale", f"Time {time_bounds}, frequency {band}, relative dB [{db_floor}, 0]")
    with QPainter(image) as painter:
        painter.drawImage(_AXES, colors)
        _axes(painter, "STFT magnitude spectrum", time_label, "Frequency (GHz)",
              time_bounds, band, grid=False)
        painter.drawImage(QRectF(956, _AXES.top(), 13, _AXES.height()), bar)
        painter.setPen(QColor(_INK))
        _label(painter, 952, 74, "Rel. dB")
        for fraction in np.linspace(0.0, 1.0, 5):
            _label(painter, 977, _AXES.top() + fraction * _AXES.height() + 4,
                   str(round(db_floor * fraction)))
    _save(image, path)


def _heatmap(levels: FloatArray) -> QImage:
    # Dark blue to teal to yellow. Raster sampling never changes analysis arrays.
    anchors = np.array([(16, 28, 54), (26, 70, 107), (31, 126, 128), (112, 176, 103),
                        (250, 224, 124)])
    positions = np.linspace(0.0, 1.0, len(anchors))
    rgb = np.stack([np.interp(levels, positions, color) for color in anchors.T], axis=-1)
    pixels = np.ascontiguousarray(rgb, dtype=np.uint8)
    height, width, _ = pixels.shape
    return QImage(pixels.data, width, height, pixels.strides[0],
                  QImage.Format.Format_RGB888).copy()


def _line_plot(
    path: Path, title: str, time_ns: FloatArray, time_label: str, y_label: str,
    traces: tuple[_Trace, ...], *, empty_message: str = "No finite values",
) -> None:
    image = _canvas(title, time_label, y_label)
    valid = [trace.values[np.isfinite(trace.values)] for trace in traces]
    finite = [values for values in valid if values.size]
    y_min, y_max = 0.0, 1.0
    if finite:
        low = min(float(values.min()) for values in finite)
        high = max(float(values.max()) for values in finite)
        margin = (high - low) * 0.06 if low != high else (abs(low) or 1.0) * 0.06
        y_min, y_max = low - margin, high + margin
    time_bounds = (0.0, float(time_ns[-1]))
    image.setText("Scale", f"Time {time_bounds}, values ({y_min}, {y_max})")
    image.setText("Traces", ", ".join(trace.label for trace in traces) if finite else empty_message)
    with QPainter(image) as painter:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _axes(painter, title, time_label, y_label, time_bounds, (y_min, y_max), grid=True)
        x = _AXES.left() + time_ns / time_bounds[1] * _AXES.width()
        for index, trace in enumerate(traces):
            pen = QPen(QColor(trace.color), 2.0, trace.style)
            painter.setPen(pen)
            legend_x = _AXES.left() + 202 * index
            painter.drawLine(QPointF(legend_x, 62), QPointF(legend_x + 26, 62))
            painter.setPen(QColor(_INK))
            _label(painter, legend_x + 33, 66, trace.label)
            painter.save()
            painter.setClipRect(_AXES)
            painter.setPen(pen)
            y = _AXES.bottom() - (trace.values - y_min) / (y_max - y_min) * _AXES.height()
            edges = np.flatnonzero(np.diff(np.isfinite(y), prepend=False, append=False))
            for start, stop in zip(edges[::2], edges[1::2], strict=True):
                points = [QPointF(a, b) for a, b in zip(x[start:stop], y[start:stop], strict=True)]
                if len(points) == 1:
                    painter.drawPoint(points[0])
                else:
                    painter.drawPolyline(QPolygonF(points))
            painter.restore()
        if not finite:
            painter.setPen(QColor(_MUTED))
            _label(painter, _AXES.center().x(), _AXES.center().y(), empty_message, 17, anchor=0.5)
    _save(image, path)


def _save(image: QImage, path: Path) -> None:
    if not image.save(str(path)):
        raise OSError(f"Could not write PNG: {path}")


def render_bundle_spectrogram_ridge(
    analyses: Mapping[str, ChannelAnalysis],
    path: Path,
    *,
    channel_frequency_bounds_hz: Mapping[str, tuple[float, float]],
    relative_db_floor: float = -60.0,
) -> None:
    """Render one combined spectrogram + ridge overview PNG across all channels."""
    if not analyses:
        raise ValueError("At least one channel analysis is required for plotting.")
    width = 1080
    panel_height = 560
    count = len(analyses)
    image = QImage(width, panel_height * count, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    image.setDotsPerMeterX(5906)
    image.setDotsPerMeterY(5906)

    scale_notes: list[str] = []
    time_axis_label = "Time (ns)"
    with QPainter(image) as painter:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for index, (channel_name, analysis) in enumerate(analyses.items()):
            y_offset = float(index * panel_height)
            axes = QRectF(110.0, y_offset + 90.0, 820.0, 405.0)
            stft = analysis.stft_result
            time_ns = (stft.time_s - stft.time_s[0]) * 1e9
            time_axis_label = f"Time since {stft.time_s[0]:.10g} s (ns)"
            frequencies_ghz = stft.frequency_hz / 1e9
            low_hz, high_hz = channel_frequency_bounds_hz[channel_name]
            rows = np.flatnonzero(
                (stft.frequency_hz >= low_hz - 1e-6) & (stft.frequency_hz <= high_hz + 1e-6)
            )
            if rows.size < 2:
                rows = np.arange(stft.frequency_hz.size, dtype=np.int64)
            values = np.abs(stft.spectrum[rows, :])
            y_indices = np.linspace(len(rows) - 1, 0, int(axes.height())).round().astype(int)
            x_indices = np.linspace(0, time_ns.size - 1, int(axes.width())).round().astype(int)
            sampled = values[np.ix_(y_indices, x_indices)]
            peak = float(values.max()) if values.size else 0.0
            relative_db = np.full(sampled.shape, relative_db_floor, dtype=np.float64)
            if peak > 0.0:
                with np.errstate(divide="ignore"):
                    relative_db = 20.0 * np.log10(sampled / peak)
            levels = np.clip((relative_db - relative_db_floor) / -relative_db_floor, 0.0, 1.0)
            colors = _heatmap(levels)
            bar = _heatmap(np.linspace(1.0, 0.0, int(axes.height()))[:, None])

            time_span = float(time_ns[-1]) if float(time_ns[-1]) > 0.0 else 1.0
            band_ghz = (float(frequencies_ghz[rows[0]]), float(frequencies_ghz[rows[-1]]))
            freq_span = (band_ghz[1] - band_ghz[0]) if band_ghz[1] > band_ghz[0] else 1.0

            detection = analysis.signal_detection_result
            measured_mask = np.asarray(
                [state is SignalState.MEASURED for state in detection.signal_states],
                dtype=np.bool_,
            )
            measured = int(np.count_nonzero(measured_mask))
            total = len(detection.signal_states)
            pct = (100.0 * measured / total) if total else 0.0
            token = channel_token(channel_name)
            header = (
                f"{token} ({channel_name})  |  Band: {band_ghz[0]:.3g}-{band_ghz[1]:.3g} GHz"
                f"  |  Measured: {measured}/{total} ({pct:.1f}%)"
            )
            scale_notes.append(
                f"{token}: Time (0.0, {float(time_ns[-1]):.6g}) ns, Frequency {band_ghz} GHz, dB [{relative_db_floor}, 0]"
            )

            painter.drawImage(axes, colors)
            painter.setPen(QColor(_INK))
            _label(painter, axes.left(), y_offset + 34.0, header, 20)
            _label(painter, axes.center().x(), y_offset + 542.0, time_axis_label, 14, anchor=0.5)
            painter.save()
            painter.translate(24.0, axes.center().y())
            painter.rotate(-90)
            _label(painter, 0.0, 0.0, "Frequency (GHz)", 14, anchor=0.5)
            painter.restore()

            for fraction in np.linspace(0.0, 1.0, 6):
                x = axes.left() + float(fraction) * axes.width()
                y = axes.bottom() - float(fraction) * axes.height()
                painter.setPen(QColor(_INK))
                painter.drawLine(QPointF(x, axes.bottom()), QPointF(x, axes.bottom() + 5.0))
                painter.drawLine(QPointF(axes.left() - 5.0, y), QPointF(axes.left(), y))
                x_value = float(fraction) * float(time_ns[-1])
                y_value = band_ghz[0] + float(fraction) * freq_span
                _label(painter, x, axes.bottom() + 21.0, f"{x_value:.4g}", 12, anchor=0.5)
                _label(painter, axes.left() - 9.0, y + 4.0, f"{y_value:.4g}", 12, anchor=1.0)
            painter.drawRect(axes)

            painter.drawImage(QRectF(954.0, axes.top(), 14.0, axes.height()), bar)
            painter.setPen(QColor(_INK))
            _label(painter, 950.0, axes.top() - 12.0, "Rel. dB", 12)
            for fraction in np.linspace(0.0, 1.0, 5):
                _label(
                    painter,
                    976.0,
                    axes.top() + float(fraction) * axes.height() + 4.0,
                    str(round(relative_db_floor * float(fraction))),
                    12,
                )

            working_ghz = analysis.working_frequency_hz / 1e9
            formal_ghz = np.where(measured_mask, detection.refined_frequency_hz / 1e9, np.nan)
            x_pixels = axes.left() + time_ns / time_span * axes.width()

            working_pen = QPen(QColor("#cfd8e3"), 1.8, Qt.PenStyle.DashLine)
            formal_pen = QPen(QColor("#ff4d4d"), 2.4, Qt.PenStyle.SolidLine)

            legend_items = (
                ("Working ridge", working_pen, axes.left()),
                ("Formal gated ridge", formal_pen, axes.left() + 185.0),
            )
            for label_text, pen, lx in legend_items:
                painter.setPen(pen)
                painter.drawLine(QPointF(lx, y_offset + 62.0), QPointF(lx + 26.0, y_offset + 62.0))
                painter.setPen(QColor(_INK))
                _label(painter, lx + 33.0, y_offset + 66.0, label_text, 12)

            painter.save()
            painter.setClipRect(axes)
            for ridge_ghz, pen in ((working_ghz, working_pen), (formal_ghz, formal_pen)):
                painter.setPen(pen)
                y_pixels = axes.bottom() - (ridge_ghz - band_ghz[0]) / freq_span * axes.height()
                finite_mask = np.isfinite(x_pixels) & np.isfinite(y_pixels)
                edges = np.flatnonzero(np.diff(finite_mask.astype(np.int8), prepend=0, append=0))
                for seg_start, seg_stop in zip(edges[::2], edges[1::2], strict=True):
                    pts = [
                        QPointF(float(x_pixels[k]), float(y_pixels[k]))
                        for k in range(int(seg_start), int(seg_stop))
                    ]
                    if len(pts) == 1:
                        painter.drawPoint(pts[0])
                    elif pts:
                        painter.drawPolyline(QPolygonF(pts))
            painter.restore()

    image.setText("Title", "Spectrogram & Ridge")
    image.setText("Channels", ", ".join(analyses))
    image.setText("Axes", f"{time_axis_label}, Frequency (GHz)")
    image.setText("Scale", "; ".join(scale_notes))
    image.setText("Traces", "Working ridge, Formal gated ridge")
    _save(image, path)
