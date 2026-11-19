"""Generate the TASK-024 tables, figures and reproducible analysis report."""
from __future__ import annotations

import csv
import io
import subprocess
import sys
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import numpy as np

from scripts.research.task017.prepare import ROOT
from scripts.research.task023.common import Estimate
from scripts.research.task023.phase1_run import Screening
from scripts.research.task023.phase3_pairs import PAIR_SHOTS, compare_pair
from scripts.research.task024.ablations import FULL, NO_CHIRP, NO_LOW, VARIANTS
from scripts.research.task024.audits import case_rows, regime_rows
from scripts.research.task024.controls import B1, LONG_QUAD, QUAD
from scripts.research.task024.metrics import (
    CHIRP_BINS, chirp_comparison, pair_comparison, runtime_rows, stage_comparison,
    wide_rows,
)
from scripts.research.task024.plots import case_figures, overview_figure
from scripts.research.task024.replay import OOB_CHANNEL
from scripts.research.task024.taxonomy import CATEGORIES, DROP_RISK, Row, classify, point_rows
from scripts.research.task024.taxonomy import strong_drop_details


def _write(path: Path, value: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != value:
            raise FileExistsError(f"Existing output differs: {path}")
        return
    with path.open("x", encoding="utf-8", newline="") as stream:
        stream.write(value)


def _csv(path: Path, rows: list[Row]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    _write(path, buffer.getvalue())


def _narrative(
    output: Path, checked: int, stages: list[Row], points: list[Row], details: list[Row],
    cases: list[Row], chirp: list[Row], runtime: list[Row], regimes: list[Row],
) -> str:
    counts = Counter(str(r["category"]) for r in points)
    counts_by_reason = Counter(str(r["rejection_stage"]) for r in details)
    stages_by_key = {(r["visual_stage"], r["method"]): r for r in stages}
    cohort = [(str(r["method"]), r["accepted_n"], r["centers_n"]) for r in stages
              if r["visual_stage"] == "all"]
    pooled = "\n".join(f"| {method} | {count}/{n} |" for method, count, n in cohort)
    taxonomy = "\n".join(f"| {kind} | {counts[kind]} |" for kind in CATEGORIES)
    risk = "\n".join(f"| {kind} | {n} |" for kind, n in counts_by_reason.most_common())
    summaries = {(r["case"], r.get("channel"), r.get("visual_stage"), r["method"]): r
                 for r in cases if r.get("cluster_id") is None}
    quiet = summaries["quiet_precursor_and_noise_publications", "20260630-1_ch1",
                      "stationary", FULL]
    late = [r for r in cases if r["case"] == "dual_gain_late_split"]
    pair = "、".join(f'{r["method"]} {r["disagree_250mhz_n"]}/{r["both_accepted_n"]}'
                    for r in late)
    plateau = summaries["band_ceiling_6_vs_8ghz", OOB_CHANNEL, "plateau_82_974_83_340", "M4_8G"]
    weak = next(r for r in regimes if r["channel"] == "all_14" and r["visual_stage"] == "weak_signal"
                and r["decoded_regime"] == "WEAK_COHERENT_TAIL")
    gate = [r for r in regimes if r["row_kind"] == "gate_trace" and
            r["visual_stage"] == "weak_signal"]
    gate_counts = [sum(int(str(r[key])) for r in gate) for key in
                   ("tracked_n", "tracked_short_support_n", "weak_emission_eligible_n")]
    cold = [float(str(r["standalone_cold_total_s"])) for r in runtime]
    proposal_pct = 100*sum(float(str(r["_propose_total_s"])) for r in runtime)/sum(cold)
    verify_pct = 100*sum(float(str(r["_verify_initial_s"])) for r in runtime)/sum(cold)
    stage_names = ("decline", "weak_signal", "onset", "noise_excluding_M4_CW_overlap")
    ablation = []
    for name in VARIANTS[1:]:
        delta = [int(str(stages_by_key[stage, name]["accepted_n"]))
                 - int(str(stages_by_key[stage, FULL]["accepted_n"])) for stage in stage_names]
        ablation.append(f"| {name} | " + " | ".join(f"{d:+d}" for d in delta) + " |")
    ablation_table = "\n".join(ablation)
    beta = {(row["observation_ns"], row["beta_bin_cycles"], row["method"]): row
            for row in chirp if row["visual_stage"] == "decline_and_weak_signal"
            and row["rate_cohort"] == "all"}
    beta_lines = []
    for duration, name in ((25.6, QUAD), (38.4, LONG_QUAD)):
        for group in CHIRP_BINS:
            control, tone, full = (beta[duration, group, method] for method in (name, NO_CHIRP, FULL))
            median_delta = float(str(control["median_abs_delta_M4_mhz"]))
            beta_lines.append(
                f"| {duration:g} | {group} | {control['centers_n']} | {control['published_n']} | "
                f"{tone['published_n']} | {full['published_n']} | {median_delta:.3f} |")
    beta_table = "\n".join(beta_lines)
    quiet_alternatives = "、".join(
        str(summaries["quiet_precursor_and_noise_publications", "20260630-1_ch1",
                      "stationary", name]["accepted_n"]) for name in (B1, QUAD, LONG_QUAD))
    strongest = max(details, key=lambda r: float(str(r["B1_raw_chirp_r2_64ns"])))
    max_r2 = float(str(strongest["B1_raw_chirp_r2_64ns"]))
    max_hz = float(str(strongest["B1_accepted_hz"]))/1e9
    max_t = float(str(strongest["time_s"]))*1e6
    traces = {(r["channel"], r["visual_stage"]): r for r in regimes
              if r["row_kind"] == "gate_trace"}
    low_delta = int(str(stages_by_key["stationary", NO_LOW]["accepted_n"])) - int(str(
        stages_by_key["stationary", FULL]["accepted_n"]))
    weak_ch2 = traces["20260607_ch2", "weak_signal"]
    plateau_ch2 = traces["20260607_ch2", "plateau"]
    plateau_ch1 = traces["20260701_ch1", "plateau"]
    late_asymmetry = [
        summaries["dual_gain_late_cw_asymmetry", ch, "noise", FULL]
        for ch in ("20260701_ch1", "20260701_ch2")
    ]
    clusters = len({r["cluster_id"] for r in details})
    branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT,
                                     text=True).strip()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    finished = (output / "centers" / f"{OOB_CHANNEL}_8ghz.npz").stat().st_mtime
    recorded = datetime.fromtimestamp(finished).astimezone()
    sample_rate_note = (
        "窗口样本数取最接近目标时长的偶数。原生 `boundary='full'` 在记录端点裁短支持，"
        "表中同时给出主网格和完整窗口分母，逐点支持长度保存在中心数组。"
    )
    return f"""# TASK-024 Phase 1 实测记录

执行者 Codex CLI，记录日期 {recorded:%Y-%m-%d %z}。
Research checkout {ROOT}，分支 {branch}，HEAD {head}。
项目 Python {sys.version.split()[0]}，原始电压 10 文件 / 14 通道，采集中心按原始索引每 128 点取样。
TASK-020 的 B1/B+S 与 TASK-023 Phase 3B 的中心存档逐值校核了 {checked:,} 个中心。
每条 M4 full 轨迹还与一遍独立 TASK-023 调用逐值比较，覆盖频率、调频率、原波形证据和诊断数组。
主统计含 {len(points):,} 个冻结主中心。8 GHz 副对照单独统计。
视觉分段用于结算和选图。B+S 在无视觉标签输入的条件下重现了冻结门控。

## 发布与等时长对照

| 方法 | 发布 / 主中心 |
| --- | ---: |
{pooled}

B1 在 80 GS/s 与 40 GS/s 的时长分别为 6.4 与 12.8 ns。{sample_rate_note}
原字段后缀 `64ns` 和 `256ns` 分别表示 6.4 ns 和 25.6 ns。
`local_center_snr_32ns` 是中心两侧各 3.2 ns 的宽带诊断，以 dB 表示。
原波形拟合采用线性相位或二次相位，频率以 Hz、调频率以 Hz/s 表示，
短窗剔除线性基线，长窗剔除二次基线。R² 与分半相干性反映当窗波形支持，
保留了失配、低幅、触轨、DC 阶跃、CW 或削顶谐波造成的归属不确定性。

## 留一消融

| 方法 | 下降 Δ点 | 弱信号 Δ点 | 起跳 Δ点 | 噪声段 Δ点（排除 M4 CW 重合） |
| --- | ---: | ---: | ---: | ---: |
{ablation_table}

每列为相对于 M4 full 的发布数净变化。噪声段使用同一个 M4 CW 重合掩码作为事后分层。
候选银行共享于 full、no CFAR、no low-frequency floor、no CW/harmonic 和 no path/gap。
no low-frequency floor 精确移除冻结验证器中的长持续振荡附加门槛，同时旁路经验低频惩罚。
no chirp 在频率假设、pursuit 和缺口拟合中只评分零调频率，评估仍使用统一的原波形口径。
低频门控旁路后，静态段发布净增 {low_delta} 点。仍有跨增益支路选择失配，见双增益表。

## 逐点分类与强短窗漏发风险

| 类别 | 点数 |
| --- | ---: |
{taxonomy}

M4 独有发布中，持久 CW 重合、低于 3 dB 的宽带 SNR、或达不到强与弱相干门槛，
均归入疑义类。B1 独有发布时，短窗 R² ≥ 0.15 优先触发风险审计，包含低频候选。
这样可以保留同时存在低频混淆和强短窗拟合的案例。连续同通道样本中心构成一簇。
强风险共 {counts[DROP_RISK]} 点、{clusters} 簇。具体拒绝阶段如下。

| M4 拒绝阶段 | 点数 |
| --- | ---: |
{risk}

最强 B1 局部拟合在 {strongest['channel']}、{max_t:.6f} µs，
频率 {max_hz:.3f} GHz，短窗 R² {max_r2:.3f}。M4 的阶段诊断为
`{strongest['rejection_stage']}`，附近边界为 `{strongest['nearby_boundary']}`。
逐点附带 B1 候选强制进入原生原波形门控的反事实检验、
分半 SNR、相干性、持续振荡读数和六种消融回收情况。强拟合仍可能来自谐波、台阶或其他物理支路。

## 已知案例复核

- 20260630-1_ch1 静态段 M4 发布 {quiet['accepted_n']}/{quiet['centers_n']}，
  其中 {quiet['near_1p83ghz_n']} 点在 1.83 GHz ± 50 MHz，
  {quiet['near_100mhz_n']} 点在 100 MHz ± 25 MHz。
  同阶段 B1、25.6 ns quad、38.4 ns quad 分别发布 {quiet_alternatives} 点。
- 20260607 在 555.70–555.75 µs 的双增益 >250 MHz 分歧数 / 共同发布数为 {pair}。
  两个 M4 full 轨迹在约 0.25 GHz 与 0.85 GHz 支路间选择了不同的切换时刻。
- 20260701 的噪声段中，ch1 发布 {late_asymmetry[0]['accepted_n']}/96，
  其中 {late_asymmetry[0]['persistent_cw_overlap_n']} 点重合持久 CW，ch2 发布
  {late_asymmetry[1]['accepted_n']}/96。
- 20201214m_ch1 的副频带平台由 M4 发布 {plateau['accepted_above_6ghz_n']}/{plateau['centers_n']}
  个 >6 GHz 中心。主频带与副频带的候选及原波形证据均保留在独立表中。
- 弱信号视觉标签有 {weak['count']}/{weak['centers_n']} 帧解码为 WEAK_COHERENT_TAIL。
  其中 {gate_counts[0]} 帧有 M4 轨迹，{gate_counts[1]} 帧满足短窗支持，
  仅 {gate_counts[2]} 帧可获得弱尾发射分数。
  持久 CW 检出使用尾部反复出现的低调频率窄线，重合频率和速率门槛可使整段平台获得固定 10 的 CW 发射。
- 20260607_ch2 的平台为 {plateau_ch2['cw_decoded_n']}/{plateau_ch2['centers_n']} 个 CW 标签。
  CW 标签集中在弱信号段，为 {weak_ch2['cw_decoded_n']}/{weak_ch2['centers_n']}，
  中位频率 {float(str(weak_ch2['cw_line_median_hz']))/1e6:.1f} MHz。
  关闭 CW 发射后，这些帧转为 {weak_ch2['cw_counterfactual_states']}。
- 20260701_ch1 的平台为 {plateau_ch1['cw_decoded_n']}/{plateau_ch1['centers_n']} 个 CW 标签，
  中位频率 {float(str(plateau_ch1['cw_line_median_hz']))/1e6:.1f} MHz。
  关闭 CW 发射后，这些帧转为 {plateau_ch1['cw_counterfactual_states']}。

## 调频展宽

线性调频在长度 T 的观察窗内扫过约 |df/dt|T Hz，相对于 1/T 的频率尺度，
得到无量纲的 β = |df/dt|T²。长窗增加短时能量积累，也会放大频率漂移。
下表分母含所有下降与弱信号帧，含可观测的 M4 未发布候选调频率，并显示无调频率帧。
按 M4 自身估计量分层存在选择效应，频差仅在共同发布时计算。

| T (ns) | β | 帧数 | 同时长 quad 发布 | 无调频 M4 发布 | M4 full 发布 | quad 与 M4 中位频差 (MHz) |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
{beta_table}

原波形 25.6 ns R²、分半相干性、共同发布分母和 M4 已发布子队列见 CSV。
无调频 M4 在高 β 档的发布率仍高于同时长 quad STFT，多尺度候选与验证共同参与了这一差异。
假设库的调频步长为 5 × 10¹⁵ Hz/s，对应 25.6 ns 的 β 步长约为 3.28。
中间两档在 25.6 ns 合计仅 2 帧，在 38.4 ns 为空，无法从这些档位定位固定的失效阈值。

## 耗时与复现

M4 full 独立冷启动 14 路中位 {np.median(cold):.2f} s，最慢 {max(cold):.2f} s。
首次验证占合计冷启动 {verify_pct:.1f}%，候选构建占 {proposal_pct:.1f}%。
计时使用单线程数值库与墙钟时间，
包括噪声模型、候选、验证、路径、缺口和原波形证据。独立原生执行只参与逐值比较。

```powershell
& scripts/dev/run.ps1 -Task TASK-024 -Python D:/miniconda3/envs/dps-studio/python.exe -B scripts/research/task024/run_study.py
```

`centers/` 保存全部方法的逐中心候选、发布、调频、窗长和原波形证据数组。
`tables/` 含 10 张 CSV，`figures/` 含 5 张 200 DPI PNG。
"""


def report(
    output: Path, screens: list[Screening], timing: dict[str, dict[str, float]],
    wide: dict[str, Estimate], checked: int,
) -> None:
    tables, figures = (output / name for name in ("tables", "figures"))
    for directory in (tables, figures):
        if directory.resolve() != directory:
            raise ValueError(f"Output path is a link: {directory}")
        directory.mkdir(exist_ok=True)
    by_channel = {item.channel.id: item for item in screens}
    pairs = [compare_pair(shot, by_channel[f"{shot}_ch1"], by_channel[f"{shot}_ch2"])
             for shot in PAIR_SHOTS]
    summary, stage = stage_comparison(screens)
    pair = pair_comparison(pairs)
    chirp = chirp_comparison(screens)
    runtime = runtime_rows(timing)
    regimes = regime_rows(screens)
    cases = case_rows(by_channel, pairs, wide)
    points: list[Row] = []
    details: list[Row] = []
    for item in screens:
        labels = classify(item.results[B1], item.results[FULL])
        points.extend(point_rows(item, labels))
        channel_details, clusters = strong_drop_details(item, labels, wide)
        details.extend(channel_details)
        cases.extend(clusters)
    assert len(points) == 9475 and len({(r["channel"], r["sample_index"]) for r in points}) == 9475
    assert len(details) == sum(r["category"] == DROP_RISK for r in points)
    for name, rows in (
        ("method_summary_all14", summary), ("per_channel_stage_comparison", stage),
        ("dual_gain_pairs_comparison", pair), ("b1_vs_m4_point_taxonomy", points),
        ("m4_failure_and_risk_catalog", cases), ("m4_dropped_strong_short_details", details),
        ("chirp_smearing_analysis", chirp), ("m4_runtime_profile", runtime),
        ("oob_20201214m_8ghz", wide_rows(by_channel[OOB_CHANNEL], wide)),
        ("regime_audit_summary", regimes),
    ):
        _csv(tables / f"{name}.csv", rows)
    case_figures(figures, by_channel, replace(by_channel[OOB_CHANNEL], results=wide), details)
    overview_figure(figures / "fig05_ablation_and_runtime_summary.png",
                    summary, pair, chirp, runtime)
    _write(output / "analysis_report.md",
           _narrative(output, checked, summary, points, details, cases, chirp, runtime, regimes))
    print(f"Completed 10 tables and 5 figures under {output}", flush=True)
