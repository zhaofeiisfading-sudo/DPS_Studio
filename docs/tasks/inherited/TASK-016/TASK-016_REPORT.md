# TASK-016 Guided Analysis 核心版完成报告

## 1. 开始前 Git/测试状态

开始时位于 `main...origin/main`，最近五个提交为 `bb9f3da`、`c48c572`、
`a7de32b`、`1d0df14`、`f0bd81b`。tracked/cached diff 均为空；工作树已有 6 个
TASK-015D 遗留 untracked 临时目录，本任务未删除或改写。要求读取的 015A、015C、
015C-R、015E 报告存在，`docs/TASK-015D_REPORT.md` 实际不存在。

环境默认 `python` 指向没有 pytest 的 base Conda；正式验证使用
`dps-studio` 环境（Python 3.12.13、pytest 9.1.1）。开始前全量收集 408 项，直接把
`--basetemp` 放在 pytest argv 中会令既有 `test_cli` 把该参数当 CLI 参数：407 passed、
1 failed。核心定向基线 134 passed，GUI 定向基线 21 passed。

## 2. 当前 automatic ridge 的真实候选搜索位置

真实入口是 `core/ridge/peak.py::extract_peak_ridge`。原实现对 STFT
`frequency_hz` 闭搜索带内的 `abs(spectrum)` 逐帧 `argmax`；workflow 位于
`core/workflow/analysis.py`，随后调用 `refine_peak_ridge_subbin`、谱质量、
`detect_beat_signal`、正式 apparent velocity、display transformer 和连续性诊断。

可复用 public API 包括 `analyze_profile`、`analyze_configuration`、`STFTResult`、
`ChannelAnalysis`、上述 ridge/quality/velocity 函数和既有后台 adapter。真实缺口只有
“逐帧频率允许区域约束”；没有复用或复制 `scripts/**`。

## 3. Guided Analysis 的最终架构

采用“现有 Automatic workflow + optional per-channel ridge constraint”。GUI 只创建
物理约束，worker 仍调用 public workflow，core 仍计算 candidate、refined、quality、
formal frequency 和 apparent velocity。没有第二套科学 workflow。

## 4. RidgeCorridorConstraint 数据模型

新增 frozen、slots、GUI 无关的 `RidgeCorridorConstraint`：
`control_times_s`、`control_frequencies_hz`、`half_width_hz`。数组复制到只读 buffer；
至少两个点、等长一维、时间严格递增、全部 finite、频率非负、半宽严格为正。
model 不保存像素、PlotItem、QColor，也不导入 PySide6/PyQtGraph。

## 5. corridor 数学语义

控制点按严格递增时间形成分段线性 `f_center(t)`。首末控制点的闭区间内，允许频率为
`f_center(t)-Δf <= f_candidate(t) <= f_center(t)+Δf`；区间外保持 automatic search。
内部单位为 s、Hz、Hz。manual constraint 不等于 manual result。

## 6. corridor 与 global search band 如何组合

活动帧使用 `global closed search band ∩ corridor band` 对应的真实 STFT 离散频点。
constraint 外仍走原 vectorized global argmax 路径。core 独立验证控制时间处于 STFT/
analysis range、控制频率不超过 STFT 上限、整个 corridor 不完全落在 global band 外。

## 7. 无峰帧如何处理

离散交集为空时，candidate frequency/magnitude 为 NaN，质量标记为
`RidgeQualityFlag.NO_ALLOWED_BINS`，精修和谱质量状态为 `NO_CANDIDATE`；下游检测返回
非 MEASURED 状态，正式频率和速度保持 NaN。不退回全带、不选最近点、不使用中心线、
不插值。

## 8. core 修改

新增 guidance model/validator，并在 ridge public exports 暴露。`extract_peak_ridge`
新增 optional constraint；refinement、spectral quality、continuity 和 related-frequency
诊断增加明确 no-candidate 传播。physics velocity 公式未修改，LiF 未接入。

## 9. workflow 修改

`analyze_profile` 与 `analyze_configuration` 接收可选
`Mapping[str, RidgeCorridorConstraint]`。mapping key 必须是已有通道；每通道在自身真实
STFT 上验证并只把 constraint 传给 candidate extraction。未提供 constraint 的通道与
无 constraint 的整个运行保持 Automatic 数值路径。

## 10. GUI corridor 交互

Spectrogram 上使用 PyQtGraph `PolyLineROI`：点击创建、双击/按钮完成、拖动 handle、
点击 segment 加点、删除 handle、统一修改半宽、清除完整 corridor。中心细线与低透明
填充带不遮挡 STFT。编辑后立即将 μs/GHz 转回 s/Hz；resize 不改变 model 坐标。

初始半宽为真实 STFT 频率间隔的 5 倍；当前 40 GHz、nfft=4096 数据约
48.828 MHz。这是明确的 GUI development initial value，不是实验标定值或最佳值。

## 11. per-channel constraint

session 以 channel name 保存 constraint，每通道最多一个 active corridor。Channel 1
不复制到 Channel 2；未约束通道继续完整 Automatic 搜索。未实现通道融合或自动择优。

## 12. Automatic/Guided session 分离

`automatic_channel_analyses`（兼容属性 `channel_analyses`）与
`guided_channel_analyses` 分开保存，并具有独立 generation/valid/stale 状态。corridor
编辑只使 Guided stale；scientific 参数使两套结果失效；display-only 参数刷新两套
display 数组而不使科学结果 stale。Guided 接受结果不替换 Automatic mapping。

## 13. Ridge 显示

Ridge 页提供 Automatic Result/Guided Result 选择。Guided 显示同一真实 STFT、静态
corridor、离散候选、亚频点精修和 formal measured ridge；正式曲线使用
`connect="finite"`，NaN 保持断线。Automatic 显示保持原语义。

## 14. Velocity 显示

Velocity 页同样切换结果来源。Guided Velocity 直接读取
`signal_detection_result.apparent_velocity_m_s`，即 guided formal frequency 经既有
core 转换；不转换 corridor center。display velocity 与 formal apparent velocity 继续
分离，窗口修正仍未接入。

## 15. Comparison

Comparison 叠加每个通道的 Automatic 与 Guided formal apparent velocity，并提供独立
可见性开关。它只展示差异，不融合通道、不择优，也不声称 Guided 更正确。

## 16. 后台线程

扩展原 `AutomaticAnalysisAdapter` 为可携带 `AnalysisResultSource` 和 constraints 的
统一请求，仍使用同一个 `QThreadPool/QRunnable`。完整 Guided workflow 不在 Qt 主
线程运行；worker 不访问 QWidget，也没有复制 thread framework。

## 17. scientific regression

无 constraint 回归逐元素使用 `numpy.testing.assert_array_equal`（保留 NaN 位置）比较
STFT 时间/频率/spectrum、candidate、refined、formal frequency、formal/refined/
display velocity；枚举精确比较 quality flags、refinement status、spectral quality、
SignalState、velocity origin 和 event candidate。所有比较通过。另验证未约束通道精确
等同 Automatic，SignalRecord、voltage、STFT 和已保存 Automatic result 不变。

## 18. no-peak corridor 测试

合成测试把 corridor 放在纯噪声频率，活动帧 formal frequency/velocity 全部 NaN 且
无 `MEASURED`。真实 `20260607.csv` 验收又把 Channel 1 corridor 放在 1.30 GHz、半宽
12 MHz：344 个活动帧的正式频率 finite count=0、正式速度 finite count=0；状态由原
算法真实返回，主要为 `NO_DETECTABLE_BEAT`/`AMBIGUOUS_PEAK`。

## 19. 新增和修改文件

新增：`core/ridge/guidance.py`、`gui/ridge_corridor.py`、
`tests/unit/test_guided_analysis.py`、
`tests/unit/gui/test_task016_guided_analysis.py`、
`tests/manual_task016_real_gui_acceptance.py`、本报告及 TASK-016 artifacts。

修改：core/ridge 的 public exports、models/refinement/spectral quality/diagnostics，
`core/workflow/analysis.py`，core 顶层 export；GUI adapter/session/main window/result
views/Qt translations；三份 `docs/ui/TASK-014_*` 文档。没有修改 config、scripts、
outputs、notebooks、presentation(s) 或 `data/raw`。

## 20. pytest

最终使用此前验证的 Windows workaround：把 basetemp 放入 `PYTEST_ADDOPTS`，避免
污染 `test_cli` 的 `sys.argv`，并用 forward-slash 绝对路径：

```text
PYTEST_ADDOPTS=--basetemp=C:/Users/89484/AppData/Local/Temp/DPS_Studio_TASK016_final3
python -m pytest
430 passed
```

直接 argv 方式仍触发既有 CLI 测试问题。一次用反斜杠写入环境变量时，Conda 参数层
把路径折叠成 `C:\Users89484...`，产生 103 个 temp fixture 权限错误；改为 forward
slash 的新独立目录后全量通过。GUI 单独为 56 passed；TASK-016 定向用例通过。

## 21. Ruff

`ruff check .`：All checks passed。

## 22. mypy

`mypy src --no-pretty --no-error-summary`：exit code 0，零错误。

## 23. diff check

`git diff --check` 通过；cached diff check 也通过。未发现 whitespace error。

## 24. 真实数据验收

使用只读 `data/raw/20260607.csv`，双通道各 80,000 samples，Balanced 结果每通道
620 STFT frames。目标 corridor 活动 422 帧，其中 113 帧 candidate 与 Automatic 不同，
298 帧仍通过正式检测得到 finite formal frequency。constraint 编辑后
`guided_results_stale=True` 且 `automatic results_valid=True`。验收经同一后台 adapter
运行，并用本机 Qt `windows` platform 生成界面证据。

## 25. 截图

本机 Windows Qt 原生截图均为 2880×1760：

- `artifacts/task016_guided/corridor_editing_zh.png`
- `artifacts/task016_guided/guided_ridge_zh.png`
- `artifacts/task016_guided/guided_velocity_zh.png`
- `artifacts/task016_guided/automatic_vs_guided_zh.png`
- `artifacts/task016_guided/no_peak_corridor_nan_zh.png`

`acceptance_summary.json` 保存来源、哈希和计数。`offscreen_review/` 保留第一次 Qt
offscreen 字体审查产物，不作为最终中文截图；最终五图已逐张目视检查。

## 26. 当前限制

每通道只允许一个 corridor，半宽恒定且对称；constraint 不持久化到项目文件；没有
正式 Guided export、包含/排除多边形、直接编辑最终 ridge、动态规划、自动融合双通道、
LiF、自动降噪、示波器连接或 cooperative cancellation。

## 27. 后续 TASK-016B 建议

单独设计可追溯 constraint persistence 与正式 export contract；如确有实验需求，再
评审 inclusion/exclusion polygon、多 corridor 或可变宽度。任何扩展仍应保持 constraint
与 formal result 分离，并继续使用同一 public quality/velocity 链。本任务未开始这些
实现。

## 28. git status

分支仍为 `main...origin/main`。工作树只包含 TASK-016 tracked modifications/new files，
以及任务开始前已存在的 6 个 TASK-015D untracked 临时目录。未删除、覆盖或整理这些
既有目录。

## 29. staged 状态

`git diff --cached` 与 `git diff --cached --check` 均为空/通过；没有执行 `git add`、
`commit` 或 `push`。

## 30. data/raw 完整性

`git diff -- data/raw` 和 `git diff --cached -- data/raw` 均为空。真实验收源
`data/raw/20260607.csv` 前后 SHA-256 均为
`AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`。
源记录的 time/voltage 数组亦逐元素不变。
