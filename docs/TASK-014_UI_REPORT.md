# TASK-014 当前处理链审计与 PDV Studio UI 工作台报告

日期：2026-07-31

## 1. 开始前 Git 和测试状态

- HEAD：`f0bd81b8baf116d71630ac7826fd08fb49419fab`
- 分支：`main...origin/main [ahead 1]`
- 暂存区：空
- `git diff --check`：通过
- 开始前工作树已有 631 个 `presentation/**`、`presentations/**` tracked 删除，
  `git diff --stat` 为 71,950 行删除；这些是用户既有改动，本任务未恢复、删除、
  格式化或覆盖。
- `docs/ui/README.md`、三个 TASK-014 文档草稿为开始前已有 untracked 文件；
  保留其结构并在其中增量完成审计内容。
- Python 3.12.13；PySide6 6.11.1；PyQtGraph 0.14.0；
  `pyside6-lupdate` 和 `pyside6-lrelease` 均可用。
- 原样基线 `python -m pytest`：收集 337 项，261 passed、76 errors。76 项全部在
  setup 阶段因
  `C:\Users\89484\AppData\Local\Temp\pytest-of-89484` 的既有
  `PermissionError [WinError 5]` 失败，没有 assertion failure。
- 基线 Ruff：通过。基线 mypy：42 个源文件无问题。

## 2. 当前真实数据处理调用链

```text
run_demo_pipeline.bat
-> scripts/run_demo_pipeline.py
-> load_workflow_configuration
-> read_delimited_signals
-> scripts.production_outputs.run_production_outputs
-> calibration / parameter selection
-> core.workflow.analyze_profile
-> core.workflow.analyze_configuration
-> each PDV channel independently:
   compute_stft
   -> extract_peak_ridge
   -> refine_peak_ridge_subbin
   -> provisional discrete apparent velocity
   -> spectral quality diagnostics
   -> detect_beat_signal
   -> quality-gated formal frequency
   -> apparent velocity
   -> separate display_velocity_m_s
   -> continuity diagnostics
   -> stream event candidates
-> profile and cross-profile event consensus metadata
-> CSV / figures / manifest production export
```

两个 PDV 电压通道逐通道独立计算。当前没有电压平均、数值通道融合或 profile
数值融合；事件 consensus 只形成事件元数据。当前也没有正式 LiF 修正、正式自动
降噪或 corrected velocity 结果。

完整逐阶段输入、输出、单位、调用者和 GUI 适用性见
`docs/ui/TASK-014_CODE_FLOW_MAP.md`。

## 3. 关键模块职责

| 模块 | 实际职责 |
|---|---|
| `core/models/signal.py` | `SignalRecord`：验证并保存单通道只读时间、电压及采样摘要 |
| `io/delimited.py` | `read_delimited_signals`：按显式列、单位比例、分隔符和表头读取一个或两个通道 |
| `core/workflow_config.py` | 加载并验证 `AnalysisConfiguration` 和各配置数据模型 |
| `core/stft.py` | `compute_stft`，产生只读 `STFTResult` |
| `core/ridge.py` | 搜索带内离散峰 `extract_peak_ridge` |
| `core/ridge_refinement.py` | `refine_peak_ridge_subbin`，进行亚频点局部精修 |
| `core/ridge_spectral_quality.py` | 峰—背景、峰—竞争峰等逐帧频谱质量诊断 |
| `core/signal_detection.py` | `detect_beat_signal`，给出 `SignalState`、门控和正式频率 |
| `core/velocity.py` | 从拍频计算表观速度；正式结果和显示结果分开 |
| `core/ridge_diagnostics.py` | 脊线连续性与质量标记 |
| `core/workflow.py` | 按通道和 profile 编排正式分析，不执行文件导出 |
| `scripts/production_outputs.py` | 生产运行编排、Matplotlib、CSV、图片和 manifest；不是 GUI service |
| `gui/data_controller.py` | 把 GUI 的显式导入请求适配到 public reader |
| `gui/raw_signal_view.py` | 用 PyQtGraph 显示真实原始通道，仅做 s→μs、V→mV 显示转换 |
| `gui/main_window.py` | 组合工作台区域、动作和状态可用性，不包含科学算法 |

## 4. GUI 可使用的 API

- 已真实使用：public `read_delimited_signals`，通过薄
  `DataImportController` 适配显式用户输入。
- 可作为后续稳定科学调用基础：`compute_stft`、`extract_peak_ridge`、
  `refine_peak_ridge_subbin`、`detect_beat_signal`、
  `analyze_configuration` 和 `analyze_profile`。
- 后续仍缺少 GUI 专用的异步分析 application service、结果失效协调器和
  public export service。当前没有从 private 模块或脚本强行拼接这些能力。

## 5. 明确没有引入 GUI 的代码

GUI 不导入 `scripts.*`、`tests.*`、`notebooks.*`、
`scripts.production_outputs`、`outputs/**`、`presentation/**` 或
`presentations/**`。没有复制 STFT、脊线、速度公式、信号门限或 production
输出流程。`core/**` 也没有反向导入 `dps_studio.gui`；自动测试会扫描这两个
依赖方向。

## 6. UI 主窗口结构

`QMainWindow` 包含原生菜单栏、常用工具栏、状态栏，以及：

- 左侧六步流程导航；
- 中央 Raw Signal、Spectrogram、Ridge、Velocity、Comparison 五个标签页；
- 右侧随步骤切换的 `QStackedWidget` 参数区；
- 底部可停靠的 Quality、Data、Log 诊断区；
- 左、中、右使用可拖动 `QSplitter`，中央绘图区具有最大 stretch priority。

六个顺序状态均已定义：
`EMPTY`、`DATA_LOADED`、`RANGE_DEFINED`、`STFT_READY`、
`RIDGE_READY`、`RESULT_READY`。本任务只允许真实到达前两个状态。STFT、Ridge、
Velocity 和 Export 的页面及动作保持禁用，并提供“计划功能/尚未接入”提示。

## 7. 中英文实现状态

默认简体中文。英文使用 `self.tr()`、`QTranslator` 和 Qt Linguist
`.ts/.qm` 资源实现，共 129 条完成翻译。设置菜单可以选择语言，`QSettings`
持久化选择，重启应用后生效。数据字段、配置键和内部枚举不随 UI 语言改变。

## 8. 真实数据加载实现状态

实现链路：

```text
QFileDialog
-> ImportSettingsDialog
-> SignalLoadRequest
-> DataImportController
-> public read_delimited_signals
-> read-only SignalRecord
-> PyQtGraph RawSignalView + data summary
-> DATA_LOADED
```

对话框要求用户显式指定时间列、一个或两个电压列、通道名、分隔符、表头、
encoding、时间单位和每通道电压单位。额外列不会静默丢弃，而在数据摘要中报告。
两个通道保持独立，没有平均、插值、平滑或填补 NaN。源文件不写入，内部数据保持
s 和 V，绘图层显示 μs 和 mV。

## 9. 新增和修改文件

开发前 `src/dps_studio/gui/` 中只有已跟踪的 `__init__.py`，内容为
`"""Package module."""`，无类、函数、入口或已有功能，判定为纯占位。该文件和
原目录继续沿用，没有删除、覆盖目录或创建平行 GUI 包。

| 文件 | 变更及沿用结论 |
|---|---|
| `src/dps_studio/gui/__init__.py` | 在原占位文件上增量补充包边界说明及 `WorkflowState` 导出；继续沿用 |
| `src/dps_studio/gui/__main__.py` | 新增 `python -m dps_studio.gui` 入口 |
| `src/dps_studio/gui/app.py` | 新增 QApplication、样式、翻译器生命周期 |
| `src/dps_studio/gui/state.py` | 新增六阶段 UI 状态机 |
| `src/dps_studio/gui/data_controller.py` | 新增 public reader adapter |
| `src/dps_studio/gui/import_dialog.py` | 新增显式导入设置对话框 |
| `src/dps_studio/gui/raw_signal_view.py` | 新增 PyQtGraph 原始信号视图 |
| `src/dps_studio/gui/main_window.py` | 新增工作台主窗口组合 |
| `src/dps_studio/gui/i18n.py` | 新增 Qt 翻译和语言持久化 |
| `src/dps_studio/gui/styles.py` | 新增小规模浅色 QSS 和系统字体规则 |
| `src/dps_studio/gui/translations/pdv_studio_en.ts` | 新增英文翻译源 |
| `src/dps_studio/gui/translations/pdv_studio_en.qm` | 新增编译后的英文翻译资源 |
| `tests/unit/gui/conftest.py` | 新增 offscreen Qt 测试环境 |
| `tests/unit/gui/test_gui_shell.py` | 新增 7 项 GUI、真实 reader 和边界测试 |
| `docs/ui/TASK-014_CODE_FLOW_MAP.md` | 完成处理链与 API 审计 |
| `docs/ui/TASK-014_UI_ARCHITECTURE.md` | 完成 UI 架构、原 GUI 逐文件审计与边界说明 |
| `docs/ui/TASK-014_UI_TERMINOLOGY.md` | 完成固定中英文术语表 |
| `docs/TASK-014_UI_REPORT.md` | 本报告 |
| `artifacts/task014_ui/render_screenshots.py` | 新增真实 Qt 截图脚本 |
| `artifacts/task014_ui/main_window_zh.png` | 1440×900 中文实际窗口截图 |
| `artifacts/task014_ui/main_window_en.png` | 1440×900 英文实际窗口截图 |
| `artifacts/task014_ui/layout_check_1280x720_zh.png` | 1280×720 最小尺寸人工检查截图 |

没有修改 `pyproject.toml`、`core/**`、`scripts/**`、`configs/**` 或原有算法测试。

## 10. 测试、Ruff、mypy 和 diff check

- 任务要求的原样全量 pytest：344 项，266 passed、78 setup errors。错误仍全部
  来自同一个既有 pytest 临时目录 `PermissionError [WinError 5]`，没有 assertion
  failure。
- 为隔离该环境问题，用新的独立 `--basetemp` 和 cache 目录运行同一完整测试集：
  **344 passed in 14.08s**。
- Ruff 全仓：`All checks passed!`
- mypy：`Success: no issues found in 51 source files`
- `git diff --check`：通过；仅提示现有 `__init__.py` 下次 Git 处理时可能执行
  LF→CRLF 转换，不是 whitespace error。

## 11. 截图与人工检查

- `artifacts/task014_ui/main_window_zh.png`
- `artifacts/task014_ui/main_window_en.png`
- `artifacts/task014_ui/layout_check_1280x720_zh.png`

三张图均由实际 Windows Qt 窗口抓取，不是绘图软件仿造。已人工检查 1440×900
中英文和 1280×720 中文：无乱码、明显文本溢出、控件重叠或图表标签重叠；中央
绘图区占主要空间，左右面板可拖动缩放，禁用功能状态清楚，窗口可正常关闭。

## 12. 已知限制和下一任务建议

- 当前只完成原始文件加载与 `EMPTY -> DATA_LOADED`，没有接入范围、STFT、脊线、
  速度或导出。
- 完整科学分析可能耗时，后续必须通过可取消的后台任务调用，不能阻塞 GUI 主线程。
- 当前 production export 与 Matplotlib、生产目录和脚本编排耦合，不适合 GUI
  直接调用；建议后续先在 application/public 层定义无 GUI、无 Matplotlib 的结果
  与导出 service。
- 多边形 ROI 应保存 `time_s`、`frequency_hz` 科学坐标，并由正式 core adapter
  消费；本任务未开始该功能。
- 未实现 LiF 修正、自动降噪、文件夹监视或示波器连接。

## 13. 最终 Git 状态

最终状态仍为 `main...origin/main [ahead 1]`，HEAD 未改变。porcelain 状态共
646 项：631 个开始前已有的 presentation tracked 删除、1 个本任务增量修改的
`src/dps_studio/gui/__init__.py`，以及 14 个未跟踪路径组（包括 TASK-014 的新
GUI、测试、文档和截图；未跟踪目录由 Git 折叠显示）。开始前用户已有的删除和
untracked 文档均未被清理或回退。

## 14. 暂存区

暂存区为空；未执行 `git add`、commit 或 push。

## 15. `data/raw` 完整性

`git diff -- data/raw` 和 `git diff --cached -- data/raw` 均为空。TASK-014 没有
写入、覆盖或删除 `data/raw/**`，也没有修改导入的源数据文件。
