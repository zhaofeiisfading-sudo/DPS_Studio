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

| 方法 | 支持RMSE m/s | 覆盖 % | 含缺失失败 % | 严格15 m/s失败 % |
| --- | --- | --- | --- | --- |
| bounded_chirp512 | 177.34 | 82.76 | 31.54 | 35.45 |
| clip_stft2048 | 151.62 | 74.24 | 35.95 | 38.24 |
| clip_stft512 | 180.59 | 81.50 | 33.78 | 39.62 |
| clutter_varpro | 169.77 | 72.30 | 38.33 | 42.78 |
| current_map | 179.16 | 81.72 | 33.16 | 36.95 |
| dechirp | 148.38 | 54.74 | 50.50 | 54.74 |
| profile2048 | 148.01 | 77.17 | 33.04 | 37.06 |
| profile512 | 179.27 | 82.73 | 32.75 | 37.39 |
| stage_map | 148.75 | 89.56 | 20.45 | 22.72 |
| stft512 | 190.26 | 60.83 | 52.10 | 56.33 |
| stft768 | 180.54 | 80.44 | 34.47 | 38.06 |
| unobservable | — | 0.00 | 100.00 | 100.00 |
| varpro | 148.19 | 54.79 | 50.47 | 53.91 |

纯噪声8条无目标；含目标分母有136条，包含8条潜在零速但无拍频记录。拒绝控制RMSE为空，不是完美精度。

## 旧分布与负结果

| 分布 | 方法 | 支持RMSE m/s | 覆盖 % | 含缺失失败 % | 起跳MAE ns |
| --- | --- | --- | --- | --- | --- |
| legacy_fresh | current_map | 8.15 | 85.80 | 14.34 | 7.72 |
| legacy_fresh | stage_map | 36.59 | 87.96 | 13.73 | 14.25 |
| legacy_fresh | stft768 | 120.04 | 92.94 | 14.82 | 8.77 |
| legacy_phase_stress | current_map | 2.53 | 49.92 | 50.08 | 18.98 |
| legacy_phase_stress | stage_map | 3.36 | 91.59 | 8.43 | 13.83 |
| legacy_phase_stress | stft768 | 2.53 | 49.92 | 50.08 | 18.98 |

旧主分布当前→复杂预设支持RMSE和起跳MAE均恶化；不能用新组合上的收益掩盖。新映射的高覆盖与低RMSE取决于不同接受集合，要同时检查严格失败、完整目标分母和共同接受点。

## 阶段匹配与配对区间

| 阶段 | 基准 | 候选 | 波形n | 失败差pp | 95%下限 | 95%上限 |
| --- | --- | --- | --- | --- | --- | --- |
| all | current_map | stage_map | 136 | -12.71 | -17.83 | -8.12 |
| all | stft768 | stage_map | 136 | -14.03 | -19.09 | -9.44 |
| acceleration | clip_stft512 | bounded_chirp512 | 40 | -20.54 | -32.42 | -9.80 |
| acceleration | dechirp | bounded_chirp512 | 40 | -2.06 | -3.19 | -1.03 |
| decline | clip_stft512 | bounded_chirp512 | 16 | -49.43 | -74.43 | -25.00 |
| decline | dechirp | bounded_chirp512 | 16 | 0.00 | 0.00 | 0.00 |
| low_frequency | clip_stft2048 | profile2048 | 24 | 0.10 | 0.00 | 0.29 |
| low_frequency | stft768 | profile2048 | 24 | -43.87 | -61.57 | -28.67 |

区间按配对波形bootstrap2000次，探索性、未做多重比较校正；重叠帧不是独立重复。低频Profile2048 RMSE0.252 m/s、覆盖92.70%、失败7.30%；匹配长窗STFT为1.480 m/s、92.79%、7.21%。覆盖改善主要来自长窗；不能把所有收益归于新拟合。完整阶段表还保留长窗在快变段大量拒绝的负结果。

## 简单映射消融

把Profile2048换成长窗STFT、有界chirp换成原Dechirp，其他人工信息/规则相同，复用所有已保存轨迹。该规则在首轮探索后提出，保守标为机制消融，不冒称原始预注册确认。

| 分布 | 基准 | 候选 | 失败差pp | 95%下限 | 95%上限 |
| --- | --- | --- | --- | --- | --- |
| independent | simple_stage_map | stage_map | -0.59 | -0.96 | -0.26 |
| independent | simple_stage_map | current_map | 12.12 | 7.53 | 17.25 |
| legacy_fresh | simple_stage_map | stage_map | 1.93 | 1.06 | 2.84 |
| legacy_fresh | simple_stage_map | current_map | 2.55 | -4.48 | 10.11 |
| legacy_phase_stress | simple_stage_map | stage_map | 0.41 | 0.05 | 0.81 |
| legacy_phase_stress | simple_stage_map | current_map | 42.05 | 31.57 | 52.41 |

复杂相对简单在独立分布失败差-0.59 pp，旧主分布+1.93 pp，支持条件性精修而非普遍增池。

## 典型失败

| 场景 | 方法 | 支持RMSE m/s | 覆盖 % | 含缺失失败 % | 可区分双支路错误 % |
| --- | --- | --- | --- | --- | --- |
| crossing | clutter_varpro | 451.01 | 100.00 | 86.82 | 96.89 |
| crossing | stage_map | 440.56 | 99.83 | 77.36 | 87.72 |
| crossing | stft768 | 447.48 | 97.47 | 90.03 | 97.58 |
| drifting_spur | clutter_varpro | 357.51 | 99.32 | 81.50 | 96.80 |
| drifting_spur | stage_map | 358.12 | 98.98 | 81.84 | 96.44 |
| drifting_spur | stft768 | 339.56 | 100.00 | 81.33 | 100.00 |
| dropout | clutter_varpro | 3.88 | 80.50 | 19.50 | — |
| dropout | stage_map | 4.63 | 76.60 | 23.40 | — |
| dropout | stft768 | 0.60 | 68.47 | 31.53 | — |
| stable_plateau | clutter_varpro | 1.47 | 87.33 | 12.67 | — |
| stable_plateau | stage_map | 0.66 | 99.83 | 0.17 | — |
| stable_plateau | stft768 | 0.81 | 100.00 | 0.00 | — |
| static_unobservable | clutter_varpro | — | 0.00 | 100.00 | — |
| static_unobservable | stage_map | — | 0.00 | 100.00 | — |
| static_unobservable | stft768 | — | 0.00 | 100.00 | — |
| target_in_prefix | clutter_varpro | 5.27 | 15.59 | 84.41 | — |
| target_in_prefix | stage_map | 0.05 | 100.00 | 0.00 | — |
| target_in_prefix | stft768 | 0.38 | 100.00 | 0.00 | — |
| weak_spur | clutter_varpro | 192.93 | 76.35 | 34.29 | 11.31 |
| weak_spur | stage_map | 193.36 | 76.01 | 34.63 | 11.31 |
| weak_spur | stft768 | 383.19 | 100.00 | 84.29 | 100.00 |

持续相干杂波的收益不能外推到漂移杂波；前缀已存在目标时，Clutter VarPro可能消除目标。交叉双分量即使高覆盖也不能保证身份正确。真实数据无物理GT，所以这些错误支路比例仅为合成生成标签下的结果。消光不补点、不以平滑曲线当测量。

未知基线下零频正弦不能自动辨识速度；近DC还依赖周期数、初相和前端高通。搜索下界5 MHz在合成1550 nm下对应3.875 m/s，命中下界不等于零速。表观/校正速度分离，未新增LiF修正式。

## 起跳误差与失败

指标是首次连续两帧支持值≥100 m/s相对GT首次越过100 m/s的误差，不是物理冲击到达时间，也不声称25 ps精度。原始能量起跳诊断另保存在逐案例JSON。

| 方法 | 成功检测者MAE ns | 可评价事件 | 漏检 | 提前超过2 ns |
| --- | --- | --- | --- | --- |
| bounded_chirp512 | 9.18 | 96 | 0 | 20 |
| clip_stft2048 | 8.90 | 96 | 0 | 16 |
| clip_stft512 | 8.33 | 96 | 0 | 18 |
| clutter_varpro | 12.85 | 96 | 3 | 8 |
| current_map | 10.68 | 96 | 0 | 22 |
| dechirp | 10.85 | 96 | 18 | 1 |
| profile2048 | 8.24 | 96 | 0 | 16 |
| profile512 | 8.01 | 96 | 0 | 20 |
| stage_map | 4.70 | 96 | 1 | 0 |
| stft512 | 16.81 | 96 | 18 | 22 |
| stft768 | 11.51 | 96 | 0 | 22 |
| unobservable | — | 96 | 96 | 0 |
| varpro | 10.66 | 96 | 18 | 0 |

静止人工标签抑制前缀输出，因此早检减少含人工信息贡献；不能归于自动检测器。漏检者不从全分母失败中剔除。

## 标注敏感性

加速、下降、转折各4条，比较原方案、全边界±5 ns和错误斜率符号。真值只用于计分，坏结果全部保留，不估计真实人工误差分布。

| 场景 | 标注扰动 | 方法 | 支持RMSE m/s | 覆盖 % | 含缺失失败 % |
| --- | --- | --- | --- | --- | --- |
| fast_accel | base | bounded_chirp512 | 1.36 | 99.66 | 0.34 |
| fast_accel | base | stage_map | 16.68 | 99.32 | 2.03 |
| fast_decel | base | bounded_chirp512 | 1.24 | 98.31 | 1.69 |
| fast_decel | base | stage_map | 0.46 | 98.99 | 1.01 |
| turnaround | base | bounded_chirp512 | 5.30 | 98.99 | 1.01 |
| turnaround | base | stage_map | 8.72 | 98.99 | 1.01 |
| fast_accel | boundaries_minus5ns | bounded_chirp512 | 3.71 | 98.31 | 1.69 |
| fast_accel | boundaries_minus5ns | stage_map | 16.13 | 99.32 | 2.03 |
| fast_decel | boundaries_minus5ns | bounded_chirp512 | 6.10 | 99.32 | 0.68 |
| fast_decel | boundaries_minus5ns | stage_map | 22.80 | 100.00 | 2.36 |
| turnaround | boundaries_minus5ns | bounded_chirp512 | 9.15 | 100.00 | 0.34 |
| turnaround | boundaries_minus5ns | stage_map | 15.46 | 99.66 | 0.68 |
| fast_accel | boundaries_plus5ns | bounded_chirp512 | 4.04 | 97.64 | 2.36 |
| fast_accel | boundaries_plus5ns | stage_map | 15.47 | 97.30 | 4.73 |
| fast_decel | boundaries_plus5ns | bounded_chirp512 | 5.45 | 98.31 | 1.69 |
| fast_decel | boundaries_plus5ns | stage_map | 24.26 | 96.28 | 5.07 |
| turnaround | boundaries_plus5ns | bounded_chirp512 | 4.44 | 100.00 | 0.00 |
| turnaround | boundaries_plus5ns | stage_map | 15.81 | 96.96 | 4.73 |
| fast_accel | wrong_slope_sign | bounded_chirp512 | 20.62 | 91.89 | 10.47 |
| fast_accel | wrong_slope_sign | stage_map | 26.96 | 91.55 | 12.16 |
| fast_decel | wrong_slope_sign | bounded_chirp512 | 26.39 | 87.50 | 16.22 |
| fast_decel | wrong_slope_sign | stage_map | 26.26 | 88.18 | 15.54 |
| turnaround | wrong_slope_sign | bounded_chirp512 | 26.84 | 98.31 | 3.72 |
| turnaround | wrong_slope_sign | stage_map | 27.73 | 98.31 | 3.72 |

## 计算成本

8代表波形×13方法×3次，共312次独立串行运行，含初始化。其他实验计算停止后测量。主矩阵并行/共享初始化耗时不作为公平成本；分位范围是不同波形/重复的分布，不是精度置信区间。

| 方法 | 中位耗时ms | 10%分位ms | 90%分位ms |
| --- | --- | --- | --- |
| bounded_chirp512 | 1031.60 | 958.62 | 1114.86 |
| clip_stft2048 | 80.22 | 75.70 | 98.37 |
| clip_stft512 | 62.43 | 57.63 | 70.21 |
| clutter_varpro | 341.92 | 42.57 | 699.42 |
| current_map | 40.09 | 10.15 | 147.78 |
| dechirp | 23.82 | 19.75 | 163.95 |
| profile2048 | 516.89 | 467.68 | 592.40 |
| profile512 | 332.31 | 282.65 | 375.32 |
| stage_map | 585.08 | 13.18 | 1674.34 |
| stft512 | 35.90 | 27.48 | 47.35 |
| stft768 | 39.07 | 29.24 | 41.28 |
| varpro | 23.35 | 20.13 | 652.61 |

映射成本模拟当前软件“每种所需算法处理全记录，再按段取值”；尚未实现只计算局部区间。新增精修必须同时考虑收益与等待时间。

## 实测与实现核验

13份indexed raw/17路完整记录，221条观测保存在real_v02；阶段仅unknown，不从波形外观编造物理标签。报告Hz、覆盖和与STFT的分歧；未知波长/参考频移/支路身份时不报告速度准确率，校正速度NaN。

实测首轮暴露浮点时间searchsorted的中心选择问题，改为整数原样本索引。初轮580条合成STFT候选/支持逐值一致、最大差0 Hz，证据保留在`checks/integer_grid_parity.json`；正式v02使用同一整数实现，另有直接核心一致性测试。real_v01失败诊断、cost_v01中止记录和所有旧数值成果保留。

## 文献与解释边界

变量投影的线性/非线性参数分离来自Golub与Pereyra（1973，SIAM J. Numer. Anal.10(2),413–432，[DOI 10.1137/0710036](https://epubs.siam.org/doi/abs/10.1137/0710036)）；本研究阈值/支持窗是本地设计，文献不为其性能背书。Dolan（2010）的[原作者摘要与元数据](https://pubmed.ncbi.nlm.nih.gov/20515153/)支持PDV误差受采样、噪声与分析时长影响，不把FFT栅格当物理精度。

Allison等（2025，RSI96,085203，[作者预印本/正式DOI记录](https://arxiv.org/abs/2508.13695)，10.1063/5.0267409）提出直接时域Bayesian PDV并讨论模型失配和成本。本轮未实现/验证其完整方法，不把弱信号区间插值当测量，仅将多峰/后验预测检查列为后续方向。核验限于元数据和摘要，不冒充阅读全文。
