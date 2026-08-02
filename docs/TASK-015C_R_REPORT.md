# TASK-015C-R：跨实验事件参考语义修复与结果视图自动适配

本任务只修复事件参考生命周期、事件前显示层和结果视图范围，并对四组真实数据进行同参数只读诊断。未修改 STFT 数值计算、ridge peak selection、signal detection 阈值、连续性算法或原始数据，也未开始 TASK-015D/TASK-015E。

## 1. 为什么只有 20260607 有 display platform

TASK-015C 原实现仅用 `time < manual_event_reference_time_s` 和非 `MEASURED` 状态构造显示平台，没有同时限定 `analysis_start_time_s <= time < event_reference_time_s`，也没有在切换实验时重新验证绝对参考时刻。默认参考为 554.668 µs：它落在 20260607 的 553.960254–555.960229 µs 时间域内，因此能生成平台；它早于 20260630-1 和 20260701 的整个时间轴，因此两者没有平台。对时间轴为 539.713250–541.713225 µs 的 20260630-2，旧逻辑反而可能把所有非 `MEASURED` 帧误当成事件前显示区。这是跨实验绝对时间引用和显示 mask 的生命周期错误，不是 formal velocity 的科学计算结果。

修复后，平台只允许出现在已确认 analysis range 的起点至有效 event reference 之间；reference 未设置、非有限、超出完整数据域或超出当前 analysis range 时不生成平台。

## 2. 旧 reference 实际来自哪里

554.668 µs 来自当前默认配置和演示配置中的 `analysis.manual_event_reference_time_s = 5.54668e-4`，对应 `configs/pdv_studio_defaults.toml` 与 `configs/demo_dual_profile.toml`。主窗口启动时会先加载默认配置，旧会话在导入新文件后没有按新时间域重新验证该值，因而造成跨炮继承。

本次没有另建第二套事件模型。GUI/会话层使用正式语义名 `event_reference_time_s`，并映射到现有 public workflow 的 `manual_event_reference_time_s` 输入和结果元数据。

## 3. 新文件如何处理 reference

每次 `load_records` 都用新文件的共同完整时间范围和当前确认的 analysis range 重新验证配置 reference：有效时可作为该文件初值；无效时运行配置设为 `None`，并单独保留被拒绝值供 GUI 显示“无效/未设置”原因。不会把 554.668 µs 平移到 746 µs，也不会继续把它传入显示速度构造器。改变 analysis range 后，如果现有 reference 不再位于新范围内，也会清除它。

用户在“分析范围”页以 µs 编辑“事件参考时刻 / Event Reference Time”，内部仍存 s；确认时必须同时通过有限值、完整数据域和 analysis range 校验。清除、无效输入和重新导入文件都会产生明确状态，而不是保留一个不可见的旧值。

四文件验证结果如下：

| 文件 | 完整时间范围 / 当前 analysis range (µs) | 配置 reference 554.668 µs |
|---|---:|---|
| 20260607.csv | 553.960254–555.960229 | 有效，可作为初值 |
| 20260630-1.csv | 743.954015–748.954015 | 无效，设为 unset |
| 20260630-2.csv | 539.713250–541.713225 | 无效，设为 unset |
| 20260701.csv | 656.191266–658.191241 | 无效，设为 unset |

## 4. detected candidate 如何使用

分析完成后，GUI 按通道显示 `detected_event_candidate_time_s`，并提供“采用该候选”按钮。候选来自谱信号检测中第一段满足条件的连续 `MEASURED` 区域，仅是建议；只有用户显式点击才会成为 event reference。候选不会自动覆盖配置值或人工确认值，tooltip 为：“该时刻来自谱信号检测，只是候选参考，不代表已经确认的冲击到时。”

确认候选只刷新显示速度层，不重新计算 STFT、ridge 或 formal result。四文件候选详见第 8 节。

## 5. formal velocity 为什么不受影响

`apparent_velocity_m_s` 仍只由现有 `MEASURED`/质量状态和 public workflow 产生；事件参考变更通过 `configure_channel_event_reference` 仅重建 `pre_event_display_velocity_m_s` 与 `display_velocity_m_s`。组合时 `MEASURED` formal 值优先，只有 analysis start 至 reference 之间的非 `MEASURED` 帧可显示默认 0 m/s 平台；reference 之后的 `NO_DETECTABLE_BEAT`、`AMBIGUOUS_PEAK`、`BAND_BOUNDARY`、`UNSTABLE_REFINEMENT` 等仍为 NaN。

单元测试和 Windows GUI 验收都逐元素确认 reference 修改前后的 formal velocity 完全一致，并确认 STFT 对象未被重算。

## 6. X/Y view range 原来为什么出现大量空白

Spectrogram、Ridge、Velocity 和 Comparison 原先在每次渲染时对全部 plot/image 数据调用 `autoRange()`。这会把视图范围交给绘制对象的完整边界，而不是当前确认的 analysis range；Velocity 的刷新还会反复触发 auto range，覆盖用户手动 zoom。Y 轴也没有按当前通道实际绘制的有限速度值做一次性 fit。Raw Signal 初次布局时依赖 enable-auto-range，部分窗口时序下还可能短暂出现 0–1 的默认范围。

## 7. 修改后的 fit 规则

- Raw Signal 默认显式显示共同完整数据范围；Analysis Range 页面仍以完整数据范围为背景并叠加分析区。
- Spectrogram、Ridge、Velocity、Comparison 在新结果加载时将 X view 设为确认的 `analysis_start_time_s`–`analysis_end_time_s`。这里只改变 view，不裁剪 record、STFT 或结果数组。
- Velocity 和 Comparison 在新结果、通道切换及用户点击“适合分析范围 / Fit Analysis Range”时，用当前可见曲线的有限值计算 Y 范围，并留 7.5% padding；显示 display velocity 时，其有限值也参与 fit。
- Spectrogram/Ridge 的 Y 轴继续沿用现有 frequency display/search 设计。
- 普通 repaint、事件参考显示层刷新和 display 开关切换会保存并恢复用户当前 X/Y view，不抢回 auto range。
- 每个结果页提供轻量“适合分析范围”动作；Velocity/Comparison 同时恢复有限数据 Y 范围。

## 8. 另外三组数据结果差异主要来自什么 SignalState / ridge 行为

四个文件均使用完全相同的当前 Balanced scientific configuration：10 dB、3 dB、guard bins 12、minimum frames 3、minimum cycles 1、0.05–2 GHz search band；未针对任何文件调参。

| file | channel | analysis range (µs) | candidate (µs) | MEASURED | NaN | NO_DETECTABLE | AMBIGUOUS | BAND_BOUNDARY | UNSTABLE | finite velocity (m/s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20260607.csv | pdv_channel_1 | 553.960254–555.960229 | 554.081854 | 392 | 228 | 66 | 122 | 21 | 19 | 117.878–1411.933 |
| 20260607.csv | pdv_channel_2 | 553.960254–555.960229 | 554.667454 | 379 | 241 | 78 | 65 | 95 | 3 | 117.624–692.095 |
| 20260630-1.csv | pdv_channel_1 | 743.954015–748.954015 | 746.117215 | 820 | 737 | 21 | 94 | 569 | 53 | 65.312–436.247 |
| 20260630-1.csv | pdv_channel_2 | 743.954015–748.954015 | 746.194015 | 769 | 788 | 35 | 116 | 609 | 28 | 65.737–436.108 |
| 20260630-2.csv | pdv_channel_1 | 539.713250–541.713225 | 540.215650 | 448 | 162 | 10 | 46 | 111 | 5 | 318.335–750.049 |
| 20260630-2.csv | pdv_channel_2 | 539.713250–541.713225 | 540.215650 | 428 | 192 | 5 | 41 | 143 | 3 | 318.356–751.653 |
| 20260701.csv | pdv_channel_1 | 656.191266–658.191241 | 656.402466 | 341 | 279 | 57 | 112 | 87 | 23 | 101.010–580.383 |
| 20260701.csv | pdv_channel_2 | 656.191266–658.191241 | 656.844066 | 313 | 307 | 36 | 91 | 169 | 11 | 267.501–580.301 |

STFT 总览显示四组数据都有明显谱结构，差异不是“没有信号”。20260630-1 的主要断线来源是频繁命中 `BAND_BOUNDARY`（569/609 帧），并存在多支谱线与支路切换；20260630-2 两通道候选一致、谱对比度最高，`NO_DETECTABLE` 和 `AMBIGUOUS` 较少，但仍有搜索边界命中；20260701 通道 1 在主可见事件之前出现较早候选，且 ambiguity、unstable 和大步跳更多，通道 2 候选更接近主谱结构但有 169 帧 `BAND_BOUNDARY`；20260607 通道 1 同样出现早于通道 2 的候选及较大支路跳跃。当前 analysis range 均覆盖对应记录及主要谱事件。

逐帧 ridge 的大于 100 MHz 跳变计数（ch1/ch2）分别为 18/8、7/7、2/2、3/0；这支持“多支谱线下局部候选选择/边界状态造成不连续”的诊断。完整诊断数据位于 `artifacts/task015c_r/cross_file_diagnostic.md`、`.json` 与 `cross_file_spectrogram_overview.png`。

## 9. 是否发现真正算法 bug

发现了三个确定的软件语义/视图 bug：跨文件未重新验证绝对 event reference；pre-event display mask 未限定 analysis start；结果视图使用绘制对象的全局 auto-range 且 repaint 会夺回手动 zoom。它们均已修复。

没有发现 STFT、ridge 数值计算或 signal detection 阈值实现错误。真实文件中较乱的 formal 结果可由多谱支路、局部 peak 选择、频带边界和质量状态分布解释；因此本任务没有改科学算法或阈值。

## 10. 是否需要后续科学算法 TASK

需要，但应明确列为“后续 Ridge/Quality 算法改进问题”，与本修复任务分离。后续可基于跨炮标注和物理预期评估多支路连续跟踪、搜索边界策略与候选共识；在取得证据前不应为曲线外观修改 10/3 dB、guard bins、minimum frames/cycles、search band 或连续性算法。本任务未开始 TASK-015D/TASK-015E。

## 11. 修改文件

TASK-015C-R 直接涉及：

- Core：`src/dps_studio/core/workflow/display.py`、`analysis.py`、`config.py`、`__init__.py`。
- GUI：`analysis_adapter.py`、`analysis_range.py`、`analysis_session.py`、`main_window.py`、`raw_signal_view.py`、`result_views.py`、英文 `.ts/.qm` 翻译。
- Tests：`tests/unit/test_display_velocity.py`、`tests/unit/test_workflow_config.py`、`tests/unit/gui/test_task015c_r_event_reference_views.py`。
- Docs：三个 `docs/ui/TASK-014_*` 设计文档、本报告。
- Acceptance：`artifacts/task015c_r/` 下的只读诊断、验收脚本和截图。

工作树在开始本任务时已包含未提交的 TASK-015B/TASK-015C 修改；本次在其上增量实现并保留这些变更，没有覆盖或回退。生产代码未写死四个验收文件路径；仅验收脚本通过显式命令行参数接收文件。

## 12. pytest

- 开始前基线：380 passed。
- 完成后完整套件：385 passed in 21.50s。
- 任务相关增量套件：30 passed in 1.78s。

完整通过使用独立 `--basetemp`/cache 配置放入 `PYTEST_ADDOPTS`，避免参数进入被测 CLI 的 `sys.argv`。按字面在 `python -m pytest` 后直接附加 `--basetemp ... -o cache_dir=...` 时结果为 384 passed、1 failed；唯一失败是既有 `tests/unit/test_package.py::test_cli` 将 pytest 自身参数交给 `dps-studio` argparse，并非 TASK-015C-R 功能回归。没有为绕过该既有测试隔离问题修改生产 CLI。

新增测试覆盖任务书列出的 17 项：跨域 invalid/unset、554.668 µs 不泄漏、人工设置、严格平台区间、formal 不变、事件后 NaN、换文件重验证、候选不自动覆盖且必须显式采用、结果 X、Raw full range、Velocity Y、zoom 保持、显式 fit、通道切换、raw 哈希和 GUI 不导入 scripts。

## 13. Ruff

`ruff check .`：All checks passed。

## 14. mypy

`mypy src`：Success: no issues found in 59 source files。

## 15. git diff

`git diff --check` 通过，无 whitespace error。最终报告写入前的整体未暂存 tracked diff 为 19 files changed、2013 insertions、427 deletions；该统计包含任务开始前已有的 TASK-015B/TASK-015C 修改，不应全部归因于 TASK-015C-R。二进制 `.qm` 显示为大小变化，翻译源 `.ts` 为 272 个 finished、0 unfinished。

## 16. git status

分支仍为 `main...origin/main`。工作树保持未提交状态，包含此前 TASK-015B/TASK-015C 与本次 TASK-015C-R 的 tracked/untracked 文件；没有回退、覆盖或清理用户的既有变更。`data/raw` 在 status 中为空。

## 17. staged 状态

`git diff --cached --stat` 为空；没有执行 `git add`、commit 或 push。

## 18. data/raw 完整性

四个只读验收文件的 SHA-256 为：

| 文件 | SHA-256 |
|---|---|
| data/raw/20260607.csv | `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353` |
| data/raw/20260630-1.csv | `203B182E477E1E08214551977A00313EAF6F17A71391D83875F6F879DC3A0A74` |
| data/raw/20260630-2.csv | `C0C31B2990EAE228B21594276D030B83600A7DDB98C1953842E4CB80C17FA261` |
| data/raw/20260701.csv | `5CCB6530E0CC715E4A7A81327C625FCE267A8B3473C0487479366EAD9D9A952A` |

Windows GUI 验收后哈希保持一致，`git status --short -- data/raw` 无输出。未修改、覆盖或删除任何 `data/raw` 文件。

验收截图：

- `artifacts/task015c_r/event_reference_invalid_new_file.png`
- `artifacts/task015c_r/event_reference_manual_new_file.png`
- `artifacts/task015c_r/velocity_fit_analysis_range.png`
- `artifacts/task015c_r/cross_file_diagnostic.png`

