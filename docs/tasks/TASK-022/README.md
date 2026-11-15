# TASK-022｜PDV 真实波形与频率支路诊断工作台

- **日期**：2026-11-14 ~ 2026-11-15
- **状态**：已完成并验收通过（阶段性报告，最终以真实 Git/源码/测试输出为准）
- **协作分工**：Gemini（架构设计、技术负责与独立视觉/代码验收）+ Codex CLI（Stage 1–3b 编码实现）
- **基线仓库与分支**：`D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN`（分支 `codex/research_2/global-path-ridge-v2`）
- **Core 架构细节补充**：[STAGE1_IMPLEMENTATION.md](STAGE1_IMPLEMENTATION.md)

## 一、核心目标与设计理念

围绕 **“STFT 能看到运动轨迹，却不一定能正确选择它”** 的工程痛点，在 Research 软件内新增第 3 个工作区模式 **`波形与支路诊断`（`diagnostic`）**，通过“纯 Core 诊断引擎 + 多视图联动 PyQtGraph GUI”，在同一真实样本索引与共同帧中心上完整回答：

1. **此刻原电压里到底有什么频率？**（256/512 点局部原波形与投影 Legendre 基线+Tone/Chirp 拟合、FFT 局部功率谱 + 背景阈值）
2. **六个方法（`B0`、`B1`、`B+S`、`Dechirp`、`VarPro`、`S2`）分别看到了什么、选择了什么？**
3. **为什么某个候选通过（`C`/`G`/`S`/`selected`）而另一候选被拒？**
4. **如何严格区分“候选存在 `C` / 原生门限接受 `G` / 原波形局部支持 `S` / 算法选择”与“物理主目标支路身份”？**
   - 明确告警：`S=True` 仅证明局部样本窗内存在可分辨正弦或线性调频能量支持，**不自动确认物理主目标支路身份**；在多支路竞争或弱信号区仍需结合轨迹连续性与实验先验判断。
   - 所有被 `G`/`S`/选中筛掉的候选依然按 `C=1`（或带外参考 `raw_frequency_hz`）保留在时频图与候选表中，拒绝静默删点或平均频率。

## 二、架构与产出文件

### 1. 纯 Core 诊断引擎（无 GUI / `research` 包依赖）
- [src/dps_studio/core/diagnostics/\_\_init\_\_.py](../../../src/dps_studio/core/diagnostics/__init__.py)
- [src/dps_studio/core/diagnostics/models.py](../../../src/dps_studio/core/diagnostics/models.py)：`DiagnosticComputeMode`（`FAST_CORE` / `FULL_S2` / `PRECOMPUTED_STACK`）、`DiagnosticBundle`、`MethodDiagnosticCurve`、`CandidateEntry`、`ClusterDiagnostic`、`FrameDiagnosticTags`、`LocalFrameEvidence` 等不可变数据快照。
- [src/dps_studio/core/diagnostics/explanations.py](../../../src/dps_studio/core/diagnostics/explanations.py)：`verdict_code` 与中文 `C/G/S` 通过/拒绝原因生成器，显式区分 `G_WITHOUT_S`、`S_WITHOUT_G`、`Chirp 调频救回`、`DC 泄漏` 与带外上下文。
- [src/dps_studio/core/diagnostics/engine.py](../../../src/dps_studio/core/diagnostics/engine.py)：复用 `core/workflow` 与 `waveform` 估计器（`B0`/`B1`/`Dechirp`/`VarPro`/次级估计器/`S2` 共识投票），提供同步双底图（原始 `W1024` / 去均值 `W512`）、共同原样本中心映射及 `inspect_frame` 原波形投影精确拟合。
- [src/dps_studio/core/diagnostics/frozen_loader.py](../../../src/dps_studio/core/diagnostics/frozen_loader.py)：可选载入 `artifacts/TASK-018/data/stack_v1` 冻结结果并与真实原始电压对账；缺失冻结文件时安全退回实时计算，打包软件不依赖 `artifacts/`。

### 2. 多视图联动诊断工作台（PySide6 + PyQtGraph）
- [src/dps_studio/gui/diagnostic/\_\_init\_\_.py](../../../src/dps_studio/gui/diagnostic/__init__.py)
- [src/dps_studio/gui/diagnostic/theme.py](../../../src/dps_studio/gui/diagnostic/theme.py)：方法/异常高对比调色板、自适应 `contrast_levels`、内置 `spectrogram_lut()`。
- [src/dps_studio/gui/diagnostic/worker.py](../../../src/dps_studio/gui/diagnostic/worker.py)：真实算例预设索引（`20201210m_ch1`、`ch3_ch1`、`20260630-1_ch2`、`20201214m_ch1`）与可取消后台工作线程（保护窗口/控件销毁线程安全）。
- [src/dps_studio/gui/diagnostic/plots.py](../../../src/dps_studio/gui/diagnostic/plots.py)：
  - **01 原始电压·阶段与证据窗**：显示真实时间轴（`μs`）、静默背景截止线、阶段着色带与实时 256/512 点证据框；
  - **02 共同原始/去均值 STFT 底图**：动态标题明确区分“传统原始 1024 STFT（可见 DC 泄漏）”与“去均值 512 STFT（抑制直流偏置）”，叠加 `● G∩S/已选`、`◇ G无S`、`○/× 未选C`、`+ S无G` 符号、`50 MHz` / `6.00 GHz 评估上限` 以及 `0–10 GHz` 带外参考视野；
  - **03 原波形证据·异常时间线**：联动查看 `Tone R² vs Chirp R²` 或 `对比度 vs 背景增益 dB`，附带双图例与 5 类异常（`分歧>100MHz`、`G无S`、`S2救回`、`多支路竞争`、`高共识缺S`）彩色标记与关键帧筛选跳转；
  - **04/05 右中微观检查区**：`LocalWaveformPlot` 对比 `去基线残差 + 拟合` 与 `含DC原始电压 + 基线`；`LocalSpectrumPlot` 为非聚焦/多估计器候选标注预留顶部 headroom 并按真实文本包围盒自动错层防重叠。
- [src/dps_studio/gui/diagnostic/inspector.py](../../../src/dps_studio/gui/diagnostic/inspector.py)：`FrameVerdictHeader`（区分原生 `[G? S?]` 与 `B+S`/`S2` 的 `[已选 S1]`/`[未选 S0]`）、8 列零横向截断候选对照表、4 行 `[过]`/`[未]` 结构化裁决理由框。
- [src/dps_studio/gui/diagnostic/workspace.py](../../../src/dps_studio/gui/diagnostic/workspace.py)：三轴时间联锁、全视图工具栏、关键帧跳转（`< 上一关键帧` / `下一关键帧 >` / `< -1帧` / `+1帧 >`）与方法显隐控制。
- [src/dps_studio/gui/research_window.py](../../../src/dps_studio/gui/research_window.py)：接入第 3 工作区模式，切换进入诊断模式时自动隐藏底部空置 `diagnostics_dock` 并在切出或关闭窗口时恢复原状。

### 3. 测试与实景截图脚本
- [tests/unit/test_task022_diagnostics_core.py](../../../tests/unit/test_task022_diagnostics_core.py)：40 项核心、物理口径、`FULL_S2` 与冻结参考精确一致及无 GUI 隔离测试。
- [tests/unit/gui/test_task022_diagnostic_workspace.py](../../../tests/unit/gui/test_task022_diagnostic_workspace.py)：18 项 GUI 联动、真实数据预设加载、线程取消/析构、`diagnostics_dock` 自动显隐恢复、动态底图标题与顶部 headroom 徽标防碰撞测试。
- [scripts/research/task022/capture_workbench_views.py](../../../scripts/research/task022/capture_workbench_views.py)：离屏真实算例 `1600×960` 截图与清单导出脚本。

## 三、真实数据关键发现与渲染核验

最终 10 张 `1600×960` 实景截图位于 `artifacts/TASK-022/figures/20261115_004011_865122/`（清单见 `capture_manifest.json`），经 Gemini 逐张视觉检查均无文字重叠、轴标签裁切或字体方框（`□`）：

| 实测算例 | 关键帧 / 位置 | 诊断工作台揭示的真实物理与算法行为 | 代表截图 |
|---|---|---|---|
| `20201210m_ch1` | 帧 `#18, q=2304` (`+57.6 ns`, `onset`)；帧 `#184, q=23552` (`+588.8 ns`, `decline`) | 原始 1024 底图可见强烈 `<250 MHz` DC 偏置泄漏（`B0` `C=305, G=0, S=0`）；去均值 512 底图下 `B1`/`B+S`/`S2` 正确拾取约 `3.7 GHz` 与快速下降段（`q=23552` 时 `B1=3.064 GHz`, `Tone R²=0.774`, `周期=19.53`）。 | `20201210m_dc_leak_B0_raw.png`, `20201210m_onset_B1_detrended.png`, `20201210m_decline_B1.png` |
| `ch3_ch1` | 帧 `#334, q=42752` (`+1068.8 ns`, `onset`) | `B0`/`B1` 在 `3.67/3.66 GHz` 虽被原生 `G=1` 发布，却因 `[未]maxR²=0.199(≥0.20)` 呈 `G_WITHOUT_S`（`[可疑] G=1无S`）；`Dechirp`/`VarPro`/`S2` 于 `3.414 GHz` 凭借 `80 GHz/μs` 调频拟合将 `R²` 从 `0.151` 提升至 `0.452`（`Chirp 调频救回`）并通过 `S`。 | `ch3_onset_q42752_B0.png`, `ch3_onset_q42752_dechirp.png`, `ch3_onset_q42752_dechirp_raw.png` |
| `20260630-1_ch2` | 帧 `#1017, q=130176` (`+3254.4 ns`, `weak_signal`) | 单帧出现 `3` 个 `S` 支持竞争簇（`0.225`、`0.362`、`0.507 GHz`）：`B+S` 选出 `0.5073 GHz`（`Tone R²=0.492`, 原始 `B1 G=0` 被抑 `S_WITHOUT_G`），`S2` 选出 `0.3616 GHz`（`Chirp R²=0.531` vs `Tone R²=0.075`, `votes=3`）。 | `20260630_weak_competing_3254p4ns_B1.png`, `20260630_weak_competing_3254p4ns_S2source.png` |
| `20201214m_ch1` | 帧 `#85, q=10880` (`+272.0 ns`) 与平台区 | `0–10 GHz` 视野清晰展示约 `6.3–6.4 GHz` 平台超出 `6.00 GHz` 评估上限的带外能量上下文，避免误将“超界未选”当作信号不存在。 | `20201214m_out_of_band_context.png` |

## 四、验证与仓库边界记录

全部验证均通过 `pwsh -File scripts/dev/run.ps1 -Task TASK-022 -Python D:\miniconda3\envs\dps-studio\python.exe` 在最终源码修改后完成：

- **Core 测试（`tests/unit/test_task022_diagnostics_core.py`）**：`40 passed, 0 failed, 0 skipped`（`43.062 s`）；含 `20201210m_ch1` 与 `ch3_ch1` 对 `stack_v1` 冻结曲率/候选/簇摘要精确一致校验。
- **全量 GUI 回归（`scripts/dev/check_gui.py --task TASK-022`）**：`27` 个测试模块共 `228 passed, 0 failed, 0 errors, 0 skipped`，零超时重试（`580.61 s`），其中 `test_task022_diagnostic_workspace.py` `18 passed`；原有经典与分段工作区（含 `test_task012_workspaces.py` 26 项、`test_task015e_display_workspace.py` 等）全部无回归通过。
- **静态检查与格式化**：`ruff check` 通过；`ruff format --check`（15 个文件）通过；`mypy --strict`（15 个文件）通过。
- **仓库卫生与边界核查**：
  - `check_repo_hygiene.py --json` 返回 `findings: []`（退出码 `0`）。
  - `data/raw/`（11 个文件）、Production 仓库（`D:\Code\Python_Projects\DPS_Studio`）、既有算法默认配置（`core/physics/`、`core/analysis_profiles.py`、`configs/`）、`artifacts/` NTFS Junction 及工作区内既有的 9 个无关未提交 dropdown 改动均保持原状。
  - 收尾时已清理 `artifacts/TASK-022/tmp/` 临时缓存与旧版中间截图目录，保留唯一验证截图集 `artifacts/TASK-022/figures/20261115_004011_865122/`。
