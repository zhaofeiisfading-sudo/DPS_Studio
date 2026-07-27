# TASK-013A-R：多通道、多 profile 事件候选共识与预览语义修正

## 1. 开始前审计

修改前仓库状态为：

- `HEAD`: `11b761fe49550f22e7430f939f2bedb87826c345`
- branch: `main`
- staged area: empty
- tracked worktree diff: 18 files, 2,079 insertions, 806 deletions
- worktree 同时含未提交 TASK-013 和更早的用户改动；大量 `presentation/`、
  `presentations/`、docs 材料为既有未跟踪内容，本任务未触碰。

TASK-013 修改前质量门：

- pytest: 296 passed；唯一警告为 `.pytest_cache` 的 Windows ACL
- Ruff: passed
- mypy: strict mode, 41 source files passed

原始文件 `data/raw/20260607.csv`：

- size: 3,792,364 bytes
- samples: 80,000
- time range: `553.96025426–555.96022926 µs`
- median sample interval: `25.0000000085 ps`
- inferred sample rate: `39.9999999864 GHz`
- SHA-256:
  `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`

Profile 审计：

| Profile | Window | Window duration | Overlap | Hop | Hop duration | NFFT | Bin spacing | Configured search | Actual search-grid centers |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Balanced | 768 | 19.2 ns | 640 | 128 | 3.2 ns | 4096 | 9.765625 MHz | 50–2,000 MHz | 58.59375–1,992.1875 MHz |
| High time resolution | 512 | 12.8 ns | 384 | 128 | 3.2 ns | 4096 | 9.765625 MHz | 50–2,000 MHz | 58.59375–1,992.1875 MHz |

原始通道统计：

| Channel | Range (V) | Peak abs (V) | Full RMS (V) | Pre-reference RMS (V) | Pre-reference MAD (V) | Clipping audit |
|---|---:|---:|---:|---:|---:|---|
| pdv_channel_1 | -0.083918363–0.076014780 | 0.083918363 | 0.02537915 | 0.00088085 | 0.00053747 | 极值无连续平台；没有明显削顶证据，但缺少仪器量程，不能证明绝对无削顶 |
| pdv_channel_2 | -0.188745156–0.208163261 | 0.208163261 | 0.07226918 | 0.00169823 | 0.00102751 | 正最大值精确重复 303 次、最长连续 6 点；存在明显正向削顶嫌疑，需量程/ADC rail 元数据确认 |

修改前 `detected_event_candidate_time_s` 在
`src/dps_studio/core/quality/detection.py` 中由第一个最终 `MEASURED`
连续段直接产生。`minimum_consecutive_frames=3` 会将更短的 provisional
`MEASURED` 段改成 `UNSTABLE_DETECTION`，因此它同时影响正式
`signal_state`、正式 refined frequency、正式 apparent/discrete velocity、
display origin 和旧兼容候选。本任务没有改变该参数。

修改前 full preview 对每个 STFT 帧都取固定搜索带内的 argmax；正式
`MEASURED` 帧复用 refined frequency，其余帧使用离散 argmax。绘图函数把
所有有限 preview 点连接为一条红线，因此
`PEAK_AT_BAND_BOUNDARY`、`NO_DETECTABLE_BEAT`、`AMBIGUOUS_PEAK` 和
`REFINEMENT_FAILED` 都可能被视觉上误解为连续物理曲线。

12-bin guard 的实际实现为：

\[
\Delta f_\text{guard,half}=(12+0.5)\Delta f
=122.0703125\ \text{MHz}.
\]

两个 profile 因 NFFT 相同而具有相同 Hz guard，但 Hann 主瓣第一零点间宽度
近似为 \(4f_s/N\)：Balanced 为 208.333 MHz，High time 为 312.5 MHz。
完整 guard 宽度与主瓣宽度之比分别为 1.171875 和 0.78125，故固定
12 bins 并不具有相同的主瓣倍数含义。

## 2. 当前四流差异的真实原因

四流使用同一原始事件、同一 NFFT 和同一 hop，但 window length 不同，
因此时间支撑、周期能力、Hann 主瓣宽度和 guard/主瓣比例不同。通道的原始
幅度和背景也不同，pdv_channel_2 还存在正向削顶嫌疑。这些差异共同造成
相同 10 dB、3 dB 和 12-bin 配置下不同的前置状态分布。

人工参考前的 measured 比例为：

- Balanced/ch1: 2.283%
- Balanced/ch2: 0.457%
- High/ch1: 0.455%
- High/ch2: 0%

对应 band-boundary 比例为 9.589%、43.379%、56.364% 和 88.182%。
因此 High/ch2 的“干净前置”主要来自边界拒绝，而不是证明该 profile
绝对更正确。

Balanced/ch1 的早期段有 3 帧，频率为 1,797.8–1,821.8 MHz，
相邻最大步进 16.5 MHz，峰/背景中位数 13.41 dB，峰/竞争峰中位数
5.20 dB。它恰好满足 TASK-013 的全部逐帧阈值和 3 帧连续门，旧实现又只取
第一段，所以被当成流内首候选。没有代码错误；缺少的是独立的事件级持续性
和多流支持层。

## 3. 修改文件

TASK-013A-R 的修改范围：

- `src/dps_studio/core/event_candidates.py`：新建纯 core 连续段、事件资格、
  同 profile 跨通道共识、跨 profile 共识模型与函数。
- `src/dps_studio/core/workflow/analysis.py`：在正式逐帧分析完成后构建独立
  stream event metadata。
- `src/dps_studio/core/workflow/models.py`：`ChannelAnalysis` 增加不可变
  `stream_event_candidates`。
- `src/dps_studio/core/workflow/config.py`：加载独立 `[event_candidate]` 和
  `[event_consensus]`。
- `src/dps_studio/core/quality/models.py`：明确 `MEASURED` 和旧 TASK-013
  首段字段的兼容语义。
- `src/dps_studio/core/__init__.py`：导出新 public core API。
- `configs/demo_dual_profile.toml`：增加显式 development-default 事件层参数。
- `scripts/production_outputs.py`：输出完整段表、共识、敏感性、阈值审计、
  状态分层 preview 和新增图表。
- `README.md`：更新正式工作流及 `MEASURED` 语义。
- `tests/unit/test_event_candidates.py`：新建事件层合成测试。
- `tests/unit/test_workflow_analysis.py`：增加事件配置与正式数组解耦测试。
- `tests/unit/test_workflow_config.py`、`tests/unit/test_production_outputs.py`：
  更新配置和输出契约测试。
- 本报告。

没有修改 `data/raw`，没有修改 TASK-013 的正式检测阈值。

## 4. 连续段数据模型

`SpectralDetectionSegment` 是 frozen/slots 不可变模型。它只枚举最终
`SignalState.MEASURED` 的严格相邻帧；遇到任何非 MEASURED 状态或 NaN
间隙即断段，不插值、不桥接、不合并。

主要字段包括：

- profile/channel/segment ID
- inclusive start/end frame index
- first/last frame-center time
- frame count
- span duration
- support duration
- start/median/minimum/maximum frequency
- maximum adjacent frequency step
- peak/background 和 peak/competitor 的 median/minimum
- `physical_branch_review_status=unreviewed`

时间定义：

- `span_duration_s = end_frame_center - start_frame_center`
- `support_duration_s = span_duration_s + window_duration_s`

因此 Balanced 的 3 帧段：

- frame-center span: \(2\times3.2=6.4\) ns
- overlapping-window support union: \(6.4+19.2=25.6\) ns

两者都不是已确认的物理事件持续时间。

## 5. 单流事件候选规则

独立 `EventCandidateConfig` development defaults：

| Parameter | Value | Role |
|---|---:|---|
| minimum_segment_frames | 8 | 事件级帧数 |
| minimum_segment_duration_s | 20 ns | 首末帧中心跨度 |
| maximum_adjacent_frequency_step_hz | 100 MHz | 事件级频率路径连续性 |
| minimum_median_peak_to_background_db | None | 不重复施加 10 dB 正式门 |
| minimum_median_peak_to_competitor_db | None | 不重复施加 3 dB 正式门 |

拒绝原因可以同时出现：

- `segment_too_short`
- `segment_duration_too_short`
- `frequency_path_unstable`
- `insufficient_event_level_contrast`
- 合格时唯一状态为 `eligible`

每流的 primary candidate 是该流最早的 event-level eligible 段，不再等于
最早的谱检测段。旧 `SignalDetectionResult.detected_event_candidate_*`
保留为明确标记的 TASK-013 compatibility metadata，不再用于共识。

敏感性审计覆盖 3/0 ns、5/10 ns、8/20 ns、12/30 ns 和 50/100/200 MHz。
所有六组变体得到相同最终跨 profile 候选
`554.6674542602 µs`。即使采用 permissive 3-frame 配置使早期段再次成为
Balanced/ch1 的 stream primary，因其没有另一通道同期支持，最终共识仍
选择主事件附近的后续段。

## 6. 跨通道共识

同 profile 内对两个通道的全部 eligible segments 做笛卡尔配对，不只比较
各通道第一段。一个 pair 必须同时满足：

1. 起始帧中心差不超过 25 ns，或 frame-center interval overlap fraction
   不低于 0.5；
2. 两段 start-frame refined frequency 差不超过 150 MHz。

若有多个 compatible pair，选择 `max(two start times)` 最早者，再依次用
start-time difference 和 start-frequency difference 决胜。候选时间为两个
支持段 start-frame centers 的算术平均。这里没有平均电压、频率轨迹或速度。

若只有一路有 eligible 段，结果为 `single_channel_only` 且 candidate time
为 `None`；人工参考时刻不参与选择。

真实结果：

| Profile | Supporting segments | Start difference | Start-frequency difference | Overlap fraction | Profile candidate | Status |
|---|---|---:|---:|---:|---:|---|
| Balanced | ch1 segment_002 + ch2 segment_001 | 3.2 ns | 27.117 MHz | 0.996865 | 554.6658542602 µs | dual_channel_consensus |
| High time | ch1 segment_001 + ch2 segment_001 | 3.2 ns | 32.553 MHz | 0.996855 | 554.6690542602 µs | dual_channel_consensus |

Balanced/ch1 segment_001 没有成为 supporting segment。

## 7. 跨 profile 共识

两个 profile 的 dual-channel candidate 使用独立的 25 ns
`cross_profile_time_tolerance_s`。不以人工时刻平移或校正任何候选。

真实结果：

- Balanced profile candidate: `554.6658542602 µs`
- High time profile candidate: `554.6690542602 µs`
- spread: `3.2000000011 ns`
- final candidate: `554.6674542602 µs`
- status: `cross_profile_consensus`
- difference from manual reference: `-0.5457397588 ns`

最后一项只在候选选择完成后计算，是诊断量。

## 8. Preview 语义修正

`apparent_velocity_full_preview.png` 现在始终使用 fixed search band 的
离散 argmax，不再在正式帧偷偷复用 refined frequency。正式结果仍单独以
蓝线显示。

图例严格标记：

`quality-unfiltered argmax preview; not a measurement`

连接规则：

- 只有连续 `MEASURED` 状态的 argmax diagnostic 可以形成红色分段线；
- boundary、no-detectable、ambiguous、refinement-failed、
  insufficient-cycles、unstable 和 outside-window 分别使用不同 marker；
- 状态之间不桥接；
- 正式 apparent velocity 保持原有 NaN 间隙；
- 没有时间插值或自动前置零。

图中显式给出：

`lower-bound argmax is not zero velocity`

High/ch2 人工参考前 220 帧中：

- 194 帧 `PEAK_AT_BAND_BOUNDARY`
- 19 帧 `NO_DETECTABLE_BEAT`
- 7 帧 `AMBIGUOUS_PEAK`
- 0 帧正式 `MEASURED`
- 218 帧 unfiltered argmax 位于 58.59375 MHz
- 对应 preview apparent velocity 为 45.410156 m/s
- 所有正式 pre-reference apparent velocity 仍为 NaN

45.410156 m/s 没有被标为零或写入正式速度。

## 9. 阈值可迁移性审计

表中对比度为 p05/median/p95，均是 magnitude contrast，不是 formal SNR。

| Stream | Region | Peak/background dB | Peak/competitor dB | Boundary frac. | Ambiguous frac. | Measured frac. | Lower-grid argmax frac. |
|---|---|---:|---:|---:|---:|---:|---:|
| balanced/1 | pre | 8.10/10.98/14.09 | 0.22/1.72/4.38 | 0.096 | 0.507 | 0.023 | 0.534 |
| balanced/2 | pre | 7.43/10.94/14.41 | 0.35/3.07/6.36 | 0.434 | 0.219 | 0.005 | 0.886 |
| high/1 | pre | 9.16/12.55/16.35 | 0.36/3.73/7.10 | 0.564 | 0.327 | 0.005 | 0.895 |
| high/2 | pre | 9.74/13.63/16.62 | 2.41/6.25/9.69 | 0.882 | 0.032 | 0.000 | 0.991 |
| balanced/1 | plateau | 51.85/53.80/55.30 | 12.65/13.46/18.48 | 0 | 0 | 1.000 | 0 |
| balanced/2 | plateau | 54.49/56.79/58.30 | 18.89/19.62/24.61 | 0 | 0 | 1.000 | 0 |
| high/1 | plateau | 46.92/48.59/50.37 | 12.66/13.50/17.98 | 0 | 0 | 1.000 | 0 |
| high/2 | plateau | 49.74/51.34/52.84 | 17.23/17.88/18.78 | 0 | 0 | 1.000 | 0 |
| balanced/1 | decline | 22.39/30.16/54.41 | 6.07/12.67/20.35 | 0 | 0 | 1.000 | 0 |
| balanced/2 | decline | 36.81/48.48/57.19 | 14.88/22.95/26.97 | 0 | 0 | 1.000 | 0 |
| high/1 | decline | 19.48/27.96/49.17 | 5.76/12.32/18.86 | 0 | 0 | 1.000 | 0 |
| high/2 | decline | 34.80/43.48/52.06 | 14.89/17.42/18.82 | 0 | 0 | 1.000 | 0 |
| balanced/1 | tail | 13.38/23.52/40.77 | 1.89/12.21/23.40 | 0 | 0.070 | 0.911 | 0.006 |
| balanced/2 | tail | 13.46/26.17/44.74 | 1.12/9.28/25.02 | 0 | 0.108 | 0.854 | 0 |
| high/1 | tail | 12.12/21.05/38.49 | 1.34/8.70/20.12 | 0.013 | 0.133 | 0.823 | 0.057 |
| high/2 | tail | 12.78/24.00/43.06 | 0.50/6.77/18.00 | 0.025 | 0.184 | 0.772 | 0.114 |

结论：

1. 10 dB/3 dB 对主平台和下降段均保留 100%，但人工参考前的假阳性、
   boundary 和 ambiguous 行为明显不同，不能称为四流等价行为。
2. 固定 12 bins 在两个 profile 中有相同 122.07 MHz half-width，但只相当于
   不同的 Hann 主瓣倍数。
3. 后续有依据比较 Hz guard、Hann 主瓣宽度倍数或 profile-specific guard；
   本轮没有改正式 guard。
4. High/ch2 前置“漂亮”主要是 boundary rejection：88.18% 帧为 boundary，
   99.09% argmax 落在 lower grid。只有 8.64% 为 no-detectable，3.18% 为
   ambiguous。
5. Balanced/ch1 早期段通过是因为三个连续帧真实越过现有 10/3 dB、
   boundary、cycle 和 refinement 规则，不是因为人工参考门或隐藏插值。

## 10. 合成测试

新增测试覆盖：

- 多个分离 MEASURED 段和单帧 NaN/状态缺口不合并；
- 3 帧强段被枚举但事件级拒绝；
- 固定种子瞬态强噪声段拒绝；
- 长稳定单频段通过；
- 80 MHz 低频稳定长段通过；
- 固定种子长随机跳频段因路径不稳定拒绝；
- 相近双通道段形成 profile consensus；
- 时间差过大不形成 consensus；
- single-channel-only 不产生候选时间；
- 两通道各有不同早期段、后续有共同段时找到后续段；
- compatible profiles 形成 cross-profile consensus；
- 只有一个 profile 支持时状态正确；
- manual reference 变化只改变诊断差；
- EventCandidateConfig 变化不改变正式逐帧数组；
- lower-bound preview 为正值而非零；
- 状态分层生产图可生成并读取；
- 原 TASK-013 测试全部继续通过。

## 11. 真实四流结果

完整 machine-readable 表：
`outputs/task013ar_validation/run_task013ar_20260726/measured_segments.csv`。

表中 start 是相对人工参考的诊断时间；频率为 min/median/max；P/B 和 P/C
为 median/minimum。

| Profile | Ch | ID | Start (µs) | Frames | Span (ns) | Support (ns) | Frequency (MHz) | Max step (MHz) | P/B (dB) | P/C (dB) | Eligible | Reason |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| balanced | 1 | 001 | -0.586146 | 3 | 6.4 | 25.6 | 1797.8/1805.3/1821.8 | 16.5 | 13.41/11.78 | 5.20/3.49 | False | segment_too_short; segment_duration_too_short |
| balanced | 1 | 002 | -0.003746 | 320 | 1020.8 | 1040.0 | 152.1/714.4/739.4 | 44.4 | 51.28/18.83 | 13.55/4.14 | True | eligible |
| balanced | 1 | 003 | 1.026654 | 12 | 35.2 | 54.4 | 850.9/854.8/868.9 | 9.2 | 24.59/15.10 | 10.16/4.74 | True | eligible |
| balanced | 1 | 004 | 1.068254 | 10 | 28.8 | 48.0 | 829.5/870.8/886.5 | 26.3 | 18.00/12.30 | 8.35/4.43 | True | eligible |
| balanced | 1 | 005 | 1.109854 | 3 | 6.4 | 25.6 | 817.6/820.1/820.5 | 2.5 | 14.79/13.69 | 4.43/3.89 | False | segment_too_short; segment_duration_too_short |
| balanced | 1 | 006 | 1.132254 | 6 | 16.0 | 35.2 | 860.1/869.4/877.6 | 9.2 | 18.04/15.02 | 6.49/4.45 | False | segment_too_short; segment_duration_too_short |
| balanced | 1 | 007 | 1.164254 | 38 | 118.4 | 137.6 | 830.4/863.1/881.5 | 16.7 | 22.13/14.79 | 11.98/3.38 | True | eligible |
| balanced | 2 | 001 | -0.000546 | 322 | 1027.2 | 1046.4 | 151.8/711.8/739.4 | 31.5 | 54.80/23.84 | 19.60/3.33 | True | eligible |
| balanced | 2 | 002 | 1.045854 | 4 | 9.6 | 28.8 | 855.0/857.8/861.4 | 3.3 | 22.63/21.02 | 4.00/3.63 | False | segment_too_short; segment_duration_too_short |
| balanced | 2 | 003 | 1.081054 | 6 | 16.0 | 35.2 | 865.9/869.8/893.0 | 13.9 | 20.43/15.61 | 8.22/4.44 | False | segment_too_short; segment_duration_too_short |
| balanced | 2 | 004 | 1.109854 | 3 | 6.4 | 25.6 | 816.9/818.4/828.5 | 10.1 | 15.71/14.64 | 4.56/3.87 | False | segment_too_short; segment_duration_too_short |
| balanced | 2 | 005 | 1.129054 | 6 | 16.0 | 35.2 | 860.8/870.2/877.0 | 7.1 | 19.51/16.77 | 7.71/3.77 | False | segment_too_short; segment_duration_too_short |
| balanced | 2 | 006 | 1.164254 | 38 | 118.4 | 137.6 | 823.0/863.6/878.2 | 32.7 | 22.37/13.57 | 10.95/3.33 | True | eligible |
| high | 1 | 001 | -0.000546 | 319 | 1017.6 | 1030.4 | 152.8/715.3/740.2 | 46.2 | 45.59/16.53 | 13.47/3.93 | True | eligible |
| high | 1 | 002 | 1.026654 | 11 | 32.0 | 44.8 | 850.6/855.5/872.7 | 17.2 | 21.63/14.87 | 8.17/3.64 | True | eligible |
| high | 1 | 003 | 1.084254 | 5 | 12.8 | 25.6 | 865.7/868.1/874.0 | 5.9 | 16.35/15.26 | 5.49/3.39 | False | segment_too_short; segment_duration_too_short |
| high | 1 | 004 | 1.132254 | 4 | 9.6 | 22.4 | 854.5/870.7/882.3 | 12.0 | 16.77/16.63 | 3.59/3.42 | False | segment_too_short; segment_duration_too_short |
| high | 1 | 005 | 1.167454 | 26 | 80.0 | 92.8 | 842.0/863.2/876.8 | 21.4 | 20.85/16.39 | 9.53/4.30 | True | eligible |
| high | 1 | 006 | 1.257054 | 10 | 28.8 | 41.6 | 856.0/861.9/867.7 | 9.6 | 19.08/15.27 | 5.13/4.09 | True | eligible |
| high | 2 | 001 | 0.002654 | 321 | 1024.0 | 1036.8 | 148.1/714.0/740.2 | 42.9 | 49.64/20.32 | 17.59/3.00 | True | eligible |
| high | 2 | 002 | 1.045854 | 4 | 9.6 | 22.4 | 854.6/857.5/860.7 | 6.0 | 20.29/19.61 | 4.06/3.38 | False | segment_too_short; segment_duration_too_short |
| high | 2 | 003 | 1.084254 | 4 | 9.6 | 22.4 | 862.2/869.5/875.2 | 11.2 | 19.99/16.71 | 6.68/3.64 | False | segment_too_short; segment_duration_too_short |
| high | 2 | 004 | 1.132254 | 3 | 6.4 | 19.2 | 859.4/871.6/876.4 | 12.1 | 17.37/16.74 | 4.63/4.13 | False | segment_too_short; segment_duration_too_short |
| high | 2 | 005 | 1.167454 | 26 | 80.0 | 92.8 | 851.5/861.5/878.5 | 19.6 | 21.61/16.81 | 7.88/3.78 | True | eligible |
| high | 2 | 006 | 1.260254 | 3 | 6.4 | 19.2 | 858.8/864.4/871.3 | 12.5 | 19.28/18.23 | 4.15/3.31 | False | segment_too_short; segment_duration_too_short |
| high | 2 | 007 | 1.273054 | 5 | 12.8 | 25.6 | 861.5/863.2/872.7 | 10.9 | 20.40/18.12 | 4.94/3.16 | False | segment_too_short; segment_duration_too_short |

记录尾部仍有 143、134、130、122 个 spectrally qualified frames。它们全部
保留，`physical_branch_review_status=unreviewed`；没有自动判断其是否为目标
界面，也没有删除。

## 12. 正式速度数组不变证明

将 TASK-013 基准
`outputs/task013_validation/run_task013_final2_20260726`
与 TASK-013A-R 输出逐流比较，以下数组全部 exact equal，包括 NaN 位置：

- `signal_state`
- `refined_frequency_hz`
- `apparent_velocity_m_s`
- `peak_to_background_db`
- `peak_to_competitor_db`
- `cycles_in_window`

| Stream | TASK-013 finite velocity | TASK-013A-R finite velocity | Old formal interval finite |
|---|---:|---:|---:|
| Balanced/ch1 | 392 | 392 | 244 |
| Balanced/ch2 | 379 | 379 | 244 |
| High/ch1 | 375 | 375 | 244 |
| High/ch2 | 366 | 366 | 244 |

EventCandidateConfig 的 permissive/strict workflow 测试也证明只有
segment eligibility 和 consensus metadata 改变，正式数组和有限点计数不变。

## 13. 风险与未知项

- EventCandidateConfig 和 EventConsensusConfig 都是 development defaults，
  不是文献标准、仪器规格或实验标定结果。
- 当前只有一条真实记录，无法估计稳健的假阳性率、漏检率或置信区间。
- 25 ns 时间容差、150 MHz start-frequency 容差和 100 MHz adjacent-step
  上限需要更多 shots、无事件基线和已标注事件数据标定。
- 共识证明多流有相容谱证据，不证明该谱支的物理身份。
- pdv_channel_2 存在正向削顶嫌疑；削顶可能改变谐波、谱对比和候选时间。
- 高重叠 STFT 帧不是独立统计样本；frame count 不能直接解释为独立观测数。
- 记录尾部约 650–680 m/s 分支的物理身份未知，保持 unreviewed。
- manual reference 与最终候选非常接近是运行结果，不是选择条件。
- 未做 LiF、折射率、入射角或 true-velocity 修正。

## 14. pytest、Ruff、mypy

最终质量门：

- pytest: 321 passed
- Ruff: passed
- mypy: strict mode, 42 source files passed
- `git diff --check`: passed

`.pytest_cache` 仍有既知 Windows ACL 警告，不影响测试结果。

## 15. Git diff 与原始数据哈希

本任务未修改 `data/raw/20260607.csv`。运行前后 SHA-256 均为：

`AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`

最终输出目录：

`outputs/task013ar_validation/run_task013ar_20260726`

关键产物：

- `measured_segments.csv`
- `event_consensus.json`
- `event_candidate_sensitivity.csv`
- `threshold_transferability_audit.csv`
- `all_measured_segments_timeline.png`
- 每 profile 的 `detected_event_candidates.png`
- `cross_profile_consensus.png`
- 每流状态分层 `apparent_velocity_full_preview.png`
- `spectral_contrast_distribution_comparison.png`
- `band_boundary_fraction_comparison.png`

最终 Git status 仍是 dirty worktree；TASK-013A-R 与之前未提交 TASK-013
共同存在。没有覆盖或删除用户原有修改。

## 16. 停止状态

- 未执行 `git add`
- 未执行 commit
- 未执行 push
- 未启动 GUI、CWT、SVD、小波、AI、LiF 修正、速度平滑、时间插值或目标
  物理脊线融合
- TASK-013A-R 到此停止，等待审计
