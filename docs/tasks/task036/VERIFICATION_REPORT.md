# TASK-036：PDV Studio Windows 正式发行与 Agent 接口建设验收报告

- **任务编号**：`TASK-036`（`task036`）
- **日期**：`2026-11-20`
- **仓库**：`D:\Code\Python_Projects\DPS_Studio`（Production）
- **分支 / 基线 HEAD**：`main` / `c03edbb639f0e8652f873563e06b6a6426ebf10d`
- **协同执行**：Gemini 4 Argon（总工程师、架构设计、阶段调度与独立验收）+ Codex CLI（`gpt-6.2-sol`, `xhigh`）
- **状态 / 结论**：`COMPLETED` / **PASS（P0 正式安装器与本地集中存储、P1 Production 无界面 CLI、P2 轻量级 Agent Skill 全部交付并通过端到端实机验证；P3 MCP 按规划跳过以保持发行包精简稳定）**

---

## 一、核心交付物清单

1. **Windows x64 正式安装程序**：
   - 路径：`D:\Code\Python_Projects\DPS_Studio\release\PDV-Studio-Setup-x64.exe`
   - 大小：`74,057,655` 字节（约 `70.63 MiB`）
   - SHA-256：`15a3efc3083b8a79419bd3f86d4003a81b0a92549e86e8c85dc6f9d3a7fef4ca`
   - 校验文件：`D:\Code\Python_Projects\DPS_Studio\release\PDV-Studio-Setup-x64.exe.sha256`
   - 签名状态：未签名（`NotSigned`，首次在开启 SmartScreen 的 Windows 系统运行可能出现“Windows 已保护你的电脑”，点击“更多信息 → 仍要运行”即可，未修改任何 Windows 系统安全策略）。
2. **构建与打包脚本 / 配置**：
   - 一键构建与自动化验收入口：`scripts/build/build_windows_installer.py`
   - Inno Setup 6 安装器配置：`packaging/pdv_studio_installer.iss`
   - PyInstaller 双入口（`PDV Studio.exe` + `pdv.exe` 共享 `_internal/`）配置：`packaging/pdv_studio.spec`
   - 第三方再发行许可声明与许可证目录：`packaging/THIRD_PARTY_NOTICES.txt`、`packaging/licenses/`
   - 发布清单：`build/task036_windows_installer/release_manifest.json`
3. **统一运行时路径与 `userdata/` 本地集中存储**：
   - 核心实现：`src/dps_studio/runtime_paths.py`
   - 接入模块：`src/dps_studio/gui/app.py`、`src/dps_studio/gui/main_window.py`、`src/dps_studio/gui/i18n.py`、`src/dps_studio/gui/window_preset_editor.py`、`src/dps_studio/gui/release_workflow_smoke.py`
4. **Production 无界面 CLI (`pdv.exe` / `dps-studio`)**：
   - 核心实现：`src/dps_studio/cli.py`、`src/dps_studio/cli_config.py`、`src/dps_studio/cli_plots.py`
5. **轻量级 Agent Skill**：
   - 源码仓库位置：`.agents/skills/pdv-studio/SKILL.md`
   - 安装后目录位置：`<install_dir>\skills\pdv-studio\SKILL.md`

---

## 二、本地集中存储与安装/升级/卸载行为

### 1. 安装后目录结构

```text
PDV Studio/
├── PDV Studio.exe              # 桌面 GUI 主程序 (console=False)
├── pdv.exe                     # 命令行分析接口 CLI (console=True)
├── _internal/                  # 共享 Python 3.12 / PySide6 / NumPy / SciPy 运行时
├── skills/
│   └── pdv-studio/
│       └── SKILL.md            # Agent Skill 说明文档
├── licenses/                   # Python、NumPy、SciPy、Pandas、PySide6(LGPLv3) 等完整许可证文本
├── THIRD_PARTY_NOTICES.txt     # 第三方依赖再发行声明
├── README.txt
├── RELEASE_NOTES.md
├── BUILD_INFO.json
├── userdata/                   # 本地集中存储目录（不向 AppData 或注册表散落配置）
│   ├── config/
│   │   └── settings.ini        # Qt 界面语言、窗口布局与显示偏好 (INI 格式)
│   ├── materials/
│   │   └── window_presets.json # 用户自定义窗口修正材料系数库
│   ├── presets/                # 用户预设目录
│   ├── cache/
│   │   └── matplotlib/         # MPLCONFIGDIR 进程级缓存目录
│   ├── logs/                   # 运行日志目录
│   └── temp/                   # 冻结态进程级 TEMP / TMP / TMPDIR 临时目录
└── unins000.exe                # 标准卸载程序
```

### 2. 安装、升级与卸载机制

- **普通用户权限 (`PrivilegesRequired=lowest`)**：无需管理员权限（不弹 UAC、不装系统服务、不写开机自启），注册表卸载项写入 `HKCU\Software\Microsoft\Windows\CurrentVersion\Uninstall\{8D6E4A72-5C39-4E91-9B1A-4D2F7A8C0200}_is1`，在 Windows“已安装的应用”列表中正常显示名称、图标与版本 `0.2.0`。
- **智能默认路径与写权限校验**：安装器动态探测非系统固定磁盘（例如存在可写 `D:` 盘时默认推荐 `D:\Programs\PDV Studio`，绝不硬编码盘符；单盘系统自动回退至 `%LOCALAPPDATA%\Programs\PDV Studio`）。若用户选择 `C:\Program Files` 等当前账户无写权限的受保护目录，安装向导与静默安装均会主动拦截并提示选择可写目录，绝不修改系统目录 ACL。
- **运行时 Fail-Fast 保护**：当安装目录或 `userdata/` 不可写时，`PDV Studio.exe` 与 `pdv.exe` 均直接报错并以退出码 `2` 退出，绝不静默回退写入 `%APPDATA%` 或 `%LOCALAPPDATA%`。
- **原位覆盖升级**：同一安装目录覆盖安装时仅更新程序二进制与 `_internal/`，完整保留 `userdata/config/settings.ini` 与 `userdata/materials/window_presets.json`。
- **标准卸载与 `userdata` 保留策略**：卸载时始终清理程序文件、`_internal/`、快捷方式、注册表项、`userdata/cache`、`userdata/temp` 以及（若曾勾选）当前用户 `HKCU\Environment\Path` 中的安装目录项（精确匹配移除，不影响其他软件 PATH）。交互式卸载弹窗询问是否保留 `userdata`（默认保留）；静默卸载默认保留 `userdata`，传入 `/PURGEUSERDATA=1` 时则连同 `userdata` 与安装目录一并彻底移除。

---

## 三、测试与多质量等级真实数据回归结果

### 1. 代码质量与全量自动化测试

- `ruff check src tests scripts/build/build_windows_installer.py scripts/maintenance/check_repo_hygiene.py`：**All checks passed!**
- `mypy --strict src/dps_studio`：**Success: no issues found in 98 source files**
- `pytest tests`（全量测试套件）：**940 passed in 115.96s**

### 2. 多质量等级真实数据回归与 GUI / CLI 逐字节一致性

测试记录保存在 `artifacts/task036/real_data_and_installer_audit/audit_summary.json` 及 `build/task036_windows_installer/release_manifest.json`：

| 数据等级 | 原始数据文件 (`data/raw/`) | 实验条件配置 | 帧数 / `measured` 帧数 (比例) | 安装前后及 Source Core vs Installed CLI/GUI 数值一致性 | 原始文件 SHA-256 前后一致性 |
|---|---|---|---|---|---|
| **高质量** | `data/raw/20260607.csv`（双通道，80,000 点/通道） | `time_unit=s`, `V`, $\lambda=1550\text{ nm}$, $\theta=0^\circ$, `LiF`, `balanced` | Ch1: `620 / 482` (`77.74%`)<br>Ch2: `620 / 485` (`78.23%`) | 简明速度 CSV、明细 CSV、加速度 CSV **SHA-256 100% 逐字节一致** | `ab9f656e...`（完全不变） |
| **中等质量** | `data/raw/PDV数据-质量中等/1/20201210m.dat`（单通道，40,000 点） | `time_unit=s`, `V`, $\lambda=1550\text{ nm}$, $\theta=0^\circ$, `none`, `balanced` | Ch1: `307` 帧（默认频带下准确诊断出 307 帧低频直流分量边界占据 `peak_at_band_boundary` 并在 `quality.json` 告警） | 简明速度 CSV、明细 CSV、加速度 CSV **SHA-256 100% 逐字节一致** | `08a8b8af...`（完全不变） |
| **低质量 / 强挑战 1** | `data/raw/20260701.csv`（双通道，含多处弱信号与竞争峰） | `time_unit=s`, `V`, $\lambda=1550\text{ nm}$, $\theta=0^\circ$, `LiF`, `balanced` | Ch1: `620 / 340` (`54.84%`, `ambiguous_peak=169`, `no_detectable_beat=15`)<br>Ch2: `620 / 313` (`50.48%`, `ambiguous_peak=135`, `no_detectable_beat=12`) | 简明速度 CSV、明细 CSV、加速度 CSV **SHA-256 100% 逐字节一致**（不可靠帧保持 `NaN` 与质量标志，零静默插值） | `5ccb6530...`（完全不变） |
| **低质量 / 强挑战 2** | `data/raw/PDV数据-质量中等/3/20201214m.dat`（单通道） | `time_unit=s`, `V`, $\lambda=1550\text{ nm}$, $\theta=0^\circ$, `none`, `balanced` | Ch1: `307` 帧（`peak_at_band_boundary=305`, `unstable_detection=2`） | 简明速度 CSV、明细 CSV、加速度 CSV **SHA-256 100% 逐字节一致** | `06da315b...`（完全不变） |

- `data/raw/` 全部 24 个文件在全流程构建与测试前后 SHA-256 100% 一致。
- `%APPDATA%` 与 `%LOCALAPPDATA%` 下 `DPS Studio` / `PDV Studio` 快照在安装、GUI 运行、CLI 分析、覆盖升级与卸载前后均为空（零系统盘 AppData 写入污染）。
- `D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN` 保持零改动；`src/dps_studio/core/**` 与 `configs/pdv_studio_defaults.toml` 保持零改动。
