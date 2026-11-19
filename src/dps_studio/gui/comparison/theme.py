"""Display palette and contrast for the side-by-side comparison."""
from dps_studio.gui.diagnostic.theme import contrast_levels, spectrogram_lut

AXIS_TEXT = "#263746"

COLORS = {
    "b1": "#0284c7",
    "m4": "#d9480f",
    "matched": "#0d9488",
    "secondary": "#7c3aed",
    "supported": "#16a34a",
    "branch": "#dc2626",
    "risk": "#be123c",
    "ambiguous": "#a16207",
    "minor": "#64748b",
    "weak": "#6b7280",
    "rejected": "#f7d6be",
    "cursor": "#0891b2",
    "raw_voltage": "#334155",
    "residual": "#475569",
    "baseline": "#8194a6",
    "dc_step": "#b45309",
    "rail": "#b91c1c",
}

STYLE = """
QWidget#comparisonWorkspace, QWidget#comparisonProperties {background:#f6f8fa;}
QWidget#comparisonWorkspace QToolButton, QWidget#comparisonProperties QToolButton {
 background:white; border:1px solid #cbd5df; border-radius:4px; padding:3px 5px;
}
QWidget#comparisonWorkspace QToolButton:checked {
 background:#dbeef8; border-color:#72a9c7; color:#0c4a6e;
}
QWidget#comparisonWorkspace QToolButton:disabled,
QWidget#comparisonProperties QToolButton:disabled {color:#87929d;background:#f1f4f6;}
QWidget#comparisonProperties QGroupBox {margin-top:7px; padding-top:3px;}
QWidget#comparisonProperties QPushButton,
QWidget#comparisonProperties QComboBox,
QWidget#comparisonProperties QDoubleSpinBox {min-height:21px;}
QWidget#comparisonProperties QCheckBox {min-height:20px; spacing:6px;}
QWidget#comparisonProperties QProgressBar {
 border:1px solid #cbd5df; border-radius:4px; text-align:center;
 background:white; color:#0f172a;
}
QWidget#comparisonProperties QProgressBar::chunk {background:#a9d7ee;}
QWidget#comparisonWorkspace QCheckBox::indicator,
QWidget#comparisonProperties QCheckBox::indicator {
 width:12px; height:12px; border:1px solid #738798; border-radius:3px; background:white;
}
QWidget#comparisonWorkspace QCheckBox::indicator:checked,
QWidget#comparisonProperties QCheckBox::indicator:checked {
 background:#0879aa; border:1px solid #075985;
}
QWidget#comparisonProperties QPushButton#computeComparison {
 background:#075985; color:white; border-color:#075985; font-weight:600;
}
QWidget#comparisonProperties QPushButton#computeComparison:disabled {
 background:#e6edf2; color:#6b7d8a; border-color:#d6dde3;
}
"""

__all__ = ["AXIS_TEXT", "COLORS", "STYLE", "contrast_levels", "spectrogram_lut"]
