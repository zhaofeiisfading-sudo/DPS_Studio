"""Tests for TASK-009 point-complete, locally unsimplified line rendering."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.figure import Figure
from pytest import MonkeyPatch, raises


SCRIPTS_DIRECTORY = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPTS_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIRECTORY))

plotting = importlib.import_module("compare_real_ridge_refinement")


def test_plot_complete_series_retains_every_value_and_nan_position() -> None:
    figure, axis = plt.subplots()
    x_values = np.array([0.0, 1.0, 2.0, 3.0], dtype=np.float64)
    y_values = np.array([4.0, np.nan, 6.0, 7.0], dtype=np.float64)

    line = plotting._plot_complete_series(  # noqa: SLF001
        axis,
        x_values,
        y_values,
        linewidth=plotting.PRESENTATION_LINE_WIDTH,
        marker="o",
        markersize=plotting.PLATEAU_DETAIL_MARKER_SIZE,
    )

    plotted_x = np.asarray(line.get_xdata(orig=True))
    plotted_y = np.asarray(line.get_ydata(orig=True))
    assert plotted_x.size == x_values.size
    assert plotted_y.size == y_values.size
    assert np.array_equal(plotted_x, x_values, equal_nan=True)
    assert np.array_equal(plotted_y, y_values, equal_nan=True)
    assert np.array_equal(np.isnan(plotted_y), np.isnan(y_values))
    assert np.array_equal(plotted_y[np.isfinite(plotted_y)], y_values[np.isfinite(y_values)])
    plt.close(figure)


def test_plot_complete_series_rejects_mismatched_lengths() -> None:
    figure, axis = plt.subplots()
    with raises(ValueError, match="identical shape"):
        plotting._plot_complete_series(  # noqa: SLF001
            axis,
            np.array([0.0, 1.0], dtype=np.float64),
            np.array([0.0], dtype=np.float64),
            linewidth=plotting.FULL_DISPLAY_LINE_WIDTH,
        )
    plt.close(figure)


def test_save_figure_disables_simplification_only_during_render(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    figure = Figure()
    observed: list[bool] = []
    original_setting = bool(matplotlib.rcParams["path.simplify"])

    def fake_savefig(path: object, *, dpi: int) -> None:
        assert path == tmp_path / "plot.png"
        assert dpi == plotting.MAIN_DISPLAY_DPI
        observed.append(bool(matplotlib.rcParams["path.simplify"]))

    monkeypatch.setattr(figure, "savefig", fake_savefig)
    plotting._save_figure_without_path_simplification(  # noqa: SLF001
        figure,
        tmp_path / "plot.png",
        dpi=plotting.MAIN_DISPLAY_DPI,
    )

    assert observed == [False]
    assert bool(matplotlib.rcParams["path.simplify"]) is original_setting
