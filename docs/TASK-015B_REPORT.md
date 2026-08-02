# TASK-015B 实施报告

## 1. 开始前状态

- 仓库：`D:\Code\Python_Projects\DPS_Studio`
- 分支：`main...origin/main`
- 开始前 `git status --short --branch` 仅输出分支行，工作树和暂存区均为空。
- 开始前 `git diff --stat`、`git diff --cached --stat` 均无输出，`git diff --check` 通过。
- 测试环境：`D:\miniconda3\envs\dps-studio\python.exe`，Python 3.12.13。
- 基线直接运行带独立 `--basetemp` 的全量 pytest：354 passed、1 failed；唯一失败为既有 `tests/unit/test_package.py::test_cli`，原因是 CLI 的 `argparse` 读取了 pytest 自身参数。基线 Ruff 与 mypy 均通过。

## 2. 原来自动分析不能直接点击的真实原因

TASK-015A 的 GUI 只有在用户手工加载 workflow TOML 后，`AnalysisSession.run_configuration` 才存在；自动分析同时依赖手工确认的分析范围和 `_wavelength_confirmed` checkbox。加载新数据还会清除波长确认。因此即使正式 Balanced 和 1550 nm 已在 core/config 中存在，启动后的普通用户流程仍不能直接运行。

## 3. 默认配置来源

新增 `configs/pdv_studio_defaults.toml` 作为桌面端正式默认科学配置。它通过现有 public `load_workflow_config` 加载，声明默认 preset 为 `balanced`、真空波长为 `1.55e-6 m`、正式 profile 列表、默认分析范围、quality、event candidate、display 和其他 workflow 公共参数。`input.path = "."` 仅为复用完整 `WorkflowConfiguration` schema；GUI 明确忽略该路径，只分析用户主动导入的记录。

## 4. preset repository 设计

新增 `PresetRepository` 和不可变 `AnalysisParameters`：

- repository 包装正式 `WorkflowConfiguration`，从 `configuration.analysis.profiles` 动态生成 GUI 下拉项；
- GUI 不按 Balanced/High 名称写 `if/elif`，预设值直接复制自 public `AnalysisProfile`；
- `AnalysisParameters` 统一承载 preset 与 Custom 实际传入 core 的 STFT/搜索参数，并派生 `hop = window - overlap`；
- 新增正式 profile 时，GUI 无需增加 profile 名称分支；仍需先在 core 的正式 profile registry 中注册，这是当前 core 配置契约的边界。

## 5. Balanced / High / Custom 的实现

启动后下拉框立即包含 `Balanced`、`High time resolution`、`自定义`，默认选择 `Balanced`。正式 preset 的窗函数、窗长、重叠、hop、nfft 和搜索上下限只读，且全部来自 `AnalysisProfile`。选择 Custom 时，以当前参数为起点开放窗长、重叠、nfft、搜索下限和上限编辑；`hann` 继续只读，因为当前正式 core 只允许该窗函数。

Custom 校验包括：正窗长、`0 <= overlap < window`、`nfft >= window`、非负频率下限、上限大于下限、数据加载后的 Nyquist 上限、通道最小样本数和正波长。Custom 通过 public `analyze_configuration` 运行，没有在 GUI 重写算法。

高级参数对话框按 STFT、脊线、信号检测、质量、显示分组，只展示当前 core 中真实存在的字段；检测与质量参数第一版保持只读，并显示配置来源。

## 6. 1550 nm 默认值来源与内部 SI 转换

默认值只存在于 `configs/pdv_studio_defaults.toml` 的 `vacuum_wavelength_m = 1.55e-6`，未在 `main_window.py` 重复硬编码。GUI 始终以 nm 显示，支持如 1550.12 的浮点编辑，写入 `AnalysisRunConfiguration` 时乘以 `1e-9` 转回 m。测试验证 1550 nm 对应 `1.55e-6 m`，1550.12 nm 对应 `1.55012e-6 m`。波长修改会递增 generation、清除旧结果，但不再需要 checkbox 或阻塞确认对话框。

## 7. workflow 手工导入如何从主流程移除

右侧主参数区不再包含“加载 workflow 配置…”按钮或长配置路径。高级导入移动到“设置 → 分析参数 → 导入配置…”，并新增“恢复默认参数”。当前配置源路径只在高级参数对话框中显示。普通流程启动即加载内置配置。

## 8. 默认分析范围逻辑

导入数据后先计算所有已选通道的完整时间交集：最大通道起点到最小通道终点。若当前配置的起止时间都存在、严格有序且完整落在该交集内，则采用配置范围；否则采用完整交集。范围通过现有 `AnalysisRangePanel.confirm_range_s` 和 `AnalysisSession.set_analysis_range` 建立，不切片、不重采样、不改写 `SignalRecord`，状态直接进入 `RANGE_DEFINED`。用户后续仍可调整范围。

## 9. 自动分析 QAction 的启用条件

菜单“分析 → 自动分析”和工具栏“自动分析”继续共享同一个 `action_automatic`。自动分析现在只要求：

1. 已导入记录；
2. 已确认合法范围；
3. 当前科学参数通过校验；
4. 后台没有另一个分析任务。

启动但无数据时 tooltip 为“请先导入实验数据。”；数据、默认范围和默认参数有效后，菜单 QAction、工具栏 QAction、STFT action 与右侧运行按钮同步可用。

## 10. 参数修改后的结果失效

切换正式 preset、进入/编辑 Custom、修改波长、导入/恢复配置和修改分析范围都会更新 session generation，并清除 spectrogram、ridge、velocity、comparison 和 quality 的旧显示。后台迟到结果仍通过 generation id 被拒绝；当前 core 没有协作取消 API，因此参数变化不会强行中断正在执行的 NumPy/SciPy 计算。

## 11. 是否修改 core config/profile

仅最小修改 `src/dps_studio/core/workflow/config.py`：为 `AnalysisConfiguration` 增加 `default_profile`，加载时允许 TOML 显式指定；旧配置未指定时回退到 profiles 第一项，保持兼容。未修改 `analysis_profiles.py`，未修改任何 STFT、ridge、signal detection 或 velocity 数值算法，也未改变两个正式 profile 的数值。

## 12. 如何证明原有数值结果未改变

新增参数化回归测试，分别对 `BALANCED_PROFILE` 和 `HIGH_TIME_RESOLUTION_PROFILE`：一条路径调用原 `analyze_profile`，另一条路径把同一 profile 的显式参数传给 public `analyze_configuration`。测试逐元素比较 STFT 时间轴、频率轴、复数 spectrum、精修频率、正式 apparent velocity 和 display velocity，均完全相等。现有真实 core GUI 分析、NaN/质量语义与双通道独立性测试也全部继续通过。

## 13. 新增和修改文件

新增：

- `configs/pdv_studio_defaults.toml`
- `src/dps_studio/gui/preset_repository.py`
- `src/dps_studio/gui/advanced_parameters_dialog.py`
- `tests/unit/gui/test_task015b_presets.py`
- `artifacts/task015b_ui/render_task015b_screenshots.py`
- `artifacts/task015b_ui/default_parameters_zh.png`
- `artifacts/task015b_ui/wavelength_visible_zh.png`
- `artifacts/task015b_ui/custom_parameters_zh.png`
- `artifacts/task015b_ui/result_ready_without_manual_config_zh.png`
- `docs/TASK-015B_REPORT.md`

修改：

- `src/dps_studio/core/workflow/config.py`
- `src/dps_studio/gui/analysis_adapter.py`
- `src/dps_studio/gui/analysis_session.py`
- `src/dps_studio/gui/main_window.py`
- `src/dps_studio/gui/translations/pdv_studio_en.ts`
- `src/dps_studio/gui/translations/pdv_studio_en.qm`
- `tests/unit/gui/test_gui_shell.py`
- `tests/unit/gui/test_task015a_analysis.py`
- `tests/unit/test_workflow_config.py`

## 14. pytest

- 最终全量验证使用独立 basetemp/cache，通过环境 `PYTEST_ADDOPTS` 传递 pytest 参数、避免参数泄漏到被测 CLI：`365 passed in 19.27s`。
- 另以常规显式参数命令复现既有问题：`364 passed, 1 failed in 24.66s`；唯一失败仍为 `tests/unit/test_package.py::test_cli`，`dps-studio` 的 argparse 将 `-q --basetemp ... -o cache_dir=...` 误认为自己的参数。本任务按要求未无关重构 CLI。
- 增量 TASK-015A/TASK-015B/config 回归：`51 passed`。

## 15. Ruff

`python -m ruff check .`：`All checks passed!`

## 16. mypy

`python -m mypy src`：`Success: no issues found in 58 source files`

## 17. diff check

`git diff --check` 通过，无空白错误。Git 仅提示当前 Windows 工作树的 LF/CRLF 自动转换警告，不属于 diff 错误。

## 18. 真实数据验收

真实数据 `data/raw/20260607.csv` 按普通用户流程验收：启动后未调用 `set_analysis_configuration` 或选择 TOML；启动即显示 Balanced、1550 nm 与正式 Balanced 参数；导入数据后自动采用配置内且位于数据内的范围 `553.960254260–555.960229260 μs`；通过工具栏上共享的自动分析 QAction 运行，成功达到 `RESULT_READY`。Spectrogram、Ridge、Velocity、Comparison 四页均实际切换并检查为可用，两通道保持 `pdv_channel_1`、`pdv_channel_2` 独立结果。

随后切换 High time resolution，确认旧结果失效；切回 Balanced 后选择 Custom，把 nfft 安全修改为 8192，确认 `AnalysisRunConfiguration.parameters.nfft == 8192`。

## 19. 截图

- `artifacts/task015b_ui/default_parameters_zh.png`
- `artifacts/task015b_ui/wavelength_visible_zh.png`
- `artifacts/task015b_ui/custom_parameters_zh.png`
- `artifacts/task015b_ui/result_ready_without_manual_config_zh.png`

截图由 Windows Qt 平台上的真实 `MainWindow` 生成，已人工复核中文、Balanced/Custom、1550 nm、参数值、默认范围和 `RESULT_READY` spectrogram 显示。

## 20. 当前限制

- 当前 formal profile registry 仍只有 Balanced 与 High time resolution；新增 formal profile 仍需在 core registry 注册，但 GUI 无需新增名称分支。
- signal detection、quality、event candidate 的高级参数第一版只读。
- core 尚无协作取消 API；GUI 仅拒绝迟到结果。
- 正式导出、ROI、示波器连接、降噪、LiF/折射率/入射角修正均未接入。
- 当前正式速度仍为 apparent velocity；display velocity 与未来 corrected velocity 继续分离，无可信拍频仍返回 NaN 与质量标志。
- 既有 CLI pytest 参数污染问题仍存在，见第 14 节。

## 21. git status

最终位于 `main...origin/main`，工作树只包含本任务列出的 core config、GUI、翻译、测试、默认配置、报告和 `artifacts/task015b_ui` 修改/新增项；无 `data/raw`、scripts、outputs、notebooks 或其他任务范围外改动。

## 22. staged 状态

`git diff --cached --stat` 无输出。未执行 `git add`、commit 或 push。

## 23. data/raw 完整性

`git status --short -- data/raw` 无输出。真实文件 `data/raw/20260607.csv` 在验收前后 SHA-256 均为：

`AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`

未修改、覆盖或删除 `data/raw` 中任何文件。
