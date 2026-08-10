# TASK-017 正式结果文件导出流程报告

## 结论

TASK-017 的正式 CSV + JSON sidecar 导出、GUI 接入、Automatic/Guided
隔离、双通道隔离、事件前 display-only 语义和不覆盖写入均已实现。
未新增分析算法、通道融合、LiF 修正、项目保存、报告生成或发布打包。

完整 pytest 命令运行到 455 项，其中 454 项通过；唯一失败是既有
`tests/unit/test_package.py::test_cli` 直接调用 CLI 时继承 pytest 自身
命令行参数，拒绝 `--basetemp`。这与 TASK-017 导出实现无关，本任务未
修改 CLI 参数设计。排除该既有测试后的 452 项全部通过；TASK-017 的 9 项
定向测试全部通过。

## 开始前审计

- HEAD: `deb8fa8bbd897eb9cf0c0eea76fafe5a7ac04c9e`
  (`main`, `origin/main`)。
- 最近提交包括 `deb8fa8`（GUI 引导模式/鼠标样式）、`221206e`
  （Guided Analysis）、`c48c572`（事件前显示平台）。
- 暂存区为空。
- 原有未提交项被保留且未暂存：TASK-016R3 相关
  `analysis_range.py`、`main_window.py`、`styles.py`、测试与 artifacts，
  以及 `docs/TASK-016R3_REPORT.md`。它们不属于本任务。
- 历史中确有 `presentation` / `presentations` 删除记录（提交
  `1d0df14`）；未恢复、修改或暂存这些历史删除。
- `data/raw` 初始有 `.gitkeep` 和四份 CSV；初始 SHA-256 与本报告末尾
  的复验值完全相同。

## 审计到的既有架构

- `AnalysisSession.channel_analyses` 保存当前 Automatic 结果；
  `guided_channel_analyses` 与 `guided_result_valid_channels` 保存当前有效
  的 Guided 结果。二者没有合并或择优逻辑。
- 参数、分析范围或共享依赖变化会使 Automatic 结果失效；走廊变化只使
  对应 Guided 通道失效。导出只读取这些现有有效状态。
- `ChannelAnalysis` 中正式速度是
  `SignalDetectionResult.apparent_velocity_m_s` / `refined_velocity_m_s`，
  显示速度是独立的 `display_velocity_m_s`。
- `core.workflow.display.PRE_EVENT_DISPLAY_ORIGIN` 为
  `configured_pre_event_display_velocity_only`。它表示 display-only 平台；
  对应正式表观速度继续是 `NaN`，不被导出逻辑改写。
- 旧 Review & Export 页和 `actionExport` 均为禁用占位；
  `scripts/production_outputs.py` 仍是开发/历史脚本，未被 GUI 调用。
- 翻译采用 Qt `.ts` + `.qm`；本任务同步更新并重新编译英文资源。

## 实现与 public API

新增 `dps_studio.core.export`，并从 `dps_studio.core` 公开以下 API：

- `ResultAnalysisMode`：`automatic` 或 `guided`。
- `ResultExportOptions`：一个模式、一个或多个独立通道、用户选择的输出
  父目录及实际可得的 provenance。
- `export_formal_results(options)`：写出结果并返回 `ResultExportReport`。
- 明确的 `ResultExportValidationError` 与 `ResultExportWriteError`。

导出器只读取不可变 `ChannelAnalysis`。它不运行 STFT、脊线、速度或 Guided
算法，不修改输入结果，不插值、不平滑、不把 `NaN` 变成零，也不融合通道。

每次调用先在用户选定父目录下创建唯一目录
`pdv_studio_export_YYYYMMDDTHHMMSSZ`；同名时追加安全 suffix。文件先写入
该目录的 `.staging`，仅在 CSV 和 JSON 都成功后移动到最终目录。失败会清理
本调用创建的目录，避免留下看似成功的半套结果。任何 `data/raw` 内部路径都
会被拒绝，GUI 也显式将仓库 `data/raw` 传为保护目录。

## CSV schema

所有数值均为内部 SI 单位；不可靠的浮点值用稳定文本 `nan` 保留。

```text
time_s
coarse_peak_frequency_hz
refined_frequency_hz
apparent_velocity_m_s
display_velocity_m_s
ridge_quality_flag
ridge_refinement_status
signal_state
velocity_origin
is_pre_event_display_only
channel
analysis_mode
```

`apparent_velocity_m_s` 始终是正式质量门控结果。`display_velocity_m_s`
只保留显示约定；`is_pre_event_display_only=true` 时，正式速度仍为 `nan`。

## JSON metadata schema

每个 CSV 配套 `<channel>_<mode>.metadata.json`，包含：

- `export_schema_version`、`dps_studio_version`、`exported_at_utc`；
- `data_file`、`source_file`、`source_channel`、`analysis_mode`、
  `analysis_profile_name`；
- `analysis_time_range_s`；
- `stft_configuration`、`ridge_configuration`、`quality_configuration`；
- `vacuum_wavelength_m`、`event_reference_time_s`、`pre_event_display`；
- `result_counts`（帧数、MEASURED、display-only、各质量/状态计数）；
- `result_status`（正式/显示列、NaN、无平滑、无通道融合的明确语义）。

系统中不存在的信息写为 `null`，不猜测元数据；未写入任何 LiF/window
correction 公式或参数。

## Automatic、Guided、双通道与事件前规则

- Automatic 与 Guided 使用独立 `ResultAnalysisMode` 请求，只能分别导出；
  GUI 下拉框只显示当前有效模式。
- 每次 GUI 导出选择一个当前有效通道；底层 API 可在同一模式请求中为多个
  通道各写独立的 CSV/JSON 文件，不会合并数据。
- GUI 的“包含事件前 display-only 平台”默认勾选，只影响输出行范围。关闭后
  仅滤除 `velocity_origin == configured_pre_event_display_velocity_only` 的行，
  不改变内存结果或正式速度。
- 无有效结果时 Export action、模式/通道与写入按钮均禁用；取消目录选择仅写
  日志，不抛异常。

## GUI 接入与翻译

Review & Export 参数页现在提供当前有效结果说明、Automatic/Guided 选择、通道
选择、目录选择、事件前 display-only 选择和 `CSV + JSON` 导出按钮。成功与失败
同时写入状态栏/日志；失败显示明确错误对话框。英文 `.ts` 已补充新增文本，
`pdv_studio_en.qm` 已由 Qt 6.11.1 `pyside6-lrelease` 重新生成。

## 新增/修改文件

- `src/dps_studio/core/export/__init__.py`
- `src/dps_studio/core/export/models.py`
- `src/dps_studio/core/export/writer.py`
- `src/dps_studio/core/__init__.py`
- `src/dps_studio/gui/main_window.py`
- `src/dps_studio/gui/translations/pdv_studio_en.ts`
- `src/dps_studio/gui/translations/pdv_studio_en.qm`
- `tests/unit/test_formal_result_export.py`
- `tests/unit/gui/test_task017_result_export.py`

## 测试与质量门

使用环境：`D:\miniconda3\envs\dps-studio\python.exe`，Python 3.12.13。

- TASK-017 定向测试：`10 passed`。覆盖 Automatic、Guided、双通道、SI schema、
  `NaN`、状态、metadata round-trip、无覆盖、保护路径/写入失败、输入不变、
  GUI 无结果、GUI 取消、GUI 模式/通道、英文翻译。
- `python -m pytest --basetemp=.pytest_tmp/task017_full_final`：`454 passed, 1 failed`。
  失败是前述既有 `test_cli` 参数继承问题；另有默认 pytest cache 目录拒绝访问
  警告，专用 basetemp 本身正常工作。
- 排除该既有 CLI 测试：`453 passed`。
- `python -m ruff check .`：通过（exit 0）；对历史临时目录有访问拒绝警告。
- `python -m mypy src/dps_studio`：`Success: no issues found in 65 source files`。
- `python -m dps_studio.gui`：进程成功启动并保持运行 5 秒。

## 实际 GUI smoke export

在原生 Windows Qt 平台读入 `data/raw/20260607.csv`，用现有 GUI 执行两通道
Automatic 分析后，选择 `artifacts/task017` 为输出目录并导出 channel 1：

- [CSV](/D:/Code/Python_Projects/DPS_Studio/artifacts/task017/pdv_studio_export_20260806T135417Z/pdv_channel_1_automatic.csv)
  含 620 行；
- [metadata JSON](/D:/Code/Python_Projects/DPS_Studio/artifacts/task017/pdv_studio_export_20260806T135417Z/pdv_channel_1_automatic.metadata.json)
  可正常解析，`analysis_mode=automatic`；
- `pre_event_display.enabled=false`，但 GUI 选择仍为包含，故没有伪造的
  display-only 行；
- smoke 前后源文件 `20260607.csv` SHA-256 相同。

## data/raw 最终 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `.gitkeep` | `F1945CD6C19E56B3C1C78943EF5EC18116907A4CA1EFC40A57D48AB1DB7ADFC5` |
| `20260607.csv` | `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353` |
| `20260630-1.csv` | `203B182E477E1E08214551977A00313EAF6F17A71391D83875F6F879DC3A0A74` |
| `20260630-2.csv` | `C0C31B2990EAE228B21594276D030B83600A7DDB98C1953842E4CB80C17FA261` |
| `20260701.csv` | `5CCB6530E0CC715E4A7A81327C625FCE267A8B3473C0487479366EAD9D9A952A` |

文件数量与全部内容均未改变。

## 最终状态与待决项

### 必须修正

无 TASK-017 范围内的必须修正项。

### 建议优化

既有 `test_cli` 应通过显式 argv 调用 CLI（或让 `main` 接受 argv），以便完整
pytest 命令不把 pytest 自己的参数传给 argparse。此项未在 TASK-017 中修改。

### 暂不处理

TASK-016R3 的既有未提交 GUI 样式改动、测试、artifact 与报告保持原状；历史
`presentation` / `presentations` 删除同样未触及。

### 未知或需实验确认

没有新增 LiF/window correction。CSV 中的 `MEASURED` 仍只表示当前配置下的
谱学质量门控结果，不确认物理分支身份；实际实验阈值与物理解释仍需实验确认。

未创建 Git commit、未 push、未修改 `data/raw`。
