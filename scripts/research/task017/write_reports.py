"""Compile actual numerical tables, per-case links and a local figure gallery."""
from __future__ import annotations

from collections import Counter
import html
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.research.task017.compare import frozen_plans
from scripts.research.task017.prepare import OUT, ROOT, records

DOC = ROOT / "docs/tasks/TASK-017"
DATA = OUT / "data/analysis_v03"
FIG = "../../../artifacts/TASK-017/figures"


def cell(value: Any) -> str:
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not np.isfinite(number):
            return "—"
        return f"{number:.11e}" if 0 < abs(number) < .001 else f"{number:.3f}"
    return str(value).replace("|", "/").replace("\n", " ")


def table(frame: Any) -> str:
    header = "| "+" | ".join(map(str, frame.columns))+" |\n"
    line = "| "+" | ".join("---" for _ in frame.columns)+" |\n"
    return header+line+"\n".join("| "+" | ".join(cell(v) for v in row)+" |"
                                for row in frame.itertuples(index=False, name=None))+"\n"


def write(name: str, content: str) -> None:
    with (DOC / name).open("x", encoding="utf-8") as handle:
        handle.write(content)


def main() -> None:
    inventory = json.loads((OUT / "data/inventory.json").read_text(encoding="utf-8"))
    plans = frozen_plans()
    metrics = pd.read_csv(DATA / "segment_metrics.csv")
    onset = metrics[metrics.stage == "onset"]
    totals = onset.groupby("method", sort=False)[[
        "centers", "candidate_n", "gated_n", "supported_n", "supported_common50_6_n"]].sum()
    totals["支持比例%"] = 100*totals.supported_n/totals.centers
    rates = onset.groupby("method").supported_coverage_pct.mean()
    totals["通道均值支持%"] = rates
    total_table = table(totals.reset_index())
    gains = pd.read_csv(DATA / "onset_gains.csv")
    sens = pd.read_csv(OUT / "data/sensitivity_v01/metrics.csv")
    sens_table = table(sens.groupby(["method", "boundary", "shift_ns"], sort=False)[[
        "candidate_n", "gated_n", "supported_n"]].sum().reset_index())
    phase_count = Counter(seg["stage"] for plan in plans.values() for seg in plan)
    compare_manifest = json.loads((OUT / "figures/comparison_v01/manifest.json").read_text(
        encoding="utf-8"))
    cards = json.loads((OUT / "figures/highlights_v01/manifest.json").read_text(encoding="utf-8"))
    nfig = len(compare_manifest)+28+len(cards)+1
    selected_methods = ["M1_balanced", "demean1024_control", "demean512_control", "stft_short",
                        "dechirp", "visual_onset_dechirp", "visual_onset_varpro", "tone_refine",
                        "M4_specialized"]
    phase_table = table(metrics[(metrics.stage.isin([
        "onset", "plateau", "decline", "rebound", "weak_signal", "acceleration"]))
        & metrics.method.isin(selected_methods)].groupby(["stage", "method"], sort=False)[[
            "centers", "candidate_n", "gated_n", "supported_n"]].sum().reset_index())
    boundary = json.loads((OUT / "data/boundaries/comparison.json").read_text(encoding="utf-8"))
    validation = json.loads((OUT / "data/validation_release/results.json").read_text(encoding="utf-8"))
    if any(v["exit_code"] != 0 for v in validation.values()):
        raise RuntimeError("Finish required validation before writing completion reports")
    base = totals.loc["M1_balanced"]
    vp = totals.loc["visual_onset_varpro"]
    baseline_note = (f"69 个共同起跳中心：Balanced 候选 {int(base.candidate_n)}、原门控 "
                     f"{int(base.gated_n)}、短窗证据支持 {int(base.supported_n)}；视觉起跳 VarPro "
                     f"对应 {int(vp.candidate_n)} / {int(vp.gated_n)} / {int(vp.supported_n)}。")
    intro = ("所有频率/时间来自当前真实原始波形。无独立测速真值，证据支持、门控通过和物理支路身份分开；"
             "`requires experimental confirmation` 适用于全部支路。没有用任何合成信号选择参数或验收。\n\n")
    write("README.md", "# TASK-017｜真实 PDV 阶段与起跳恢复\n\n2026-11-08；完成，Research-only。\n\n"
          "**起跳信息丢失确实存在，但来源包含直流泄漏、门控和候选生成前的事件判断；不能归结为 STFT 一概失效。**\n\n"
          +baseline_note+" 原始候选覆盖始终为 100%；支持比例由 79.71% 变为 92.75%（+13.04 个百分点），"
          "这是相关帧的描述性比率，不是准确率。VarPro 原生频带到 8 GHz；仅计共同 50 MHz–6 GHz 时为 62/69。"
          "简单的去均值 512 点 STFT 已有 63/69 个短窗支持点，全部在共同频带；复杂拟合没有总体必胜证据。\n\n"
          "`20201210m` 是最清楚的专项案例：固定基准 3 个起跳中心全部选到近带下限且被拒绝；"
          "旧 VarPro 自动事件未触发，整条不生成候选；冻结视觉起跳边界后 3 个候选落在原始约 3.7 GHz 支路并有短窗支持。"
          "去均值短窗和阶段短窗各支持 2 个，说明其中大部分收益也可由简单处理获得。\n\n"
          f"![起跳案例]({FIG}/highlights_v01/20201210m_ch1__onset_card.png)\n\n"
          "当前 `data/raw` 全量为 **10 文件、14 通道**；历史 13/17 另含迁移到补充目录的 ch1/ch2/ch4，本任务未将其作为输入。"
          f"视觉先冻结 **102 段**：起跳 {phase_count['onset']}、平台 {phase_count['plateau']}、下降 {phase_count['decline']}、"
          f"回升 {phase_count['rebound']}、弱信号 {phase_count['weak_signal']}，其余见分段表。完成 **28 方法/控制/路由 × 14 通道**；"
          f"主图共 {nfig} 组 PNG+SVG，含每通道完整曲线、起跳图、谱叠加和实际存在阶段的局部图。\n\n"
          "TASK-015 保留 STFT 的安全默认有理由，但其真实数据阶段专项证据不足：真实脚本把阶段设为 unknown，"
          "M2/M3/M4 退化为 M1 是路由定义，不能证明专项方法无用。此次真实起跳与下降案例限制了把旧总体结论推广到所有阶段的做法；"
          "并未建立所有阶段统一改用 VarPro 的依据。人工起跳边界迟移 5 ns 时，视觉 VarPro 支持点从 64 降到 45，不能默认当作自动恢复。\n\n"
          "全部波长未确认，图表以 Hz/GHz 为准，速度字段 NaN；未施加角度/LiF 修正。"
          "100 项限定范围测试通过；Ruff、mypy、仓库治理检查通过。raw、全部 Production（含 .git）和 src 内容前后哈希一致。"
          "没有改 GUI、安装依赖、打包、commit、push 或 promotion。\n\n"
          "[逐通道图册](../../../artifacts/TASK-017/gallery.html) · [全部图索引](FIGURE_INDEX.md) · "
          "[起跳专项](ONSET_STUDY.md) · [数据盘点](DATA_INVENTORY.md) · [视觉标注](VISUAL_SEGMENTATION.md) · "
          "[源码与门控审计](ALGORITHM_AUDIT.md) · [完整比较/阶段建议](REAL_COMPARISON.md) · [验收与复现](VALIDATION.md)\n")

    files = pd.DataFrame(inventory["files"])
    inv = "# 数据盘点\n\n"+intro
    inv += ("当前磁盘有 10 个波形文件、14 个电压列，另有 `.gitkeep`；全部读入。10 个 SHA-256 互异，未发现字节重复。"
            "历史 TASK-009/015 的 13/17 是 10/14 加上 `data/research/TASK-009/source_data/raw_supplement/` "
            "的 `ch1.csv`、`ch2.csv`、`ch4.csv` 三个不同输入，不是重复映射；它们位于本任务唯一数据源之外，故没有运行。"
            "历史索引中标记 PROCESSED_EXCLUDED 的 `result*.dat` 未作为电压输入，当前 raw 也没有 result 文件。\n\n")
    inv += table(files[["file", "samples", "channels", "start_s", "end_s", "sample_rate_hz"]])
    inv += "\n上表为 SI 秒/Hz，时间小数的完整精度在 inventory.json；下表为便于阅读的原始绝对微秒。\n\n"
    display = files[["file", "start_s", "end_s", "sample_rate_hz"]].copy()
    display.start_s *= 1e6
    display.end_s *= 1e6
    display.sample_rate_hz /= 1e9
    display.columns = ["文件", "起始 µs", "终止 µs", "采样率 GHz"]
    inv += table(display)
    inv += ("\n全部输入无表头。显式映射为时间数值×1 s、电压数值×1 V，依据是现有 acquisition 配置和迁移索引，"
            "不是重新取得的仪器标定；若该继承映射错误，时间、频率和残差电压单位会整体失效。时间严格递增，"
            "最大相对步长偏差见 JSON，未重采样。物理波长、入射角、窗介质/晶向均未确认为本批记录的元数据；"
            "1550 nm 仅是旧 API 内部往返换算占位，未输出假设速度，也未执行窗口修正。\n\n")
    inv += table(files[["file", "sha256"]])
    inv += "\n| 通道 | 视觉质量/问题 |\n|---|---|\n"
    for item in records():
        notes = "; ".join(seg["visual_evidence"] for seg in plans[item["id"]]
                          if seg["stage"] in ("onset", "unknown", "weak_signal"))
        inv += f"| {item['id']}（原列 {item['column']}） | {notes} |\n"
    inv += "\n完整机器清单：[inventory.json](../../../artifacts/TASK-017/data/inventory.json)。"
    write("DATA_INVENTORY.md", inv)

    visual = "# 模型实际视觉分段\n\n"+intro
    visual += ("Codex 使用图像工具实际查看全部 14 张原始全程图和 14 张起跳局部图，随后才生成算法重建。"
               "视觉冻结 JSON、UTC 时间和这 28 张 PNG 的 SHA-256 在 [visual_freeze.json]"
               "(../../../artifacts/TASK-017/data/visual_freeze.json)。算法入口验证标注/输入哈希。"
               "原图仅包含电压、统一 1024 点和 256 点 Hann 图，不包含重建轨迹。用户两张图仅作示意，没有拷贝分界时间或阶段数。\n\n"
               "`stationary` 是背景/静止操作先验，绝非 AC 耦合无信号的零速度实测；有直流前驱或干扰的不确定段另标 unknown。"
               "阶段名称描述拍频形态，不证明速度方向或目标身份。置信度是视觉判断等级；±ns 是边界合理范围，不是统计置信区间。"
               "`ch3` 不强行标平台。两个回升段来自同一文件的两通道，只有一个文件层面的案例。\n\n")
    visual += table(pd.DataFrame([{"阶段": k, "段数": v} for k, v in sorted(phase_count.items())]))
    for channel, plan in plans.items():
        visual += f"\n## {channel}\n\n"
        rows = [{"ID": s["id"], "起始 µs": s["start_s"]*1e6, "结束 µs": s["end_s"]*1e6,
                 "阶段": s["stage"], "置信": s["confidence"],
                 "起始±ns": (s["start_range_s"][1]-s["start_range_s"][0])*5e8,
                 "结束±ns": (s["end_range_s"][1]-s["end_range_s"][0])*5e8,
                 "原始视觉证据": s["visual_evidence"]} for s in plan]
        visual += table(pd.DataFrame(rows))
        visual += f"\n[冻结分段图]({FIG}/comparison_v01/{channel}/frozen_segmentation.png) · "
        visual += f"[原始起跳复核图]({FIG}/visual_review/{channel}__onset_review.png)\n"
    write("VISUAL_SEGMENTATION.md", visual)

    old = pd.read_csv(OUT / "data/forensic_v01/task015_gate_counts.csv")
    audit = "# 当前实现与 TASK-015 审计\n\n"+intro
    audit += ("核心拥有者：`core/segmentation/pool.py` 的 `_stft/_frozen/default_pool`；"
              "`core/workflow/analysis.py::_build_working_ridge`；`core/quality/detection.py`；"
              "`core/segmentation/strategies.py::estimate_strategy`；`algorithms/waveform/common.py::Context/finish`；"
              "`scripts/research/task015/real.py/experiment.py`；`task014/study.py::route`。"
              "逐文件内容哈希见 [owning_source_hashes.json](../../../artifacts/TASK-017/data/forensic_v01/owning_source_hashes.json)。"
              "TASK-008～015 的报告、当前源文件、TASK-016 数据迁移记录已交叉检查；没有执行其合成生成器。\n\n"
              "正式 STFT 是 Hann 1024/H64/NFFT4096，原样不去 DC；峰值后用三点对数幅值亚频点精修。"
              "refinement 失败可以在 working ridge 保留原离散 bin，但 formal gated 仍是 NaN。"
              "门控包含峰/背景、竞争峰、周期数、谱边界和连续帧建立/重捕获；原 formal 参数阈值详见 owning source。"
              "working candidate 与 gated refined velocity 是不同数组，不能因为 formal 没显示就断言算法没算出候选。\n\n"
              "当前策略引擎在频谱初始化前投影常数/线性或二次基线，段内裁剪支撑；"
              "mode=band/glrt 限低频 ≤250 MHz，GLRT 在有足够高频谱峰时局部投影 nuisance。"
              "正弦精修对真实 cos/sin 拟合，Dechirp 为有限 chirp bank，VarPro 为频率+线性 chirp 非线性优化/线性系数投影；"
              "它们都不是额外的物理真值。长支撑 2048/4096 样本不因输出 hop 小而获得更高时间分辨。\n\n"
              "旧 Dechirp/VarPro/ACMD/Matrix Pencil/时域实现先依赖 `Context.event_detector`：未触发事件，或中心在其之前时，"
              "生成循环直接跳过。`finish` 之后还以原始 256 样本支撑的 R²、条件数、对比度及事件规则作门控。"
              "Clutter VarPro 会在内存中预测单一前缀正弦、重新创建 Context；本批 14/14 前缀 R² 未达 0.45，"
              "全都返回 NO_STRONG_COHERENT_PREFIX_TONE。因此其原生结果与 VarPro 相同，不能声称本批验证了背景扣除的优越性，"
              "也没有本批目标已在前缀而被错误扣除的实证；该风险仍来自实现假设。\n\n"
              "TASK-015 `real.py` 只实际执行 M1、短窗、长窗、GLRT、tone_refine、Clutter VarPro 六项。"
              "整条阶段为 unknown，报告写 M2/M3/M4=M1 是按映射定义推导，不是对人工真实阶段逐条运行后的优胜结果。"
              "其总体排名来自另一套合成实验；本轮没有拿那个排名选真实优胜者。\n\n"
              "下表重新读取旧真实 NPZ 中与当前 raw 相匹配的 14 通道，分母 9475 个旧共同中心；不是新数据，也没有包括补充目录三通道。\n\n")
    audit += table(old.groupby("method", sort=False)[["centers", "candidate_n", "gated_n",
                                                    "gate_rejected_n", "no_candidate_n"]].sum().reset_index())
    audit += ("\n例如旧 GLRT 9475 个候选、158 个通过，9317 个是门控拒绝，不能写作 9317 次算法计算失败。"
              "旧 M1 9475 候选、5244 门控通过、4231 被拒绝。完整质量类别保存在 forensic_v01。\n\n"
              "本轮每个方法保留 native 时间/候选/门控/质量/详细拟合，整数采样中心对齐到 128 样本网格，无频率插值。"
              "主要比较只取 1024≤sample≤N−1024，避免完整记录边缘对长窗不公平；原生边缘和无中心状态仍留在 CSV。"
              "H64 的 formal 门控先在原生 H64 上执行，再抽取共同 H128 中心，不能将其连续帧规则误认为和 H128 门控相同。\n\n"
              "首轮脚本路由未完全恢复用户 6 GHz band，本轮分析从未删掉的组件重组 M2/M3/M4，"
              "对 frozen 组件执行 50 MHz–6 GHz gate、对全部路由执行 6 GHz ceiling；full_v01 原样留档。"
              "最终分析为 analysis_v03；analysis_v02 与其所有绘图使用字段逐元素相同。\n\n"
              "结论：TASK-015 的默认是安全策略，不能据其真实部分论证所有实际阶段 STFT 最优。"
              "真实数据上的 DC 泄漏和事件生成跳过是本轮确认的两个遗漏机制；不需要重构 GUI 或正式默认值才能检验。\n")
    write("ALGORITHM_AUDIT.md", audit)

    study = "# 起跳信号恢复专项\n\n"+intro+baseline_note+"\n\n"
    study += ("C=合法频带候选；G=原方法门控输出；S=统一短窗原波形支持。S 的明示规则为："
              "原始 256 样本窗、局部线性基线后，候选邻域功率相对谱中位数 ≥10 dB、相对冻结起跳前背景 ≥6 dB，"
              "窗内 ≥1 周期，原始实值 tone 或该法 chirp 拟合 R²≥0.20。阈值是诊断定义，未经仪器实验校准；"
              "全部方法用相同原始电压验证，包括 Clutter VarPro，绝不只验证其扣除后的残差。\n\n"
              "S 可能接受瞬态、杂散或谐波。特别是 `20201214m` 早期一个低频瞬态候选通过 S，"
              "却不能据此认作连续约 6.3 GHz 主支路的恢复。64 个 S 点绝不等于 64 个已确认速度测量。"
              "第一支持时间是同一规则首个中心，不是物理起跳真值，也不是因果检测延迟：居中窗用到未来样本。\n\n")
    study += total_table
    study += ("\nVarPro 原生频带到 8 GHz，不能把该列直接当成与 6 GHz 基准完全等条件的算法收益。"
              "共同 50 MHz–6 GHz 支持数分别为 Balanced 55、去均值短窗 63、视觉 Dechirp 63、视觉 VarPro 62。"
              "候选覆盖 69/69 没有增长；VarPro 的 11 个新增 S 中心与 2 个 S 损失并存，净增 9。"
              "以文件/通道判断，视觉 VarPro 的净增集中在 4 个通道、4 个文件，其余 10 路净计数相同；并非 69 次独立试验。\n\n")
    study += table(gains[gains.method == "visual_onset_varpro"][[
        "channel", "centers", "base_supported_n", "supported_n", "supported_gain_n", "supported_loss_n",
        "same_base_candidate_rejected_n", "different_supported_candidate_n"]])
    study += ("\n“same_base_candidate_rejected”只表示两个候选相差不超过显式容差且原 M1 拒绝，不能证明改法只撤门控；"
              "完整对照更直接：单纯把 M1 的 G 换成 C，会多显示 16 点，但其中仅 3 点满足 S。"
              "其余 13 点不能因为放宽门控就当作恢复；不同候选支路必须回查原始谱。\n\n"
              f"![起跳计数]({FIG}/highlights_v01/onset_counts.png)\n\n")
    study += "## 逐条起跳回答\n\n"
    for item in records():
        channel = item["id"]
        rows = onset[(onset.channel == channel) & onset.method.isin(selected_methods)]
        study += f"### {channel}\n\n"
        study += table(rows[["method", "centers", "candidate_n", "gated_n", "supported_n",
                             "jump_250MHz_n", "first_supported_time_s"]])
        study += f"\n![原始证据与候选]({FIG}/highlights_v01/{channel}__onset_card.png)\n\n"
        if channel == "20201210m_ch1":
            study += ("原始电压有缓慢基线抬升和随后 GHz 振荡。M1 近频带下限的候选没有支持连续主线；"
                      "旧 Context 没有事件，native VarPro 全程没有候选。视觉边界让同一个 VarPro 实现计算 3 个约 3.5–3.8 GHz 起跳候选；"
                      "去均值短窗/阶段短窗各支持 2 个，说明 DC 投影有主要贡献，VarPro 另多 1 个局部支持中心。"
                      "这是有原始谱/电压支撑的条件性恢复，目标身份仍待实验确认。\n\n")
        elif channel == "20201214m_ch1":
            study += ("全 Nyquist 图的平台高于 6 GHz；只扩到 8 GHz 而不处理 DC 起跳段仍只有 0 个 S。"
                      "VarPro 原生输出约 6.3 GHz 的后续候选；早期低频瞬态即使通过 S 也不能确认为主支路。"
                      "此例混合了频带排除与基线/瞬态问题，不能全部记为 VarPro 相对同频带 STFT 的优势。\n\n")
        elif channel == "ch3_ch1":
            study += ("可见建立段只有弱且间歇的约 3.6–3.9 GHz 支路，随后幅度塌陷、支路跳变和宽带终止脉冲。"
                      "VarPro 起跳 S 比基准多 1，但不支持把整个记录连成可靠物理速度曲线；失败区与候选冲突保留。\n\n")
        elif channel.startswith("20260630") or channel.startswith("20260607") or channel.startswith("20260701"):
            study += ("多条近似谐波支路和部分削顶可见。更多 G 不自动意味着选中物理目标；"
                      "在原始谱叠加图保留所有候选竞争。既有 S 已高的通道没有稳定的净起跳收益，"
                      "不把单个跳变或更平滑曲线作优胜证据。\n\n")
        else:
            study += ("以本表比较候选/门控/支持，完整谱叠加见图册。已有主线清晰的记录，专项方法"
                      "没有建立额外物理信息的证据；起跳瞬态与背景分开，未把缺失补为零。\n\n")
    study += "## 边界与低频补充\n\n"+sens_table
    study += ("\n同一原波形、原冻结起跳中心作固定分母；±2/±5 ns 改动不是新实验。"
              "起始边界迟移 +2/+5 ns 时，视觉 VarPro 的 S 由 64 降至 58/45；视觉 Dechirp 由 64 降至 56/46。"
              "裁剪短窗对起跳结束边界较稳定，对起始边界并非单调稳定；完整 CSV 保留频率差与质量状态。"
              "这限制了依靠精确人工起跳先验的推广。\n\n"
              "低频另用 4096 样本的原始电压支撑核查 M1、低频 STFT、GLRT 中实际 ≤250 MHz 的候选，"
              "结果在 low_support_v01。13 路有足够前背景，20201210m 不足，明确记 unavailable；"
              "没有任何具有有效背景的起跳低频候选通过该长窗联合规则。"
              "该窗在 40/80 GHz 采样下为 102.4/51.2 ns，不可解释为对 7–23 ns 起跳的精确时间恢复。"
              "原生 GLRT 起跳 G 为 0/69；本批未提供可确认的低频真实目标来验证其低速优势。\n")
    write("ONSET_STUDY.md", study)

    comparison = "# 真实数据完整比较与阶段建议\n\n"+intro
    comparison += ("主比较共 28 个方法/控制/路由，14 通道，392 个完整方法流。"
                   "前 25 个在 full_v01，3 个 DC 控制在 dc_controls_v01；全部轨迹的最终共同中心、CSV、门控和原始诊断在 analysis_v03。"
                   "这些路由不是 28 个相互独立的算法。每条 CSV 保留原始合法候选、非法原始值、缺失原因、"
                   "门控、谱支持、原始电压残差、跳变可复算数据、来源、阶段和通道；波长/速度字段 NaN。\n\n")
    comparison += phase_table
    comparison += ("\n表中 n 为相关中心数量，不能用于独立重复推断。逐通道、逐阶段与完整分母见 segment_metrics.csv；"
                   "没有单一综合评分。`raw_tone_r2/raw_chirp_r2` 及残差 RMS 是在同一 256 点原始支撑的样本内模型比较，"
                   "不是误差、置信度或独立验证；有更灵活参数的拟合较好也不能证明物理正确。"
                   "相邻跳变阈值为 250 MHz，只作描述，快速真实过程同样可能超过它，不能自动删点。\n\n"
                   "## Research 决策表\n\n"
                   "| 实际条件/阶段 | 推荐候选 | 次选 | 本批证据与覆盖 | 失败/适用条件 |\n|---|---|---|---|---|\n"
                   "| 起跳伴 DC 基线或下限泄漏 | 显式去均值短窗 / 阶段短窗 | 视觉起跳 Dechirp、VarPro | 同频带去均值512支持63/69，基准55/69；20201210m视觉VP3/3 | 手工边界晚移会丢点；瞬态支持不等于主支路；保留原候选 |\n"
                   "| 主线清晰的起跳 | 保留 STFT 并查看候选 | 以上专项作为对照 | 多数通道起跳 S 无净计数增加 | 不为高覆盖而强行换法 |\n"
                   "| 快速下降 | 短窗基线投影；比较 VarPro/Dechirp | 阶段专项有符号 chirp | 基准554/699 S，去均值512为658，视觉VP673，M4为662 | Native自动事件可整条失效；长tone局部定频模型可能失配；频带也有差异 |\n"
                   "| 短暂回升 | 保留 STFT 作对照，证据不足以专推 | 短窗、Dechirp、VarPro | 同一文件双通道，72/72多法均有支持 | 只有一个独立文件；无专项净优势证据 |\n"
                   "| 窄带平台 | 先核对频带和 DC，再比较短/长窗 | 长窗正弦精修 | tone2216/2342 S，短均值2227，视觉VP2339；6.3GHz例有频带影响 | 本批不证明长窗更准确；长窗会混合边界；需报告残差/竞争峰 |\n"
                   "| 弱信号/塌陷 | 保留多法冲突与 NaN | Dechirp/VarPro 条件性候选 | 基准487/624 S，Dechirp/视觉VP514；长tone472 | 无法可靠复原所有弱段；不桥接消光；模型候选不作测量 |\n"
                   "| 静止/低频先验 | 先验独立记录，不输出实测零 | 低频 GLRT 仅实验条件满足时手选 | 本批起跳 GLRT0/69 G；无确认低速目标 | 低频模型、周期数和前端未知；不能凭先验产生速度 |\n"
                   "| 固定杂散 | 本批证据不足以专推 Clutter VP | 原始 VarPro并行对照 | 14/14前缀未达扣除条件，结果退化为VP | 未测试到符合相干固定杂散条件的真实正例；目标在前缀时存在误扣风险 |\n\n"
                   "前后缀噪声候选可有谱支持，但没有可确认运动身份；本次没有准确率、真实 RMSE、符号速度或校正速度结论。"
                   "ACMD 变体、LS Matrix Pencil 与正则化时域法真实运行且保留负结果，起跳 S 为60/62/58，"
                   "没有优于简单去均值短窗的总体证据。ACMD 是现有单模态启发式变体；时域法有模型正则化，"
                   "其内部模型初始化/频率基函数不等于对缺失测量作事后插值。未新增滤波或曲线平滑。\n\n"
                   "## 成本与可复现性\n\n"
                   "metadata.json 逐方法记录实际 wall time、窗口、频带、代码来源；Context 初始化另列。"
                   "数值库单线程，但有 3 条真实记录并发，因此只报告执行成本，不作方法间硬件加速比。"
                   "路由成本是所有用到整轨组件成本之和，包含重算，不是优化后按段 GUI 延迟。\n\n")
    runtime_rows: list[dict[str, Any]] = []
    for item in records():
        meta = json.loads((DATA / item["id"] / "metadata.json").read_text(encoding="utf-8"))
        runtime_rows.extend({"method": name, "runtime_s": value["runtime_s"]}
                            for name, value in meta["methods"].items())
    comparison += table(pd.DataFrame(runtime_rows).groupby("method").runtime_s.agg(
        ["median", "min", "max"]).reset_index())
    write("REAL_COMPARISON.md", comparison)

    index = f"# 全部图件索引\n\n主交付 {nfig} 组，每组 PNG 和 SVG；另保留 preflight 开发图，不作最终图。\n\n"
    index += ("全程和起跳比较包括全部 28 个方法/控制/路由，分组使用统一 0–8 GHz 坐标。"
              "圆点是原门控通过，叉号是被拒候选，灰竖线是独立分类状态行的缺失，不是零频。"
              "图中颜色相同的重叠点可能互相覆盖，完整逐点数据以 CSV 为准。"
              "没有确认波长，所以全部图使用拍频；每图标明频带差异。\n\n"
              "[逐通道 HTML 图册](../../../artifacts/TASK-017/gallery.html)\n\n")
    for item in records():
        channel = item["id"]
        index += f"## {channel}\n\n| 图 | PNG | SVG |\n|---|---|---|\n"
        entries = [r for r in compare_manifest if r["channel"] == channel]
        entries += [r for r in cards if r["channel"] == channel]
        for tag in ("overview", "onset_review"):
            entries.append({"png": f"figures/visual_review/{channel}__{tag}.png",
                            "svg": f"figures/visual_review/{channel}__{tag}.svg"})
        for row in entries:
            title = Path(row["png"]).stem
            index += f"| {title} | [PNG](../../../artifacts/TASK-017/{row['png']}) | "
            index += f"[SVG](../../../artifacts/TASK-017/{row['svg']}) |\n"
    index += f"\n![计数概览]({FIG}/highlights_v01/onset_counts.png)\n"
    write("FIGURE_INDEX.md", index)

    validation_text = "# 验证、复现与边界\n\n"
    validation_text += ("限定范围 pytest **100 passed**；包括既有非波形/非 GUI 单元测试和新增真实输入契约。"
                        "没有运行会生成合成波形的旧算法测试，以遵守本次零合成要求；不能写成全仓测试全部通过。"
                        "核心算法数值未改，全部 raw 上25方法+3控制实际执行，0方法异常；"
                        "另完成边界起始/结束±2/±5ns及长支撑低频核查。\n\n")
    validation_text += table(pd.DataFrame([{"检查": k, "exit_code": v["exit_code"]}
                                         for k, v in validation.items()]))
    validation_text += "\n保护边界完整内容和 mtime 核对：\n\n"+table(pd.DataFrame(
        [{"边界": k, "前后相同": v} for k, v in boundary.items()]))
    validation_text += ("\nProduction manifest 跳过目录 symlink/junction，不读取或写入其外部目标；Production .git 的实际文件也纳入。"
                        "Research初始工作树/暂存区干净，HEAD为 `4fea2c4493cb2758f85e8473e0442dd51607c590`，"
                        "分支 `codex/research_2/global-path-ridge-v2`。只增加 scripts/research/task017、tests/unit/test_task017_real_research.py、"
                        "docs/tasks/TASK-017 与被忽略的 artifacts，另写用户指定 Obsidian 日志。"
                        "没有修改 src、GUI、默认参数、正式导出、.gitignore 或 AGENTS，现有规则已覆盖。"
                        "无 Git 写命令、打包、全局/局部依赖安装；未触及 raw/Production 写权限。\n\n"
                        "## 开发失败与处理\n\n"
                        "早期 mypy 因 namespace module 重复定位、缺少科学库 stubs 和少量类型/未使用导入报错，"
                        "用 explicit-package-bases、准确类型和局部 import-untyped 注解修复，没有安装新依赖。"
                        "validation_v01 为84项阶段检查，validation_v02、validation_final、validation_delivery保留静态检查修正过程；"
                        "100项真实/元数据测试均已通过。最终静态检查以validation_release为准，其中pytest记录明确复用validation_delivery的通过日志，未重复运行已通过测试。\n\n"
                        "首轮路由的6GHz限制在未删的原组件上重新组装；最终数值与所有图的时间/候选/门控/短窗支持逐元素验证相同。"
                        "开发版4096窗背景循环恰好空范围，导致长窗支持诊断无效；analysis_v01/v02的 long4096_* 不用于结论。"
                        "已修正为允许恰好完整的背景窗，用 low_support_v01 单列有效性。最终 analysis_v03 删除全部无效长窗列，"
                        "新增真实背景可用性回归测试。20201210m原始前背景仍不足4096点，保留 unavailable，不作零支持负结果。\n\n"
                        "未删除旧结果或临时缓存。小型可重建工具缓存仍集中 artifacts/TASK-017/tmp；无根目录缓存/环境；"
                        "若要清理，只应人工确认此 tmp 的用途，不能删冻结结果。\n\n"
                        "## 复现\n\n"
                        "Python 3.12/3.13；本次既有环境见 validation_release/environment.json。所有数据输出选不存在的新目录，"
                        "脚本会拒绝覆盖。视觉阶段由实际看图形成，不能用自动检测重新冒充视觉标注；冻结文件已经交付。\n\n"
                        "```powershell\n$task17Python = 'D:\\miniconda3\\envs\\dps-studio\\python.exe'\n"
                        "& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.compare --output artifacts/TASK-017/data/replay_new --workers 3\n"
                        "& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.dc_controls --output artifacts/TASK-017/data/dc_new\n"
                        "& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.sensitivity --output artifacts/TASK-017/data/sensitivity_new\n"
                        "& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.analyze --run artifacts/TASK-017/data/replay_new --controls artifacts/TASK-017/data/dc_new --output artifacts/TASK-017/data/analysis_new\n"
                        "& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.plot --analysis artifacts/TASK-017/data/analysis_new --output artifacts/TASK-017/figures/replay_new\n"
                        "& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.highlights --analysis artifacts/TASK-017/data/analysis_new --output artifacts/TASK-017/figures/cards_new\n"
                        "& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.low_support --analysis artifacts/TASK-017/data/analysis_new --output artifacts/TASK-017/data/low_new\n"
                        "& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.validate --output validation_new\n```\n\n"
                        "DC控制入口 dc_controls.py，长窗核查 low_support.py，重点卡图 highlights.py，归档门控 audit15.py。"
                        "DC控制直接读取当前raw及冻结阶段；卡图/长窗核查可用--analysis显式选择新结果。测试和报告编译默认校验本次冻结交付路径。"
                        "首次 raw 盘点/图片/冻结脚本只在干净任务目录运行，现有 freeze 不应重写。\n")
    write("VALIDATION.md", validation_text)

    parts = ["<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>TASK-017真实PDV图册</title>",
             "<style>body{font:16px system-ui;max-width:1250px;margin:30px auto;background:#f4f6f8;color:#182835}"
             "img{width:100%;background:white}section{background:white;padding:20px;margin:25px 0;border-radius:9px}"
             "nav{position:sticky;top:0;background:#e4edf2;padding:12px}a{color:#126287}summary{cursor:pointer;padding:10px}</style>",
             "<h1>TASK-017：真实PDV逐通道图册</h1><p>10文件、14通道；28方法/控制/路由。"
             "两张用户示例图未提供实际分段。波长未确认，纵轴为拍频；无速度真值/准确率结论。</p>",
             "<p>先看彩色起跳卡片，再展开全程28法曲线和各阶段局部图。圆点=原门控通过，叉号=拒绝候选，"
             "灰竖线=状态行缺失；空心菱形=短窗诊断支持，不等于物理身份。</p><nav>"]
    parts.extend(f"<a href='#{html.escape(r['id'])}'>{html.escape(r['id'])}</a> · " for r in records())
    parts.append("</nav>")
    for item in records():
        channel = item["id"]
        card_path = f"figures/highlights_v01/{channel}__onset_card.png"
        parts.append(f"<section id='{html.escape(channel)}'><h2>{html.escape(channel)}</h2>"
                     f"<img loading='lazy' src='{card_path}' alt='起跳原始证据与候选'>"
                     f"<p><a href='data/analysis_v03/{channel}/candidates.csv.gz'>全部候选CSV.gz</a> · "
                     f"<a href='{card_path[:-4]}.svg'>卡片SVG</a></p>")
        for row in compare_manifest:
            if row["channel"] != channel:
                continue
            label = html.escape(Path(row["png"]).stem)
            parts.append(f"<details><summary>{label} · <a href='{row['svg']}'>SVG</a></summary>"
                         f"<img loading='lazy' src='{row['png']}' alt='{label}'></details>")
        parts.append("</section>")
    parts.append("</html>")
    with (OUT / "gallery.html").open("x", encoding="utf-8") as handle:
        handle.write("\n".join(parts))
    note = Path("D:/Research/Notes/05项目/dps/2026-11-08_TASK-017_真实数据阶段算法与起跳恢复研究.md")
    note_text = ("# TASK-017｜真实数据阶段算法与起跳恢复研究\n\n"
                 "日期：2026-11-08；状态：完成；分支：codex/research_2/global-path-ridge-v2；"
                 "HEAD：4fea2c4493cb2758f85e8473e0442dd51607c590。\n\n"+baseline_note+
                 " 去均值短窗已有63/69支持点；原始候选覆盖未增加；无准确率结论。"
                 "10个真实文件14通道全部运行，28方法/控制/路由。102段视觉标注在算法曲线前冻结。"
                 "旧13/17另含不在当前raw的3个补充文件；本轮未使用。\n\n"
                 "改动：Research scripts/research/task017、tests/unit/test_task017_real_research.py、docs/tasks/TASK-017；"
                 "artifact：D:/Code/Python_Projects/DPS_Studio_RESEARCH_CLEAN/artifacts/TASK-017，最终数值data/analysis_v03，"
                 f"图件{nfig}组PNG/SVG及gallery.html。测试：100 passed；Ruff/mypy/hygiene通过；"
                 "src/raw/Production及.git前后完整哈希相同，暂存区无改动；无commit/push/promotion、GUI更改或打包。\n\n"
                 "结论：TASK015安全默认不能推广为真实所有阶段STFT最优；DC预处理和事件生成先验是重点。"
                 "20201210m视觉VP有条件恢复3点；边界迟移5ns显著减少支持。6.3GHz记录有频带混淆，"
                 "削顶谐波、ch3间歇弱段与消光不能可靠赋予物理支路。下一步：实验确认波长/目标身份，"
                 "再决定是否将显式候选诊断或预处理进入软件；本次完成后停止，无自动推广。\n")
    with note.open("x", encoding="utf-8") as handle:
        handle.write(note_text)
    print("Eight reports, figure index/gallery, and Obsidian note written", flush=True)


if __name__ == "__main__":
    main()
