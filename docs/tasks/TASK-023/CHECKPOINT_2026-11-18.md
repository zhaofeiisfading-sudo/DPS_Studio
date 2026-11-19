# TASK-023｜阶段进度暂存（2026-11-18）

- **状态**：PAUSED（Phase 0 真实数据物理诊断完成；Phase 1 方案与 Codex 指令已就绪，待明日启动/续跑）
- **仓库**：`D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN`
- **分支 / HEAD**：`codex/research_2/global-path-ridge-v2` / `07416ffd79a00ea7436553f8967ee6a078b218df`
- **协同分工**：Gemini Antigravity（首席研究员 / 方案设计 / 独立审核） + Codex CLI（默认 `gpt-6.2-sol`, `xhigh`）

---

## 1. 今日已完成（Phase 0：真实波形物理机制与既有失败诊断）

全部结论均直接来自 `data/raw/`（10 文件 / 14 通道）与冻结 `TASK-017/020` 实测数据对照，未使用合成信号作为结论依据。

1. **仓库与边界核查**
   - `git status` 任务开始前干净；确认另有一项 `task023_hotfix` Codex 进程作用于独立 Production 仓（`D:\Code\Python_Projects\DPS_Studio`），未触碰 Production 或 `data/raw/`。
   - 验证项目 Python 3.12 环境：`D:\miniconda3\envs\dps-studio\python.exe`（Python `3.12.13`）及 `pwsh`（PowerShell `7.7.0`）可用；`scripts/dev/run.ps1 -Task TASK-023` 正常。

2. **实测信号四类关键物理与采集特征（直接实测统计）**
   - **8.5 GHz 硬件通带与有色噪底**：全部 14 路在 ~8.5 GHz 处存在急剧模拟带宽截止（带外降约 20–35 dB）；`[0.05, 8] GHz` 内噪底显著有色（`20201210m` `[0.05–1 GHz] = -4.3 dB` vs `[4–8 GHz] = -20.1 dB`；`20221017a` 前缀 1–2.5 GHz 干扰带 `-5.3 dB`；`ch3` `<1 GHz = -34.2 dB` vs `1–8 GHz = -27.3..-27.9 dB`）。
   - **ADC 削波与同源双增益自然对照**：`20260630-1/2`、`20260701`、`20260607` 的两通道实测互相关达 `0.954–0.992`（分别为高增益削波通道与低增益未削波通道）；尾段（后 25%）跨通道互相关 `0.823–0.987`（`20260630-1` 共峰 `0.5096 GHz`、`20260630-2` 共峰 `0.9440 GHz`），证实晚期窄带 CW 支路是物理光学信号而非单路噪声，但在算法中仍严格保持单通道独立输入。
   - **TASK-020（`B1`/`S2`）失锁根因定位**：
     - 起跳阶跃/脉冲劫持：`20201210m`（`q=2304`, `0.061 GHz`）、`20201211m`（`q=9600`, `0.223 GHz`）、`20201214m`（`0.054–0.091 GHz`）。
     - 弱信号与下降段丢失：`20201211m`（`weak_signal 0/28`、`decline 20/36`）、`20201214m`（`weak_signal 0/19`、`decline 40/53`）、`20221017a`（`weak_signal 1/41`，部分帧 `raw_tone_r2 = 0.468–0.524` 仅因对抗前缀干扰 `bg_gain = 4.1–5.3 < 6 dB` 被 `S` 拒绝，同时 `s00`/`noise` 存在 16 次跳变）、`20231019-ch1`（`weak_signal 17/50`）。
   - **采样率失配与实测相干尺度（`probe_coherence.py`）**：
     - 40 GS/s 与 80 GS/s 若固定采样点数（如 `512` 点），物理时长相差 2 倍（`12.8 ns` vs `6.4 ns`）。
     - 实测将局部去势与调频率匹配积分窗口扩展至物理时长 `25.6–38.4 ns`（`1536 @ 40G` / `2048 @ 80G`），弱信号相干 SNR 提升 `+6.8` 至 `+8.9 dB`：
       - `20201211m_ch1` `[108.31, 108.45] us`：`8.7 → 15.5 dB`（恢复 `1.17 → 0.74 GHz` @ `-5..-10 GHz/us`）
       - `20201214m_ch1` `[83.48, 83.60] us`：`13.6 → 21.0 dB`（恢复 `1.38 → 0.84 GHz`）
       - `20221017a_ch1` `[88.24, 88.31] us`：`10.2 → 19.1 dB`（恢复 `3.32 → 2.79 GHz` @ `-5..-15 GHz/us`）
       - `20231019-ch1_ch1` `[90.02, 90.11] us`：`13.5 → 21.3 dB`（恢复 `0.92 → 1.25 GHz` @ `+5..+10 GHz/us`）

---

## 2. 已设计待执行的 Phase 1 筛选路线（5 路典型困难通道）

已拟定规范并落盘于 `artifacts/TASK-023/tmp/phase1_prompt.md`，对比 `B0` / `B1` / `B+S` 与 3 类独立新范式：

1. **`M1_sw_wpd_tbd`**：阶跃自适应局部线性去基线（含 $\pm 3.2\text{ ns}$ 中心能量门防未来泄漏） + 宽带噪底估计白化 + 物理时长多尺度（`6.4 / 12.8 / 25.6 / 38.4 ns`）**分段半窗相位相干交叉功率（Split-Half Phase Coherence）** + 稠密二阶运动学 Viterbi Track-Before-Detect（含显式 `OFF` 断轨与离散 `JUMP` 切换）。
2. **`M2_mc_decomp`**：时域形态学慢基线/脉冲分离 + ADC 削波删失加权拟合（Rail-Censored Declipping）+ 正交多分量啁啾匹配追踪与谐波/持续窄带杂散辨析。
3. **`M3_ss_demod`**：仅从高置信度相干岛起跳，双向 I-Q 相位状态解调（含低频实信号共轭镜像修正、自适应带宽扩展与相位失锁即断轨机制）。

**今日 Codex 启动排查记录**：
- 首次启动 `task-111`（`codex exec -m gpt-6.2-sol -c model_reasoning_effort=xhigh`）在读取技能后因 `codex_models_manager::manager: failed to refresh available models: request timed out` 长期无进度，已于 11:18 安全终止并清理空输出文件与子进程（PID 6952 / 40776），源码/数据零修改。

---

## 3. 明日续跑步骤

1. 先核对 `git status --short` 及网络连通性，确认无冲突进程。
2. 重新触发 Phase 1（`artifacts/TASK-023/tmp/phase1_prompt.md` 已就绪）：
   - 建议启动 `codex exec` 时显式关闭与本任务无关的外部 MCP（如 `solidworks`、`origin-pro`、`playwright`、`github`、`semantic-scholar`、`context7`、`fetch`），或拆分为“算法核心与单测” + “5 通道实测对照与局部放大图”两个快速子回合，避免长回合超时挂起。
3. Gemini 独立审核 Phase 1 源码、diff、`pytest`/`ruff`/`mypy` 及逐通道局部放大 PNG 图像，淘汰无效方向，仅保留真正具备增益的方法进入 **Phase 2（机制打磨/融合或智能分段验证）** 与 **Phase 3（全部 10 文件 / 14 通道扩展验证 + `2026xxxx` 削波/未削波自然对称性检查）**，最后完成报告、Obsidian 日志与授权的 `git commit` / `git push`。
