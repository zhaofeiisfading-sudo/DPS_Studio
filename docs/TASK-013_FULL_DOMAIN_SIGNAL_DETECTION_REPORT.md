# TASK-013 全时域信号存在检测与低频数据处理报告

## 1. 开始前审计

审计日期为 2026-07-26，仓库为
`D:\Code\Python_Projects\DPS_Studio`。

- `HEAD`: `11b761fe49550f22e7430f939f2bedb87826c345`
- 分支：`main`
- 上游：`origin/main`
- 暂存区：空
- 工作树：开始前已经为 dirty。13 个跟踪文件有未提交修改，另有
  `configs/`、`docs/`、`presentation/`、`presentations/`、4 个
  `core/workflow` 模块及若干测试/fixture 未跟踪。TASK-013 在这些现有修改上
  工作，没有回退、覆盖或提交用户原有变更。
- Python shell：`base` 的 Python 3.9.1；正式验证使用
  `conda run --no-capture-output -n dps-studio`，Python 3.12.13。
- 修改前全量 pytest：`271 passed`，18.92 s；唯一警告是现有
  `.pytest_cache` ACL 导致的 `PytestCacheWarning`。
- 修改前 Ruff：`All checks passed!`
- 修改前 mypy strict（项目配置，命令 `mypy src`）：39 个源文件无问题。
- 修改前真实生产运行：
  `outputs/task013_baseline/run_pre_task013_20260726`，成功生成 30 个文件。
- 原始数据：
  `data/raw/20260607.csv`，3,792,364 bytes，
  SHA-256
  `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`。
  `data/raw/.gitkeep` 的 SHA-256 为
  `F1945CD6C19E56B3C1C78943EF5EC18116907A4CA1EFC40A57D48AB1DB7ADFC5`。

修改前生产结果中，每个 profile/通道都有 244 个有限正式速度点：

| Profile | Channel | PRE_EVENT | CANDIDATE | OUTSIDE | 有限正式速度 |
|---|---:|---:|---:|---:|---:|
| Balanced | 1 | 219 | 244 | 157 | 244 |
| Balanced | 2 | 219 | 244 | 157 | 244 |
| High time resolution | 1 | 220 | 244 | 158 | 244 |
| High time resolution | 2 | 220 | 244 | 158 | 244 |

## 2. 发现的当前真实逻辑

修改前的真实调用链是：

`scripts/run_demo_pipeline.py` →
`scripts/production_outputs.py:run_production_outputs` →
`core.workflow.analyze_profile` →
`core.workflow.analyze_configuration` →
`compute_stft` → `extract_peak_ridge` → `refine_peak_ridge_subbin` →
表观速度转换 → 显示速度 → spectral quality/continuity diagnostics。

关键事实如下。

1. `core/workflow/config.py:AnalysisConfiguration` 把
   `event_start_time_s` 作为必填分析参数；配置加载器要求它小于
   `analysis_end_time_s`。
2. `core/ridge/models.py:RidgeQualityFlag` 只有 `PRE_EVENT`、
   `CANDIDATE`、`OUTSIDE_ANALYSIS_WINDOW`。
3. `core/ridge/peak.py:extract_peak_ridge` 先以
   `event_start_time_s`/`analysis_end_time_s` 生成时间掩码，只对
   `CANDIDATE` 帧在闭合频带内做 `np.argmax(abs(STFT spectrum))`。
4. `core/ridge/refinement.py:refine_peak_ridge_subbin` 只对 candidate
   做三点 log-magnitude 二次精修；边界峰或无效局部峰返回 NaN 和明确状态。
5. `core/workflow/analysis.py` 在 spectral quality 之前已经生成离散和精修表观
   速度，因此修改前的正式速度没有使用峰—背景或峰—竞争峰诊断。
6. 修改前 `_display_velocity` 无条件把 `PRE_EVENT` 写成显示零；核心精修速度
   仍为 NaN，但显示零默认开启。
7. `core/ridge/spectral_quality.py` 已有可复用的线性幅值诊断：在主峰 guard
   外用中位数作背景、最大值作竞争峰，并按幅值比
   `20 log10(peak/level)` 计算两种对比度。它们是谱对比度，不是正式 SNR。
8. 数值层保存的是复数 `STFTResult.spectrum`；诊断按需计算未裁剪线性幅值
   `abs(spectrum)`；绘图层另行生成相对显示 dB。没有第三套独立保存的正式
   功率谱数组，只有旧 onset diagnostic 中的平方幅值和。显示 dB 从未作为
   TASK-013 判据。
9. 两个通道在 `for channel_name, record in records.items()` 中独立执行全部
   数值流程；没有电压平均、通道选择或融合。

## 3. 修改文件

TASK-013 直接新增或修改的文件如下。工作树中的其他开始前变更仍属于用户原有
工作，不归入本任务实现。

- `configs/demo_dual_profile.toml`
- `src/dps_studio/core/quality/__init__.py`
- `src/dps_studio/core/quality/models.py`
- `src/dps_studio/core/quality/detection.py`
- `src/dps_studio/core/ridge/peak.py`
- `src/dps_studio/core/workflow/analysis.py`
- `src/dps_studio/core/workflow/config.py`
- `src/dps_studio/core/workflow/models.py`
- `src/dps_studio/core/workflow/quality_parameters.py`
- `src/dps_studio/core/workflow/__init__.py`
- `src/dps_studio/core/__init__.py`
- `scripts/production_outputs.py`
- `scripts/audit_legacy_velocity_reference.py`
- `tests/unit/test_peak_ridge.py`
- `tests/unit/test_ridge_refinement.py`
- `tests/unit/test_signal_detection.py`
- `tests/unit/test_workflow_config.py`
- `tests/unit/test_production_outputs.py`
- `docs/TASK-013_FULL_DOMAIN_SIGNAL_DETECTION_REPORT.md`

`scripts/audit_legacy_velocity_reference.py` 只把历史重现用的旧起点改为显式
`analysis_start_time_s`，使历史指纹测试继续复现旧基线；新正式生产流程不使用
该旧时间门。

## 4. 新的信号存在判据

新增 `SignalDetectionConfig`、`SignalState`、`SignalDetectionResult` 和纯函数
`detect_beat_signal`。每帧先在显式 profile 搜索频带中得到离散峰和已有的
亚频点精修，然后复用未裁剪线性 STFT 幅值的背景/竞争峰诊断。

每帧保存或导出：

- coarse peak frequency、peak amplitude、background level；
- strongest competitor level；
- peak/background dB、peak/competitor dB；
- peak bin index、band-boundary flag；
- cycles in window、refinement status、signal state；
- 只在 `MEASURED` 帧有限的正式 refined frequency 和 apparent velocity。

判定顺序为：

1. 分析范围外 → `OUTSIDE_ANALYSIS_WINDOW`
2. 检测关闭、谱诊断不可用或对比度非有限 → `NO_DETECTABLE_BEAT`
3. 峰—背景差低于阈值 → `NO_DETECTABLE_BEAT`
4. 峰—竞争峰差低于阈值 → `AMBIGUOUS_PEAK`
5. 峰位于搜索频带边界 → `PEAK_AT_BAND_BOUNDARY`
6. 窗内周期数不足 → `INSUFFICIENT_CYCLES`
7. 亚频点精修未成功 → `REFINEMENT_FAILED`
8. 全部通过 → provisional `MEASURED`
9. provisional measured 的精确连续段短于最小帧数 →
   `UNSTABLE_DETECTION`

连续段之间不插值、不平滑、不连接短缺口，也不填补 NaN。只有最终
`MEASURED` 帧进入正式频率/速度数组。

## 5. 阈值及其物理含义

本次配置使用共享的显式 development defaults：

| 参数 | 值 | 含义 |
|---|---:|---|
| `minimum_peak_to_background_db` | 10 dB | 线性幅值比至少 3.162 |
| `minimum_peak_to_competitor_db` | 3 dB | 主峰幅值至少约为竞争峰 1.413 倍 |
| `peak_exclusion_half_width_bins` | 12 bins | 排除主峰和两侧各 12 个频点 |
| `minimum_consecutive_frames` | 3 | 至少 3 个相邻 provisional measured 帧 |
| `minimum_cycles_in_window` | 1.0 | 当前 STFT 窗内至少一个候选振荡周期 |
| `enabled` | true | 正式门控启用 |

背景用 guard 外幅值中位数，竞争峰用 guard 外最大幅值。频率 bin 间距约
9.765625 MHz；实现用 `(12 + 0.5) * bin_spacing` 作为 inclusive guard 的
Hz 判据，从而精确排除两侧各 12 个邻居。

这些值没有被声明为文献或仪器校准阈值。依据仅是：已有幅值语义、明确可解释
的对比度、固定种子合成行为测试和 fail-closed NaN 规则。真实实验阈值仍需
独立标注数据或物理审查，因此 manifest 明确记录
`development defaults; ... experimental threshold validation remains required`。

## 6. 低频周期数处理

使用：

`cycles_in_window = coarse_peak_frequency_hz * window_duration_s`

低于 `minimum_cycles_in_window` 的候选标为 `INSUFFICIENT_CYCLES`，正式频率和
速度保持 NaN，不写零。

| Profile | 窗长 | cycle-rule 最低频率提示 | 对应表观速度提示 |
|---|---:|---:|---:|
| Balanced | 19.2 ns | 52.083333 MHz | 40.364583 m/s |
| High time resolution | 12.8 ns | 78.125000 MHz | 60.546875 m/s |

这些只是当前窗口与 `minimum_cycles_in_window=1` 的分析能力提示，不是仪器
绝对低速下限。profile 的搜索下限仍为显式 0.05 GHz；低于原 0.1 GHz 的
80 MHz 合成单频在周期数、谱对比度、精修和连续性均足够时可以被测量。

## 7. 自动候选事件时刻定义

`detected_event_candidate_time_s` 定义为第一个长度不少于
`minimum_consecutive_frames` 的正式 `MEASURED` 连续段首帧中心时间。

结果同时记录首帧中心时间、window duration、hop duration、首段连续帧数和
source=`spectral_detection`。候选不是 `true_event_time`、`impact_time` 或
`shock_arrival_time`。两个通道独立计算，只并列显示，不融合。

`manual_event_reference_time_s=554.668 µs` 只用于相对坐标和人工审查。
`event_start_time_s` 保留为兼容别名，但不会门控正式计算。改变人工参考不会
改变正式频率、速度或 signal state。

显示零配置 `assume_pre_event_zero_for_display=false` 默认关闭。显式开启时只
覆盖 `display_velocity_m_s`，origin 为
`assumed_pre_event_zero_display_only`；正式
`apparent_velocity_m_s` 不变。关闭时图中也不显示零平台或 bridge 图例。

## 8. 合成测试结果

`tests/unit/test_signal_detection.py` 包含 19 个通过的测试/参数化检查，随机噪声
使用固定 seed。覆盖：

- 纯噪声全部正式速度为 NaN、无候选时刻；
- 已知时刻出现的清晰单频；
- 全记录单频从首个 STFT 帧可测；
- 弱单频低于门槛；
- 等强竞争谱线；
- 搜索边界峰；
- 周期数不足；
- 80 MHz 低频但可测；
- 亚频点精修失败；
- 只有两帧的孤立强峰；
- 人工参考时刻不改变正式数组；
- 显式显示零只改变 display 数组；
- 非有限/负阈值、非法 guard、连续帧数、周期数和 enabled 类型。

生产集成测试另验证双通道独立、CSV 全帧保留、正式列与 core 结果一致、完整
输出树、manifest/provenance 和可读图像。

## 9. 真实双通道结果

最终输出：
`outputs/task013_validation/run_task013_final2_20260726`，成功生成 36 个文件。

| Profile / Channel | MEASURED | NO_DETECTABLE | AMBIGUOUS | INSUFFICIENT_CYCLES | BAND_BOUNDARY | REFINEMENT_FAILED | UNSTABLE |
|---|---:|---:|---:|---:|---:|---:|---:|
| Balanced / 1 | 392 | 66 | 122 | 0 | 21 | 0 | 19 |
| Balanced / 2 | 379 | 78 | 65 | 0 | 95 | 0 | 3 |
| High time / 1 | 375 | 25 | 93 | 0 | 126 | 0 | 3 |
| High time / 2 | 366 | 22 | 36 | 0 | 198 | 0 | 0 |

所有 profile/channel 的 `OUTSIDE_ANALYSIS_WINDOW` 为 0，因为配置显式覆盖当前
完整原始记录；分析范围内所有 STFT 帧都完成峰搜索、精修尝试和质量评估。

| Profile | Channel 1 candidate | Channel 2 candidate | 绝对差 |
|---|---:|---:|---:|
| Balanced | 554.081854260 µs | 554.667454260 µs | 585.600 ns |
| High time | 554.667454260 µs | 554.670654260 µs | 3.200 ns |

Balanced channel 1 的首段只有 3 帧，频率约 1.82 GHz，位于人工参考前约
586 ns。它可能是当前 development thresholds 留下的噪声假峰，也可能是早期
真实谱结构；现有数据和本任务范围不能判定。它绝不能被解释为真实冲击到时。

## 10. 修改前后差异

完整记录的有限正式速度点由旧逻辑的每通道 244 点变为：

- Balanced channel 1: 392
- Balanced channel 2: 379
- High time channel 1: 375
- High time channel 2: 366

这个总数不能直接解释为“增加了可靠测量”，因为旧逻辑把人工参考前和旧
`analysis_end` 后全部屏蔽。

按历史固定区间比较：

| 区间（相对人工参考） | 每通道旧有限点 | 每通道新有限点 |
|---|---:|---:|
| onset `[0, 0.08 µs)` | 25 | 25 |
| plateau `[0.08, 0.50 µs)` | 131 | 131 |
| decline `[0.50, 0.782 µs)` | 88 | 88 |

旧正式窗口内的 244 个点在所有 profile/channel 中全部保留，没有出现真实平台
大面积误删。

人工参考前的新有限点分别为 5、1、1、0；其中 Balanced channel 1 的首个 3 帧
段触发了过早候选风险。历史 analysis end 后的记录尾部新增有限点分别为
143、134、130、122。尾部图上可见连续低速分支后又出现约 650–680 m/s 分支；
仅凭当前谱对比度不能确认它们是物理信号还是噪声/其他谱支，因此保留为需人工
物理复核的正式检测结果，不宣称为已验证真实速度。

生成的每通道图包括全时域 STFT、分析频带与门控 ridge、旧式质量未门控预览
与新正式速度对比、signal state、峰—背景差、峰—竞争峰差和 cycles/window；
每个 profile 另有双通道候选时刻比较图。

## 11. 剩余风险和未知项

1. 10 dB、3 dB、12 bins、3 frames、1 cycle 均为 development defaults，
   尚无实验标注或文献校准。
2. Balanced channel 1 的 3 帧早期段会把候选时刻提前 585.6 ns，是最重要的
   假阳性风险。没有为了消除它而事后调参。
3. 记录尾部大量帧通过当前门槛，但其物理支路身份未知。峰值存在不等于已经
   验证了正确的 PDV 分支。
4. `minimum_cycles_in_window` 只描述 STFT 窗口可测性，不包含仪器带宽、探测器
   响应、采样链校准或实际低速不确定度。
5. 配置中的 1550 nm 波长仍是 demo value，未由实验记录确认；速度值因此只能
   视为当前配置下的 unsigned apparent velocity。
6. 未实现 LiF 修正、通道融合、平滑、插值、自动补点、CWT、SVD、AI 或 GUI。

## 12. pytest、Ruff、mypy 结果

最终质量门：

- `conda run --no-capture-output -n dps-studio python -m pytest`
  → `296 passed, 1 warning in 13.39s`
- `conda run --no-capture-output -n dps-studio ruff check .`
  → `All checks passed!`
- `conda run --no-capture-output -n dps-studio mypy src`
  → `Success: no issues found in 41 source files`

唯一 warning 仍是 `.pytest_cache` 的环境 ACL capture noise，不是测试失败。

## 13. Git diff 和原始数据哈希

终检要求使用：

- `git diff --stat`
- `git diff --check`
- `git status --short --branch`
- `git diff --cached --stat`
- `Get-FileHash data/raw/20260607.csv -Algorithm SHA256`

最终原始 CSV SHA-256 复核为
`AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`，
与开始前完全一致。生产脚本也在每次运行前后内部复核该哈希。

终检时跟踪文件总体 `git diff --stat` 为 18 个文件、2,079 行新增、
806 行删除；该统计不包含未跟踪的新增 core 模块、测试、配置和本报告。
`git diff --check` 无输出并以 0 退出，暂存区 diff 仍为空。

由于工作树在 TASK-013 开始前已有大量未提交的 TASK-011B/文档/展示相关变更，
仓库级 `git diff --stat` 包含这些既有内容；最终汇报必须把仓库总体 diff 与
本报告第 3 节列出的 TASK-013 直接触及文件区分开。

## 14. Git 与任务边界声明

本任务没有执行 `git add`，没有暂存文件，没有创建提交，没有推送，没有改写
Git 历史，也没有开始下一项 TASK。`data/raw` 未修改、未覆盖、未重采样。
