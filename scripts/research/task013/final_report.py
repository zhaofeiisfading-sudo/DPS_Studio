"""Final reports from disjoint-seed evaluation_v02; archive prior own reports."""
from __future__ import annotations

import json
import shutil
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from .experiment import OUT
from .report import md_table


def write(name: str, value: str) -> None:
    destination = OUT / name
    if destination.exists():
        backup = OUT / "checks/reports_v01" / name
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise FileExistsError("Prior report backup already exists; choose a new review version")
        shutil.copy2(destination, backup)
    destination.write_text(value.strip() + "\n", encoding="utf-8", newline="\n")


def select(frame: pd.DataFrame, method: str, *, split: str = "independent",
           **filters: str) -> Any:
    take = (frame.method == method) & (frame.split == split) & (frame.kind == "supported")
    for key, value in filters.items():
        take &= frame[key] == value
    return frame[take].iloc[0]


def main() -> None:
    folder = OUT / "statistics/final_v02"
    overall = pd.read_csv(folder / "overall.csv")
    stage = pd.read_csv(folder / "stage.csv")
    families = pd.read_csv(folder / "family.csv")
    pairs = pd.read_csv(folder / "paired.csv")
    cost = pd.read_csv(folder / "cost.csv")
    sensitive = pd.read_csv(folder / "annotation_sensitivity.csv")
    ablation = pd.read_csv(OUT / "statistics/routing_ablation_v02/overall.csv")
    ablation_pairs = pd.read_csv(OUT / "statistics/routing_ablation_v02/paired.csv")
    new = select(overall, "stage_map")
    simple = select(ablation, "simple_stage_map")
    lp = select(stage, "profile2048", region="low_frequency")
    ls = select(stage, "clip_stft2048", region="low_frequency")
    old_cur = select(overall, "current_map", split="legacy_fresh")
    old_new = select(overall, "stage_map", split="legacy_fresh")
    old_simple = select(ablation, "simple_stage_map", split="legacy_fresh")
    delta = new.failure_percent - simple.failure_percent
    old_delta = old_new.failure_percent - old_simple.failure_percent
    common_columns = ["method", "rmse_m_s", "coverage_percent", "failure_percent"]
    common_labels = ["方法", "支持RMSE m/s", "覆盖 %", "含缺失失败 %"]
    main_table = ablation[(ablation.split == "independent") & (ablation.kind == "supported")
                         & ablation.method.isin(["current_map", "simple_stage_map", "stage_map"])]
    compact = md_table(main_table, common_columns, common_labels)
    write("README.md", f"""
# TASK-013｜分阶段算法适配与 Git 治理

2026-11-06；**研究完成。优先改进阶段信息、窗长和使用条件，保留现有算法池与正式默认值。**

**Git治理完成：**误提交b8faed27未进入远端研究分支。Research已转为独立.git，保留远端26066704为浅历史基点；本地发布包与旧成果保留，待推送历史只有轻量代码/文档。精确ignore及本仓库pre-commit检查生效；未push、未写Production Git。[Git报告](GIT_CLEANUP.md)

**阶段需要分维度，算法数量无需普遍增加。**保留九个人工入口，区分运动形态、观测质量和杂波/边界条件。静止先验、低频可见、无可观测拍频分开；最低频率不是实测零速度。下降/回升也值得复用Dechirp。[阶段算法表](STAGE_ALGORITHM_MAP.md)

290条GT波形（146旧＋144全局不重用开发种子的新测试），13种方法/控制/映射，3770条正式配置、0异常。独立新分布如下；NaN和消光保留在失败分母中：

{compact}

收益以人工阶段及±2 ns边界信息为条件，不是自动识别能力。复杂预设相对简单适配的失败差为{delta:+.2f}个百分点；旧主分布为{old_delta:+.2f}个百分点。旧主分布当前→复杂预设RMSE {old_cur.rmse_m_s:.2f}→{old_new.rmse_m_s:.2f} m/s，起跳MAE {old_cur.onset_mae_ns:.2f}→{old_new.onset_mae_ns:.2f} ns，不能全面替换。

**值得保留：**稳定低频的长窗频率剖面可选精修，低频组RMSE {lp.rmse_m_s:.3f} m/s、覆盖{lp.coverage_percent:.2f}%；匹配长窗STFT为{ls.rmse_m_s:.3f} m/s、{ls.coverage_percent:.2f}%。覆盖收益主要来自窗长，chirp变体继续作为研究原型。

**负结果保留：**漂移杂波、交叉双支路和消光仍会失败；无拍频静止输出NaN。13份真实原始文件/17路只作Hz观测，不宣称真实支路正确。[完整比较](COMPARISON.md)

[六组科研图](FIGURE_INDEX.md) · [协议及独立性修订](PROTOCOL.md) · [验证与复现](VALIDATION.md)。原raw、发布包、src/configs与Production（含完整.git）校验一致；旧生成成果按路径/大小/mtime清单保留。首轮跨场景12个种子重用已披露，evaluation_v01只作探索记录，最终采用evaluation_v02。
""")
    write("STAGE_ALGORITHM_MAP.md", f"""
# 阶段分类与算法推荐

## 分类结论

现有九个标签可保留为人工入口，但不宜成为一个互斥分类。“加速/平台”描述运动，“弱信号/噪声”描述观测，两者可以同时成立。内部推荐分为`kinematics`、`observation`和`context`，本轮不改GUI或核心枚举。

运动形态保留静止先验、起跳/突变、连续正负斜坡、平台、转折后回升和未知；下降与加速共享带斜率的模型，回升标记转折后复用正斜率模型。弱信号、噪声和消光移作观测属性。静止必须细分**实验先验为零、低频分量可见、无足够拍频信息**；不得合并为测得零速。上下文记录边界不确定度、前缀是否可能有目标、杂波持续性、可用周期和前端高通标定状态。

| 人工阶段 | 条件推荐 | 简单控制/互补 | 限制 |
| --- | --- | --- | --- |
| 静止 | 无拍频→NaN；低频可见→长窗STFT，必要时Profile2048精修 | STFT768/1024、匹配长窗STFT | 先验零速独立保存，不填进测量列 |
| 起跳 | 短窗STFT及显式边界下的单侧/截断窗作审计基准 | 连续斜坡可比较Dechirp/VarPro | 短窗并非所有起跳案例赢家；人工边界不是自动检测结果 |
| 加速 | 可见连续分量优先Dechirp；局部VarPro精修 | 零斜率Profile512、短窗STFT512 | 相位重置/多分量会失配；有界chirp仅为研究变体 |
| 平台 | STFT768/1024；稳定内部可选长窗及Profile2048 | 长窗STFT2048隔离窗长收益 | 含边界误差的平台组不保证更优 |
| 下降 | 连续减速复用Dechirp，必要时VarPro | 原STFT、零斜率控制 | 不因新增阶段而另注册一个算法 |
| 回升 | 转折附近检查短窗，连续回升复用Dechirp | VarPro/有界chirp研究精修 | 非负拍频不能独立确定真实运动方向 |
| 弱信号 | 近稳态用长窗；持续相干杂波且前缀无目标时用Clutter VarPro | 减/不减杂波并列诊断 | 漂移杂波及前缀已有目标可失败；消光NaN |
| 噪声 | 不估计（NaN＋原因） | 候选仅作诊断 | 不以最低频率填零 |
| 未知 | STFT基准并保留人工选择 | 多窗及局部模型残差 | 身份不明保留多候选或不估计，R²不能确认支路 |

## 算法池与专用变体

现有五项池作为框架足够，优先补充支持窗、参数和质量诊断。Profile2048值得作为稳定低频精修选项；有界chirp512保留研究代码，尚不支持普遍增加正式算法。预设受检映射`stage_map`与最终条件性建议不同，不能把论文图中的建议称为已验证的自动默认。

当前比较映射是加速→Dechirp、噪声→NaN、其余→STFT768。768是本比较明确选定的配置，不声称是所有用户当前设置。预设映射增加低频/平台→Profile2048、下降/回升→有界chirp、明确杂波→Clutter VarPro。简单映射消融以长窗STFT、原Dechirp替换两种复杂拟合，保留同样人工信息：独立失败{simple.failure_percent:.2f}% vs复杂{new.failure_percent:.2f}%；旧主分布{old_simple.failure_percent:.2f}% vs{old_new.failure_percent:.2f}%。不据此推广全部复杂拟合。

两个原型拟合原始实电压：`y=a*cos(phi)+b*sin(phi)+c+d*tau+epsilon`，线性参数SVD消去。稳定段`phi=2*pi*f*tau`；chirp段`phi=2*pi*(f*tau+alpha*tau²/2)`，搜索5 MHz–8 GHz、|alpha|≤8e16 Hz/s。边界只限定显式支持，不插值、不补点、不平滑。新控制与变体共享线性基线/门控；原方法保留冻结门控。

`f*T`很小时，正弦常数/线性项可被未知基线吸收，辨识依赖高阶曲率、初相及前端高通。0.75周期、增量R²≥0.2、条件数≤1e4是启发式门控，不是普适分辨极限或搜索后置信度。合成用`v_app=lambda*f/2`；真实波长/参考频移未核定，只报告Hz、校正速度NaN。

## 后续四个方向

1. **可观测性驱动的稳定段窗长/频率剖面。**匹配长窗STFT作门槛，加入前端高通标定、初相与频率多极值诊断。
2. **边界不确定性。**比较短窗、单侧窗和分段chirp，区分人工位置误差与窗口混合，不将GT时刻输入算法。
3. **现有Dechirp/VarPro按需计算和模型检查。**下降/回升复用方法，检查多起点、残差、相位重置；独立证据支持后才增加曲率。
4. **杂波持续性和支路身份。**保护前缀已有目标，比较减/不减杂波及多候选，用实验先验和后验预测检查补充波形拟合，消光仍保留缺失。
""")
    independent = overall[(overall.split == "independent") & (overall.kind == "supported")]
    old = overall[(overall.split != "independent") & (overall.kind == "supported")
                  & overall.method.isin(["current_map", "simple_stage_map", "stage_map", "stft768"])]
    all_pairs = pairs[(pairs.split == "independent") & (
        (pairs.region == "all") | ((pairs.region == "low_frequency") & pairs.baseline.isin(["clip_stft2048", "stft768"]))
        | ((pairs.region.isin(["acceleration", "decline"])) & pairs.baseline.isin(["clip_stft512", "dechirp"])))]
    failure = families[(families.split == "independent") & (families.kind == "supported")
                       & families.method.isin(["stft768", "stage_map", "clutter_varpro"])
                       & families.family.isin(["weak_spur", "drifting_spur", "crossing", "dropout",
                                               "target_in_prefix", "stable_plateau", "static_unobservable"])]
    onset = independent[["method", "onset_mae_ns", "onset_eligible", "onset_missed", "onset_early"]]
    st = sensitive[(sensitive.kind == "supported") & sensitive.method.isin(["bounded_chirp512", "stage_map"])]
    write("COMPARISON.md", f"""
# TASK-013 主要对比与失败情况

## 结论与正式数据版本

人工阶段、观测条件和窗长能改善本次组合成测试，但新增复杂拟合没有全面优势。最终建议以合理窗长、下降/回升复用Dechirp和明确条件下的Clutter VarPro为主；稳定低频可选剖面精修，有界chirp继续研究。所有效果限定到合成模型及人工标注，不推广为真实速度准确率。

正式结果是`runs/evaluation_v02`、`runs/sensitivity_v02`、`runs/cost_v03`、`statistics/final_v02`，真实观测仍为`runs/real_v02`。首轮evaluation_v01有12个开发/测试跨场景种子重用，完整保留为探索记录。独立性补充审计后使用81400000基点，全部开发36流/正式新测试144流不重叠；重跑全部290条，不删除碰撞案例，也不根据新结果调模型参数、门控或预设映射。旧报告归档在`checks/reports_v01`，不能当最终独立证据。

146条旧数据含TASK-008主分布96条和初相低速50条；新分布16族每族8条、低频族24条。290×13＝3770正式配置，所有候选/支持轨迹、输入波形、真值及人工方案保留，0执行异常。旧数据不能称未见过的新盲测。

## 评分与公平性

所有估计器仅收电压/时间和显式人工方案，真值只进计分。人工边界由场景时间表独立抖动±2 ns；这不是自动分段性能。截断控制共享同样边界；原STFT保持原始完整窗口，故对照须同时看匹配控制。原模型保持原门控，新方法和简单控制共享新门控；有限点RMSE不能单独证明提高。

“当前映射”指本研究的推荐逻辑对照，用冻结TASK-008 STFT768及其门控实现；未逐点重放TASK-012经典GUI完整检测/导出链，不能把表中数字称为现有GUI全处理链误差。成本同样是这些研究实现的计时。

共同比较是原样本1024+128k≤N−1024，每条85中心，不插值；边缘外不外推。主失败为NaN或|速度误差|>77.5 m/s，另给15及38.75 m/s严格失败。RMSE为有限点pooled值，覆盖/失败为逐波形宏平均；`statistics/common_support_v02.csv`给相同接受点RMSE，必须与完整分母表一起读。消光保留目标分母；纯噪声无RMSE；静止潜在零速的100%缺失同时体现不能制造测量值。

## 独立新测试：全部方法

{md_table(independent, common_columns + ['strict_15_percent'], common_labels + ['严格15 m/s失败 %'])}

纯噪声8条无目标；含目标分母有136条，包含8条潜在零速但无拍频记录。拒绝控制RMSE为空，不是完美精度。

## 旧分布与负结果

{md_table(old, ['split'] + common_columns + ['onset_mae_ns'], ['分布'] + common_labels + ['起跳MAE ns'])}

旧主分布当前→复杂预设支持RMSE和起跳MAE均恶化；不能用新组合上的收益掩盖。新映射的高覆盖与低RMSE取决于不同接受集合，要同时检查严格失败、完整目标分母和共同接受点。

## 阶段匹配与配对区间

{md_table(all_pairs, ['region','baseline','method','n_waveforms','failure_difference_pp','ci_low_pp','ci_high_pp'], ['阶段','基准','候选','波形n','失败差pp','95%下限','95%上限'])}

区间按配对波形bootstrap2000次，探索性、未做多重比较校正；重叠帧不是独立重复。低频Profile2048 RMSE{lp.rmse_m_s:.3f} m/s、覆盖{lp.coverage_percent:.2f}%、失败{lp.failure_percent:.2f}%；匹配长窗STFT为{ls.rmse_m_s:.3f} m/s、{ls.coverage_percent:.2f}%、{ls.failure_percent:.2f}%。覆盖改善主要来自长窗；不能把所有收益归于新拟合。完整阶段表还保留长窗在快变段大量拒绝的负结果。

## 简单映射消融

把Profile2048换成长窗STFT、有界chirp换成原Dechirp，其他人工信息/规则相同，复用所有已保存轨迹。该规则在首轮探索后提出，保守标为机制消融，不冒称原始预注册确认。

{md_table(ablation_pairs, ['split','baseline','method','failure_difference_pp','ci_low_pp','ci_high_pp'], ['分布','基准','候选','失败差pp','95%下限','95%上限'])}

复杂相对简单在独立分布失败差{delta:+.2f} pp，旧主分布{old_delta:+.2f} pp，支持条件性精修而非普遍增池。

## 典型失败

{md_table(failure, ['family'] + common_columns + ['wrong_branch_percent'], ['场景'] + common_labels + ['可区分双支路错误 %'])}

持续相干杂波的收益不能外推到漂移杂波；前缀已存在目标时，Clutter VarPro可能消除目标。交叉双分量即使高覆盖也不能保证身份正确。真实数据无物理GT，所以这些错误支路比例仅为合成生成标签下的结果。消光不补点、不以平滑曲线当测量。

未知基线下零频正弦不能自动辨识速度；近DC还依赖周期数、初相和前端高通。搜索下界5 MHz在合成1550 nm下对应3.875 m/s，命中下界不等于零速。表观/校正速度分离，未新增LiF修正式。

## 起跳误差与失败

指标是首次连续两帧支持值≥100 m/s相对GT首次越过100 m/s的误差，不是物理冲击到达时间，也不声称25 ps精度。原始能量起跳诊断另保存在逐案例JSON。

{md_table(onset, ['method','onset_mae_ns','onset_eligible','onset_missed','onset_early'], ['方法','成功检测者MAE ns','可评价事件','漏检','提前超过2 ns'])}

静止人工标签抑制前缀输出，因此早检减少含人工信息贡献；不能归于自动检测器。漏检者不从全分母失败中剔除。

## 标注敏感性

加速、下降、转折各4条，比较原方案、全边界±5 ns和错误斜率符号。真值只用于计分，坏结果全部保留，不估计真实人工误差分布。

{md_table(st, ['family','perturbation'] + common_columns, ['场景','标注扰动'] + common_labels)}

## 计算成本

8代表波形×13方法×3次，共312次独立串行运行，含初始化。其他实验计算停止后测量。主矩阵并行/共享初始化耗时不作为公平成本；分位范围是不同波形/重复的分布，不是精度置信区间。

{md_table(cost[cost.method != 'unobservable'], ['method','median_ms','p10_ms','p90_ms'], ['方法','中位耗时ms','10%分位ms','90%分位ms'])}

映射成本模拟当前软件“每种所需算法处理全记录，再按段取值”；尚未实现只计算局部区间。新增精修必须同时考虑收益与等待时间。

## 实测与实现核验

13份indexed raw/17路完整记录，221条观测保存在real_v02；阶段仅unknown，不从波形外观编造物理标签。报告Hz、覆盖和与STFT的分歧；未知波长/参考频移/支路身份时不报告速度准确率，校正速度NaN。

实测首轮暴露浮点时间searchsorted的中心选择问题，改为整数原样本索引。初轮580条合成STFT候选/支持逐值一致、最大差0 Hz，证据保留在`checks/integer_grid_parity.json`；正式v02使用同一整数实现，另有直接核心一致性测试。real_v01失败诊断、cost_v01中止记录和所有旧数值成果保留。

## 文献与解释边界

变量投影的线性/非线性参数分离来自Golub与Pereyra（1973，SIAM J. Numer. Anal.10(2),413–432，[DOI 10.1137/0710036](https://epubs.siam.org/doi/abs/10.1137/0710036)）；本研究阈值/支持窗是本地设计，文献不为其性能背书。Dolan（2010）的[原作者摘要与元数据](https://pubmed.ncbi.nlm.nih.gov/20515153/)支持PDV误差受采样、噪声与分析时长影响，不把FFT栅格当物理精度。

Allison等（2025，RSI96,085203，[作者预印本/正式DOI记录](https://arxiv.org/abs/2508.13695)，10.1063/5.0267409）提出直接时域Bayesian PDV并讨论模型失配和成本。本轮未实现/验证其完整方法，不把弱信号区间插值当测量，仅将多峰/后验预测检查列为后续方向。核验限于元数据和摘要，不冒充阅读全文。
""")
    # Figure meanings do not depend on scalar performance values.
    original = (OUT / "FIGURE_INDEX.md").read_text(encoding="utf-8")
    write("FIGURE_INDEX.md", original.replace("statistics/final/", "statistics/final_v02/")
          .replace("figures/final/", "figures/final_v02/"))
    checks = json.loads((folder / "checks.json").read_text(encoding="utf-8"))
    assert checks["unique_cases"] == 290 and checks["independent_cases"] == 144


if __name__ == "__main__":
    main()
