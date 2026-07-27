# DPS Studio 组会汇报重制版来源映射

## 使用原则

- 所有实验信号、STFT、脊线和速度曲线均来自当前仓库真实数据或真实运行输出。
- 未使用 image generation；未手画实验曲线；未为美观平滑、插值、重采样或修改数值。
- `data/raw/20260607.csv` 只读使用，SHA-256：
  `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`。
- 模板 `presentations/Sigapore_presentation.pptx` 只用于观察暖白背景、砖红强调和留白气质；未复用其正文、校徽、章节、版式结构或格式。
- 初版 `presentations/group_meeting/20260725/DPS_Studio_组会汇报_20260725.pptx`
  只用于识别需要避免的问题：机械小框、粗箭头、卡片堆叠和宣传式语言；未复制其页面。

## 逐页来源

### Slide 1

- 题目和汇报主线：用户提供的重制任务说明。
- `V(t) / S(t,f) / v_app(t)`：
  - `src/dps_studio/core/models/signal.py`
  - `src/dps_studio/core/time_frequency/stft.py`
  - `src/dps_studio/core/physics/velocity.py:23-31`
- 无实验图片。

### Slide 2

- “参数不透明、人工选择难复现、假峰缺少证据、原始数据安全风险”：
  用户提供的重制任务说明，以及仓库中对旧流程证据链的既有审计背景。
- 旧软件只作为问题背景，不展示或复用旧软件截图，不把未核验细节写成事实。

### Slide 3

- 数据安全要求：
  - `AGENTS.md`：不得覆盖原始数据、内部使用 SI、表观/修正速度分开、无可靠信号返回 NaN 和质量标记。
  - `src/dps_studio/core/models/signal.py:28-63,115-124`
- 算法复刻与可信判断的分层：当前 `core` 模块与真实 production 输出的能力边界。
- GUI 尚未完成：
  - `src/dps_studio/gui/__init__.py` 仅含 package docstring。
  - `src/dps_studio/cli.py` 当前只提供 `--version`。

### Slide 4

- 依赖及工具：
  - `pyproject.toml:11-27`
  - 数值：NumPy、SciPy、pandas。
  - 绘图：Matplotlib。
  - 后续 GUI：PySide6、PyQtGraph。
  - 检查：pytest、Ruff、mypy。
- 结论只针对本仓库实际依赖，不扩展为 Python 通用优点。

### Slide 5

- 当前工作树处理顺序：
  - `src/dps_studio/core/workflow/analysis.py:97-146`
  - `compute_stft` → `extract_peak_ridge` → `refine_peak_ridge_subbin`
    → `convert_ridge_to_apparent_velocity`
    → `assess_ridge_spectral_quality`
    → `assess_ridge_continuity`
- 正式导出及 manifest：
  - `scripts/production_outputs.py`
  - `outputs/production_runs/run_20260724_004901_103968/run_manifest.json`
- LiF、折射率和入射角修正未实现：
  - `src/dps_studio/core/physics/velocity.py:23-31`
- 双通道当前独立分析、没有自动择优或融合：
  - `outputs/production_runs/run_20260724_004901_103968/*/quality_summary.csv`
  - 对应两通道独立目录和 CSV。

### Slide 6

- `SignalRecord` 的 SI、只读数组与采样信息：
  - `src/dps_studio/core/models/signal.py:28-63,115-180`
- 非均匀采样不静默处理；标准 STFT 明确拒绝：
  - `src/dps_studio/core/time_frequency/stft.py:33-48`
- 真实图片：
  - 交付资产：`assets/real/raw_voltage_dual_channel.png`
  - 原始来源：`data/raw/20260607.csv`
  - 生成脚本：`generate_redesign_assets.py::_raw_voltage_plot`
  - 处理：只选择 `[-0.12, 0.28] μs` 显示窗；无平滑、插值和重采样。
- 实际显示窗统计：
  - channel 1 峰峰值：`0.159933143 V`
  - channel 2 峰峰值：`0.396908417 V`
  - 峰峰值比：`2.4817146062`
  - 统计记录：`assets/asset_stats.json`

### Slide 7

- 真实图片：
  - 交付资产：`assets/real/stft_balanced_channel1.png`
  - 原始来源：
    `outputs/production_runs/run_20260724_004901_103968/balanced/pdv_channel_1/stft_analysis_band_with_ridge.png`
- 图中数据与标记：
  - 横轴：相对事件时间。
  - 纵轴：频率。
  - 颜色：相对 STFT 幅值。
  - 白线：refined candidate ridge。
  - 黄虚线：搜索下限。
- STFT 实现：
  - `src/dps_studio/core/time_frequency/stft.py:74-87`
  - `boundary=None`、`padded=False`，未添加边界填充。

### Slide 8

- 参数定义：
  - `src/dps_studio/core/analysis_profiles.py:136-168`
  - Balanced：Hann、768、640 overlap、128 hop、4096 nfft、0.05–2.0 GHz。
  - High time resolution：Hann、512、384 overlap、128 hop、4096 nfft、0.05–2.0 GHz。
- 运行配置：
  - `configs/demo_dual_profile.toml:17-31`
  - `outputs/production_runs/run_20260724_004901_103968/balanced/profile_manifest.json`
- 数据采样率与窗长：
  - 采样率约 `40 GHz`。
  - Balanced 窗长约 `19.2 ns`。
  - High time resolution 窗长约 `12.8 ns`。
  - hop 约 `3.2 ns`。
- 代码截图：
  - `assets/code/analysis_profiles_balanced_excerpt.png`
  - 原始文本：`src/dps_studio/core/analysis_profiles.py:136-145`
  - 生成脚本：`generate_redesign_assets.py::_code_excerpt`
- “nfft 加密频率网格不等于真实分辨率无限提高”是 STFT 参数解释；不把零填充误写成新增物理信息。

### Slide 9

- 公式和边界：
  - `src/dps_studio/core/physics/velocity.py:23-31`
  - `v_app = λ₀ f_b / 2`
  - 单边 STFT 只提供非负拍频，因此结果为无符号 magnitude。
  - 未应用入射角、折射率、LiF 或其他修正。
- 波长：
  - `configs/demo_dual_profile.toml:21-22`
  - `1.55e-6 m` 明确标记为 demonstration value，尚未对照实验记录。
- apparent / corrected 分离：
  - `src/dps_studio/core/physics/models.py`
  - 当前没有 corrected velocity 字段。

### Slide 10

- 左图：
  - `assets/real/stft_balanced_channel1.png`
  - 原始来源：
    `outputs/production_runs/run_20260724_004901_103968/balanced/pdv_channel_1/stft_analysis_band_with_ridge.png`
- 右图：
  - `assets/real/velocity_balanced_channel1_event.png`
  - 原始来源：
    `outputs/production_runs/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_event_detail.png`
- 两图来自同一真实 run、同一 profile、同一 channel。
- 图中“display-only bridge”和“assumed pre-event zero”只用于显示；
  正式 apparent velocity 的非 candidate 位置保持 NaN：
  - `src/dps_studio/core/workflow/analysis.py:210-228`
  - `outputs/production_runs/run_20260724_004901_103968/balanced/profile_manifest.json`

### Slide 11

- 双通道真实比较图：
  - `assets/real/two_channel_latest_candidates.png`
  - 原始来源：
    - `outputs/production_runs/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity.csv`
    - `outputs/production_runs/run_20260724_004901_103968/balanced/pdv_channel_2/apparent_velocity.csv`
  - 生成脚本：`generate_redesign_assets.py::_two_channel_plot`
  - 仅绘制 `quality_flag == candidate` 的 `apparent_velocity_m_s`；
    未平滑、插值、择优、平均或融合。
- 实际数值：
  - 首个候选：channel 1 `537.9387 m/s`；channel 2 `531.8331 m/s`。
  - peak-to-background median：`52.5301 / 55.7844 dB`。
  - peak-to-competitor median：`13.2956 / 19.8805 dB`。
  - 来源：`balanced/quality_summary.csv` 与 `assets/asset_stats.json`。
- dB 量只称为描述性谱对比度，不称 SNR，不设置自动可信阈值。

### Slide 12

- 已实现：
  - 只读数据模型：`src/dps_studio/core/models/signal.py`
  - STFT：`src/dps_studio/core/time_frequency/stft.py`
  - 脊线与精修：`src/dps_studio/core/ridge/peak.py`、`refinement.py`
  - 表观速度：`src/dps_studio/core/physics/velocity.py`
  - 双通道 workflow：`src/dps_studio/core/workflow/analysis.py`
  - production 输出：`scripts/production_outputs.py`
- 初步实现：
  - 谱质量与连续性证据：
    `src/dps_studio/core/ridge/spectral_quality.py`、`diagnostics.py`
- 未完成：
  - LiF / corrected velocity：`src/dps_studio/core/physics/` 中不存在。
  - GUI：`src/dps_studio/gui/__init__.py` 仅为占位。
  - 完整 CLI：`src/dps_studio/cli.py` 当前只支持版本信息。

### Slide 13

- 弱信号和分支连续性问题：
  - `src/dps_studio/core/ridge/peak.py` 当前为逐帧峰值搜索。
  - `src/dps_studio/core/ridge/diagnostics.py` 提供证据，但未形成最终可信规则。
- 参数敏感性：
  - `src/dps_studio/core/analysis_profiles.py:1-11,136-168`
- 双通道无正式择优：
  - 最新 run 的两通道分别输出，没有 selection / averaging / fusion。
- 波长与 LiF 未核验：
  - `configs/demo_dual_profile.toml:21-22`
  - `src/dps_studio/core/physics/velocity.py:23-31`
- GUI 和打包未完成：
  - `src/dps_studio/gui/__init__.py`
  - `pyproject.toml` 中虽列出 PyInstaller，但没有已交付的安装包证据。

### Slide 14

- 下一阶段顺序来自用户给定的重制任务说明，并按当前依赖关系核对：
  谱线连续性 → 起跳/平台/弱信号判据 → 双通道择优 → 实验条件与修正 →
  GUI → 打包与用户测试。
- AI 的边界：只作为后期辅助识别，不生成、替换或决定最终速度曲线。
- 本页是计划，不作为当前成果来源。

### Slide 15

- 总结仅覆盖当前可证实状态：
  - 真实原始数据到表观速度的基础数值链已存在。
  - 当前需要证明脊线物理分支正确。
  - 后续需要非 AI 约束、双通道证据、波长/LiF 核验、GUI 和部署。
- 事实来源综合自 Slide 5–14 的当前源码、配置和真实输出。
