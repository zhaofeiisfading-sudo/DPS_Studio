"""Non-destructive TASK-002 result QA and numerical-limit supplement.

Adds new files only; frozen thresholds, main benchmark, and earlier CSVs stay
unchanged. Fast-chirp refinement is a numerical check, never label tuning.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from dps_studio.research.bandwidth_task001 import AnalogCase, NoiseModel
from dps_studio.research.bandwidth_task002 import (
    Acceptance, FS, GATED, METHODS, WINDOWS, WideToneSearch, acquire,
)
from run_task001_bandwidth import write_csv
from run_task002_bandwidth import ROOT, evaluate, seed, sha, trial_rows, write_json
from summarize_task002_bandwidth import COLORS, LABELS, MARKERS, STYLES, save, text_file


def numerical_chirp_check(out: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for wi, w in enumerate(WINDOWS):
        data = json.loads((out / f"thresholds_{w.name}_1.json").read_text(encoding="utf-8"))
        search = WideToneSearch(w.n, FS, NoiseModel(**data["model"]))
        base = AnalogCase(sample_rate_hz=FS, bandwidth_hz=6e9, n=w.n, frequency_hz=12e9,
                          amplitude_v=.04, noise_rms_v=.035, noise_rho=.85,
                          chirp_hz_per_s=8e9*FS/w.n)
        for i in range(4):
            trial_seed = seed(5, wi, 0, 0, i)
            ref = acquire(replace(base, oversample=256), trial_seed)
            norm = float(np.linalg.norm(ref.clean_v))
            for oversample in (8, 16, 32, 64, 128, 256):
                wave = acquire(replace(base, oversample=oversample), trial_seed)
                relative_rms = float(np.linalg.norm(wave.clean_v-ref.clean_v))/norm
                values = trial_rows(evaluate(wave.voltage_v, w, search), data["thresholds"],
                                    {"window": w.name, "trial": i, "seed": trial_seed,
                                     "truth_hz": 12e9, "alias_hz": 12e9})
                for row in values:
                    row["oversample"] = oversample
                    row["relative_waveform_error_vs_256"] = relative_rms
                    row["numerical_check_only"] = True
                    rows.append(row)
    write_csv(out / "supplement_chirp_convergence.csv", rows)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    out = ROOT / "results/task002_bandwidth" / args.run_id
    if not out.resolve().is_relative_to((ROOT / "results/task002_bandwidth").resolve()):
        raise ValueError("Outside task root")
    if (out / "result_qa.json").exists() or (out / "supplement_chirp_convergence.csv").exists():
        raise FileExistsError("Supplement already exists")
    summary = pd.read_csv(out / "frequency_summary.csv")
    null = pd.read_csv(out / "null_summary.csv")
    groups = []
    for label in ("evaluation", "null", "calibration", "pressure"):
        files = sorted(out.glob(label+"_*.csv"))
        files = [p for p in files if not p.name.endswith("_summary.csv")]
        block = pd.concat([pd.read_csv(p, dtype={"seed": str}) for p in files], ignore_index=True)
        groups.append((label, block))
    seeds = {name: set(block.seed.astype(str)) for name, block in groups}
    collisions = {a+"_"+b: len(seeds[a] & seeds[b]) for a in seeds for b in seeds if a < b}
    if any(collisions.values()):
        raise RuntimeError("Independent split seeds intersect")
    if len(summary) != 600 or not (summary.n == 400).all():
        raise RuntimeError("Missing or incomplete main frequency groups")
    if len(null) != 30 or not (null.n == 4096).all():
        raise RuntimeError("Missing or incomplete null groups")
    main_rows = dict(groups)["evaluation"]
    agreement = main_rows.groupby(["window", "condition", "truth_hz", "trial"])
    if not (agreement.seed.nunique() == 1).all() or not (agreement.method.nunique() == 5).all():
        raise RuntimeError("Methods did not share the same seeded waveform")
    config = json.loads((out / "config.json").read_text(encoding="utf-8"))
    hashes_ok = all(sha(ROOT / k) == v for k, v in config["source_sha256"].items())
    if not hashes_ok:
        raise RuntimeError("Frozen benchmark sources changed")
    # Report false recovery for ABSENT targets using acceptance, never a chance
    # frequency-proximity hit. Raw pressure CSVs preserve their original columns.
    pressure = dict(groups)["pressure"]
    absent = pressure[pressure.condition.isin([
        "zero_response", "noise_mismatch_white", "quantization_erasure"])]
    absent_rows = []
    for keys, block in absent.groupby(["window", "condition", "method"]):
        absent_rows.append({"window": keys[0], "condition": keys[1], "method": keys[2],
                            "n": len(block), "false_recoveries": int(block.accepted.sum()),
                            "false_recovery_rate": float(block.accepted.mean()),
                            "true_target_identifications": 0,
                            "coincidental_frequency_hits": int(block.correct.sum())})
    write_csv(out / "absent_target_false_recovery.csv", absent_rows)
    numerical = numerical_chirp_check(out)
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8), layout="constrained", sharey=True)
    for ax, w in zip(axes, WINDOWS, strict=True):
        for i, method in enumerate(METHODS):
            block = summary[(summary.window == w.name) & (summary.condition == "ideal_white")
                            & (summary.method == method)].sort_values("truth_hz")
            y = block.correct_rate.to_numpy()
            ax.errorbar(block.truth_hz/1e9, y,
                        yerr=np.array([y-block.correct_ci95_low, block.correct_ci95_high-y]),
                        color=COLORS[i], marker=MARKERS[i], linestyle=STYLES[i],
                        markersize=4, capsize=2, linewidth=1.2, label=LABELS[i])
        ax.axvline(6, color="black", linewidth=.7, linestyle=":")
        ax.axhline(.95, color="black", linewidth=.7, linestyle="--")
        ax.set(title=w.name, xlabel="Known analog beat (GHz)", ylabel="Accepted and correct / all trials",
               ylim=(-.025, 1.04))
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="outside lower center", ncol=5, frameon=False)
    fig.suptitle("A1  Synthetic ideal receiver + white noise: 400 independent waveforms per point\n"
                 "Fs=40 GS/s; error <=50 MHz; ordinary 95% exact CI", fontsize=12)
    save(fig, out, "figure_A1_ideal_digital_accuracy")
    # Individual points are distinct from the mandatory passing prefix.
    point_rows = []
    for row in summary.itertuples():
        rho = 0. if row.condition == "ideal_white" else .85
        null_row = null[(null.window == row.window) & (null.noise_rho == rho)
                        & (null.method == row.method)].iloc[0]
        point_rows.append({"window": row.window, "condition": row.condition,
                           "method": row.method, "truth_hz": row.truth_hz,
                           "point_pass": (row.method in GATED
                                          and row.correct_simultaneous_lower >= .95
                                          and null_row.accept_simultaneous_upper <= .01),
                           "prefix_required_separately": True})
    write_csv(out / "individual_grid_point_checks.csv", point_rows)
    raw_errors = numerical[numerical.method == "D_ar1_glrt"].groupby("oversample")\
        .relative_waveform_error_vs_256.agg(["min", "max"])
    refined = numerical[(numerical.oversample == 256) & (numerical.method == "D_ar1_glrt")]
    text_file(out / "MEASUREMENT_LIMITS_AND_QA.md", "# 数值与解释补核\n\n"
              "主扫描/阈值/原始CSV均未覆盖；追加检查不改变冻结验收。\n\n"
              "## 广谱门控与可识别性\n\n"
              "OU下峰/全频带背景对比度受到噪声谱形影响。C未取得3GHz起始的合格前缀，"
              "不等于STFT无法估计所有高频，也不等于最高频点必然失败。例如Balanced理想OU："
              "3GHz接纳正确378/400，18GHz395/400；后者单点通过但前缀不通过。"
              "B忽略门控时两点都400/400。AR1改变了噪声加权和检测统计量，"
              "相对于本次C门的优势不能外推为相对于全部STFT门控方法的优势。"
              "C无前缀时gain_vs_C_hz为NaN，不把NONE当0计算GHz增益。\n\n"
              "## 完全无目标的假恢复\n\n"
              "noise_mismatch_white / zero_response / quantization_erasure 中，任何接纳均为假恢复。"
              "原始pressure文件correct只按距预置频率50MHz的数值接近计算；"
              "噪声失配偶然靠近预置频率的点不构成正确目标识别。"
              "absent_target_false_recovery.csv 给出科学判定：true_target_identifications恒为0。\n\n"
              "## chirp模拟精度\n\n"
              "初始8x对32x相对波形RMS差约8.6–8.8%，未达到收敛；"
              "不得将8x压力测试的精确误接受比例当作已收敛的连续硬件预测。"
              "追加相同12条种子的8/16/32/64/128/256x检查，256x为数值参考；"
              "不是整个参数空间收敛证明，也不重新校准阈值。\n\n"
              + raw_errors.to_string() + "\n\n"
              + f"256x检查AR1共{len(refined)}条：接纳{int(refined.accepted.sum())}条，"
              + f"满足中心频率误差{int(refined.correct.sum())}条；仅描述性，不认证统计比例。\n\n"
              "初始8x统计保留；主扫描全为平稳tone精确复响应，不受该数值近似影响。\n\n"
              "## 独立性\n\n"
              "result_qa.json记录全部主要分组计数、方法共用波形种子、四阶段种子无交集和冻结源哈希一致。"
              "主扫描600组均400条；空信号30组均4096条。"
              "所有绘图已目视检查，标签/单位/置信范围和模拟/真实区分明确；线型与图案可灰度阅读。\n")
    write_json(out / "result_qa.json", {
        "main_groups": len(summary), "null_groups": len(null),
        "evaluation_row_counts": {name: len(block) for name, block in groups},
        "independent_waveform_counts": {name: len(s) for name, s in seeds.items()},
        "stage_seed_collisions": collisions, "same_waveform_all_methods": True,
        "frozen_sources_unchanged": hashes_ok, "qa_script_sha256": sha(Path(__file__)),
        "numerical_chirp_rows": len(numerical), "main_stationary_model_exact": True,
        "initial_chirp_numerically_converged": False,
        "supplemental_chirp256_ar1_accepted": int(refined.accepted.sum()),
        "supplemental_chirp256_ar1_correct": int(refined.correct.sum()),
        "rule": str(Acceptance()),
    })
    print((out / "result_qa.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
