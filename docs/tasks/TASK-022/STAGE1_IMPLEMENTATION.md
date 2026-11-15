# TASK-022 Stage 1：纯 Core 诊断引擎

日期：2026-11-14  
执行 Agent：Codex  
仓库：D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN  
分支：codex/research_2/global-path-ridge-v2  
HEAD：4eeed35a9e8bea63ba57ba46fdd85f90f92bb729  
状态：Stage 1 完成；未提交 Git。

## 新增文件

- src/dps_studio/core/diagnostics/__init__.py
- src/dps_studio/core/diagnostics/models.py
- src/dps_studio/core/diagnostics/explanations.py
- src/dps_studio/core/diagnostics/engine.py
- src/dps_studio/core/diagnostics/frozen_loader.py
- tests/unit/test_task022_diagnostics_core.py
- docs/tasks/TASK-022/STAGE1_IMPLEMENTATION.md

Obsidian 日志：D:\Research\Notes\05项目\dps\2026-11-14_TASK-022_Stage1_纯Core诊断引擎.md。

## 实现与数学口径

计算直接复用现有 formal STFT、segmentation strategies 与 waveform 模块。
候选归一化、256 点证据、聚类、S0/S1/S2 投票逐式移植自 TASK-017/018。
S2 保留家族在全部 C 簇间分摊的预算、频带适用性分母、代表候选优先级及
次级 Matrix Pencil 极点；不平均频率，不引入轨迹先验。

- FAST_CORE：B0、B1、Dechirp、VarPro 与 B+S；不发布 S2。
- FULL_S2：8 个估计器、9 个候选行/帧（含次级极点），输出 S2 与全部簇摘要。
- PRECOMPUTED_STACK：仅由 frozen_loader 读取可选冻结 CSV；缺文件返回 None。
- 核心只依赖 stdlib、NumPy、SciPy 及现有 core/waveform；实时计算不读取 artifacts。
  独立子进程禁止导入 PySide6、pyqtgraph、matplotlib、pandas、tkinter、
  dps_studio.research、scripts 后，导入与 FAST_CORE 计算均通过。
- 当前实际 I/O API 为 dps_studio.core.io.read_delimited_signals；
  通过相同严格读取器保留无表头文件第一行、列号、单位缩放及导入元数据。
- 当前 spec 显式 excludes 含 matplotlib、tkinter、dps_studio.research，
  未显式列出 pandas；本任务不改 spec，诊断包也不导入 pandas。

冻结 curves.csv.gz 原本没有 B+S、Dechirp、VarPro 行。
B0/B1 采用 TASK-018 候选曲线：selected=C，frequency_hz 为带内候选，G 单列保留。
TASK-020 的原生发布 A/B 可取 where(G, frequency_hz, NaN)。
B+S 为 B1.frequency_hz where S；Dechirp/VarPro 从候选表构造同口径候选曲线，
对应原 estimator 标识 dechirp/varpro。S2 的 C 是提议存在，selected 是 S 投票选择；
proposal_hz 保留未通过 S 的提议。被拒原因始终可在候选表查看。

背景严格沿用历史公式：
min(4096, searchsorted(time_s, onset.start_range_s[0] - 2 ns))。
StageSegment 保留可选 start_range_s，以便完整重放；没有视觉 onset 时，
明确采用 TASK-018 的固定前缀对照 min(N//20, 2048)，不声称该前缀已验证静默。
也可显式传入 background_stop_index。原参考文件没有 DEFAULT_BACKGROUND 常量，
未臆造一个历史默认值。视觉分段不会覆盖 waveform 原生自动事件触发。

证据谱保留 50 MHz–8 GHz 历史诊断带、对称 np.hanning、degree=1 Legendre
基线和 fit_tone 的投影最小二乘。显示谱使用周期 Hann：
原始 W1024 / 去均值 W512，H128、NFFT4096；同步至共同原样本中心，
不完整窗口保留 NaN。power_db 形状为 (n_frequency, n_time)，
默认显示上限 min(Nyquist, 10 GHz)，独立于 50 MHz–6 GHz 评估带。

LocalFrameEvidence 返回真实投影拟合、基线与残差，不用示意正弦代替模型。
历史 local_psd_db / background_psd_db 字段实际上是未归一化 FFT 功率的 dB，
不是每 Hz 谱密度；512 点检查也保留实际窗口周期跨度，不冒充冻结 256 点 S。

## 验证结果

所有命令经 scripts/dev/run.ps1 -Task TASK-022，
使用 D:\miniconda3\envs\dps-studio\python.exe（Python 3.12.13）。
缓存、JUnit 与运行指标均在 artifacts/TASK-022/tmp/。

| 检查 | 结果 |
|---|---|
| TASK-022 最终核心测试 | 40 passed，0 skipped，52.780 s |
| TASK-022 + TASK-017/018 + stage strategies + STFT 合并回归 | 139 passed，0 skipped，61.303 s |
| Ruff check / format --check | 通过，6 个 Python 文件格式一致 |
| mypy strict | 通过，6 个文件 |
| repo hygiene / staged-only | 通过，无 findings |

真实数据重放使用精确数组相等断言，包括 NaN 位置，未放宽容差：

| 通道 | 样本数 / 共同中心 | FULL_S2 计算时间 | 对比结果 |
|---|---:|---:|---|
| 20201210m_ch1 | 40000 / 313 | 9.282 s | 六曲线、全部候选字段、全部簇摘要完全一致 |
| ch3_ch1 | 80000 / 625 | 22.270 s | 六曲线、全部候选字段、全部簇摘要完全一致 |

时间为最后一次 compute 调用本身，不含读取 raw、冻结参照与断言开销。
同机不同轮次受系统调度影响；此前计算分别约 6 s、14 s，不作固定延迟保证。
ch3 冻结完整 bundle 加载三次为 0.356 / 0.371 / 0.380 s，
包括解析、双背景谱和解释，不含调用前 raw 读取与模块导入。

关键帧：
- 20201210m：原始 B0 低频无 S、B1 高频有 S 的 DC 泄漏场景实际存在。
- ch3，q=42752：B0/B1 约 3.67/3.66 GHz 未通过 S；
  Dechirp 3.413572 GHz，Tone R²=0.151315、Chirp R²=0.452000，通过 S；
  VarPro 对应指标也与冻结候选逐项精确一致。
- 20260630-1_ch2，q=130176：相对采集起点 3254.4 ns，
  绝对时间 0.00074720841499 s；B+S 0.507340 GHz、S2 0.361573 GHz，
  两者均有 S，存在竞争支路。不能把展示用相对 ns 当成绝对时间。
- ch3 冻结阶段不含 decline；decline 筛选在 20201210m 及合成数据验证，
  未增改视觉标注。

证据文件：
- artifacts/TASK-022/tmp/verification.xml
- artifacts/TASK-022/tmp/stage1_final.xml
- artifacts/TASK-022/tmp/parity_20201210m_ch1.json
- artifacts/TASK-022/tmp/parity_ch3_ch1.json
- artifacts/TASK-022/tmp/load_timings.json
- artifacts/TASK-022/tmp/static_checks.json
- artifacts/TASK-022/tmp/boundary_before.json
- artifacts/TASK-022/tmp/boundary_after.json

## 边界与适用范围

边界核验全部通过：raw 全文件哈希、TASK-017 数据与 TASK-018 stack_v1 哈希、
9 个保护文件、所有既有 src 文件、Research HEAD/index 均保持一致。
Production 未写入；其 src 哈希及 Git HEAD/status/staged 状态保持一致。
历史 task017/018/020、physics、analysis_profiles.py、configs 与 .gitignore 无 diff。
仅新增上述源码、测试、报告、任务产物及指定 Obsidian 日志；未操作 junction，
未 commit、push、merge、清理 Git 或更改默认算法。

数据结构为 frozen/slots；数组采用不可写快照。输入缺失/非均匀波形明确拒绝，
输出缺测保留 NaN 与质量状态。取消在估计器、阶段边界和证据/显示批次间检查；
现有单次估计器内部调用完成前不能强制抢占，应由未来 GUI worker 调用。

S=True 是局部、样本内的正弦/Chirp 支持，不确认物理主目标身份，
也不是独立精度验证。多支路竞争与无 S 高共识均保留。
下一步：另行实现 Stage 2 GUI 接入；本次不改 GUI。

