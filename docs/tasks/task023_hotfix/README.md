# Production TASK-023 Hotfix｜速度语义、拖拽阻塞与快速分析图标修复

- **仓库**：`D:\Code\Python_Projects\DPS_Studio`（`main`，基于 `b6557b015683d34428c384291d4a828824962cee`）
- **职责分工**：Gemini Antigravity 担任技术负责人与独立验收者；实际代码修复由 Codex CLI（`gpt-6.2-astra` 负责核心/导出/三态语义架构，`gpt-6.2-sol` 负责拖放/图标/视口修复与严格类型标注）完成。

## 一、三个问题的根因与解决方式

### 1. 起跳前速度异常非零（三态语义显式分离）

- **根因**：
  1. `src/dps_studio/core/quality/detection.py` 中 `CONTINUITY_ASSISTED_ALTERNATIVE` 帧只要自身通过单帧门限就会被直接提升为 `SignalState.MEASURED`，导致真实数据起跳前的孤立高信噪比噪声（如 `20260607.csv` `pdv_channel_1` 第 `20`、`111` 帧分别输出 `2080.101`、`1443.823 m/s`；`ch2.csv` 第 `404` 帧；`ch3.csv` 第 `9`、`21`、`455` 帧；`ch4.csv` 第 `55`、`65`、`67`、`262`、`387`、`494` 帧）误入正式结果。
  2. `src/dps_studio/core/workflow/analysis.py` 原 `_build_working_ridge()` 在非 `MEASURED` 帧上无条件回退到 `COARSE_BIN_FALLBACK` 或 `STRONGEST_REFINED_FALLBACK`，把 `50 MHz` 搜索下界附近低频峰（`bin 6 = 58.59375 MHz`，LiF 折算约 `36.7719 m/s`）及宽带噪声峰转成有限的 `working_frequency_hz`、`continuous_*_velocity_m_s` 与 `display_velocity_m_s`。
  3. `src/dps_studio/core/workflow/display.py` 原 `build_display_velocity()` 在启用事件前平台且存在参考时间时，将参考前所有帧强制覆盖为 `0.0 m/s`，甚至会覆盖真正测得运动的 `MEASURED` 帧及起跳前强振荡未定帧；同时 `VelocityView` 在确认事件参考刷新显示时未同步扩展 Y 轴以纳入 `0.0 m/s` 静止约束。
- **修复**：
  - `detection.py` / `quality/models.py`：新增 `SignalState.UNASSESSED`，并要求 `CONTINUITY_ASSISTED_ALTERNATIVE` 救回帧必须满足“左右紧邻帧在分析区间内、已评估、非频带边界、通过 `minimum_peak_to_background_db` 门限，且 2 帧内存在已建立的 `MEASURED` 连续支撑段”，被救回帧不再递归作为支撑依据。保留 `20260630-1.csv` `pdv_channel_2` 第 `[1015]` 帧合法连续性桥接（`163.819 m/s` 表观 / `131.268 m/s` LiF）。
  - `workflow/models.py`、`analysis.py`、`acceleration.py`：移除非 `MEASURED` 回退生成物理速度的路径；工作脊线与连续速度仅在 `SignalState.MEASURED` 帧有限，其余非测速帧为 `NaN` 与 `WorkingRidgeSource.UNAVAILABLE`；原始 `ridge_result.frequency_hz` 仍仅作频谱诊断保留；速度微分加速度仅作用于连续 `MEASURED` 段；`channel_dechirp()` 通过 `dechirp_seed_frequencies()` 独立获取诊断初值，确保未干预的 Dechirp 与 STFT 链完全等价。
  - `workflow/display.py`、`export/writer.py`、`gui/result_views.py`：严格建立三态语义——① **有效测速**（`measured`）：始终保留正式修正速度，绝不被事件前平台覆盖；② **事件前静止约束**（`pre_event_display_platform`，仅显示先验）：需同时开启平台、事件参考有效、位于参考及首次持续 `MEASURED` 运动之前，且由 `stationary_pre_event_evidence()` 验证去除窗口 DC 泄漏后的 Parseval AC 能量满足非窄带且不高于基底下四分位数 4 倍（保留 `20260630-2.csv` 第 `[153]` 帧、`ch2.csv` 第 `[355..359]` 帧等起跳前振荡为 `NaN`）；③ **未确定速度**：统一保持 `NaN` 并保留 `signal_state.value` 来源。CSV 简表/详表、`metadata.json` (`undetermined_velocity_frame_count`、`pre_event_display_platform_count`、`display_semantics`)、图例/统计条与主窗口视口自适应全部保持一致。

### 2. 拖拽文件后 Windows 文件资源管理器卡住

- **根因**：Windows 资源管理器通过 `IDropSource::DoDragDrop` 同步等待目标窗口 `IDropTarget::Drop`（即 `MainWindow.dropEvent`）返回。原 `MainWindow.dropEvent()` 直接调用 `_import_file()` 读取预览并进入 `ImportSettingsDialog.exec()` 模态循环，且 `pyqtgraph.PlotWidget` 及其 `viewport()` 默认开启 `acceptDrops=True`，会拦截或阻塞拖放事件流。
- **修复**：
  - `src/dps_studio/gui/main_window.py`：在 `dragEnterEvent` / `dragMoveEvent` 仅做无磁盘阻塞的本地文件 URL 检验；`dropEvent` 优先接收 `CopyAction`、缓存首个本地路径并以 `QTimer.singleShot(0, self, self._process_pending_drop)` 投递到下一轮事件循环后**立即返回**；在 `_process_pending_drop` 与 `_import_file` 中守卫窗口关闭、忙碌态、已打开模态框及异常路径（缺失/目录/无权限），并清理 `closeEvent` 中的 `_pending_drop`。
  - `src/dps_studio/gui/plot_chrome.py`：`style_plot_widget()` 统一关闭 `PlotWidget` 及 `viewport()` 的 `acceptDrops`，确保覆盖在各绘图区域上的拖放穿透到主窗口。
  - `src/dps_studio/core/io/delimited_preview.py`、`src/dps_studio/gui/import_dialog.py`：有界采样（32,768 字符样本截断检查）拦截空文件、二进制控制字符、超长单行及预览无效列，避免异常文件阻塞或错误进入导入器，取消或失败后状态完全可恢复。

### 3. 快速分析图标

- **根因**：`src/dps_studio/gui/icons.py` 中 `"quick_analysis"` 仅用描边线画出偏左上角的空心三角形，并在右下方附加了多余折线 `((9, 20), (12, 17), (15, 19), (20, 11))`。
- **修复**：改为 24×24 坐标内光学居中的单个实心播放三角形 `((7, 5), (19, 12), (7, 19))`，无多余装饰，使用与工业工具栏一致的 `#1e293b` 实色填充和 1×/2× 矢量光栅渲染。

## 二、真实数据对照与关键指标

- `data/raw/` 全部 24 个原始文件 SHA-256 校验与基线完全一致，未作任何修改。
- 基线对比（Production balanced 默认配置，`20260607.csv::pdv_channel_1` 与 `20260630-1.csv::pdv_channel_2`）：
  - `20260607.csv::pdv_channel_1`：STFT 复谱/时间轴/频率轴 SHA-256 与修改前逐比特一致；有效测速从 `390` 帧变为 `388` 帧（撤销第 `20`、`111` 帧孤立噪声，其余 388 帧完全一致）；无参考时起跳前全部 `232` 个非测速帧为 `NaN`；确认自动参考后为 `有效测速 388 帧 · 未确定 15 帧 · 事件前静止约束 217 帧`；`channel_dechirp` `apparent_acceleration_m_s2`（`310` 有限点）SHA-256 与修改前完全一致。
  - `20260630-1.csv::pdv_channel_2`：STFT 复谱/坐标轴、正式表观速度、正式修正速度（含第 `[1015]` 帧 `131.268 m/s`）、`MEASURED` 掩码（`767` 帧）及 Dechirp 加速度（`621` 有限点）SHA-256 与修改前逐比特一致；无参考时为 `有效测速 767 帧 · 未确定 790 帧 · 事件前静止约束 0 帧`；确认参考后为 `有效测速 767 帧 · 未确定 98 帧 · 事件前静止约束 692 帧`。
- `dropEvent()` 返回耗时实测（Qt `MainWindow`，真实 `20260607.csv` 与 `20260630-1.csv`）：`0.055 ms` 与 `0.048 ms`（在进入预览及模态对话框前返回），`20260630-1.csv` 正常导入 `200,001` 行双通道信号。
- 修改前后原生 Windows GUI 截图证据（保存在 `artifacts/task023_hotfix/figures/`）：
  - Before：`artifacts/task023_hotfix/figures/before/20260607_pdv_channel_1_unset_before.png`、`artifacts/task023_hotfix/figures/before/20260630-1_pdv_channel_2_unset_before.png`
  - After：`artifacts/task023_hotfix/figures/after/20260607_pdv_channel_1_unset_after.png`、`artifacts/task023_hotfix/figures/after/20260607_pdv_channel_1_confirmed_after.png`、`artifacts/task023_hotfix/figures/after/20260630-1_pdv_channel_2_unset_after.png`、`artifacts/task023_hotfix/figures/after/20260630-1_pdv_channel_2_confirmed_after.png`、`artifacts/task023_hotfix/figures/pass2_toolbar_windows.png`

## 三、最终验证结果

在最后一次代码改动（`tests/unit/gui/test_task023_hotfix.py` 类型注解修正）之后独立执行观测：

| 检查项 | 命令摘要 | 结果 |
|---|---|---|
| Ruff 检查 | `ruff check src tests scripts/build scripts/maintenance` | **All checks passed!**（退出码 0） |
| 严格 Mypy | `mypy src ... test_task023_hotfix.py --strict` | **100 source files, 0 issues**（退出码 0） |
| 全量 Pytest | `pytest tests -q` | **872 passed in 153.76s**（退出码 0） |
| 仓库卫生 | `python -B scripts/maintenance/check_repo_hygiene.py` | **退出码 0**（`unexpected_root: 0`, `tracked_generated: 0`, `large_tracked: 0`, `raw_copies_in_artifacts: 0`） |
| Research 边界 | `git -C D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN status -sb` | 干净无改动 |

- 其他说明：`pass1.md`、`pass2.md`、`velocity_viewport.md`、`strict_typing.md` 为各阶段分项复核记录；`Qt` 回归已覆盖非阻塞 `dropEvent` 生命周期、穿透与异常文件恢复，桌面资源管理器手工鼠标拖拽留作现场人工顺带复验（OLE `DoDragDrop` 释放机制已在 `dropEvent` 返回时序中解决）。
