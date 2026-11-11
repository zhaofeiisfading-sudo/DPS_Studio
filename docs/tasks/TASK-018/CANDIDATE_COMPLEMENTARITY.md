# 候选交集、并集和独有信息

从实际 raw 目录重新盘点：10 个 CSV/DAT、14 路，另有 `.gitkeep`；与 TASK-017 一致。TASK-009 的 13 文件、17 通道来自旧清单，另三个补充文件不在当前 `data/raw`。四个双通道文件按文件归组。TASK-017 的 28 配置全部读取汇总，B0/B1、Dechirp、VarPro、Clutter VarPro 和 Matrix Pencil 在本次原电压重跑后逐通道对照旧原生 C/G/调频率。低频 GLRT 与长窗改为全记录、无阶段裁窗的公平对照；不把 TASK-017 的阶段策略当成独立家族。

在 9,475 个完整共同中心，100 MHz 簇并集 27,775；交集（至少两家族）8,064（29.03%），其中一部分由共享种子或同一波形的共同失败产生。其余 19,711 个为单家族簇：

| 家族 | 独有簇 | 至少一条候选通过 S |
|---|---:|---:|
| STFT | 6,102 | 314 |
| Dechirp | 92 | 6 |
| VarPro（含 Clutter） | 64 | 7 |
| 低频 GLRT | 6,796 | 11 |
| 子空间 | 6,657 | 249 |

相对 B1/B2 都未在 100 MHz 内匹配的簇有 **15,411**；162 个（1.05%）含 S，其中 47 个与其它簇呈近 2:1 或 3:1，2 个接近频带下限。这些是诊断线索。未过 S 的 15,249 个中，4,481 个呈近谐波比、2,762 个靠近下限、9,321 个至少一个成员的前背景增益不足；这些条件可以重叠。162 个簇分布为起跳 5、平台 17、下降 24、回升 5、加速 7、弱信号 26、未知 60、静止 8、噪声 10。簇数含同中心多分支；例如有 17 个平台新簇，S2 相对 B1 却没有新增平台中心。

| 对照 | 两者均给出带内候选的中心 | 100 MHz 内至少一对 | 两者均未通过 S |
|---|---:|---:|---:|
| VarPro / Clutter VarPro | 5,909 | 5,909（100%） | 812 |
| Dechirp / VarPro | 5,875 | 5,704（97.09%） | 762 |

14 路均未找到通过 Clutter VarPro 前缀门槛的强相干干扰，故该包装本轮没有产生有效的新内核观测。Dechirp 和 VarPro 共享调频 FFT 初值；后者再拟合实电压。两者共同不通过 S 的比例为 12.97%，比在同一批共同 C 中用各自失败比例相乘的描述性参考高 11.24 个百分点。这个比较包含共同阶段、信号和重叠窗，不能据此估计物理错误相关性或作独立性检验。

互补性存在，主要来自少数短暂窗口及子空间的替代极点；大量新增低频或次峰没有波形支持。加入更多变体不能直接增加证据。文件级支持净增、候选来源及剔除家族后的结果见 [全量比较](REAL_COMPARISON.md) 和 [消融](FAILURE_ANALYSIS.md)。

[互补性图](../../../artifacts/TASK-018/figures/v1/candidate_complementarity.png) · [并集](../../../artifacts/TASK-018/data/audit_v1/candidate_union.csv) · [跨家族交集](../../../artifacts/TASK-018/data/audit_v1/cross_family_intersection.csv) · [家族独有](../../../artifacts/TASK-018/data/audit_v1/family_exclusive.csv) · [B1/B2 未匹配](../../../artifacts/TASK-018/data/audit_v1/strong_stft_unmatched.csv) · [配对重合和共同失败，逐通道阶段](../../../artifacts/TASK-018/data/audit_v1/paired_channel_stage.csv) · [TASK-017 28 配置复核](../../../artifacts/TASK-018/data/inputs_v1/task017_review.csv)
