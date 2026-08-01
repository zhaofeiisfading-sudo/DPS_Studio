# TASK-015A 原生文件夹图标与真实自动分析工作流报告

日期：2026-08-01

## 1. 开始前 Git 和测试状态

- 开始前分支为 `main...origin/main`，工作树和暂存区均为空；`git diff --stat`、
  `git diff --cached --stat` 无输出，`git diff --check` 通过。
- Python：3.12.13（`dps-studio` Conda 环境）。
- 开始前 Ruff 全仓通过，mypy 对 51 个源文件通过。
- 开始前全量 pytest 收集 344 项：直接附加独立 `--basetemp` 时 343 passed、
  1 failed。唯一失败是既有 `tests/unit/test_package.py::test_cli` 把 pytest 的
  `--basetemp` 误交给 `dps-studio` 的 `argparse`；另有仓库 `.test_tmp` cache 的既有
  WinError 5。该 CLI 测试不在 TASK-015A 允许修改范围内，本任务未越界修改。
- `presentation/**`、`presentations/**` 在本任务开始时没有需要处理的工作树项；本
  任务没有触碰这些目录。

## 2. 文件夹图标修改方式

工具栏“打开数据”由 `native_icons.native_directory_icon()` 提供图标。函数优先用
`QFileIconProvider.icon(QFileInfo(QDir.homePath()))` 获取 Windows 系统目录图标；
provider 失败、抛出受控异常或返回 null icon 时回退到
`QStyle.StandardPixmap.SP_DirOpenIcon`。没有下载或复制系统图标资源。

主工具栏 `iconSize` 为 20×20；菜单动作文字“打开数据…”、应用左上角图标、科学图
颜色和图例规则没有因图标任务改变。

## 3. 分析范围实现

`AnalysisRangePanel` 的数值框显示 μs，信号和 session 保存 `start_time_s`、
`end_time_s`。`RawSignalView` 使用受共同数据边界约束的 `LinearRegionItem`；图上范围
和数值框双向同步。图和数值框只表示 draft，zoom 不会自动写入正式范围；用户必须
点击“确认分析范围”“使用完整范围”或“使用当前显示范围”。

范围使用两个通道时间域的交集并强制 `start_time_s < end_time_s`。原始
`SignalRecord` 不裁剪、不替换、保持只读。重新导入会清除旧范围和所有下游结果，
确认范围后进入 `RANGE_DEFINED`。

## 4. 后台任务结构

`AutomaticAnalysisAdapter` 使用 `QThreadPool + QRunnable`。worker 只捕获不可变
`AnalysisRequest`，发送 started/finished/failed，不访问 `QWidget`；主线程负责忙碌
状态、视图更新、异常摘要和状态推进。运行期间重复启动返回 false，界面显示不确定
进度条并保持可移动、可重绘。

core 当前没有 cooperative cancellation API。本任务没有伪装成能中断 NumPy/SciPy
计算，取消按钮保持禁用。上游参数变化会增加 generation id；旧 worker 完成后，其
迟到结果会被主线程忽略。这是结果软失效，不是真实取消。

## 5. 实际调用的 public core API

唯一完整科学入口为：

```text
dps_studio.core.workflow.analyze_profile
```

调用输入是当前 GUI 内存中的 `Mapping[str, SignalRecord]`，不是 workflow TOML 的
`input.path`，也不是 `outputs` 文件。`analyze_profile` 逐通道独立调用正式 STFT、
候选峰、亚频点精修、谱质量、信号检测、表观速度、连续性和事件候选链，返回
`Mapping[str, ChannelAnalysis]`。GUI/worker 不复制十几个科学步骤，不导入
`scripts.production_outputs`，不使用 subprocess 或生产 CSV/PNG。

## 6. 配置和单位来源

- `load_workflow_config` 显式加载用户选择的 TOML；第一版支持当前正式 profile 名称
  `Balanced` 和 `High time resolution`。
- profile 的 Hann、window length、overlap、hop、nfft 和搜索带直接来自
  `AnalysisProfile`；右侧只读显示与传入 core 的对象相同。
- detection、event candidate、背景保护参数和 display-only 配置来自同一
  `WorkflowConfiguration`；右侧显示实际 quality TOML 路径。
- 分析时间范围来自用户确认的 SI 秒范围；界面显示 μs。
- 真空波长内部为 m，界面为 nm。配置值加载后不会静默启用；必须勾选“我已核对当前
  实验的真空波长”。真实验收显式确认了配置中的 1550 nm 值。
- 配置中的旧 raw 路径不会替换当前 GUI records。

## 7. STFT 显示

每个通道独立切换，图像直接使用
`ChannelAnalysis.stft_result.spectrum/time_s/frequency_hz`。内部轴保持 s、Hz；显示轴
为 μs、GHz。显示量明确定义为
`20 log10(abs(spectrum) / channel_global_max)`，按 workflow plot floor 截断，不称
为正式 SNR。图中画出 profile 搜索频段上下界，不平均两个通道，不对科学数据插值
补缺。

真实 Balanced 验收中，每个通道 STFT 图像为 2049×620。

## 8. Ridge 显示

- 离散候选峰：`ridge_result.frequency_hz`，散点；
- 亚频点精修：`refined_result.refined_frequency_hz`；
- 正式可信脊线：`signal_detection_result.refined_frequency_hz`。

refined 和 formal 曲线使用 `connect="finite"`，NaN 两侧不连接；没有平滑、自动换
频率分支或脊线走廊。图例分别标明 candidate、refined、formal measured ridge，
下方同步显示真实逐帧 `SignalState` 计数。

## 9. Velocity 显示

默认曲线直接使用正式质量门控字段
`signal_detection_result.apparent_velocity_m_s`。NaN 保持断线，每个通道独立切换。
`display_velocity_m_s` 只在用户勾选后以虚线显示，图例明确“仅显示”，不冒充正式
测量。

当前仍不存在 `corrected_velocity_m_s` 和正式 LiF/窗口修正。两个修正入口保持禁用并
显示“窗口修正尚未接入”。

## 10. Comparison 和 Quality

Comparison 只叠加 Channel A/Channel B 各自的 formal apparent velocity，使用真实
通道名并允许逐通道隐藏；没有融合曲线、自动择优或所谓最终通道。

Quality 表直接统计 `signal_states`、谱质量 `assessment_statuses`、连续性
`continuity_statuses`、MEASURED 数和 formal velocity NaN 数。真实验收结果：

| 通道 | MEASURED | NaN | 主要 SignalState 计数 |
|---|---:|---:|---|
| `pdv_channel_1` | 392 | 228 | AMBIGUOUS_PEAK=122，NO_DETECTABLE_BEAT=66，UNSTABLE_DETECTION=19，PEAK_AT_BAND_BOUNDARY=21 |
| `pdv_channel_2` | 379 | 241 | AMBIGUOUS_PEAK=65，NO_DETECTABLE_BEAT=78，UNSTABLE_DETECTION=3，PEAK_AT_BAND_BOUNDARY=95 |

## 11. 结果失效机制

`AnalysisSession` 保存当前源文件、只读 records、确认范围、workflow configuration、
当前 profile、实际 run configuration、通道 `ChannelAnalysis`、结果有效性和 generation
id。重新导入、确认新范围、切换 profile、修改真空波长或加载新的正式质量配置都会：

1. 增加 generation id；
2. 清空内存 `channel_analyses` 并设置 `results_valid=False`；
3. 清除 STFT/Ridge/Velocity/Comparison/Quality 视图；
4. 禁用下游 tab 和 Export；
5. 明确提示需要重新分析；
6. 回到 `DATA_LOADED` 或 `RANGE_DEFINED`。

完整结果被当前 generation 接受后，主线程依次推进 `STFT_READY`、`RIDGE_READY`、
`RESULT_READY`。`RUNNING` 只作为 adapter busy flag。

## 12. 新增和修改文件

新增：

- `src/dps_studio/gui/native_icons.py`
- `src/dps_studio/gui/analysis_range.py`
- `src/dps_studio/gui/analysis_session.py`
- `src/dps_studio/gui/analysis_adapter.py`
- `src/dps_studio/gui/result_views.py`
- `tests/unit/gui/test_task015a_analysis.py`
- `artifacts/task015a_ui/render_task015a_screenshots.py`
- 五张 `artifacts/task015a_ui/*.png` 实际窗口截图
- `docs/TASK-015A_REPORT.md`

修改：

- `src/dps_studio/gui/main_window.py`
- `src/dps_studio/gui/raw_signal_view.py`
- `src/dps_studio/gui/translations/pdv_studio_en.ts`
- `src/dps_studio/gui/translations/pdv_studio_en.qm`
- `docs/ui/TASK-014_CODE_FLOW_MAP.md`
- `docs/ui/TASK-014_UI_ARCHITECTURE.md`
- `docs/ui/TASK-014_UI_TERMINOLOGY.md`

没有修改 `core/**`、`scripts/**`、`configs/**`、`data/raw/**`、`outputs/**`、
`presentation/**`、`presentations/**` 或 `notebooks/**`。

## 13. 全量 pytest、Ruff、mypy 和 diff check

- TASK-015A GUI 测试：18 passed。
- 最终直接命令、独立 basetemp：收集 355 项，354 passed、1 failed；唯一失败仍是
  既有 `test_cli` 读取 pytest 的 `--basetemp/-o` 参数，没有其他失败或错误。
- 采用相同完整测试集、相同独立 basetemp，但隔离测试进程 `sys.argv` 后：
  **355 passed in 15.55s**。
- Ruff：`All checks passed!`
- mypy：`Success: no issues found in 56 source files`
- `git diff --check`：通过。

## 14. 真实数据验收结果

使用 `data/raw/20260607.csv`（80,000 行）和
`configs/demo_dual_profile.toml` 的显式列、单位、Balanced profile、质量配置与经用户
核对的 1550 nm 真空波长，在实际 Windows Qt 窗口中运行。

两个原始通道分别显示、共享确认范围并在后台分别完成分析；窗口在运行期间仍处理 Qt
事件。Spectrogram、Ridge、formal apparent velocity 和质量统计均来自当前 public
core 返回数组；NaN 没有隐藏，Comparison 没有融合通道。最终状态为
`RESULT_READY`。

源文件验收前后 SHA-256 均为：

```text
AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353
```

## 15. 截图路径

- `artifacts/task015a_ui/main_window_native_icon_zh.png`
- `artifacts/task015a_ui/real_spectrogram_zh.png`
- `artifacts/task015a_ui/real_ridge_zh.png`
- `artifacts/task015a_ui/real_velocity_zh.png`
- `artifacts/task015a_ui/real_comparison_zh.png`

五张图均由实际 Windows Qt `MainWindow.grab()` 生成。已检查中文字体、20×20 原生目录
图标、坐标轴、图例、范围线、NaN 断线和 1440×900 布局。

## 16. 当前限制

- 没有真正的 cooperative cancellation；只有 generation-id 迟到结果忽略。
- 没有正式导出、项目保存、多边形 ROI、脊线走廊、引导分析、新降噪、动态规划、
  自动通道择优、通道融合、LiF/corrected velocity、示波器连接、文件夹监视或正式
  PyInstaller 包。
- relative dB 只是 STFT 视觉量，不是正式 SNR。
- 当前配置文件明确把 1550 nm 标为 demonstration value，因此 GUI 强制要求用户逐次
  核对，不会把它静默当成实验事实。
- 直接给 pytest 添加参数会暴露既有 `test_cli` 的全局 `sys.argv` 污染问题；本任务未
  越界修改该 CLI 测试或生产 CLI。

## 17. 最终 Git 状态

工作树只包含本报告第 12 节列出的 TASK-015A GUI、测试、文档和截图改动；没有
`core/**` 或禁止目录变更。HEAD、分支和远端均未改变。

## 18. 暂存区

暂存区为空。未执行 `git add`、commit 或 push。

## 19. `data/raw` 完整性

`git diff -- data/raw`、`git diff --cached -- data/raw` 均为空；真实验收前后源文件
SHA-256 一致。TASK-015A 没有写入、覆盖或删除 `data/raw/**`。
