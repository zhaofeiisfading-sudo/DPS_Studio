"""Generate presentation-only figures from the current DPS Studio data and outputs."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np


TASK_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = TASK_DIR.parents[2]
ASSET_DIR = TASK_DIR / "assets" / "project_outputs"
RAW_DATA_PATH = REPOSITORY_ROOT / "data" / "raw" / "20260607.csv"
EVENT_START_TIME_S = 5.54668e-4


def _configure_matplotlib() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Microsoft YaHei", "DengXian", "Arial"],
            "axes.unicode_minus": False,
            "font.size": 15,
            "axes.titlesize": 21,
            "axes.labelsize": 17,
            "xtick.labelsize": 14,
            "ytick.labelsize": 14,
            "legend.fontsize": 14,
        }
    )


def _load_raw_records() -> dict[str, object]:
    sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
    from dps_studio.core.io import read_delimited_signals

    result = read_delimited_signals(
        RAW_DATA_PATH,
        time_column=0,
        voltage_columns={"pdv_channel_1": 1, "pdv_channel_2": 2},
        delimiter=",",
        has_header=False,
        encoding="utf-8",
        time_scale=1.0,
        voltage_scales={"pdv_channel_1": 1.0, "pdv_channel_2": 1.0},
    )
    return dict(result.records)


def _save_raw_voltage_figure() -> None:
    records = _load_raw_records()
    start_s = EVENT_START_TIME_S - 0.12e-6
    end_s = EVENT_START_TIME_S + 0.28e-6

    figure, axes = plt.subplots(2, 1, figsize=(12.8, 7.2), sharex=True)
    colors = ("#B52A12", "#167D8D")
    labels = ("PDV 通道 1（原始电压）", "PDV 通道 2（原始电压）")

    for axis, (channel_name, record), color, label in zip(
        axes,
        records.items(),
        colors,
        labels,
        strict=True,
    ):
        time_s = np.asarray(record.time_s)
        voltage_v = np.asarray(record.voltage_v)
        mask = (time_s >= start_s) & (time_s <= end_s)
        axis.plot(
            (time_s[mask] - EVENT_START_TIME_S) * 1e6,
            voltage_v[mask],
            color=color,
            linewidth=0.75,
            label=label,
        )
        axis.axvline(0.0, color="#D18A00", linewidth=1.2, linestyle="--")
        axis.set_ylabel("电压 (V)")
        axis.grid(alpha=0.2)
        axis.legend(loc="upper right", frameon=False)

    axes[0].set_title("同一原始文件中的两个采集通道：保持独立，不做电压平均")
    axes[-1].set_xlabel("相对事件起点时间 (µs)")
    figure.text(
        0.01,
        0.01,
        "来源：data/raw/20260607.csv；仅截取显示窗口，未平滑、未插值、未重采样。",
        fontsize=12,
        color="#555555",
    )
    figure.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    figure.savefig(ASSET_DIR / "raw_voltage_event.png", dpi=220)
    plt.close(figure)


def _read_quality_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _save_quality_summary_figure() -> None:
    balanced_rows = _read_quality_rows(ASSET_DIR / "balanced_quality_summary.csv")
    high_rows = _read_quality_rows(ASSET_DIR / "high_time_quality_summary.csv")
    rows = balanced_rows + high_rows
    group_labels = ["Balanced\n通道 1", "Balanced\n通道 2", "High time\n通道 1", "High time\n通道 2"]
    peak_background = [
        float(row["peak_to_background_db_median"])
        for row in rows
    ]
    peak_competitor = [
        float(row["peak_to_competitor_db_median"])
        for row in rows
    ]

    x_positions = np.arange(len(group_labels), dtype=np.float64)
    width = 0.34
    figure, axis = plt.subplots(figsize=(12.8, 7.2))
    bars_background = axis.bar(
        x_positions - width / 2,
        peak_background,
        width,
        color="#B52A12",
        label="峰—背景幅值对比度中位数",
    )
    bars_competitor = axis.bar(
        x_positions + width / 2,
        peak_competitor,
        width,
        color="#167D8D",
        label="峰—竞争峰幅值对比度中位数",
    )
    axis.bar_label(bars_background, fmt="%.1f", padding=3, fontsize=13)
    axis.bar_label(bars_competitor, fmt="%.1f", padding=3, fontsize=13)
    axis.set_xticks(x_positions, group_labels)
    axis.set_ylabel("幅值对比度 (dB)")
    axis.set_ylim(0.0, 65.0)
    axis.grid(axis="y", alpha=0.2)
    axis.legend(loc="upper right", frameon=False)
    axis.set_title("最近一次真实运行的描述性谱质量统计（不是正式 SNR）")
    figure.text(
        0.01,
        0.01,
        "来源：run_20260724_004901_103968；数值只描述当前数据，不自动决定可信通道或物理分支。",
        fontsize=12,
        color="#555555",
    )
    figure.tight_layout(rect=(0.0, 0.04, 1.0, 1.0))
    figure.savefig(ASSET_DIR / "quality_diagnostics_summary.png", dpi=220)
    plt.close(figure)


def main() -> None:
    _configure_matplotlib()
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    _save_raw_voltage_figure()
    _save_quality_summary_figure()


if __name__ == "__main__":
    main()
