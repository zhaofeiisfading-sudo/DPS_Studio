# TASK-001：PDV 残差结构、相关噪声与超带宽频率可辨识性

执行日期：2026-10-28。分支：`research/bandwidth`。基线提交：`76f90325`。

**总判决：MIXED。真实硬件超带宽结论：REQUIRES_EXPERIMENTAL_CONFIRMATION。**

冻结的独立噪声 AR(1) 似然在匹配的单频合成分布中提高了可靠输出比例；独立测试同时表明，它不能单靠信号存在性检验解决噪声谱变化、快速变频和物理支路识别。当前原型不适合直接用作 Production 的频率质量门。真实参考波形保留明显相关残差，其来源仍为 **UNKNOWN**。本任务到此停止，不启动 TASK-002。

## 1. 工程审计与证据索引

工作树为 `D:\Code\Python_Projects\DPS_Studio_BANDWIDTH`；开始时 `git status --short`、`git diff` 均为空，分支符合要求。读取了 `AGENTS.md`、`README.md`、`.gitignore`、`pyproject.toml`、`environment.yml` 和 `scripts/bandwidth_env.ps1`。Python 使用已有的 `D:/miniconda3/envs/dps-studio/python.exe`，版本 3.12.13；默认 PATH 中的 Python 3.9 没有用于本任务计算。没有安装依赖。

当前代码确有以下接口，研究基线直接调用它们：

- `core/time_frequency/stft.py::compute_stft`：单边 Hann STFT，无边界填充。
- `core/ridge/peak.py::extract_peak_ridge`：逐帧最强峰，无时间连续性先验。
- `core/ridge/refinement.py::refine_peak_ridge_subbin`：三点对数幅值精修。
- `core/ridge/spectral_quality.py::assess_ridge_spectral_quality`：峰/背景和峰/竞争成分幅值对比。
- 对应现有测试：`test_stft.py`、`test_ridge_refinement.py`、`test_ridge_spectral_quality.py`。

现有 Production TOML 包含面向既有记录的演示波长、搜索频带和开发门限；本研究没有把这些配置视为新实验的已知物理参数。没有引入旧 P3、VP_tone、VP_chirp，也没有复制旧 Research 数据或算法。用户给出的 TASK-007 数值仅为研究背景，未纳入本任务实测结果。

所有产物均在 `results/task001_bandwidth/` 下，继续被 Git 忽略：

|目录|证据范围|
|---|---|
|`run_20261028_main01/`|冻结校准、独立合成测试、全部 23,744 行评价、5,936 条数字波形、归因诊断与图件|
|`run_20261028_reference01/`|`docs/原始数据.csv` 的只读诊断、显式列/单位映射、SHA-256、真实候选与残差图|
|`run_20261028_assessment01/`|最终四份轻量报告、补充错误率、oracle 诊断、边界审计与测试日志|
|`literature_20261028/`|四篇论文的完整 Crossref JSON、核验台账、Allison 开放 HTML 及解析文本|

最终阅读入口为 `run_20261028_assessment01/README_TASK001.md`；方法与配置见本报告和 `run_20261028_main01/config.json`。初次合成运行的 `REAL_DATA_UNAVAILABLE` 仅反映当时对空 `data/raw` 的检查；随后发现的文档参考波形保存在另一独立诊断目录，旧结果没有被覆盖。最终数据状态为 **OBSERVATIONAL_REFERENCE_ONLY**，不是“整个工作树没有波形”。

## 2. 问题、模型与拒绝机制

### 2.1 连续信号与采集链

合成实信号使用相位约定

\[
s(t)=A(t)\cos\{2\pi[f_0t+\tfrac12\dot f t^2]+\phi_0+\phi_m(t)\}
      +A_c\cos(2\pi f_ct+\phi_c).
\]

采集顺序为连续 fringe → 连续模拟 Butterworth 接收链 → 下游电子噪声 → ADC 采样 → 量化。模拟带宽定义为幅值 −3 dB 点，采用一阶/四阶模型：

\[
|H_p(f)|=[1+(f/B)^{2p}]^{-1/2},\quad B=3\times10^9\ {\rm Hz},\quad p\in\{1,4\}.
\]

平稳分量通过解析的复数 `H(j2πf)` 计算稳态输出，包含幅值和相位响应；变频/调制分量通过 8 倍过采样的连续状态方程 ZOH 离散近似求解，在 ADC 之前施加模拟链并舍去启动段。诊断例与 32 倍过采样比较，相对 RMS 差异为 1.51–1.57%；16 倍与 32 倍之差为 0.50–0.52%。这一检查只覆盖列出的诊断例，不能视为整个参数空间的收敛证明。平稳主扫描不受这项数值近似影响。

噪声在模拟信号响应之后、ADC 之前注入：白噪声采用独立孔径噪声理想化；相关噪声采用平稳 Ornstein–Uhlenbeck 过程在 ADC 时刻的精确采样，`rho=exp(-dt/tau)=0.85`。递推只是连续 OU 的精确采样表达。该设定没有建模所有上游光学/电子噪声经过实际探测链的情况，尤其不证明真实链是 OU 或 AR(1)。默认主扫描使用理想无量化 ADC；另设 2 mV 步长、零随机噪声的弱信号量化抹除反例。没有模拟全量 ADC 非线性、饱和、时钟抖动或真实仪器噪声。

采样率为 `20e9 Hz`，Nyquist 为 `10e9 Hz`；公共数字搜索频带为 `0.2e9–9.5e9 Hz`。模拟响应带宽、Nyquist、噪声 PSD、量化和 FFT 网格分别记录。光学波长、光学频偏及真实仪器带宽均为 `UNKNOWN`，不输出任何速度，也不应用角度或窗口修正。

### 2.2 两个基线与一个噪声建模方案

`stft_peak` 为既有 STFT 的逐帧最强离散峰，保留全部候选；`stft_gate` 在同一 STFT 上精修，要求峰/竞争成分 ≥3 dB，峰/背景门限由独立纯噪声校准。背景排除半宽为 `2fs/N`，使用现有质量接口计算。这是本任务独立定义的研究门控，**不声称等于旧 Research 或 Production 的完整门控逻辑**。没有放宽残差相关性门限；残差 ACF 在本研究中用于诊断，不直接作信号存在性判据。频谱幅值对比不是正式 SNR。

新方案为单频广义似然比检验，另保留 iid 噪声消融：

\[
H_0:d=c+e,\qquad
H_1:d=c+a\cos(2\pi ft)+b\sin(2\pi ft)+e.
\]

独立噪声训练确定 `rho` 和创新标准差 `sigma_e`，之后冻结；不从被检测帧或拟合残差重估。协方差为

\[
C_{ij}=\frac{\sigma_e^2}{1-\rho^2}\rho^{|i-j|}.
\]

相应精度因子为 `(Wx)_0=sqrt(1-rho²)x_0`、`(Wx)_k=x_k-rho*x_(k-1)`。**数据与信号设计矩阵同时变换**，包括 DC 列。对线性系数作投影后计算

\[
T(d)=\max_{f\in\mathcal B}
\frac{\operatorname{RSS}_0-\operatorname{RSS}_1(f)}{\sigma_e^2}.
\]

使用公共 `4N` 频率网格搜索，并在最强网格附近作局部精修。完整搜索统计量以独立空假设数据标定，避免把选峰后的值当成预先指定频率的卡方检验。`iid_glrt` 使用同一独立训练集的边际方差及 `rho=0`，其相关噪声组是明确的失配消融。

每个噪声/窗长组有 499 条空假设校准波形，名义 `alpha=0.01`，取第 `ceil((M+1)(1-alpha))` 个顺序统计量，严格大于阈值才接受。给定冻结训练模型，在校准/测试空假设可交换时，秩论证提供边际名义误接受率控制；**不保证每个固定校准集的条件错误率，不保证噪声谱漂移后的错误率**。所有方法均未得到测试真值或目标频带先验。

### 2.3 输出、不确定度与物理含义

完整评价 CSV 分开保存 `candidate_frequency_hz`、`accepted_frequency_hz`、`quality_flag`、`uncertainty_hz` 和 `provenance`。检出状态为 `COMPONENT_DETECTED_BRANCH_UNREVIEWED`。这里的 accepted 表示数字成分通过检验，不能读成目标界面已确认，更不能读成独立验证的物理速度。

`uncertainty_hz` 始终为 NaN。另存单频局部 Fisher 曲率标准差、名义 95% 区间、独立信号校准后的诊断区间。局部标准差将线性幅值/相位/DC 作为干扰参数投影掉；它忽略模型选择错误、协方差参数不确定性及模型失配。每组另用 128 条独立信号校准波形，对接受样本的标准化频率误差标定区间倍率，不使用测试标签。该条件校准不构成所有信号类型的覆盖保证。

## 3. 数据划分、指标与可重复运行

训练：每个噪声组 64×2048 个样本，两个组共 128 条独立噪声记录。空假设校准共 1996 条，区间校准共 512 条；其种子流与最终测试分离。

独立测试含 5936 条波形：3072 条平稳单频、2000 条纯噪声、864 条特殊条件。主扫描为 `N={256,512}`、白/OU 噪声、一/四阶响应、输入幅值 `{0.04,0.12} V`、`f/B={0.25,1,1.6,2.6}`，每格 48 次独立随机相位/噪声。特殊条件为快速 chirp、AM、相位调制、竞争频率、H=0、量化抹除、13 GHz 欠采样混叠、噪声谱变化和无目标的相干干扰，各 96 条。

每条测试波形只取一个观测窗，因此合成统计的单位是独立完整波形。所有方法使用完全相同的数字波形。全部失败和拒绝样本保存在 `evaluation.csv`，数字波形保存在 `heldout_waveforms.npz`，不删除错峰。训练、校准和测试种子、模型参数、库版本、线程设置与源文件 SHA-256 均记录于配置。

正确频率容差预设为 `fs/(4N)`，即 19.53125 MHz / 9.765625 MHz；中心频率真值来自合成模型，不随获胜频率改变。总帧正确率分母包含拒绝；条件 RMSE/MAE 包含所有已接受目标帧的错误峰。竞争支路另报；无目标/丢失信息条件下的接受另报。混叠案例同时记录数字 alias 正确和物理载频不可确认。

STFT 窗长为 12.8/25.6 ns，帧间隔也为 N/fs，因为此实验无重叠。FFT 网格为 fs/(4N)，这是零填充采样间隔；Hann 主瓣零到零宽度约 4fs/N，不能把网格加密称为真实分辨能力提高。参数化单频估计的精度也不等于相邻两个分量的可分辨间距。

## 4. 独立合成测试结果

下表针对 3072 条主扫描单频波形。超过 B 的正确率另以 1536 条超带宽单频波形为分母。

|方法|覆盖率|总帧正确率|已接受 RMSE / MAE（MHz）|纯噪声误接受 / 2000|超过 B 的正确率|
|---|---:|---:|---:|---:|---:|
|STFT strongest|100.00%|73.37%|2747.762 / 1263.721|2000（100%）|48.24%|
|门控 STFT|60.48%|59.99%|303.358 / 14.609|17（0.85%）|35.35%|
|iid GLRT|68.36%|67.77%|498.737 / 39.879|23（1.15%）|42.51%|
|AR(1) GLRT|84.11%|83.69%|203.682 / 10.469|24（1.20%）|67.51%|

RMSE 被少数严重错峰显著拉高，不能只展示 MAE 或只保留正确峰。AR(1) 接受的 2584 个单频样本中有 13 个超出频率容差。匹配纯噪声下，AR(1) 的 24/2000 对应精确 95% 区间 0.77–1.78%；门控 STFT 的 17/2000 为 0.50–1.36%。当前证据**没有证明误接受率不增加**，也没有在固定校准集上证明实际 FPR≤1%。

收益主要来自相关噪声组：AR(1) 单频正确率为 87.43%，门控 STFT 为 45.57%，iid GLRT 为 55.53%。白噪声组中 AR(1)/iid 分别为 79.95%/80.01%，符合协方差建模在白噪声下没有额外优势。与门控 STFT 的配对波形 bootstrap 差值为：白噪声 +5.53 个百分点，95% 区间 +4.43 至 +6.71；OU 噪声 +41.86 个百分点，区间 +39.52 至 +44.27。它们描述本任务固定合成混合分布，不可外推为真实 PDV 效应量。

主扫描的输入幅值和边际噪声 RMS 相同，并不意味着各频率的检测难度相同：OU 噪声功率集中于低频，频率局部背景不同；`residual_snr_db` 记录的是接收后信号功率/全部随机噪声功率，不能替代频率局部 SNR。完整 SNR/窗长/模拟响应分层见 `cell_boundary.csv`。

### 4.1 明确保留的反例

|条件（每项 96 条）|门控 STFT：接受 / 正确|AR(1)：接受 / 正确|判读|
|---|---:|---:|---|
|快速 chirp|6 / 2|95 / 1|单频检测通过但中心频率错误；检测不等于单频模型可信|
|相位调制|1 / 0|96 / 18|侧带/失配使候选偏离中心频率|
|强竞争频率|96 / 0|96 / 0|两者均 96/96 选错目标支路|
|噪声谱变化，无目标|12 / 0|90 / 0|冻结模型面对分布变化会严重误接受|
|H=0，仍有噪声|1 / 0|2 / 0|随机假阳性；没有恢复被模拟链抹去的真值|
|量化抹除|0 / 0|0 / 0|数字数组全零，新方案和门控基线均拒绝|
|13 GHz 混叠至 7 GHz|96 / 0|96 / 0|数字成分可以检出，模拟载频分支不唯一|
|无目标的相干干扰|96 / 0|96 / 0|真实存在的非目标分量不能由存在性检验识别为目标|

竞争与混叠属于物理身份信息不足；不能仅靠收紧单频存在性阈值解决。输出已经携带 branch-unreviewed 状态，报告中的“false physical recovery”计算的是将这些数字接受误读为目标真值时的错误率。

AR(1) 诊断区间在已接受单频上的实际覆盖率为 95.36%（未放大名义区间为 93.46%）；在全部已接受目标存在案例上下降到 86.59%，快速 chirp 为 0%。这些数据支持保持正式 `uncertainty_hz=NaN`，不能给真实数据附上看似精确的频率误差条。

### 4.2 条件辨识边界

定义格点通过条件为：正确率精确双侧 95% 区间下界≥90%，同噪声/窗长测试的观测空假设误接受率≤1%，且从最低测试频率开始连续通过。此条件只是预设网格上的经验筛选，空假设误差仍有有限样本不确定性，不能认证硬件或固定校准集的 FPR。

AR(1)、N=512 的连续通过上界如下；数值是已测格点，不是精确极限：

|噪声 rho|响应阶数|输入 A=0.04 V|输入 A=0.12 V|
|---|---:|---:|---:|
|0|1|4.8 GHz|7.8 GHz|
|0.85|1|7.8 GHz|7.8 GHz|
|0|4|3.0 GHz|4.8 GHz|
|0.85|4|3.0 GHz|4.8 GHz|

N=256 各格没有通过该联合准则，因为相应组观测空假设误接受率为 1.2%/1.8%，不能把“没有通过”解释为这些频率物理上不存在。最长窗、一阶响应在部分条件下到达网格最高的 2.6B；四阶衰减的结果更保守。真实 H(f) 未知，不能据此给真实示波器增加“软件带宽”。

计算耗时仅作工程量级参考：单频样本上共享 STFT/精修/质量接口均值约 1.366 ms，iid 似然约 1.717 ms，AR(1) 约 1.569 ms。STFT 两个方法记的是同一完整接口成本，非 strongest-only 的最小耗时；似然不含预建设计矩阵/训练/校准。完整合成入口实际用时 63.45 s。库版本、机器信息和单线程环境见配置。

## 5. 残差归因、数值失效与真实参考波形

### 5.1 合成归因

每种机制 20 次独立诊断，分别拟合单频、线性 chirp 和双频模型，记录 ACF、Welch PSD、季度窗功率比、残差 RMS 和参数。单频残差 lag-1 中位数为：白噪声单频 −0.017，OU 单频 0.844，白噪声加 AM 0.734，白噪声加 chirp 0.838，白噪声双频 0.690。因此接近旧报告的高相关数值可以由不同机制产生，相关系数本身不具有来源鉴别力。

双频模型使已知双频案例的中位相关降至 −0.001；OU 案例仍为 0.826，表明本组受控对照能部分区分漏拟合分量和持续随机相关。但更灵活模型也会降低无关噪声残差，不可仅凭残差变小确认真实成分。

初始局部 chirp 优化对较快 chirp 陷入局部极小值，虽报告收敛，残差 RMS 仍为 0.1032 V。另用**已知合成真值初始化**只作数值诊断，残差降至约 0.03507 V，lag-1 约 −0.045，拟合 chirp 中位数 `4.00314e16 Hz/s`。这个 oracle 检查不进入四种方法的任何得分/校准，不代表实用算法成功。它防止将局部求解失败误判为 chirp 模型在物理上不能解释该信号；更不能借它选择真实数据最优参数。

精度变换检查显示：OU 样本 lag-1 从 0.85045 降到 −0.00262，但正弦在 0.75/3/7.8 GHz 的幅值因子分别为 0.264/0.850/1.741。它改变信号与噪声的表征，必须同时变换设计，不能当作无影响的默认白化滤波。该可逆似然计算没有创造信息或反演未知 H(f)。

信号吸收反例：把 0.75 GHz 相干分量污染进“噪声训练”，rho 从 0.8504 偏到 0.9599，创新标准差从 0.01845 增至 0.03117 V，同一弱信号统计量由 30.41 压到 8.35。正式比较使用独立、无信号训练避免这一反馈；真实记录尚无经确认的独立噪声样本，不能照搬这个前提。

### 5.2 当前工作树真实数据状态

`data/raw` 只有 `.gitkeep`，四个旧 TASK-007 文件不在其中。全面检查发现 `docs/原始数据.csv`（3,792,364 字节），现有审计称它是 raw 的参考副本，现有用户手册第 305 行明确给出：80,000 行、3 列、逗号、无表头、时间列 0 为 s、信号列为 V。按此文档映射只读分析两通道。其原始实验来源未通过缺失的 raw 独立核对，标为 **OBSERVATIONAL_REFERENCE_ONLY**；它不是对旧四片段的复现。

采样率由时间列导出 `39,999,999,986.36 Hz`，Nyquist 约 20 GHz；不能把它当作 20 GS/s 合成链。每通道、每窗长均匀选取 48 个不重叠窗，共 192 个窗、576 次模型拟合。两窗长覆盖同一记录，不作为独立实验重复。真实窗长约 6.4/12.8 ns，FFT 网格约 39.06/19.53 MHz。

|通道|N|单频残差 lag-1 中位数|chirp|双频|
|---|---:|---:|---:|---:|
|ch1|256|0.8379|0.8295|0.8076|
|ch1|512|0.8367|0.8363|0.8161|
|ch2|256|0.9061|0.9023|0.7874|
|ch2|512|0.9223|0.9217|0.8092|

576/576 拟合残差的绝对 lag-1 均超过 0.3。双频模型降低部分残差能量，例如 ch2、N=512 的中位 RMS 从 0.002543 降至 0.001578 V，但相关性仍强。这个结果与“漏拟合成分可能贡献残差”相容，不足以确认电子噪声、AM、相位变化或滤波链中任何一项的独占归因。局部优化收敛标志也不保证全局最优。

没有经过实验确认的 noise-only 区间，没有独立文件级训练/测试，没有 H(f)、示波器型号/带宽、探测器/放大器响应、波长、光学频偏或独立频率真值。未将合成阈值迁移到参考波形；真实 `accepted_frequency_hz` 和 `uncertainty_hz` 均为 NaN。真实候选保留用于观察，不称为恢复频率或物理速度。

读取前后参考文件 SHA-256 完全一致：

`AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`

## 6. 文献核验与证据边界

查询数据库为 Crossref，端点 `https://api.crossref.org/works/{URL编码的DOI}`；四次原始 JSON 和准确作者列表均保存在文献目录，不以旧报告转述冒充原文。查阅范围如下：

|真实文献|DOI / 元数据|实际查阅范围与本任务用途|
|---|---|---|
|D. H. Dolan (2010), Accuracy and precision in photonic Doppler velocimetry, RSI 81(5), 053905|[10.1063/1.3429257](https://doi.org/10.1063/1.3429257)|核验元数据与摘要；摘要讨论采样率、噪声份额和分析时长对极限不确定度的影响。没有把它用于证明本原型阈值或真实超带宽性能。|
|D. H. Dolan (2020), Extreme measurements with Photonic Doppler Velocimetry (PDV), RSI 91(5), 051501|[10.1063/5.0004363](https://doi.org/10.1063/5.0004363)|核验元数据与摘要；确认综述主题。全文未成功获得，本任务不从未读章节推导仪器响应或具体修正。|
|D. Rife and R. Boorstyn (1974), Single tone parameter estimation from discrete-time observations, IEEE TIT 20(5), 591–598|[10.1109/TIT.1974.1055282](https://doi.org/10.1109/TIT.1974.1055282)|核验元数据；IEEE 页面被机器人检查阻挡，全文未读，不将任何相关噪声检测结论归给该文。本文使用的投影似然与 Fisher 表达为本任务明确列出的模型推导。|
|J. R. Allison et al. (2025), A Bayesian approach to time-domain photonic Doppler velocimetry analysis, RSI 96(8), 085203|[10.1063/5.0267409](https://doi.org/10.1063/5.0267409)|元数据与摘要核验，并查阅[开放作者全文](https://arxiv.org/html/2508.13695v1)的 II.2、II.3.3、验证与讨论部分。相关噪声假设、模型失配风险和先验依赖仅按实际内容解释。|

Allison 的相关噪声来源假设及其特定数据检验，不能证明本参考记录的相关残差来自电子链；其低信噪区间模型插值也不构成本任务中不存在数字信息的恢复证据。本任务未使用其先验速度轨迹填补信号。

## 7. 代码、复现与检查

新增文件（既有受跟踪文件未改）：

- `src/dps_studio/research/__init__.py`
- `src/dps_studio/research/bandwidth_task001.py`
- `scripts/run_task001_bandwidth.py`
- `scripts/diagnose_task001_reference.py`
- `scripts/summarize_task001_bandwidth.py`
- `tests/unit/test_bandwidth_task001.py`
- 本报告 `docs/TASK-001_BANDWIDTH_RESEARCH.md`

PowerShell 7 复现命令如下。已用的 run_id 会明确报错，复跑必须换新名字，不覆盖旧结果：

```powershell
. ./scripts/bandwidth_env.ps1
$env:OPENBLAS_NUM_THREADS='1'
$env:OMP_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:QT_QPA_PLATFORM='offscreen'
& D:/miniconda3/envs/dps-studio/python.exe scripts/run_task001_bandwidth.py --run-id NEW_SYNTHETIC
& D:/miniconda3/envs/dps-studio/python.exe scripts/diagnose_task001_reference.py --run-id NEW_REFERENCE
& D:/miniconda3/envs/dps-studio/python.exe scripts/summarize_task001_bandwidth.py --synthetic-run NEW_SYNTHETIC --reference-run NEW_REFERENCE --run-id NEW_ASSESSMENT
```

运行时合成与参考脚本各自记录源文件哈希。合成运行后仅扩展了诊断函数对实际 40 GS/s 的 Hz 边界处理；20 GS/s 的搜索范围与数学运算不变，没有根据测试标签调整检测器、阈值或参数。新增 40 GS/s 回归测试通过。最初局部 chirp 失败结果保留，后续 oracle 诊断不改写其结果。

实际检查命令及结果：

```powershell
# 变更前全量基线：710 passed, 7 failed，114.50 s，exit 1
& D:/miniconda3/envs/dps-studio/python.exe -m pytest -q -o cache_dir=.local_cache/task001_baseline_pytest_cache --basetemp=.local_cache/task001_baseline_pytest_tmp

# 最终全量：731 passed, 7 failed，1599.36 s，exit 1
& D:/miniconda3/envs/dps-studio/python.exe -m pytest -q -o cache_dir=.local_cache/task001_delivery_pytest_cache --basetemp=.local_cache/task001_delivery_pytest_tmp

# 新增研究测试及相关基线：86 passed，4.19 s，exit 0
& D:/miniconda3/envs/dps-studio/python.exe -m pytest -q tests/unit/test_bandwidth_task001.py tests/unit/test_stft.py tests/unit/test_ridge_refinement.py tests/unit/test_ridge_spectral_quality.py -o cache_dir=.local_cache/task001_verified_unit_cache --basetemp=.local_cache/task001_verified_unit_tmp

# 变更前与最终均通过；最终 exit 0
& D:/miniconda3/envs/dps-studio/python.exe -m ruff check src tests scripts

# 最终 90 source files，无问题，exit 0
& D:/miniconda3/envs/dps-studio/python.exe -m mypy --strict src scripts/run_task001_bandwidth.py scripts/diagnose_task001_reference.py scripts/summarize_task001_bandwidth.py tests/unit/test_bandwidth_task001.py
```

最终全量运行时长包含任务中断期间的墙钟时间，不能用作算法性能数据。新增研究模块的 21 个测试全部通过。七个既有失败名称与初始基线完全相同：

- `test_task015a_analysis.py::test_repository_raw_data_hash_is_stable_during_gui_tests`
- `test_task015c_r_event_reference_views.py::test_cross_file_raw_hashes_and_gui_script_boundary_are_stable`
- `test_legacy_velocity_audit.py::test_real_production_baseline_and_task008_fingerprints_are_unchanged`
- `test_task018c_real_regression.py::test_frame_1015_is_formally_promoted_and_legacy_remains_recoverable`
- `test_v014_release_verification.py::test_zip_verification_rejects_different_file_sets_or_bytes[extra/missing/changed]`（三个参数案例）

前四个失败涉及缺失的私有 `data/raw/20260607.csv` 或 `20260630-1.csv`。后三个因统一临时目录被重定向到工作树内部，提前触发发布 smoke 解压必须位于仓库/环境外部的保护，而测试期待后续文件集/SHA 差异错误。没有为让测试变绿而迁移 raw、写出允许边界或放松发布保护。下一步应另行授权独立处理这些既有测试的可移植性。

## 8. 边界审计与后续建议

结束分支仍为 `research/bandwidth`；已受跟踪文件的 `git diff` 为空；仅上述七个新增文件为未跟踪状态，未 stage、commit、push、merge 或修改历史。所有一级目录保持原样；`.gitignore`、`AGENTS.md`、Production 默认算法及 GUI 均未改。检查的工程树中没有重解析点；结果、artifacts、logs、缓存和 raw 保护忽略规则均继续生效。

Production 保持 `b8524bd3d2da3ff17fe8eece84931b84d9edaaab`；任务开始时已有 `M docs/TASK-031_MACOS_ARM64_INTERNAL_RELEASE.md`，结束状态相同，该文件前后 SHA-256 均为 `DFE16248EBAD3D14BAB275083AF8B4853AE2763F79242FFF6D591C354A7643CB`。没有写入任何其他工作树。参考原始文件、两份旧参考文件的校验均一致，详细值见 `boundary_audit.json`。唯一外部写入为要求的 Obsidian TASK 日志。

六个研究问题的回答：真实残差只能确认存在结构，不能确定来源；冻结噪声似然在匹配合成单频上有效，独立测试成立；它没有证明误接受不增加，且分布失配时明显恶化；竞争支路与模拟 alias 仍不唯一；没有独立真实超带宽恢复证据；下一阶段最值得投入的是仪器/噪声标定及独立注入真值，而非继续增加估计器。

最小确认实验应记录完整接收链（光电探测器、放大器、线缆、示波器）的复响应/不确定度、采样率与抗混叠条件、ADC 量化/饱和/抖动、噪声采集条件、波长与光学频偏。使用独立频率计或已标定源注入跨 B 的频率/幅值扫描，另采独立无目标噪声记录并检查随时间/增益的稳定性；按完整记录分离校准/测试，预设错误率、误差容差和样本量，覆盖双频/变频及 H≈0 对照。只有在独立测试证明新增接受对应真实目标信息后，才讨论硬件链的条件测量范围。

Obsidian 索引：`D:\Research\Notes\05项目\DPS_Studio_BANDWIDTH\2026-10-28_TASK-001_真实PDV残差与可辨识性研究.md`。源码、Git、原始数据校验及实际 artifact 优先于该索引。
