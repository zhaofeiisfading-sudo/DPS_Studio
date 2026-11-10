# 当前实现与 TASK-015 审计

所有频率/时间来自当前真实原始波形。无独立测速真值，证据支持、门控通过和物理支路身份分开；`requires experimental confirmation` 适用于全部支路。没有用任何合成信号选择参数或验收。

核心拥有者：`core/segmentation/pool.py` 的 `_stft/_frozen/default_pool`；`core/workflow/analysis.py::_build_working_ridge`；`core/quality/detection.py`；`core/segmentation/strategies.py::estimate_strategy`；`algorithms/waveform/common.py::Context/finish`；`scripts/research/task015/real.py/experiment.py`；`task014/study.py::route`。逐文件内容哈希见 [owning_source_hashes.json](../../../artifacts/TASK-017/data/forensic_v01/owning_source_hashes.json)。TASK-008～015 的报告、当前源文件、TASK-016 数据迁移记录已交叉检查；没有执行其合成生成器。

正式 STFT 是 Hann 1024/H64/NFFT4096，原样不去 DC；峰值后用三点对数幅值亚频点精修。refinement 失败可以在 working ridge 保留原离散 bin，但 formal gated 仍是 NaN。门控包含峰/背景、竞争峰、周期数、谱边界和连续帧建立/重捕获；原 formal 参数阈值详见 owning source。working candidate 与 gated refined velocity 是不同数组，不能因为 formal 没显示就断言算法没算出候选。

当前策略引擎在频谱初始化前投影常数/线性或二次基线，段内裁剪支撑；mode=band/glrt 限低频 ≤250 MHz，GLRT 在有足够高频谱峰时局部投影 nuisance。正弦精修对真实 cos/sin 拟合，Dechirp 为有限 chirp bank，VarPro 为频率+线性 chirp 非线性优化/线性系数投影；它们都不是额外的物理真值。长支撑 2048/4096 样本不因输出 hop 小而获得更高时间分辨。

旧 Dechirp/VarPro/ACMD/Matrix Pencil/时域实现先依赖 `Context.event_detector`：未触发事件，或中心在其之前时，生成循环直接跳过。`finish` 之后还以原始 256 样本支撑的 R²、条件数、对比度及事件规则作门控。Clutter VarPro 会在内存中预测单一前缀正弦、重新创建 Context；本批 14/14 前缀 R² 未达 0.45，全都返回 NO_STRONG_COHERENT_PREFIX_TONE。因此其原生结果与 VarPro 相同，不能声称本批验证了背景扣除的优越性，也没有本批目标已在前缀而被错误扣除的实证；该风险仍来自实现假设。

TASK-015 `real.py` 只实际执行 M1、短窗、长窗、GLRT、tone_refine、Clutter VarPro 六项。整条阶段为 unknown，报告写 M2/M3/M4=M1 是按映射定义推导，不是对人工真实阶段逐条运行后的优胜结果。其总体排名来自另一套合成实验；本轮没有拿那个排名选真实优胜者。

下表重新读取旧真实 NPZ 中与当前 raw 相匹配的 14 通道，分母 9475 个旧共同中心；不是新数据，也没有包括补充目录三通道。

| method | centers | candidate_n | gated_n | gate_rejected_n | no_candidate_n |
| --- | --- | --- | --- | --- | --- |
| M1_balanced | 9475 | 9475 | 5244 | 4231 | 0 |
| stft_short | 9475 | 9475 | 5418 | 4057 | 0 |
| stft_long | 9475 | 9475 | 4720 | 4755 | 0 |
| low_glrt | 9475 | 9475 | 158 | 9317 | 0 |
| tone_refine | 9475 | 9475 | 4927 | 4548 | 0 |
| clutter_varpro | 9475 | 6229 | 5300 | 929 | 3246 |

例如旧 GLRT 9475 个候选、158 个通过，9317 个是门控拒绝，不能写作 9317 次算法计算失败。旧 M1 9475 候选、5244 门控通过、4231 被拒绝。完整质量类别保存在 forensic_v01。

本轮每个方法保留 native 时间/候选/门控/质量/详细拟合，整数采样中心对齐到 128 样本网格，无频率插值。主要比较只取 1024≤sample≤N−1024，避免完整记录边缘对长窗不公平；原生边缘和无中心状态仍留在 CSV。H64 的 formal 门控先在原生 H64 上执行，再抽取共同 H128 中心，不能将其连续帧规则误认为和 H128 门控相同。

首轮脚本路由未完全恢复用户 6 GHz band，本轮分析从未删掉的组件重组 M2/M3/M4，对 frozen 组件执行 50 MHz–6 GHz gate、对全部路由执行 6 GHz ceiling；full_v01 原样留档。最终分析为 analysis_v03；analysis_v02 与其所有绘图使用字段逐元素相同。

结论：TASK-015 的默认是安全策略，不能据其真实部分论证所有实际阶段 STFT 最优。真实数据上的 DC 泄漏和事件生成跳过是本轮确认的两个遗漏机制；不需要重构 GUI 或正式默认值才能检验。


## 20201210m 背景前缀重叠复核

当前 Context 的背景前缀为 4000 点（约 100.0 ns）；冻结视觉起跳位于第 2192 点（约 54.8 ns）。前缀中有 1808 点处于该边界之后，约占 45.2%。因此 quiet-prefix 假设在本案例被视觉证据直接违反，原自动能量检测确实返回 NO_CONFIRMED_ENERGY_CHANGE。混入 DC 变化和已建立振荡会改变它估计的背景尺度和阈值，是整条不生成候选的明确机制线索；没有额外做因果标定或篡改原波形。Clutter VarPro 此例前缀拟合未达扣除门槛，故不是目标被相干扣除的实证。完整数值见 [prefix_overlap.json](../../../artifacts/TASK-017/data/prefix_overlap.json)。
