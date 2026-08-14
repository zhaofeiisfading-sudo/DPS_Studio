# TASK-015 Follow-up 报告：多列导入、流程联动、第六步预览与 GUI 安全瘦身

## 1. 修改前问题

- `ImportSettingsDialog` 固定创建一个必选信号和一个默认启用的第二信号，列选择器固定允许 `0..999`。两列文件因此会默认请求不存在的 column 2。
- 信号行里的整数只有 tooltip 解释为 zero-based column index，视觉上容易被误认为电压量程；V/mV 也没有明确区分 CSV 数值单位与示波器 V/div。
- 打开文件后没有轻量结构预览，GUI 不知道实际列数、初步表头、分隔符或列样例。
- 左侧步骤只切换右侧参数页，不切中央科学 tab；后台操作完成后也没有一次性的目标页跳转。
- 第六步的 analysis mode/channel 只控制导出参数，没有驱动中央预览。缺失 Guided 通道无法作为安全的“无结果”目标进行复核。
- `MainWindow` 尾部保留两个已无 caller 的 planned placeholder 构建 helper。

## 2. 导入模型的新语义

GUI 现在只构造通用的 `ChannelImportSpec` tuple：

- 必须且只能选择一个时间列；
- 至少一个、最多三个启用信号；
- 源文件可有任意合理列数，未选列由现有 strict core reader 报告为 unselected，不生成 `SignalRecord`；
- 两列默认 `time=0, signal1=1`；三列默认启用 signal1/2；四列及以上默认启用 signal1/2/3；
- 每个 spin box 最大值为 preview 得到的 `column_count - 1`；
- 禁用槽的 name/column/unit 整体灰显，不参与 validation，也不进入请求；
- 校验覆盖无信号、空名、重名、重复信号列、time == signal、实际范围和单字符 delimiter；
- `DataImportController` 在 GUI 边界再次校验 1–3 信号、名称/列唯一性及 time/signal 分离，避免 dict 构造静默覆盖；“最多三信号”没有进入科学 core。

`delimited_preview.py` 只读取开头最多 32 KiB 和最多五条 CSV record，使用标准库 `csv.Sniffer` 做 tentative delimiter/header 检测，并明确允许用户手动覆盖。它不完整加载大文件，也不替代 `read_delimited_signals` 的严格全文件校验。

界面明确显示：

- `电压列（从 0 开始）`；
- `CSV 中该列的单位`；
- V/mV 不是 V/div 或硬件输入量程；
- 实际列数、合法索引、delimiter、encoding、tentative header 和每列短样例。

## 3. 修改文件

- `src/dps_studio/gui/delimited_preview.py`：新增有界结构 preview。
- `src/dps_studio/gui/import_dialog.py`：三槽动态导入 UI、实际范围、预览和可读 validation。
- `src/dps_studio/gui/data_controller.py`：GUI 请求边界校验，继续调用唯一的 public core reader。
- `src/dps_studio/gui/main_window.py`：步骤/tab 一次性联动、Step 6 target/preview 同步、删除 dead placeholder helper。
- `src/dps_studio/gui/result_views.py`：纯 view 的 mode/channel 选择入口；Step 6 显示简单 CSV 实际使用的 display velocity；缺失结果清图。
- `src/dps_studio/gui/raw_signal_view.py`：把过时的 “one or two channels” docstring 改成 loaded channels。
- `src/dps_studio/gui/translations/pdv_studio_en.ts`、`.qm`：更新双语 GUI；447 finished、0 unfinished。
- `tests/unit/gui/test_task015_followup.py`：新增导入、单/双/三通道、导航及 Step 6 测试。
- `tests/unit/gui/test_task017_result_export.py`：按新安全复核语义更新 Guided 缺失通道断言。

## 4. 单/双/三信号通道行为

- 单信号：真实后台 Automatic 测试覆盖独立 STFT、ridge、velocity 和 Step 6 preview。
- 双信号：现有 reader、GUI workflow、Guided、export 和数值 regression 保持；未修改科学函数或数组。
- 三信号：真实后台 Automatic 测试覆盖三个独立结果和 channel 3 的 Step 6 preview。
- 任意多源列：GUI 最多选择三个信号，其他列忽略；测试覆盖六列源文件和任意列映射。
- `SignalRecord`、STFT、ridge、event detection、velocity/window/LiF 数学代码均未修改。

## 5. 双通道 consensus 边界

审计确认 reader、`AnalysisSession`、STFT 和 GUI analysis workflow 都遍历 channel mapping；GUI 主分析路径不调用双通道 consensus。core 中明确要求 exactly two streams 的 `build_profile_consensus` 保持原样：

- 没有为单通道伪造第二通道；
- 没有为三通道偷偷选前两个；
- 没有做通道平均或扩展科研融合定义；
- 正好双通道的既有共识行为不变。

## 6. 页面自动跳转规则

- Step 1 数据导入 → Raw Signal；空会话实际点击该项会打开现有 file/import flow。
- Step 2 分析范围 → Raw Signal。
- Step 3 时频分析：已有 STFT 立即进入 Spectrogram；否则运行现有 STFT，成功后只切一次 Spectrogram，失败保持原页。
- Step 4 脊线提取：只有 STFT 时进入 Spectrogram；现有 Automatic/Guided result 时进入 Ridge；显式 staged/Guided ridge 成功后只切一次 Ridge。
- Step 5 速度结果：已有正式结果进入 Velocity；否则运行现有完整 Automatic，最终成功后只切一次 Velocity。
- Step 6 复核与导出 → 现有 Velocity 主预览和既有 export 参数页，没有新造页面。

`_pending_navigation_tab` 只记录一次用户操作的最终语义目标。Automatic 内部的 STFT/RIDGE/RESULT 状态更新不会逐阶段改变 tab；测试观察到完整 Automatic 只有最终 `[Velocity]` 一次 `currentChanged`。

## 7. Step 6 preview / export state 联动

- 导出 mode 和 channel 的变化立即调用 `VelocityView.select_result_target`，不启动任何 worker、不修改 generation id、不重算 STFT/ridge/analysis。
- channel selector 在当前 mode 下仍列出所有 loaded channels；有效性继续由当前 mode 的 result mapping 判定。因此可以安全查看“Guided / channel 2 尚无结果”的状态。
- 缺失目标会调用现有清图路径，`formal_curve/display_curve` 不残留；notice 明确提示，export button 禁用。
- 简单 CSV 的既有正式 contract 是 `time + display_velocity_m_s`；detail CSV 同时包含 apparent、angle-corrected、corrected、display velocity。Step 6 因此固定显示同一个 `display_velocity_m_s` 数组，同时保留现有 apparent/corrected 曲线和标签。离开 Step 6 后恢复用户原先的 display-velocity 显示选择。
- 测试覆盖 Automatic channel 1/2、Guided channel 1、缺失 Guided channel 2，以及单/三通道目标；验证 selector = preview source = preview channel = export target。

## 8. GUI dead code 审计

### Removed

- `MainWindow._planned_view`
- `MainWindow._planned_parameters`

证据：修改前对全部 `src/dps_studio/gui/*.py` 做 AST/function-name 引用计数，两者都只有 definition 自身一次文本引用；全 tests 无引用、无 signal connection、无 runtime caller。现有五个科学 tab 和六个参数页都已由真实 builder 构造。删除后相关 GUI、全量 pytest、Ruff 和 mypy 均通过。

另修正 `RawSignalView` 的过时私有 docstring，不再声称只支持 one/two channels。

### Kept

- `AnalysisSession._stale_guided_results`：静态引用审计显示当前无直接 caller，但它表达共享依赖变化时 Guided cache 整体 stale 的安全语义；本 TASK 明令保留 session cache/generation safety，故 KEEP。
- result view 的 `set_analyses` compatibility entry：已有测试和兼容调用价值，KEEP。
- generation id、background adapter、late-result rejection、export safety、provenance/error handling：全部 KEEP。
- 大型 `MainWindow`：只增加局部联动 helper，没有 MVC/MVVM 拆分或状态机重写。

## 9. 测试

开始前基线：

- `pytest -q`：530 collected，529 passed，1 failed。
- 唯一失败：`tests/unit/test_package.py::test_cli` 直接调用 `main()`，继承 pytest 自身 `-q`，生产 CLI 正确拒绝未知参数。
- `ruff check .`：passed。
- `mypy --strict src`：passed。

完成后：

- 新 follow-up offscreen tests：14 passed。
- 相关 I/O/session/staged/Guided/export regression：113 passed。
- `pytest`（不向被测 CLI 注入 pytest 参数）：544 passed in 60.27 s。
- 任务要求的原命令 `pytest -q`：544 collected，543 passed，1 failed；仍为同一个基线 `test_cli` / inherited `-q`，未出现新失败。
- `ruff check .`：passed。
- `mypy --strict src`：77 source files，passed。
- Qt translation：447 finished，0 unfinished。
- `git diff --check`：passed；仅 Git 给出既有 LF→CRLF working-copy warning，不是 whitespace error。

没有把生产 CLI 改成忽略未知参数，也没有修改这个任务范围外的 CLI test 来掩盖基线问题。

## 10. Offscreen smoke test

`QT_QPA_PLATFORM=offscreen` 下完成：

- Case A：2-column `time + voltage`，默认只启用 signal 1，严格 reader 成功。
- Case B：3-column `time + ch1 + ch2`，默认双通道行为不变。
- Case C：4-column 默认三个信号；另用三通道真实 Automatic 验证独立显示。
- Case D：关闭 signal 2、清空其名称，其控件灰显且不影响 signal 1/3 load。
- Case E：Raw/Spectrogram/Ridge/Velocity 步骤跳转及一次性 Automatic focus change。
- Case F：Automatic/Guided、channel 1/2、缺失 Guided 和 channel 3 的 Step 6 同步。

测试输入和导出均位于 task-owned pytest temp；`git diff -- data/raw` 为空，未写入 `data/raw`。

## 11. Git 状态

- 分支：`codex/feature/task-018-auto-analysis`
- HEAD：`3b39efb 修改：（窗口修正）优化修正流程，切换材料不会从新开始`
- `git diff --cached --stat`：空。
- 未执行 `git add`、commit、push、reset、checkout 或 clean。
- 开始前已有的大量 `.pytest_tmp` / TASK-016R3 residue 删除、`.gitignore`、`pyproject.toml`、`data/reference`、`docs/learning`、`run_demo_pipeline.bat` 等工作树状态均未回滚或纳入本任务。
- 本任务改动只位于上文列出的 GUI、translations、两份 GUI tests 和本报告；`data/raw` 无 diff。

