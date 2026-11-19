# TASK-024｜M4 深入验证与 STFT 可视化对比

**结论状态：完成（全 10 文件 / 14 路真实通道科学验证 + Research GUI「STFT vs M4 对比工作区」集成 + Windows PyInstaller `onedir` 正式发布包构建与真机 EXE 实测验收）**  
**日期**：2026-11-19  
**仓库与分支**：`D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN` · `codex/research_2/global-path-ridge-v2`（基线 `c2568241f6959b49a2b9b380ef1022bf5badff00`）  
**研究负责人 / GUI 设计 / 独立验收**：Gemini Neon  
**工程实现 / 测试 / Windows 打包执行**：Codex CLI (`gpt-6.2-sol`, `xhigh`)

**关键交付与过程记录**：
- 阶段验收记录：[PHASE_2_VERIFICATION.md](./PHASE_2_VERIFICATION.md) · [PHASE_3_VERIFICATION.md](./PHASE_3_VERIFICATION.md)
- 共享纯科学核心与 GUI 代码：`src/dps_studio/core/stft_m4/`、`src/dps_studio/gui/comparison/`、`src/dps_studio/gui/research_window.py`、`src/dps_studio/gui/app.py`、`scripts/research/task024/`
- 正式 Windows 便携发布包（Git 忽略，可直接整体压缩分发）：`release/TASK-024/PDV_Studio_Research/`（含 `PDV Studio Research.exe` + `_internal/`，452 文件，230.09 MiB，EXE SHA-256 `2bfd80385fc4962ce754f08ee2497d4fe66bc7b91e84c06bdb659ca364de76c0`）
- 科学研究数据表与对照图（Git 忽略）：`artifacts/TASK-024/study/tables/`、`artifacts/TASK-024/study/figures/fig01–fig05`
- 真实 EXE 启动烟测与 8 张成功/失败实测截图（Git 忽略）：`artifacts/TASK-024/exe_verify/`、`artifacts/TASK-024/figures/exe_screenshots/exe_01–exe_08`

---

## 一、核心科学问题回答

> **M4 究竟在哪些场景真正优于简单 STFT？增益来自什么？又在哪些场景不值得使用？**

在全部 **10 个真实 PDV 文件 / 14 路真实通道 / 9,475 个主中心**、严格统一原始电压、样本中心网格 `q`、主频带 `[50 MHz, 6 GHz]`（另附 `20201214m_ch1` 独立 `8 GHz` 副对照）以及同一原始波形证据评估口径下，通过新增 **4 组等物理观察时长 STFT 对照**（`STFT_12p8ns`、`STFT_25p6ns`、`STFT_25p6ns_quad`、`STFT_38p4ns_quad`）和 **6 项留一组件消融**，得出明确结论：

### 1. M4 真正优于简单 STFT（含等物理时长 STFT）的四类真实场景

1. **急减速与高调频弱尾段（$\beta_T = |\mathrm{d}f/\mathrm{d}t|\cdot T^2 \ge 3.0$ 周期）**：
   - 仅把 STFT 窗口拉长到与 M4 相同的 `25.6 ns` 或 `38.4 ns`（即使加入二次多项式去势），不仅**无法**复制 M4，反而在高调频下降区发生灾难性调频展宽：
     - 在全部 `decline`（$n = 699$）上，`B1` 为 `667/699`（`95.4%`），`STFT_25p6ns_quad` 跌至 **`496/699`（`71.0%`）**，`STFT_38p4ns_quad` 暴跌至 **`332/699`（`47.5%`）**，而 **`M4_full` 达 `689/699`（`98.6%`）** 且 25.6 ns 原始波形解释度中位达 **`0.823`**（`B1` 仅 `0.591`）。
     - 在 $\beta_{25.6} \ge 3.0$ 周期的急变 `decline + weak_signal` 帧（$n = 575$，中位 $\beta_{25.6} = 6.55$ 周期）上，`STFT_38p4ns_quad` 仅存 `76/575`（`13.2%`），`STFT_25p6ns_quad` 仅存 `241/575`（`41.9%`），`B1` 为 `462/575`（`80.3%`，中位 25.6 ns $R^2 = 0.130$），而 **`M4_full` 达 `485/575`（`84.3%`，占 M4 全部可辨识帧 `100%`）** 且 25.6 ns 原始波形 $R^2$ 提升至 **`0.567`**（为 `B1` 的 **4.36 倍**、无去调频 `M4_no_chirp` `0.177` 的 **3.21 倍**）。
   - 典型真机实证：`20201211m_ch1`（`108.358–108.384 µs` 弱尾，`B1` 与 `25.6 ns STFT` 均提前中断，`M4` 连续追踪至 `0.748 GHz`）、`20221017a_ch1`（弱尾延伸至 `2.771 GHz` 且尾后零离群）、`ch3_ch1`（弱尾连续恢复 `44/44`）。
2. **起跳台阶边缘与低频脉冲基线抑制（`onset`）**：
   - 长窗 STFT 在起跳前产生严重低频泄漏与边缘涂抹（`onset` 跌至 `49/69`，`20201214m_ch1` 起跳前误报 `62/73`，`20201210m_ch1` 起跳前误报 `8/10`）。
   - `B1` 在 `20201214m_ch1` 起跳处误将单脉冲基线抖动报为 `~0.20–0.24 GHz` 速度（`2/5`）；`M4` 拒绝该非持续低频伪迹（`0/5`，在 `8 GHz` 模式下正确锁定 `6.40 GHz` 平台 `114/114`），并在 `20201210m_ch1` 借分侧阶跃投影提前 `3.2 ns` 捕获 `~3.79 GHz` 真起跳。
3. **震后宽带噪底抑制（无晚时 CW 通道 `noise` 段）**：
   - 窗内 35 分位 `CA-CFAR` 与孤岛清理在不损失有效信号段的前提下，将 7 路无晚时 CW 通道的噪声段发布压低至 **`4/599`（`0.67%`）**（远低于 `B1` `26/599`、`B+S` `33/599`），尤其在 `ch3_ch1` 彻底清除了震后宽带噪声伪轨迹。
4. **多支路并存 / 晚时 CW 竞争下的主支路连续性**：
   - 在 `20260630-1_ch2`（`747.18–747.26 µs`）等减速靶面信号与晚时 `~0.51 GHz` CW 并存区间，`B1` 发生跳变上浮至 CW，而 `M4` 保持连续靶面主线并将 CW 作为 `secondary_hz` 显式暴露；全集 `>250 MHz` 邻帧跳变从 `B1` 的 `21` 次（`B+S` `37` 次）降至 `7` 次。

### 2. 增益究竟来自什么？（6 项留一消融定量拆解）

数据来源：`artifacts/TASK-024/study/tables/method_summary_all14.csv` 与 `dual_gain_pairs_comparison.csv`。

| 留一消融项 | 去掉该机制后的定量退化 | 科学机制归因 |
|---|---|---|
| **`M4_no_chirp`（去调频）** | `decline` `689 → 670`（`-19`）、`unknown` `315 → 290`（`-25`）、`decline` 25.6 ns $R^2$ **`0.823 → 0.597`**、跳变 `7 → 9` | **非平稳相位相干增益核心**：消除长积分窗内的调频展宽，使弱尾信噪比在 $\beta_T \ge 3$ 周期下依然聚焦 |
| **`M4_no_cfar`（去 CA-CFAR）** | `stationary` 误报 **`72 → 155`（+83）**、非 CW `noise` **`151 → 190`（+39）**，信号段 `0` 损失 | **零信号代价的宽带抗噪门**：在震后/高噪底窗内将局部相对谱底抬高，消除伪条纹 |
| **`M4_no_lowfreq_floor`（去 38.4 ns 低频噪底与持续振荡门）** | `stationary` 误报 **`72 → 200`（+128）**、`>250 MHz` 分歧 `+6`，信号段 `0` 损失 | **基线漂移与起跳前低频免疫门**：过滤 `<250 MHz` 不足完整周期的瞬态曲率拟合 |
| **`M4_no_path_gap`（去运动学 Viterbi + 缺口复验 + 孤岛清理）** | 邻帧跳变暴增近 9 倍（**`7 → 61`**）、`stationary` **`72 → 239`**、非 CW `noise` **`151 → 249`**、`20260630-1` 双增益大误差 `0 → 4` | **时间连贯与孤立虚警抑制核心**（但也是 `20260607` 晚时双支路切换滞后的来源） |
| **`M4_no_cw_harmonic`（去 CW 拮抗与 2–8 阶谐波排除）** | 晚时 CW 竞争帧大频差分歧 `+3`、`20260607` 双增益 `>250 MHz` `14 → 16` | **多支路与削顶谐波解耦**：防止 CW 压倒运动支路，并防止削顶谐波误触发 CW 拮抗 |
| **`M4_no_step_rail`（去阶跃/触轨分侧保护）** | 失去起跳阶跃边缘隔离；但**意外暴露一项负作用**：去掉后反而找回了 4 帧被 `pre_edge_side_veto` 误拒的高 $R^2$ 帧且削顶窗双通道中位频差由 `0.38–1.87 MHz` 降至 `0.04–0.09 MHz` | **双刃剑机制**：起跳台阶处有益，但当前对 `rail_exit` / `DC_step` 前侧一刀切否决会造成有效信号单帧误伤 |

### 3. M4 在哪些场景不值得使用？（诚实边界、失败案例与代价）

1. **高信噪比平稳平台 / 缓变主段 + 快速交互式初筛**：
   - 在 `plateau`（$n = 2,342$）、`acceleration`（$n = 97$）及 $\beta_{25.6} < 0.5$ 周期的缓变段，`B1`、`STFT_25p6ns_quad` 与 `M4` 频率中位差仅 `0.06–0.91 MHz`、`0` 跳变。
   - **算力代价**：即使经 Phase 2 等价缓存优化将长记录耗时削减 **22.0%–35.5%**（`20221017a`: `19.55 → 15.25 s`；`20260630-1_ch1`: `26.19 → 16.89 s`），`M4` 仍比 `B1`（`0.35–1.40 s`）慢 **7–20 倍**。因此日常快检与强信号区 **不值得用 M4 替代 B1**。
2. **对起跳前微弱窄带杂波/电磁串扰高度敏感的静默段（高灵敏度反噬）**：
   - `20260630-1_ch1` 静态段（$n = 699$）`M4` 发布 `60` 帧（`B1` `29` 帧），含 `744.09–744.17 µs` 连续 `26` 帧 `~1.83 GHz` 微弱条纹（仅 `±2 mV`、`25.6 ns ρ = 0.993`）与 `33` 帧 `~100 MHz` 振荡。虽然波形确实存在微弱窄带振荡（且与 `ch2` 存在跨通道相干），但在无独立干涉/电干扰隔离证实时，将其直接当作靶面运动速度发布存在误导风险，必须保留为**未知归属/前驱争议**。
3. **无明确物理优势的晚时双支路等权竞争区（滞后分歧）**：
   - 在 `20260607` 晚时 `555.70–555.75 µs`，高低增益两通道间由于分支 SNR 细微差别叠加 Viterbi 路径滞后，导致 `M4` 在两通道上的支路切换时刻不同步，产生 **`14` 帧 `>250 MHz` 双增益分歧**（反而高于 `B1` 的 `4` 帧）。
4. **重度限幅但高信噪比的连续区（`pre_edge_side_veto` 单帧误伤）**：
   - 全集 `9,475` 帧中共有 `72` 个「`B1` 强短窗（$R^2_{6.4\text{ns}} \ge 0.15$）但被 `M4` 拒绝」的点：其中 `53` 个在 `stationary/noise`（多数为 M4 正确拒噪）、`2` 个为 `20201214m` 起跳假低频（正确拒绝），但明确抓出 **4 帧真实误伤**：最典型为 `20260630-1_ch1` 反弹段 `747.026015 µs`（$R^2_{6.4\text{ns}} = 0.989$、`0.335 GHz` 极清晰信号）因紧邻 `rail_exit` 前侧被 `pre_edge_side_veto` 一刀切否决，以及 `20260607` `unknown` 段 3 帧（$R^2 = 0.54\text{–}0.96$）因紧邻 `DC_step` 前侧被否决。此外在重度削顶窗内，触轨样本剔除会带来 `0.38–1.87 MHz` 的细微频率偏移（`B1` 仅 `0.08 MHz`）。
5. **超出物理可辨识信噪比极限或硬件搜索带宽上限的区域**：
   - 如 `20201211m` `108.393 µs` 后、`20201214m` `83.555 µs` 后属光学/硬件信噪比极限；`20201214m` 的 `6.40 GHz` 平台在 `6 GHz` 搜索上限下任何算法都不可见（须用户将上限调整至 `8 GHz`）。

---

## 二、全 14 通道实测汇总与逐点差异分类

### 1. STFT 对照组 vs M4 关键指标（全 14 通道 / `9,475` 主中心，`[50 MHz, 6 GHz]`）

数据来自 [method_summary_all14.csv](../../../artifacts/TASK-024/study/tables/method_summary_all14.csv)：

| 方法 | 全集发布 (`/9475`) | `decline` (`/699`) | `weak_signal` (`/624`) | `onset` (`/69`) | `stationary` (`/3024`) | 非 CW `noise` (`/768`) | 邻帧 `>250 MHz` 跳变 | `decline` 25.6 ns $R^2$ 中位 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `B1` (512 pt 去均值) | 5,397 | 667 (95.4%) | 523 (83.8%) | 62 | 49 | 132 | 21 | 0.591 |
| `B+S` (B1 + 256 pt S) | 5,351 | 658 (94.1%) | 492 (78.8%) | 63 | 37 | 149 | 37 | 0.604 |
| `STFT_12p8ns` | 5,344 | 663 (94.8%) | 519 (83.2%) | 62 | 51 | 132 | 9 | 0.600 |
| `STFT_25p6ns` | 5,097 | 495 (70.8%) | 470 (75.3%) | 57 | 95 | 121 | 5 | 0.784 |
| `STFT_25p6ns_quad` | 5,134 | 496 (71.0%) | 470 (75.3%) | 57 | 108 | 121 | 5 | 0.783 |
| `STFT_38p4ns_quad` | 4,857 | 332 (47.5%) | 452 (72.4%) | 49 | 96 | 113 | 1 | 0.880 |
| **`M4_full`** | **5,600** | **689 (98.6%)** | **531 (85.1%)** | **59** | **72** | **151** | **7** | **0.823** |
| `M4_no_chirp` | 5,557 | 670 (95.9%) | 535 (85.7%) | 59 | 70 | 156 | 9 | 0.597 |
| `M4_no_cfar` | 5,719 | 689 (98.6%) | 531 (85.1%) | 59 | 155 | 190 | 7 | 0.823 |
| `M4_no_lowfreq_floor` | 5,740 | 689 (98.6%) | 531 (85.1%) | 59 | 200 | 151 | 7 | 0.823 |
| `M4_no_path_gap` | 5,915 | 690 (98.7%) | 547 (87.7%) | 59 | 239 | 249 | 61 | 0.819 |

### 2. B1 vs M4 逐点互斥差异分类（`9,475` 主中心全覆盖）

数据来自 [b1_vs_m4_point_taxonomy.csv](../../../artifacts/TASK-024/study/tables/b1_vs_m4_point_taxonomy.csv)：

- `both_agree_50MHz`：**5,180**（54.67%）
- `both_rejected`：**3,795**（40.05%）
- `m4_added_cw_or_lowamp_ambiguous`：**186**（1.96%，主要为晚时 CW 138 帧与静态弱窄带 22 帧）
- `both_disagree_50_250MHz`：**99**（1.04%）
- `m4_added_strong_raw`：**81**（0.85%）与 `m4_added_weak_coherent`：**16**（0.17%）
- **`m4_dropped_strong_short_risk`（显式疑似误伤审计）**：**72**（0.76%，其中 `stationary/noise` 53 帧、`onset` 4 帧、`rebound` 1 帧、`unknown` 10 帧、`weak_signal` 4 帧）
- `both_disagree_gt250MHz`：**38**（0.40%，主要集中于 `20221017a` `unknown`、`20260607` 晚时双支路及 `20260630-1/2` 竞争 CW）
- `m4_dropped_weak_or_artifact`：**8**（0.08%）

---

## 三、Research GUI「STFT vs M4 对比工作区」与 Windows 发布交付

### 1. 架构与核心交互能力
- **单一数据源纯科学核心**：`src/dps_studio/core/stft_m4/` 完全独立于 GUI、`matplotlib`、`scripts/`、`artifacts/` 与 `data/raw/`，对任意均匀采样真实 `SignalRecord` 即开即算；与 TASK-023 冻结 `B1`/`M4` 逐值精确一致（含 `NaN` 位置），经按唯一帧复用原窗与去势计算，将长记录耗时压低 **22%–35.5%**，并支持批次级合作取消与 `0–100%` 实时进度回报。
- **第 4 工作区无缝集成**：在 `ResearchMainWindow` 工具栏工作区下拉菜单新增 **`STFT vs M4 对比`**（索引 3，不破坏原有 0/1/2 模式）：
  - 支持打开任意外部 CSV/DAT/TXT 文件，一键异步计算 `B1`、`M4` 及可选 `25.6 ns` 等时长 STFT 对照，运行中支持随时取消；
  - 支持 **左右并排 / 上下并排 / 单图叠加** 三种排布，三幅主图 **严格 X/Y 双向同步联动**，默认强制共用同一 `B1` STFT 底图与锁定 dB 色标（零视觉误导），亦支持显式切换并标注「右底图：M4 白化相干响应（独立量纲）」；
  - 支持一键切换 **`仅 B1` / `仅 M4` / `叠加对比` / `差异高亮`**，默认保留 **被拒绝点 (`×`)**、支持切换 **原始候选 (`·`)**、**M4 次支路** 与 **25.6 ns STFT**；
  - 自动发现关注区域（全部差异、M4 新增弱信号、大频差分歧、疑似误伤、起跳/阶跃边界、高调频区）并支持 `±120 ns` / `±30 ns` 快速局部放大；
  - 点选任意帧即同步刷新下方 **单帧原波形检验台**（`±16 ns` 去势残差叠加 B1/M4 拟合，或原始电压叠加基线/阶跃/触轨红点）及并排数值证据表与中文决策原因；
  - **严格波长门控单位**：默认锁定显示 **频率 (`GHz`)**；仅当用户显式勾选「已确认可靠真空波长」并输入有效正有限波长后，方可按法向反射公式 $v = \lambda_0 f / 2$ 切换 **表观速度 (`m/s`)** 并显式标注「未做窗口/角度修正」。

### 2. Windows PyInstaller `onedir` 发布与真 EXE 8 组成功/失败截图验收
- **正式发布包**：`release/TASK-024/PDV_Studio_Research/`（**452 文件，230.09 MiB**，顶层仅 `PDV Studio Research.exe` 与 `_internal/`，PYZ 完整含 16 个对比核心与 GUI 模块，已核验排除 `data/raw`、`artifacts`、`scripts`、`matplotlib`、`dps_studio.research`）。
- **干净环境实机启动烟测**：在仅保留 Windows 系统 `PATH`（无 Conda / `PYTHONPATH`）的环境下实机启动 `PDV Studio Research.exe --startup-smoke-test`，确认 `event_loop_entered=true`、`window_visible=true`、`window_exposed=true`，全部 Qt/Shiboken/SciPy 运行路径均来自 `_internal/`。
- **8 张真实 EXE 窗口截图（已由 Gemini Neon 逐张目视审查通过，三图坐标与左右色标均逐值精确同步）**：
  - 成功案例 1–5：`exe_01_20201211m_weak_decline_win.png`（弱尾同时胜过 B1 与 25.6 ns STFT）、`exe_02_20221017a_weak_tail_win.png`（高调频弱尾连续恢复）、`exe_03_20260630-1_ch2_competing_cw_win.png`（CW 竞争保持主支路并曝光次支路）、`exe_04_20201214m_onset_and_8ghz.png`（拒绝起跳假低频 + 8 GHz 恢复 6.40 GHz 平台）、`exe_05_ch3_cfar_weak_and_noise.png`（弱尾补全与震后 CA-CFAR 抑噪）。
  - 失败/误伤/争议案例 6–8：`exe_06_20260630-1_ch1_fail_preonset_1p83ghz.png`（静态 1.83 GHz 微弱窄带敏感度反噬）、`exe_07_20260630-1_ch1_fail_overreject_r2_0989.png`（`R²=0.989` 清晰反弹帧因触轨前侧 `pre_edge_side_veto` 误伤）、`exe_08_20260607_ch2_fail_dual_branch_velocity_1366.png`（`1366×768` 紧凑屏 + 显式确认 1550 nm 表观速度 + 晚时双支路切换滞后争议）。

---

## 四、测试、静态检查与仓库边界核验

- **定向核心 + 科学验证 + GUI 测试**：`tests/unit/test_task024_study.py`、`tests/unit/test_task024_stft_m4_core.py`、`tests/unit/gui/test_task024_compare_workspace.py` 共 **21 passed**。
- **全量 Research GUI 回归**（`scripts/dev/check_gui.py --task TASK-024`）：**28 模块 / 231 项全通过**（含全部 27 个既有 GUI 模块与新增对比工作区）。
- **静态检查与打包门禁**：`ruff check` 零告警；`mypy --strict --explicit-package-bases`（226 个源文件）零错误；`scripts/build/check_build_inputs.py` 通过；`scripts/maintenance/check_repo_hygiene.py`（工作树与暂存区）通过。
- **边界保护**：`data/raw/`（全文件 SHA-256 不变）、Production 仓库（`D:\Code\Python_Projects\DPS_Studio`）、`core/physics/`、`core/analysis_profiles.py`、`configs/`、`AGENTS.md`、`.gitignore` 与 `scripts/research/task023/` 均保持只读零改动。
