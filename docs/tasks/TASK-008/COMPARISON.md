# TASK-008｜PDV 算法完整比较与研究结论

研究实验与报告完成；停留在 Research。14 个方法/对照均运行了 **13 个真正原始文件、17 条电压通道**，另完成 96 条新种子主合成测试和 50 条低速随机初相压力测试，共 2282 个正式方法流，执行异常为 0。12 个探索方法先冻结；随后追加两种历史 M0 契约对照，不改变探索参数。开发轮失败另外保留，没有混入最终统计。

有条件的最明确新增收益来自“相干杂散预测＋VarPro”：主分布支持后全分母失败率 8.70%，原 768 点 STFT 为 13.64%，去 DC＋截断 512 点控制为 17.79%。**相对原 768 的配对区间跨零，不能宣布全面胜出。** 低速极限、弱信号漏检、双分量身份与前端未知传递函数仍未解决。


## 🧪 样本、测量契约与历史依据

实际递归发现 24 个文件：13 个原始时间–电压文件，5 个文件名标记 result 的处理结果，5 张参考图片与 1 个占位文件。全部文件均纳入 SHA-256 边界检查；只对 13 个原波形的全部 17 个电压列估计。四个双列 CSV 的通道和独立命名的 ch1/ch2/ch3/ch4 文件不作独立实验次数推断。两条 DAT 为约 80 GS/s，其余约 40 GS/s，均直接使用真实时间轴，无重采样。无单位表头；时间/电压按已有 acquisition reader 配置为 s/V，新加入的独立通道文件沿用同一格式假设，并保留标定未核验标签。

当前源码、Git 和实际运行优先于旧报告。已读取 TASK-026/027/028 的实际报告与前端源码，以及 clean_task4/4A/4B/5/7 的研究结果：表示层重分配、候选路径/IMM/MHT/Rescue、固定 FIR 或 PSD Whitening 不能自动转化为新的原始波形信息。本轮不重新调 Global Path/P3 权重，也不把历史半自动种子收益算给新算法。历史资料仅帮助选择路线，没有将旧分布合并进本轮 RMSE。

Research 分支 `codex/research_2/global-path-ridge`，HEAD `1b88f6ba97b4edda61268a88150aacc6f14d2796`。任务开始已有 12375 条 tracked 删除和 40 项 untracked 状态（含本任务初始目录），全部保留；Production 起始为 clean。原始前后证据见 `boundary_before.json`、`boundary_after.json` 和 `checks/final_boundary_check.json`。

开发使用 48 条独立波形，三轮共 792 个方法流；development00/02 重用每族第 0 条，不把 72 次生成算为 72 条独立波形。初版因低频/DC 选峰导致部分方法无初值，异常和原代码保存在 development_sources00；修正显式局部 DC 初始化、短窗 DC 极点后才冻结。新评价为 12 族×8=96 条，另 50 条新初相低速压力。每条 320 ns、40 GS/s。全部真值仅进入外部 scorer，不给估计器提供真值速度、起跳点或目标身份。完整注册条件与算子见 [PROTOCOL.md](PROTOCOL.md)。

基准口径补充：旧 Research M0 对 refinement 失败显式保留 discrete 候选，正式 strict refined 通道则保留 NaN。原12方法的 source_freeze 和结果未改，另追加 legacy_m0_512/768 对照，全部数据再跑；其注册发生在查看主结果后，只修正对照完整性，不据结果调新算法。两种契约均在下表展示，完整说明见 [BASELINE_AUDIT.md](BASELINE_AUDIT.md)。

候选、启发式支持后的假设和物理测量必须区分。所有方法保存原候选/NaN；共同 256 点局部正余弦拟合解释率≥0.20、条件数≤1e5、谱对比≥10 dB 只是固定启发式门槛，不是正式 SNR、F 检验 p 值或目标身份认证。复杂方法另有显式包络/镜像门槛。杂散组合的支持统计在 nuisance-subtracted 电压域，表中已单列模型域，不能直接据 R2 比其他方法更可信。

合成使用 $v=1550\times10^{-9} f/2$，真实数据只作同一波长假设下的等效表观速度。无参考频移实值模型不辨速度符号；AC 耦合下没有可辨拍频时输出 NaN/状态，不输出实测零速。参考频移、波长、AC 截止、真实反射界面和 LiF 修正均没有凭模型猜测补齐。

## 📊 96 条新种子主评价：全部方法

主表为全部有真值运动点，包含消光、不混入起跳前静止。有限 RMSE 只在有限点计算，失败率则保留所有目标帧，缺失也失败。有限误差 >100 MHz（77.5 m/s）算频率偏离；这不是独立物理身份误判率。50/200 MHz 敏感性在完整 summary 表。

| 方法 | 候选有限 RMSE m/s | 候选覆盖 | 支持后有限 RMSE m/s | 支持后覆盖 | 支持后失败含缺失 |
| --- | --- | --- | --- | --- | --- |
| [stft512](methods/stft512/README.md) | 141.137 | 81.72% | 138.691 | 80.09% | 27.66% |
| [stft768](methods/stft768/README.md) | 132.493 | 95.61% | 128.520 | 93.17% | 14.67% |
| [stft512_wide](methods/stft512_wide/README.md) | 141.660 | 76.90% | 142.926 | 75.47% | 32.31% |
| [gated_stft256](methods/gated_stft256/README.md) | 349.758 | 84.71% | 18.489 | 82.16% | 18.25% |
| [gated_stft512](methods/gated_stft512/README.md) | 289.335 | 84.71% | 8.912 | 82.32% | 17.79% |
| [dechirp](methods/dechirp/README.md) | 257.787 | 84.71% | 14.238 | 82.31% | 17.88% |
| [varpro](methods/varpro/README.md) | 285.230 | 84.71% | 9.364 | 82.39% | 17.78% |
| [clutter_varpro](methods/clutter_varpro/README.md) | 271.077 | 93.79% | 8.898 | 91.47% | 8.70% |
| [acmd](methods/acmd/README.md) | 290.021 | 84.71% | 17.213 | 69.23% | 31.17% |
| [matrix_pencil](methods/matrix_pencil/README.md) | 464.652 | 82.88% | 23.215 | 73.26% | 27.46% |
| [time_domain](methods/time_domain/README.md) | 252.155 | 84.71% | 10.404 | 81.62% | 18.60% |
| [baseband](methods/baseband/README.md) | 295.176 | 82.80% | 13.181 | 53.67% | 46.40% |
| [legacy_m0_512](methods/legacy_m0_512/README.md) | 362.985 | 100.00% | 138.634 | 83.01% | 26.06% |
| [legacy_m0_768](methods/legacy_m0_768/README.md) | 185.342 | 100.00% | 128.234 | 94.42% | 13.64% |

![全部族比较](../../../artifacts/TASK-008/figures/synthetic_comparison.png)

有限 RMSE 的大幅降低部分来自拒绝/缺失和去 DC/事件截断。不能把原 STFT 在噪声或谱边界的无输出、以及复杂方法在困难样本的漏检隐去。相干杂散组合与单独 VarPro 的区别集中在 8 条 stationary_spur；其他场景大多相同，不能说 VarPro 自身解决了强杂散。

## 📐 配对不确定度与增益归因

每次 bootstrap 重采样 88 条有运动的独立波形，2000 次、seed=81300001。下表为每波形全分母失败率差，负数表示新方法更少失败；不是重叠帧的独立置信区间，也不是仪器测量不确定度。

| 方法 | 对照 | 失败率宏差/百分点 | 配对95%区间/百分点 | 波形N |
| --- | --- | --- | --- | --- |
| dechirp | stft768 | +3.208 | [-0.590, +7.754] | 88 |
| varpro | stft768 | +3.107 | [-0.691, +7.610] | 88 |
| clutter_varpro | stft768 | -5.970 | [-12.486, +0.663] | 88 |
| time_domain | stft768 | +3.927 | [+0.173, +8.473] | 88 |
| dechirp | gated_stft512 | +0.086 | [-0.129, +0.288] | 88 |
| varpro | gated_stft512 | -0.014 | [-0.129, +0.101] | 88 |
| clutter_varpro | gated_stft512 | -9.091 | [-15.852, -3.467] | 88 |
| time_domain | gated_stft512 | +0.806 | [+0.503, +1.136] | 88 |
| dechirp | legacy_m0_768 | +4.243 | [+0.446, +8.732] | 88 |
| varpro | legacy_m0_768 | +4.143 | [+0.402, +8.574] | 88 |
| clutter_varpro | legacy_m0_768 | -4.934 | [-11.508, +1.683] | 88 |
| time_domain | legacy_m0_768 | +4.963 | [+1.323, +9.365] | 88 |

相对截断 512，组合收益区间未跨零；相对原 768，区间跨零。这一分布上的均值改善不能推成全面取代 STFT。单独 VarPro 相对截断 512 的整体失败差接近零。8 条确定性持续杂散构成主分布的固定比例，不能用该总体数值估计真实杂散发生率。

## 🔬 机制与数学实现

VarPro 在实值域最小化 $\|(I-\Phi\Phi^\dagger)y\|^2$，$\Phi=[\cos\phi,\sin\phi,1]$，$\phi=2\pi(f\tau+a\tau^2/2)$；用 SVD 消去线性幅相/DC，再以带解析梯度的多起点 L-BFGS-B 搜索频率与斜率。变量投影的来源是 Golub–Pereyra；本轮具体模型和质量门槛由代码及数值验证定义。[^1] 搜索频率后不能套用固定设计的 F 分布；非线性有限样本估计也不保证亚周期无偏。

Dechirp 在 512 点截断窗上遍历 17 个斜率，最大化实值输入的复指数投影；不用全局 Hilbert 或双向高通，保留负频镜像失配，并把非对称窗口中心频率按斜率运回原采样中心。它是局部近似频率集中法，不冒充精确实值似然。

ACMD 变体求解 $\|y-Cu-Sv\|^2+\alpha(\|D^2u\|^2+\|D^2v\|^2)$，在起跳处断开区间，交错变量形成带宽 4 的 SPD 系统，六次迭代更新频率。对于 $y=u\cos\theta+v\sin\theta$，物理相位是 $\theta-\operatorname{atan2}(v,u)$，故修正为 $(v u'-u v')/[2\pi(u^2+v^2)]$；符号由解析单音单测验证。这里只测试自推导单模态变体，不声称完整复现 Chen 等 VNCMD 的多模态算法。[^2]

矩阵束家族实现为 96 点窗、32 列 Hankel、五维信号子空间的 LS 移位估计。四个共轭信号极点之外保留一个 DC nuisance 极点；去均值后直接用 rank 4 会使常数项占据信号子空间。正角极点在实值波形中重新拟合幅度，主/次分量都保存。未实现 TLS，也没有用“超分辨”一词代替噪声稳定性验证。

时域反演把每 2048 点分为独立相干 slab，以 9 个分段线性频率节点积分相位，再消去余弦、正弦及 DC 系数，以解析梯度 L-BFGS-B 优化，加固定二阶节点惩罚。该前向建模思路受 Allison 等时域 PDV 工作启发，本文实现是确定性局部正则最小二乘；没有运行 MCMC、未知前端协方差或后验多模态采样，不能宣称与贝叶斯采样等价。[^3]

基带法把去基线的实值电压乘以粗相位负指数，使用明确的 257 点、200 MHz 中心 FIR 和 129 点二阶 SG 相位导数；离线中心滤波只作用于独立事件之后，不以此定位因果起跳。低于 400 MHz 或低包络时拒绝，代价是低速和弱信号覆盖为零。

相干杂散组合只在首 10%（最多 4096 点）拟合一个强静态正弦的频率、幅相和偏置，预测全记录电压后在内存副本相减，再执行完全相同的 VarPro。它利用相位预测，不是 PSD Whitening、notch 或完整 OMP；相位可预测性和前缀无目标仍是待验证先验。

## ⚡ 局部场景，不用总体均值掩盖失败

| 场景（各8条） | 方法 | 有限RMSE m/s | 支持覆盖 | 失败含缺失 |
| --- | --- | --- | --- | --- |
| fast_accel | stft768 | 9.014 | 93.35% | 7.28% |
| fast_accel | legacy_m0_768 | 13.039 | 94.15% | 6.80% |
| fast_accel | gated_stft256 | 6.438 | 99.37% | 0.79% |
| fast_accel | gated_stft512 | 11.946 | 99.37% | 1.42% |
| fast_accel | dechirp | 3.360 | 99.37% | 0.63% |
| fast_accel | varpro | 3.532 | 99.37% | 0.63% |
| fast_accel | clutter_varpro | 3.532 | 99.37% | 0.63% |
| fast_accel | time_domain | 5.807 | 99.37% | 0.63% |
| low_ramp | stft768 | 1.929 | 87.82% | 12.18% |
| low_ramp | legacy_m0_768 | 7.258 | 96.36% | 3.64% |
| low_ramp | gated_stft256 | 27.861 | 94.94% | 7.44% |
| low_ramp | gated_stft512 | 9.095 | 95.41% | 4.91% |
| low_ramp | dechirp | 15.586 | 94.78% | 6.01% |
| low_ramp | varpro | 3.025 | 95.41% | 4.59% |
| low_ramp | clutter_varpro | 3.025 | 95.41% | 4.59% |
| low_ramp | time_domain | 2.055 | 95.41% | 4.59% |
| stationary_spur | stft768 | 411.072 | 100.00% | 85.60% |
| stationary_spur | legacy_m0_768 | 411.072 | 100.00% | 85.60% |
| stationary_spur | gated_stft256 | — | 0.00% | 100.00% |
| stationary_spur | gated_stft512 | — | 0.00% | 100.00% |
| stationary_spur | dechirp | — | 0.00% | 100.00% |
| stationary_spur | varpro | — | 0.00% | 100.00% |
| stationary_spur | clutter_varpro | 1.364 | 99.84% | 0.16% |
| stationary_spur | time_domain | — | 0.00% | 100.00% |
| weak_chirp | stft768 | 2.550 | 79.27% | 20.73% |
| weak_chirp | legacy_m0_768 | 11.813 | 79.43% | 20.73% |
| weak_chirp | gated_stft256 | 12.166 | 30.85% | 69.15% |
| weak_chirp | gated_stft512 | 4.257 | 30.85% | 69.15% |
| weak_chirp | dechirp | 5.923 | 31.96% | 68.04% |
| weak_chirp | varpro | 7.708 | 31.33% | 68.83% |
| weak_chirp | clutter_varpro | 7.708 | 31.33% | 68.83% |
| weak_chirp | time_domain | 5.777 | 30.54% | 69.46% |
| two_shock | stft768 | 1.140 | 99.53% | 0.47% |
| two_shock | legacy_m0_768 | 7.836 | 99.68% | 0.47% |
| two_shock | gated_stft256 | 3.353 | 99.53% | 0.47% |
| two_shock | gated_stft512 | 1.001 | 99.53% | 0.47% |
| two_shock | dechirp | 4.100 | 99.53% | 0.47% |
| two_shock | varpro | 6.666 | 99.53% | 0.63% |
| two_shock | clutter_varpro | 6.666 | 99.53% | 0.63% |
| two_shock | time_domain | 8.463 | 97.47% | 2.85% |
| two_component | stft768 | 10.656 | 99.68% | 0.32% |
| two_component | legacy_m0_768 | 10.656 | 99.68% | 0.32% |
| two_component | gated_stft256 | 35.181 | 100.00% | 1.27% |
| two_component | gated_stft512 | 17.571 | 99.53% | 0.47% |
| two_component | dechirp | 21.649 | 100.00% | 0.63% |
| two_component | varpro | 20.581 | 100.00% | 0.79% |
| two_component | clutter_varpro | 20.581 | 100.00% | 0.79% |
| two_component | time_domain | 25.114 | 97.78% | 3.96% |

强加速中 Dechirp 和 VarPro 相比两个短窗控制确有条件性精度改善；基带法更准但少输出。双冲击中截断 STFT512 的 1.001 m/s 优于 VarPro 6.666 和时域反演 8.463 m/s，不能把连续相位模型推成阶跃恢复最优。-5 dB 弱信号的 VarPro 支持覆盖只有约 31%，原 768 约 79%；弱信号瓶颈并未解决。

## ⏱️ 起跳、静止误报与消光

| 方法 | 检出/88 | 漏检 | 已检出中位绝对误差 ns | 95%绝对误差 ns | 噪声假事件/8 | 静止支持误报 | 消光支持误报 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| stft512 | 79/88 | 9 | 2.457 | 19.289 | 3/8 | 8.86% | 6.82% |
| stft768 | 80/88 | 8 | 2.572 | 7.765 | 0/8 | 8.16% | 6.82% |
| stft512_wide | 79/88 | 9 | 2.457 | 19.289 | 3/8 | 8.58% | 6.82% |
| gated_stft256 | 75/88 | 13 | 0.189 | 8.634 | 0/8 | 0.09% | 9.09% |
| gated_stft512 | 75/88 | 13 | 0.189 | 8.634 | 0/8 | 0.09% | 9.09% |
| dechirp | 75/88 | 13 | 0.189 | 8.634 | 0/8 | 0.05% | 9.09% |
| varpro | 75/88 | 13 | 0.189 | 8.634 | 0/8 | 0.09% | 9.09% |
| clutter_varpro | 83/88 | 5 | 0.189 | 8.178 | 0/8 | 0.09% | 9.09% |
| acmd | 75/88 | 13 | 0.189 | 8.634 | 0/8 | 0.05% | 6.82% |
| matrix_pencil | 75/88 | 13 | 0.189 | 8.634 | 0/8 | 0.00% | 5.68% |
| time_domain | 75/88 | 13 | 0.189 | 8.634 | 0/8 | 0.09% | 1.14% |
| baseband | 75/88 | 13 | 0.189 | 8.634 | 0/8 | 0.00% | 2.27% |
| legacy_m0_512 | 79/88 | 9 | 2.457 | 19.289 | 3/8 | 9.78% | 6.82% |
| legacy_m0_768 | 80/88 | 8 | 2.572 | 7.765 | 0/8 | 9.04% | 6.82% |

能量检测的已检出中位数 0.189 ns 不能包装成一般起跳精度：普通共享检测漏 13/88，95 分位为 8.634 ns；杂散组合漏 5/88，95 分位为 8.178 ns。多个估计器共用检测器，不是独立重复。零速度没有作为可测量物理量恢复；完全消光中仍有边界混合/假支持，必须保留在失败记录，不能按平滑曲线连接缺口。速度历史网格为 3.2/1.6 ns，与该事件时刻估计的亚采样块统计分辨不同。

## 🌡️ 50 次随机初相低速压力

15/30/50/100/200 m/s 每档 10 条，AC 截止和 SNR 与实例模数共同分配，存在条件关联；不能作每个截止/SNR 单元 50 次独立重复。下表保留候选错误，防止仅靠支持拒绝隐藏发散。

| 方法 | 速度 m/s | 候选有限RMSE m/s | 候选覆盖 | 支持覆盖 | 支持失败含缺失 |
| --- | --- | --- | --- | --- | --- |
| stft768 | 15 | 36.366 | 0.25% | 0.00% | 100.00% |
| stft768 | 30 | 35.786 | 1.52% | 0.38% | 99.62% |
| stft768 | 50 | 4.580 | 54.30% | 54.05% | 45.95% |
| stft768 | 100 | 1.165 | 95.82% | 95.82% | 4.18% |
| stft768 | 200 | 0.863 | 99.37% | 99.37% | 0.63% |
| gated_stft512 | 15 | 57.055 | 98.10% | 57.85% | 42.28% |
| gated_stft512 | 30 | 25.393 | 98.86% | 84.68% | 15.44% |
| gated_stft512 | 50 | 12.805 | 99.24% | 98.99% | 1.01% |
| gated_stft512 | 100 | 4.962 | 99.49% | 99.49% | 0.51% |
| gated_stft512 | 200 | 0.838 | 99.62% | 99.62% | 0.38% |
| varpro | 15 | 641.908 | 98.10% | 58.73% | 41.27% |
| varpro | 30 | 15.332 | 98.86% | 87.85% | 12.28% |
| varpro | 50 | 12.645 | 99.24% | 99.11% | 0.89% |
| varpro | 100 | 1.631 | 99.49% | 99.49% | 0.51% |
| varpro | 200 | 1.318 | 99.62% | 99.62% | 0.38% |
| matrix_pencil | 15 | 3523.331 | 63.80% | 1.90% | 98.86% |
| matrix_pencil | 30 | 2935.119 | 64.05% | 8.86% | 95.95% |
| matrix_pencil | 50 | 2318.405 | 68.35% | 24.56% | 82.15% |
| matrix_pencil | 100 | 879.720 | 92.41% | 60.13% | 44.30% |
| matrix_pencil | 200 | 53.854 | 99.24% | 82.78% | 20.13% |
| time_domain | 15 | 333.287 | 98.10% | 33.29% | 70.51% |
| time_domain | 30 | 559.564 | 98.86% | 60.51% | 41.39% |
| time_domain | 50 | 3.686 | 99.24% | 99.11% | 0.89% |
| time_domain | 100 | 4.370 | 99.49% | 99.49% | 0.51% |
| time_domain | 200 | 1.479 | 99.62% | 99.62% | 0.38% |
| legacy_m0_768 | 15 | 30.427 | 100.00% | 59.62% | 40.38% |
| legacy_m0_768 | 30 | 15.916 | 100.00% | 88.61% | 11.39% |
| legacy_m0_768 | 50 | 4.585 | 100.00% | 99.62% | 0.38% |
| legacy_m0_768 | 100 | 11.215 | 100.00% | 100.00% | 0.00% |
| legacy_m0_768 | 200 | 12.329 | 100.00% | 100.00% | 0.63% |

![低速压力](../../../artifacts/TASK-008/figures/low_speed_phase_stress.png)

VarPro 在 15 m/s 候选有限 RMSE 641.908 m/s，时域反演在 15/30 m/s 分别 333.287/559.564 m/s；这些输出都可能伴随优化器成功收敛。半周期实值模型在未知幅度/DC/噪声下不能自动解决可辨识性。严格 refined 的 768 在 15/30 m/s 几乎没有有限输出，但完整历史 M0 有 100% 候选覆盖，RMSE 为 30.427/15.916 m/s；不能用 strict-refined 的缺失削弱历史基准。100 MHz 对应 77.5 m/s，对极低速非常宽松，‘阈值内’不意味着准确重建 15 m/s，必须同时看 RMSE/真值尺度。50 m/s 时域反演候选 RMSE 3.686 m/s、覆盖 99.24%，历史 M0 为 4.585 m/s、100% 候选覆盖；增益有限，不外推到所有零/低速。

## 🧩 双分量与优化器诊断

矩阵束保存了两个正频率候选。额外事后双分量配对诊断要求两个输出分别在两个真频率 ±50 MHz 内：仅 **5/632** 目标帧通过；两真频率相隔≥100 MHz 的帧为 **3/245**。分母是重叠窗帧，不是独立重复次数；此项未用于调参。无噪固定双音单测通过，含噪/近邻/慢 chirp 条件下稳定超分辨并未建立。

| 阶段 | 方法 | 拟合次数 | 优化器报告收敛 | 未收敛却支持的帧 |
| --- | --- | --- | --- | --- |
| fresh | clutter_varpro | 6522 | 6522 | 0 |
| fresh | time_domain | 442 | 442 | 0 |
| fresh | varpro | 5891 | 5891 | 0 |
| phase_stress | clutter_varpro | 3913 | 3913 | 0 |
| phase_stress | time_domain | 289 | 289 | 0 |
| phase_stress | varpro | 3913 | 3913 | 0 |
| real | clutter_varpro | 7359 | 7359 | 0 |
| real | time_domain | 471 | 471 | 0 |
| real | varpro | 7359 | 7359 | 0 |

当前全部已执行拟合报告收敛；极低速错误解仍然存在，所以优化器成功不是速度正确性或后验单峰性的证据。没有用逆海森局部曲率给出未经校准的真实误差带。

## 💻 实测计算成本

当前机器、单线程 BLAS、wall clock；包含公共 setup 和质量支持检查，排除数据读入/图片导出。setup 对某些原基准含不必要的粗初始化，所以这是统一 harness 的实际成本，不是各方法的最优实现成本。每条真实通道独立测量，不从 12,800 点合成线性外推。

| 方法 | 80k中位 s | 80k P95 s | 80k超过3秒 | 200001点最大 s |
| --- | --- | --- | --- | --- |
| stft512 | 0.226 | 0.252 | 0/12 | 0.605 |
| stft768 | 0.227 | 0.239 | 0/12 | 0.584 |
| stft512_wide | 0.150 | 0.176 | 0/12 | 0.393 |
| gated_stft256 | 0.239 | 0.259 | 0/12 | 0.590 |
| gated_stft512 | 0.237 | 0.258 | 0/12 | 0.598 |
| dechirp | 0.857 | 1.099 | 0/12 | 1.687 |
| varpro | 3.184 | 4.410 | 8/12 | 6.723 |
| clutter_varpro | 3.204 | 4.603 | 9/12 | 7.220 |
| acmd | 0.257 | 0.314 | 0/12 | 0.615 |
| matrix_pencil | 0.364 | 0.455 | 0/12 | 0.839 |
| time_domain | 0.498 | 0.723 | 0/12 | 1.126 |
| baseband | 0.171 | 0.194 | 0/12 | 0.436 |
| legacy_m0_512 | 1.213 | 1.283 | 0/12 | 3.166 |
| legacy_m0_768 | 1.227 | 1.294 | 0/12 | 3.152 |

VarPro/组合的 80k 中位数约 3.18/3.20 秒，已经超过附件的默认交互目标；后续优先研究局部调用，不能拿 320 ns 小合成的耗时声称全记录满足 3 秒。时域反演确实是亚秒级，但精度和模型适配没有因此过关。峰值 RAM 未做专门进程级计量，不报告伪造内存基准。

## 🗂️ 每种方法的实际实现与负结果

| 方法 | 范围/限制 |
| --- | --- |
| [stft512](methods/stft512/README.md) | 保留原基准；DC、持续杂散、时间窗边界和 refinement 缺失均暴露。 |
| [stft768](methods/stft768/README.md) | 整体很强的对照，弱信号及双分量较好；长窗提前响应、杂散身份误锁、低频边界仍存在。 |
| [stft512_wide](methods/stft512_wide/README.md) | 单独扩展频带并不构成新算法收益；更容易选中低频漂移，原 sub-bin 边界拒绝仍保留。 |
| [gated_stft256](methods/gated_stft256/README.md) | 低成本基础对照；起跳后覆盖高，但短窗低频镜像偏差明显，弱信号事件漏检。 |
| [gated_stft512](methods/gated_stft512/README.md) | 复杂方法必须击败的简单对照；低速和快变存在偏差，持续杂散使能量事件漏检。 |
| [dechirp](methods/dechirp/README.md) | 强加速族有净收益；卸载、低速、双冲击和弱信号没有整体优势。不是精确实值似然。 |
| [varpro](methods/varpro/README.md) | 低速爬升、强加速有局部价值；15 m/s 亚周期压力会跳入错误极值，常数包络不能解释所有散斑与双分量。 |
| [clutter_varpro](methods/clutter_varpro/README.md) | 新增收益集中在可预测持续正弦杂散；前缀若包含真实运动，或杂散漂移/失相干，会误减目标或失效。 |
| [acmd](methods/acmd/README.md) | 本轮单模态变体没有综合净优势；弱/有色噪声下包络门槛损失大量覆盖，粗轨迹和正则带宽影响明显。 |
| [matrix_pencil](methods/matrix_pencil/README.md) | 噪声与短窗令极点不稳定；无噪双音单测可分不意味着 12 dB 近邻双分量稳定可分。 |
| [time_domain](methods/time_domain/README.md) | 低速爬升有条件价值；15–30 m/s 压力、双冲击及全局相位盆地失败，收敛不认证正确解。 |
| [baseband](methods/baseband/README.md) | 高频单分量强加速条件下精度较高；近零/低频由镜像保护拒绝，整体覆盖低，不能作为通用主引擎。 |
| [legacy_m0_512](methods/legacy_m0_512/README.md) | 逐值复现旧 Research M0；refined 失败时显式保留 discrete，不把边界候选伪称可靠测量。 |
| [legacy_m0_768](methods/legacy_m0_768/README.md) | 逐值复现旧 Research M0 的长窗；与 strict refined 通道并列，避免 NaN 细化契约削弱基准。 |

## 🧾 ALG-01～18 的处置

| 候选 | 本轮处置 |
| --- | --- |
| ALG-01 | 只实现截断短窗/去DC控制；未实现完整 LPA-ICI/DPSS 多窗，不冒称相同方法。 |
| ALG-02 | 未重做高阶 SST；已读 TASK-026 表示层负结果，无新的弱信号导数证据。 |
| ALG-03 | 局部 chirplet 集中归入 Dechirp，不构造全长三维张量。 |
| ALG-04 | 实现实值 VarPro 与相干杂散组合；不采信无偏/固定F置信度的强论断。 |
| ALG-05 | 实现 raw-real 局部 Dechirp 变体，无全局 Hilbert，不冒充完整 CB-LCMLE。 |
| ALG-06 | 实现数字基带相位精修；频移外差论文的结论不直接套用本无偏频假设。 |
| ALG-07 | 实现 LS 子空间极点变体、主/次频率及双分量诊断；未实现 TLS。 |
| ALG-08 | 未实现 TVAR；优先把算力用于独立原波形模型，不据理论风险声称实测淘汰。 |
| ALG-09 | 只实现单相干 nuisance 预测，非 OMP-MCA；完整稀疏字典仍待研究。 |
| ALG-10 | 未实现 TV/L1 后端；本轮先识别前端观测与多极值问题，未把平滑当新证据。 |
| ALG-11 | 未实现 raw-EKF/UKF；锁定/重捕获与低速可观测性需单独设计。 |
| ALG-12 | 未实现 raw-IMM-SLDS；不以旧 STFT IMM 的结果替代它的实测。 |
| ALG-13 | 实现确定性分段前向反演；未实现 MCMC/Laplace/未知前端噪声协方差。 |
| ALG-14 | 实现单模态边界 ACMD-inspired 变体；未实现完整多模态 VNCMD。 |
| ALG-15 | 未实现 VMD/CEEMDAN，本轮无新实测结论，不称彻底否定全部变体。 |
| ALG-16 | 采用显式块能量/局部方差事件检测；不是 PELT/BOCPD。 |
| ALG-17 | 未实现 CTKEO；不把块能量的起跳数字算给三点 TKEO。 |
| ALG-18 | 未训练网络；缺少真实GT/前端域标定，不以合成拟合替代物理验证。 |

## 🧪 全部真实数据的逐通道结果

以下覆盖全部 17 条通道。支持覆盖和 R2 是观测量，不是准确率。R2 列对杂散组合取减去预测 nuisance 的电压域，对其他方法取原电压域；它们不能无条件横向排序。所有时刻为相对原首样本的 ns；中位频率为有限候选的统计，不能当已确认界面速度。原谱中的强低频、谐波和多分量都保留在各方法全记录图中。

### raw00_20260607_ch1

`data/raw/20260607.csv`，电压列 1，80,000 点，采样率 40.000 GS/s，SHA-256 `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw00_20260607_ch1.png) | 69.68% | 62.74% | 0.727 | 0.931 | 0.214 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw00_20260607_ch1.png) | 89.52% | 62.26% | 0.729 | 0.712 | 0.215 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw00_20260607_ch1.png) | 61.45% | 60.97% | 0.725 | 0.940 | 0.133 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw00_20260607_ch1.png) | 64.68% | 61.45% | 0.726 | 0.936 | 0.201 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw00_20260607_ch1.png) | 64.68% | 61.61% | 0.726 | 0.938 | 0.198 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw00_20260607_ch1.png) | 64.68% | 61.77% | 0.726 | 0.938 | 0.731 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw00_20260607_ch1.png) | 64.68% | 61.77% | 0.726 | 0.937 | 3.101 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw00_20260607_ch1.png) | 64.68% | 61.77% | 0.726 | 0.937 | 3.182 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw00_20260607_ch1.png) | 64.68% | 47.74% | 0.726 | 0.937 | 0.243 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw00_20260607_ch1.png) | 64.68% | 46.29% | 0.737 | 0.784 | 0.360 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw00_20260607_ch1.png) | 64.68% | 60.97% | 0.726 | 0.937 | 0.447 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw00_20260607_ch1.png) | 64.52% | 32.90% | 0.726 | 0.937 | 0.152 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw00_20260607_ch1.png) | 100.00% | 62.74% | 0.452 | 0.599 | 1.222 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw00_20260607_ch1.png) | 100.00% | 62.26% | 0.728 | 0.599 | 1.264 |
### raw00_20260607_ch2

`data/raw/20260607.csv`，电压列 2，80,000 点，采样率 40.000 GS/s，SHA-256 `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw00_20260607_ch2.png) | 62.10% | 61.94% | 0.725 | 0.986 | 0.221 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw00_20260607_ch2.png) | 71.61% | 63.06% | 0.727 | 0.983 | 0.215 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw00_20260607_ch2.png) | 60.16% | 60.00% | 0.725 | 0.986 | 0.143 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw00_20260607_ch2.png) | 64.68% | 62.74% | 0.725 | 0.985 | 0.222 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw00_20260607_ch2.png) | 64.68% | 62.90% | 0.725 | 0.985 | 0.230 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw00_20260607_ch2.png) | 64.68% | 63.06% | 0.725 | 0.985 | 0.773 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw00_20260607_ch2.png) | 64.68% | 63.06% | 0.725 | 0.986 | 3.166 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw00_20260607_ch2.png) | 64.68% | 63.06% | 0.725 | 0.986 | 3.211 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw00_20260607_ch2.png) | 64.68% | 54.19% | 0.725 | 0.986 | 0.234 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw00_20260607_ch2.png) | 64.68% | 51.77% | 0.726 | 0.949 | 0.328 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw00_20260607_ch2.png) | 64.68% | 60.81% | 0.725 | 0.985 | 0.399 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw00_20260607_ch2.png) | 64.52% | 34.52% | 0.725 | 0.986 | 0.174 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw00_20260607_ch2.png) | 100.00% | 61.94% | 0.277 | 0.723 | 1.301 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw00_20260607_ch2.png) | 100.00% | 63.06% | 0.504 | 0.717 | 1.331 |
### raw01_20260630-1_ch1

`data/raw/20260630-1.csv`，电压列 1，200,001 点，采样率 40.000 GS/s，SHA-256 `203b182e477e1e08214551977a00313eaf6f17a71391d83875f6f879dc3a0a74`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw01_20260630-1_ch1.png) | 52.92% | 52.86% | 0.507 | 0.861 | 0.605 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw01_20260630-1_ch1.png) | 59.86% | 56.07% | 0.506 | 0.826 | 0.584 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw01_20260630-1_ch1.png) | 48.23% | 48.23% | 0.507 | 0.896 | 0.393 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw01_20260630-1_ch1.png) | 55.49% | 53.89% | 0.507 | 0.845 | 0.545 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw01_20260630-1_ch1.png) | 55.49% | 54.14% | 0.507 | 0.850 | 0.598 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw01_20260630-1_ch1.png) | 55.49% | 54.40% | 0.507 | 0.851 | 1.687 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw01_20260630-1_ch1.png) | 55.49% | 54.40% | 0.508 | 0.850 | 6.671 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw01_20260630-1_ch1.png) | 55.49% | 54.40% | 0.508 | 0.850 | 7.220 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw01_20260630-1_ch1.png) | 55.49% | 38.54% | 0.507 | 0.845 | 0.615 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw01_20260630-1_ch1.png) | 55.49% | 46.11% | 0.512 | 0.681 | 0.839 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw01_20260630-1_ch1.png) | 55.49% | 53.69% | 0.508 | 0.847 | 1.126 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw01_20260630-1_ch1.png) | 55.36% | 29.67% | 0.507 | 0.850 | 0.436 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw01_20260630-1_ch1.png) | 100.00% | 56.39% | 0.289 | 0.465 | 3.166 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw01_20260630-1_ch1.png) | 100.00% | 58.19% | 0.314 | 0.455 | 3.152 |
### raw01_20260630-1_ch2

`data/raw/20260630-1.csv`，电压列 2，200,001 点，采样率 40.000 GS/s，SHA-256 `203b182e477e1e08214551977a00313eaf6f17a71391d83875f6f879dc3a0a74`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw01_20260630-1_ch2.png) | 48.68% | 48.43% | 0.507 | 0.802 | 0.583 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw01_20260630-1_ch2.png) | 56.33% | 52.41% | 0.507 | 0.718 | 0.563 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw01_20260630-1_ch2.png) | 41.23% | 41.23% | 0.507 | 0.887 | 0.374 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw01_20260630-1_ch2.png) | 55.17% | 51.89% | 0.507 | 0.728 | 0.590 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw01_20260630-1_ch2.png) | 55.17% | 52.28% | 0.508 | 0.736 | 0.522 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw01_20260630-1_ch2.png) | 55.17% | 52.28% | 0.507 | 0.739 | 1.685 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw01_20260630-1_ch2.png) | 55.17% | 52.15% | 0.508 | 0.738 | 6.723 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw01_20260630-1_ch2.png) | 55.17% | 52.15% | 0.508 | 0.738 | 6.845 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw01_20260630-1_ch2.png) | 55.17% | 29.74% | 0.507 | 0.730 | 0.601 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw01_20260630-1_ch2.png) | 55.17% | 42.39% | 0.521 | 0.594 | 0.839 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw01_20260630-1_ch2.png) | 55.17% | 51.51% | 0.509 | 0.733 | 1.116 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw01_20260630-1_ch2.png) | 55.11% | 21.13% | 0.507 | 0.730 | 0.423 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw01_20260630-1_ch2.png) | 100.00% | 49.13% | 0.059 | 0.164 | 2.931 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw01_20260630-1_ch2.png) | 100.00% | 52.92% | 0.303 | 0.272 | 3.148 |
### raw02_20260630-2_ch1

`data/raw/20260630-2.csv`，电压列 1，80,000 点，采样率 40.000 GS/s，SHA-256 `c0c31b2990eae228b21594276d030b83600a7ddb98c1953842e4cb80c17fa261`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw02_20260630-2_ch1.png) | 72.42% | 72.10% | 0.860 | 0.958 | 0.230 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw02_20260630-2_ch1.png) | 75.48% | 73.87% | 0.860 | 0.956 | 0.239 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw02_20260630-2_ch1.png) | 67.74% | 67.58% | 0.859 | 0.961 | 0.160 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw02_20260630-2_ch1.png) | 75.16% | 73.39% | 0.862 | 0.956 | 0.241 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw02_20260630-2_ch1.png) | 75.16% | 73.71% | 0.862 | 0.956 | 0.233 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw02_20260630-2_ch1.png) | 75.16% | 73.87% | 0.862 | 0.956 | 1.058 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw02_20260630-2_ch1.png) | 75.16% | 73.87% | 0.862 | 0.956 | 3.249 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw02_20260630-2_ch1.png) | 75.16% | 73.87% | 0.862 | 0.956 | 3.452 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw02_20260630-2_ch1.png) | 75.16% | 60.97% | 0.862 | 0.956 | 0.288 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw02_20260630-2_ch1.png) | 75.16% | 70.97% | 0.864 | 0.953 | 0.367 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw02_20260630-2_ch1.png) | 75.16% | 73.06% | 0.862 | 0.956 | 0.516 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw02_20260630-2_ch1.png) | 75.00% | 61.29% | 0.862 | 0.956 | 0.191 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw02_20260630-2_ch1.png) | 100.00% | 73.71% | 0.854 | 0.943 | 1.224 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw02_20260630-2_ch1.png) | 100.00% | 74.84% | 0.855 | 0.943 | 1.191 |
### raw02_20260630-2_ch2

`data/raw/20260630-2.csv`，电压列 2，80,000 点，采样率 40.000 GS/s，SHA-256 `c0c31b2990eae228b21594276d030b83600a7ddb98c1953842e4cb80c17fa261`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw02_20260630-2_ch2.png) | 68.39% | 68.23% | 0.859 | 0.994 | 0.263 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw02_20260630-2_ch2.png) | 73.23% | 71.77% | 0.860 | 0.993 | 0.239 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw02_20260630-2_ch2.png) | 60.00% | 59.84% | 0.858 | 0.994 | 0.172 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw02_20260630-2_ch2.png) | 75.00% | 71.45% | 0.861 | 0.993 | 0.260 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw02_20260630-2_ch2.png) | 75.00% | 72.10% | 0.861 | 0.993 | 0.248 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw02_20260630-2_ch2.png) | 75.00% | 72.26% | 0.861 | 0.993 | 0.930 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw02_20260630-2_ch2.png) | 75.00% | 71.94% | 0.861 | 0.993 | 3.580 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw02_20260630-2_ch2.png) | 75.00% | 71.94% | 0.861 | 0.993 | 3.577 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw02_20260630-2_ch2.png) | 75.00% | 55.16% | 0.861 | 0.993 | 0.277 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw02_20260630-2_ch2.png) | 75.00% | 66.29% | 0.861 | 0.991 | 0.392 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw02_20260630-2_ch2.png) | 75.00% | 70.97% | 0.861 | 0.993 | 0.509 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw02_20260630-2_ch2.png) | 74.84% | 55.00% | 0.861 | 0.994 | 0.198 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw02_20260630-2_ch2.png) | 100.00% | 68.39% | 0.852 | 0.940 | 1.146 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw02_20260630-2_ch2.png) | 100.00% | 71.94% | 0.855 | 0.940 | 1.226 |
### raw03_20260701_ch1

`data/raw/20260701.csv`，电压列 1，80,000 点，采样率 40.000 GS/s，SHA-256 `5ccb6530e0cc715e4a7a81327c625fce267a8b3473c0487479366ead9d9a952a`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw03_20260701_ch1.png) | 56.61% | 55.16% | 0.705 | 0.985 | 0.207 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw03_20260701_ch1.png) | 71.94% | 61.29% | 0.705 | 0.982 | 0.214 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw03_20260701_ch1.png) | 50.97% | 50.97% | 0.705 | 0.986 | 0.147 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw03_20260701_ch1.png) | 67.42% | 61.61% | 0.706 | 0.983 | 0.220 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw03_20260701_ch1.png) | 67.42% | 61.94% | 0.706 | 0.983 | 0.249 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw03_20260701_ch1.png) | 67.42% | 62.90% | 0.706 | 0.983 | 0.867 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw03_20260701_ch1.png) | 67.42% | 62.26% | 0.706 | 0.983 | 2.998 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw03_20260701_ch1.png) | 67.42% | 62.26% | 0.706 | 0.983 | 3.198 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw03_20260701_ch1.png) | 67.42% | 49.52% | 0.707 | 0.982 | 0.253 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw03_20260701_ch1.png) | 67.42% | 56.61% | 0.709 | 0.978 | 0.360 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw03_20260701_ch1.png) | 67.42% | 60.65% | 0.707 | 0.983 | 0.452 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw03_20260701_ch1.png) | 67.26% | 44.19% | 0.706 | 0.983 | 0.164 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw03_20260701_ch1.png) | 100.00% | 56.61% | 0.372 | 0.701 | 1.173 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw03_20260701_ch1.png) | 100.00% | 61.94% | 0.700 | 0.701 | 1.227 |
### raw03_20260701_ch2

`data/raw/20260701.csv`，电压列 2，80,000 点，采样率 40.000 GS/s，SHA-256 `5ccb6530e0cc715e4a7a81327c625fce267a8b3473c0487479366ead9d9a952a`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw03_20260701_ch2.png) | 50.81% | 50.32% | 0.705 | 0.985 | 0.215 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw03_20260701_ch2.png) | 58.39% | 54.03% | 0.705 | 0.983 | 0.223 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw03_20260701_ch2.png) | 49.84% | 49.68% | 0.705 | 0.985 | 0.149 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw03_20260701_ch2.png) | 67.42% | 55.16% | 0.707 | 0.981 | 0.258 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw03_20260701_ch2.png) | 67.42% | 55.65% | 0.707 | 0.981 | 0.241 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw03_20260701_ch2.png) | 67.42% | 55.65% | 0.707 | 0.981 | 0.848 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw03_20260701_ch2.png) | 67.42% | 55.65% | 0.707 | 0.981 | 3.202 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw03_20260701_ch2.png) | 67.42% | 55.65% | 0.707 | 0.981 | 3.098 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw03_20260701_ch2.png) | 67.42% | 48.71% | 0.707 | 0.981 | 0.273 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw03_20260701_ch2.png) | 67.42% | 51.13% | 0.710 | 0.976 | 0.372 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw03_20260701_ch2.png) | 67.42% | 53.87% | 0.708 | 0.981 | 0.488 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw03_20260701_ch2.png) | 67.26% | 44.19% | 0.706 | 0.981 | 0.185 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw03_20260701_ch2.png) | 100.00% | 50.48% | 0.347 | 0.385 | 1.252 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw03_20260701_ch2.png) | 100.00% | 54.19% | 0.420 | 0.441 | 1.243 |
### raw04_ch1_ch1

`data/raw/ch1.csv`，电压列 1，80,000 点，采样率 40.000 GS/s，SHA-256 `3bdcefd19b0cabd45ff713bc104e00829876f0be4303abcfff31dc5ada727a6a`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw04_ch1_ch1.png) | 87.10% | 18.39% | 4.799 | 0.110 | 0.230 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw04_ch1_ch1.png) | 94.03% | 17.10% | 4.852 | 0.095 | 0.231 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw04_ch1_ch1.png) | 75.48% | 18.23% | 4.957 | 0.120 | 0.158 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw04_ch1_ch1.png) | 78.39% | 16.94% | 4.843 | 0.101 | 0.242 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw04_ch1_ch1.png) | 78.39% | 18.39% | 4.948 | 0.117 | 0.265 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw04_ch1_ch1.png) | 78.39% | 20.48% | 4.945 | 0.141 | 0.982 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw04_ch1_ch1.png) | 78.39% | 18.87% | 4.920 | 0.127 | 3.931 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw04_ch1_ch1.png) | 78.39% | 18.87% | 4.920 | 0.127 | 3.910 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw04_ch1_ch1.png) | 78.39% | 13.06% | 4.948 | 0.057 | 0.262 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw04_ch1_ch1.png) | 78.39% | 9.52% | 4.746 | 0.043 | 0.423 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw04_ch1_ch1.png) | 78.39% | 14.68% | 5.053 | 0.050 | 0.719 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw04_ch1_ch1.png) | 78.23% | 12.58% | 4.957 | 0.050 | 0.189 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw04_ch1_ch1.png) | 100.00% | 18.71% | 4.617 | 0.104 | 1.268 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw04_ch1_ch1.png) | 100.00% | 17.42% | 4.814 | 0.094 | 1.257 |
### raw05_ch2_ch1

`data/raw/ch2.csv`，电压列 1，80,000 点，采样率 40.000 GS/s，SHA-256 `975d5edc124754a170cac083247d2f2ba1232f6bf6d26f2c878b498025b27a5f`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw05_ch2_ch1.png) | 77.42% | 30.65% | 3.131 | 0.141 | 0.235 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw05_ch2_ch1.png) | 99.03% | 28.55% | 3.158 | 0.099 | 0.238 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw05_ch2_ch1.png) | 43.39% | 30.16% | 3.165 | 0.343 | 0.142 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw05_ch2_ch1.png) | 42.26% | 29.52% | 3.184 | 0.327 | 0.189 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw05_ch2_ch1.png) | 42.26% | 30.48% | 3.197 | 0.353 | 0.203 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw05_ch2_ch1.png) | 42.26% | 32.10% | 3.188 | 0.418 | 0.586 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw05_ch2_ch1.png) | 42.26% | 31.77% | 3.187 | 0.395 | 2.151 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw05_ch2_ch1.png) | 42.26% | 31.77% | 3.187 | 0.395 | 2.296 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw05_ch2_ch1.png) | 42.26% | 10.65% | 3.196 | 0.309 | 0.203 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw05_ch2_ch1.png) | 42.26% | 19.84% | 3.128 | 0.176 | 0.274 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw05_ch2_ch1.png) | 42.26% | 24.84% | 3.181 | 0.253 | 0.436 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw05_ch2_ch1.png) | 42.10% | 10.81% | 3.186 | 0.299 | 0.151 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw05_ch2_ch1.png) | 100.00% | 30.65% | 2.309 | 0.105 | 1.182 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw05_ch2_ch1.png) | 100.00% | 28.55% | 3.150 | 0.097 | 1.253 |
### raw06_ch3_ch1

`data/raw/ch3.csv`，电压列 1，80,000 点，采样率 40.000 GS/s，SHA-256 `401673b77829d4b2568a4b2a9b88dc649afa926b668c6c493012d8fc30115d49`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw06_ch3_ch1.png) | 96.13% | 12.42% | 3.505 | 0.102 | 0.243 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw06_ch3_ch1.png) | 99.84% | 11.29% | 3.510 | 0.087 | 0.234 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw06_ch3_ch1.png) | 72.90% | 12.42% | 3.728 | 0.113 | 0.152 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw06_ch3_ch1.png) | 55.16% | 10.16% | 3.725 | 0.090 | 0.191 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw06_ch3_ch1.png) | 55.16% | 11.61% | 3.733 | 0.110 | 0.190 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw06_ch3_ch1.png) | 55.16% | 11.94% | 3.742 | 0.130 | 0.699 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw06_ch3_ch1.png) | 55.16% | 11.77% | 3.714 | 0.115 | 2.744 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw06_ch3_ch1.png) | 55.16% | 11.77% | 3.714 | 0.115 | 2.921 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw06_ch3_ch1.png) | 55.16% | 9.35% | 3.749 | 0.043 | 0.233 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw06_ch3_ch1.png) | 55.16% | 7.26% | 3.750 | 0.042 | 0.323 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw06_ch3_ch1.png) | 55.16% | 8.87% | 3.745 | 0.039 | 0.558 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw06_ch3_ch1.png) | 54.84% | 10.00% | 3.739 | 0.032 | 0.154 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw06_ch3_ch1.png) | 100.00% | 12.42% | 3.444 | 0.099 | 1.203 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw06_ch3_ch1.png) | 100.00% | 11.29% | 3.509 | 0.087 | 1.197 |
### raw07_ch4_ch1

`data/raw/ch4.csv`，电压列 1，80,000 点，采样率 40.000 GS/s，SHA-256 `84e2859d4285c3d3d4144ba7e5ec0b51fbc0c578857f4dfaf6209e4b87842f5b`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw07_ch4_ch1.png) | 100.00% | 11.13% | 3.173 | 0.101 | 0.237 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw07_ch4_ch1.png) | 100.00% | 10.16% | 3.064 | 0.087 | 0.233 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw07_ch4_ch1.png) | 95.32% | 11.13% | 3.421 | 0.105 | 0.181 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw07_ch4_ch1.png) | 51.13% | 10.16% | 3.587 | 0.095 | 0.237 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw07_ch4_ch1.png) | 51.13% | 10.81% | 3.268 | 0.113 | 0.209 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw07_ch4_ch1.png) | 51.13% | 11.94% | 3.322 | 0.131 | 0.662 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw07_ch4_ch1.png) | 51.13% | 11.77% | 3.313 | 0.117 | 2.503 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw07_ch4_ch1.png) | 51.13% | 11.77% | 3.313 | 0.117 | 2.650 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw07_ch4_ch1.png) | 51.13% | 8.87% | 3.245 | 0.049 | 0.216 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw07_ch4_ch1.png) | 51.13% | 7.26% | 3.752 | 0.037 | 0.309 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw07_ch4_ch1.png) | 51.13% | 8.55% | 3.317 | 0.045 | 0.475 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw07_ch4_ch1.png) | 50.81% | 8.87% | 3.260 | 0.037 | 0.164 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw07_ch4_ch1.png) | 100.00% | 11.13% | 3.173 | 0.101 | 1.252 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw07_ch4_ch1.png) | 100.00% | 10.16% | 3.064 | 0.087 | 1.164 |
### raw08_20201210m_ch1

`data/raw/PDV数据-质量中等/1/20201210m.dat`，电压列 1，40,000 点，采样率 40.000 GS/s，SHA-256 `08a8b8af06dd241f6f1b2ceb08e60f8b6b110d755b867f36935e48a28495e956`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.091 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.094 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.059 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.058 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.058 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.058 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.058 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.131 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.058 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.058 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.058 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw08_20201210m_ch1.png) | 0.00% | 0.00% | — | — | 0.058 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw08_20201210m_ch1.png) | 100.00% | 4.23% | 0.059 | 0.005 | 0.591 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw08_20201210m_ch1.png) | 100.00% | 4.23% | 0.059 | 0.005 | 0.596 |
### raw09_20201211m_ch1

`data/raw/PDV数据-质量中等/2/20201211m.dat`，电压列 1，40,000 点，采样率 40.000 GS/s，SHA-256 `b7994a2b31970daf4813583394a92556287f0eaa4aeeb1d1ec00a1f256452b84`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw09_20201211m_ch1.png) | 0.33% | 0.33% | 0.067 | 0.820 | 0.086 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw09_20201211m_ch1.png) | 0.00% | 0.00% | — | — | 0.094 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw09_20201211m_ch1.png) | 0.65% | 0.65% | 0.059 | 0.829 | 0.057 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw09_20201211m_ch1.png) | 82.41% | 71.66% | 4.788 | 0.776 | 0.128 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw09_20201211m_ch1.png) | 82.41% | 74.27% | 4.785 | 0.789 | 0.122 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw09_20201211m_ch1.png) | 82.41% | 74.27% | 4.785 | 0.790 | 0.446 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw09_20201211m_ch1.png) | 82.41% | 74.27% | 4.786 | 0.792 | 1.911 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw09_20201211m_ch1.png) | 82.41% | 74.27% | 4.786 | 0.792 | 1.953 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw09_20201211m_ch1.png) | 82.41% | 34.53% | 4.786 | 0.785 | 0.122 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw09_20201211m_ch1.png) | 82.41% | 63.19% | 4.791 | 0.702 | 0.217 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw09_20201211m_ch1.png) | 82.41% | 63.52% | 4.787 | 0.775 | 0.343 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw09_20201211m_ch1.png) | 82.08% | 30.62% | 4.786 | 0.785 | 0.084 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw09_20201211m_ch1.png) | 100.00% | 7.49% | 0.059 | 0.004 | 0.575 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw09_20201211m_ch1.png) | 100.00% | 7.49% | 0.059 | 0.004 | 0.584 |
### raw10_20201214m_ch1

`data/raw/PDV数据-质量中等/3/20201214m.dat`，电压列 1，40,000 点，采样率 40.000 GS/s，SHA-256 `06da315b9e148c8589564771e172a5d9974d6a04f59ae126ce9b724007ef0798`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw10_20201214m_ch1.png) | 0.65% | 0.65% | 0.067 | 0.981 | 0.092 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw10_20201214m_ch1.png) | 0.65% | 0.65% | 0.093 | 0.785 | 0.089 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw10_20201214m_ch1.png) | 1.30% | 1.30% | 0.060 | 0.981 | 0.059 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw10_20201214m_ch1.png) | 88.60% | 70.36% | 6.358 | 0.788 | 0.139 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw10_20201214m_ch1.png) | 88.60% | 70.03% | 6.361 | 0.839 | 0.123 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw10_20201214m_ch1.png) | 88.60% | 70.03% | 6.282 | 0.845 | 0.540 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw10_20201214m_ch1.png) | 88.60% | 70.68% | 6.314 | 0.849 | 2.106 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw10_20201214m_ch1.png) | 88.60% | 70.68% | 6.314 | 0.849 | 2.159 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw10_20201214m_ch1.png) | 88.60% | 8.47% | 6.361 | 0.843 | 0.132 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw10_20201214m_ch1.png) | 88.27% | 56.03% | 6.354 | 0.766 | 0.202 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw10_20201214m_ch1.png) | 88.60% | 61.56% | 6.292 | 0.811 | 0.328 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw10_20201214m_ch1.png) | 87.95% | 0.00% | 6.312 | 0.818 | 0.092 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw10_20201214m_ch1.png) | 100.00% | 24.43% | 0.059 | 0.006 | 0.594 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw10_20201214m_ch1.png) | 100.00% | 24.43% | 0.059 | 0.006 | 0.644 |
### raw11_20231019-ch1_ch1

`data/raw/PDV数据-质量中等/4/20231019-ch1.dat`，电压列 1，80,000 点，采样率 80.000 GS/s，SHA-256 `4ccbe54b8def8fc3b05d8b1d25eec9a8700baa91eec679c5a2b8a04d0bf3d6dc`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw11_20231019-ch1_ch1.png) | 60.97% | 60.97% | 4.101 | 0.932 | 0.207 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw11_20231019-ch1_ch1.png) | 64.03% | 63.71% | 4.098 | 0.925 | 0.201 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw11_20231019-ch1_ch1.png) | 60.32% | 60.32% | 4.101 | 0.933 | 0.134 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw11_20231019-ch1_ch1.png) | 88.87% | 66.61% | 4.087 | 0.837 | 0.253 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw11_20231019-ch1_ch1.png) | 88.87% | 67.74% | 4.088 | 0.839 | 0.253 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw11_20231019-ch1_ch1.png) | 88.87% | 67.74% | 4.061 | 0.846 | 1.088 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw11_20231019-ch1_ch1.png) | 88.87% | 67.74% | 4.081 | 0.842 | 4.267 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw11_20231019-ch1_ch1.png) | 88.87% | 67.74% | 4.081 | 0.842 | 4.501 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw11_20231019-ch1_ch1.png) | 88.87% | 46.45% | 4.086 | 0.845 | 0.286 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw11_20231019-ch1_ch1.png) | 88.87% | 59.84% | 4.094 | 0.764 | 0.390 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw11_20231019-ch1_ch1.png) | 88.87% | 65.32% | 4.052 | 0.841 | 0.708 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw11_20231019-ch1_ch1.png) | 88.71% | 46.77% | 4.087 | 0.845 | 0.167 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw11_20231019-ch1_ch1.png) | 100.00% | 60.97% | 2.465 | 0.734 | 0.785 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw11_20231019-ch1_ch1.png) | 100.00% | 63.71% | 2.670 | 0.731 | 1.077 |
### raw12_20221017a_ch1

`data/raw/PDV数据-质量中等/5/20221017a.dat`，电压列 1，80,000 点，采样率 80.000 GS/s，SHA-256 `3228766dbac4c14e960d10fc7c663cfc99f8ab7bfd8329e7ba0c7e7aa3c2c954`。

| 方法/全记录图 | 候选覆盖 | 支持覆盖 | 候选中位 GHz | 模型域R2 | 耗时 s |
| --- | --- | --- | --- | --- | --- |
| [stft512](../../../artifacts/TASK-008/stft512/figures/real/raw12_20221017a_ch1.png) | 78.06% | 76.94% | 4.415 | 0.761 | 0.221 |
| [stft768](../../../artifacts/TASK-008/stft768/figures/real/raw12_20221017a_ch1.png) | 78.87% | 75.81% | 4.416 | 0.750 | 0.210 |
| [stft512_wide](../../../artifacts/TASK-008/stft512_wide/figures/real/raw12_20221017a_ch1.png) | 76.77% | 75.81% | 4.416 | 0.770 | 0.151 |
| [gated_stft256](../../../artifacts/TASK-008/gated_stft256/figures/real/raw12_20221017a_ch1.png) | 94.19% | 76.94% | 4.408 | 0.649 | 0.248 |
| [gated_stft512](../../../artifacts/TASK-008/gated_stft512/figures/real/raw12_20221017a_ch1.png) | 94.19% | 79.52% | 4.416 | 0.657 | 0.251 |
| [dechirp](../../../artifacts/TASK-008/dechirp/figures/real/raw12_20221017a_ch1.png) | 94.19% | 79.68% | 4.416 | 0.668 | 1.114 |
| [varpro](../../../artifacts/TASK-008/varpro/figures/real/raw12_20221017a_ch1.png) | 94.19% | 78.23% | 4.416 | 0.659 | 4.585 |
| [clutter_varpro](../../../artifacts/TASK-008/clutter_varpro/figures/real/raw12_20221017a_ch1.png) | 94.19% | 78.23% | 4.416 | 0.659 | 4.728 |
| [acmd](../../../artifacts/TASK-008/acmd/figures/real/raw12_20221017a_ch1.png) | 94.19% | 40.81% | 4.413 | 0.658 | 0.347 |
| [matrix_pencil](../../../artifacts/TASK-008/matrix_pencil/figures/real/raw12_20221017a_ch1.png) | 94.19% | 64.52% | 4.369 | 0.513 | 0.494 |
| [time_domain](../../../artifacts/TASK-008/time_domain/figures/real/raw12_20221017a_ch1.png) | 94.19% | 73.55% | 4.414 | 0.644 | 0.729 |
| [baseband](../../../artifacts/TASK-008/baseband/figures/real/raw12_20221017a_ch1.png) | 94.03% | 41.13% | 4.411 | 0.664 | 0.183 |
| [legacy_m0_512](../../../artifacts/TASK-008/legacy_m0_512/figures/real/raw12_20221017a_ch1.png) | 100.00% | 76.94% | 3.678 | 0.627 | 0.831 |
| [legacy_m0_768](../../../artifacts/TASK-008/legacy_m0_768/figures/real/raw12_20221017a_ch1.png) | 100.00% | 75.81% | 3.659 | 0.612 | 1.065 |

可直接观察的例子：`20260607.csv` 第一电压列的图中，主拍频及晚期多条谱带同时可见，新方法仍有晚期候选尖峰与支持缺口。它们没有从展示中删除。没有独立实验身份信息，不能把每个更平滑的新选择写为真实纠错。所有原始记录未因曲线难看被排除；一条记录没有检测到事件时，图中保留全 NaN 的结果及原因。

## 🧭 推荐继续研究的四条路线

1. **相干杂散的显式时域 nuisance 模型＋局部实值估计。** 当前最有辨识度的新增能力是恢复强持续杂散场景的事件与目标频率；不是重做 PSD Whitening。下一次研究应专门加入杂散频率缓慢漂移、相位漂移、幅度改变，以及前缀已含运动的反例，评价误减目标和相位预测残差。当前单正弦预测不能直接转为默认自动净化器。
2. **按需局部 Dechirp，用于已可见的强连续加速。** fast_accel 的支持后 RMSE 为 3.360 m/s，短窗 256 对照 6.438，截断 512 对照 11.946；覆盖均约 99%。该优势限定到此族，双冲击和卸载会变差。下一步应按波形模型证据触发，仅在高加速度局部搜索，保留零斜率/短窗控制，避免把变点截断收益算给 Chirp 搜索。
3. **带条件数与多极值诊断的局部 VarPro。** 低速爬升的 RMSE 为 3.025 m/s，截断 512 为 9.095，覆盖分别 95.4%/95.4%；完整历史 M0 768 为 7.258 m/s、覆盖 96.4%。这是一种精度/覆盖折中，不能称全面击败长窗。后续需要自适应观测长度、显式噪声/基线模型、多起点一致性和搜索后置信度标定。80k 全记录超过 3 秒，优先作为局部精修研究。
4. **分段确定性时域反演，限定相干性与足够周期数。** 低速爬升 RMSE 2.055 m/s、覆盖 95.4%；50 m/s 压力单元的候选 RMSE 3.686 m/s、候选覆盖 99.2%。它在 15–30 m/s 和双冲击上有明确错误极值/失配，不能宣称越过不可辨识性。下一步是已知前端传递函数条件下的带边缘速度节点、相位重置与后验多模态诊断；本轮没有估计未知 AC 参数，也没有用优化器逆海森伪造可信区间。

上述只是研究优先级，不是 Production 准入建议。单模态 ACMD、短窗矩阵束和全记录基带方案保留负结果；新实现/新参数需重新跑同一全量协议。任何路线都应以廉价的截断短窗对照和原 STFT 为门槛，不能用曲线平滑或少输出代替真实性能。

## ✅ 测试、边界与复现

新增 30 个测试通过，覆盖原基准逐值一致、解析梯度、积分基函数、ACMD 符号/带状解、DC 双音、nuisance 预测、缺失计分、非均匀/NaN拒绝以及每个方法的输入字节不变性。全仓 pytest **913 通过、6 失败**，与任务前同一六项；不声称全仓通过。Ruff 和严格 mypy 正常。日志和失败名称见 `checks/validation.json`。

全部 24 个 raw/辅助文件逐文件 SHA-256 前后一致；既有 Research 源文件与 Production 代码/配置指纹核验，Git HEAD、分支、index 与既有状态保持。本轮只新增独立 Research artifact、一个测试文件，按要求更新根 README/COMPARISON 并写指定笔记。没有修改 Production、raw 或 promotion 入口，没有 commit/push。根 README 原文保留。

完整重放命令见 [README.md](README.md)。`reproduce --output <new-directory> --figures` 拒绝覆盖旧输出；`--smoke` 在独立目录重跑 12 个固定合成例并核对所有 12 个方法的轨迹。参数、实现、数据生成真值、逐点CSV/NPZ、失败和图源均保留。源码/协议与最终材料指纹在 source_freeze.json 和 checks/final_source_manifest.json。

## 📚 文献核验与结论来源

本轮 DOI/作者/卷期等元数据通过 Crossref 注册记录核验，原始响应摘录在 literature_metadata.json；没有把元数据可查等同于全文已核验。Allison 的公开 HTML 已读；其对模型失配、多峰后验和数小时采样成本的讨论不等于本轮快求解器与 MCMC 等价。Chen 的 VNCMD 本轮仅核验书目/摘要，完整论文方程复现仍 **unverified**；因此实现明确写为受启发的单模态变体。Gemini 附件里其余未使用文献的“已核实”标签没有继承，仍 unverified。所有性能数字只来源本次运行，不从文献或模型猜测搬入。

[^1]: G. H. Golub, V. Pereyra. The Differentiation of Pseudo-Inverses and Nonlinear Least Squares Problems Whose Variables Separate. SIAM Journal on Numerical Analysis 10(2), 413–432 (1973). [DOI](https://doi.org/10.1137/0710036)。另见 [2003 review](https://doi.org/10.1088/0266-5611/19/2/201)，书目已核验，付费全文未完整核验。

[^2]: S. Chen, X. Dong, Z. Peng, W. Zhang, G. Meng. Nonlinear Chirp Mode Decomposition: A Variational Method. IEEE Transactions on Signal Processing 65(22), 6024–6037 (2017). [DOI](https://doi.org/10.1109/TSP.2017.2731300)。书目/摘要已核验，完整方法复现 unverified。

[^3]: J. R. Allison et al. A Bayesian approach to time-domain photonic Doppler velocimetry analysis (2025). [DOI](https://doi.org/10.1063/5.0267409)，[作者公开全文](https://arxiv.org/html/2508.13695v1)。该文报告时域概率反演及模型/计算限制；本文确定性变体是独立研究实现。

D. H. Dolan. Accuracy and precision in photonic Doppler velocimetry (2010). [DOI](https://doi.org/10.1063/1.3429257)。书目已核验；本轮噪声/窗长/前端限制由自己的合成与代码检查衡量，不冒称已完整复现该文理论误差界。
