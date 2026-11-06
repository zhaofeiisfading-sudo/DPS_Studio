# 图件与图注

统一Times New Roman、封闭坐标轴、内刻度、色盲友好线色；PNG600 dpi，SVG文字可编辑。图中英文保证字形一致，中文解释见下。主统计来自`statistics/final_v02/`。不将重叠采样点当独立重复。

| 图件 | 内容与读取边界 |
| --- | --- |
| [01 阶段–算法矩阵](figures/final_v02/01_stage_algorithm_matrix.png) | 独立测试的各阶段宏平均含缺失失败率/有限覆盖率并排；静止潜在零速的100%缺失不是错误填零。 |
| [02 代表性速度与残差](figures/final_v02/02_representative_velocity_curves.png) | 预定第0号低频、加速、下降、平台案例；黑线仅为合成真值，缺失不连线。残差帮助辨认小于纵轴范围的差异。 |
| [03 失败案例](figures/final_v02/03_failure_cases.png) | 漂移杂波、交叉支路、消光、不可观测静止；覆盖高不等于支路正确，潜在零速线不代表测量。 |
| [04 最终推荐关系](figures/final_v02/04_stage_algorithm_recommendations.png) | 基于全部正/负结果的条件性使用建议，不是已推广的自动算法或GUI新默认。 |
| [05 配对失败与成本](figures/final_v02/05_paired_performance_and_cost.png) | 配对波形bootstrap95%区间，2000次、探索性未校正；成本为8记录×3串行运行的中位及10–90%分位，含初始化。 |
| [06 低频与起跳](figures/final_v02/06_low_frequency_and_onset.png) | 低频每速度6条、均值±SD；起跳每点一波形，漏检在图中计数。阈值时间不等价于物理冲击到达时间。 |

对应SVG与PNG同名。实际样本数、分母、失败、NaN和成本口径均在COMPARISON及CSV中保留。
