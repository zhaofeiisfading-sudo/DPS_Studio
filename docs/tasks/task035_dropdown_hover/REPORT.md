# TASK-035: 下拉框悬停显示修复与 Windows 目录发布 (v0.1.7)

## 1. 根因定位

1. **Qt 默认组合框委托绕过 QSS 状态样式导致“白块遮字”**：
   - 此前 `src/dps_studio/gui/styles.py` 仅使用原生 `"Fusion"` 样式，并配置了 `QComboBox { background: #ffffff; }` 等外框样式，但未声明 `QComboBox QAbstractItemView` 及其子项样式，且未替换 `QComboBox` 默认的内部 `QComboBoxDelegate`（`QItemDelegate` 子类）。
   - 在 PySide6 (`Fusion`) 下，`QItemDelegate` 不遵循 `QComboBox QAbstractItemView::item` 样式表规则，悬停/选中激活项（`State_Selected | State_MouseOver`）与主控件样式叠加后被绘制成实心 `#ffffff` 亮白块，配合高亮前景色，导致选项文字（含中文标签）对比度大幅下降甚至不可辨。
2. **参数校验红框向下拉弹出层泄露**：
   - `MainWindow._set_parameter_validation_state` 对异常控件直接调用 `control.setStyleSheet("border: 1px solid #c62828;")`，因未限定选择器，红框规则会向下级联到 `QComboBox` 的弹出容器框。
3. **同类弹出组件状态不一致与窄下拉框截断**：
   - `QMenu` 仅设置了全局背景与前景色，缺少 `QMenu::item:selected` / `:disabled` 反馈；此外为弹出项加入 padding 后，若按控件默认宽度展示长标签下拉框（如右侧参数区/导出区），需要结合 `screen.availableGeometry()` 自适应放宽弹出宽度且不溢出屏幕右边界。

## 2. 修改内容

- [styles.py](file:///D:/Code/Python_Projects/DPS_Studio/src/dps_studio/gui/styles.py)
  - 引入 `_DesktopProxyStyle(QProxyStyle("Fusion"))`，在 `polish` 阶段对全部 `QComboBox`（主窗口、弹窗及动态对话框）统一调用 `configure_combo_box_popup`。
  - 安装 `_ComboBoxItemDelegate(QStyledItemDelegate)` 使弹出项完整响应 QSS 状态，并为 `view()` 设置对比度安全的 `QPalette`（`Base=#ffffff`, `Text=#1b2a3b`, `Highlight=#e4f0f8`, `HighlightedText=#102a43`）与 `ElideRight`。
  - 增加 `_ComboBoxPopupSizer` 事件过滤器，在弹出窗口 `Show` 时依据 `view.sizeHintForColumn(0)`、滚动条宽度与 `screen.availableGeometry()` 调整弹出层宽度并防止右边缘裁切。
  - 在 `APPLICATION_STYLE_SHEET` 中补全克制统一的工业风浅蓝灰交互配色：
    - `QComboBox` 本体：正常 `#ffffff` / `#c5d1de`，`:hover:enabled` `#f5f9fc` / `#5c8eac`，`:focus` & `:on:enabled` `#166d9b`，`:disabled` `#edf2f6` / `#6d7c8d`
    - `QComboBox QAbstractItemView::item`：正常 `#1b2a3b`，`:selected` `#e4f0f8`（字 `#102a43`），`:hover:enabled` `#d2e5f3`（字 `#0d2338`，框 `#79a7c7`），`:pressed:enabled` `#c1dcf0`（字 `#091d30`），`:disabled` `#8a99a8`（无悬停高亮）
    - 同步统一 `QMenuBar::item`、`QMenu::item` 与 `QTableWidget` 选中/悬停配色。
- [main_window.py](file:///D:/Code/Python_Projects/DPS_Studio/src/dps_studio/gui/main_window.py)
  - `_set_parameter_validation_state` 将无选择器样式收缩为 `"QComboBox, QAbstractSpinBox { border: 1px solid #c62828; }"`，避免校验红框渗透到下拉弹出框。
- [__init__.py](file:///D:/Code/Python_Projects/DPS_Studio/src/dps_studio/__init__.py) & [RELEASE_NOTES_0.1.7.md](file:///D:/Code/Python_Projects/DPS_Studio/docs/RELEASE_NOTES_0.1.7.md)
  - 递增补丁版本至 `0.1.7`（无核心算法/默认参数/配置修改）并新增版本说明。
- [test_combo_popup_styles.py](file:///D:/Code/Python_Projects/DPS_Studio/tests/unit/gui/test_combo_popup_styles.py)
  - 新增 5 项 GUI 回归测试，覆盖全局 `QComboBox` 代理配置、样式表关键选择器、中英文悬停/禁用像素对比度（>= 7.0）、校验红框非泄露及弹出框自适应宽度。

## 3. 交付目录

- 完整可分发文件夹：`release/PDV_Studio_v0.1.7_Windows_x64/`
- 主程序：`release/PDV_Studio_v0.1.7_Windows_x64/PDV Studio.exe`
- 依赖与资源：`release/PDV_Studio_v0.1.7_Windows_x64/_internal/`（含 PySide6/shiboken6/SciPy/NumPy、`ffi-8.dll` 等 Conda 运行库、`configs/pdv_studio_defaults.toml`、翻译文件与程序图标）
- 说明文档：`README.txt` 与 `RELEASE_NOTES.md`

## 4. 验证记录

- `ruff check src tests scripts/build scripts/maintenance`：通过（All checks passed）
- `mypy src tests/unit/gui/test_combo_popup_styles.py`（strict）：94 个源文件 0 问题
- `pytest tests`：814 passed
- Windows 实机界面采样与像素检查（`QT_QPA_PLATFORM=windows`，最大化窗口及 `ImportSettingsDialog`）：右侧参数区下拉框与顶部菜单悬停背景 `#d2e5f3`、深色文字清晰、禁用态无悬停变白、屏幕右边界无裁切
- 隔离环境（无 Conda/Python/Qt 环境变量，仅 `C:\Windows\System32;C:\Windows`）实机运行 `release/PDV_Studio_v0.1.7_Windows_x64/PDV Studio.exe`：
  - `--startup-smoke-test` + `--analysis-smoke-input`：`PASS`（`version=0.1.7`, `qt_platform=windows`, `analysis_smoke=PASS`）
  - `--workflow-smoke-test`：5 项用例全部通过（`zh_CN` @ 1.0x + 重启参数恢复、`en` @ 1.25x、`zh_CN` @ 1.5x、`en` @ 2.0x）
  - 无参数桌面直接启动后主窗体 `['PDV Studio']` 正常可见并优雅退出（exit code 0），运行后全部 452 个打包文件 SHA-256 不变
- 中间构建目录 `build/task035_dropdown_hover/` 与临时测试图像/缓存已清理。
