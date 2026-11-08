"""Publication supplements from local frozen evidence and unchanged raw voltage."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager
from matplotlib.colors import Normalize

from dps_studio.algorithms.waveform.catalog import METHODS
from dps_studio.research.waveform.data import FAMILIES
from scripts.research.task009.prepare_figures import (
    ALIASES, COLORS, ROOT, T8, T9, number, source, table, trajectory,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.time_frequency import compute_stft


def style() -> None:
    for filename in ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"):
        font_manager.fontManager.addfont(str(Path("C:/Windows/Fonts") / filename))
    plt.rcParams.update({"font.family": "Times New Roman", "font.size": 9,
        "axes.labelsize": 10, "legend.fontsize": 8.5, "axes.linewidth": 0.8,
        "xtick.direction": "in", "ytick.direction": "in", "xtick.top": True,
        "ytick.right": True, "pdf.fonttype": 42, "ps.fonttype": 42,
        "svg.fonttype": "none", "savefig.dpi": 600, "axes.unicode_minus": True})


def finish(fig: Any, folder: Path, caption: str, sources: list[Path], metadata: dict[str, Any]) -> None:
    name = folder.name
    for ext in ("pdf", "svg", "png"):
        fig.savefig(folder / f"{name}.{ext}", facecolor="white")
    for ax in fig.axes:
        for spine in ax.spines.values():
            spine.set_visible(True)
    plt.close(fig)
    (folder / "caption_zh.md").write_text(caption + "\n", encoding="utf-8")
    (folder / "figure.json").write_text(json.dumps(dict(id=name, backend="Matplotlib",
        caption_zh=caption, sources=[source(p) for p in dict.fromkeys(sources)], **metadata),
        ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")


def heatmap(destination: Path, *, real: bool) -> None:
    identifier = "SFig02_RealCoverage" if real else "SFig01_FamilyFailure"
    folder = destination / identifier
    folder.mkdir()
    if real:
        rows = table("all_real_metrics.csv")
        columns = list(dict.fromkeys(r["case_id"] for r in rows))
        values = np.array([[number(next(r for r in rows if r["method"] == m and r["case_id"] == c),
                                   "accepted_coverage") for c in columns] for m in METHODS])
        labels = [f"R{i:02d}" for i in range(1, 18)]
        groups = [slice(0, 9), slice(9, 17)]
        mapping = [next(r for r in rows if r["case_id"] == c) for c in columns]
        with (folder / "stream_mapping.csv").open("x", newline="", encoding="utf-8-sig") as h:
            keys = ["display_id", "case_id", "raw_path", "raw_sha256", "voltage_column", "samples", "sample_rate_hz"]
            w = csv.DictWriter(h, fieldnames=keys)
            w.writeheader()
            w.writerows(dict(display_id=label, **{k: row[k] for k in keys[1:]}) for label, row in zip(labels, mapping, strict=True))
        metric = "Supported coverage (%)"
        caption = "全部13个原始实验文件、17个电压流及14种方法的支持覆盖率。R01–R17到原始路径、SHA、采样率和电压列的映射见stream_mapping.csv，处理过的result文件和图片均排除。数值为有效支持帧/该记录全部输出帧，分母随记录长度与采样率变化；整数标签仅用于显示，CSV保留完整精度。支持率不是准确率，真实界面身份和速度均无Ground Truth，不能按颜色宣称真实速度已被证明。"
        sources = [T8 / "tables/all_real_metrics.csv"]
    else:
        rows = table("fresh_summary.csv")
        columns = list(FAMILIES)
        values = np.array([[number(next(r for r in rows if r["method"] == m and r["family"] == c
                                         and r["channel"] == "accepted" and r["region"] == "motion"),
                                   "failure_fraction") for c in columns] for m in METHODS])
        labels = ["Step", "Low ramp", "Fast accel.", "Fast decel.", "Two shock", "Weak chirp",
                  "Dropout", "Stationary spur", "Two component", "Phase jump", "Colored noise", "Noise only"]
        groups = [slice(0, 6), slice(6, 12)]
        metric = "Failure incl. missing (%)"
        caption = "冻结独立合成测试的12类运动/信号场景，每类8条，全部14种方法。颜色与数字为支持后含缺失失败百分比，阈值为100 MHz（按1550 nm等效77.5 m/s），每族按原目标帧分母汇总；无运动真值的纯噪声显示NA，不用零代替。缺失计入失败，有限点误差与覆盖须结合Fig01及原表判断。色图为cividis；显示整数百分比，来源CSV保持全精度。该矩阵保留弱信号、相位跳变、多分量等负结果。"
        sources = [T8 / "tables/fresh_summary.csv"]
    with (folder / "matrix.csv").open("x", newline="", encoding="utf-8") as h:
        writer = csv.writer(h)
        writer.writerow(["method", *columns])
        writer.writerows([m, *[float(v) if np.isfinite(v) else "" for v in row]] for m, row in zip(METHODS, values, strict=True))
    fig, axes = plt.subplots(2, 1, figsize=(180 / 25.4, 205 / 25.4))
    fig.subplots_adjust(left=0.22, right=0.88, bottom=0.07, top=0.93, hspace=0.35)
    cmap = plt.get_cmap("cividis").copy()
    cmap.set_bad("#e0e0e0")
    for i, (ax, group) in enumerate(zip(axes, groups, strict=True)):
        data = values[:, group]
        ax.pcolormesh(np.ma.masked_invalid(data), cmap=cmap, vmin=0, vmax=1,
                      shading="flat", rasterized=False)
        ax.set_xlim(0, data.shape[1])
        ax.set_ylim(14, 0)
        ax.set_xticks(np.arange(data.shape[1]) + 0.5, labels[group], rotation=25, ha="right")
        ax.set_yticks(np.arange(14) + 0.5, [ALIASES[m] for m in METHODS])
        ax.tick_params(length=2, top=True, right=True)
        for row in range(14):
            for col in range(data.shape[1]):
                value = data[row, col]
                ax.text(col + 0.5, row + 0.5, f"{100 * value:.0f}" if np.isfinite(value) else "NA",
                        ha="center", va="center", fontsize=8,
                        color="white" if np.isfinite(value) and value < 0.55 else "black")
        ax.text(-0.17, 1.04, f"({chr(97 + i)})", transform=ax.transAxes, fontweight="bold", fontsize=11)
    color_ax = fig.add_axes((0.91, 0.22, 0.025, 0.58))
    cb = fig.colorbar(plt.cm.ScalarMappable(norm=Normalize(0, 100), cmap=cmap), cax=color_ax)
    cb.set_label(metric)
    cb.ax.tick_params(direction="in")
    finish(fig, folder, caption, sources, dict(matrix_shape=list(values.shape), all_methods=list(METHODS),
            missing_representation="NA; not zero", editable_vector_cells=True))


def spectra(destination: Path) -> None:
    folder = destination / "SFig03_RealSpectra"
    folder.mkdir()
    fig, axes = plt.subplots(2, 1, figsize=(180 / 25.4, 145 / 25.4))
    fig.subplots_adjust(left=0.11, right=0.86, top=0.92, bottom=0.09, hspace=0.4)
    index = json.loads((T9 / "data_index.json").read_text(encoding="utf-8"))["records"]
    rows = table("all_real_metrics.csv")
    sources = [T9 / "data_index.json"]
    metadata = []
    for i, (case, ax) in enumerate(zip(["raw00_20260607_ch1", "raw06_ch3_ch1"], axes, strict=True)):
        row = next(r for r in rows if r["case_id"] == case)
        entry = next(r for r in index if r["path"] == row["raw_path"])
        path = ROOT / entry["local_path"]
        sources.append(path)
        matrix = np.loadtxt(path, delimiter=",")
        t, voltage = matrix[:, 0], matrix[:, int(row["voltage_column"])]
        stft = compute_stft(SignalRecord(t, voltage), window_length_samples=512,
            overlap_samples=384, nfft=4096, window_name="hann")
        freq = np.asarray(stft.frequency_hz)
        keep = freq <= 8e9
        power = abs(stft.spectrum[keep]) ** 2
        db = 10 * np.log10(np.maximum(power, 1e-300) / np.max(power))
        tx = (stft.time_s - t[0]) * 1e6
        image = ax.pcolormesh(tx, freq[keep] / 1e9, db, shading="nearest", cmap="cividis",
                              vmin=-60, vmax=0, rasterized=True)
        with (folder / f"{case}_spectrum.npz").open("xb") as h:
            np.savez_compressed(h, time_from_first_sample_us=tx, frequency_ghz=freq[keep] / 1e9,
                                relative_power_db=db, absolute_first_sample_s=t[0])
        for method in ["legacy_m0_768", "varpro", "clutter_varpro"]:
            path, data = trajectory(method, "real", case)
            sources.append(path)
            ax.plot((data["time_s"] - t[0]) * 1e6, data["accepted_hz"] / 1e9,
                    color=COLORS[method], lw=0.85, label=ALIASES[method])
        ax.set_xlim(0, (t[-1] - t[0]) * 1e6)
        ax.set_ylim(0, 8)
        ax.set_xlabel("Time from first sample (µs)")
        ax.set_ylabel("Beat frequency (GHz)")
        ax.text(-0.09, 1.06, f"({chr(97 + i)})", transform=ax.transAxes, fontweight="bold", fontsize=11)
        ax.set_title(case, loc="left", fontsize=9, pad=7)
        if i == 0:
            ax.legend(loc="lower right", bbox_to_anchor=(1, 1.02), frameon=False, ncol=3, fontsize=8)
        color_ax = fig.add_axes((0.89, 0.575 if i == 0 else 0.1, 0.02, 0.32))
        cb = fig.colorbar(image, cax=color_ax)
        cb.set_label("Relative spectral power (dB)")
        metadata.append(dict(case=case, raw_sha256=entry["sha256"],
                             voltage_column=int(row["voltage_column"]), spectrum_shape=list(db.shape)))
    caption = "真实原电压的观测证据：20260607第一电压列与ch3坏信号记录。仅为可视化重算原512点Hann、128点hop、4096点FFT的无去趋势STFT；没有重采样、滤波或改写原电压，谱功率分别相对该记录最大值归一化，色条不是SNR，不能跨记录比较绝对强度。叠加冻结质量支持频率假设，缺失保留；坏记录上若出现候选或支路，不能凭拟合或平滑认证物理速度。色块在矢量容器内为600 dpi栅格，轴、文字和轨迹为矢量；完整谱矩阵保存为NPZ。"
    finish(fig, folder, caption, sources, dict(records=metadata, window_samples=512, hop_samples=128,
        nfft=4096, window="hann", detrend=False, resampling=False,
        normalization="per-record maximum spectral power; not SNR", mixed_vector_raster=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(T9):
        parser.error("Output must be within TASK-009")
    output.mkdir(parents=True, exist_ok=False)
    style()
    heatmap(output, real=False)
    heatmap(output, real=True)
    spectra(output)
    print(f"Three supplements exported: {output}")


if __name__ == "__main__":
    main()
