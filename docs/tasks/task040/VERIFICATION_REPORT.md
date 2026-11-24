# TASK-040 验证报告：PDV Studio v0.2.1

- **任务编号**：`TASK-040`（`task040`）
- **仓库与分支**：`D:\Code\Python_Projects\DPS_Studio` / `main`（基于 HEAD `c03edbb639f0e8652f873563e06b6a6426ebf10d` 保留既有未提交改动继续开发；按规未自动 `commit` / `push` / 建 GitHub Release）
- **版本**：`0.2.0` → `0.2.1`

---

## 1. 实现摘要与文件改动清单

### 核心导出与科学边界
- 新增 [bundle.py](file:///d:/Code/Python_Projects/DPS_Studio/src/dps_studio/core/export/bundle.py) 并通过 [\_\_init\_\_.py](file:///d:/Code/Python_Projects/DPS_Studio/src/dps_studio/core/export/__init__.py) 导出，统一由 CLI 与桌面 GUI 调用：
  - 默认统一生成 **5 个输出文件**（取消默认 `*_detail.csv`，加速度 `acceleration.csv` 改为默认关闭按需开启）：
    1. `velocity_raw.csv`（全均匀时间网格，未门控未平滑的连续工作修正速度 `<tok>_raw_velocity_m_s`）
    2. `velocity_gated.csv`（全均匀时间网格，不删行；仅 `signal_state == measured` 且有限帧保留正式修正速度 `<tok>_gated_velocity_m_s`，其余帧输出空白单元格 `""`，无 `"nan"` 文本）
    3. `velocity_display.csv`（由 `build_display_velocity_curve()` 生成：仅基于 `measured` 帧在长度 `>= 3` 连续段内做保持两端点不变的 `[1, 2, 1]/4` 平滑，仅在 `<= 5` 帧内部短缺口线性桥接，并按显式参考 → `stream_event_candidate` → `first_measured_frame` 顺序生成可追溯事件前 `0` 平台；若 `measured_frames == 0` 则全部保持空值不造假）
    4. `run_summary.json`（`schema_version = "pdv-studio-bundle-v1"`，集中记录源校验、输入格式与推断采样率、实验条件、`auto_band_retry` 重试明细、`display_processing` 溯源、质量统计、告警及输出清单）
    5. `spectrogram_ridge.png`（[cli_plots.py](file:///d:/Code/Python_Projects/DPS_Studio/src/dps_studio/cli_plots.py) 中 `render_bundle_spectrogram_ridge()` 基于纯 `PySide6` 无 `matplotlib` 绘制，多通道纵向堆叠，展示频段内 Viridis 时频图、灰虚线 Working ridge、红实线 Formal gated ridge 及通过率标题）
- 保持 [writer.py](file:///d:/Code/Python_Projects/DPS_Studio/src/dps_studio/core/export/writer.py)（`export_formal_results()`）向后兼容；`src/dps_studio/core/export/bundle.py` 经核对不含任何 `PySide6` / `matplotlib` / GUI 导入。
- 受保护核心科学算法与配置目录（`core/time_frequency/**`、`core/ridge/**`、`core/quality/**`、`core/physics/**`、`core/workflow/**`、`configs/**`、`data/raw/**`）均 **零修改**。

### CLI 与桌面端
- [cli.py](file:///d:/Code/Python_Projects/DPS_Studio/src/dps_studio/cli.py) & [cli_config.py](file:///d:/Code/Python_Projects/DPS_Studio/src/dps_studio/cli_config.py)：
  - 新增 `--auto-columns`（自动识别 `.csv`/`.dat` 分隔符与表头，默认第 0 列时间、第 1–3 列为 `pdv_channel_1..3`）、采样率异常范围（`[1e8, 1e12]` Hz 外）stderr + `run_summary.json` 双告警。
  - 新增透明低频下限阶梯重试 `[0.20e9, 0.35e9, 0.50e9]`（未显式指定 `--min-freq-hz` 时，当 `measured_fraction < 5%` 且 `>= 50%` 窗内帧呈 `peak_at_band_boundary` 时触发，最终只在 `--out` 输出 1 份结果；支持 `--no-auto-band-retry` 关闭）。
  - 支持 `--acceleration`、`--full-diagnostics`、`--time-origin {absolute,event}`、`--event-reference-time-s`、`--no-pre-event-display`；`pdv analyze` 在 stdout 打印 JSON 摘要并在 0 有效帧时向 stderr 告警。
- [main_window.py](file:///d:/Code/Python_Projects/DPS_Studio/src/dps_studio/gui/main_window.py) & [pdv_studio_en.ts](file:///d:/Code/Python_Projects/DPS_Studio/src/dps_studio/gui/translations/pdv_studio_en.ts) / `.qm`：
  - 移除 `简表仅含质量通过点` 与默认 `*_detail.csv`，加速度导出默认取消勾选；多通道数据默认选择 **`全部通道（合并导出）`**（`__all__`），预览首路可用通道并保持 Guided 单通道未分析禁用保护；每次导出自动分配无覆写 `<parent>/<stem>_<mode>[_N]` 子文件夹并使“打开目录”直达结果目录。

### 桌面一键拖放脚本与文档打包
- 新增 UTF-8（无 BOM）CRLF 一键拖放脚本：
  - [一键分析_1550nm_LiF_0度.bat](file:///d:/Code/Python_Projects/DPS_Studio/packaging/launchers/一键分析_1550nm_LiF_0度.bat)
  - [一键分析_1550nm_无窗口_0度.bat](file:///d:/Code/Python_Projects/DPS_Studio/packaging/launchers/一键分析_1550nm_无窗口_0度.bat)
  - 内置 `pdv.exe` 自动定位与 `\data\raw` 写入保护（拖入 `data\raw\` 内文件时自动改向 `%USERPROFILE%\Desktop\PDV_Results\` 输出）。
- 更新版本号及说明文档：[__init__.py](file:///d:/Code/Python_Projects/DPS_Studio/src/dps_studio/__init__.py)（`0.2.1`）、[pdv_studio_installer.iss](file:///d:/Code/Python_Projects/DPS_Studio/packaging/pdv_studio_installer.iss)、[RELEASE_NOTES_0.2.1.md](file:///d:/Code/Python_Projects/DPS_Studio/docs/RELEASE_NOTES_0.2.1.md)、[SKILL.md](file:///d:/Code/Python_Projects/DPS_Studio/.agents/skills/pdv-studio/SKILL.md)、[README_for_agent.md](file:///d:/Code/Python_Projects/DPS_Studio/docs/README_for_agent.md)、[USER_QUICK_START.md](file:///d:/Code/Python_Projects/DPS_Studio/docs/USER_QUICK_START.md)、[INSTALL_FAQ.md](file:///d:/Code/Python_Projects/DPS_Studio/docs/INSTALL_FAQ.md) 及 6 页图文手册 [说明书.pdf](file:///d:/Code/Python_Projects/DPS_Studio/docs/说明书.pdf)。

---

## 2. 验证结果清单

### 2.1 静态检查与全量回归测试
- `D:\miniconda3\envs\dps-studio\python.exe -B -m ruff check --cache-dir artifacts\task040\ruff_cache src tests scripts\build\build_windows_installer.py`：**All checks passed!**
- `D:\miniconda3\envs\dps-studio\python.exe -B -m mypy --strict --cache-dir artifacts\task040\mypy_cache src\dps_studio`：**Success: no issues found in 103 source files**
- `D:\miniconda3\envs\dps-studio\python.exe -B -m pytest -q -o cache_dir=artifacts\task040\pytest_cache --basetemp=artifacts\task040\pytest_tmp tests`（设置 `OPENBLAS_NUM_THREADS=1`、`OMP_NUM_THREADS=1`）：**1035 passed in 200.29s (0 failed)**。
  - 新增/更新覆盖：[test_export_bundle.py](file:///d:/Code/Python_Projects/DPS_Studio/tests/unit/test_export_bundle.py)、[test_cli.py](file:///d:/Code/Python_Projects/DPS_Studio/tests/unit/test_cli.py)、[test_task017_result_export.py](file:///d:/Code/Python_Projects/DPS_Studio/tests/unit/gui/test_task017_result_export.py)、[test_task019a_interactions.py](file:///d:/Code/Python_Projects/DPS_Studio/tests/unit/gui/test_task019a_interactions.py)、[test_task023_hotfix_real.py](file:///d:/Code/Python_Projects/DPS_Studio/tests/unit/test_task023_hotfix_real.py)、[test_acceleration_presets.py](file:///d:/Code/Python_Projects/DPS_Studio/tests/unit/gui/test_acceleration_presets.py)、[test_task023_inspector.py](file:///d:/Code/Python_Projects/DPS_Studio/tests/unit/gui/test_task023_inspector.py)、[test_production_release.py](file:///d:/Code/Python_Projects/DPS_Studio/tests/unit/test_production_release.py)。

### 2.2 真实波形 CLI 实测（`--auto-columns` / `s` / `V` / `1550 nm` / `0°` / `LiF`）
所有输出位于 `artifacts/task040/real_data_checks/`（每个目录均仅含 5 个文件且零 `"nan"` 文本）：

| 原始文件 | 通道数 | 触发低频重试 | 最终通过率 (`measured/total`) | 解析频带 (GHz) |
|---|---:|---|---|---|
| `data/raw/20260607.csv` | 2 (`ch1`, `ch2`) | 否 | `390/620 (62.9%)` / `379/620 (61.1%)` | `0.05 – 6.00` |
| `data/raw/PDV数据-质量中等/2/20201211m.dat` | 1 (`ch1`) | **是（`0/307` → `0.20 GHz`）** | **`199/307 (64.82%)`** | `0.20 – 6.00` |
| `data/raw/PDV数据-质量中等/1/20201210m.dat` | 1 (`ch1`) | **是（`0/307` → `0.20 GHz`）** | **`279/307 (90.88%)`** | `0.20 – 6.00` |
| `data/raw/20260701.csv` | 2 (`ch1`, `ch2`) | 否 | `340/620 (54.8%)` / `313/620 (50.5%)` | `0.05 – 6.00` |

- 已通过 `read_file` 人工目视检查 `artifacts/task040/real_data_checks/20201211m/spectrogram_ridge.png` 与 `artifacts/task040/real_data_checks/20260607/spectrogram_ridge.png`：Viridis 时频底图、灰虚线 Working ridge 与红实线 Formal gated ridge 分层清晰，单/双通道堆叠排版与表头完整无误。

### 2.3 Windows 打包、桌面脚本实测与图文手册检查
- 执行 `scripts/build/build_windows_installer.py --output-root build\task040_windows_installer --release-root release\_staging_task040 --analysis-smoke-input data\raw\20260607.csv --allow-dirty` 完成：
  - PyInstaller `dist/PDV_Studio_v0.2.1` 冻结构建成功（内含更新后的 `launchers\*.bat` 与 `skills\pdv-studio\SKILL.md`）。
  - `onedir_verification/report.json` 全部通过：`startup.analysis_smoke.status = PASS`；5 项不同分辨率/语言 `gui_workflows` 均 `PASS`（含 `workflow_complete = True` 与自定义材质重启恢复）；冻结态 `pdv.exe 0.2.1` 输出 5 文件并与 GUI 数值完全一致；运行期零改动包内文件。
  - Inno Setup 6 成功编译安装程序（耗时 66.0s），PE 版本信息确认为 `0.2.1` / `0.2.1.0`。
  - **重要说明（安装器静默安装/卸载循环阶段）**：本机 `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8D6E4A72-5C39-4E91-9B1A-4D2F7A8C0200}_is1` 当前已存在用户本机的 `PDV Studio 0.2.0`（位于 `D:\apps\PDV Studio\`），`build_windows_installer.py::verify_installer()` 按设计安全拒绝对现有注册表执行覆盖/卸载操作，因此未在本机执行无人值守覆写与卸载循环，以完整保护用户现有环境。
- 对冻结版 `build\task040_windows_installer\dist\PDV_Studio_v0.2.1\launchers\一键分析_1550nm_LiF_0度.bat` 执行了真实 `cmd.exe /c` 拖放烟测（输入 `artifacts/task040/bat_smoke/sample.dat`），返回码 `0`，成功生成全部 5 个结果文件。
- 已捕获并目视审阅新版 GUI 截图 `05_export.png`（默认 `全部通道（合并导出）`、加速度默认未勾选、完整显示 5 个文件回执）与 `06_update_dialog.png`（当前版本 `0.2.1`）；已编译 `docs/说明书.pdf` 并用 `pdftoppm` 逐页渲染共 6 页全部目视检查无溢出、无截断。

---

## 3. 交付产物与完整性核验

- **Windows 安装包**：[PDV-Studio-Setup-x64.exe](file:///d:/Code/Python_Projects/DPS_Studio/release/PDV-Studio-Setup-x64.exe)
  - 大小：`74,169,483` 字节
  - SHA-256：`3a8e9bcd70565c22b21c5969fa4e535e0a1d7b03fdcf8e2e385e24a88cfec079`（与 [PDV-Studio-Setup-x64.exe.sha256](file:///d:/Code/Python_Projects/DPS_Studio/release/PDV-Studio-Setup-x64.exe.sha256) 一致，未配置商业代码签名 `NotSigned`）
- **最终分发压缩包**：[PDV_Studio_v0.2.1_Windows.zip](file:///d:/Code/Python_Projects/DPS_Studio/release/PDV_Studio_v0.2.1_Windows.zip)
  - 大小：`75,001,441` 字节
  - SHA-256：`f750f9440a37762c1029549a5654eeb24d32c0fa32f2fd38a21224bc1034a9e7`
  - 压缩包成员及成员 SHA-256 逐一校验通过：
    - `PDV_Studio_v0.2.1/PDV-Studio-Setup-x64.exe`（`3a8e9bcd...`）
    - `PDV_Studio_v0.2.1/说明书.pdf`（`1,606,625` 字节，SHA-256 `dcb52b4c8a822b9cc57b4a79207bdd87617770b61cff62a0fd8e103f5c2cdd4c`）
    - `PDV_Studio_v0.2.1/README_for_agent.md`（`6,978` 字节，SHA-256 `03bf105646acb0a7584d4cc0449dbbf56b60f471486e4c461072dc733fd73c75`）
    - `PDV_Studio_v0.2.1/一键分析_1550nm_LiF_0度.bat`（`2,721` 字节，SHA-256 `82dbaf6c789783eb565085ee02fdb28476ceae77b5d73ead79c6a93a41d22464`）
    - `PDV_Studio_v0.2.1/一键分析_1550nm_无窗口_0度.bat`（`2,728` 字节，SHA-256 `ce0724c07ef7884ed1392c4327b02c4553628a825ab81ac005c99c8ed4a11a7b`）
- **原始数据与仓库卫生**：
  - `data/raw/` 全部 24 个文件在任务前后 SHA-256 完全一致。
  - `check_repo_hygiene.py` 终检通过：`unexpected_root: 0`、`tracked_generated: 0`、`large_tracked: 0`、`duplicate_packages: 0`、`raw_copies_in_artifacts: 0`、`misplaced_packages: 5`（均为既有 Task 029–031 历史产物）。
