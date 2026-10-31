# TASK-002：PDV 高拍频测速上限归因与软件可测范围验证

执行/完成：2026-10-29；分支 `research/bandwidth`；基线 `d216552e00930b17cbb472aa660c4974f49e11fd`。
工作树：`D:\Code\Python_Projects\DPS_Studio_BANDWIDTH`。

**总判决：MIXED。真实硬件上限：UNKNOWN；真实硬件增益：REQUIRES_EXPERIMENTAL_CONFIRMATION。**
主要成果是确认现有软件已能分析 6 GHz 以上的完整数字拍频，不需要另写高频 STFT 或修改默认 GUI。
在冻结的理想链路/白噪声实验中，扩展频带的现有 STFT 质量门与 AR(1) 都通过最高测试点18 GHz，
相对于扩展 STFT 的 AR(1) 上限增益为0 GHz。匹配相关噪声时 AR(1) 有条件优势，不能外推到真实硬件。

证据入口：[`README_TASK002.md`](../results/task002_bandwidth/run_20261029_01/README_TASK002.md)。
完整产物：`results/task002_bandwidth/run_20261029_01/`，约172 MB，继续被Git忽略。
该目录中的源码审计、基准、边界、判决、参考观察、数值补核、逐波形CSV、配置和SVG/PNG均已生成；旧TASK-001未覆盖。

## 1. 三种上限的归因

|问题|本任务结论|直接证据|
|---|---|---|
|A：默认6 GHz|可覆盖的预设分析参数；不是示波器带宽|`core/analysis_profiles.py:464–546`；默认0.05–6 GHz|
|STFT是否丢弃6 GHz以上|没有；单边数组保留至rFFT最高bin|`core/time_frequency/stft.py:76–111`；模拟40 GS/s完整20 GHz谱|
|峰搜索/精修/质量|搜索带参数决定候选范围；边界/质量不足有明确拒绝|`core/ridge/peak.py:83–117,156–176`；`refinement.py:93–161`；`spectral_quality.py:31–185`|
|GUI额外硬限|未发现6 GHz硬限；按共同记录rFFT上界约束|`gui/main_window.py:1890–1950`；`result_views.py:204–231,650–683`|
|GUI有效参数来源|STFT后Search Band写入`ridge_search_region`，基础预设可仍保留6 GHz|`gui/analysis_session.py:646`；`gui/analysis_adapter.py:127–135`优先读取region|
|导出是否再截断|未发现；metadata记录实际ridge上下界，8 GHz正式detail导出通过|`core/export/writer.py:648–670`；新增端到端GUI测试|
|B：模拟链上限|依H(f)、信号幅度、噪声PSD、窗长、量化而变|本任务仅假定理想/一阶/四阶Butterworth/零响应|
|C：数字采样上限|无外部先验时，23 GHz与17 GHz数字alias不可唯一区分|40 GS/s混叠对照；Nyquist不等于已标定硬件上限|

GUI已有操作路径：导入波形并计算STFT → 修改Search Band数值/区域 → 确认后重新提取脊线；
STFT可以复用。显示配置0–2 GHz仅限制视野；“完整频谱”可恢复全频率显示。
新增GUI测试实际运行该路径、选中8 GHz并核对正式导出参数，未改GUI、默认配置、导出格式或LiF修正。

8 GHz干净正弦的Balanced控制：默认峰5.99609375 GHz（错误）；扩展峰7.998046875 GHz；
现有三点精修8.000003709 GHz。失败由搜索带遗漏造成，不能据此声称突破示波器模拟带宽。

## 2. 冻结方法与统计范围

先验方案为 [`TASK-002_PREREGISTRATION.md`](TASK-002_PREREGISTRATION.md)，在性能实验前写入并记录SHA。
Fs=40e9 Hz仅模拟导出采样网格；原生ADC采样率未确认。频率点为3、5、6.5、8、10、12、16、18 GHz。
窄带0.05–6 GHz，宽带0.05–19.5 GHz。输入峰值0.04 V、下游噪声RMS 0.035 V，
白噪声rho=0、OU噪声rho=0.85；主扫描量化步长0 V，另设2 mV量化抹除负对照。
平稳分量采用连续复响应精确计算后再加下游噪声、ADC采样/量化；没有用数字滤波倒置物理顺序。

方法A=默认逐帧最强峰，B=相同STFT扩大搜索带，C=宽带现有三点精修+背景/竞争质量门，
D=TASK-001 AR1 GLRT；另保留窄带同类质量门A_gate。D只在新模块扩展网格，继承TASK-001的fit。
所有方法共用相同数字波形/窗；C不是Production完整跟踪质量逻辑。没有新增或挑选其他估计器。

主扫描每条件/窗/频点400条独立波形，共48,000条、240,000行方法评价；
每窗/噪声以128×2048独立噪声训练模型、4096条校准完整搜索统计量，另4096条独立测试噪声。
校准上尾目标0.1%，最终风险目标1%；宽/窄门限分别校准。校准分数73,728行，空信号评价122,880行，压力评价36,000行。
种子根20261029，阶段/窗/条件/频点/重复通过SeedSequence独立生成；阶段种子无交集。

误差容差50e6 Hz；正确率分母包含全部拒绝/错误；要求正确率单侧下界≥95%、纯噪声接纳上界≤1%。
378个主要单侧判据用Bonferroni同时控制，alpha=0.05/378；图中的普通双侧95% CI另行标注。
400/400的同时下界为97.7921%。`f_max_reliable`为从最低3 GHz开始连续通过的最高**测试格点**；
NONE表示无合格前缀，不是0 Hz，也不认证格点之间所有频率。18 GHz是本次扫描上端，非绝对软件上限。
A/B强制给候选，纯噪声候选率100%；不能按本任务风险要求认证正式f_max，另列已知信号存在时准确率前缀。

Balanced=768/640/128/4096，支持长19.2 ns；High Time=512/384/128/4096，支持长12.8 ns；
两者帧步长3.2 ns、FFT网格9.765625 MHz，Fs/N分别52.0833/78.125 MHz，Hann ENBW为其1.5倍。
这些量与多频实际分辨能力、模拟带宽分别记录。增加nfft只加密网格。
短窗128/0/128/1024也已执行。重叠长记录帧没有被当作独立统计重复。

## 3. 最高可靠测试格点

下表Balanced与High Time的边界一致；单位GHz。仅合成采用1550 nm、零频偏、正beat，
`v_apparent=lambda*f/2`；1 GHz对应775 m/s，50 MHz误差对应38.75 m/s。

|条件|默认质量门|扩展STFT质量门C|AR1 D|D对应合成表观速度|
|---|---:|---:|---:|---:|
|理想链+白噪声|5|18|18|13,950 m/s|
|理想链+OU|NONE|NONE|18|13,950 m/s|
|一阶B=6 GHz+OU|NONE|NONE|18|13,950 m/s|
|四阶B=6 GHz+OU|NONE|NONE|8|6,200 m/s|
|四阶B=3 GHz+OU|NONE|NONE|3|2,325 m/s|

白噪声下，C与D在两种正式窗的全部8格点均400/400；相对于窄带同类门的最高测试格点从5推进到18 GHz。
Balanced白噪声C空信号6/4096=0.1465%，同时上界0.5095%；D为1/4096，同时上界0.2792%。
High Time白噪声C为13/4096，同时上界0.7764%，仍低于1%。全部18个主要门控空检验均通过。

**OU下C无合格前缀不代表没有高频信息。** Balanced理想OU的B全部格点400/400；
C在3 GHz为378/400，18 GHz为395/400：18 GHz单点通过，起始点未通过，因此正式前缀仍为NONE。
高带对比度门受宽带噪声谱形影响；D利用匹配噪声加权，在这组门控比较中取得有条件优势。
C无边界时`gain_vs_C_hz`留空，不能把NONE当0声称增加18 GHz；本任务没有证明D优于所有可能的STFT门控。
可数值比较的白噪声条件增益为**0 GHz**，不足以支持通用新上限声明。

模拟滚降变陡时，残留信号即使频率低于Nyquist也可能不足以接纳。
例如Balanced四阶B6：8 GHz的D为400/400；10 GHz虽386/400=96.5%，同时下界91.8623%，未过冻结验收，故边界8 GHz。
短窗在理想白噪声下只有D到6.5 GHz的前缀，其余相关噪声条件未通过最低点；时间窗不是免费可缩短的参数。
下游OU在高频的低噪声假设是这些收益的重要条件；不能当作真实接收链噪声特性。

图A：[理想数字条件](../results/task002_bandwidth/run_20261029_01/figure_A1_ideal_digital_accuracy.png)、
[OU/四阶衰减](../results/task002_bandwidth/run_20261029_01/figure_A_frequency_accuracy.png)；
图B：[可靠频率与合成表观速度边界](../results/task002_bandwidth/run_20261029_01/figure_B_reliable_boundary.png)。

## 4. 失败机制与数值限制

Balanced强竞争案例中，C/D均400/400接纳8 GHz竞争成分，12 GHz目标识别0/400；检测数字周期不等于识别目标界面。
23 GHz混叠案例：D的400/400数字候选落在17 GHz，真实23 GHz识别0/400；没有从alias唯一反推载频。
OU模型用于独立白噪声空信号时，D假恢复400/400；匹配空信号的1%约束不覆盖噪声谱分布变化。
无目标条件的任何接纳均是假恢复；原始pressure CSV中的`correct`仅是数值距预置频率接近，
其中偶然接近的噪声点不算正确识别，科学判定见`absent_target_false_recovery.csv`（真实目标识别恒0）。
Balanced零响应/量化抹除时C/D均0/400接纳，不能恢复不存在的记录信息；400条本身不足以单独认证1%风险。

快速chirp初始8倍过采样与32倍有8.6–8.8%波形RMS差，精确接纳比例不可当作已收敛硬件预测。
保留初始结果并追加相同12条种子至256倍数值参考；128对256倍差0.3505–0.3564%。
256倍下D接纳2/12，中心误差合格0/12，仅为描述性补核；不重调阈值、不认证总体比例。
平稳主扫描使用精确连续复响应，不受此chirp数值近似影响。详见`MEASUREMENT_LIMITS_AND_QA.md`。
AR1局部Fisher误差也非通用校准区间：Balanced理想白噪声名义95%覆盖94.91%，强衰减B3为91.17%；不可外推至失配/竞争。

计时为本机单线程描述性结果：Balanced共享STFT中位0.636 ms，两搜索带联合搜索/精修/质量1.115 ms，D为2.519 ms。
前两项是共享/联合成本，不是各方法独占耗时；CPU并发背景/缓存影响见`execution_environment.json`与`computational_cost.csv`。

## 5. 真实参考观察

`docs/原始数据.csv`：80000行双通道，列0为s，列1/2为V；导出网格39,999,999,986.36 Hz。
读取前后SHA256同为 `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`。
Balanced每通道620帧：宽带最强峰超过6 GHz分别0/620、1/620；High Time两通道均0/622。
仅搜索6.05–19.5 GHz时，Balanced高带候选中位频率7.583/7.100 GHz，
相对默认峰幅度中位低19.61/25.69 dB，峰/竞争成分仅0.963/0.906 dB；两通道50 MHz内一致率4.52%。

高带峰/背景中位虽达37.14/35.76 dB，但高带多数bin处于更低谱底，中位背景不能代表局部宽谱平台，
因此该大对比度本身不证明窄带目标拍频；多重竞争、带内谱底和未知滤波都须核实。
频谱约8–9 GHz附近有幅度结构变化，原因UNKNOWN，未把它认作实测H(f)或仪器带宽。
高带搜索会被迫返回背景/干扰候选。未找到独立可确认的高频界面拍频或速度真值；没有输出真实速度。
最高状态**OBSERVATIONAL_CANDIDATE**，不能移用合成门限作为真实测量置信。

## 6. 文件、验证与边界

新增八个可审阅文件，既有受跟踪文件均未改：

- `src/dps_studio/research/bandwidth_task002.py`
- `scripts/run_task002_bandwidth.py`、`scripts/summarize_task002_bandwidth.py`、`scripts/audit_task002_bandwidth.py`
- `tests/unit/test_bandwidth_task002.py`、`tests/unit/gui/test_task002_high_frequency_path.py`
- `docs/TASK-002_PREREGISTRATION.md`、本摘要。

PowerShell 7；既有Python3.12.13环境，无安装依赖。实际命令（先dot-source缓存环境）：

```powershell
. ./scripts/bandwidth_env.ps1
$env:OPENBLAS_NUM_THREADS='1'; $env:OMP_NUM_THREADS='1'; $env:MKL_NUM_THREADS='1'
$env:QT_QPA_PLATFORM='offscreen'

# 初始全量：731 passed, 7 failed，103.52 s，exit 1
& D:/miniconda3/envs/dps-studio/python.exe -m pytest -q -o cache_dir=.local_cache/task002_baseline_cache --basetemp=.local_cache/task002_baseline_tmp

# 最终全量：756 passed, 7 failed，52.28 s，exit 1
& D:/miniconda3/envs/dps-studio/python.exe -m pytest -q -o cache_dir=.local_cache/task002_complete_cache --basetemp=.local_cache/task002_complete_tmp

# 相关核心与GUI：111 passed，1.03 s，exit 0
& D:/miniconda3/envs/dps-studio/python.exe -m pytest -q tests/unit/test_bandwidth_task001.py tests/unit/test_bandwidth_task002.py tests/unit/test_stft.py tests/unit/test_ridge_refinement.py tests/unit/test_ridge_spectral_quality.py tests/unit/gui/test_task002_high_frequency_path.py -o cache_dir=.local_cache/task002_relevant_cache --basetemp=.local_cache/task002_relevant_tmp

# 全部通过，exit 0
& D:/miniconda3/envs/dps-studio/python.exe -m ruff check src tests scripts

# 96 source files无问题，exit 0
& D:/miniconda3/envs/dps-studio/python.exe -m mypy --strict src scripts/run_task001_bandwidth.py scripts/diagnose_task001_reference.py scripts/summarize_task001_bandwidth.py scripts/run_task002_bandwidth.py scripts/summarize_task002_bandwidth.py scripts/audit_task002_bandwidth.py tests/unit/test_bandwidth_task001.py tests/unit/test_bandwidth_task002.py tests/unit/gui/test_task002_high_frequency_path.py
```

七项既有失败前后相同：GUI `test_repository_raw_data_hash_is_stable_during_gui_tests`、
`test_cross_file_raw_hashes_and_gui_script_boundary_are_stable`；
`test_real_production_baseline_and_task008_fingerprints_are_unchanged`；
`test_frame_1015_is_formally_promoted_and_legacy_remains_recoverable`；
`test_zip_verification_rejects_different_file_sets_or_bytes[extra/missing/changed]`三例。
前四项缺少私有raw；后三项在工作树内临时目录触发发布解压外部目录保护。
未迁移raw、绕过发布保护或写出允许目录以令测试变绿。TASK-002新增25项全部通过。

复现：按上述环境运行三个TASK-002脚本，分别`--run-id NEW_ID`；必须换新ID，不覆盖既有run。
完整结果核查通过：600主分组、30空信号分组、全部方法同种子波形、阶段独立、冻结源哈希一致。
最终`git diff`为空、仅八个新增文件未跟踪；没有stage/commit/push/merge/rebase。
`boundary_before.json`与`boundary_after.json`核对全部324项既有工作树/TASK-001哈希及受保护工作树状态/跟踪文件。
一级目录不变、无越界重解析点；raw仅占位、参考文件及TASK-001字节不变，结果/缓存忽略有效。
Production仍为`b8524bd3d2da3ff17fe8eece84931b84d9edaaab`，原有TASK-031文档修改保持原状；其他受保护工作树未写入。

Obsidian日志：`D:\Research\Notes\05项目\DPS_Studio_BANDWIDTH\2026-10-29_TASK-002_高拍频测速上限评估.md`。
唯一外部写入是此任务要求的日志。日志是导航索引，代码、Git、原始CSV与完整评估优先。

## 7. 后续建议与可核验资料

优先标定真实接收链H(f)/噪声PSD及其稳定性、原生ADC采样/抗混叠/量化/抖动，
明确波长、光学偏置与界面身份；用独立已标定源跨频率/幅度注入并按完整记录拆分校准/测试。
本任务不支持宣称扩展了真实仪器测速上限，也不建议直接将AR1门接入Production。
若再做算法研究，应针对已测噪声谱和失配检验；本任务完成后停止，不启动TASK-003。

参考来源均为可核验官方资料，不推断真实仪器参数：
[NIST精确二项置信界](https://itl.nist.gov/div898/software/dataplot/refman2/auxillar/exacbino.htm)、
[Analog Devices采样与混叠](https://www.analog.com/en/resources/technical-articles/basics-of-bandlimited-sampling-and-aliasing.html)、
[SciPy模拟Butterworth与-3 dB定义](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.butter.html)。
