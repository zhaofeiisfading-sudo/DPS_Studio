# TASK-017R：结果导出易用性修订报告

## 范围与审计结论

本次仅修订 TASK-017 已有的正式结果导出入口、文件组织和反馈；未修改自动分析、
事件检测、脊线跟踪或任何 LiF/window correction 逻辑，也没有开始 TASK-018。

修改前，顶部工具栏和“文件”菜单共用 `actionExport`，其文字为“导出结果”，并且
直接连接 `MainWindow._export_current_result`。因此，当当前已有可用结果并已选择输出
目录时，点击该入口会立即调用 public core writer。它使用 Review & Export 页面当时的
选择；在首次 Automatic 分析后的默认状态，通常是 Automatic / `pdv_channel_1`。若目录
尚未选择，它会直接弹出目录选择框。该行为绕过了第 6 步的显式复核，容易让用户以为只是
“进入导出页面”，实际上已经发生文件写入。

## 顶部与菜单入口修订

- 顶部文字和“文件”菜单中的同一 action 现在均为“复核与导出”
  (`Review & Export`)；
- action 现在只调用 `_show_review_and_export`：刷新当前有效的
  Automatic/Guided 和 channel selector、激活左侧第 6 步并显示参数页；
- 该路径不调用 core writer、不创建目录或文件、不改变 `AnalysisSession`，也不消费
  `RESULT_READY`；
- 真正写入文件的唯一 GUI 操作是第 6 步页面的“导出结果”按钮；
- 顶部“自动分析”保持原有一键分析行为，未改动。

## 三件套导出与数据语义

每次第 6 步的正式导出固定生成三份互相关联的文件：

1. 主 CSV：`time_s,velocity_m_s`，严格只有两列；
2. 诊断 CSV：保留 `time_s`、coarse/refined frequency、apparent/display velocity、
   ridge/quality/state/origin、pre-event 标志、channel、analysis mode 等 TASK-017
   诊断字段；
3. metadata JSON：每次均生成。

主 CSV 的 `velocity_m_s` 直接复制既有 `ChannelAnalysis.display_velocity_m_s`，没有
重新应用 `v = λf / 2` 或任何其他物理公式。可信测量值保持既有显示速度；事件前
display-only 行保持当前配置速度；事件后的不可信值仍为 `nan`。关闭“包含事件前
display-only 平台”只在导出时过滤这些行，不修改内存结果、正式表观速度或质量标志。

metadata 保留 export schema/DPS Studio version/export time/source/channel/mode/profile、
分析范围、STFT/ridge/quality 配置、真空波长、事件参考、pre-event display 配置、结果
计数及状态语义。schema 版本升为 `pdv-studio-formal-result-v2`，新增 `detail_data_file`
和主 CSV 显示速度来源的明确记录；没有加入 LiF/window correction 公式。

## 文件名、目录与冲突

成功后文件直接放入用户明确选择的目录，内部仅使用临时 hidden staging 目录并在完成后
清除。不会再额外创建 `pdv_studio_export_...` 子目录。

文件名使用真实 source path 的 stem、输出 channel token 和简短 mode token：

```text
20260607_ch1_auto.csv
20260607_ch1_auto_detail.csv
20260607_ch1_auto.metadata.json
```

`pdv_channel_1`/`pdv_channel_2` 仅在文件名中映射为 `ch1`/`ch2`；内部 key 不变。
`automatic` 仅在文件名中缩写为 `auto`，`guided` 保持 `guided`。source path 缺失时使用
明确、可测试的 `unsourced` fallback，而不会伪造原始文件名；metadata 的 `source_file`
此时为 `null`。

如果三件套中任意目标文件已存在，整个新文件组获得统一后缀，例如
`20260607_ch1_auto_2.csv`、`20260607_ch1_auto_2_detail.csv` 和
`20260607_ch1_auto_2.metadata.json`。发布采用拒绝覆盖的 hard-link 方式；发生写入或
发布错误时会移除本次自己的 staging/已发布文件，不覆盖既有结果，也不保留半套文件。
`data/raw` 仍被 core writer 明确拒绝作为输出位置。

## GUI 反馈与重复导出

成功路径现在会：

- 在状态栏显示完成目录；
- 在 Log 面板记录目录及三个文件名；
- 显示“导出完成”对话框，列出三文件名和输出位置。

导出不改变 `RESULT_READY`、结果集或当前选择。按钮保持可用，用户可切换
Automatic/Guided、Channel 1/2、目录后继续导出，也可重复导出同一组合并获得一致的
collision suffix。

已有 Automatic/Guided selector 和 channel selector 均保留，且仍只显示当前有效的独立结果：
Automatic 与 Guided 不混合，Guided 只显示有当前有效结果的通道。

## 测试与真实 GUI smoke

新增/更新的定向测试覆盖：

- 顶部/菜单“复核与导出”仅导航至第 6 步、不调用 writer、不产生文件、不改变结果状态；
- 主 CSV 两列表头、display velocity 来源、pre-event 行、后续 `NaN`、关闭 pre-event
  时仅过滤输出行、输入 `ChannelAnalysis` 不变；
- 诊断 CSV schema、metadata parse/source/channel/mode/configuration；
- `20260607` source stem、`ch1`/`ch2`、`auto`/`guided` 命名，以及无 source fallback；
- 三件套一致 collision suffix；
- 成功日志/对话框、按钮仍可用和第二次 GUI 导出。

在原生 Windows Qt GUI 上实际读取 `data/raw/20260607.csv` 后完成双通道 Automatic
analysis，并验证：

1. 点击顶部“复核与导出”只进入第 6 步且输出目录仍为空；
2. 第 6 步导出 Automatic Channel 1，生成三件套；
3. 切换至 Channel 2 后导出，生成三件套；
4. 再次导出 Channel 2，生成统一 `_2` 后缀的三件套；
5. Channel 1 主 CSV 与 detail CSV 均为 620 行；主 CSV 只有两列，detail CSV 包含诊断字段；
6. JSON 可解析且保留 STFT/ridge/quality/source/mode/channel 信息；
7. Log 中存在输出目录，Export button 在导出后仍可用。

真实 smoke artifact 位于：
`artifacts/task017r/gui_smoke_final_20260806/`。

## 质量门

环境：`D:\miniconda3\envs\dps-studio\python.exe`（Python 3.12.13）。

- 定向导出与 GUI 测试：`11 passed`；
- `python -m pytest --basetemp=.pytest_tmp/task017r_full_20260806 -q`：
  `455 passed, 1 failed`；唯一失败为既有 `tests/unit/test_package.py::test_cli`，它让
  CLI `main()` 继承 pytest 的 `--basetemp` 和 `-q`，导致 argparse 报未识别参数；
- `python -m pytest --basetemp=.pytest_tmp/task017r_without_only_cli_20260806 -q
  -k "not test_cli"`：`454 passed, 2 deselected`；其中第二项也匹配历史测试名，故以
  前一条完整测试的 `455 passed, 1 failed` 为准确全量结果；
- `python -m ruff check src/dps_studio/core/export src/dps_studio/gui/main_window.py
  tests/unit/test_formal_result_export.py tests/unit/gui/test_task017_result_export.py`：通过；
- `python -m ruff check .`：通过（历史受保护临时目录产生访问拒绝 warning，但 exit 0）；
- `python -m mypy src/dps_studio`：`Success: no issues found in 65 source files`。
- `git diff --check`：通过；
- `python -m dps_studio.gui`：成功启动并保持 5 秒后由 smoke harness 关闭。

`pytest` 的 cache provider 仍会对既有受保护 `.test_tmp` 目录发出权限 warning；专用
`--basetemp` 的测试目录本身正常工作。

## data/raw SHA-256（开始前）

| 文件 | SHA-256 |
| --- | --- |
| `.gitkeep` | `F1945CD6C19E56B3C1C78943EF5EC18116907A4CA1EFC40A57D48AB1DB7ADFC5` |
| `20260607.csv` | `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353` |
| `20260630-1.csv` | `203B182E477E1E08214551977A00313EAF6F17A71391D83875F6F879DC3A0A74` |
| `20260630-2.csv` | `C0C31B2990EAE228B21594276D030B83600A7DDB98C1953842E4CB80C17FA261` |
| `20260701.csv` | `5CCB6530E0CC715E4A7A81327C625FCE267A8B3473C0487479366EAD9D9A952A` |

结束后再次计算的全部哈希与上表逐项相同；导出 smoke 仅写入
`artifacts/task017r/`，未写入或移动任何 raw 数据。

## 最终 Git 状态

未暂存任何文件，`git diff --cached --stat` 为空。`git diff --stat` 仅显示已跟踪文件中的
core re-export、GUI、翻译及既有 TASK-016R3 GUI 改动；本任务新增的 exporter、测试、报告
和 smoke artifact 仍为 untracked，未执行 `git add`、commit 或 push。原有 TASK-016R3 的
`analysis_range.py`、`styles.py`、对应测试/report/artifact，以及历史临时目录均保持原状。

## 结论

### 必须修正

无剩余 TASK-017R 必须修正项。

### 建议优化

既有 CLI 测试应显式传递空 argv，或让 `main()` 接受 argv，以免完整 pytest 将自己的参数
交给 argparse；该问题与 TASK-017R 无关，未修改。

### 暂不处理

TASK-018 的自动分析算法优化、连续性分析、新 ridge tracking、降噪、通道融合、项目保存、
示波器连接和 LiF 正式修正均未处理。

### 未知或需要实验确认

本任务没有新的物理推断。当前质量门与 measured/invalid 状态仅反映已有 workflow；具体
实验阈值、物理分支和任何 LiF/window 修正仍需独立实验确认。
