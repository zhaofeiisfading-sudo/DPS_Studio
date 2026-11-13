# PDV Studio 0.1.7

发布日期：2026-11-13

## 主要更新与修复

- **修复全局下拉框（`QComboBox`）弹出列表悬停发白遮字问题**：
  - 根因：在全局 Fusion 样式与 `QComboBox` 样式表组合下，Qt 默认内部委托（`QItemDelegate` 子类）会忽略 `QComboBox QAbstractItemView::item` 状态规则，并将悬停/激活行绘制为实心 `#ffffff` 背景配合高对比失效的前景色，导致文字被白块吃掉。
  - 修复方案：在 `src/dps_studio/gui/styles.py` 全局样式层引入 `_DesktopProxyStyle`、`QStyledItemDelegate`（`_ComboBoxItemDelegate`）以及窗口可用区约束的 `_ComboBoxPopupSizer`，补全 `QComboBox` 及其弹出视图在普通、选中（selected）、悬停（hover）、按下（pressed）、禁用（disabled）、聚焦（focus）下的高对比度浅蓝灰工业风状态配色，并同步统一 `QMenuBar`、`QMenu` 与 `QTableWidget` 的交互反馈。
  - 局部泄露修复：限定 `MainWindow._set_parameter_validation_state` 的校验红框选择器作用域，防止异常高亮边框向下拉框弹出层级联传递。
- **兼容性与科学计算保持不变**：
  - 未修改任何核心物理模型、窗口参数默认值、原始数据或科学分析流程。
  - 提供完整 Windows 目录版（`PDV Studio.exe` 及运行依赖、`configs/pdv_studio_defaults.toml`、翻译与图标资源），可直接整体压缩分发或双击 `PDV Studio.exe` 运行。
