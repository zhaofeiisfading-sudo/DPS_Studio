# 局部 Dechirp

强加速族有净收益；卸载、低速、双冲击和弱信号没有整体优势。不是精确实值似然。

## 📊 实际结果与限制

- 新种子主评价：96 波形，其中 88 条含运动；运动目标共 6952 帧，支持后有限 5722 帧。
- 支持后有限 RMSE **14.238 m/s**，覆盖 **82.31%**，全分母失败率 **17.88%**。有限 RMSE 不能脱离覆盖率解释。
- 全部 13 原始文件、17 电压列已运行，执行异常 0；没有真实 GT，不报告真实正确率。
- 当前统一 harness 的 80k 点耗时中位数 0.857 s，最大 1.114 s；包含公共初始化和支持检查，不含画图。

## 📁 可复核产物

| 文件 / 目录 | 含义 |
| --- | --- |
| [implementation.py](../../../../../src/dps_studio/algorithms/waveform/dechirp/implementation.py) | 实际运行的实现，冻结指纹在上级 source_freeze.json |
| [parameters.json](../../../../../artifacts/TASK-008/dechirp/parameters.json) | 全部方法超参数，共同背景/支持门槛另见 PROTOCOL.md |
| [fresh_metrics.csv](../../../../../artifacts/TASK-008/dechirp/fresh_metrics.csv) | 逐合成波形、各区域、候选/支持后完整计数与误差 |
| [phase_stress_metrics.csv](../../../../../artifacts/TASK-008/dechirp/phase_stress_metrics.csv) | 全部 50 条低速随机初相压力结果 |
| [real_metrics.csv](../../../../../artifacts/TASK-008/dechirp/real_metrics.csv) | 全部真实通道的观测诊断；无准确率 |
| [failure_records.json](../../../../../artifacts/TASK-008/dechirp/failure_records.json) | 固定评价的最差实例与失败诊断选择口径 |
| [real_limitations.json](../../../../../artifacts/TASK-008/dechirp/real_limitations.json) | 未检测事件/没有支持输出的真实记录，不能解释为零速 |
| [tests_results.json](../../../../../artifacts/TASK-008/dechirp/tests_results.json) | 方法输入不变性和相关数值契约验证 |
| runs/fresh、runs/phase_stress、runs/real | 各案例轨迹 NPZ、细节 JSON；real 另含逐点 CSV |
| figures/real | 每条真实通道的原谱图、频率假设、等效速度和支持统计 |
| figures/synthetic | 每族预先固定第 0 条的真值与误差图，失败例不替换 |

真实图的速度只按假设 1550 nm 换算，物理波长/参考频移未核验；corrected_velocity_m_s 全为 NaN。`accepted_hz` 是启发式支持后的假设，不是校准的测量通道。

共同协议见 [PROTOCOL.md](../../PROTOCOL.md)，完整对照与逐真实数据表见根目录 [COMPARISON.md](../../COMPARISON.md)。本方法没有进入 Production。
