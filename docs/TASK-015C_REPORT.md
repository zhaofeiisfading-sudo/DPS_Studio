# TASK-015C 完成报告：事件前显示速度语义与 display velocity 参数化

## 1. 开始前 Git 状态

- 分支为 `main...origin/main`，暂存区为空。
- 工作树在 TASK-015C 开始前已包含未提交的 TASK-015B 修改：`workflow/config.py`、`analysis_adapter.py`、`analysis_session.py`、`main_window.py`、英译资源、部分 GUI/config 测试，以及 `artifacts/task015b_ui/`、默认配置、TASK-015B 报告、预设仓库和高级参数对话框等未跟踪文件。本任务完整保留这些用户改动，没有回退、覆盖或暂存。
- 开始前 `git diff --check` 通过；`git diff --cached --stat` 无输出。
- 在上述真实工作树上，隔离 pytest 参数后的基线为 `365 passed in 43.45s`；Ruff 通过；mypy 对 58 个源码文件通过。

## 2. 当前 pre-event 的真实定义

仓库已有、可复用且含义明确的事件边界是 `manual_event_reference_time_s`。本任务将事件前定义为 `time_s < manual_event_reference_time_s`，但显示平台只应用于该范围内的非 `MEASURED` 帧；如果事件边界前存在正式 `MEASURED` 帧，正式测量值优先，显示曲线继续使用该正式值。

本任务没有把“第一帧 MEASURED 之前”当作事件前，没有依据速度或频率阈值猜测起跳，也没有新增 onset detector。`RidgeQualityFlag.PRE_EVENT` 是 ridge 的分析起点质量语义，当前 workflow 没有用它定义 GUI 事件边界；`SignalState` 没有 PRE_EVENT 枚举；event candidate 是下游候选段元数据；analysis range 只产生 `OUTSIDE_ANALYSIS_WINDOW` 等正式逐帧状态。因此这些对象均没有被错误地替代为 display pre-event 边界。

## 3. display_velocity_m_s 的构建位置

任务开始时，`display_velocity_m_s` 由 `src/dps_studio/core/workflow/analysis.py` 的私有 `_display_velocity` 构建，结果作为独立数组存入 `ChannelAnalysis`，并非 GUI 临时数组，也不是正式 quality/apparent velocity 数组。原逻辑仅能配置事件前零值，并且会先按时间填零，可能覆盖事件边界前的有效 `MEASURED` 显示值。

任务完成后，构建逻辑收敛到 public core 模块 `src/dps_studio/core/workflow/display.py`：`build_display_velocity` 负责纯数组构建，`configure_channel_display_velocity` 只替换 `ChannelAnalysis` 的 `display_velocity_m_s` 与 `velocity_origins`。`analysis.py` 和 GUI session 共用这套语义，避免出现第二套 GUI 规则。

## 4. 本任务复用的 event/pre-event 接口

唯一复用的事件接口是 `SignalDetectionResult.manual_event_reference_time_s`，其来源仍为当前 public workflow/config 的 `manual_event_reference_time_s`。没有修改该字段的检测方法、来源或数值，也没有接入新的事件模型。

## 5. 不影响 formal velocity 的保证

`build_display_velocity` 以 formal apparent velocity 的副本开始，只返回独立显示数组和显示来源；它不持有也不修改 detection result。`configure_channel_display_velocity` 使用不可变 dataclass 的 `replace`，仅更新两个 display-only 字段。

测试在相同输入和相同科学参数下，把平台从 0.0 m/s 改为 12.5 m/s，并逐项确认 `signal_detection_result.apparent_velocity_m_s` 的字节/NaN 语义、`refined_velocity_m_s`、formal frequency、`SignalState`、STFT 对象身份和分析 generation 完全不变。正式 `MEASURED` 帧继续使用真实 apparent velocity；正式非 `MEASURED` 帧继续为 NaN。

## 6. 配置模型变化

- `PlotConfiguration` 新增 `pre_event_display_velocity_m_s: float`，内部单位为 m/s，默认值为 `0.0`，加载时要求有限实数。
- 现有 `assume_pre_event_zero_for_display` 配置键为兼容已有 TOML 和调用方而保留，并映射为显示平台启用开关；没有建立平行配置体系。
- GUI 运行配置采用语义更清楚的 `enable_pre_event_display` 与 `pre_event_display_velocity_m_s`。
- `configs/demo_dual_profile.toml` 和默认启动配置显式记录 `pre_event_display_velocity_m_s = 0.0`；旧配置缺少该键时仍兼容并使用 0.0。

## 7. GUI 参数实现

速度结果页增加“事件前显示速度” `QDoubleSpinBox`，默认 `0.000000 m/s`、内部和显示单位均为 m/s，可编辑有限范围为 ±1e9 m/s。高 DPI 窄侧栏下对数值框设置了合理最大宽度，确保中文字段名与单位同时可见。

tooltip 为：“仅影响事件前 display velocity 的绘图与未来 display-velocity 导出，不修改正式表观速度。”现有勾选项统一为“显示速度（非正式结果）”，英文分别为 “Pre-event Display Velocity” 和 “Display Velocity (Non-formal Result)”。翻译通过 Qt `.ts/.qm` 资源完成，没有语言条件硬编码。

修改数值或勾选状态只调用 session 的 display-only refresh，并只刷新 VelocityView；不会使分析结果失效、递增 generation 或启动新的 STFT/ridge/formal velocity 任务。绘图的正式与显示曲线继续分开，均使用有限段连接，未补线、未平滑、未跨 NaN 连接。

## 8. 事件后 NaN 的保持方式

显示构建顺序为：`MEASURED` 优先保留 formal 值；仅当帧为非 `MEASURED`、时间严格早于显式事件边界且显示平台启用时，写入配置平台；其余帧沿用 formal 数组中的 NaN。由此，事件后的 `NO_DETECTABLE_BEAT`、`AMBIGUOUS_PEAK`、`UNSTABLE_DETECTION`、`REFINEMENT_FAILED`、`INSUFFICIENT_CYCLES`、`PEAK_AT_BAND_BOUNDARY` 和 `OUTSIDE_ANALYSIS_WINDOW` 均不会被填成平台值。

## 9. 未来导出契约

`docs/ui/TASK-014_UI_ARCHITECTURE.md` 已记录 TASK-016 的未来契约，但本任务没有实现导出：

- 导出必须分列 `apparent_velocity_m_s`、`display_velocity_m_s`、`signal_state`；
- 元数据记录 `pre_event_display_velocity_m_s`；
- 未来 GUI 选项为“包含事件前显示平台”，默认包含；
- 该选项只决定 `display_velocity_m_s` 的事件前展示/导出，任何非 `MEASURED` 帧的 `apparent_velocity_m_s` 始终保持 NaN。

GUI 没有导入或调用 `scripts/production_outputs.py`，也没有新增 CSV writer。

## 10. 新增和修改文件

TASK-015C 新增：

- `src/dps_studio/core/workflow/display.py`
- `tests/unit/test_display_velocity.py`
- `tests/unit/gui/test_task015c_display_velocity.py`
- `artifacts/task015c_ui/render_task015c_screenshots.py`
- `artifacts/task015c_ui/pre_event_display_zero_zh.png`
- `artifacts/task015c_ui/pre_event_display_nonzero_zh.png`
- `artifacts/task015c_ui/formal_vs_display_zh.png`
- `docs/TASK-015C_REPORT.md`

TASK-015C 修改：

- `src/dps_studio/core/workflow/__init__.py`
- `src/dps_studio/core/workflow/analysis.py`
- `src/dps_studio/core/workflow/config.py`
- `src/dps_studio/gui/analysis_adapter.py`
- `src/dps_studio/gui/analysis_session.py`
- `src/dps_studio/gui/main_window.py`
- `src/dps_studio/gui/result_views.py`
- `src/dps_studio/gui/translations/pdv_studio_en.ts`
- `src/dps_studio/gui/translations/pdv_studio_en.qm`
- `configs/demo_dual_profile.toml`
- `configs/pdv_studio_defaults.toml`（该文件由开始前未提交的 TASK-015B 新增，本任务只扩展显示参数）
- `tests/unit/test_signal_detection.py`
- `tests/unit/test_workflow_config.py`
- `docs/ui/TASK-014_CODE_FLOW_MAP.md`
- `docs/ui/TASK-014_UI_ARCHITECTURE.md`
- `docs/ui/TASK-014_UI_TERMINOLOGY.md`

`git diff --stat` 还包含开始前已有的 TASK-015B 同文件修改，因此不能把当前总 diff 的全部行数归因于 TASK-015C。

## 11. pytest

- TASK-015C core/GUI 增量回归：`78 passed in 2.44s`。
- 最终完整测试集使用独立 basetemp/cache，并通过环境 `PYTEST_ADDOPTS` 隔离参数，结果为：`380 passed in 17.26s`。
- 另用显式 pytest 参数复验既有问题，结果为：`379 passed, 1 failed in 17.38s`。唯一失败仍是 `tests/unit/test_package.py::test_cli`：被测 CLI 的 `argparse` 直接读取 pytest 的 `-q --basetemp ... -o cache_dir=...`。本任务按边界没有修改 CLI 或该既有测试。

新增回归覆盖默认 0 m/s、12.5 m/s、formal 不变、各类事件后无效状态、NaN 断线、两通道独立、GUI 中英文、无 STFT 重跑、无 scripts 导入及真实 workflow 前后对比。

## 12. Ruff

最终执行 `python -m ruff check .`：`All checks passed!`

## 13. mypy

最终执行 `python -m mypy src`：`Success: no issues found in 59 source files`。

## 14. diff check

最终 `git diff --check` 与 `git diff --cached --check` 均通过。Git 仅报告 Windows 工作树未来可能进行 LF→CRLF 转换的提示，没有空白错误。

## 15. 真实数据验收

验收脚本通过必填 `--data` 接收用户选择的数据路径，未在代码中写死真实数据路径。本次使用 `data/raw/20260607.csv`，加载双通道并实际运行 GUI 自动分析至 `RESULT_READY`。

验收结果：通道为 `pdv_channel_1,pdv_channel_2`；两通道共 432 个事件前非 `MEASURED` 显示帧和 37 个事件后无效帧；0 m/s 与 12.5 m/s 均只改变事件前 display 数组；切回 0 m/s 后恢复；正式 apparent velocity、主体 `MEASURED` 速度、事件后 NaN、STFT 对象和通道独立性均通过断言。display 参数切换前后 generation 保持为 3，后台分析重启数为 0。

## 16. 截图

- `artifacts/task015c_ui/pre_event_display_zero_zh.png`：中文速度页、0.000000 m/s 参数及事件前零显示平台。
- `artifacts/task015c_ui/pre_event_display_nonzero_zh.png`：中文速度页、12.500000 m/s 参数及真实数据曲线。
- `artifacts/task015c_ui/formal_vs_display_zh.png`：正式表观速度与显示速度的独立图例和有限段曲线。

三张图均由 Windows 原生 Qt 窗口和真实分析结果生成；已逐张目视检查中文字体、字段名、单位、图例和曲线布局。

## 17. 当前限制

- 显示平台只在存在显式 `manual_event_reference_time_s` 时应用；没有显式边界时不会猜测事件前区域。
- 兼容配置键仍名为 `assume_pre_event_zero_for_display`，但平台数值已参数化；未来若迁移键名，需要单独兼容策略。
- 正式导出、未来导出 checkbox、ROI、LiF/窗口修正、新降噪、STFT/ridge/detection 算法均未实现或修改。
- 已知 CLI 直接读取 pytest `sys.argv` 的问题仍存在，详见第 11 节。

## 18. git status

最终仍位于 `main...origin/main`。工作树包含开始前未提交的 TASK-015B 项，以及第 10 节列出的 TASK-015C core、GUI、配置、翻译、测试、文档和验收产物；没有 `scripts/**`、`outputs/**`、`notebooks/**`、`presentation/**`、`presentations/**` 或 `data/raw/**` 工作树修改。本任务没有执行无关重构。

## 19. staged 状态

`git diff --cached --stat` 与 `git diff --cached --check` 均无输出。没有执行 `git add`、commit 或 push。

## 20. data/raw 完整性

`git status --short -- data/raw` 无输出，`data/raw` 没有修改、覆盖或新增。真实验收源文件 `data/raw/20260607.csv` 的 SHA-256 为 `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`；验收脚本只读该文件并将截图写入 `artifacts/task015c_ui/`。
