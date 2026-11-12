"""Reproduce synthetic derivative checks and optional read-only native GUI data audits.

Outputs are new files only. Real measurements have no independent acceleration
truth; reported peak changes describe estimator behavior, not physical accuracy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from dps_studio.core.physics.acceleration import differentiate_velocity, local_linear_acceleration


def metrics(time: Any, result: Any, truth: Any = None) -> dict[str, Any]:
    finite = np.isfinite(result)
    if not finite.any():
        return {"finite": 0}
    peak = int(np.nanargmax(np.abs(result)))
    data: dict[str, Any] = {"finite": int(finite.sum()), "peak_m_s2": float(result[peak]),
                            "peak_time_s": float(time[peak])}
    if truth is not None:
        mask = finite & np.isfinite(truth)
        data["rmse_m_s2"] = float(np.sqrt(np.mean((result[mask] - truth[mask])**2)))
        interior = mask & (time > time[0] + 160e-9) & (time < time[-1] - 160e-9)
        data["interior_rmse_m_s2"] = float(
            np.sqrt(np.mean((result[interior] - truth[interior])**2)))
    return data


def residual_audit(time: Any, velocity: Any, result: Any, window_s: float,
                   eligible: Any) -> dict[str, Any]:
    """Independent local design-matrix check; residuals are not uncertainty."""
    indices = np.flatnonzero(eligible)
    runs = np.split(indices, np.flatnonzero(np.diff(indices) != 1) + 1)
    residuals, counts, differences = [], [], []
    for run in runs:
        if not len(run):
            continue
        tolerance = 8*np.finfo(float).eps*max(float(np.max(np.abs(time[run]))), window_s)
        for index in run:
            if not np.isfinite(result[index]):
                continue
            selected = run[np.abs(time[run] - time[index]) <= window_s/2 + tolerance]
            x = (time[selected] - time[index])/window_s
            y = velocity[selected] - velocity[selected[0]]
            matrix = np.column_stack((np.ones(len(x)), x))
            coefficients = np.linalg.lstsq(matrix, y, rcond=None)[0]
            residuals.append(float(np.sqrt(np.mean((y - matrix @ coefficients)**2))))
            counts.append(len(selected))
            differences.append(float(abs(coefficients[1]/window_s - result[index])))
    return {"model": "v(t)=intercept+slope*(t-t_center); unweighted OLS",
            "residual_rms_m_s_median": float(np.median(residuals)) if residuals else None,
            "residual_rms_m_s_max": max(residuals, default=None),
            "sample_count_min": min(counts, default=None),
            "sample_count_max": max(counts, default=None),
            "independent_slope_max_difference_m_s2": max(differences, default=None),
            "uncertainty": "not estimated; overlapping frames correlated; residual RMS is not slope error"}


def synthetic(output: Path) -> dict[str, Any]:
    time = np.linspace(0, 2e-6, 1001)
    omega = 2*np.pi/1e-6
    z = (time - 1e-6)/20e-9
    fast = 100 + 50*np.tanh(z)
    fast_truth = 50/20e-9 / np.cosh(z)**2
    rng = np.random.default_rng(34)
    noisy = 100 + 2e8*time + rng.normal(0, 2, time.size)
    gap = noisy.copy()
    gap[480:520] = np.nan
    cases = {
        "constant": (np.full(time.shape, 100.), np.zeros(time.shape)),
        "constant_acceleration": (100 + 2e8*time, np.full(time.shape, 2e8)),
        "smooth": (100 + 50*np.sin(omega*time), 50*omega*np.cos(omega*time)),
        "rapid_20ns": (fast, fast_truth),
        "ideal_step_no_finite_derivative": (100 + 50*(time >= 1e-6), None),
        "noisy_linear": (noisy, np.full(time.shape, 2e8)),
        "noisy_gap": (gap, np.full(time.shape, 2e8)),
    }
    report = {}
    figure, axes = plt.subplots(len(cases), 2, figsize=(12, 16))
    for (name, (velocity, truth)), row in zip(cases.items(), axes, strict=True):
        raw = differentiate_velocity(time, velocity).acceleration_m_s2
        item = {"raw": metrics(time, raw, truth)}
        row[0].plot(time*1e6, velocity)
        row[0].set(title=name, ylabel="Speed (m/s)")
        row[1].plot(time*1e6, raw*1e-9, label="raw", alpha=.6)
        for ns in (20, 50, 100):
            fitted = local_linear_acceleration(time, velocity, window_s=ns*1e-9)
            item[str(ns) + "ns"] = metrics(time, fitted.acceleration_m_s2, truth)
            item[str(ns) + "ns"]["residuals"] = residual_audit(
                time, velocity, fitted.acceleration_m_s2, ns*1e-9, np.isfinite(velocity))
            row[1].plot(time*1e6, fitted.acceleration_m_s2*1e-9, label=f"{ns} ns")
        if truth is not None:
            row[1].plot(time*1e6, truth*1e-9, "k--", label="truth")
        row[1].set(ylabel="dv/dt (1e9 m/s²)")
        row[1].legend(fontsize=7)
        report[name] = item
    for axis in axes.flat:
        axis.set_xlabel("Time (µs)")
    figure.tight_layout()
    figure.savefig(output / "synthetic.png", dpi=140)
    plt.close(figure)
    return report


def real_data(source: Path, output: Path) -> dict[str, Any]:
    from PySide6.QtCore import QSettings
    from dps_studio.core.physics.window_presets import WindowPresetRepository
    from dps_studio.core.workflow.acceleration import channel_acceleration, acceleration_metadata
    from dps_studio.gui.app import create_application, translation_manager
    from dps_studio.gui.main_window import MainWindow
    from dps_studio.gui.release_workflow_smoke import _exercise, audit_derivative

    app = create_application([], language_code="zh_CN")
    window = MainWindow(translation_manager=translation_manager(),
                        settings=QSettings(str(output / "layout.ini"), QSettings.Format.IniFormat),
                        window_preset_repository=WindowPresetRepository(output / "presets.json"))
    window.resize(1366, 768)
    window.show()
    app.processEvents()
    try:
        workflow = _exercise(window, source, output)
        # Inspect the built-in correction, not the smoke test's custom coefficients.
        window.window_preset_editor.preset_combo.setCurrentIndex(0)
        channels = {}
        figure, axes = plt.subplots(len(window.analysis_session.channel_analyses), 2,
                                    figsize=(12, 7), squeeze=False)
        for (name, analysis), row in zip(window.analysis_session.channel_analyses.items(),
                                         axes, strict=True):
            time = analysis.stft_result.time_s
            velocity = analysis.plot_velocity_m_s
            raw = channel_acceleration(analysis).acceleration_m_s2
            item = {"raw": metrics(time, raw), "independent_difference": audit_derivative(analysis),
                    "provenance": acceleration_metadata(analysis), "fits": {}}
            relative = (time - time[0])*1e6
            row[0].plot(relative, velocity)
            row[0].set(title=name, ylabel="Speed (m/s)")
            row[1].plot(relative, raw*1e-9, label="raw", alpha=.6)
            for ns in (20, 50, 100):
                fit = channel_acceleration(analysis, window_s=ns*1e-9)
                entry = metrics(time, fit.acceleration_m_s2)
                eligible = np.array([flag != "invalid_or_masked" for flag in
                                     channel_acceleration(analysis).numerical_flags])
                entry["residuals"] = residual_audit(
                    time, velocity, fit.acceleration_m_s2, ns*1e-9, eligible)
                entry["flags"] = {flag: fit.numerical_flags.count(flag)
                                  for flag in set(fit.numerical_flags)}
                entry["raw_peak_ratio"] = abs(entry.get("peak_m_s2", 0)/item["raw"]["peak_m_s2"])
                item["fits"][str(ns)+"ns"] = entry
                row[1].plot(relative, fit.acceleration_m_s2*1e-9, label=f"{ns} ns")
            peak = int(np.nanargmax(np.abs(raw)))
            indices = np.arange(max(0, peak-3), min(time.size, peak+4))
            item["peak_neighborhood"] = {
                "indices": indices.tolist(), "time_s": time[indices].tolist(),
                "dt_s": np.diff(time[indices]).tolist(), "velocity_m_s": velocity[indices].tolist(),
                "raw_acceleration_m_s2": raw[indices].tolist(),
                "states": [analysis.signal_detection_result.signal_states[i].value for i in indices],
            }
            item["signal_states"] = {state.value: analysis.signal_detection_result.signal_states.count(state)
                                     for state in set(analysis.signal_detection_result.signal_states)}
            channels[name] = item
            row[1].set(ylabel="dv/dt (1e9 m/s²)")
            row[1].legend()
        for axis in axes.flat:
            axis.set_xlabel("Time from first frame (µs)")
        figure.tight_layout()
        figure.savefig(output / "comparison.png", dpi=140)
        plt.close(figure)
        return {"source": source.name, "workflow": workflow, "channels": channels,
                "independent_physical_acceleration_truth": False}
    finally:
        window.close()
        app.processEvents()


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    result = real_data(args.input, args.output) if args.input else synthetic(args.output)
    with (args.output / "validation.json").open("x", encoding="utf-8") as handle:
        json.dump(clean(result), handle, ensure_ascii=False, indent=2, allow_nan=False)


if __name__ == "__main__":
    main()
