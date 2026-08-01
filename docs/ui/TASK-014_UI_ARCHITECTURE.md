# TASK-014 UI 架构

## 1. 设计目标

TASK-014 建立可长期沿用的 PDV Studio 桌面工作台，不追求一次完成最终软件。

界面必须支持后续扩展：

- 非 AI 降噪；
- 自动脊线分析；
- 人工引导分析；
- 双通道复核；
- 窗口修正；
- 文件夹自动监视；
- 示波器只读连接。

当前产品显示名称暂定为：

```text
PDV Studio
```

本任务不重命名仓库 `DPS_Studio` 和 Python 包 `dps_studio`。

### 1.1 旧 DPS 软件的取舍

当前仓库没有可运行的旧 GUI：开发前 `src/dps_studio/gui/` 仅有一个 21 字节的
占位 `__init__.py`，仓库内也没有代码引用该包。因此不存在可以直接迁移的旧
窗口、控件状态或 GUI 数据模型。

可以借鉴的是项目已有的科学工作流概念：显式数据导入、双通道独立处理、分析
范围、STFT、脊线、表观速度、质量诊断和复核导出。必须舍弃的是依赖操作员记忆
按钮顺序、把脚本生产流程直接绑定到按钮、用 Matplotlib 充当主交互视图、用假
数据填充未接入页面，以及把显示值当作正式科学结果。TASK-014 因而采用显式状态
机、public-core adapter 和 PyQtGraph 视图，而不是复刻任何历史界面。

## 2. 主界面布局

```text
┌──────────────────────────────────────────────────────────┐
│ 菜单栏                                                   │
├──────────────────────────────────────────────────────────┤
│ 常用工具栏                                               │
├────────────┬─────────────────────────────┬───────────────┤
│ 流程导航区 │        中央科学绘图区       │ 当前参数区    │
├────────────┴─────────────────────────────┴───────────────┤
│ 质量诊断 / 数据表 / 日志                                 │
├──────────────────────────────────────────────────────────┤
│ 状态栏                                                   │
└──────────────────────────────────────────────────────────┘
```

布局要求：

- 使用 `QMainWindow`；
- 使用 `QSplitter`、`QDockWidget`、`QTabWidget` 或 `QStackedWidget`；
- 中央绘图区占最大面积；
- 左右面板可缩放；
- 支持 1440×900；
- 1280×720 下仍可操作；
- 不使用固定坐标摆放控件；
- 不复制 VS Code 皮肤；
- 不复刻 MATLAB GUIDE 外观。

## 3. 左侧流程导航

固定步骤：

1. 数据导入 / Data
2. 分析范围 / Range
3. 时频分析 / STFT
4. 脊线提取 / Ridge
5. 速度结果 / Velocity
6. 复核与导出 / Review & Export

每一步必须显示状态：

- 未开始；
- 可配置；
- 正在运行；
- 已完成；
- 结果已失效；
- 失败。

## 4. 中央视图

固定标签页：

- 原始信号 / Raw Signal
- 时频图 / Spectrogram
- 频谱脊线 / Ridge
- 速度曲线 / Velocity
- 结果比较 / Comparison

TASK-014 不得使用假数据伪装尚未接入的功能。

## 5. 右侧参数区

参数区随当前步骤切换。

### 数据导入

- 文件路径；
- 时间列；
- 电压列；
- 表头；
- 分隔符；
- 时间单位；
- 电压单位；
- 通道名称；
- 数据摘要。

### 分析范围

- 完整时间范围；
- 分析起点；
- 分析终点；
- 使用当前视图；
- 恢复完整范围。

显示范围与分析范围必须分开。

### STFT

- 分析配置；
- 窗函数；
- window length；
- overlap；
- hop；
- nfft；
- 搜索频段；
- 幅值显示方式。

### 脊线

- 自动分析；
- 引导分析；
- 候选峰；
- 亚频点精修；
- 信号存在检测；
- 连续性设置；
- 人工约束工具入口。

### 速度

- 激光波长；
- 表观速度；
- 窗口修正状态；
- 显示事件前零平台；
- 质量标记。

### 复核与导出

- 双通道比较；
- 自动与引导结果比较；
- 导出数据；
- 导出图像；
- 参数快照；
- 质量标记；
- 输出目录。

## 6. 底部面板

固定标签：

- 质量 / Quality
- 数据 / Data
- 日志 / Log

质量面板显示：

- 信号状态；
- 质量标记；
- 削顶；
- 背景水平；
- 竞争峰；
- 连续性；
- 无可信信号区间。

日志面板记录：

- 数据加载；
- 参数修改；
- 分析开始与结束；
- 警告；
- 错误；
- 导出位置。

## 7. 状态机

正式顺序状态：

```text
EMPTY
DATA_LOADED
RANGE_DEFINED
STFT_READY
RIDGE_READY
RESULT_READY
```

规则：

- `EMPTY`：只能打开数据、设置和帮助。
- `DATA_LOADED`：可以查看原始信号和设置范围。
- `RANGE_DEFINED`：允许运行 STFT。
- `STFT_READY`：允许脊线分析。
- `RIDGE_READY`：允许速度转换。
- `RESULT_READY`：允许复核和导出。

TASK-014 的 `state.py` 定义以上六个状态，只真正进入 `EMPTY` 和
`DATA_LOADED`。其余状态及对应控件已定义但保持不可达/禁用，不伪造分析结果。
未来后台任务可在不改变这六个结果阶段的前提下另加 `RUNNING`、`FAILED` 等瞬时
执行状态。

## 8. 结果失效

修改上游参数后，下游结果必须标记为失效。

示例：

```text
修改分析范围
-> STFT 失效
-> 脊线失效
-> 速度失效
```

```text
修改脊线参数
-> STFT 保持有效
-> 脊线失效
-> 速度失效
```

```text
修改波长
-> STFT 保持有效
-> 脊线保持有效
-> 速度失效
```

不得继续把旧结果显示为当前结果。

## 9. 自动分析与引导分析

### 自动分析

自动完成：

- STFT；
- 候选峰；
- 亚频点精修；
- 信号存在检测；
- 正式频率；
- 表观速度；
- 质量评估。

### 引导分析

用户提供可追溯约束，算法仍负责计算最终频率和速度。

未来工具：

- 事件参考竖线；
- 脊线走廊；
- 包含多边形；
- 排除多边形。

人工约束保存为：

```text
time_s
frequency_hz
```

不得保存屏幕像素。

人工区域内没有可信信号时，正式结果仍为 `NaN`。

TASK-014 只预留界面和状态，不实现正式 ROI 算法。

## 10. GUI 与 core 边界

允许：

```text
GUI -> controller -> public core API
```

禁止：

```text
core -> GUI
GUI -> scripts
GUI -> tests
GUI -> notebooks
GUI -> outputs
```

GUI 可以：

- 收集用户参数；
- 将显示单位转换为 SI；
- 调用 public core API；
- 绘图；
- 显示错误和质量状态。

GUI 不可以：

- 重新实现 STFT；
- 复制速度公式；
- 复制脊线算法；
- 复制信号阈值；
- 自动插值或平滑正式结果；
- 平均两个原始电压通道。

## 11. 中英文

支持：

- 简体中文；
- English。

默认简体中文。

优先使用：

- `self.tr()`；
- `QTranslator`；
- `.ts` 和 `.qm`；
- `QSettings` 保存语言选择。

允许第一版切换语言后重启生效。

CSV 字段、配置键、类名、函数名和枚举值保持英文。

## 12. 视觉规范

- 浅色主题优先；
- 中性灰和深蓝灰为主；
- 使用一个强调色；
- 不使用渐变背景；
- 不使用大面积装饰卡片；
- 不使用复杂动画；
- 不下载来源不明的图标；
- 中文字体优先 `Microsoft YaHei UI`；
- 英文字体优先 `Segoe UI`；
- 路径和日志使用 `Consolas`；
- 支持高 DPI。

## 13. 代码目录

开发前已有：

```text
src/dps_studio/gui/
└── __init__.py
```

开发前 `__init__.py` 只有 21 字节占位 docstring，没有任何功能。TASK-014 复用
同一目录和文件，没有删除、覆盖目录或创建平行 GUI package。

建议职责：

| 文件或目录 | 职责 |
|---|---|
| `app.py` | QApplication 生命周期 |
| `main_window.py` | 组合主窗口 |
| `state.py` | GUI 工作流状态 |
| `i18n.py` | 中英文加载 |
| `styles.py` | 少量统一样式 |
| `controllers/` | 调用 core 和更新状态 |
| `views/` | PyQtGraph 绘图 |
| `panels/` | 导航、参数、质量和日志 |
| `dialogs/` | 导入、设置和导出对话框 |

不得为了形式创建大量空文件。

TASK-014 实际采用的精简结构见第 16 节；尚未需要的 `panels/`、`views/`、
`controllers/` 子包没有为了目录外观而创建。

## 14. 未来采集扩展

发展顺序：

```text
文件导入
-> 文件夹监视
-> 单型号示波器只读连接
-> 多型号适配
-> 远程配置与实验控制
```

未来设备接口应独立于 core 算法和主窗口。

## 15. TASK-014 不实现

- 新降噪算法；
- AI；
- 多边形 ROI 算法；
- LiF 正式修正；
- 示波器连接；
- 文件夹监视；
- 插件系统；
- 云服务；
- 最终安装包。

## 16. TASK-014 实际实现

```text
src/dps_studio/gui/
├── __init__.py
├── __main__.py
├── app.py
├── main_window.py
├── state.py
├── data_controller.py
├── import_dialog.py
├── raw_signal_view.py
├── i18n.py
├── styles.py
└── translations/
    ├── pdv_studio_en.ts
    └── pdv_studio_en.qm
```

逐文件职责与沿用结论：

| 文件 | 职责 | 是否沿用 |
|---|---|---|
| `__init__.py` | 原占位包文件；现补充依赖方向说明并导出 `WorkflowState` | 是，在原文件增量修改 |
| `__main__.py` | `python -m dps_studio.gui` 入口 | 新增 |
| `app.py` | QApplication、样式、翻译器生命周期 | 新增 |
| `main_window.py` | 只组合菜单、工具栏、splitter、tabs、dock、状态栏和状态可用性 | 新增 |
| `state.py` | 六个顺序 workflow states；不包含科学数据 | 新增 |
| `data_controller.py` | 将显式导入请求适配到 public `read_delimited_signals` | 新增 |
| `import_dialog.py` | 显式时间列、电压列、delimiter、header、encoding 与源单位 | 新增 |
| `raw_signal_view.py` | PyQtGraph 原始信号视图；只做 s→μs、V→mV 显示转换 | 新增 |
| `i18n.py` | `QTranslator` 资源加载和 `QSettings` 持久化 | 新增 |
| `styles.py` | 少量浅色 QSS 和系统字体 | 新增 |
| `translations/*` | Qt Linguist 英文源和编译资源 | 新增 |

主窗口使用水平 `QSplitter` 组织左侧流程、中间五个科学标签页和右侧参数栈；
底部使用可停靠 `QDockWidget` 放置质量、数据、日志三个标签。布局不使用固定坐标，
中央绘图区具有 stretch priority，左右区域可拖动。

真实接入只包括：

```text
QFileDialog
-> ImportSettingsDialog
-> SignalLoadRequest
-> DataImportController
-> public read_delimited_signals
-> DelimitedSignalLoadResult / read-only SignalRecord
-> PyQtGraph RawSignalView + data summary
-> DATA_LOADED
```

两个通道各自绘图；没有平均、融合、插值、平滑或源文件写入。未选择的额外列索引
显示在数据摘要中。后续 STFT、Ridge、Velocity、Export action 和页面保持禁用，
并带有“计划功能/尚未接入” tooltip。

中英文使用 `self.tr()`、`QTranslator`、`.ts/.qm` 和 `QSettings`。默认简体中文；
“设置 → 语言”保存偏好，重启应用后生效。英文资源包含 129 条已完成翻译。

## 17. TASK-015A 增量架构

TASK-015A 不改变 TASK-014 的主窗口布局，只把原预留页面接到以下真实组件：

| 组件 | 职责 |
|---|---|
| `native_icons.py` | 通过 `QFileIconProvider` 获取系统目录图标，失败时回退 `SP_DirOpenIcon` |
| `analysis_range.py` | 管理 μs 数值控件中的范围草稿，仅在用户确认后发送 SI 秒端点 |
| `raw_signal_view.py` | 增加受数据边界约束的 `LinearRegionItem`，与范围草稿双向同步 |
| `analysis_session.py` | 保存当前源、只读 records、范围、profile、正式配置、通道结果、有效性和 generation id |
| `analysis_adapter.py` | 在 `QThreadPool` worker 中只调用 public `analyze_profile`，向主线程发送 started/finished/failed |
| `result_views.py` | 显示真实 STFT、三类脊线、formal/display velocity、双通道比较和质量统计 |
| `main_window.py` | 组合状态、配置确认、后台任务和主线程 QWidget 更新，不包含科学算法 |

### 17.1 范围与原始数据

`SignalRecord` 从不裁剪、覆盖、平滑或重采样。图上双竖线与右侧 μs 数值框表示
draft；只有“确认分析范围”“使用完整范围”或“使用当前显示范围”才创建
`AnalysisRange(start_time_s, end_time_s)`。两个通道使用共同时间域交集，范围强制
满足数据边界和 `start_time_s < end_time_s`。

### 17.2 后台执行与取消语义

完整 public workflow 在 `QRunnable` 中执行，所有 `QWidget` 更新仍在 GUI 主线程。
运行期间禁止重复启动并显示不确定进度。core 当前没有 cooperative cancellation
API，所以取消按钮保持禁用；参数变化或重新导入只增加 generation id，迟到结果会
被忽略，但正在进行的 NumPy/SciPy 计算不会被伪装为已中断。

### 17.3 状态和失效

范围确认后进入 `RANGE_DEFINED`。完整结果返回后，主线程按真实聚合结果依次推进
`STFT_READY`、`RIDGE_READY` 和 `RESULT_READY` 并启用对应页面。重新导入、确认新
范围、切换 profile、改变真空波长或重新加载质量配置都会清空内存结果和视图，回到
`DATA_LOADED` 或 `RANGE_DEFINED`。`RUNNING` 仍是独立 busy flag，不加入六阶段
枚举。

英文翻译资源在 TASK-015A 更新为 203 条完成翻译；新增范围、配置、分析、质量和
失效提示均通过 Qt Linguist 资源提供。
