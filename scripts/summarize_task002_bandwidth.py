"""Summarize a completed frozen TASK-002 run without changing its raw CSVs."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.research.bandwidth_task002 import (
    Acceptance, GATED, METHODS, WINDOWS, binomial_bounds,
    reliable_boundary,
)
from run_task001_bandwidth import write_csv
from run_task002_bandwidth import CONDITIONS, ROOT, sha, write_json

COLORS = ("#777777", "#E69F00", "#0072B2", "#D55E00", "#009E73")
LABELS = ("A: default peak", "B: wide peak", "C: wide gate", "D: AR1 GLRT", "A: default gate")
STYLES = (":", "--", "-", "-.", ":")
MARKERS = ("x", "s", "o", "^", "v")


def text_file(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    rows = ["|" + "|".join(columns) + "|", "|" + "|".join("---" for _ in columns) + "|"]
    for _, row in frame.iterrows():
        values = []
        for name in columns:
            item = row[name]
            if isinstance(item, (float, np.floating)):
                values.append("NONE" if not np.isfinite(item) else f"{item:.6g}")
            else:
                values.append(str(item))
        rows.append("|" + "|".join(values) + "|")
    return "\n".join(rows) + "\n"


def save(fig: Any, out: Path, name: str) -> None:
    for suffix in ("png", "svg"):
        target = out / f"{name}.{suffix}"
        if target.exists():
            raise FileExistsError(target)
        fig.savefig(target, dpi=220, bbox_inches="tight")
    plt.close(fig)


def aggregate(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    rows = []
    rule = Acceptance()
    for labels, block in frame.groupby(keys, dropna=False, sort=True):
        if not isinstance(labels, tuple):
            labels = (labels,)
        row = dict(zip(keys, labels, strict=True))
        n, correct, accepted = len(block), int(block.correct.sum()), int(block.accepted.sum())
        low, high = binomial_bounds(correct, n)
        null_low, null_high = binomial_bounds(accepted, n)
        errors = block.loc[block.accepted == 1, "absolute_error_hz"].dropna().to_numpy()
        row.update({"n": n, "correct": correct, "accepted": accepted,
                    "correct_rate": correct/n, "correct_ci95_low": low,
                    "correct_ci95_high": high,
                    "correct_simultaneous_lower": binomial_bounds(correct, n, rule.tail)[0],
                    "accept_rate": accepted/n, "accept_ci95_low": null_low,
                    "candidate_accuracy_ignoring_gate": float(
                        (block.absolute_error_hz <= rule.tolerance_hz).mean()),
                    "accept_ci95_high": null_high,
                    "accept_simultaneous_upper": binomial_bounds(accepted, n, rule.tail)[1],
                    "accepted_wrong_rate": float(block.accepted_wrong.mean()),
                    "alias_hit_rate": float(block.alias_hit.mean()),
                    "competitor_hit_rate": float(block.competitor_hit.mean()),
                    "accepted_rmse_hz": (float(np.sqrt(np.mean(errors**2)))
                                         if errors.size else math.nan),
                    "stft_median_ms": float(block.stft_seconds.median()*1e3),
                    "both_bands_median_ms": float(block.both_spectral_bands_seconds.median()*1e3),
                    "ar1_median_ms": float(block.ar1_seconds.median()*1e3)})
        rows.append(row)
    return pd.DataFrame(rows)


def boundaries(summary: pd.DataFrame, null: pd.DataFrame) -> pd.DataFrame:
    rows = []
    rule = Acceptance()
    for window, condition, method in summary[["window", "condition", "method"]].drop_duplicates()\
            .itertuples(index=False, name=None):
        block = summary[(summary.window == window) & (summary.condition == condition)
                        & (summary.method == method)].sort_values("truth_hz")
        rho = 0. if condition == "ideal_white" else .85
        empty = null[(null.window == window) & (null.noise_rho == rho) & (null.method == method)]
        k, n = int(empty.iloc[0].accepted), int(empty.iloc[0].n)
        frequency = reliable_boundary(block.truth_hz.tolist(), block.correct.astype(int).tolist(),
                                       block.n.astype(int).tolist(), k, n, rule)
        accuracy_prefix = None
        for row in block.itertuples():
            if row.correct_simultaneous_lower < rule.correct_target:
                break
            accuracy_prefix = float(row.truth_hz)
        rows.append({"window": window, "condition": condition, "method": method,
                     "f_max_reliable_hz": frequency,
                     "v_max_apparent_m_s_synthetic": (frequency*1550e-9/2
                                                       if frequency is not None else None),
                     "accuracy_only_prefix_hz": accuracy_prefix,
                     "null_accepted": k, "null_trials": n,
                     "null_simultaneous_upper": binomial_bounds(k, n, rule.tail)[1],
                     "null_pass": binomial_bounds(k, n, rule.tail)[1] <= .01,
                     "formal_eligible": method in GATED,
                     "evidence": "SYNTHETIC_ONLY; TESTED_GRID_PREFIX"})
    result = pd.DataFrame(rows)
    gains = []
    for row in result.itertuples():
        baseline = result[(result.window == row.window) & (result.condition == row.condition)
                          & (result.method == "C_wide_gate")].iloc[0].f_max_reliable_hz
        gains.append(row.f_max_reliable_hz-baseline
                     if pd.notna(row.f_max_reliable_hz) and pd.notna(baseline) else math.nan)
    result["gain_vs_C_hz"] = gains
    return result


def figures(out: Path, summary: pd.DataFrame, boundary: pd.DataFrame,
            pressure: pd.DataFrame) -> None:
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                          "axes.spines.top": False, "axes.spines.right": False,
                          "svg.fonttype": "none"})
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.6), layout="constrained", sharey=True)
    for ax, window, condition in zip(axes.flat,
                                    [w.name for w in WINDOWS]*2,
                                    ["ideal_OU"]*3+["LP4_B6_OU"]*3, strict=True):
        for i, method in enumerate(METHODS):
            block = summary[(summary.window == window) & (summary.condition == condition)
                            & (summary.method == method)].sort_values("truth_hz")
            y = block.correct_rate.to_numpy()
            ax.errorbar(block.truth_hz/1e9, y,
                        yerr=np.array([y-block.correct_ci95_low, block.correct_ci95_high-y]),
                        color=COLORS[i], marker=MARKERS[i], linestyle=STYLES[i],
                        linewidth=1.2, markersize=4, capsize=2, label=LABELS[i])
        ax.axhline(.95, color="black", linewidth=.7, linestyle="--")
        ax.axvline(6, color="#999999", linewidth=.7, linestyle=":")
        ax.set(title=f"{window}: {condition}", xlabel="Known analog beat (GHz)",
               ylabel="Accepted and correct / all trials", ylim=(-.025, 1.04))
    handles, labels = axes[0, 0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=5, frameon=False)
    fig.suptitle("A  Synthetic only: 400 independent waveforms per point; ordinary 95% exact CI\n"
                 "Fs=40 GS/s; error <=50 MHz; formal acceptance uses simultaneous bounds", fontsize=13)
    save(fig, out, "figure_A_frequency_accuracy")

    fig, axes2 = plt.subplots(1, 3, figsize=(15, 6), layout="constrained", sharey=True)
    names = [str(c[0]) for c in CONDITIONS]
    short_names = ["Ideal\nwhite", "Ideal\nOU", "LP1 B6\nOU", "LP4 B6\nOU", "LP4 B3\nOU"]
    for ax, window_spec in zip(axes2, WINDOWS, strict=True):
        for i, method in enumerate(("A_default_gate", "C_wide_gate", "D_ar1_glrt")):
            block = boundary[(boundary.window == window_spec.name) & (boundary.method == method)]
            ys = [block[block.condition == name].iloc[0].f_max_reliable_hz/1e9 for name in names]
            x = np.arange(len(names)) + (i-1)*.23
            bars = ax.bar(x, np.nan_to_num(ys), width=.21,
                          color=[COLORS[4], COLORS[2], COLORS[3]][i],
                          hatch=["//", "", ".."][i],
                          label=["Default gate", "Wide STFT gate", "AR1 GLRT"][i])
            for bar, value in zip(bars, ys, strict=True):
                ax.text(bar.get_x()+bar.get_width()/2, .3 if not np.isfinite(value) else value+.25,
                        "NONE" if not np.isfinite(value) else f"{value:g}",
                        ha="center", va="bottom", fontsize=7, rotation=90)
        ax.set_xticks(np.arange(len(names)), short_names, fontsize=9)
        ax.set(title=window_spec.name, ylabel="Highest reliable tested prefix point (GHz)",
               ylim=(0, 20))
        sec = ax.secondary_yaxis("right", functions=(lambda x: x*.775, lambda x: x/.775))
        sec.set_ylabel("Synthetic apparent speed (km/s)")
    handles, labels = axes2[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=3, frameon=False)
    fig.suptitle("B  Synthetic only: accuracy lower bound >=95%, null upper bound <=1%\n"
                 "95% simultaneous family; NONE = no certified prefix; grid gaps remain untested",
                 fontsize=13)
    save(fig, out, "figure_B_reliable_boundary")

    fig, axes3 = plt.subplots(1, 3, figsize=(14, 4.4), layout="constrained", sharey=True)
    for ax, condition in zip(axes3, ("fast_chirp", "strong_competitor", "alias_23_to_17"),
                             strict=True):
        block = pressure[(pressure.window == "balanced") & (pressure.condition == condition)]
        pressure_x = np.arange(len(METHODS))
        block = block.set_index("method").reindex(METHODS)
        ax.bar(pressure_x-.16, block.accept_rate, .3, color="#777777", label="Accept digital candidate")
        ax.bar(pressure_x+.16, block.correct_rate, .3, color="#0072B2", label="Hit physical/center truth")
        if condition == "alias_23_to_17":
            ax.scatter(pressure_x, block.alias_hit_rate, color="#D55E00", marker="x", s=55,
                       label="Hit 17 GHz digital alias")
        ax.set_xticks(pressure_x, ["A", "B", "C", "D", "A gate"])
        ax.set(title=condition, ylabel="Fraction / 400 independent waveforms", ylim=(0, 1.08))
        ax.legend(fontsize=7, frameon=False, loc="upper center", bbox_to_anchor=(.5, -.15))
    fig.suptitle("Synthetic failure controls: accepting a periodic component does not identify an interface")
    save(fig, out, "failure_controls")


def real_summary(out: Path) -> pd.DataFrame:
    frame = pd.read_csv(out / "reference_candidates.csv")
    rows = []
    for window in ("balanced", "high_time"):
        for channel in ("ch1", "ch2"):
            base = frame[(frame.window == window) & (frame.channel == channel)]
            default = base[base.band == "default"].sort_values("frame")
            wide = base[base.band == "wide"].sort_values("frame")
            high = base[base.band == "high"].sort_values("frame")
            rows.append({"window": window, "channel": channel, "frames": len(wide),
                         "wide_above6_fraction": float((wide.peak_hz > 6e9).mean()),
                         "high_median_peak_hz": float(high.peak_hz.median()),
                         "high_peak_to_background_median_db": float(high.background_db.median()),
                         "high_peak_to_competitor_median_db": float(high.competitor_db.median()),
                         "high_to_default_median_db": float(np.median(20*np.log10(
                             high.peak_magnitude_v.to_numpy()/default.peak_magnitude_v.to_numpy()))),
                         "high_descriptive_10dB_3dB_fraction": float(
                             ((high.background_db >= 10) & (high.competitor_db >= 3)).mean()),
                         "classification": "OBSERVATIONAL_CANDIDATE; NO_REAL_FPR_CALIBRATION"})
        a = frame[(frame.window == window) & (frame.channel == "ch1") & (frame.band == "high")]
        b = frame[(frame.window == window) & (frame.channel == "ch2") & (frame.band == "high")]
        difference = np.abs(a.peak_hz.to_numpy()-b.peak_hz.to_numpy())
        for row in rows[-2:]:
            row["cross_channel_high_agreement_50MHz"] = float((difference <= 50e6).mean())
    result = pd.DataFrame(rows)
    result.to_csv(out / "reference_summary.csv", index=False)

    fig, axes = plt.subplots(2, 2, figsize=(13, 7), layout="constrained")
    for col, channel in enumerate(("ch1", "ch2")):
        with np.load(out / f"reference_{channel}_balanced.npz") as z:
            f = z["frequency_hz"]/1e9
            power = np.mean(z["magnitude"]**2, axis=1)
            db = 10*np.log10(np.maximum(power, 1e-300)/power.max())
            axes[0, col].plot(f, db, color=COLORS[col+2], linewidth=1)
            axes[0, col].axvline(6, linestyle=":", color="black")
            axes[0, col].set(title=channel+": full digital spectrum", xlabel="Frequency (GHz)",
                             ylabel="Mean STFT power / full maximum (dB)", xlim=(0, 20))
            for band, color, marker in (("default", "#0072B2", "."),
                                        ("wide", "#D55E00", "."),
                                        ("high", "#777777", "x")):
                axes[1, col].scatter((z["time_s"]-z["time_s"][0])*1e9,
                                     z[band+"_peak_hz"]/1e9, s=5, alpha=.5,
                                     color=color, marker=marker, label=band)
            axes[1, col].set(xlabel="Time from first STFT frame (ns)", ylabel="Candidate (GHz)",
                             ylim=(0, 20))
            axes[1, col].legend(frameon=False, fontsize=8)
    fig.suptitle("Actual reference waveform: observations only; no physical velocity or hardware-limit truth")
    save(fig, out, "reference_observations")
    return result


def reports(out: Path, summary: pd.DataFrame, null: pd.DataFrame, boundary: pd.DataFrame,
            pressure: pd.DataFrame, real: pd.DataFrame) -> None:
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    controls = pd.concat([pd.read_csv(p) for p in sorted(out.glob("controls_*.csv"))])
    columns = ["window", "condition", "method", "f_max_reliable_hz",
               "v_max_apparent_m_s_synthetic", "gain_vs_C_hz"]
    board = boundary[boundary.method.isin(GATED)]
    null_table = markdown_table(null[null.method.isin(GATED)], [
        "window", "noise_rho", "method", "n", "accepted", "accept_rate",
        "accept_ci95_high", "accept_simultaneous_upper"])
    text_file(out / "LIMIT_SOURCE_AUDIT.md",
              (ROOT / "docs/TASK-002_PREREGISTRATION.md").read_text(encoding="utf-8")
              + "\n## 无噪声动态控制\n\n"
              + markdown_table(controls, ["window", "truth_hz", "method", "candidate_hz", "correct"])
              + "\nSTFT存于运行内 npz 的完整单边频谱；真实2GHz显示范围不删除数字频谱。\n"
              "\n## GUI端到端补核\n\n"
              "tests/unit/gui/test_task002_high_frequency_path.py 实际执行现有GUI计算STFT、"
              "扩大Search Band、复用STFT提取8GHz、显示完整20GHz频谱并导出正式metadata/detail。"
              "GUI计算STFT后的数字编辑写入AnalysisSession.ridge_search_region，"
              "基础AnalysisRunParameters可以仍显示6GHz。analysis_adapter.py:127–135优先读取"
              "region.frequency_max_hz作为实际搜索上限；正式导出ridge_configuration记录实际范围。"
              "不能仅凭基础预设或旧analysis provenance判断本次实际搜索带。"
              "本补核不改变冻结的模拟参数/阈值。\n")
    text_file(out / "HIGH_FREQUENCY_BENCHMARK.md", "# TASK-002 高频基准\n\n"
              "所有主实验为合成。每格点400条独立波形；同一波形供全部方法。"
              "拒绝计为未正确；普通95%二项CI与正式同时下界分别报告。"
              "A/B是强制候选选择器，空信号候选率100%，不能认证可靠上限。\n\n"
              "![频率正确率](figure_A_frequency_accuracy.png)\n\n"
              "完整主格点见 frequency_summary.csv，逐波形见 evaluation_*.csv，"
              "完整空信号见 null_*.csv，独立校准分数见 calibration_*.csv。\n\n"
              "## 独立空信号风险\n\n" + null_table
              + "\n## 压力测试（描述性，不用于重调参数）\n\n"
              + markdown_table(pressure[pressure.method.isin(GATED)], [
                  "window", "condition", "method", "n", "accept_rate", "correct_rate",
                  "accepted_wrong_rate", "competitor_hit_rate", "alias_hit_rate"])
              + "\n![失效对照](failure_controls.png)\n\n"
              "快速chirp的truth为窗中心频率；单音似然与Hann中心时刻略有不同；"
              "模拟链群延迟/振幅选择也可使峰移。23GHz受采样混叠为17GHz；"
              "数字alias正确不等于原始模拟载频可识别。噪声失配/零响应的任何接受均为假恢复。\n")
    window_lines = []
    for w in WINDOWS:
        window_lines.append(f"- {w.name}: N/overlap/hop/nfft={w.n}/{w.overlap}/{w.hop}/{w.nfft}; "
                            f"支持长={w.n/40e9*1e9:g} ns; 帧步长={w.hop/40e9*1e9:g} ns; "
                            f"FFT网格={40e9/w.nfft/1e6:g} MHz; Fs/N={40e9/w.n/1e6:g} MHz; "
                            f"Hann ENBW={1.5*40e9/w.n/1e6:g} MHz。")
    text_file(out / "RELIABLE_FREQUENCY_BOUNDARY.md", "# 可靠频率边界\n\n"
              "合成格点前缀；置信家族覆盖全部主要可靠率和空信号风险比较，"
              "每个单侧尾alpha=0.05/378。正确率下界>=95%，空信号上界<=1%。"
              "表中NONE表示没有通过最低点或风险门，不代表0Hz真值。"
              "跨越的格点间隔没有连续扫描认证。18GHz为最高测试点，非绝对软件/硬件上限。\n\n"
              + markdown_table(board, columns)
              + "\n![可靠边界](figure_B_reliable_boundary.png)\n\n"
              + "\n".join(window_lines)
              + "\n\nFs/N为有限窗尺度，Hann主瓣首零点偏移2Fs/N；多频可分辨性依赖幅度与噪声。"
              "nfft只加密FFT采样；窗长不变时不增加独立信息。\n\n"
              "输入A=0.04V，噪声RMS=0.035V；LP阶数p的 |H|=[1+(f/B)^(2p)]^(-1/2)。"
              "合成输出SNR=10log10(mean(clean²)/sigma²)，见逐波形CSV。"
              "噪声在模拟响应后加入，为下游噪声模型；上游噪声同受滤波时结论可能不同。"
              "假定OU谱有高频低噪声，AR1收益有条件；改变噪声谱时空检验不受保证。\n")
    text_file(out / "REFERENCE_OBSERVATIONS.md", "# 真实参考观察\n\n"
              "原始文件仅只读，SHA前后见reference_status.json；80000行、两通道，"
              "采样网格约40GS/s。原生ADC采样、真实模拟带宽、H(f)、光学频偏、"
              "独立频率/速度真值均UNKNOWN。\n\n" + markdown_table(real, list(real.columns))
              + "\n![参考观察](reference_observations.png)\n\n"
              "10dB背景/3dB竞争比例仅描述性筛选，不是经过真实噪声校准的接纳门限。"
              "重叠帧不独立；跨通道一致性也不证明来自目标界面。高频窄带强制取峰会返回"
              "噪声/干扰候选，不可直接输出对应速度。最高状态OBSERVATIONAL_CANDIDATE，"
              "硬件增益REQUIRES_EXPERIMENTAL_CONFIRMATION。\n")
    text_file(out / "TASK002_VERDICT.md", "# TASK-002 判决\n\n"
              "总体MIXED；软件搜索限制已定位并实证；新算法收益只允许依本运行"
              "reliable_boundaries.csv逐条件比较，不外推硬件。\n\n"
              "1. 6GHz是预设搜索上限，可通过已有参数覆盖，无需修改算法或GUI。\n"
              "2. 宽带STFT在理想数字条件的最高测试点18GHz可正确选择；正式门控上限见下表。\n"
              "3. AR1是否优于宽带STFT依窗/响应/噪声条件而定；没有统一上限增益声明。\n"
              "4. 主要失效机制：带外目标遗漏、衰减后统计证据不足、模型失配、竞争支路、混叠。\n"
              "5. 模拟滚降随频率降低目标SNR；ADC丢弃/量化抹除和无外部先验的混叠不可恢复。\n"
              "6. 实际硬件可靠测速上限UNKNOWN；无证据证明本算法扩展真实硬件范围。\n"
              "7. 推荐优先取得真实接收链标定与独立注入频率真值，再冻结真实噪声校准。\n\n"
              + markdown_table(board, columns)
              + "\n本任务完成后停止，不进入TASK-003。\n")
    text_file(out / "README_TASK002.md", "# TASK-002 证据入口\n\n"
              "[判决](TASK002_VERDICT.md) · [源码归因](LIMIT_SOURCE_AUDIT.md) · "
              "[高频基准](HIGH_FREQUENCY_BENCHMARK.md) · "
              "[可靠边界](RELIABLE_FREQUENCY_BOUNDARY.md) · "
              "[参考观察](REFERENCE_OBSERVATIONS.md)\n\n"
              "全部模拟参数/种子/源哈希在config.json；主数据evaluation_*.csv、"
              "calibration_*.csv、null_*.csv、pressure_*.csv；汇总CSV不代替逐波形证据。"
              "candidate_hz保留模型候选，accepted字段控制是否接纳；拒绝的候选不得当成测量。"
              "95%普通CI用于作图，correct_simultaneous_lower/accept_simultaneous_upper用于判决。\n\n"
              "功耗/成本：时间用perf_counter；STFT时间是共享变换，both_spectral_bands_seconds"
              "同时含两带搜索/精修/质量，不可当作某单方法独占成本；AR1时间含搜索精修。"
              "成本见computational_cost.csv；单CPU线程，环境见execution_environment.json。\n\n"
              "复现（PowerShell 7，换新run-id）：\n\n```powershell\n"
              ". ./scripts/bandwidth_env.ps1\n"
              "$env:OPENBLAS_NUM_THREADS='1'\n$env:OMP_NUM_THREADS='1'\n$env:MKL_NUM_THREADS='1'\n"
              "& D:/miniconda3/envs/dps-studio/python.exe scripts/run_task002_bandwidth.py --run-id NEW_ID\n"
              "& D:/miniconda3/envs/dps-studio/python.exe scripts/summarize_task002_bandwidth.py --run-id NEW_ID\n"
              "```\n\n来源与范围见源码审计/先验冻结方案的可核验官方链接。"
              "原始参考文件不复制到结果或Git；无真实速度输出。\n")
    write_json(out / "assessment_manifest.json", {"acceptance": asdict(Acceptance()),
                "config_source_hashes": config["source_sha256"],
                "summary_script_sha256": sha(Path(__file__)),
                "all_main_source_hashes_still_match": all(
                    sha(ROOT / name) == digest for name, digest in config["source_sha256"].items()),
                "summary_rows": len(summary), "null_summary_rows": len(null),
                "boundaries": len(boundary), "pressure_summary_rows": len(pressure)})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    out = ROOT / "results/task002_bandwidth" / args.run_id
    if not out.resolve().is_relative_to((ROOT / "results/task002_bandwidth").resolve()):
        raise ValueError("Run path outside task root")
    if not (out / "completion.json").exists():
        raise RuntimeError("Benchmark is not complete")
    if (out / "assessment_manifest.json").exists() or (out / "frequency_summary.csv").exists():
        raise FileExistsError("Assessment already exists; do not overwrite")
    main_frame = pd.concat([pd.read_csv(p) for p in sorted(out.glob("evaluation_*.csv"))],
                           ignore_index=True)
    summary = aggregate(main_frame, ["window", "condition", "truth_hz", "method"])
    null_frame = pd.concat([pd.read_csv(p) for p in sorted(out.glob("null_*.csv"))], ignore_index=True)
    null = aggregate(null_frame, ["window", "noise_rho", "method"])
    pressure_frame = pd.concat([pd.read_csv(p) for p in sorted(out.glob("pressure_*.csv"))],
                               ignore_index=True)
    pressure = aggregate(pressure_frame, ["window", "condition", "method"])
    boundary = boundaries(summary, null)
    summary.to_csv(out / "frequency_summary.csv", index=False)
    null.to_csv(out / "null_summary.csv", index=False)
    boundary.to_csv(out / "reliable_boundaries.csv", index=False)
    pressure.to_csv(out / "pressure_summary.csv", index=False)
    costs = []
    for w, block in main_frame.groupby("window"):
        first = block[block.method == METHODS[0]]
        for field in ("stft_seconds", "both_spectral_bands_seconds", "ar1_seconds"):
            costs.append({"window": w, "operation": field, "waveforms": len(first),
                          "median_ms": float(first[field].median()*1000),
                          "p95_ms": float(first[field].quantile(.95)*1000),
                          "total_seconds": float(first[field].sum())})
    write_csv(out / "computational_cost.csv", costs)
    # Curvature intervals are nominal local Gaussian intervals, conditional on a
    # single-tone model; report empirical coverage rather than certifying them.
    uncertainty = []
    for keys, block in main_frame[main_frame.method == "D_ar1_glrt"].groupby(["window", "condition"]):
        accepted = block[block.accepted == 1]
        uncertainty.append({"window": keys[0], "condition": keys[1], "n_accepted": len(accepted),
                            "nominal_95pct_coverage": float((accepted.absolute_error_hz
                                      <= 1.96*accepted.ar1_nominal_sigma_hz).mean()),
                            "median_nominal_sigma_hz": float(accepted.ar1_nominal_sigma_hz.median()),
                            "scope": "conditional descriptive; selection/model dependent"})
    write_csv(out / "ar1_uncertainty_calibration.csv", uncertainty)
    figures(out, summary, boundary, pressure)
    real = real_summary(out)
    reports(out, summary, null, boundary, pressure, real)
    print(boundary[boundary.method.isin(GATED)].to_string(index=False))
    print(real.to_string(index=False))


if __name__ == "__main__":
    main()
