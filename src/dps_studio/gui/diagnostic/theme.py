"""Display-only palette and finite-safe spectrogram contrast."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg  # type: ignore[import-untyped]
from numpy.typing import NDArray
from PySide6.QtGui import QColor

METHOD_COLORS = {
    "B0": "#d55e00",
    "B1": "#0284c7",
    "B+S": "#1d4ed8",
    "Dechirp": "#059669",
    "VarPro": "#9333ea",
    "S2": "#be123c",
}
ESTIMATOR_COLORS = {**METHOD_COLORS, "dechirp": "#059669", "varpro": "#9333ea"}
ANOMALIES = (
    ("disagreement_mask", "分歧>100MHz", "#dc2626"),
    ("g_without_s_mask", "G无S", "#d97706"),
    ("s2_rescued_mask", "S2救回", "#059669"),
    ("competing_clusters_mask", "多支路竞争", "#9333ea"),
    ("high_without_s_mask", "高共识缺S", "#be123c"),
)
STAGE_COLORS = {
    "onset": "#fef3c7",
    "decline": "#ffe4e6",
    "weak_signal": "#ede9fe",
    "stationary": "#e9eef2",
    "plateau": "#edf2f7",
}
STYLE = """
QWidget#diagnosticWorkspace, QWidget#diagnosticProperties {background:#f5f7f9;color:#263746;}
QGroupBox {background:#ffffff;border:1px solid #d6dde3;border-radius:5px;
 margin-top:14px;padding:8px 5px 5px 5px;font-weight:600;}
QGroupBox::title {subcontrol-origin:margin;left:8px;padding:0 4px;}
QTableWidget {background:#ffffff;gridline-color:#e8edf1;font-size:11px;}
QHeaderView::section {background:#edf2f6;color:#263746;padding:3px;border:0;}
QLabel[badge="warning"] {background:#fff5df;color:#80551c;border-radius:4px;padding:5px;}
QLabel[badge="info"] {background:#eaf3fc;color:#24577e;border-radius:4px;padding:5px;}
QToolButton {padding:3px 5px;border:1px solid #d6dde3;border-radius:4px;background:white;}
QToolButton:checked {background:#e4edf7;border-color:#8aa9c7;}
"""


def contrast_levels(values: NDArray[np.float64], mode: str = "adaptive") -> tuple[float, float]:
    finite = values[np.isfinite(values)]
    if not finite.size:
        return -100.0, 0.0
    percentiles = {"adaptive": (55, 99.7), "weak": (65, 98.5), "full": (0, 100)}[mode]
    lo, hi = (float(v) for v in np.percentile(finite, percentiles))
    return lo, max(hi, lo + 1e-6)


def spectrogram_lut() -> NDArray[np.uint8]:
    # Explicit built-in stops keep the packaged GUI independent of plotting extras.
    colors = [
        QColor(c).getRgb()
        for c in ("#f5f8fc", "#bfd5e6", "#4b91b6", "#225a84", "#293659", "#e1a33c", "#fff2ba")
    ]
    return np.asarray(
        pg.ColorMap(np.linspace(0, 1, len(colors)), colors).getLookupTable(0, 1, 256),
        dtype=np.uint8,
    )


def number(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}" if np.isfinite(value) else "—"
