# PDV Studio v0.2.1

## 中文说明

### 主要更新

- **统一极简 5 文件导出（桌面端 & CLI）**：单次分析默认输出 5 个核心文件——`velocity_raw.csv`（全时域原始工作速度）、`velocity_gated.csv`（质量门控正式速度）、`velocity_display.csv`（面向绘图的派生速度）、`run_summary.json`（完整参数与质量汇总）以及 `spectrogram_ridge.png`（时频图叠加工作/正式脊线）。退役旧版 `*_detail.csv`，加速度默认不再导出（CLI 可用 `--acceleration` 按需开启）。
- **OriginPro 友好格式与派生展示曲线**：所有 CSV 保持统一时间网格，缺失或未通过门控的单元格导出为空白 `""`（不再输出 `"nan"`），导入 OriginPro 可直接正确断线绘图；`velocity_display.csv` 在不篡改正式物理结果的前提下，提供段内保端点 3 帧平滑、短缺口桥接（`<= 5` 帧）及可追溯的起跳前展示处理。
- **更智能的 CLI 自动识别与频带重试**：新增 `--auto-columns`，自动识别 `.csv`/`.dat` 分隔符、表头及 1–3 列电压通道并合并导出；当默认低频边界峰导致正式通过率极低时，自动按阶梯低频下限（`0.20 / 0.35 / 0.50 GHz`）重试并仅输出最优结果（可用 `--no-auto-band-retry` 关闭）。
- **桌面端多通道合并导出与一键拖放脚本**：桌面端审阅与导出默认采用「全部通道（合并导出）」；安装目录 `launchers/` 内置两个 Windows 拖放 `.bat` 脚本（`1550 nm + LiF + 0°` 与 `1550 nm + 无窗口 + 0°`），直接将波形文件拖到脚本上即可一键出图出数。

### 升级与下载说明

- **从 `v0.2.0` 升级**：可在软件内通过「帮助 → 检查更新」直接下载并原位覆盖升级，升级过程自动保留 `<安装目录>\userdata\` 中的用户设置、自定义材料与预设。
- **附件说明**：
  - `PDV-Studio-Setup-x64.exe` & `PDV-Studio-Setup-x64.exe.sha256`：Windows x64 独立安装程序及其 SHA-256 校验文件（同时用于软件内自动更新）。
  - `PDV_Studio_v0.2.1_Windows.zip`：完整分发包，额外包含《说明书.pdf》、Agent 专用说明 `README_for_agent.md` 及桌面一键拖放 `.bat` 脚本。

---

## English Release Notes

### Highlights

- **Unified 5-file export bundle (Desktop GUI & CLI)**: Every run exports five focused outputs by default — `velocity_raw.csv` (unfiltered full-grid working velocity), `velocity_gated.csv` (quality-gated formal velocity), `velocity_display.csv` (derived plotting curve), `run_summary.json` (run metadata, retry trace, and quality summary), and `spectrogram_ridge.png` (STFT spectrogram overlaid with working and formal ridges). Legacy `*_detail.csv` is retired, and acceleration export is now opt-in (`--acceleration` in CLI).
- **OriginPro-friendly CSVs and derived display curve**: Non-finite/missing cells export as empty strings (`""`) instead of `"nan"` on the full uniform time grid so plotting tools break cleanly at unmeasured gaps. `velocity_display.csv` provides endpoint-preserving 3-frame smoothing, short-gap bridging (`<= 5` frames), and traceable pre-event display handling while keeping formal measurements strictly untouched.
- **Smarter CLI defaults (`--auto-columns` & stepped low-frequency band retry)**: `--auto-columns` automatically detects `.csv`/`.dat` delimiters, headers, and 1–3 voltage channels for combined export. When low-frequency boundary peaks suppress formal pass rate, CLI performs a single-bundle stepped low-frequency band retry (`0.20 / 0.35 / 0.50 GHz`, opt-out via `--no-auto-band-retry`).
- **Desktop multi-channel export & drag-and-drop launchers**: Desktop review/export defaults to combined multi-channel export (`All channels (combined export)`), and two Windows drag-and-drop `.bat` launchers (`1550 nm + LiF + 0°` and `1550 nm + Free surface + 0°`) are bundled under `launchers/`.

### Upgrade & Assets

- **Upgrading from `v0.2.0`**: Use **Help → Check for Updates** inside PDV Studio for a SHA-256-verified in-place upgrade that preserves `<install_dir>\userdata\` (settings, custom materials, and presets).
- **Release assets**:
  - `PDV-Studio-Setup-x64.exe` & `PDV-Studio-Setup-x64.exe.sha256`: Standalone Windows x64 installer and SHA-256 checksum (used by the built-in updater).
  - `PDV_Studio_v0.2.1_Windows.zip`: Complete bundle including the installer, illustrated user manual (`说明书.pdf`), `README_for_agent.md`, and drag-and-drop `.bat` launchers.
