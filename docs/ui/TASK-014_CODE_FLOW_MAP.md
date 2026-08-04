# TASK-014 当前代码处理链审计

本审计以 2026-07-31 的本地源码、测试、配置和脚本为准。历史 TASK-011/012/013
报告仅用于交叉检查；报告中已经被后续任务改变的旧入口、旧文件名和旧输出契约
不作为当前事实。

## 1. 审计范围

已实际检查 `README.md`、`AGENTS.md`、`pyproject.toml`、`environment.yml`、
`configs/**`、`src/dps_studio/**`、`scripts/**`、`tests/**`、现有 TASK-011/012/013
审计报告、production 入口与 demo 入口。

开始时：

- HEAD：`f0bd81b8baf116d71630ac7826fd08fb49419fab`；
- 分支：`main`，相对 `origin/main` ahead 1；
- 暂存区为空，`git diff --check` 通过；
- 工作树已有 631 个 `presentation/`、`presentations/` 跟踪文件删除，本任务不触碰；
- `docs/ui/` 已有 4 个未跟踪模板草稿，本任务保留其结构并增量回填；
- 修改前 pytest 为 `261 passed, 76 errors`，76 个错误均是系统 pytest 临时根与
  `.test_tmp/pytest_cache` 的 `WinError 5`，不是测试断言失败；
- 修改前 Ruff 通过，mypy strict 对 42 个源文件通过。

### 1.1 开发前现有 GUI 目录逐文件审计

开发前 `src/dps_studio/gui/` 只有一个已跟踪文件，没有隐藏子目录或其他源码：

| 文件 | 开发前内容 | 实际职责 | 判断 | TASK-014 处理 |
|---|---|---|---|---|
| `src/dps_studio/gui/__init__.py` | 21 字节，仅 `"""Package module."""` | 只使目录成为 Python 包 | 占位实现；无类、函数、入口、Qt 控件或引用 | 继续沿用同一文件和目录，增量补充包说明与 public UI 状态导出 |

仓库中没有任何代码引用 `dps_studio.gui`，也不存在 GUI 启动入口。因此本任务是在
既有目录内扩展，不是替换已有功能，也没有创建平行 GUI 包。

## 2. 当前正式入口

请填写：

| 入口命令或脚本 | 文件路径 | 实际调用目标 | 作用 | 是否继续保留 |
|---|---|---|---|---|
| `dps-studio` | `pyproject.toml` → `src/dps_studio/cli.py` | `cli.main` | 仅解析 `--version`；不运行分析 | 是，未修改 |
| `python -m dps_studio` | `src/dps_studio/__main__.py` | `cli.main` | 与安装后的 CLI 相同 | 是，未修改 |
| `run_demo_pipeline.bat` | 仓库根 | conda Python + `scripts/run_demo_pipeline.py` | Windows 正式双 profile 生产入口，成功后打开输出目录 | 是；GUI 不调用 |
| `python scripts/run_demo_pipeline.py --config ...` | `scripts/run_demo_pipeline.py` | `load_workflow_config`、`read_delimited_signals`、`run_production_outputs` | 命令行正式生产编排 | 是；GUI 不调用 |
| 各开发脚本的 `main()` | `scripts/assess_*`、`compare_*`、`plot_*`、`audit_*` | 各自开发/历史流程 | 绘图、质量证据、历史审计和参数比较 | 是；不是 GUI API |
| `python -m dps_studio.gui` | `src/dps_studio/gui/__main__.py` | `gui.app.main` | TASK-014 新增桌面入口 | 是 |

## 3. 当前真实处理链

```text
原始文件
-> load_workflow_config
-> WorkflowConfiguration（显式路径、列、SI 缩放、分析与输出参数）
-> read_delimited_signals
-> DelimitedSignalLoadResult
-> Mapping[str, SignalRecord]（两个通道分离）
-> run_production_outputs（脚本层生产编排）
-> 每个 AnalysisProfile 调用 analyze_profile
-> analyze_configuration
-> 每个通道独立 compute_stft
-> extract_peak_ridge
-> refine_peak_ridge_subbin
-> convert_ridge_to_apparent_velocity（未门控的离散候选兼容视图）
-> assess_ridge_spectral_quality
-> detect_beat_signal
-> 仅 MEASURED 帧保留正式 refined_frequency_hz / apparent_velocity_m_s
-> formal_discrete_velocity_m_s / refined_velocity_m_s
-> display_velocity_m_s（单独的显示数组）
-> assess_ridge_continuity
-> build_stream_event_candidates
-> build_profile_consensus / build_cross_profile_consensus（仅元数据共识）
-> CSV、PNG、JSON manifest、README 和 log
```

生产函数在正式 profile 分析前还会对四组已批准的 development threshold pair
重复调用同一 public workflow 做阈值校准。`assess_related_frequency_evidence`
存在于 public core，但当前 production 主链不调用。

当前不存在：正式 LiF/折射率/入射角修正、`corrected_velocity_m_s` 数据对象、
有符号速度、通道电压融合、profile 数值融合、正式自动降噪和 GUI 可调用的
public 导出服务。

## 4. 模块职责表

| 文件路径 | 类或函数 | 实际职责 | 输入 | 输出 | 内部单位 | 当前调用者 | GUI 接入结论 |
|---|---|---|---|---|---|---|---|
| `core/io/delimited.py` | `read_delimited_signals` | 严格读取显式列，不猜单位，不写源文件 | 路径、列、delimiter、scale | `DelimitedSignalLoadResult` | scale 后 s、V | CLI、开发脚本、TASK-014 adapter | YES |
| `core/io/models.py` | `DelimitedSignalLoadResult` | 冻结文件结构、只读 records mapping、未选列索引 | reader 结果 | 文件级不可变模型 | s、V | reader、调用方 | YES |
| `core/models/signal.py` | `SignalRecord` | 验证并保存单通道时间—电压、采样摘要 | 1D arrays | bytes-backed 只读数组 | s、V、Hz | reader、STFT、GUI | YES |
| `core/workflow/config.py` | `load_workflow_config` | 加载唯一正式 TOML，验证路径/列/分析/质量/输出参数 | TOML、仓库根 | `WorkflowConfiguration` | SI | CLI | YES |
| `core/analysis_profiles.py` | `AnalysisProfile`、两个 profile | 固定 Hann/window/overlap/hop/nfft/搜索带 | profile id | 冻结配置 | samples、Hz | workflow、production | YES |
| `core/time_frequency/stft.py` | `compute_stft` | 对一个均匀采样通道计算无 padding、无 detrend 的单边 STFT | `SignalRecord`、STFT 参数 | `STFTResult` | s、Hz、V 谱幅 | workflow、开发脚本 | ADAPTER |
| `core/time_frequency/models.py` | `STFTResult` | 保存只读物理轴、复数谱和可复现元数据 | STFT arrays | 冻结结果 | s、Hz | ridge、quality、plot | YES |
| `core/ridge/peak.py` | `extract_peak_ridge` | 闭频带逐帧 `argmax(abs(spectrum))`；不平滑/跟踪 | `STFTResult`、范围 | `RidgeResult` | s、Hz | workflow | ADAPTER |
| `core/ridge/refinement.py` | `refine_peak_ridge_subbin` | 三点 log-magnitude 二次亚频点精修；失败返回 NaN/status | STFT + ridge | `RefinedRidgeResult` | s、Hz、bin | workflow | ADAPTER |
| `core/ridge/spectral_quality.py` | `assess_ridge_spectral_quality` | guard 外背景中位数与最强竞争峰对比；不是 SNR | STFT + refined + guard | `RidgeSpectralQualityResult` | Hz、线性幅值、dB | workflow、开发脚本 | ADAPTER |
| `core/quality/models.py` | `SignalDetectionConfig` | 显式 development 检测阈值 | 数值配置 | 冻结阈值 | dB、bins、frames | config、workflow | YES |
| `core/quality/detection.py` | `detect_beat_signal` | 按顺序应用谱、边界、周期数、精修、连续帧质量门 | STFT + refined + quality | `SignalDetectionResult` | s、Hz、m/s | workflow | ADAPTER |
| `core/physics/velocity.py` | `convert_ridge_to_apparent_velocity` | 法向反射 `v = λf/2`，仅无符号表观速度，无 LiF | ridge + 真空波长 | `ApparentVelocityResult` | m、Hz、m/s | workflow、开发脚本 | ADAPTER |
| `core/ridge/diagnostics.py` | `assess_ridge_continuity` | 计算相邻频率步进、斜率和二阶差，不改结果 | refined ridge | `RidgeContinuityResult` | Hz、Hz/s | workflow、production | ADAPTER |
| `core/ridge/diagnostics.py` | `assess_related_frequency_evidence` | 评估 2f/f/2 邻域证据，不自动换分支 | STFT + refined + quality | evidence result | Hz、dB | 诊断/历史脚本 | NO（非主链） |
| `core/event_candidates.py` | `build_stream_event_candidates` | 从精确 MEASURED 连续段生成事件资格元数据 | detection、config | `StreamEventCandidates` | s、Hz、dB | workflow | ADAPTER |
| `core/event_candidates.py` | profile/cross-profile consensus | 比较通道/profile 的相容事件段；不融合科学数组 | stream candidates | consensus metadata | s、Hz | production | ADAPTER |
| `core/workflow/analysis.py` | `analyze_configuration` | I/O-free 单 profile、多通道独立正式数值链 | records + 显式参数 | 只读 channel mapping | SI | `analyze_profile`、测试 | ADAPTER |
| `core/workflow/analysis.py` | `analyze_profile` | 将 `AnalysisProfile` 展开给正式 workflow | records + profile | `Mapping[str, ChannelAnalysis]` | SI | production、开发脚本 | ADAPTER |
| `core/workflow/models.py` | `ChannelAnalysis` | 聚合一个独立通道的 STFT、ridge、质量、正式/显示速度 | core results | 冻结聚合结果 | s、Hz、m/s | production | YES（接收） |
| `scripts/run_demo_pipeline.py` | `main`、`run_pipeline` | CLI、哈希核验、生产目录和 `LATEST_RUN` 编排 | TOML、路径 | 路径列表/磁盘树 | SI 配置 | BAT、命令行 | NO |
| `scripts/production_outputs.py` | `run_production_outputs` | 阈值校准、profile/通道编排、Matplotlib/CSV/manifest 导出 | records + workflow config | production 文件树 | SI 文件字段；图可显示 μs | CLI | NO |
| `src/dps_studio/cli.py` | `main` | 版本查询占位 CLI | argv | exit code | 无 | console script | NO |
| `src/dps_studio/gui/data_controller.py` | `DataImportController` | TASK-014 导入 adapter，只组装显式参数并调用 public reader | `SignalLoadRequest` | `DelimitedSignalLoadResult` | 输入 scale → s/V | GUI | GUI 内部 |

GUI 接入结论含义：

- `YES`：稳定的 public core API，GUI 可以直接调用。
- `ADAPTER`：功能可用，但应通过控制器或应用服务调用。
- `NO`：脚本、测试、绘图、历史审计、命令行专用或私有实现，GUI 不得调用。

## 5. 数据模型

- 原始信号模型是每通道一个 `SignalRecord`；`DelimitedSignalLoadResult.records`
  是只读 mapping，双通道名称到两个独立对象，时间和电压数组不共享内存。
- `SignalRecord.time_s`、`voltage_v` 及正式结果模型的数组均复制到
  bytes-backed read-only buffer；metadata 深拷贝。
- reader 要求每行列数一致且所有字段非空。未选择列的值不进入
  `SignalRecord`，但 `unselected_column_indices` 明确报告，因此 GUI 必须显示，
  不能假装第三列不存在。
- 内部使用 s、V、Hz、m、m/s；GUI 仅绘图时显示 μs、mV。
- `RidgeResult` 的遮罩帧、精修失败、质量评估不可用和非 `MEASURED` 的正式频率/
  速度允许并要求为 NaN；状态序列解释原因。
- 正式精修表观速度是 `ChannelAnalysis.refined_velocity_m_s`，与
  `SignalDetectionResult.apparent_velocity_m_s` 完全相等；离散正式速度另存于
  `formal_discrete_velocity_m_s`。
- `display_velocity_m_s` 是单独显示数组。只有显式启用显示约定时，才可在
  `manual_event_reference_time_s` 之前的非 `MEASURED` 帧写入配置的
  `pre_event_display_velocity_m_s`；`MEASURED` 帧始终使用正式表观速度，事件后
  非可信帧始终保持 NaN。该数组不覆盖正式速度。
- `ApparentVelocityResult` 只有 unsigned apparent velocity。当前没有
  `corrected_velocity_m_s`、LiF/折射率/入射角修正或有符号速度。
- 每个 profile 内 `for channel_name, record in records.items()` 独立完成整条链。
  profile/cross-profile consensus 只改变事件元数据，不平均/选择/融合电压、频率或速度。
- 正式自动降噪当前不存在；`core/preprocessing/__init__.py` 仍是占位包。

实际枚举值：

- `RidgeQualityFlag`：`pre_event`、`candidate`、`outside_analysis_window`。
- `SignalState`：`measured`、`no_detectable_beat`、`ambiguous_peak`、
  `insufficient_cycles`、`peak_at_band_boundary`、`refinement_failed`、
  `unstable_detection`、`outside_analysis_window`。

## 6. 文件读取接口

请填写：

| 项目 | 当前事实 |
|---|---|
| 正式读取函数 | `read_delimited_signals` |
| 文件路径 | `src/dps_studio/core/io/delimited.py` |
| 支持格式 | Python `csv.reader` 可读的单字符分隔文本；不按扩展名猜格式 |
| 列映射方式 | zero-based `time_column` 与 `Mapping[channel_name, column_index]` |
| 单位输入方式 | 显式 `time_scale` 与逐通道 `voltage_scales`，转换后为 s/V |
| 是否猜测单位 | 否 |
| 是否保留额外列 | 不保存额外列值；验证其结构/非空并报告 `unselected_column_indices` |
| 返回类型 | `DelimitedSignalLoadResult`，其中包含只读 records mapping |
| 异常类型 | `SignalIOError` 子类及 `SignalValidationError` 子类，保留原因链和上下文 |
| GUI 接入结论 | public API 稳定；TASK-014 通过薄 `DataImportController` 调用 |

## 7. STFT、脊线与速度接口

请填写：

| 阶段 | 正式函数或类 | 文件路径 | 输入 | 输出 | GUI 接入结论 |
|---|---|---|---|---|---|
| STFT | `compute_stft` / `STFTResult` | `core/time_frequency/` | 单 `SignalRecord` + 显式参数 | 只读单边复谱和物理轴 | ADAPTER；未来后台任务 |
| 离散峰 | `extract_peak_ridge` / `RidgeResult` | `core/ridge/peak.py` | STFT + 显式闭频带/时间范围 | 全 STFT 时间轴的峰/NaN/flag | ADAPTER |
| 亚频点精修 | `refine_peak_ridge_subbin` | `core/ridge/refinement.py` | STFT + discrete ridge | refined Hz/NaN/status | ADAPTER |
| 谱质量 | `assess_ridge_spectral_quality` | `core/ridge/spectral_quality.py` | STFT + refined + guard | 背景/竞争峰/dB/status | ADAPTER |
| 信号存在检测 | `detect_beat_signal` | `core/quality/detection.py` | STFT + refined + spectral quality + config | 正式频率、速度、state | ADAPTER |
| 表观速度 | `convert_ridge_to_apparent_velocity` | `core/physics/velocity.py` | ridge + vacuum wavelength m | unsigned apparent velocity | ADAPTER；不得复制公式 |
| 连续性诊断 | `assess_ridge_continuity` | `core/ridge/diagnostics.py` | refined ridge | step/slope/second difference/status | ADAPTER |
| 聚合 workflow | `analyze_profile` / `analyze_configuration` | `core/workflow/analysis.py` | records + profile/显式参数 | 每通道 `ChannelAnalysis` | ADAPTER；未来后台任务 |
| 导出 | `run_production_outputs` 及私有 writers | `scripts/production_outputs.py` | workflow config + records | CSV/PNG/JSON/text | NO；缺少 public core/application export service |

## 8. 明确禁止引入 GUI 的代码

- `scripts/run_demo_pipeline.py`：命令行解析、源文件哈希、输出目录和 `LATEST_RUN`。
- `scripts/production_outputs.py`：production 编排、Pandas CSV、Matplotlib 图、
  manifest、README、log、输出契约和阈值校准。
- `scripts/compare_real_ridge_refinement.py`、`assess_real_ridge_quality.py`、
  `assess_real_ridge_diagnostics.py`：开发参数、绘图、表格和报告。
- `scripts/plot_real_stft.py`、`plot_real_velocity.py`：写死 demo 路径/旧参数的预览。
- `scripts/audit_legacy_velocity_reference.py`：历史审计、独立参数网格、合成真值和报告。
- 全部 `tests/**`、`notebooks/**`、`outputs/**`、`presentation/**`、
  `presentations/**`、脚本私有函数和 Matplotlib 图均禁止成为 GUI 运行依赖。

TASK-014 GUI 源码的自动测试会扫描上述禁止 import，并扫描 core 是否反向导入 GUI。

## 9. GUI 当前缺失的公开接口

请填写：

| 缺失接口 | 为什么需要 | 建议新增位置 | 是否属于 TASK-014 |
|---|---|---|---|
| 可取消、可报告进度的分析 job service | `analyze_profile` 是同步纯函数，完整分析不应阻塞 Qt 主线程 | 新的 application/controller adapter，内部只调 public workflow | 否 |
| GUI 可用的 public export service | 当前导出全部在 `scripts/production_outputs.py` 且耦合 Matplotlib/生产目录 | 将稳定导出契约设计为独立 application/export API，core 保持 I/O-free | 否 |
| 工作区/项目状态持久化 | 保存文件、单位映射、范围、参数和失效关系 | GUI project model 或 application 层 | 否 |
| 引导分析约束模型 | 需要保存 `time_s/frequency_hz` 走廊和 inclusion/exclusion regions | 经审计的 core/application public model | 否 |
| corrected velocity 模型和经验证公式 | 必须与 apparent/display 分离，且 LiF 公式尚未验证 | `core/physics`，仅在物理模型核验后 | 否 |
| 文件夹监视和示波器采集 adapter | 未来采集源不能塞入主窗口或数值 core | 独立 acquisition/application package | 否 |

本任务没有越界实现这些接口。仅完成 public reader 的真实调用、原始数据展示和
明确禁用的后续界面位置。

## 10. 最终审计结论

### 当前真实调用链

```text
run_demo_pipeline(.bat/.py)
-> load_workflow_config
-> read_delimited_signals
-> run_production_outputs
-> analyze_profile
-> analyze_configuration
-> compute_stft
-> extract_peak_ridge
-> refine_peak_ridge_subbin
-> provisional discrete apparent velocity
-> assess_ridge_spectral_quality
-> detect_beat_signal
-> quality-gated formal frequency/apparent velocity
-> separate display velocity
-> continuity + event metadata consensus
-> production CSV/PNG/JSON/text
```

### GUI 可以直接调用的接口

```text
read_delimited_signals、load_workflow_config、所有 public immutable result models
```

### 必须经过 adapter 的接口

```text
compute_stft、ridge/refinement/quality/detection/velocity functions、
analyze_profile、analyze_configuration
```

### 明确不能引入 GUI 的代码

```text
scripts/**、tests/**、notebooks/**、outputs/**、presentation(s)/**、
Matplotlib/Pandas production writers、CLI 私有编排和历史审计实现
```

### 当前最大架构风险

```text
把 scripts 层 production 产出误当成可复用 GUI service，或在主线程中拼接 private
函数，会复制流程、阻塞界面并导致正式/显示速度与质量语义分叉。
```

### 下一项最小接口任务

```text
设计可取消的后台 analysis adapter 和独立 public export service；在此之前保持
STFT、Ridge、Velocity、Export 控件禁用，不用假数据或 private scripts 绕过边界。
```

## 11. TASK-015A 增量：GUI 自动分析调用链

TASK-015A 沿用上述边界，没有修改 `core/**`，实际 GUI 调用链更新为：

```text
当前 GUI 已加载的只读 Mapping[str, SignalRecord]
+ 用户确认的 AnalysisRange(start_time_s, end_time_s)
+ 显式 load_workflow_config 得到的 WorkflowConfiguration
+ 用户选择的正式 AnalysisProfile
+ 用户明确核对的 vacuum_wavelength_m
-> AnalysisRequest(generation_id, records, range, configuration)
-> QThreadPool / QRunnable 后台 worker
-> public core.workflow.analyze_profile
-> 每个通道独立 Mapping[str, ChannelAnalysis]
-> GUI 主线程接收当前 generation 的结果
-> STFT_READY -> RIDGE_READY -> RESULT_READY
```

配置文件中的 `input.path` 只用于说明原 workflow 配置，不会替换 GUI 当前加载的
records。worker 传给 `analyze_profile` 的正式参数为 profile、分析起止时间、真空
波长、`SignalDetectionConfig`、`EventCandidateConfig`、背景保护参数、人工事件参考
时间和 display-only 事件前零平台开关。GUI 不展开或复制 STFT、脊线、检测、速度和
连续性算法，也不导入 `scripts`。

### 11.1 GUI 图与 public 结果字段

| 视图 | 实际字段 | 显示转换 |
|---|---|---|
| Spectrogram | `ChannelAnalysis.stft_result.spectrum/time_s/frequency_hz` | s→μs、Hz→GHz；`20 log10(abs(spectrum) / channel_max)`，按配置 floor 截断，明确不是 SNR |
| Ridge candidate | `ridge_result.frequency_hz` | Hz→GHz，散点，不平滑 |
| Ridge refined | `refined_result.refined_frequency_hz` | Hz→GHz，`connect="finite"` |
| Ridge formal | `signal_detection_result.refined_frequency_hz` | Hz→GHz，NaN 真实断线 |
| Velocity formal | `signal_detection_result.apparent_velocity_m_s` | 保持 m/s；PyQtGraph 可显示 SI 前缀 |
| Velocity display | `display_velocity_m_s` | 默认隐藏、虚线、明确为仅显示结果 |
| Comparison | 各通道 formal apparent velocity | 只叠加，不融合、不择优 |
| Quality | `signal_states`、`assessment_statuses`、`continuity_statuses` 和 formal velocity NaN | 枚举与数量直接统计 |

当前仍没有 `corrected_velocity_m_s`、LiF 修正或 GUI public export service；相关入口
继续禁用。

## 12. TASK-015C-R 跨文件参考与结果视图调用链

```text
新 DelimitedSignalLoadResult
-> AnalysisSession.load_records
-> 重新验证 configuration.analysis.event_reference_time_s
   -> 当前 data + analysis range 内：作为初始参考
   -> 越界：run_configuration.event_reference_time_s=None + rejected audit value
-> 用户可手工确认，或在结果返回后显式采用某通道 detected candidate
-> configure_channel_event_reference（仅 metadata/display）
-> build_display_velocity（analysis start <= time < event reference）
-> formal apparent velocity / SignalState / STFT 保持不变
```

结果视图从 `SignalDetectionResult.analysis_start_time_s` 和
`analysis_end_time_s` 取得 X view；Velocity/Comparison 从当前可见有限速度计算一次性 Y
fit。PyQtGraph repaint 和 display-only refresh 不重新 auto-range，避免覆盖用户 zoom。

## 13. TASK-015D preset + overrides 调用链

```text
PresetRepository.configuration.analysis.profiles
-> 用户选择 immutable AnalysisProfile
-> MainWindow 从 profile/public run model 填充可编辑字段
-> 用户修改 scientific field
-> AnalysisParameterOverrides（nm→m、GHz→Hz）
-> core build_analysis_run_parameters
   -> 复用 AnalysisProfile 正式静态 validator
   -> hop = window - overlap
   -> 规范化 explicit overrides
-> AnalysisRunParameters.validate_for_records
   -> sample count + uniform sampling
   -> 当前 sample rate/nfft 的真实 one-sided FFT grid
   -> search band 至少包含两个正式质量频点
-> AnalysisSession.run_configuration
-> generation 失效并清除旧 formal result
-> AnalysisRequest 捕获同一 immutable final_run_configuration
-> unchanged preset: analyze_profile
   custom run: analyze_configuration(final values)
-> 每个通道独立 ChannelAnalysis
```

display-only 参数不经过该 scientific invalidation 链。GUI 不导入 time-frequency/ridge
私有 validator，不复制 preset 数字，不修改任何 TOML 或 `data/raw`。

## 14. TASK-016 Ridge Corridor 调用链

```text
真实 STFT（Automatic Result 中当前通道）
-> Spectrogram RidgeCorridorController / PolyLineROI
-> plot μs/GHz 立即转换为 SI s/Hz
-> immutable RidgeCorridorConstraint
-> AnalysisSession.ridge_constraints[channel_name]
-> guided_generation_id 增加；仅 Guided Result stale
-> AnalysisRequest(result_source=GUIDED, ridge_constraints=...)
-> 同一 QThreadPool / QRunnable adapter
-> public analyze_profile 或 analyze_configuration
-> 每通道独立 validate_ridge_corridor_for_stft
-> extract_peak_ridge
   corridor 外：原 global closed-band argmax
   corridor 内：global search band ∩ corridor band
   空离散交集：NO_ALLOWED_BINS + NaN（不 fallback）
-> 原 refine_peak_ridge_subbin
-> 原 assess_ridge_spectral_quality
-> 原 detect_beat_signal / quality gating
-> 原 formal frequency / apparent velocity / display transformer
-> guided_channel_analyses（不覆盖 automatic_channel_analyses）
-> Ridge/Velocity source selector + Comparison overlay
```

无 constraint 时 `extract_peak_ridge` 保留原 vectorized search 路径，workflow 的 STFT、
candidate、refined、formal、apparent velocity、SignalState、quality status 逐元素回归
相同。只为某一通道提供 constraint 时，其他通道仍走完全相同的 Automatic 路径。

结果失效关系：

| 操作 | Automatic Result | Guided Result | Constraint |
|---|---|---|---|
| 编辑/清除 corridor | 保持有效 | stale | 更新/清除当前通道 |
| 修改 scientific 参数或 analysis range | 失效 | 失效 | 保留；新数据导入时清除 |
| 修改 display-only 参数 | 保持有效并刷新 display | 保持有效并刷新 display | 不变 |
| Guided worker 返回 | 不覆盖 | 按 guided generation 接受 | 不变 |

新增的 public core 接口为 `RidgeCorridorConstraint`、
`validate_ridge_corridor_for_stft`，以及 `analyze_profile`/
`analyze_configuration` 的可选 per-channel `ridge_constraints` mapping。GUI 仍不调用
`scripts/**`，core 仍不依赖 GUI。

## 15. TASK-016R staged STFT / Ridge 调用链

```text
SignalRecord + AnalysisRange + AnalysisRunConfiguration
-> compute_configuration_stfts
-> Mapping[channel_name, STFTResult]
-> AnalysisSession.accept_stft_results
-> STFT_READY
   -> SpectrogramView.set_stft_results
   -> Automatic: analyze_stft_results(stft_results, no constraint)
   -> Guided: analyze_stft_results(stft_results, per-channel corridor)
-> Mapping[channel_name, ChannelAnalysis]
-> RIDGE_READY -> RESULT_READY
```

`compute_profile_stfts`/`compute_configuration_stfts` 是公开的第一阶段接口；
`analyze_stft_results` 是复用既有 STFT 的第二阶段接口。`analyze_profile` 和
`analyze_configuration` 继续作为一键兼容接口，内部按相同两阶段组合，因此旧 Automatic
结果与分步 Automatic 逐元素一致。adapter 的 `SPECTROGRAM` 请求只计算 STFT，Automatic
或 Guided 请求可携带缓存的 `stft_results`，worker 不重新调用 STFT。

```text
STFT-affecting change
-> stft_valid=False
-> Automatic stale + Guided stale + Velocity stale

search/wavelength downstream change
-> keep stft_results
-> Automatic stale + Guided stale + Velocity stale

corridor/control-point/half-width change
-> keep stft_results + keep Automatic
-> Guided stale only
```

Guided 请求只包含具有合法约束的通道。对每个此类通道，workflow 将 analysis bounds 设为
`[min(control_times), max(control_times)]`；候选频点是逐帧 corridor 与 global search band
的离散交集。域外经原有 signal detection、quality gate 和 velocity conversion 得到 NaN，
不会拼接 Automatic 曲线。
