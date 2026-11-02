# TASK-032 速度求导与自定义窗口配置

开始核查：2026-11-02，Production `D:\Code\Python_Projects\DPS_Studio`，main，
HEAD `b8524bd3d2da3ff17fe8eece84931b84d9edaaab`。暂存区为空。
既有修改仅 `docs/TASK-031_MACOS_ARM64_INTERNAL_RELEASE.md`，保留不动。
初始 diff、该文件 SHA 和 24 个 raw 文件 SHA 记录于 `build/task032/`。

实际源码：v0.1.4，STFT/ridge → working 表观速度 → 角度修正 → 窗口修正 →
可选事件前显示平台。主图使用 `plot_velocity_m_s`，formal/trusted 仅为诊断叠加。
LiF 已实现 Rigg2014_Eq16，`1000*b1*(v/1000)**b2`，默认 b1=0.7895、
b2=0.9918、参考波长 1550 nm；旧 README 中未实现 LiF 的说明已过时。
现有 GUI 可编辑 b1、b2、参考波长与观测角；参数变化即时重建后处理数组，
不重跑 STFT/ridge/质量门控。TOML 按真实系数恢复配置；没有独立项目会话保存器。
本地 QSettings 原来只保存布局、语言与显示偏好。Windows 以 Conda 启动，
冻结包通过 runtime_paths 读取安装资源，用户配置不能写入这些资源目录。

接入方案（修改前记录）：

- core physics 新增分段有限差分；workflow 新增共享的加速度来源/掩码/元数据适配，
  GUI 和 exporter 使用同一入口，保留输入时间点。主速度来源不变；显示平台、
  无信号、分析区外、插值及无有效 bin 等已知不可求导区返回 NaN。
- VelocityView 增加速度/加速度切换，沿用通道、自动/人工范围、时间零点及刷新。
- exporter 可选额外 `_acceleration.csv`，保留现有两列/详细表格式与默认行为。
  求导在完整时间轴上进行，导出范围筛选随后执行，不跨删行求导。
- 原有 LiF 模型追加可选配置名称，旧 TOML 系数保持原样，差异参数显示自定义。
  新增用户目录 JSON 配置库，完整模型/单位快照、中文名称、显式保存/另存、
  原子写入，损坏文件保留并停止写入。内置常量与公式不改。

## 最终行为

速度页原有主曲线、formal 诊断与通道/自动/人工范围选择保持；新增下拉项
“加速度 dv/dt”。输入为 `plot_velocity_m_s`，时间为该轨迹的完整 STFT 时间轴，
按当前 angle → window 配置实时更新。加速度显示单位 `10⁹ m/s²`、时间 μs；
两种时间零点沿用原设置。切换量时重设轴范围；明确清除 PyQtGraph 缓存的 SI
前缀比例，防止切换速度/加速度后出现错误的刻度因子。

求导 core API：`differentiate_velocity(time_s, velocity_m_s, valid_mask=..., break_before=...)`。
空数组输出空数组；单点 NaN；双点共用割线；三点及以上内部为非均匀三点中心差分，
端点为相邻两点的一侧割线。令 hL=tᵢ−tᵢ₋₁、hR=tᵢ₊₁−tᵢ，内部公式为：

`aᵢ = hR/(hL*(hL+hR))*(vᵢ-vᵢ₋₁) + hL/(hR*(hL+hR))*(vᵢ₊₁-vᵢ)`。

拒绝非一维、长度不等、重复/倒序/非有限时间；不排序修复。NaN/Inf 速度、
no_detectable_beat、分析区外、插值、无可用 bin 及事件前显示平台独立留 NaN，
不跨越已知缺口。独立 API 还支持显式断边。有限低质量 working 点可求导，
保留其输入点质量及工作/人工选峰来源；邻点也可能低质量，数值存在不代表可信。
不平滑、不插值、不改输入、不生成不确定度。

复核/导出页勾选“额外导出加速度 CSV”，生成同组 `_acceleration.csv`：
时间（绝对 `time_s` 或 `time_from_event_s`）、`acceleration_m_s2`、对应 SI 速度、
来源、数值差分标记和输入点质量/working/velocity/选峰来源。先在完整轴求导，
再按原详细表范围选择行；保留无效行 NaN。即使速度简表选择 quality_passed，
加速度表仍明确使用主图 display 速度，不把删行后的点当作相邻求导。
原简表/详细表的列、数值、格式保持；默认不增加 CSV。
原 metadata 的 window 节追加名称、配置类型、公式及单位，旧字段语义保留；
勾选求导时追加 acceleration_export，记录方法、边界、无效段、来源与修正快照。
全部输出仍采用原 staging/非覆盖发布/失败回滚机制。

材料参数区新增窗口配置选择、中文名称、保存自定义配置/保存修改及另存入口。
编辑内置参数即显示“自定义 · 新材料N”，自动避开已有名称。保存后可选回；
仅重命名不改变速度/导数数值。编辑已有项通过显式保存修改或另存；重名拒绝，
导入另一份 TOML 会解除之前的保存目标。内置常量/公式不变；没有新增删除入口。
损坏配置保留原文件、禁用保存并显示路径；写失败保留旧文件并报告错误。
后处理失败时恢复旧配置及两类结果，界面恢复到实际计算值，避免旧曲线配新参数。

本地保存使用 Qt AppConfigLocation，本机实际为：

`C:\Users\89484\AppData\Local\DPS Studio\PDV Studio\window_presets.json`

文件包含版本、完整模型参数（含名称、模型 ID、参考波长、来源字段）及单位；
同目录临时文件 fsync 后原子替换。安装资源目录不写入；布局/语言仍用原 QSettings。
旧 TOML 没有名称仍能按真实参数加载，非默认参数明确显示自定义；可选新增
`velocity_correction.configuration_name`。不自动迁移/改写历史 TOML 或导出。
不从外部库重新查询历史结果：metadata 使用结果对象中不可变的配置快照。
GUI 未编辑的参数保留原始精度，不通过 spinbox 显示精度重新截断。

## 验证与边界

- Python：现有 `D:\miniconda3\envs\dps-studio\python.exe`，3.12.13，无安装/升级依赖。
- 全套 pytest：**776 passed in 104.88s**，没有 portable 排除、skip/xfail。
  日志 `build/task032/pytest_final.txt`。本次新增 59 项测试；原导出快照测试只追加
  新 metadata 字段的预期，保留全部原字段断言。
- 全套通过后修正图轴 SI 前缀缓存，针对 GUI/导出再测 **15 passed in 6.09s**。
- Ruff：`ruff check .` 通过；`mypy --strict src/dps_studio`：**88 source files 通过**。
  日志 `build/task032/{ruff_final,mypy_final}.txt`；`git diff --check` 退出 0，
  仅 Git 提示工作副本未来 LF→CRLF，无空白错误。
- Windows 原生 Qt（windows platform，真实可见窗口与事件循环）脚本化操作：
  导入对话框实际参数 → 正式后台分析 → 速度 → dv/dt → b1=0.8 → 中文保存 →
  选回内置再选回自定义 → 两通道各自导出 → 独立进程重启选回。全部通过。
  对象级 GUI 测试同时覆盖真实后台 busy 锁定、上游参数改动后清空再分析、
  缺少人工范围结果的通道清空、仅名称变更数值不变、损坏配置与历史系数精度。
- 实际使用 `docs/原始数据.csv`：每通道 80,000 电压样本，各 **620** 速度/导数行，
  依规则可用导数分别 **558 / 583**；导出逐点对比内存数组通过，示例 SHA 不变。
  这是流程/可追溯性验证，没有独立加速度真值，未验证物理峰值或矢量方向。
- 原生证据及截图：`build/task032/native_verified/{gui_native.json,gui_restart.json,
  gui_velocity.png,gui_acceleration.png,gui_window_presets.png,native_export/}`；
  可复运行脚本为 `build/task032/gui_workflow.py`（使用隔离用户目录）。
- `data/raw` 全部 **24** 文件前后 SHA 一致；既有 TASK-031 工作副本 SHA 一致；
  暂存区仍空，main/HEAD 不变。完整性证据 `build/task032/integrity_final.json`。
  无 commit/push/分支切换；未改 Research、STFT、ridge、质量门或默认科学参数。
- 数值求导放大噪声/跳变，速度重建窗限制有效时间分辨能力；无符号速度导数
  不是已确定运动方向的矢量加速度，自定义系数名称不代表材料校准。
- 本次交付源码；未重新构建既有 Windows/macOS 安装包，旧发布 EXE 不含新功能。
  无已知未解决的功能测试失败。用户配置删除未纳入本次界面。

## 文件清单

本任务共 21 个文件（12 个已有文件修改，9 个新增），不含下方保留的用户改动。

修改：

- `README.md`
- `src/dps_studio/core/export/models.py`
- `src/dps_studio/core/export/writer.py`
- `src/dps_studio/core/physics/models.py`
- `src/dps_studio/core/physics/corrections.py`
- `src/dps_studio/core/workflow/config.py`
- `src/dps_studio/gui/analysis_session.py`
- `src/dps_studio/gui/main_window.py`
- `src/dps_studio/gui/result_views.py`
- `src/dps_studio/gui/translations/pdv_studio_en.ts`
- `src/dps_studio/gui/translations/pdv_studio_en.qm`
- `tests/unit/test_formal_result_export.py`

新增：

- `docs/TASK-032_ACCELERATION_WINDOW_PRESETS.md`
- `src/dps_studio/core/physics/acceleration.py`
- `src/dps_studio/core/physics/window_presets.py`
- `src/dps_studio/core/workflow/acceleration.py`
- `src/dps_studio/gui/window_preset_editor.py`
- `tests/unit/test_acceleration.py`
- `tests/unit/test_acceleration_export.py`
- `tests/unit/test_window_presets.py`
- `tests/unit/gui/test_acceleration_presets.py`

保留的任务前改动：`docs/TASK-031_MACOS_ARM64_INTERNAL_RELEASE.md`（未触碰）。
运行证据在 git 忽略的 build/task032，另有用户要求的 Obsidian 轻量日志。
