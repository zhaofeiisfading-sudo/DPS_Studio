# Production TASK-023｜PDV Studio 商业级产品重设计（v0.2.0）

本任务仅修改 `D:\Code\Python_Projects\DPS_Studio`（Production `main` 分支），基线提交 `5ae3479d`，源码冻结提交 `c276c0c`（`c276c0c6db2ceceee87af10f0bf7b5df9e58f4f6`）。Research 仓库、`data/raw/`、`configs/`、`src/dps_studio/core/**` 及 `AGENTS.md` 均零写入、零修改。

## 1. 分工与协同记录

由 Gemini Antigravity 担任产品设计总监、技术负责人、Codex CLI 调度者与最终验收者，按「Gemini 设计 → Codex CLI 实现 → Gemini 独立审查与实机验收 → 定向返修」推进四个子阶段：

- **Stage 1（`gpt-6.2-astra`）**：桌面外壳、4 步流程导航条、矢量图标系统（`icons.py`）、`InspectorCard` / `CollapsibleSection` / `StatusBanner` 检视原语（`inspector_widgets.py`）、底部固定主操作区、参数输入 `keyboardTracking(False)` 防抖、拖放导入、导出回执横幅与关闭清理；详见 [stage1.md](stage1.md)。
- **Stage 2（`gpt-6.2-astra`）**：图表工作区统一样式 `plot_chrome.py`、欢迎页 `RawSignalView` 空状态与数据徽章、`ResultView` / `ComparisonView` 单行控制条与十字准星 HUD、加速度页内联 `settingsStrip`、Dechirp 拟合缓存与观测角/LiF 参数解耦、`ImportSettingsDialog` 双栏与表格预览；详见 [stage2.md](stage2.md)。
- **Stage 2 Polish（`gpt-6.2-sol`）**：修复 `ManualFrequencyRegionROI`（`ridge_corridor.py`）析构与 PyQtGraph scene 悬停/拖拽指针清理导致的间歇性 `0xC0000005` 崩溃，补充 GUI `QSettings` 临时目录隔离与窗体生命周期释放，修正折叠箭头图标一致性和英文紧凑字距；详见 [stage2.md](stage2.md)。
- **Stage 3 Prep（`gpt-6.2-sol`）**：版本递增至 `0.2.0`、补充中英文翻译并重编译 `pdv_studio_en.qm`、新增 [RELEASE_NOTES_0.2.0.md](../../RELEASE_NOTES_0.2.0.md)、为 `scripts/build/build_production_release.py` 增加 `--onedir-folder` 原生 Windows x64 目录发布模式与发布前隔离冒烟门禁；详见 [stage3.md](stage3.md)。

## 2. 主要改动模块与 Bug 修复

| 类别 | 模块文件 | 核心改进 / 修复内容 |
|---|---|---|
| 视觉与基础组件 | `icons.py`, `inspector_widgets.py`, `plot_chrome.py`, `styles.py` | 统一浅色工业工作台、矢量图标、折叠卡片与单行自适应图表控制栏 / 十字准星 HUD；保持 `QComboBox` / `QMenu` / `QTableWidget` 高对比度悬停选中样式 |
| 主工作台与参数 | `main_window.py`, `workstation.py`, `analysis_range.py`, `window_preset_editor.py` | 四步分段式工作流导航、拖放导入引导、参数失焦提交、材料/事件参按需折叠、导出回执与一键打开输出目录、关闭窗口取消后台 Dechirp |
| 导入与结果视图 | `import_dialog.py`, `raw_signal_view.py`, `result_views.py`, `acceleration_view.py` | 双栏导入卡片 + 4 行表格预览 + 红框作用域收敛；欢迎页空白态引导卡片；`ComparisonView` 修正速度纵轴；Dechirp 缓存与光学修正参数解耦 |
| 生命周期稳定 | `ridge_corridor.py`, `tests/unit/gui/conftest.py` | 断开 ROI 信号、停止 `_overlay_timer` 并清空 scene hover/drag 引用消除崩溃；测试 `QSettings` 沙盒化 |
| 构建与测试 | `scripts/build/build_production_release.py`, `tests/unit/test_production_release.py`, `test_task023_*.py` | 支持 `--onedir-folder` 发布、新增 Inspector / Plot Workspace / 发布门禁回归测试 |

## 3. 科学计算等价性与数据完整性

- **数值与导出字节对齐**：在真实数据 `20260607.csv`、`20260630-1.csv`、`20260701.csv` 上运行 `scripts/dev/research_task19_acceptance.py` 并对照 `v0.1.7` 基线（`artifacts/task023/baseline/parity`），`results.json`（STFT、速度、修正、微分与拟合加速度、CSV 指纹）完全一致；全部 3 份 `.metadata.json` 仅在 `software_version`、`dps_studio_version`（`0.1.7` → `0.2.0`）与 `exported_at_utc` 存在预期差异。
- **Dechirp 基线核对**：3 份真实记录的 `channel_dechirp` 加速度数组 `shape`、有限点数（`310` / `621` / `326`）与数组字节 SHA-256 同 `artifacts/task023/baseline/dechirp_baseline.json` 完全一致。
- **原始数据完整性**：`data/raw/` 全部 24 个文件与 `artifacts/task023/baseline/raw_sha256.json` 零键差、零哈希变化。

## 4. 静态检查、回归测试与桌面实机验证

- **静态检查**：`ruff check src tests scripts/build scripts/maintenance` 零错误；`mypy --strict`（99 个源文件）零问题。
- **全量回归**：`pytest tests`（`-o cache_dir=artifacts/task023/cache/pytest --basetemp=artifacts/task023/tmp/pytest_final`）执行 **841 passed in 129.22s**（0 failed / 0 skipped）。
- **视觉截图对照**：改版前后真实截图保存于 `artifacts/task023/figures/before/`（12 张）、`artifacts/task023/figures/after/`（14 张，含 `v0.2.0` 关于弹窗 `11_about_dialog.png` 与 `QComboBox` 悬停弹出层 `12_combobox_hover.png`）及 `artifacts/task023/figures/stage2_polish/`（60 张中英文多分辨率截图）。

## 5. Windows x64 正式发布与独立 EXE 实机验收

- **构建命令**：`D:\miniconda3\envs\dps-studio\python.exe -B scripts/build/build_production_release.py --onedir-folder --output-root build/task023_windows_x64 --analysis-smoke-input data/raw/20260607.csv`
- **发布目录**：`D:\Code\Python_Projects\DPS_Studio\release\PDV_Studio_v0.2.0_Windows_x64\`（主程序 `PDV Studio.exe`，共 **453** 个文件，总计 `240,919,185` 字节；含 `_internal/`、`README.txt`、`RELEASE_NOTES.md`、`BUILD_INFO.json`，完整保留既有 `PDV_Studio_v0.1.7_Windows_x64` 等旧发布包，未生成重复安装包或 ZIP）。
- **构建清单**：`build/task023_windows_x64/release_manifest.json`（commit `c276c0c6db2ceceee87af10f0bf7b5df9e58f4f6`，`PDV Studio.exe` 发布前已通过 `zh_CN` 1.0x+重启、`en` 1.25x、`zh_CN` 1.5x、`en` 2.0x 工作流与图标/Dechirp 验收）。
- **发布后直接启动 EXE 独立验收**（`PATH=C:\Windows\System32;C:\Windows`，无 Python/Conda/Qt 环境变量，独立外部临时目录）：
  1. `20260607.csv` 启动与分析冒烟通过（`version=0.2.0`, `qt_platform=windows`, `ch1_rows=620`, `Qt6Core.dll` 来自发布目录 `_internal/`）。
  2. `20260630-1.csv` 简体中文 `1366x768` 全流程工作流与 `--workflow-restart` 参数恢复通过（`dechirp_finite=621`，成功导出 8 个双通道 CSV/metadata 文件）。
  3. `20260607.csv` 英文版 `QT_SCALE_FACTOR=1.25`（实测 `dpr=2.5`）全流程工作流与导出通过（metadata `software_version="0.2.0"`，导出 8 个文件）。
  4. 无参数直接启动 `PDV Studio.exe`，Win32 `EnumWindows` 验证 `'PDV Studio'` 主窗体可见并优雅关闭（exit code `0`）。
  5. 运行全部实机用例前后，发布目录全部 **453** 个文件 SHA-256 哈希零变化。

## 6. 仓库卫生与规则核查

- `scripts/maintenance/check_repo_hygiene.py` 退出码 `0`（`unexpected_root: 0`, `tracked_generated: 0`, `large_tracked: 0`, `duplicate_packages: 0`, `raw_copies_in_artifacts: 0`）。
- `.gitignore` 与 `AGENTS.md` 已覆盖本任务目录规范，无需修改。
