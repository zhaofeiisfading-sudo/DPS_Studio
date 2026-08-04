# TASK-016R2 Guided Analysis 工程修订报告

验收日期：2026-08-04。工作目录：`D:\Code\Python_Projects\DPS_Studio`。本报告仅描述
TASK-016R2 范围内的增量实现和验证；未将推断表述为实验事实。

## 1. 任务范围

本次修订处理 Guided 的多通道独立性、当前显示通道的运行目标、Guided-only 结果页、
提取方式 radio 状态、仅显示的事件前速度连接，以及两组实验性极限预设。未扩展
polygon、AI、动态规划、LiF 修正、正式 Guided 导出或跨通道融合。

## 2. 审计前提

开始前检查了工作树、最近提交、cached diff、`git diff --check`、TASK-015E、TASK-016、
TASK-016R 和三份 `docs/ui/TASK-014_*` 文档。用户要求审阅的
`docs/TASK-015D_REPORT.md` 在本仓库不存在；这一缺失没有被猜测或补造。

## 3. 发现的多通道问题

原先 `AnalysisSession` 只有全局 Guided valid/stale 布尔值，且接收新 Guided 结果会替换
整个 mapping。因此在 Channel 2 运行后，Channel 1 的 Guided 结果会消失；编辑任一
corridor 也会让所有 Guided 结果一起失效。

## 4. 通道局部状态模型

session 现在保存 `guided_result_valid_channels`、`guided_result_stale_channels` 和
`valid_guided_channel_analyses`。旧的 aggregate 布尔值保留为兼容性摘要，不再承担
通道级判断。提交一个通道的新结果会合并到既有 mapping，并只清除该通道的 stale 标记。

## 5. corridor 的独立失效语义

`set_ridge_constraint` 与 `clear_ridge_constraint` 只使目标 channel 的 Guided 结果 stale。
其他 channel 的 corridor、STFT 和有效 Guided 分析对象保持不变；共享科学参数、数据或
分析范围改变时才会整体使结果失效。

## 6. 当前显示通道是唯一 Guided 目标

所有 Guided 操作从 Spectrogram channel combo 的 `currentData()` 读取真实 channel name。
运行时请求只传入该通道的 `records`、缓存 `stft_results` 和 corridor；没有 corridor 的
其他通道不会阻止当前通道运行，也不会被 worker 计算。

## 7. 单 worker 边界

仍使用现有单一后台 adapter/worker，没有引入并行 Guided worker。多通道的含义是结果
可逐通道累积，而非同时分析；这样保持既有 generation、Qt 线程边界和 core public
workflow 的行为。

## 8. Guided-only 结果页

工作流状态从能力推导：Automatic 有效或至少一个有效 Guided 正式结果都进入
`RESULT_READY`。因此仅完成 Guided 时，“速度结果”和“结果比较”页可用；不再依赖
Automatic 结果先存在。

## 9. 真实结果来源选择

Ridge 和 Velocity 的来源下拉框只添加实际非空的 Automatic/Guided mapping。Guided-only
场景不再出现不可用的“自动结果”占位来源，也没有把 Guided 数据伪装为 Automatic。

## 10. Velocity 的缺失通道处理

Velocity 保留全部已加载通道作为可选项。若所选真实来源中没有当前通道的结果，图页不
禁用，而显示“当前通道尚无{来源}：{通道}”并清空曲线；正式数组、质量状态和其他通道
结果均不受影响。

## 11. Comparison 的单结果提示

Comparison 在只有一条真实序列时显示“当前只有一个可比较结果。”；有两条或以上时清除
提示。它始终只叠加独立的正式表观速度，不融合、平均、选择或宣称任一来源更正确。

## 12. radio 状态映射

新增 `RidgeExtractionMode.AUTOMATIC/GUIDED`。两个 native `QRadioButton` 由
`QButtonGroup` 的稳定 ID 映射到枚举；业务逻辑从枚举读取，不以某个 radio 的
`isChecked()` 反推模式。单元测试连续切换五次并分别覆盖 Guided 与 Automatic 运行。

## 13. 仅显示的事件前连接

Velocity 图在启用“显示速度（非正式结果）”时额外绘制一条细灰色虚线。点 A 为
`(event_reference_time_s, event 前最后一个 finite display velocity)`，点 B 为 Guided
有效域内首个 finite `apparent_velocity_m_s`。无可用点时不画连接；不插值、不平滑。

## 14. 正式数组保持不变

连接由 `display_velocity_connector_points` 直接构造两个显示点，不写入
`SignalDetectionResult`。测试和真实 GUI 验收都在启用、关闭显示开关前后逐元素比较
`apparent_velocity_m_s`，包括 NaN 位置；正式速度数组保持相同。

## 15. 新增实验性预设

注册两个不可变 Hann profile，均使用 0.05--2.0 GHz 搜索带、hop=128、nfft=4096：
`very_high_time_resolution_experimental` 为 window/overlap=256/128，
`very_high_frequency_resolution_experimental` 为 2048/1920。既有 Balanced、High Time
Resolution、High Frequency Resolution 的 ID 和数值不变。

## 16. 有限窗口的物理解释

在约 40 GHz 采样率下，256 点和 2048 点窗口的有限窗时间尺度分别约为 6.4 ns 与
51.2 ns，对应约 156.25 MHz 与 19.53 MHz 的有限窗频率尺度。固定 nfft=4096 的约
9.765625 MHz 网格并不等于有限窗的真实频率可分辨能力；tooltip 明确说明这是取舍，
不是对任何数据“更准确”的承诺。

## 17. 配置与预设顺序

`pdv_studio_defaults.toml` 注册顺序为：极高时间分辨率（实验）、高时间分辨率、平衡、
高频率分辨率、极高频率分辨率（实验）。默认值仍为 Balanced；解析器继续兼容旧的双/三
预设配置，并校验新的完整五预设集合。

## 18. 预设界面和 tooltip

下拉框提供中文极高时间/极高频率实验性名称。两个极限 profile 分别显示短窗时间响应
增强但有限窗频率分辨更弱、长窗频率分辨增强但快速瞬态时间定位变差的 tooltip；界面未
使用“最佳”“保证”等无依据措辞。

## 19. 翻译更新

对全部 GUI Python 源运行 `pyside6-lupdate`，为 10 条新英文文本补充翻译，再以
`pyside6-lrelease` 生成 `.qm`。最终输出为 373 条 finished、0 条 unfinished；包括
来源缺失提示、单结果提示、极限预设、tooltip 和 Guided 状态文本。

## 20. 单元回归覆盖

新增 `tests/unit/gui/test_task016r2_guided_multichannel.py`，覆盖 Channel 1 后 Channel 2
逐通道运行、切换恢复各自 corridor、仅编辑/清除 Channel 2 不影响 Channel 1、Guided-only
来源选择、缺失通道说明、五次 radio 切换、Automatic 路径和显示连接的数组不变性。

## 21. 预设和配置测试

`test_analysis_profiles.py` 验证两个新 profile 的 ID、窗口、overlap、hop、nfft 和频带；
`test_workflow_config.py` 验证五预设解析和 Balanced 默认值；旧预设 UI 测试改为按 profile
ID 查找 Balanced，避免把新排序错误地当成旧的索引 0 语义。

## 22. 真实数据验收方法

新增仅手工运行的 `tests/manual_task016r2_real_acceptance.py`。它读取四个
`data/raw/*.csv`，在每个文件的双通道上运行全部五预设，记录 STFT shape、帧数、网格、
窗口、hop、nfft、有限窗尺度和 finite 正式速度计数；原始文件仅读取。

## 23. 真实数据预设结果

20 个文件--预设组合均完成。所有通道 STFT 都为 Hann、nfft=4096、hop=128、2049 个正频
率 bin，且出现非零有限正式速度帧。以 20260607.csv 为例，256/512/768/1024/2048 窗口的
帧数分别为 624/622/620/618/610，符合固定 hop 下窗口变长、可定位帧数稍减的预期。

## 24. 原始数据完整性

四个 CSV 在验收前后 SHA-256 完全一致：20260607、20260630-1、20260630-2、20260701 的
完整散列记录在 `artifacts/task016r2/acceptance_summary.json`。验收脚本若发现哈希不同会
直接失败；`git diff -- data/raw` 也保持为空。

## 25. 本机 Qt GUI 验收

真实 20260607.csv 在 Windows 原生 Qt 平台运行 STFT 后，依次完成 Ch1 Guided、Ch2 Guided，
且没有运行 Automatic。结果为两个有效 Guided channel、Automatic 不可用、工作流
`RESULT_READY`、Velocity 来源为 Guided、两通道选择器可用、Comparison 有两条序列。

## 26. 截图证据

`artifacts/task016r2` 含 8 张中文原生 Qt 截图：`five_presets_zh.png`、
`mode_automatic_zh.png`、`mode_guided_zh.png`、`guided_channel1_corridor_zh.png`、
`guided_channel2_corridor_zh.png`、`guided_only_velocity_zh.png`、
`pre_event_display_connector_zh.png`、`guided_only_comparison_zh.png`。预设图是原生 Qt
下拉列表的 416×300 抓图；其余七张为 2880×1760（1440×900 逻辑窗口在当前 Windows
DPI 下的原生像素输出）。

## 27. 验证命令

定向 pytest 使用独立 basetemp 后为 `54 passed`；全量 pytest 以 `PYTEST_ADDOPTS` 注入
独立 basetemp（避免 `test_cli` 读取命令行参数）后为 `442 passed, 1 warning`。默认 Windows
临时根目录与既有 `.test_tmp/pytest_cache` 存在 WinError 5 权限问题，属于环境缓存目录而非
测试断言失败。`ruff check .`、`mypy src` 和 `git diff --check` 均通过。

## 28. Git 状态与后续边界

本任务没有执行 `git add`、commit 或 push；index 保持不暂存。生成的 acceptance JSON 和
截图只位于 `artifacts/task016r2`，源数据没有改写。后续若要持久化 corridor、导出 Guided
正式结果或引入多走廊，应另行定义数据契约、质量语义和科学验证，不能把显示连接当作
正式数据处理。
