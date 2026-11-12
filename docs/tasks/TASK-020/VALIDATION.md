# 参数、复现和验收

## 冻结输入与可比条件

- 输入为 `data/raw/` 的 10 个 CSV/DAT、14 个电压通道。复用 TASK-017 冻结清单、102 个区间、TASK-018 主比较候选和方案参数。核验输入 SHA-256、每列、样本数、原始时间和采样率。12 路约 40 GS/s，`20221017a` 和 `20231019-ch1` 约 80 GS/s。全记录保留 9,690 个原始中心，主分母为 `q % 128 == 0` 且 `1024 ≤ q ≤ N−1024` 的 9,475 个中心，起跳内 69 个。A 原生步长 64，图与统计直接选取 q 为 128 整倍数的已有中心。
- A 是正式 Balanced STFT，1024 点、H64、Hann、NFFT4096、无去均值，原生 G 保留。B 是 TASK-017/018 的 512 点去均值、H128、Hann、NFFT4096、完整窗方案，原生 G 保留。B + S 从 B 的同一未门控候选应用 S，原 G 仅作为独立质量列，避免用两层门控和 S2 比较。主频带统一 0.05–6 GHz。
- C 使用 TASK-018 原样的 S2，合并 B1/B2/B0、Dechirp、VarPro、Clutter VarPro、Low GLRT 和 Matrix Pencil（含第二极点）。原生 5 MHz–8 GHz 胜出候选超出主比较频带时标记出带。低频 GLRT 仅在 0.05–0.25 GHz 和完整窗内投票。以每中心 ≤100 MHz 的簇跨度聚类，各家族的单位票在其簇间分配，只计有 S 成员的家族份额。选最高分 S 簇的原候选或留空。评分和同分顺序完全沿用 TASK-018，无人工起跳触发、时间连边或按阶段调权。
- S 使用同一原电压 256 点窗、同一噪声参考带 0.05–8 GHz、同一记录前背景与阈值：候选附近谱对比 ≥10 dB，较前背景增益 ≥6 dB，窗内 ≥1 周期，正弦或原生调频拟合 R² ≥0.20。背景取记录首最多 4,096 样本内完整窗，并以冻结起跳下界减 2 ns 封顶。STFT 候选的原生调频率为零，调频候选可带其估计斜率。两者共用规则与原电压，调频模型给 S2 提供了额外证据输入。完整 256 点窗的单周期下限约为 0.157 GHz（40 GS/s）或 0.314 GHz（80 GS/s）。它会造成部分低频空缺，固定背景门也可能拒绝原本较弱的可见脊。

## 图件与 CSV 口径

图 1 和图 3 所有面板都使用相同的原始电压 512 点 Hann STFT（H128、NFFT4096、无去均值/去趋势、无补边）。同一通道所有局部沿用全记录带内峰值归一化，色标统一 −60 至 0 dB。原始谱的分析窗带来时间和频率展宽。零填充只细化 FFT 网格。所有图的 y 轴固定 0.05–6 GHz。x 轴为原始记录起点后的 ns，图题给出绝对起点 µs。虚线为冻结阶段边界，局部图留少量邻段供回查。图线只连接相邻且发布的中心，保留 NaN 空缺。

图 1–2 中 A/B 发布轨迹取原生 G，C 取 S2；未过 S 的原生发布点画菱形。空心点记录未发布候选，C 在此显示筛选前 S1 赢家被拒或被替换时的位置。图 3 的 A/B 显示各自最强原始候选，B + S 保留同一候选的 S 通过或拒绝状态，C 显示最终选择、未选的 S 簇和未过 S 的 S1 代表。簇内所有成员保存在候选 CSV.GZ。补充共识图的 S1/S2 使用相同 0–1 票分色标，候选频率 ±50 MHz 内画三角形权重。原始功率使用自己的 dB 色标。

| 文件 | 内容 |
| --- | --- |
| [逐中心 CSV](../../../artifacts/TASK-020/data/centers) | A/B 原频、带内候选、原生 G、S、发布频率、原质量、B + S、S1 和 C 赢家、C 来源索引和竞争标记。频率 Hz、时间 s。空频率字段为 NaN。 |
| [候选 CSV.GZ](../../../artifacts/TASK-020/data/candidates) | TASK-018 已复验的全估计器原始候选与质量，含带外候选、适用性、原生门控、S 证据与簇归属。 |
| [共识簇 CSV.GZ](../../../artifacts/TASK-020/data/peaks) | 每中心所有簇，保留 S0/S1/S2 评分、支持家族、原始代表、最终代表及标记。 |
| [分阶段与分段诊断](../../../artifacts/TASK-020/data/stage_diagnostics.csv) | 主分母、S 支持、原生发布、未过 S 的发布、跳变及公平共同相邻对。 |
| [新增和换支](../../../artifacts/TASK-020/data/paired_changes.csv) · [起跳逐中心](../../../artifacts/TASK-020/data/onset_centers.csv) | B + S 与 S2 的 49 个新增、13 个 >100 MHz 支路替换及全部 69 个冻结起跳中心。 |

## 真实数据复跑与耗时

串行复跑 14 路的原估计器、共用 S 和投票，并将全记录 9,690 个中心的八个估计器候选（含子空间第二极点）、C/G/S 状态、频率及证据值与 TASK-018 对照。候选/质量逐项一致，数值按频率/调频率绝对容差 0.01、原波形诊断绝对容差 `1e-8`、两者相对容差 `1e-10` 检查。S1/S2 胜出来源、峰来源与票数完全匹配，得分通过 NumPy 绝对容差 `1e-14` 与相对容差 `1e-7` 检查。发布 CSV 用已复核的冻结行。扩带失败诊断直接引用 TASK-018 的留存结果。 [复跑记录](../../../artifacts/TASK-020/data/replay.json) · [8 GHz 诊断](../../../artifacts/TASK-018/data/stack_v1/wide8_metrics.csv)

| 方法 | 单路耗时中位数 | 单路范围 | 14 路合计 |
| --- | ---: | ---: | ---: |
| A | 0.84 s | 0.35–2.14 s | 12.58 s |
| B | 0.66 s | 0.29–1.47 s | 9.85 s |
| B + S | 1.22 s | 0.55–2.75 s | 18.16 s |
| C | 37.28 s | 12.28–79.70 s | 547.64 s |

现有 Conda `dps-studio` Python 3.12 环境，单个数值核线程，按通道串行测量。A/B 计入各自原生门控。B + S 计入 B、共用原波形预计算及 B 的 S 审计；C 计入波形上下文、八个估计器、共用 S 预计算、各候选 S 审计、S1/S2 主投票。S 审计包含轻量数据整理。原始文件读取、交付 CSV、图件生成和复跑一致性检查在各分段计时之外。部分测量期间同机渲染，数值用于本实现量级比较。总量上 C 约为 B + S 的 30 倍，Low GLRT 本身共约 247.18 s。 [逐路与分项计时](../../../artifacts/TASK-020/data/timing.csv)

## 验收

- 实测与投票契约 pytest 通过 67 项，范围为 `test_task017_real_research.py` 和 `test_task018_consensus.py`。TASK-020/018 Ruff 和严格 mypy（`--explicit-package-bases`）通过。repo-hygiene 常规和暂存区检查均通过。运行环境 Python 3.12.13、NumPy 2.5.1、SciPy 1.18.0、Matplotlib 3.11.0、pandas 3.0.3。
- 图册覆盖 14 个全记录视图和 102 个冻结阶段视图，共 352 对 PNG/SVG，核验 749 个本地文件目标、图件可解码、单位标签和同谱面板等宽。人工打开了 14 路全程同谱图缩览，以及三个重点通道的起跳、下降/换支、弱段、回升、筛选前后共识图和带宽边界等代表性原尺寸图。修正了图件边界候选截半与空标记问题后重渲染。首轮图件与缓存归入 `artifacts/TASK-020/tmp/`。 [交付校验](../../../artifacts/TASK-020/delivery_validation.json)
- Research 分支 `codex/research_2/global-path-ridge-v2`，HEAD `0e978d9f5d84b679a067df8e98efa630a4b4eef0`，index SHA-256 和空暂存区前后一致。`data/raw/` 10 个原始文件及 `.gitkeep` 的 SHA-256、大小和 mtime 前后相同，`src/` 快照一致。Production 工作树文件和实际 Git 目录的前后快照均一致，查询使用只读哈希和 `git --no-optional-locks`。Research 增量为研究脚本、任务报告、忽略的 artifacts 和指定 Obsidian 日志。Git 提交、推送、合并和打包均未执行。 [边界核验](../../../artifacts/TASK-020/boundaries.json)

## 重跑

在 Research 根目录用 PowerShell 7，路径设为新的 TASK-020 子目录。需要本地 TASK-017/018 冻结产物。主实验只用真实电压。pytest 覆盖真实输入、时间对齐、候选与投票契约。

```powershell
$task020Python = 'D:/miniconda3/envs/dps-studio/python.exe'
$task020Replay = 'artifacts/TASK-020/replay_2'
& scripts/dev/run.ps1 -Task TASK-020 -Python $task020Python -m scripts.research.task020.replay before --output $task020Replay
& scripts/dev/run.ps1 -Task TASK-020 -Python $task020Python -m scripts.research.task020.replay compare --output $task020Replay
& scripts/dev/run.ps1 -Task TASK-020 -Python $task020Python -m scripts.research.task020.atlas --output $task020Replay
& scripts/dev/run.ps1 -Task TASK-020 -Python $task020Python -m scripts.research.task020.validate --output $task020Replay
& scripts/dev/run.ps1 -Task TASK-020 -Python $task020Python -m scripts.research.task020.replay after --output $task020Replay
```

波长、入射角、窗口修正及独立速度真值未核实，交付仅使用频率。已知真实数据上的回顾性比较使用同一批相关时窗和冻结标签。S、票分、跳变和冻结噪声标签用于诊断，不能据此估计物理误差或测速准确率。
