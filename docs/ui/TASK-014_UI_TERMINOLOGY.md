# TASK-014 UI 中英文术语表

## 1. 基本规则

- 用户界面使用自然中文和标准英文。
- Python 代码使用英文标识。
- CSV、配置和项目字段保持英文。
- 字段尽量包含单位后缀。
- 单位不翻译。

## 2. 核心术语

| 中文 | English | 推荐内部标识 |
|---|---|---|
| 原始数据 | Raw Data | `raw_data` |
| 原始信号 | Raw Signal | `raw_signal` |
| 数据导入 | Data Import | `data_import` |
| 分析范围 | Analysis Range | `analysis_range` |
| 显示范围 | View Range | `view_range` |
| 导出范围 | Export Range | `export_range` |
| 短时傅里叶变换 | Short-Time Fourier Transform | `stft` |
| 时频图 | Spectrogram | `spectrogram` |
| 频谱 | Spectrum | `spectrum` |
| 频谱脊线 | Spectral Ridge | `spectral_ridge` |
| 候选脊线 | Candidate Ridge | `candidate_ridge` |
| 精修脊线 | Refined Ridge | `refined_ridge` |
| 拍频信号 | Beat Signal | `beat_signal` |
| 拍频频率 | Beat Frequency | `beat_frequency_hz` |
| 信号存在检测 | Signal Presence Detection | `signal_presence_detection` |
| 表观速度 | Apparent Velocity | `apparent_velocity_m_s` |
| 修正速度 | Corrected Velocity | `corrected_velocity_m_s` |
| 显示速度 | Display Velocity | `display_velocity_m_s` |
| 质量标记 | Quality Flag | `quality_flag` |
| 信号状态 | Signal State | `signal_state` |
| 自动分析 | Automatic Analysis | `automatic_analysis` |
| 引导分析 | Guided Analysis | `guided_analysis` |
| 事件参考线 | Event Reference Line | `event_reference_line` |
| 脊线走廊 | Ridge Corridor | `ridge_corridor` |
| 包含区域 | Inclusion Region | `inclusion_region` |
| 排除区域 | Exclusion Region | `exclusion_region` |
| 复核与导出 | Review & Export | `review_export` |

## 3. 数据与采样

| 中文 | English | 推荐内部标识 |
|---|---|---|
| 时间 | Time | `time_s` |
| 电压 | Voltage | `voltage_v` |
| 样本数 | Sample Count | `sample_count` |
| 采样间隔 | Sample Interval | `sample_interval_s` |
| 采样率 | Sample Rate | `sample_rate_hz` |
| Nyquist 频率 | Nyquist Frequency | `nyquist_frequency_hz` |
| 均匀采样 | Uniform Sampling | `uniform_sampling` |
| 非均匀采样 | Non-uniform Sampling | `nonuniform_sampling` |
| 通道 A | Channel A | `channel_a` |
| 通道 B | Channel B | `channel_b` |
| 削顶 | Clipping | `clipping` |

当前正式配置和导入默认名称是 `pdv_channel_1`、`pdv_channel_2`。它们是内部数据
字段，不随 UI 语言变化；界面允许用户在导入对话框中显式修改通道名。

## 4. STFT 参数

| 中文 | English | 推荐内部标识 |
|---|---|---|
| 窗函数 | Window Function | `window_function` |
| 窗长 | Window Length | `window_length` |
| 重叠长度 | Overlap Length | `overlap_length` |
| 步长 | Hop Length | `hop_length` |
| FFT 长度 | FFT Length | `nfft` |
| 搜索频段 | Search Band | `search_band_hz` |
| 显示频段 | Display Band | `display_band_hz` |
| 频率网格 | Frequency Grid | `frequency_grid_hz` |
| 频率网格间隔 | Frequency Bin Spacing | `frequency_bin_spacing_hz` |
| 幅值 | Magnitude | `magnitude` |
| 分贝幅值 | Magnitude in Decibels | `magnitude_db` |
| 频谱探针 | Spectrum Inspector | `spectrum_inspector` |

## 5. 脊线与质量

| 中文 | English | 推荐内部标识 |
|---|---|---|
| 离散峰 | Discrete Peak | `discrete_peak` |
| 峰值频率 | Peak Frequency | `peak_frequency_hz` |
| 亚频点精修 | Sub-bin Refinement | `subbin_refinement` |
| 逐帧最大值 | Frame-wise Maximum | `framewise_maximum` |
| 局部拟合 | Local Fitting | `local_fitting` |
| 连续性约束 | Continuity Constraint | `continuity_constraint` |
| 竞争峰 | Competing Peak | `competing_peak` |
| 背景水平 | Background Level | `background_level_db` |
| 低可信度 | Low Confidence | `low_confidence` |
| 无可信信号 | No Reliable Signal | `no_reliable_signal` |
| 无可信结果 | No Reliable Result | `no_reliable_result` |

## 6. 工作流状态

| 中文 | English | 内部枚举 |
|---|---|---|
| 空白 | Empty | `EMPTY` |
| 数据已加载 | Data Loaded | `DATA_LOADED` |
| 已设置分析范围 | Range Defined | `RANGE_DEFINED` |
| 时频结果就绪 | STFT Ready | `STFT_READY` |
| 脊线结果就绪 | Ridge Ready | `RIDGE_READY` |
| 结果就绪 | Result Ready | `RESULT_READY` |
| 正在运行 | Running | `RUNNING` |
| 失败 | Failed | `FAILED` |
| 结果已失效 | Result Stale | `STALE` |
| 不可用 | Not Available | `NOT_AVAILABLE` |

TASK-014 代码当前只定义前六个顺序结果状态
`EMPTY`、`DATA_LOADED`、`RANGE_DEFINED`、`STFT_READY`、`RIDGE_READY`、
`RESULT_READY`；运行、失败、失效和不可用是未来任务的执行/失效状态术语。

## 7. 单位

| 物理量 | 内部单位 | 常用显示单位 |
|---|---|---|
| 时间 | `s` | `μs` |
| 电压 | `V` | `mV` |
| 频率 | `Hz` | `MHz`、`GHz` |
| 速度 | `m/s` | `m/s` |
| 波长 | `m` | `nm` |
| 角度 | `rad` | `rad` |

## 8. 禁止或不推荐用语

| 不推荐 | 推荐 |
|---|---|
| 真速度 | 表观速度或修正速度 |
| 谱线就是速度 | 频谱脊线对应拍频，拍频再转换为速度 |
| 最大值法求速度 | 逐帧最大值估计峰值频率 |
| 多项式法求速度 | 局部拟合精修峰值频率 |
| 没有信号所以速度为零 | 无可信信号，正式速度为 `NaN` |
| 裁掉数据 | 设置分析范围 |
| 滤波框 | 搜索区域、包含区域或排除区域 |
| 两通道融合 | 双通道比较或通道择优 |
| 自动 LiF 修正 | 未经验证不得正式启用 |

## 9. 固定提示语

### 数据未加载

中文：

```text
请先导入并验证时间—电压数据。
```

English:

```text
Import and validate time–voltage data first.
```

### 原始数据只读

中文：

```text
原始数据保持只读。当前操作不会覆盖源文件。
```

English:

```text
Raw data remain read-only. This operation does not overwrite the source file.
```

### 无可信信号

中文：

```text
当前区间未检测到可信拍频，正式频率和速度结果保持为 NaN。
```

English:

```text
No reliable beat signal was detected in this interval. Formal frequency and velocity results remain NaN.
```

### 功能尚未接入

中文：

```text
该功能已列入后续开发计划，当前版本尚未接入。
```

English:

```text
This feature is planned but is not connected in the current version.
```
