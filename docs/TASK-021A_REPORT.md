# TASK-021A：单通道 Top-K 候选峰全局最优脊线研究报告

状态：**development / uncalibrated；Research only；不进入 production 默认路径。**

## 1. Branch / worktree 安全处理

- 原工作树保持在 `codex/research`，HEAD `83000df`，未切分支、未 stash、未 reset、未提交。
- 目标分支使用人工批准的新名称 `codex/research_2/global-path-ridge`。
- 独立 worktree：`D:\Code\Python_Projects\DPS_Studio_TASK021A`。
- 基线为本地稳定 `main`：`e7739d2`。
- 原分支 `codex/research` 与最初目标子分支名存在 Git ref D/F 冲突；`pack-refs` 未改变任何分支指向，随后采用获批的新名称。

## 2. 开始前源码审计

1. STFT public result 是不可变 `STFTResult`：`time_s`、`frequency_hz`、复数 `spectrum` 与 window/overlap/hop/nfft/sample-rate/scaling/source provenance；谱矩阵形状为 frequency × time。
2. Production 搜索频带是闭区间布尔 mask；超出 STFT 频率轴或频带无 bin 时显式报错。
3. 每帧 coarse peak 是搜索频带内 `abs(spectrum)` 的 `np.argmax`，相等峰选最低频 bin。
4. strongest competitor 是排除所选峰中心两侧 inclusive Hz guard 后，剩余频带线性幅值的最大值。
5. 已存在 `extract_local_peak_candidates`，使用未平滑幅值上的 `scipy.signal.find_peaks` 并折叠 plateau。
6. 既有函数内部可找到 local maxima，但 public result 只保留配置的前 K 个；未暴露一帧所有未截断 maxima。
7. refinement 为三点 log-magnitude quadratic：令 `y=ln|S|`，`delta=0.5*(y_left-y_right)/(y_left-2*y_center+y_right)`，`f_refined=f_bin+delta*df`；失败返回 NaN，不回退为离散频率。
8. 质量数据来源：peak=`abs(S_peak)`；background=guard 外幅值中位数；competitor=guard 外最大幅值；两种 contrast=`20 log10(peak/reference)`；cycles=`f_discrete*window_length/sample_rate`；boundary=搜索带首末 bin；refinement status 来自上述 kernel。
9. Continuity diagnostics 使用相邻有限帧频差、中心斜率和“一帧跳出后恢复”条件；gap 不跨越。Production 仅允许通过严格双邻居门的孤立跳点 Top-3 rescue。
10. `SignalState.MEASURED` 要求：质量可评估、peak/background ≥10 dB、peak/competitor ≥3 dB（validated rescue 使用显式 relative threshold）、非频带边界、cycles/window ≥1、refinement 成功，随后还要满足默认 3 连续帧；rescue 帧保留显式来源。
11. 第一峰不可信时，production 通常输出拒绝状态与正式 NaN；只有 isolated-jump continuity rescue 能选择低排名 local peak，不做全段 global optimization。
12. 既有 synthetic infrastructure 包含 STFT/ridge/refinement/quality/detection、legacy velocity 与 continuity-reselection tests，但没有含 NULL 的全局路径 ground truth benchmark。
13. 当前正式 profiles：Balanced (768/640/4096)、High time (512/384/4096)、High frequency (1024/896/4096)，以及 256 和 2048 sample 两个 experimental profile；搜索频带均 0.05–6.0 GHz。当前 demo production 配置运行 Balanced + High time × 2 channels，共四流。
14. Real-data production pipeline：TOML → read-only delimited records → 每 profile 独立 STFT → 每 channel 独立 analysis → formal detection/velocity/correction/display/export；event consensus 只进入 metadata，不融合频率或速度。
15. 初始基线：`mypy --strict src` 通过；隔离 worktree 因 ignored raw 不在新目录而得到 550 passed / 7 missing-raw-or-pytest-argv failures；使用原 raw 的最终 main-suite 回归全部通过。环境级 Ruff `ALL` 规则初始有 217 个历史问题。
16. `data/raw` baseline SHA-256 见第 23 节。

## 3. 当前 production ridge 真实逻辑

Production 默认仍是 strongest peak 加“仅孤立跳点”的局部 continuity-assisted reselection。它不是本任务实现的 Viterbi/DAG path，也没有 NULL state。TASK-021A 没有修改 `analyze_profile`、`analyze_stft_results`、GUI、export 或任何 profile default。

## 4. 新增与修改文件

- `src/dps_studio/core/ridge/global_path_models.py`：config、candidate、candidate set、path result。
- `src/dps_studio/core/ridge/global_path.py`：Top-K、node/transition costs、DP 和 backtracking。
- `src/dps_studio/research/global_path_benchmark.py`：A–H fixed-seed benchmark 与指标。
- `scripts/run_task021a_global_path_research.py`：真实数据、图、CSV、JSON artifacts。
- `tests/unit/test_global_candidate_path.py`、`tests/unit/test_global_path_benchmark.py`：39 项新增测试。
- `src/dps_studio/core/ridge/__init__.py`：只导出显式 opt-in research API。
- `artifacts/task021a_global_path/`：57 个文件、约 3.76 MB。

## 5. Top-K candidate 生成

算法只看单个 `STFTResult`。在正式闭区间 search band 的未裁剪线性幅值上寻找真正 local maxima；频带端点通过 `-inf` padding 参与判断；plateau 由 SciPy 只表示一次。候选按 amplitude 降序、bin index 升序确定性排序。弱峰、boundary 和 refinement failure 不删除，只进入 node penalty；非有限或带外值不进入。

## 6. Candidate separation

采用按 amplitude 次序的 Hz non-maximum suppression。默认 separation 为 `2 * sample_rate / window_length`，也可用 `minimum_candidate_separation_hz` 显式覆盖。比较 K=3、5、10；全部使用同一规则，没有按真实 shot 调 K。

## 7. NULL state

每帧状态严格为 `{retained candidates, NULL}`。NULL rank sentinel 为 0，离散和 refined frequency 均为 NaN。Synthetic dropout、onset 和 pure-noise tests 分别证明 candidate→NULL→candidate、NULL→candidate 和全 NULL。

## 8. Node cost

对 contrast 使用有界缺损：

`C(x; r, s) = clip((r - x) / s, 0, 1)`；非有限 evidence 的缺损为 1。

`C_cycles = clip((target_cycles - cycles) / target_cycles, 0, 1)`。

`C_node = w_bg*C_bg + w_comp*C_comp + w_cycles*C_cycles + w_boundary*I_boundary + w_refinement*I_failure`。

绝对 amplitude 只用于候选 rank，不进入 node cost；plot-relative dB 不进入算法。默认权重和 reference 均在 `GlobalPathConfig` 中序列化，并标记 development / uncalibrated。

## 9. Transition cost

Candidate→candidate 使用 Hz 二次代价：

`C_transition = w_continuity * (abs(f_i - f_(i-1)) / frequency_step_scale_hz)^2`。

选择 quadratic 是为了让普通大跳跃快速增大，同时保持物理单位与解释性；没有二阶 curvature，也没有 magic bin step。

四类 transition 独立：NULL→NULL=`null_stay_cost`，NULL→candidate=`ridge_entry_cost`，candidate→NULL=`ridge_exit_cost`，candidate→candidate=上述 Hz 代价。Synthetic 参数研究发现 entry/exit=3 可阻止利用短 NULL 绕过 sustained-branch jump，同时仍允许真实 dropout 和 onset；该值尚未经实验标定。

## 10. DP recurrence 与 backtracking

实现精确 first-order DAG shortest path：

`D[i,j] = node[i,j] + min_k(D[i-1,k] + transition[k,j])`。

每一状态保存 predecessor，末帧取最低 cumulative cost 后逐帧回溯。相等 cost 由状态顺序确定性打破。明确测试构造了 greedy 在中间帧选择远端最强峰、DP 选择 rank 2 真支的案例，并用穷举路径代价验证回溯结果。

## 11. Config / provenance

`GlobalPathConfig` 包含 K、candidate/background Hz scales、最小背景 bin 数、五类 node weights/reference/scale、frequency step、continuity、NULL node/stay、entry 和 exit costs。`to_metadata()` 可直接 JSON 序列化。Result 保存所有候选、选择 rank、discrete/refined Hz、NULL、逐帧 node/transition/cumulative、total cost、method 和 provenance。

## 12. Synthetic cases

固定 seed 21021，覆盖 A clean、B 1–2 帧强 distractor、C sustained parallel branch、D true ridge weak、E true dropout、F shock onset、G plateau + unloading、H pure noise。全部是 STFT-domain ground truth，真实 shot 未参与参数选择。

## 13. Baseline 对比

每 case 比较 raw frame-wise argmax、当前 production ridge、TASK-021A global path。仓库没有 MeanShift，因此未新增。K=3/5/10 与 continuity weight=0.5/1/2 的 sensitivity 中，global path 总 wrong branch、NULL false-negative 和 false pre-event detection 均为 0。

## 14–17. 核心 synthetic 指标（K=5）

| Case | Argmax RMSE (MHz) | Production RMSE (MHz) | Global RMSE (MHz) | Global velocity RMSE (m/s) | Global wrong frames | Coverage | Rank 2 | NULL |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A | 0.1468 | 0.1468 | 0.1468 | 0.1138 | 0 | 100% | 0% | 0% |
| B | 158.1236 | 158.1236 | 0.1604 | 0.1243 | 0 | 100% | 2.5% | 0% |
| C | 632.4838 | 0.1930 at 37.5% coverage | 0.1750 | 0.1356 | 0 | 100% | 62.5% | 0% |
| D | 282.8760 | 282.8760 | 0.2341 | 0.1814 | 0 | 100% | 12.5% | 0% |
| E | 0.1350 | 0.1350 | 0.1350 | 0.1046 | 0 | 100% | 0% | 7.5% |
| F | 0.1600 | 0.1600 | 0.1600 | 0.1240 | 0 | 100% | 0% | 25% |
| G | 0.1510 | 0.1510 | 0.1510 | 0.1170 | 0 | 100% | 0% | 0% |
| H | N/A | N/A | N/A | N/A | 0 | N/A | 0% | 100% |

Global wrong-branch rate 为 0；NULL false-negative 为 0；F false pre-event detection 为 0；E dropout 后第一帧即恢复。H 全 NULL。完整 rank 1/2/3/4+/NULL 分布在 `synthetic_benchmark_table.csv`。

## 18. Real-data 四流结果

| Stream | Frames | NULL | Rank 1 | Rank 2 | Rank 3 | Disagreement | Production NaN + global rank>1 | Tail selected |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| balanced/ch1 | 620 | 220 | 397 | 1 | 2 | 14 | 3 | 60 |
| balanced/ch2 | 620 | 219 | 396 | 4 | 1 | 22 | 5 | 62 |
| high-time/ch1 | 622 | 262 | 359 | 1 | 0 | 25 | 1 | 39 |
| high-time/ch2 | 622 | 246 | 363 | 12 | 1 | 28 | 9 | 38 |

每流只向 `analyze_profile` 提供一个 record，再独立运行 global path。Candidate cloud 显示起跳前随机高频峰、主平台/下降、多平行谱支、低频复杂区与尾部支路。人工 reference 只画竖线，未进入候选、node、transition 或 path。尾部选择全部标记 `physical identity unreviewed`，不得解释为目标界面速度。

## 19. Production vs global disagreement

四流 disagreement frame 数为 14/22/25/28。CSV 逐候选保存 frequency、amplitude、background/competitor contrast、candidate node cost、selected transition/cumulative cost 和选择理由。真实数据没有 ground truth，因此这些分歧只能作为外部定性验证；不能声称 global path 物理上更正确。

## 20. Residual risks

- 参数只在有限 synthetic family 上开发，尚未针对仪器噪声、谱泄漏、不同 window/profile 和多类 shot 标定。
- First-order continuity 无法区分两条长期、同样平滑但物理身份不同的支路。
- NULL entry/exit costs 能被 sustained branch 结构影响，需更广泛 sensitivity。
- Candidate separation 与主瓣近似尺度有关；密集真实支路可能被抑制。
- Refined-failure candidate 可进入路径但 refined output 保持 NaN；下游使用者必须尊重 status。
- 真实尾部和 production-NaN/global-secondary 帧的物理身份均未审核。
- 本任务没有二阶 curvature；不能据此推断二阶方法的收益。

## 21. Pytest / Ruff / mypy

- Main production suite：555 项（排除 TASK-020-only 与 package 文件）全部通过；main package 2 项单独通过，即 main 基线 557/557。
- TASK-021A 新增：39/39 通过。
- `mypy --strict src`：通过，81 source files 无问题。
- 新增/修改文件在环境级 Ruff `ALL` 规则下：全部通过。
- 全仓 `ruff check . --statistics`：仍有 215 个历史问题；开始前为 217。减少的两项来自本任务必须修改的 ridge `__init__` import/`__all__` 排序；未做无关大重构。
- `git diff --check`：通过。

## 22. Git 状态

分支 `codex/research_2/global-path-ridge`。所有 TASK-021A 代码、tests、docs 和 artifacts 均未暂存；无 commit、无 push。原 `codex/research` 工作树仍 clean。

## 23. `data/raw` SHA-256

开始前与结束后完全一致：

- `.gitkeep`: `F1945CD6C19E56B3C1C78943EF5EC18116907A4CA1EFC40A57D48AB1DB7ADFC5`
- `20260607.csv`: `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`
- `20260630-1.csv`: `203B182E477E1E08214551977A00313EAF6F17A71391D83875F6F879DC3A0A74`
- `20260630-2.csv`: `C0C31B2990EAE228B21594276D030B83600A7DDB98C1953842E4CB80C17FA261`
- `20260701.csv`: `5CCB6530E0CC715E4A7A81327C625FCE267A8B3473C0487479366EAD9D9A952A`
- `ch1.csv`: `3BDCEFD19B0CABD45FF713BC104E00829876F0BE4303ABCFFF31DC5ADA727A6A`
- `ch2.csv`: `975D5EDC124754A170CAC083247D2F2BA1232F6BF6D26F2C878B498025B27A5F`
- `ch3.csv`: `401673B77829D4B2568A4B2A9B88DC649AFA926B668C6C493012D8FC30115D49`
- `ch4.csv`: `84E2859D4285C3D3D4144BA7E5EC0B51FBC0C578857F4DFAF6209E4B87842F5B`

## 24. 明确声明

- 未 `git add`；未暂存。
- 未 commit；未 push。
- 未修改 `data/raw`。
- 未修改 production 默认 ridge、GUI、formal CSV、simple exports 或 LiF 修正。
- 未合并 TASK-020 whitening。
- 未开始双通道 global path。
- 未开始 multi-resolution / 多 profile 联合路径。
- 未开始 AI / machine learning。
- TASK-021A 到此停止，等待人工审计。
