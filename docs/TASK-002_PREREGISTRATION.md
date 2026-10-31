# TASK-002：先验冻结方案

2026-10-29；分支 research/bandwidth；工作树 DPS_Studio_BANDWIDTH。
本文件在首次 TASK-002 合成性能测试前写入，运行时记录 SHA-256。

## 阶段 A 已完成的审计

- `src/dps_studio/core/analysis_profiles.py:464–546`：全部预设为 0.05–6 GHz。
- 同文件 `AnalysisParameterOverrides` / `build_analysis_run_parameters` 可覆盖上下界；
  `AnalysisRunParameters.validate_for_records:251–299` 按实际 rFFT 网格校验，不固定 6 GHz。
- `core/time_frequency/stft.py:76–111`：单边 Hann STFT 到 Nyquist，无搜索带裁切。
- `core/ridge/peak.py:83–117,156–176`：只在给定搜索带内取最强峰，检查实际 STFT 上界。
- `core/ridge/refinement.py:93–161`：三点对数幅值精修，带边界返回 NaN，不隐式补值。
- `core/ridge/spectral_quality.py:31–185`：在该搜索带内计算背景/竞争幅值，非正式 SNR。
- `gui/main_window.py:1890–1950,1990–1996`：按共同记录最高 rFFT bin 限制 GHz 控件并转回 Hz。
- `gui/analysis_session.py::set_analysis_overrides` 和 `core/workflow/analysis.py` 传递最终参数。
- `gui/result_views.py:204–231,650–683`：全 STFT 图像仍保留，可显示完整频谱；
  Fit search region 仅限制显示视野。配置中 0–2 GHz 是另一个显示范围，不是估频硬限。
- `core/export/writer.py:648–670`：记录最终 STFT/搜索参数，无额外 6 GHz 截断。
- TASK-001 `ToneSearch` 则固定 Fs=20 GS/s、0.2–9.5 GHz。本任务仅在新模块
  `WideToneSearch` 放开网格，继承原 fit/精修/噪声似然；不改 TASK-001 文件。

结论：6 GHz 是默认分析参数，可通过现有覆盖参数扩展。正式 GUI、默认配置、导出、物理修正均不改。

## 冻结实验

Fs=40e9 Hz 是模拟网格，非已确认原生 ADC；Nyquist=20e9 Hz。
频率格点：[3,5,6.5,8,10,12,16,18]e9 Hz；窄带 [0.05,6]e9，宽带 [0.05,19.5]e9。
光学参数仅合成采用 lambda=1550e-9 m、零偏置、正 beat；v=lambda*f/2。
没有原生 ADC、真实 H(f)、抗混叠或独立界面速度真值，真实上限 UNKNOWN。

三个窗：short=128/0/128/1024；Balanced=768/640/128/4096；High Time=512/384/128/4096。
每条独立波形恰好一个窗，逐窗独立统计；实际长记录用指定 overlap/hop，不把相关帧计作独立重复。
独立波形之间随机相位与噪声均重采样，主测试每格点400条。误差容差50e6 Hz。
不做信号标签原型筛选、不调整幅度/阈值寻找胜例，不加入新估计器。

固定条件：ideal_white、ideal_OU、LP1_B6_OU、LP4_B6_OU、LP4_B3_OU；
输入峰值0.04 V，下游噪声 RMS=0.035 V；white rho=0，OU rho=0.85。
接收链为理想、连续一/四阶 Butterworth（B=6或3e9 Hz），或完全零响应；均非真实硬件标定。
平稳 tone 精确复频响在 ADC 前作用；变频用 TASK-001 过采样连续状态近似，压力测试检查收敛。
噪声为下游 OU/独立孔径理想化，PSD 显式给出；主扫描 ADC 量化步长0 V、无抖动/饱和。
另有 2 mV 步长量化抹除反例。没有把提高 nfft 当作硬件增益。

A=默认最强峰，B=宽带最强峰，C=宽带 STFT 三点精修+质量门，D=宽带 TASK-001 AR1 GLRT。
额外 A_gate=窄带同样质量门，用于公平比较搜索范围；C 的未经门控精修数值另存。
门控背景保护半宽=2Fs/N，竞争幅值差>=3dB。每个窗和每种噪声分别训练128x2048条噪声样本；
每个窗/噪声用4096独立空信号重新校准完整搜索统计量，经验上尾目标0.1%，严格大于阈值接受。
C/A_gate 不共享窄宽门限。独立空信号测试4096条，不复用训练/校准集。
种子通过 SeedSequence([20261029,stage,window,noise/condition,frequency,trial]) 产生；
stage=1训练，2校准，3测试空信号，4主频率测试，5压力测试，6无噪声控制。

正确率分母为所有独立测试波形，包括拒绝和错误接受；目标95%。
误接受目标<=1%；所有主要接纳判据采用单侧 Clopper–Pearson 界，
每尾 alpha=0.05/378。378=5条件x3窗x3门控方法x8格点+2噪声x3窗x3空检验。
Bonferroni 全家族置信至少95%，用于可靠格点前缀及方法选择；相关的配对方法不要求独立。
图中普通双侧95% CI 仅描述，正式下界另列。压力试验为描述性，不认证边界。
f_max 为最低3GHz开始连续通过的最高**测试格点**，不认证格点之间全部频率。
没有通过最低点或空信号风险不通过时用空值，不伪造0 Hz测量。
A/B始终输出候选，纯噪声候选率预期100%，不能获得满足误接受约束的正式 f_max；
额外提供已知信号存在时的准确率前缀，明确与正式 f_max 区分。

压力试验：8GHz干净正弦控制；12GHz快速 chirp（窗内8GHz扫宽）；12GHz目标+8GHz强竞争；
23GHz→17GHz混叠；零响应；噪声谱失配；量化抹除。每窗每条件400条，混叠只评数字 alias，
物理载频始终 NOT_IDENTIFIABLE。零响应与噪声失配不通过目标识别而“恢复”时计假恢复。

参考数据：docs/原始数据.csv，只读前后 SHA256；完整两通道STFT与默认/宽带/高带候选，
候选对背景和竞争的比值仅描述。无认证空区，禁止迁移合成门限作为真实测量置信，禁止输出真实速度。

## 资料基础

公式与模型由本任务明确给定；采样混叠参照 Analog Devices 的
[Basics of Band-Limited Sampling and Aliasing](https://www.analog.com/en/resources/technical-articles/basics-of-bandlimited-sampling-and-aliasing.html)。
二项置信界参照 NIST [EXACT BINOMIAL](https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbino.htm)。
模拟 Butterworth -3dB 定义参照 [SciPy butter](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html)。
不由这些资料推断真实仪器参数。
