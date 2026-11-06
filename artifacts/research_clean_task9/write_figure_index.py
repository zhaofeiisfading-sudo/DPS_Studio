"""Write the human-readable figure/field index from the final publication pack."""
from __future__ import annotations

import json

from artifacts.research_clean_task9.prepare_figures import T9


def main() -> None:
    descriptions = {
        "Fig01_GlobalPerformance": ("总体精度、缺失与覆盖", "96波形；88有运动GT，6952运动目标帧；14方法", "不能按有限点RMSE单独排序"),
        "Fig02_PairedEffect": ("波形级配对差与95%区间", "88独立运动波形，既有配对bootstrap", "对完整M0的组合收益区间跨零"),
        "Fig03_LowVelocity": ("低速初相压力", "15/30/50/100/200 m/s各10条", "Pencil/VarPro等存在大错误解，候选与支持分开"),
        "Fig04_Onset": ("起跳误差与漏检", "88事件及条件检出集合", "条件ECDF不含漏检，不是亚采样精度证明"),
        "Fig05_Acceleration": ("强加速与起跳放大", "固定fresh_fast_accel_00", "局部Chirp模型的收益依赖场景"),
        "Fig06_Clutter": ("强静止杂散与局部放大", "固定fresh_stationary_spur_00", "相位可预测的杂散模型有针对性价值"),
        "Fig07_DoubleShockFailure": ("双冲击负结果", "固定fresh_two_shock_00；105 ns二次突变", "复杂相位优化可能差于截断STFT控制"),
        "Fig08_SubcycleFailure": ("不足周期的错误解", "15 m/s中事后选择VarPro误差最大一条", "诊断例不用于排名；收敛/拟合不能认证正确频率"),
        "Fig09_RealPDV": ("真实PDV支持假设", "(a)20260607第一电压列；(b)80GS/s 20231019 DAT", "1550 nm仅为等效速度假设，无真实GT"),
        "Fig10_Cost": ("计算成本", "原12条80k真实流、14方法", "中位至P95为分布摘要，不是置信区间"),
        "SFig01_FamilyFailure": ("全部场景的失败矩阵", "14方法×12族，每族8条", "纯噪声运动评分为NA；保留全部负结果"),
        "SFig02_RealCoverage": ("全部真实流支持覆盖", "14方法×17流，13原始文件", "支持率不是准确率；含完整路径/SHA/列映射"),
        "SFig03_RealSpectra": ("真实谱证据与坏记录", "原20260607第一电压列与ch3；512/Hann/4096", "逐记录相对功率不是SNR；谱图不能认证支路身份"),
    }
    fields = {
        "Fig01": "fresh_summary.csv：family=ALL, region=motion, channel=accepted；failure_fraction、finite_rmse_m_s、coverage。百分数仅乘100；不重算分母。",
        "Fig02": "fresh_paired_bootstrap.csv：channel=accepted，reference分别为legacy_m0_768/gated_stft512；failure_macro_delta及原ci_low/ci_high，乘100为百分点。",
        "Fig03": "phase_stress_by_velocity.csv：specified_velocity_m_s；左accepted_failure_fraction×100，右finite_rmse_m_s为candidate集合。",
        "Fig04": "all_fresh_metrics.csv：truth_onset_s非空且onset_error_ns有限时，绝对值排序后作条件ECDF；漏检从onset_and_false_outputs.csv的missed_n/88得到。",
        "Fig05–07": "原datasets/fresh/*.npz：time_s×1e9、truth_hz×1550e−9/2；各方法原trajectory.npz：time_s×1e9、accepted_hz×1550e−9/2。左保留全跨度，右仅改变显示轴限，不改变点。",
        "Fig08": "phase_stress原trajectory：左frequency_hz×1550e−9/2（candidate），右VarPro native_model_r2；同case原truth_hz作真值。仅15m/s组按原candidate_motion_rmse_m_s最大选诊断例。",
        "Fig09": "原real trajectory：accepted_hz×1550e−9/2；显示时间=(time_s−原电压首采样时刻)×1e6。只平移显示，不修改算法时间网格。",
        "Fig10": "real_runtime.csv：samples=80000；median_total_s为点，至p95_total_s为线；x轴对数。",
        "SFig01": "fresh_summary.csv：region=motion, channel=accepted，按每个family的failure_fraction；NA保留，不取零。",
        "SFig02": "all_real_metrics.csv：每个method/case_id的accepted_coverage；stream_mapping.csv保留全部17流的原始SHA、列、采样率。",
        "SFig03": "同SHA原电压经既有compute_stft；窗口512、hop128、nfft4096、Hann、无去趋势/重采样；10log10(|X|²/max|X|²)，每记录单独归一化。原accepted_hz叠加，完整谱矩阵NPZ保留。",
    }
    lines = ["# TASK-009 图件索引", "", "日期：2026-11-05。论文成品位于 `figures_final/`；`figures/` 与旧render均为QA草稿。主文可优先组合Fig01、02、03、05、06、09，Fig07/08保留失败解释，完整覆盖见补图。", "",
        "全部13图提供嵌字PDF、SVG、600 dpi PNG、figure.json来源SHA与中文图注。10主图另有可编辑Origin OPJU；SVG由矢量PDF转换，字形是路径，文字/曲线原生编辑应打开OPJU。补图由Matplotlib生成：热图单元格为矢量，谱图为声明过的600 dpi栅格加矢量坐标/轨迹。", "",
        "| 图 | 内容/数据 | 科学限制 | 文件 |", "| --- | --- | --- | --- |"]
    folders = sorted((T9 / "figures_final").glob("*"))
    for folder in folders:
        if not folder.is_dir():
            continue
        identifier = folder.name
        name, data, limit = descriptions[identifier]
        base = f"figures_final/{identifier}"
        links = f"[PDF]({base}/{identifier}.pdf) · [SVG]({base}/{identifier}.svg) · [PNG]({base}/{identifier}.png) · [图注]({base}/caption_zh.md) · [来源]({base}/figure.json)"
        if (folder / f"{identifier}.opju").exists():
            links += f" · [OPJU]({base}/{identifier}.opju)"
        lines.append(f"| {identifier}：{name} | {data} | {limit} | {links} |")
    lines += ["", "## 数值对应关系", "", "每个主图文件夹的 `panelNN_seriesNN.csv` 为完整绘图数值，单位在同目录figure.json的xlabel/ylabel中；空字段为NaN，不是零。`native_data/` 保存传给Origin的连续有限段，导入后逐点读回核验，不跨NaN、不抽稀。原始算法数组仍在TASK-008，未被绘图输出覆盖。", ""]
    for key, text in fields.items():
        lines += [f"- **{key}**：{text}"]
    lines += ["", "## 图注与阅读原则", "", "各图caption_zh.md可直接作为论文图注起稿；正式排版时保留来源、分母、选择规则和限制。全分母失败、有限点RMSE、候选与支持集合不能互相替代。95%区间以波形为重采样单位，不把相关帧当独立样本；没有新增p值或显著性星号。", "", "真实实验没有Ground Truth，v=λf/2中的1550 nm是假设，校正速度未计算；拟合、收敛、支持或重合都不能证明真实速度或界面身份。全部源表、负结果和完整M0基准保留，不以平滑程度判断成败。", "", "QA记录：`checks/figure_qa_final/structural_qa.json`、联系图、`checks/origin_project_reopen_final.json`及 `checks/VALIDATION.md`。所有成品通过页面文字边界、字体嵌入、来源SHA、原始点数与NaN、完整统计分母检查；局部放大只改变显示范围。", ""]
    with (T9 / "FIGURE_INDEX.md").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    # Machine-readable one-place index, without copying or changing results.
    index = [dict(id=k, description=v[0], data=v[1], limitation=v[2],
                  spec=f"figures_final/{k}/figure.json") for k, v in descriptions.items()]
    with (T9 / "figure_index.json").open("x", encoding="utf-8") as handle:
        json.dump(index, handle, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
