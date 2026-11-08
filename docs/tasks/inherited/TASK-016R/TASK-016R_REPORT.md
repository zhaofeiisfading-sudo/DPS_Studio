# TASK-016R 验收报告

本报告记录 TASK-016R 的仓库审计、实现边界、科学回归、真实数据验收与 Git 状态。验收日期为
2026-08-04，工作目录为 `D:\Code\Python_Projects\DPS_Studio`。

## 1. TASK-016 第一版流程为何显得复杂

第一版把 STFT 参数、Automatic 分析、Guided 参数与走廊操作集中在同一个右侧面板，同时
又把 Guided 放在顶部作为与打开数据、一键自动分析同级的入口。STFT 仍主要隐含在完整
分析调用内，走廊还要求“绘制—完成—运行”三个状态，因而界面步骤与真实依赖关系没有
一一对应。

## 2. 文字和控件重叠的真实原因

根因是不同步骤的长说明和控件共用固定宽高的参数容器，并非字体本身过大。TASK-016R
按步骤拆成独立可滚动页面，长标签启用换行，输入控件使用合适的 `QSizePolicy`，超高时
自然出现垂直滚动条；没有靠缩小字体掩盖布局问题。原生 Windows 125% DPI 下的
1280×720 截图已验收。

## 3. 新的 STFT 到 Ridge 流程

正式流程为 `Data -> Range -> STFT_READY -> Automatic Ridge 或 Guided Ridge ->
RIDGE_READY -> Velocity -> RESULT_READY`。第 3 步“计算时频图”调用公开
`compute_profile_stfts`/`compute_configuration_stfts`，独立得到并缓存 `STFTResult`；
第 4 步用 `analyze_stft_results` 在缓存 STFT 上执行后续科学链。

## 4. 一键自动分析如何继续保留

顶部仍保留“一键自动分析”。它继续执行 `Data -> Range -> STFT -> Automatic Ridge ->
Velocity`，内部复用同一分阶段 core 实现。它是 convenience workflow，不要求用户先手动
点击第 3、4 步；Guided 已从顶部同级大按钮移回第 4 步。

## 5. 新增了哪些 profile

只新增一套有仓库证据支持的不可变正式预设 `High Frequency Resolution`：Hann，
window=1024 samples，overlap=896 samples，hop=128 samples，nfft=4096，search band=
0.05--2.0 GHz。原有 Balanced（768/640/128/4096）和 High Time Resolution
（512/384/128/4096）名称与数值均未改变。

## 6. 新增 profile 的真实依据

依据是仓库已有真实数据窗口长度对照
`outputs/task007_demo_runs/run_27962_16185/window_length_sensitivity_summary.csv`。同一
20260607 实验、固定 hop=128 的 512/768/1024 对照实际运行过；1024 点窗长为约
25.6 ns，有限窗频率尺度约 39.0625 MHz，相比 Balanced 的 52.0833 MHz 和 High Time
Resolution 的 78.1250 MHz 更细。nfft 均为 4096、频率网格均约 9.765625 MHz，因此新
名称来自更长有限时间窗，而不是仅增大 nfft。

## 7. 为什么不能承诺某 preset 一定适合某类数据

预设只给出时间--频率分辨率取舍的分析起点。信号持续时间、谱线间距、非平稳性、噪声和
采样条件都会改变有效性；更长窗也会牺牲局部时间响应。GUI tooltip 明确要求结合频谱和
质量状态复核，不使用“最佳”“万能”或“保证正确”等表述，Custom 仍可按单次运行覆盖。

## 8. Fit Search Region 的实现

Spectrogram 和 Ridge 页的“适合搜索区域”直接设置 PyQtGraph `ViewBox`：X 为当前
analysis range，Y 为当前实际 configuration 的 scientific search band。测试在操作前后
逐元素比较 STFT spectrum，确认它只改视图，不改 `SignalRecord`、analysis range、
search band 或科学数组。

## 9. Show Full Spectrum 的实现

“显示完整频谱”把 Y view 恢复为当前 `STFTResult.frequency_hz` 实际首尾值，X 保持
analysis range。它不重新计算 STFT，也不扩大正式 search band；“完整”仅指已计算
STFT 所含的频率轴。

## 10. 进入 Guided 时的自动 fit 规则

当前 STFT 有效时，第一次由 Ridge 切换到 Guided 自动执行一次 Fit Search Region。窗口
用 session 内的一次性标志记录该动作；此后的 repaint、hover、控制点增删/移动和半宽更新
均保留用户 zoom/pan。只有再次显式点击 Fit Search Region 才重新适合。

## 11. corridor half width 是否真实参与 core search

是。GUI 以 MHz 编辑后转换为 Hz，写入不可变
`RidgeCorridorConstraint.half_width_hz`。core 每帧构造
`[f_center-half_width, f_center+half_width]`，并与 global search band 取离散频点交集；
交集无候选频点时返回质量状态与 NaN，不回退 Automatic。

## 12. upper/lower corridor 如何绘制

controller 由同一组中心控制点分段线性插值得到 `f_center(t)`，绘制中心线、
`f_center(t)+half_width_hz` 和 `f_center(t)-half_width_hz` 两条细边界，并在边界间添加
低透明度填充。控制点保持可见，填充不遮蔽真实 STFT。

## 13. GUI corridor 与 core corridor 是否严格一致

严格一致。显示模型和正式请求都引用同一 `RidgeCorridorConstraint` 的 SI 控制点及
`half_width_hz`，没有第二套 GUI 半宽常量。单元测试验证 upper/lower 等于 center ±
half width，并验证修改半宽只令 Guided stale，STFT 与 Automatic 对象身份保持不变。

## 14. Undo 实现

按钮、`Ctrl+Z` 与 `Backspace` 共用撤回最后新增控制点的路径。连续 A/B/C/D 可依次删除
D、C；少于两个合法点时 constraint 失效且运行 Guided 禁用。`Esc` 只退出当前绘制模式，
不清除已有合法走廊；双击和 Enter 仍可作为可选结束操作。

## 15. Clear 的原问题与修复

原问题主要是清理路径与反馈不完整：缺少端到端证据证明可见 ROI、边界、填充、draft、
session constraint 和结果失效关系同时被清理。现在 Clear 统一删除中心线、上下边界、
填充、全部 handles/draft，并令当前通道 session constraint 为 `None`、Guided stale；真实
GUI 验收同时证明缓存 STFT 和 Automatic 仍为原对象。

## 16. 是否取消 Complete Corridor 步骤

已取消强制步骤。两个以上合法控制点加合法半宽即实时形成可运行 constraint；点击“运行
引导分析”会自动结束当前绘制事务并验证。双击或 Enter 只作为可选的提前结束方式。

## 17. Guided domain 的新语义

控制点按时间排序，`t_left=min(control_times)`、`t_right=max(control_times)`，Guided 的
正式闭时间域严格为 `[t_left, t_right]`。域外 formal frequency 与 apparent velocity 均为
NaN，不自动回退或拼接 Automatic；Automatic 作为另一套完整结果独立保存。Comparison
可并列显示两种来源。

## 18. STFT 如何避免重复计算

session 独立保存 `stft_results` 与 `stft_valid`。adapter 支持 STFT-only 请求和携带缓存
`stft_results` 的后处理请求；添加/移动/撤回控制点、改半宽、清除走廊、切换提取模式、
改 colormap 和两个快速视图操作均不触发 STFT。对象身份测试与真实 GUI 验收都为 true。

## 19. Automatic scientific regression

未改写 STFT 数值公式、Automatic candidate/refined/formal ridge、signal detection
threshold、quality threshold 或 velocity conversion。单元测试验证旧 Automatic 一键路径
与分步路径逐元素一致；真实 20260607.csv 与 20260630-2.csv 的
`staged_equals_one_click` 均为 true。Automatic 底层候选脊线仍覆盖完整 STFT 轴，正式
analysis time gate 仍只作用于正式结果。

## 20. preset regression

Balanced 和 High Time Resolution 的 immutable baseline 数值未变，原双预设 demo 配置
仍按双预设加载，正式默认配置注册三套预设，Custom override、恢复预设值与 hop 派生规则
继续通过旧测试。三个预设在四个真实文件上全部合法运行并返回预期 STFT 元数据。

## 21. pytest

最终命令为 `python -m pytest`，通过 437 项：`437 passed in 23.35s`。使用新的独立
basetemp。仍有 1 条既有 Windows `PytestCacheWarning`：仓库配置的
`.test_tmp/pytest_cache` 拒绝创建 nodeids；它不影响测试收集、独立 basetemp 或退出码。

## 22. Ruff

`ruff check .` 退出码 0，结果为 `All checks passed!`。Ruff 扫描仓库时对既有不可访问的
TASK-015D 临时目录报告若干 `os error 5` 警告，但没有 lint 违规。

## 23. mypy

`mypy src` 退出码 0：`Success: no issues found in 62 source files`。

## 24. git diff --check

`git diff --check` 退出码 0，没有空白错误。Git 仅提示部分工作区文件未来被 Git 处理时
可能由 LF 转为 CRLF，不是 diff-check 失败。

## 25. 真实数据验收

对 `data/raw` 的 20260607、20260630-1、20260630-2、20260701 四个 CSV，依次运行三套
正式预设，共 12 次双通道分析。所有运行均为 2049 个频率 bin、约 9.765625 MHz 网格；
各文件的 Balanced/High Time/High Frequency 帧数分别为：20260607 620/622/618，
20260630-1 1557/1559/1555，20260630-2 620/622/618，20260701 620/622/618。完整参数、
shape、帧数和正式有限帧数记录在 `artifacts/task016r/acceptance_summary.json`。

## 26. 截图

`artifacts/task016r` 中恰有 9 张要求的中文截图：
`stft_panel_clean_zh.png`、`ridge_guided_clean_panel_zh.png`、
`spectrogram_full_range_zh.png`、`spectrogram_fit_search_region_zh.png`、
`corridor_boundaries_zh.png`、`corridor_undo_zh.png`、
`guided_local_domain_zh.png`、`automatic_vs_guided_zh.png`、
`layout_1280x720_zh.png`。它们以 Windows 原生字体环境生成；前八张逻辑尺寸为
1440×880，布局证据逻辑尺寸为 1280×720（125%/高 DPI 抓图像素按系统缩放放大）。

## 27. 启动耗时测量

真实验收进程在模块已导入后，从创建 QApplication/MainWindow 到 shown 并处理首轮事件为
0.496814 s。另以环境 Python 新进程外部计时，进程启动、imports、构造、shown、关闭的
保守上界为 2.479905 s。`-X importtime` 线索显示 `dps_studio.gui.main_window` 累计约
2.047 s、其中 pyqtgraph 累计约 0.293 s；主要初始化还包含 PySide6、NumPy/SciPy 与视图
模块。本任务没有据此进行无关启动架构重构。

## 28. 当前限制

当前仍是一通道一个活动折线 corridor；不包含 inclusion/exclusion polygon、AI、动态规划、
LiF 修正、正式 Guided Export、示波器连接或可取消 worker。导出按钮继续禁用。审计要求的
`docs/TASK-015D_REPORT.md` 在当前仓库不存在，已读取 TASK-015E、TASK-016 与 `docs/ui`，
未猜测缺失报告内容。

## 29. git status

当前分支为 `main`，跟踪 `origin/main`，工作树为 dirty。状态包含用户开始 TASK-016R 前已
存在的 TASK-016 未提交修改，以及本任务允许范围内的 core/GUI/config/tests/docs/artifacts
修改；未暂存、未提交、未推送，也未执行破坏性 Git 操作。

## 30. staged 状态

`git diff --cached` 为空。整个任务未执行 `git add`，Git index 保持无 staged changes。

## 31. data/raw 完整性

`git diff -- data/raw` 为空。验收前后 SHA-256 完全一致：20260607 为
`AB9F656E...68F7353`，20260630-1 为 `203B182E...C3A0A74`，20260630-2 为
`C0C31B29...17FA261`，20260701 为 `5CCB6530...9A952A`；完整散列记录在验收 JSON。
没有覆盖、改写或删除任何源数据。
