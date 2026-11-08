# PDV Studio GUI Usability Consolidation Report

日期：2026-08-18
分支：`codex/feature/task-018-auto-analysis`
起始 HEAD：`5087065`

## 结论

本任务完成了数据导入窗口、Analysis Range、Search Band、参数组织、LiF correction 配置、Review & Export 摘要和中英文资源的收敛。STFT 数组定义、Ridge/continuity、quality、表观速度关系和 LiF 公式均未更改。`data/raw` 始终只读；未执行 `git add`、commit 或 push。

## 开始前真实审计

1. 修改前 Git 状态：工作树与暂存区均为空；`git diff`、`git diff --cached`、`git diff --check` 无内容。基线 Ruff 与 mypy strict 通过。基线 pytest 的独立临时目录运行得到 545 passed、1 个由 `--basetemp` 被 CLI 测试继承导致的参数失败；普通 Windows pytest 临时根另会触发既有 `WinError 5`，与产品测试失败无关。
2. 顶部原“自动分析”实际不是事件检测快捷键。它调用 `MainWindow.run_automatic_analysis()`，创建默认 `AUTOMATIC` `AnalysisRequest`，由 `_AnalysisWorker` 调用 public core `analyze_configuration()`，完成 Range → STFT → Automatic Ridge → Velocity，并由 session 接受为 `RESULT_READY`。
3. `554.668 µs` 原来由通用 `configs/pdv_studio_defaults.toml` 的 `analysis.manual_event_reference_time_s = 5.54668e-4` 进入正常 GUI。该通用默认已移除；专属 demo/benchmark 配置未删除。
4. GUI 所称 `primary` 的真实模型来源是每通道 `stream_event_candidates.primary_candidate_time_s`，即通过事件段规则选出的推荐候选。`signal_detection_result.detected_event_candidate_time_s` 是兼容/较弱诊断候选。两者都不是自动确认的物理真值。
5. Search Band 存储在不可变 `AnalysisRunParameters.minimum_frequency_hz/maximum_frequency_hz`，session 自定义时进入 `AnalysisParameterOverrides`；权威单位为 Hz。
6. Search Band 只传给 `analyze_stft_results()` 的 Ridge/candidate 阶段。`compute_configuration_stfts()` 不按 Search Band 截断，缓存完整 `rfft` 单边频谱（0 到有效 Nyquist）。
7. 修改 Search Band 时，`AnalysisSession.set_analysis_overrides()` 保留 STFT，清除 Automatic、依赖全局频带的 Guided、Velocity 与候选/质量结果。
8. 原频谱图用不可移动的 `InfiniteLine` 标出频带；Analysis Range 使用 `LinearRegionItem`/`InfiniteLine`、hover pen、cursor 与 Qt/pyqtgraph 原生命中形状。新 Search Band 沿用该架构。
9. 正式 LiF correction 为 Rigg et al. (2014) Eq. (16)：以 km/s 数值单位计算 `b1 * v_app**b2`，其中 `b1=0.7895`、`b2=0.9918`，参考波长 `1550 nm`，材料方向 `[100]`；角度修正在此之前单独执行。
10. 开始时 `.ts/.qm` 与最近界面大体同步，但 Ridge 模式名称通过变量调用 `tr()`，静态 `lupdate` 无法提取，英文界面仍残留中文；本任务已修复。

## 实现与验收（最终报告 27 项）

1. **最终 Git 范围**：修改集中在 profiles、LiF 配置/metadata、GUI 视图/翻译和对应测试；没有暂存或提交。最终状态详见质量门部分。
2. **Import Dialog**：原问题是所有控件与 `QDialogButtonBox` 位于同一纵向布局，720 px 固定高度在较小工作区/DPI 下把按钮推到屏幕边缘。现在顶部源文件固定，中部文件结构/预览/通道/提示进入 `QScrollArea`，按钮盒固定在 scroll 外；初始尺寸由 `QScreen.availableGeometry()` 的 82% 决定并限于 680×720。1920×1080、1440×900、1366×768 三组工作区尺寸有参数化测试；未用缩小字体规避问题。未能在本轮自动化中切换物理显示器的 125%/150% DPI。
3. **554.668 µs**：已从通用默认 TOML 移除。新 session/普通新文件为 unset；只有用户输入、显式采用候选或专属配置能建立正式 Event Reference。
4. **候选呈现**：底层 `primary`/compatibility 模型保留，普通 Range 页改为“推荐候选 / 采用候选”。较弱 compatibility 值仅在 tooltip/诊断中出现，不提供采用按钮。
5. **One-click 调用链**：工具栏“一键分析”/`Run Analysis` → `run_automatic_analysis()` → `AnalysisRequest(AUTOMATIC)` → background `_AnalysisWorker` → public core `analyze_configuration()` → session `accept_results()` → `RESULT_READY` → Velocity tab（index 3）。真实 raw GUI 验收通过。
6. **Range actions**：删除“使用当前显示范围”主界面入口；内部 helper 保留兼容。“使用完整范围”降级为终点旁“重置”，只重置 draft；唯一主操作为“确认分析范围”。新增“检测候选”，它复用现有自动链读取既有候选，但临时正式结果不会写入 session；检测后仍为 `RANGE_DEFINED`、无 STFT cache、无正式结果，也不自动确认 Event Reference。
7. **默认 Search Band**：所有正式内置 profiles 统一为 `0.05–6.0 GHz`。下限保留 0.05 GHz 以排除默认 DC/低频漂移，但用户仍可显式输入 0。6 GHz 只是更宽的候选约束，不宣称更准确。
8. **真实 Nyquist**：`data/raw/20260630-2.csv` 与 `data/raw/20260701.csv` 均为 80,000 行、双通道；采样率 `39,999,999,986.359764 Hz`，Nyquist `19,999,999,993.179882 Hz`，因此 6 GHz 合法。
9. **Search SpinBox**：`singleStep=1.0 GHz`；使用最多 12 位 GHz 小数的内部 editor 精度和去尾零显示，常见值显示为 `0.05`、`6.00`，仍可键入 2.35 等小数。为了覆盖极低采样率测试，GUI Nyquist 限值向下量化到不超过真实上限的 1 mHz，绝不越界。
10. **图形交互**：Spectrogram 与 Ridge 使用两条 movable horizontal `pyqtgraph.InfiniteLine`。视觉 pen 为 1 px dashed，hover pen 为 3 px 高亮，cursor 为 `SizeVerCursor`，具有上下限 tooltip；原生 marker 扩大 `InfiniteLine` 的 bounding/hit shape，无像素坐标状态或散落 mouse hack。拖动完成后吸附到当前 STFT frequency grid，再以 Hz 发出。
11. **Search/View 分离**：拖线或 SpinBox 更新 session 科学参数；zoom/pan、Fit Search Region、Show Full Spectrum 只调用 plot view range API，不写 session。测试验证连续改变 Y view 不会改变 Search Band。
12. **stale dependency**：Search Band change → STFT valid → Automatic stale → Guided stale → corrected/display velocity stale。候选与质量随 Ridge 下游一起失效。
13. **STFT 重算**：Search Band 拖动验收中，修改前后的 `STFTResult` 为同一对象；没有后台 STFT 请求。真实 raw GUI 验收同样确认复用。
14. **Ridge-only 参数**：`automatic_ridge_extraction_combo` 与 Search Band 上下限从 STFT/common 区移到第 4 步 Automatic Ridge 区。该 selector 变化只使 Ridge/Velocity stale。
15. **LiF 正式模型参数**：只暴露 core 已使用的 `b1`（无量纲系数）、`b2`（无量纲指数）与 `reference_wavelength_m`（GUI 为 nm）。公式、orientation、来源与 DOI 未重写。
16. **LiF 可修改项**：Velocity 页折叠的“LiF 材料参数…”可编辑上述三个真实参数，并提供“恢复 LiF 默认值”。偏离正式默认时显示 `Custom LiF`。
17. **验证/provenance/JSON**：`LiFWindowCorrectionModel.__post_init__` 要求三个数值有限且严格为正，文本 provenance 非空；TOML loader 支持 `lif_b1/lif_b2/lif_reference_wavelength_m`。值进入 `VelocityCorrectionConfig.lif_model` 和 session run configuration；export metadata 写出实际参数、来源、DOI、`parameter_provenance=formal_default|user_custom` 与 `custom_parameters`。
18. **Velocity / Review & Export**：真空波长、材料、角度与折叠 LiF 参数只在第 5 步编辑。第 6 步仅显示 `LiF/Custom LiF · angle` 摘要，并保留结果来源、通道、时间零点、事件前显示段、输出目录与导出。兼容属性指向同一控件，不存在第二套 correction state。隐藏了没有 core cancellation API 的禁用大按钮。
19. **Translation**：最终 `pyside6-lupdate` 发现 475 条，`unfinished=0`；`pyside6-lrelease` 生成 475 finished、0 unfinished 的 `pdv_studio_en.qm`。动态 Ridge/Boxcar 标签改为可静态提取的 literal mapping。
20. **中文 GUI smoke**：Windows Qt offscreen 下以真实 `20260630-2.csv` 验证 Import 按钮固定可见、Event Reference 初始 unset、2 个推荐候选、检测后 session 仍无 STFT/正式结果、显式采用、确认 Range、分别拖动 Search Min/Max、两个 SpinBox 回写、STFT 复用、staged Ridge/Velocity 与一键 Velocity，全部通过。拖线频带由网格吸附为 `390,624,999.867–4,882,812,498.335 Hz`；两通道有限 Ridge 分别落在 `400,390,624.863–4,775,390,623.372 Hz` 与 `400,390,624.863–4,853,515,623.345 Hz`，未越过搜索约束。
21. **English GUI smoke**：Windows Qt offscreen、1366×768 窗口检查 toolbar、Import Dialog、Range、candidate、sample suffix、Ridge selector、Velocity、LiF 与 Review & Export；按钮可见、窗口受屏幕约束、检查文本无 CJK 残留且无空白。未进行人工物理屏幕逐像素审查。
22. **pytest**：最终全量 `557 passed in 36.99s`。使用独立 `.test_tmp/gui_final_candidate_20260818` basetemp，避免既有 Windows 临时根权限问题；无真实测试失败。
23. **Ruff**：全仓 `ruff check .` 通过。
24. **mypy strict**：`mypy src` 通过（77 source files）。
25. **git diff --check**：通过；仅 Git 提示工作区 LF 将来可能转 CRLF，无 whitespace error。
26. **git status**：所有变更均未暂存。存在本任务源代码/测试/报告修改，以及基线 pytest 生成的未跟踪 `.task_gui_baseline_tmp_20260817_a/`；该目录不是产品或原始数据，因项目规则要求删除前确认而未自行删除。
27. **data/raw**：`git diff -- data/raw` 为空。任务前后 SHA-256 一致；关键验收文件：`20260630-2.csv = C0C31B2990EAE228B21594276D030B83600A7DDB98C1953842E4CB80C17FA261`，`20260701.csv = 5CCB6530E0CC715E4A7A81327C625FCE267A8B3473C0487479366EAD9D9A952A`。

## 真实科学检查

Balanced profile 的 STFT 网格为 2049 个频点，范围 `0–19,999,999,993.179882 Hz`，间隔 `9,765,624.996669864 Hz`。

- `20260630-2.csv`：Ch1/Ch2 refined ridge finite frame 数为 468/454，formal apparent velocity finite frame 数为 448/428，corrected velocity finite frame 数为 448/428。
- `20260701.csv`：Ch1/Ch2 refined ridge finite frame 数为 446/362，formal apparent velocity finite frame 数为 340/313。

这些结果只证明 0.05–6 GHz 默认频带在当前真实采样域内合法并可产生有限结果，不代表扩大频带提高了准确度。

## 数据与 Git 纪律

- 未修改 `scripts/**`、`data/raw/**` 或历史 `outputs/**`。
- 未新增第三方依赖。
- 未 `git add`、commit、push。
- 未开始后续任务。
