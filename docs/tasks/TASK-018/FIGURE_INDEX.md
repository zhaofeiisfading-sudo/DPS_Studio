# 图件索引

[主图册](../../../artifacts/TASK-018/gallery.html) · [完整复核版图册](../../../artifacts/TASK-018/gallery_reviewed.html)（可按文件/通道和冻结阶段筛选；各图都有 PNG 和 SVG）。复核版 168 组：14 路 A–E、88 张非起跳冻结段图、5 张汇总与候选审计图、5 张 G 案例。PNG 为 210 dpi；SVG 保留可编辑文字、标记、轴和曲线，密集热图作为嵌入栅格。

| 图组 | 内容 |
|---|---|
| A | 原始 Hann 1024 STFT；显示 Nyquist 全频带及共同频带。全记录时间轴，虚线是冻结边界。 |
| B | S0/S1/S2 同坐标共识图；颜色为投票评分，±50 MHz 显示宽度不参与选峰。 |
| C | 原始频谱叠加所有 S2 代表及备选；白叉标注高 S1 无 S。 |
| D | B0/B1/B2 与 S0/S1/S2 全记录轨迹和覆盖条；保留断点和孤立测量点，菱形表示竞争 S2 簇。 |
| E | 每路冻结起跳局部，原谱、C/G/S、S2 家族数及相对 B1 的增损。 |
| [F1](../../../artifacts/TASK-018/figures/v1/F1_all_channels.png) | 14 路全记录覆盖、增损、跳变和高共识警示。 |
| [F2](../../../artifacts/TASK-018/figures/v1/F2_stage_coverage.png) | 每路、每阶段的六种方法 S 覆盖；灰格无共同评价中心。 |
| [F3](../../../artifacts/TASK-018/figures/v1/F3_net_and_cost.png) | 逐阶段 S2 相对 B1 净增，以及逐通道运行时间。 |
| [F4](../../../artifacts/TASK-018/figures/v1/F4_stage_jumps_and_warnings.png) | 固定共同 S 相邻对的跳变，逐阶段高共识无 S。 |
| [候选互补性](../../../artifacts/TASK-018/figures/v1/candidate_complementarity.png) | 交集、独有簇，及 B1/B2 外的 S 和非 S 候选。 |

G 案例：[20201210m 去均值收益与融合无额外收益](../../../artifacts/TASK-018/figures/v1/G_20201210m_ch1.png)、[20201214m 带内低频瞬态](../../../artifacts/TASK-018/figures/v1/G_20201214m_ch1.png)、[ch3 起跳新增](../../../artifacts/TASK-018/figures/v1/G_ch3_ch1.png)、[ch3 快速变化时的受支持支路替换](../../../artifacts/TASK-018/figures/v1/G_branch_replacement_ch3_ch1_s03.png)、[短窗已表现良好的 20260630-2](../../../artifacts/TASK-018/figures/v1/G_20260630-2_ch1.png)。可对照 [20260630-1 原谱叠加](../../../artifacts/TASK-018/figures/v1/20260630-1_ch1__C_overlay.png) 看谐波与噪声段窄谱脊。

图中连线只连相邻输出；无 S 的 S2 频率为 NaN，未作平滑。局部卡保留冻结段前后少量原记录作为上下文；汇总仍严格按冻结分段。图册初版 D 另保留，复核版修正了折线图遇到孤立点不显标记的问题。
