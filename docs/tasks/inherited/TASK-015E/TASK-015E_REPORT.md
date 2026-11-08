# TASK-015E 科学绘图显示与桌面工作台交互优化报告

## 结论

TASK-015E 已完成。改动仅位于 GUI 显示、交互、翻译、测试、文档和验收截图；没有修改 STFT、脊线、信号检测、质量判定、速度公式、显示速度科学语义、导出、ROI、LiF 或采集代码。

当前环境为 PyQtGraph 0.14.0、Qt 6.11.1。最终全量测试为 408 passed，Ruff、mypy strict 和 `git diff --check` 均通过。

## 开始前审计

### 灰度图原实现

原 `SpectrogramView` 和 `RidgeView` 创建 `pg.ImageItem(axisOrder="row-major")` 后直接调用 `setImage`，没有显式 LUT、ColorMap 或 colorbar。因此实际显示依赖 ImageItem 的默认灰度映射。

显示数组由 `relative_magnitude_db` 生成，定义保持为：

```text
20 log10(|STFT| / channel global maximum)
```

原实现及本任务后的实现都只在下限处按当前 `relative_db_floor` 截断，显示 levels 为 `(relative_db_floor, 0 dB)`。该量是 Relative STFT Magnitude，不是 SNR。本任务没有改动输入 spectrum 或上述计算。

### 分析范围原交互问题

原始 `RawSignalView` 已使用可移动的 `LinearRegionItem`，两条边界也是 PyQtGraph 原生 `InfiniteLine`，因此“看起来能拖但拖不动”不是科学状态或坐标逻辑错误。实际问题是：

- 正常 pen 只有 1 px；
- 没有显式 `hoverPen`，PyQtGraph 默认 hover pen 与正常 pen 同宽；
- 没有 marker，`_maxMarkerSize` 为 0；
- 没有水平 resize cursor、tooltip 或状态栏反馈。

PyQtGraph 0.14.0 的 `InfiniteLine._computeBoundingRect()` 会按 marker 大小、正常/hover pen 最大半宽和设备像素向量构造原生命中区域。原配置因此只有很窄的屏幕像素命中范围，并非 QSplitter 或数据坐标问题。

### splitter 原来不能拖动的真实原因

运行时审计结果如下：

| 项目 | 原值/行为 |
|---|---|
| splitter handle width | 4 px |
| 左栏 minimum / size hint | 210 / 274 px |
| 中央 minimum size hint | 约 622 px |
| 右栏 minimum / size hint | 310 / 408 px |
| 左/右水平 QSizePolicy | Preferred |
| 中央水平 QSizePolicy | Expanding |
| 底部 dock features | Closable、Movable、Floatable，架构正常 |

在 1440 px 窗口中请求 `[160, 1000, 270]` 时，原 splitter 被约束为 `[210, 912, 310]`；请求压缩中央区域时又被子控件 size hint 限制。底部 dock 本身可移动/浮动，但 central widget 的垂直 size hint 使其高度增长被提前夹住。真实阻塞来自侧栏 minimum、子控件 size hint、QSizePolicy 与过窄且不明显的 separator，不是 QSplitter 或 QDockWidget 缺陷。

## 新 colormap API

新增轻量模块 `display_preferences.py`，集中维护以下稳定显示 ID：

- `viridis`（默认）；
- `cividis`；
- `grayscale`。

Viridis 和 Cividis 使用当前 PyQtGraph 0.14.0 内置 `pg.colormap.get()`。Grayscale 使用显式黑到白的两点 `pg.ColorMap`。没有使用 jet、rainbow 或其他彩虹色图，也没有新增依赖。

`SpectrogramView.set_colormap()` 只调用 ColorBar/ImageItem 的显示映射 API，不重新调用 `_set_image`，不替换 `ChannelAnalysis`，不改变 `AnalysisSession.generation_id` 或 `results_valid`。Ridge 页的 STFT 背景同步使用同一显示偏好。

## colorbar 定义

使用 PyQtGraph 0.14.0 的 `ColorBarItem`：

- 与 Spectrogram `ImageItem` 绑定并共享同一个 ColorMap；
- 每次载入结果时显式同步 `(relative_db_floor, 0 dB)` levels；
- 中文标签：`相对 STFT 幅值 (dB)`；
- 英文标签：`Relative STFT Magnitude (dB)`；
- tooltip：`20 log10(|STFT| / max|STFT|)`，并明确说明不是正式 SNR；
- `interactive=False`、`colorMapMenu=False`，避免把显示动态范围操作误解为频谱重算。

## 新 hit、hover 与 cursor 方案

继续保留既有 `LinearRegionItem / InfiniteLine` 架构，没有自定义鼠标坐标换算或数据单位宽度。

- 正常边界仍为 1 px 蓝线；
- hover pen 为 4 px 橙色高亮；
- 每条边界在 94% 高度处使用 6 px 原生 `<|>` marker；
- marker 与 hover pen 自动进入 PyQtGraph 的设备像素 bounding/hit area；
- 边界 cursor 为 `Qt.SizeHorCursor`；
- tooltip 与状态栏显示“拖动以调整分析范围”/“Drag to adjust the analysis range”；
- 状态探测复用每条 InfiniteLine 的原生 `boundingRect()`，没有散落的屏幕分辨率或 mouse-position pixel hack。

拖动仍只更新分析范围草稿；完整数据范围、分析范围和显示范围继续相互独立。`SignalRecord` 没有被修改。

## 布局修复

保留既有 horizontal QSplitter 和 bottom QDockWidget，只做局部修复：

- 左/中/右 minimum width 调整为 150/360/240 px；
- 三个子区水平 policy 使用 `Ignored`，让 splitter 不再把内容 size hint 当作不可越过的宽度；
- 相关垂直 policy 使用 `Ignored`，允许底部 dock 获得真实高度变化空间；
- 中央区仍设置 360 px minimum，不能缩成 0；
- 三个 splitter child 均显式 `collapsible=False`；
- splitter handle width 为 7 px，并有 hover 样式；
- QMainWindow dock separator 为 7 px，并有 hover 样式；
- QDockWidget 保持原架构，显式保留 Closable、Movable、Floatable features。

Windows 原生 Qt 鼠标事件验收结果：

- 左边界从 2.000000 μs 拖到 2.261413 μs，右边界保持 4.000000 μs；
- 左 splitter 从 `[220, 866, 340]` 拖到 `[281, 805, 340]`；
- 右 splitter 随后拖到 `[281, 756, 389]`；
- bottom dock 改为 380 px 后可保存并在重启后恢复。

## QSettings

沿用应用现有组织名和应用名下的 QSettings，键名不依赖翻译文本：

| 键 | 内容 |
|---|---|
| `display/spectrogram_colormap` | 最后一次合法色图选择 |
| `layout/main_window_geometry` | `saveGeometry()` |
| `layout/main_window_state` | `QMainWindow.saveState(version=1)` |
| `layout/workspace_splitter_state` | horizontal splitter state |
| `layout/diagnostics_dock_height` | bottom dock 高度 |

启动时逐项验证 QByteArray 和 restore 返回值；损坏或旧值不会使启动崩溃。中文保存的布局已在英文界面恢复，证明布局键与翻译无关。

新增“视图 → 恢复默认布局”/“View → Restore Default Layout”。它恢复默认 geometry、toolbar/dock state、`[220, 830, 340]` splitter 比例和 210 px bottom dock，并立即持久化。Windows 原生重启验收中，保存状态 `[281, 756, 389] / 380 px` 恢复为 `[281, 754, 389] / 380 px`（中央 2 px 为窗口装饰差异），恢复默认后为 `[220, 864, 340] / 210 px`。

## 测试

新增 `tests/unit/gui/test_task015e_display_workspace.py`，覆盖：

1. 切换色图前后 STFT spectrum 和相对 dB 数组逐元素相同；
2. 默认 Viridis；
3. Grayscale 可切换；
4. Cividis 可切换；
5. 中英文 colorbar label 和实际 levels；
6. colorbar 不把显示量命名为 SNR，tooltip 明确否定正式 SNR；
7. colormap 不改变 generation 或 `results_valid`；
8. 边界存在显式 hover pen 和原生 marker；
9. 边界使用 `SizeHorCursor`；
10. 边界移动只发出分析范围变化；
11. SignalRecord 时间和电压数组逐元素不变；
12. PlotWidget 显示 X 范围变化不改 LinearRegionItem 范围；
13. 左/中/右 sizes 可程序化改变；
14. 侧栏没有 fixed width，size policy 允许 resize；
15. bottom dock 可在 170 px 和 400 px 间改变；
16. QSettings 恢复 splitter 与 dock；
17. reset layout 恢复默认值；
18. 中文保存、英文恢复后布局逻辑不变；
19. GUI 不导入 scripts；
20. `data/raw`、`scripts`、`outputs` Git 状态为空。

执行结果：

```text
基线 pytest: 401 passed
最终 pytest: 408 passed in 20.80s
Ruff: All checks passed!
mypy --strict src: Success: no issues found in 60 source files
git diff --check: passed
```

## screenshots

四张截图均由本机 Windows Qt `windows` 平台插件生成并进行视觉检查：

- `artifacts/task015e_ui/spectrogram_viridis_zh.png`
- `artifacts/task015e_ui/spectrogram_grayscale_zh.png`
- `artifacts/task015e_ui/analysis_range_hover_zh.png`
- `artifacts/task015e_ui/resized_workspace_zh.png`

截图确认中文字体、Viridis/Grayscale 与共享 colorbar、左边界 hover 高亮和小型 marker、三栏宽度变化及 bottom dock 高度变化均可见。Cividis 在同一原生 GUI 运行中切换并验证，且会话保持 `results_valid=True`。

## Git 与受保护目录

- 分支：`main`，相对 `origin/main`；
- 按要求没有提交；
- cached diff 为空；
- `git diff --check` 和 cached check 均通过；
- `data/raw/**`、`scripts/**`、`outputs/**` 没有改动；
- 未新增第三方依赖；
- 任务开始前已有的 TASK-015D 临时目录仍为 untracked，本任务没有删除、覆盖或修改它们。

TASK-015E 到此停止；没有开始 TASK-016。
