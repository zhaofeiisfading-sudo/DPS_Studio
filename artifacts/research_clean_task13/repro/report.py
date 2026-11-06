"""Exploratory v01 reports. Final disjoint-seed delivery uses final_report.py."""
from __future__ import annotations

import json
from typing import Any

import pandas as pd  # type: ignore[import-untyped]

from .experiment import OUT


def md_table(frame: pd.DataFrame, columns: list[str], labels: list[str]) -> str:
    def cell(value: Any) -> str:
        if pd.isna(value):
            return "—"
        return f"{value:.2f}" if isinstance(value, float) else str(value)
    lines = ["| " + " | ".join(labels) + " |", "| " + " | ".join("---" for _ in labels) + " |"]
    lines += ["| " + " | ".join(cell(row[key]) for key in columns) + " |"
              for _, row in frame.iterrows()]
    return "\n".join(lines)


def text(name: str, value: str) -> None:
    with (OUT / name).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value.strip() + "\n")


def main() -> None:
    summary = OUT / "statistics/final"
    overall = pd.read_csv(summary / "overall.csv")
    families = pd.read_csv(summary / "family.csv")
    pairs = pd.read_csv(summary / "paired.csv")
    cost = pd.read_csv(summary / "cost.csv")
    sensitivity = pd.read_csv(summary / "annotation_sensitivity.csv")
    ablation = pd.read_csv(OUT / "statistics/routing_ablation_v01/overall.csv")
    ablation_pairs = pd.read_csv(OUT / "statistics/routing_ablation_v01/paired.csv")
    supported = overall[overall.kind == "supported"]
    independent = supported[supported.split == "independent"]
    main_table = ablation[(ablation.split == "independent") & (ablation.kind == "supported")
                         & ablation.method.isin(["current_map", "simple_stage_map", "stage_map"])]
    columns = ["method", "rmse_m_s", "coverage_percent", "failure_percent"]
    headings = ["方法", "支持RMSE m/s", "覆盖 %", "含缺失失败 %"]
    simple = md_table(main_table, columns, headings)
    text("README.md", f"""
# TASK-013｜分阶段算法适配与 Git 治理

2026-11-06；**研究完成。建议改进阶段信息与算法使用条件，保留现有算法池和正式默认值。**

**Git 已清理：**误提交 `b8faed27` 未进入远端研究分支。Research 已转为独立 `.git`，保留远端 `26066704` 为浅历史基点；本地发布包与旧成果保留。TASK-012 源码另行保存，release/数值产物不在待推送历史。精确 `.gitignore` 和本仓库 pre-commit 检查同时生效，未 push、未重写远端。[Git报告](GIT_CLEANUP.md)

**阶段需要分维度，算法数量无需普遍增加。**保留九个人工标签作为入口，区分运动形态、观测质量和杂波/边界条件。静止先验、低频可见、无可观测拍频分开；最低频率不是实测零速度。下降/回升也值得使用 Dechirp，不能只把“加速”映射到它。[推荐关系](STAGE_ALGORITHM_MAP.md)

290 条GT波形（146条旧分布＋144条独立新种子），13种方法/控制/映射，共3770条正式配置；另有明确标为事后分析的简单映射消融。独立测试如下，所有缺失保留在失败分母中：

{simple}

人工标注及±2 ns边界信息是上述收益的条件，不能解释为自动识别能力。新变体比简单映射只再降低0.58个百分点失败；在旧主分布反而增加1.94个百分点。旧主分布“当前→预设新映射”支持RMSE由8.15升至36.59 m/s、起跳MAE由7.72升至14.25 ns，不能全面替换。

**最值得保留的变体：**稳定低频的长窗频率剖面精修，低频组RMSE 0.274 m/s、覆盖92.89%；匹配长窗STFT为1.484 m/s、覆盖92.84%，两者失败率几乎相同。窗口长度贡献了主要覆盖收益。边界/符号约束chirp仅作为原型，既有Dechirp已解释大部分快变收益。

**负结果保留：**漂移杂波失败约82%；交叉双支路失败约78%、身份未解决；消光不填补；无拍频零速输出NaN。13份真实原始文件/17路只作Hz观测，不报告真实速度准确率。[完整比较](COMPARISON.md)

[六组科研图及图注](FIGURE_INDEX.md) · [冻结协议](PROTOCOL.md) · [验证及复现](VALIDATION.md)。125项相关pytest、Ruff、严格mypy通过；13份indexed raw、Research raw/release/src/configs、Production源码/配置/发布包/raw及完整.git内容校验一致。旧生成成果用名称/大小/mtime清单核验，未删除文件。
""")
    text("STAGE_ALGORITHM_MAP.md", r"""
# 阶段与算法推荐

## 分类结论

现有九个标签足以保留为人工入口，但作为单一互斥分类不够。“加速/平台”描述运动，“弱信号/噪声”描述观测，它们可以同时成立。推荐内部使用三个字段：`kinematics`、`observation`、`context`，暂不改变GUI或核心枚举。

- 运动：静止先验、起跳/突变、连续斜坡（记录正负）、平台、转折后回升、未知。
- 观测：低频可见、普通可见、弱信号、消光/无可观测拍频、噪声、身份未定。
- 上下文：人工边界及其不确定度、目标是否在前缀、杂波持续性、可用周期数、前端高通是否已标定。

下降和加速可共享带斜率的模型；回升保留转折位置后共享正斜率模型。弱信号/噪声宜成为覆盖运动标签的观测属性。静止必须区分“实验先验为零”“看见低频分量”“没有足够信息”；这三个状态不合并为零速。

| 现有阶段 | 条件推荐 | 简单控制/互补 | 必须保留的边界 |
| --- | --- | --- | --- |
| 静止 | 无可观测拍频→不估计；可见低频→长窗STFT，必要时Profile2048精修 | STFT768/1024、匹配长窗STFT | 先验零速独立记录，不写入测量列 |
| 起跳 | 短窗STFT/明确人工边界的单侧或截断窗作审计基准 | Dechirp/VarPro仅用于连续斜坡；同时显示未截断STFT | 本轮短窗不是全部起跳案例的赢家；边界抖动、漏检、提前检出另报 |
| 加速 | 已可见连续分量优先Dechirp；难例局部VarPro精修 | 零斜率Profile512、截断STFT512 | 大加速度、相位重置、双分量会失配；Bounded chirp是研究原型 |
| 平台 | STFT768/1024；稳定内部可选长窗和Profile2048 | 长窗STFT2048与Profile512分离窗长/拟合收益 | 混合平台组中Profile2048未全面超过STFT768；靠近边界不盲目用长窗 |
| 下降 | 连续减速优先Dechirp，必要时VarPro | 原STFT与零斜率控制 | 本轮下降段Dechirp失败0%，新约束chirp同为0%，不必再增加正式算法 |
| 回升 | 转折附近审查短窗；连续回升段Dechirp | VarPro/局部有界chirp作精修 | 非负拍频不能独立给出真实运动方向；转折标签不等于整个区间一个模型 |
| 弱信号 | 近稳态用长窗STFT；确认持续相干杂波且前缀无目标时用Clutter VarPro | 对比原始电压及未减杂波VarPro | 漂移杂波、本来就在前缀的目标会失败；消光NaN |
| 噪声 | 不估计（NaN＋原因） | 保留候选诊断，禁止最低频率填零 | 信号与噪声的质量门限是启发式，尚非标定置信度 |
| 未知 | STFT基准并保留人工选择；身份不明可保留多候选/不估计 | 查看多窗及局部模型残差 | 不用平滑曲线或拟合R²确认支路 |

## 算法池结论与映射证据

现有五项池作为框架足够。优先补充**参数、支持窗和质量诊断**，不建议把每个阶段注册成一个新算法。Profile2048值得作为稳定段可选精修；Bounded chirp512保留研究代码，尚不支持普遍进入正式池。推荐关系图是条件性使用建议，正式实验中的`stage_map`是预先固定的受检策略，二者不要混称为已验证的自动默认。

当前映射基准取`acceleration→Dechirp, noise→NaN, other→STFT768`，STFT768是本比较明确选择的配置，不声称它就是所有用户当前设置。预设研究映射增加可见低频/平台→Profile2048、连续下降/回升→有界chirp、明确杂波→Clutter VarPro。后验简单映射把前两种新拟合替换为长窗STFT和原Dechirp，保留相同人工信息：独立失败率20.10% vs新映射19.52%；旧主分布简单映射11.79% vs新映射13.73%。因此下一轮应优先验证简单映射和边界不确定性，而不是增加算法名称。

## 数学方法与可观测性

两个原型都拟合原始实电压，`y=a*cos(phi)+b*sin(phi)+c+d*tau+epsilon`，线性参数用SVD最小二乘消去。稳定段`phi=2*pi*f*tau`；chirp段`phi=2*pi*(f*tau+alpha*tau^2/2)`，搜索`f=5 MHz–8 GHz`、`|alpha|≤8e16 Hz/s`，下降/回升可由人工标签约束符号。人工边界只截取显式支持，没有补点、拼接或平滑。新控制与变体共享DC/线性基线和门控；原方法保持自己的冻结门控。

当`f*T`很小时，正弦的常数项及线性项可被未知基线吸收，辨识依赖高阶曲率及初相。高通还会按前端传递函数衰减低频。`0.75周期、R²≥0.2、条件数≤1e4`是本次启发式拒绝规则，并非普适分辨极限。无拍频、搜索下界和低频可观测是不同概念。合成`v_app=lambda*f/2`；真实波长/参考频移/方向未核定，本轮实测只保存Hz，校正速度为NaN。

## 建议继续的四个方向

1. **可观测性驱动的稳定段窗长和剖面拟合。**匹配长窗STFT作对照，加入前端高通标定、初相和多个频率极小值诊断；不输出未标定的“搜索后置信度”。
2. **带不确定区间的边界估计。**区分人工位置误差与窗口混合，比较短窗、单侧窗、分段chirp；不要把GT时刻作为算法输入，也不把人工边界收益算作自动起跳能力。
3. **现有Dechirp/VarPro的按需计算与模型检查。**下降/回升复用既有方法，测试多起点、残差和相位重置；只在有独立验证收益时增加曲率参数。
4. **杂波持续性和多支路身份。**保护前缀已存在的目标，比较减杂波/不减杂波及多分量候选；结合实验先验与后验预测检查，消光仍保留缺失。
""")
    independent_table = md_table(independent.sort_values("method"), columns + ["strict_15_percent"],
                                 headings + ["严格15 m/s失败 %"])
    old = supported[supported.method.isin(["current_map", "stage_map", "stft768"])]
    old = old[old.split != "independent"]
    old_table = md_table(old, ["split"] + columns + ["onset_mae_ns"],
                         ["分布"] + headings + ["起跳MAE ns"])
    paired_subset = pairs[(pairs.split == "independent") & (
        (pairs.region == "all") | ((pairs.region == "low_frequency") &
        pairs.baseline.isin(["clip_stft2048", "stft768"])) |
        ((pairs.region.isin(["acceleration", "decline"])) &
         pairs.baseline.isin(["dechirp", "clip_stft512"])))]
    paired_table = md_table(paired_subset, ["region", "baseline", "method", "n_waveforms",
                            "failure_difference_pp", "ci_low_pp", "ci_high_pp"],
                            ["阶段", "基准", "候选", "波形n", "失败差pp", "95%下限", "95%上限"])
    failures = families[(families.split == "independent") & (families.kind == "supported")
                        & families.method.isin(["stft768", "stage_map"])
                        & families.family.isin(["weak_spur", "drifting_spur", "crossing", "dropout",
                                               "target_in_prefix", "stable_plateau", "static_unobservable"])]
    failure_table = md_table(failures, ["family"] + columns + ["wrong_branch_percent"],
                            ["场景"] + headings + ["可区分双支路错误 %"])
    sens = sensitivity[(sensitivity.kind == "supported") &
                       sensitivity.method.isin(["bounded_chirp512", "stage_map"])]
    sensitivity_table = md_table(sens, ["family", "perturbation"] + columns,
                                ["场景", "标注扰动"] + headings)
    cost_table = md_table(cost[cost.method != "unobservable"], ["method", "median_ms", "p10_ms", "p90_ms"],
                          ["方法", "中位耗时ms", "10%分位ms", "90%分位ms"])
    ablation_table = md_table(ablation_pairs, ["split", "baseline", "method", "failure_difference_pp",
                               "ci_low_pp", "ci_high_pp"], ["分布", "基准", "候选", "失败差pp", "95%下限", "95%上限"])
    text("COMPARISON.md", f"""
# TASK-013 主要对比与失败情况

## 结论范围

人工阶段和观测条件能提高本组合成测试的重建表现，但不支持自动推荐替换全部既有默认。新增复杂拟合的收益小于合理窗长、持续杂波处理和现有Dechirp的阶段适配。低频稳定段可选精修值得保留，通用chirp新名称暂不进入正式算法池。所有数字来自实际运行的文件，解释性建议与实验结果分开。

## 数据、信息与公平性

146条TASK-008冻结波形（96主分布＋50低速初相）用于重复分布；独立新生成144条，另36条开发波形不混入正式统计。16个新增族每族8条，低频平台24条。原始波形、真值、人工方案、完整候选/支持轨迹和逐案例表均在`runs/evaluation_v01/cases/`。290×13＝3770条正式方法配置，无执行异常，无按结果删案例。

人工时间表独立抖动±2 ns，是输入信息；所有新截断对照共享它。阶段评分按未抖动的生成时刻，估计器不接收真值数组。原STFT512/768是未去DC的正式核心，候选逐值测试通过。原模型保持冻结门控；新模型与简单控制共享基线和门控，门控不同于原池，不能只比较接受后的RMSE。

共同比较时刻为原始样本1024+128k≤N−1024，每条12800点波形85个中心，边缘之外不外推。主失败为NaN或绝对速度误差>77.5 m/s；另报告15/38.75 m/s严格失败。支持RMSE为有限点pooled值，覆盖/失败为逐波形宏平均；`statistics/common_support_v01.csv`另给完全相同接受点的描述性RMSE。消光仍计入目标分母。纯噪声无速度RMSE；潜在零速但不可观测的8条记录有100%重建缺失，同时正确保留“不测得零”的语义。

## 独立新分布：全部方法

{independent_table}

`unobservable`仅是拒绝控制，RMSE空白绝不表示完美精度。物理不可观测零速记录也计入总体目标分母；纯噪声8条无目标，总体有效目标波形136条。

## 原分布负结果

{old_table}

当前映射的原主分布RMSE明显低于预设新映射；新映射增加了一些输出/失败模式，严格15 m/s失败也由18.41%升至19.10%。不能拿独立组合上的改善覆盖这项负结果。原主分布新映射与当前映射的含缺失失败只差约−0.61 pp，强结论不成立；原低速压力的覆盖收益较明确，但误差和起跳不全面改善。

## 阶段与匹配控制

{paired_table}

95%区间按配对波形bootstrap2000次，未做多重比较校正，属于探索性。重叠帧不是独立重复。独立低频组Profile2048为RMSE0.274 m/s、覆盖92.89%、失败7.11%；长窗STFT为1.484 m/s、92.84%、7.16%。**覆盖收益主要来自长窗，剖面拟合主要改善精度；两者失败差区间触零。**混合平台组Profile2048 RMSE1.473 m/s，STFT768为1.350 m/s，因此不能把纯稳定平台的收益泛化到含边界误差的平台。

下降段Dechirp与新有界chirp均为100%覆盖、0%失败，RMSE分别3.940/4.210 m/s；该段新算法无必要。加速段有界chirp相对Dechirp失败差−1.876 pp，仍混有边界支持和人工符号先验差异，不能全部归于非线性优化。相对零斜率Profile512的对照另存完整配对表。低RMSE但拒绝绝大部分困难点的长窗结果不算全面提高，例如下降段长窗剖面仅约1.58%覆盖。

## 简单映射消融（事后，不是独立确认）

将预设新映射的Profile2048换成长窗STFT、将有界chirp换成原Dechirp，其余人工信息/规则保留。使用所有已保存轨迹重新路由，未重新搜索算法或挑选成功案例。

{ablation_table}

新分布中复杂映射比简单映射少0.58 pp失败，旧主分布多1.94 pp、旧低速压力多0.41 pp。因此最终建议以简单适配和质量诊断为主，两个变体作为有条件精修；本消融使用已经查看过的评估分布，不能称新增盲测。

## 典型失败与可观测性

{failure_table}

相干固定杂波的收益不能外推到漂移杂波；后者新映射失败81.93%、可分辨时错误支路97.34%。交叉双分量新映射失败78.27%、错误支路87.85%，高覆盖并未解决目标身份。目标已在前缀时，Clutter VarPro覆盖31.76%、失败68.24%；强制减去前缀谱线有删除目标的风险。所有这些是合成已知标签下的测试，真实数据没有可用的错误支路真值。

零频正弦在未知DC/基线下不能自动辨识速度，近DC分量也受支撑周期、初相和前端高通影响。本轮静止/纯噪声没有测得零的平台，也没有通过平滑或补点填消光。搜索下界5 MHz对应合成等效速度3.875 m/s，不能把下界命中解释为零速。

## 起跳

起跳指标为**首次连续两帧支持值≥100 m/s**相对GT首次100 m/s越过的偏差，并不声称物理冲击到达时间或25 ps精度。低速爬升的阈值越过可以晚于物理起跳；原始能量检测的物理起跳诊断另保存在每条JSON。独立新分布有96条可评价阈值事件，当前映射/预设新映射MAE10.715/4.256 ns、漏检0/0、提前超过2 ns的记录22/0；后者使用静止人工标签屏蔽了前缀，必须计为人工信息收益。Dechirp漏检18条，不把成功者MAE单独当整体精度。

## 标注敏感性

独立选取加速、下降、转折各4条，分别使用原方案、全边界±5 ns、错误斜率符号；真值只用于事后计分。下表包括坏结果，不改主实验阈值：

{sensitivity_table}

该检查测量依赖人工信息的程度，不给出真实标注误差的分布估计。错误符号可以让有界模型排除真实解；所以符号约束不能仅从“看起来属于某阶段”无条件强制。

## 计算成本

8条预先列出的代表波形，单进程、每方法3次独立串行运行，包含初始化；主矩阵的共享初始化/并行时间不作为公平成本。最终成本为`runs/cost_v02/measurements.csv`，`cost_v01`因有其他实验同时活动被中止，不进入统计。分位区间表达不同波形/运行的成本分布，不是精度CI。

{cost_table}

映射成本采用当前软件的“每种所需算法处理全记录、再按段取值”方式；尚未做只算局部区间的性能优化。新增精修必须同时评估收益和等待时间。

## 真实观测

按TASK-009 owning index读取13份原始文件、17路完整记录，221条方法/控制/映射观测均已保存。阶段设为unknown，未从外观编造真实阶段标签；只输出Hz、候选/支持、覆盖及与STFT768的分歧，`runs/real_v02/diagnostics.csv`不能解释为真实准确率。真实波长、参考频移和物理支路身份未校验，校正速度独立NaN。

真实绝对时间暴露浮点searchsorted可能错选相邻STFT中心，改为原始整数样本索引。修复后全部580条合成STFT候选/支持轨迹与主实验逐值完全一致，见`checks/integer_grid_parity.json`；`real_v01`保留为失败诊断，最终使用real_v02。

## 方法依据与未来研究

变量投影的线性/非线性参数分离依据是Golub与Pereyra的原始论文（1973，SIAM J. Numer. Anal.10(2),413–432，[DOI 10.1137/0710036](https://epubs.siam.org/doi/abs/10.1137/0710036)）；本轮具体支持窗/拒绝阈值是研究设计，文献不为其性能背书。Dolan（2010）的[原作者摘要及元数据](https://pubmed.ncbi.nlm.nih.gov/20515153/)确认PDV误差与采样、噪声及分析时长有关；未把FFT栅格间距当成物理精度。

Allison等（2025，RSI96,085203，[作者预印本及正式DOI记录](https://arxiv.org/abs/2508.13695)，正式DOI10.1063/5.0267409）提出直接时域Bayesian PDV，并指出模型失配和计算成本。本轮未实现或验证该完整方法，不采用它跨弱信号区间的插值作为测量；仅把多峰/后验预测检查列为后续方向。文献核验范围是上述元数据与摘要，不冒充阅读全文。四条具体优化方向见[阶段算法表](STAGE_ALGORITHM_MAP.md)。
""")
    text("FIGURE_INDEX.md", """
# 图件与图注

统一Times New Roman、封闭坐标轴、内刻度、色盲友好线色；PNG600 dpi，SVG文字可编辑。图中英文保证字形一致，中文解释见下。主统计来自`statistics/final/`。不将重叠采样点当独立重复。

| 图件 | 内容与读取边界 |
| --- | --- |
| [01 阶段–算法矩阵](figures/final/01_stage_algorithm_matrix.png) | 独立测试的各阶段宏平均含缺失失败率/有限覆盖率并排；静止潜在零速的100%缺失不是错误填零。 |
| [02 代表性速度与残差](figures/final/02_representative_velocity_curves.png) | 预定第0号低频、加速、下降、平台案例；黑线仅为合成真值，缺失不连线。残差帮助辨认小于纵轴范围的差异。 |
| [03 失败案例](figures/final/03_failure_cases.png) | 漂移杂波、交叉支路、消光、不可观测静止；覆盖高不等于支路正确，潜在零速线不代表测量。 |
| [04 最终推荐关系](figures/final/04_stage_algorithm_recommendations.png) | 基于全部正/负结果的条件性使用建议，不是已推广的自动算法或GUI新默认。 |
| [05 配对失败与成本](figures/final/05_paired_performance_and_cost.png) | 配对波形bootstrap95%区间，2000次、探索性未校正；成本为8记录×3串行运行的中位及10–90%分位，含初始化。 |
| [06 低频与起跳](figures/final/06_low_frequency_and_onset.png) | 低频每速度6条、均值±SD；起跳每点一波形，漏检在图中计数。阈值时间不等价于物理冲击到达时间。 |

对应SVG与PNG同名。实际样本数、分母、失败、NaN和成本口径均在COMPARISON及CSV中保留。
""")
    # Retain small machine-readable report checks, without rewriting old runs.
    checks = json.loads((summary / "checks.json").read_text(encoding="utf-8"))
    assert checks["unique_cases"] == 290 and checks["independent_cases"] == 144


if __name__ == "__main__":
    main()
