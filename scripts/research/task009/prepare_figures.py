"""Derive figure source tables from frozen TASK-008 evidence, without refitting.

Run with the repository root and src on PYTHONPATH. Every destination is new.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from dps_studio.algorithms.waveform.catalog import METHODS, run_folder

ROOT = Path(__file__).resolve().parents[3]
T8 = ROOT / "artifacts/TASK-008"
T9 = Path(__file__).resolve().parents[3] / "artifacts/TASK-009"
VELOCITY = 1.55e-6 / 2
ALIASES = dict(zip(METHODS, (
    "Strict-512", "Strict-768", "Wide-512", "Gated-256", "Gated-512",
    "Dechirp", "VarPro", "Coherent-VP", "ACMD", "Pencil", "Time-domain",
    "Baseband", "M0-512", "M0-768"), strict=True))
COLORS = {"truth": "#111111", "legacy_m0_768": "#0072B2", "gated_stft512": "#777777",
          "dechirp": "#E69F00", "varpro": "#009E73", "clutter_varpro": "#D55E00",
          "time_domain": "#56B4E9", "matrix_pencil": "#CC79A7"}


def table(name: str) -> list[dict[str, str]]:
    with (T8 / "tables" / name).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def number(row: dict[str, str], key: str) -> float:
    return float(row[key]) if row.get(key) else float("nan")


def packed(values: Any) -> list[float | None]:
    return [float(v) if np.isfinite(v) else None for v in np.asarray(values).ravel()]


def series(x: Any, y: Any, label: str = "", method: str = "", **kwargs: Any) -> dict[str, Any]:
    return dict(x=packed(x), y=packed(y), label=label, color=COLORS.get(method, "#666666"),
                kind="line", width=1.4, **kwargs)


def panel(rect: list[float], xlabel: str, ylabel: str, **kwargs: Any) -> dict[str, Any]:
    return dict(rect=rect, xlabel=xlabel, ylabel=ylabel, series=[], **kwargs)


def source(path: Path) -> dict[str, str]:
    with path.open("rb") as handle:
        sha = hashlib.file_digest(handle, "sha256").hexdigest()
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=sha)


def trajectory(method: str, stage: str, case: str) -> tuple[Path, dict[str, np.ndarray]]:
    path = run_folder(T8, method, stage, case) / "trajectory.npz"
    with np.load(path) as data:
        return path, {k: np.array(data[k]) for k in data.files}


def make_trajectory_figure(identifier: str, case: str, methods: list[str], caption: str,
                           zoom: list[float], ylim: list[float], stage: str = "fresh",
                           zoom_ylim: list[float] | None = None) -> dict[str, Any]:
    raw = T8 / f"datasets/{stage}/{case}.npz"
    with np.load(raw) as data:
        tx = np.array(data["time_s"]) * 1e9
        vy = np.array(data["truth_hz"]) * VELOCITY
    panels = [panel([11, 13, 36, 68], "Time (ns)", "Velocity (m/s)", xlim=[0, 320], ylim=ylim),
              panel([62, 13, 34, 68], "Time (ns)", "Velocity (m/s)", xlim=zoom, ylim=zoom_ylim or ylim)]
    paths = [raw]
    for p in panels:
        p["legend_position"] = [55, 60]
        p["series"].append(series(tx, vy, "Ground truth", "truth", dash=1))
    panels[1]["show_legend"] = False
    if "Clutter" in identifier:
        panels[0]["legend_position"] = [50, 78]
    for method in methods:
        path, data = trajectory(method, stage, case)
        paths.append(path)
        for p in panels:
            p["series"].append(series(data["time_s"] * 1e9,
                                      data["accepted_hz"] * VELOCITY, ALIASES[method], method,
                                      symbols=True))
    return dict(id=identifier, width_mm=180, height_mm=90, panels=panels,
                source_paths=paths, selection=f"Preselected family member {case}; no error-based selection",
                caption_zh=caption)


def build() -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    summary = table("fresh_summary.csv")
    all_fresh = table("all_fresh_metrics.csv")
    all_stress = table("all_phase_stress_metrics.csv")
    real = table("all_real_metrics.csv")
    pooled = {r["method"]: r for r in summary
              if r["family"] == "ALL" and r["region"] == "motion" and r["channel"] == "accepted"}
    labels = [ALIASES[m] for m in METHODS[::-1]]
    panels = []
    for index, (key, title, limits, log) in enumerate([
        ("failure_fraction", "Failure (%)", [0, 55], False),
        ("finite_rmse_m_s", "RMSE (m/s)", [0.7, 500], True),
        ("coverage", "Coverage (%)", [0, 100], False),
    ]):
        p = panel([27 + index * 24, 11, 19, 77], title, "", xlim=limits,
                  ylim=[0.5, 14.5], yticklabels=labels if index == 0 else [], xlog=log)
        for y, method in enumerate(METHODS[::-1], 1):
            value = number(pooled[method], key) * (100 if key != "finite_rmse_m_s" else 1)
            p["series"].append(series([value], [y], "", method, kind_override="scatter"))
        panels.append(p)
    figures.append(dict(id="Fig01_GlobalPerformance", width_mm=180, height_mm=145, panels=panels,
        source_paths=[T8 / "tables/fresh_summary.csv"], selection="All 14 methods; no ranking-based exclusion",
        caption_zh="冻结独立合成测试含96条波形，其中88条有运动真值，8条纯噪声不进入运动误差分母。三面板均保留14种方法；运动目标共6952帧。失败=(缺失或绝对频率误差>100 MHz)/6952，约对应77.5 m/s阈值；RMSE仅对支持后的有限点计算，覆盖率同时给出，不能单独按RMSE排序。Coherent-VP为静止杂散预测加VarPro，M0为保留离散回退的完整历史最强峰基准；Strict为严格细化分支。帧有相关性，本图不把帧当独立统计重复。"))
    paired = table("fresh_paired_bootstrap.csv")
    names = ["gated_stft256", "dechirp", "varpro", "clutter_varpro", "acmd", "matrix_pencil", "time_domain", "baseband"]
    panels = []
    for index, reference in enumerate(["legacy_m0_768", "gated_stft512"]):
        p = panel([24 + index * 42, 15, 30, 70], "Failure difference (pp)", "",
                  ylim=[0.5, 8.5], xlim=[-25, 55], yticklabels=[ALIASES[m] for m in names[::-1]] if index == 0 else [],
                  heading="Reference: " + ALIASES[reference])
        p["xlabel"] = "Difference vs " + ALIASES[reference] + " (pp)"
        p["series"].append(series([0, 0], [0.5, 8.5], method="truth", dash=1, width_override=0.8))
        for y, method in enumerate(names[::-1], 1):
            r = next(r for r in paired if r["method"] == method and r["reference"] == reference and r["channel"] == "accepted")
            lo, hi = (100 * number(r, "failure_macro_delta_ci_" + suffix) for suffix in ("low", "high"))
            p["series"].extend([series([lo, hi], [y, y], method=method),
                series([100 * number(r, "failure_macro_delta")], [y], method=method, kind_override="scatter")])
        panels.append(p)
    figures.append(dict(id="Fig02_PairedEffect", width_mm=180, height_mm=115, panels=panels,
        source_paths=[T8 / "tables/fresh_paired_bootstrap.csv"], selection="Seven model routes plus the Gated-256 truncation control",
        caption_zh="88条独立运动波形的逐波形宏平均失败差及原有配对bootstrap 95%区间，负值有利于被比较方法；缺失保持在失败分母。参考分别为完整M0-768及Gated-512。Coherent-VP对完整M0的差为−4.93个百分点，区间[−11.51,1.68]跨零，现有测试不足以支持普遍改善；相对Gated-512为−9.09个百分点，区间[−15.85,−3.47]。不同于Fig01的帧汇总；不重新采样相关帧，也不作多重比较后显著性声明。"))
    stress = table("phase_stress_by_velocity.csv")
    picks = ["legacy_m0_768", "gated_stft512", "varpro", "time_domain", "matrix_pencil"]
    panels = [panel([11, 13, 36, 67], "Specified velocity (m/s)", "Failure incl. missing (%)", xlim=[10, 210], ylim=[0, 105]),
              panel([62, 13, 34, 67], "Specified velocity (m/s)", "Candidate RMSE (m/s)", xlim=[10, 210], ylim=[0.5, 5000], ylog=True)]
    panels[1]["show_legend"] = False
    for method in picks:
        rows = sorted((r for r in stress if r["method"] == method), key=lambda r: number(r, "specified_velocity_m_s"))
        x = [number(r, "specified_velocity_m_s") for r in rows]
        for p, key, factor in zip(panels, ["accepted_failure_fraction", "finite_rmse_m_s"], [100, 1], strict=True):
            p["series"].append(series(x, [factor * number(r, key) for r in rows], ALIASES[method], method, symbols=True))
    for p in panels:
        p["legend_position"] = [45, 5]
    figures.append(dict(id="Fig03_LowVelocity", width_mm=180, height_mm=100, panels=panels,
        source_paths=[T8 / "tables/phase_stress_by_velocity.csv"], selection="Five predeclared velocities, ten phase realizations each",
        caption_zh="低速初相压力测试：15、30、50、100、200 m/s各10条，左为支持后含缺失失败，右为候选有限点RMSE（对数轴）。每速度运动目标790帧，不把有限点误差代替全分母。15 m/s时VarPro与Pencil候选RMSE约641.9与3523.3 m/s；时域方法在15与30 m/s约333.3与559.6 m/s，优化成功不代表物理解正确。完整M0的候选覆盖在15/30 m/s为100%，不能用严格细化基准的缺失夸大改进。100 MHz统一容差相对15 m/s过宽，低失败率不代表低相对误差，应结合右图及原表50/200 MHz敏感性列。右图为候选而非左图的支持后集合；两面板配色对应左侧图例，全14方法在来源表中保留。"))
    onset = table("onset_and_false_outputs.csv")
    p1 = panel([11, 15, 39, 65], "Absolute onset error (ns)", "Conditional detected fraction", xlim=[0, 50], ylim=[0, 1.03])
    p1["legend_position"] = [45, 60]
    p2 = panel([70, 15, 25, 65], "Missed events / 88 (%)", "", xlim=[0, 20], ylim=[0.5, 3.5],
               yticklabels=["M0-768", "Coherent-VP", "Shared-gate"])
    selected = ["gated_stft512", "clutter_varpro", "legacy_m0_768"]
    maxerr = 0.0
    for i, method in enumerate(selected):
        e = sorted(abs(number(r, "onset_error_ns")) for r in all_fresh
                   if r["method"] == method and r.get("truth_onset_s") and np.isfinite(number(r, "onset_error_ns")))
        maxerr = max(maxerr, max(e))
        ecdf_x = np.repeat(e, 2)
        ecdf_y = np.column_stack((np.arange(len(e)) / len(e), (np.arange(len(e)) + 1) / len(e))).ravel()
        label = ("Shared-gate" if i == 0 else ALIASES[method]) + f" ({len(e)}/88)"
        p1["series"].append(series(ecdf_x, ecdf_y, label, method))
        r = next(r for r in onset if r["method"] == method)
        p2["series"].append(series([number(r, "missed_n") / 88 * 100], [3 - i], method=method, kind_override="scatter"))
    p1["xlim"][1] = float(np.ceil(maxerr / 5) * 5)
    figures.append(dict(id="Fig04_Onset", width_mm=180, height_mm=100, panels=[p1, p2],
        source_paths=[T8 / "tables/all_fresh_metrics.csv", T8 / "tables/onset_and_false_outputs.csv"],
        selection="All 88 truth events; ECDF conditional on detected events; no tail truncation",
        caption_zh="起跳绝对误差的条件经验分布与漏检率分开呈现，全部88个运动事件均进入漏检分母。共享原电压检测器检出75/88，Coherent-VP为83/88，M0-768为80/88；条件误差曲线未包含漏检事件，也不代表亚采样测量精度。共享检测器对应多种方法，不能当作独立重复。8条纯噪声的事件误报另见原表，不能混入88条运动事件；显示全部误差尾部。"))
    figures.append(make_trajectory_figure("Fig05_Acceleration", "fresh_fast_accel_00",
        ["gated_stft512", "dechirp", "varpro"],
        "固定fast_accel第0条波形：支持后等效速度，全时间跨度与起跳附近放大；黑线为原采样物理合成真值，所有有限估计点及NaN间断保留。局部Chirp模型在连续强加速可降低偏差，不能外推至阶跃或弱信号场景。本族8条的支持后RMSE：Dechirp 3.36、VarPro 3.53、Gated-512 11.95 m/s；本图单条曲线不是统计重复。连线仅引导视线，不提高3.2 ns输出网格分辨率。", [56, 72], [-60, 1950], zoom_ylim=[-20, 650]))
    figures.append(make_trajectory_figure("Fig06_Clutter", "fresh_stationary_spur_00",
        ["legacy_m0_768", "clutter_varpro"],
        "固定stationary_spur第0条：静止杂散相位预测加VarPro与完整M0-768对照，全时程与起跳放大。该族8条的Coherent-VP支持后RMSE约1.36 m/s、覆盖约99.8%；收益依赖预事件杂散相位可预测，不能据此认证真实界面身份。原共享门控在该族无法给出有效事件，缺失作为负结果保留，未绘制替代平滑曲线。", [54, 85], [-50, 1150], zoom_ylim=[260, 430]))
    figures.append(make_trajectory_figure("Fig07_DoubleShockFailure", "fresh_two_shock_00",
        ["gated_stft512", "varpro", "time_domain"],
        "固定two_shock第0条负结果：全时程与第二次冲击附近放大，理想真值阶跃保留原25 ps采样，输出网格未插值。复杂平滑相位模型在突变附近可能偏离，而Gated-512本族支持后RMSE约1.00 m/s，小于VarPro 6.67和时域8.46 m/s。不能用平滑外观评价真实性；局部连线不代表在两个估计时刻之间已测得轨迹。", [99, 112], [-50, 1650], zoom_ylim=[150, 1250]))
    fifteen = [r for r in all_stress if r["method"] == "varpro"
               and int(r["case_id"].rsplit("_", 1)[1]) % 5 == 0]
    worst = max(fifteen, key=lambda r: number(r, "candidate_motion_rmse_m_s"))
    case = worst["case_id"]
    paths = []
    p1 = panel([11, 14, 37, 65], "Time (ns)", "Candidate velocity (m/s)", xlim=[0, 320], ylim=[1, 100000], ylog=True)
    p1["legend_position"] = [45, 5]
    p2 = panel([62, 14, 34, 65], "Time (ns)", "Native fit R2", xlim=[0, 320], ylim=[0, 1.05])
    for method in ["legacy_m0_768", "varpro", "time_domain"]:
        path, data = trajectory(method, "phase_stress", case)
        paths.append(path)
        p1["series"].append(series(data["time_s"] * 1e9, data["frequency_hz"] * VELOCITY, ALIASES[method], method, symbols=True))
        if method == "varpro":
            key = "native_model_r2"
            p2["series"].append(series(data["time_s"] * 1e9, data[key], "VarPro native fit", method, symbols=True))
    raw = T8 / f"datasets/phase_stress/{case}.npz"
    with np.load(raw) as data:
        p1["series"].append(series(data["time_s"] * 1e9, data["truth_hz"] * VELOCITY, "Ground truth", "truth", dash=1))
    paths.append(raw)
    figures.append(dict(id="Fig08_SubcycleFailure", width_mm=180, height_mm=100, panels=[p1, p2],
        source_paths=paths + [T8 / "tables/all_phase_stress_metrics.csv"],
        selection=f"POST HOC DIAGNOSTIC: worst VarPro candidate motion RMSE among 10 at 15 m/s: {case}",
        caption_zh=f"事后选择的诊断反例{case}：在15 m/s的10条中按VarPro候选运动RMSE最大选出，不能用作算法排名。左图显示候选速度，预事件零速未参与运动评分，档案真值标为NaN，缺失不填补；右图为同一候选原生模型拟合R²。高拟合或收敛均不能排除不足周期条件下的错误频率解。支持门控可能拒绝候选，左图不能视为可信输出；总体失败见Fig03。"))
    cases = ["raw00_20260607_ch1", "raw11_20231019-ch1_ch1"]
    panels = []
    paths = [T8 / "tables/all_real_metrics.csv"]
    for index, case in enumerate(cases):
        row = next(r for r in real if r["case_id"] == case)
        p = panel([11 + index * 51, 15, 35, 65], "Time from first sample (µs)", "Equivalent velocity (m/s)",
                  heading=f"{case.split('_', 1)[1]} ({float(row['sample_rate_hz']) / 1e9:.0f} GS/s)")
        local = json.loads((T9 / "data_index.json").read_text(encoding="utf-8"))["records"]
        match = next(r for r in local if r["path"] == row["raw_path"])
        matrix = np.loadtxt(ROOT / match["local_path"], delimiter=",")
        paths.append(ROOT / match["local_path"])
        t0 = matrix[0, 0]
        p["xlim"] = [0, float((matrix[-1, 0] - t0) * 1e6)]
        p["ylim"] = [-100, 6500]
        for method in ["legacy_m0_768", "varpro", "clutter_varpro"]:
            path, data = trajectory(method, "real", case)
            paths.append(path)
            p["series"].append(series((data["time_s"] - t0) * 1e6, data["accepted_hz"] * VELOCITY,
                                      ALIASES[method], method))
        panels.append(p)
    figures.append(dict(id="Fig09_RealPDV", width_mm=180, height_mm=105, panels=panels,
        source_paths=paths, selection="Two fixed records: first 20260607 voltage stream and 80 GS/s 20231019 DAT",
        caption_zh="两条真实PDV记录的质量支持后等效速度假设，分别为20260607第一电压列与20231019-ch1 DAT（40与80 GS/s）。使用假定真空波长1550 nm的v=λf/2；未进行LiF或其他校正，真实速度Ground Truth不可得。起始时间仅作明确显示平移，算法使用原时间；全跨度显示、缺失保留，支路身份和绝对速度均未经认证。拟合好、支持率高或曲线平滑不能证明真实速度。全部13原始文件17流见SFig02，谱证据及坏记录见SFig03。"))
    runtime = {r["method"]: r for r in table("real_runtime.csv") if r["samples"] == "80000"}
    p = panel([28, 12, 66, 76], "Recorded wall time per 80k stream (s)", "", xlog=True,
              xlim=[0.1, 10], ylim=[0.5, 14.5], yticklabels=labels)
    p["series"].append(series([3, 3], [0.5, 14.5], method="truth", dash=1, width_override=0.8))
    for y, method in enumerate(METHODS[::-1], 1):
        r = runtime[method]
        p["series"].extend([series([number(r, "median_total_s"), number(r, "p95_total_s")], [y, y], method=method),
            series([number(r, "median_total_s")], [y], method=method, kind_override="scatter")])
    figures.append(dict(id="Fig10_Cost", width_mm=180, height_mm=145, panels=[p],
        source_paths=[T8 / "tables/real_runtime.csv"], selection="All 14 methods; 12 frozen 80k-stream timings",
        caption_zh="原冻结运行的12条80k采样真实流：圆点为总耗时中位数，横线从中位数延伸至P95，非置信区间；竖线为3 s参考。总耗时含公共上下文、估计及质量检查，未含导出，完整M0还保留Top20等历史合同开销。本次复用既有实测，未把迁移重放或新绘图机器上的耗时冒充统一新benchmark。全部算法使用同一原始数据集，运行成本不能直接证明精度。"))
    return figures


def save(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    figures = build()
    for fig in figures:
        folder = destination / fig["id"]
        folder.mkdir()
        fig["sources"] = [source(path) for path in dict.fromkeys(fig.pop("source_paths"))]
        for pi, p in enumerate(fig["panels"], 1):
            for si, s in enumerate(p["series"], 1):
                s["kind"] = s.pop("kind_override", s["kind"])
                s["width"] = s.pop("width_override", s["width"])
                filename = f"panel{pi:02d}_series{si:02d}.csv"
                with (folder / filename).open("x", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["x_display_units", "y_display_units"])
                    writer.writerows(zip(s["x"], s["y"], strict=True))
                s["data_csv"] = filename
        fig["rendering"] = dict(backend="Origin 2021 native COM", preserve_all_points=True,
                                nan_handling="split finite segments; never bridge gaps",
                                statistical_source="frozen TASK-008; no refit or reranking")
        with (folder / "figure.json").open("x", encoding="utf-8") as handle:
            json.dump(fig, handle, ensure_ascii=False, allow_nan=False, indent=2)
        (folder / "caption_zh.md").write_text(fig["caption_zh"] + "\n\n选择规则：" + fig["selection"] + "\n", encoding="utf-8")
    with (destination / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(dict(figures=[f["id"] for f in figures], methods=list(METHODS), aliases=ALIASES,
                       assumed_wavelength_m=1.55e-6, frozen_results_changed=False), handle, ensure_ascii=False, indent=2)
    print(json.dumps(dict(figures=len(figures), output=str(destination))))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(T9):
        parser.error("Output must be a new directory under TASK-009")
    save(output)


if __name__ == "__main__":
    main()
