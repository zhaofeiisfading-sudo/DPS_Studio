# PDV Studio CLI / Agent 快速参考（Windows v0.2.1）

> 面向 Codex、Antigravity、Claude Code 等自动化 Agent 及终端用户，提供无界面 5 文件标准导出与批量调用指南。（普通研究人员图文指南请查看同目录下的 `说明书.pdf`。）

---

## 1. CLI 安装状态与 PATH 配置

> **核心说明**
> - **CLI 已随软件安装，无需额外单独安装**。运行 `PDV-Studio-Setup-x64.exe` 时，`<安装目录>\pdv.exe`、`launchers\*.bat`（桌面一键拖放脚本）与 `skills\pdv-studio\SKILL.md` 会默认随主程序一并安装。
> - 安装向导仅将 **Add command-line tool (pdv) to current user PATH** 设为可选项（默认未勾选）。安装时勾选并重开终端，即可直接输入 `pdv`。
> - **若终端无法直接输入 `pdv`，请按说明补加 PATH**（任选下面一种方式即可）。

### 校验当前是否可用

```powershell
pdv --version
Get-Command pdv
```

正常应返回 `pdv 0.2.1` 及 `pdv.exe` 所在路径。

### 未勾选 PATH 时的 3 种补救方式

- **方式 A（推荐）**：再次运行 `PDV-Studio-Setup-x64.exe`，安装到同一目录并勾选 `Add command-line tool (pdv) to current user PATH`（原有 `userdata/` 会完整保留），完成后**重开终端**。
- **方式 B（PowerShell 一键写入当前用户 PATH，无需管理员权限）**：

```powershell
$dir = "D:\Programs\PDV Studio"   # 改为你的实际安装目录
$cur = [Environment]::GetEnvironmentVariable("Path", "User")
$parts = @($cur -split ';' | Where-Object { $_ -and $_.TrimEnd('\') -ne $dir.TrimEnd('\') })
[Environment]::SetEnvironmentVariable("Path", (($parts + $dir) -join ';'), "User")
```

执行后**重开终端**即可（也可在 Windows 搜索“编辑账户的环境变量” → 用户变量 `Path` 中手动新增安装目录）。

- **方式 C（不改 PATH，直接通过完整路径调用）**：

```powershell
& "D:\Programs\PDV Studio\pdv.exe" --version
```

> **静默安装同时写入 PATH 示例**：
> ```powershell
> .\PDV-Studio-Setup-x64.exe /VERYSILENT /TASKS="addtopath"
> ```

---

## 2. 最小可用命令

### ① 检查数据结构（只读，不修改原文件）

```powershell
pdv inspect "waveforms\shot01.dat"
```

输出含 SHA-256、分隔符（支持逗号 / Tab / 空格 / 分号）、编码、表头推测与样例行（**列索引从 0 开始**）。

### ② 单文件最快命令（推荐 `--auto-columns`）

适用于最常见的 **2–4 列文件**（第 0 列时间，第 1–3 列信号；自动识别 `.csv`/`.dat` 分隔符与表头）：

```powershell
pdv analyze "waveforms\shot01.dat" --auto-columns `
  --time-unit s --voltage-units V `
  --wavelength-m 1.55e-6 --angle-deg 0 --window-material LiF `
  --out "results\shot01"
```

- 常用可选参数：
  - `--min-freq-hz` / `--max-freq-hz`（未手动指定 `--min-freq-hz` 时，若因低频边界峰导致通过率 `< 5%`，会自动按 `[0.20, 0.35, 0.50]` GHz 阶梯重试并在 `--out` 只输出 1 份最终结果；传入 `--no-auto-band-retry` 可关闭）
  - `--time-origin event --event-reference-time-s <秒>`（以起跳时刻为时间零点）
  - `--no-pre-event-display`（关闭 `velocity_display.csv` 的事件前零平台）
  - `--acceleration`（默认**关闭**加速度，传此参数才额外生成 `acceleration.csv`）
  - `--full-diagnostics`（仅排障需要时额外导出 `<tok>_detail.csv`）

### ③ 配置文件方式与批量处理（`experiment.json`）

```json
{
  "time_column": 0,
  "time_unit": "ns",
  "voltage_columns": { "pdv_channel_1": 1, "pdv_channel_2": 2 },
  "voltage_units": { "pdv_channel_1": "mV", "pdv_channel_2": "V" },
  "vacuum_wavelength_m": 1.55e-6,
  "measurement_angle_deg": 0.0,
  "window_material": "LiF"
}
```

```powershell
pdv analyze "waveforms\shot01.csv" --config "experiment.json" --out "results\shot01"
pdv batch "waveforms" --config "experiment.json" --out "results\batch01" --pattern "*.csv"
```

(`time_unit` 支持 `s|ms|us|ns|ps`；`voltage_units` 支持 `V|mV`；`window_material` 支持 `LiF`、`none` 或已保存自定义预设。使用 `pdv <command> --help` 查看全部参数。)

---

## 3. 输出目录结构与关键目录

### 统一 5 文件标准输出（CLI 与桌面 GUI 结构一致）

```text
results\shot01\
├── velocity_raw.csv        # 全时间网格原始工作速度（未门控、未平滑，列名 <tok>_raw_velocity_m_s）
├── velocity_gated.csv      # 全时间网格门控正式速度（仅 measured 帧有数；无效帧为空白单元格 ""，无 "nan" 文本）
├── velocity_display.csv    # 直接作图曲线（measured 端点保留 3 帧平滑 + 短缺口 <=5 帧线性桥接 + 可追溯起跳前 0 平台）
├── run_summary.json        # 实验条件、质量统计、auto_band_retry 与 display_processing 溯源、warnings 与文件清单
└── spectrogram_ridge.png   # 时频图 + 灰虚线工作脊线 + 红实线正式门控脊线总览（多通道纵向堆叠）
```

> - 多通道（1–3 路）自动按列合并在同一张 CSV 中（`ch1_*`, `ch2_*`, `ch3_*`），不再默认输出 `*_detail.csv` 与加速度文件。
> - `velocity_gated.csv` 中未通过帧写为空白 `""`（不删行、不写 `"nan"`），Origin / Excel 可直接按数值列导入并自动在缺测区间断线。

### 安装目录关键文件

```text
<安装目录>\PDV Studio\
├── PDV Studio.exe             # 桌面 GUI 主程序
├── pdv.exe                    # 命令行入口（禁止脱离 _internal\ 单独复制）
├── launchers\                 # 桌面一键拖放脚本（1550nm / 0° / LiF 或无窗口，可复制到桌面使用）
├── _internal\                 # 共享运行时（含 configs\pdv_studio_defaults.toml）
├── skills\pdv-studio\SKILL.md # Agent 专用工作流规范
└── userdata\                  # 设置、窗口预设、缓存与日志
```

- **路径与 `userdata` 隔离规则**：每次重跑必须使用新的空 `--out` 目录（拒绝覆写，禁止输出到 `data/raw/`）；若设置 `PDV_STUDIO_USERDATA_DIR`，**必须单独指向临时/缓存目录，严禁放进 `--out` 结果目录内**。

---

## 4. Agent 必守规则

- **向研究人员确认实验条件**：通道单位、波长、角度与窗口材料必须真实确认，禁止猜数或默填 `none`。
- **禁止自写替代算法**：统一调用 `pdv inspect` / `pdv analyze` / `pdv batch`，不要另写 STFT 或速度换算脚本。
- **读取摘要与检查空测警告**：分析后务必读取标准输出 JSON 与 `run_summary.json` 中的 `quality`、`auto_band_retry` 与 `warnings`；退出码 `0` 仍可能因低信噪比出现 `0` 有效帧（此时会向 `stderr` 告警，且 `velocity_display.csv` 保持全空不造假数据）。
- **保护原始数据与运行中文件**：绝不修改 `data/raw/` 原始波形；执行软件覆盖升级前请先结束正在运行的 `pdv.exe`。
