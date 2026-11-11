# 复现、耗时与边界核对

## 实验及图件验证

- 原始文件按 SHA-256 和列索引核验；12 路约 40 GS/s，2 路约 80 GS/s。共同时间步长分别约 3.2 ns 和 1.6 ns；窗长不同，时间中心一致，NFFT 网格间隔不是物理频率分辨力。69 个起跳中心的时间与样本索引逐项匹配 TASK-017。未使用合成波形做性能验证；单元测试只用确定性候选数值和已有实测输入检查契约。
- 研究相关 pytest **106 passed**，覆盖本任务投票、家族去重、峰宽、失配和全部 raw 中心，以及 TASK-017 实测研究契约与已有仓库测试。Ruff、严格 mypy、仓库卫生、JSON 检查及暂存区检查均通过；[日志](../../../artifacts/TASK-018/data/validation_v2/checks.json)。未运行全仓 GUI 或所有既有合成波形回归。初版静态检查发现未使用导入，保留初版日志并修正。
- 交付核对全部候选和簇的中心坐标、50 MHz–6 GHz 频带、S2 逐点来源、峰宽和得分范围，以及 168 对 PNG/SVG 可读性和 336 个图册链接。[图件 SHA-256 与验证记录](../../../artifacts/TASK-018/data/validation_v2/delivery.json)。实际查看了 `20201214m` 全 Nyquist 谱、`ch3` S0–S2 热图、`20260630-1` 谱叠加、`20201210m` 起跳、`ch3` 换支局部及阶段覆盖；复核版 D 明示孤立点与 NaN 缺口。没有根据看图调整冻结数据或指标。
- 执行环境为现有 `dps-studio` Conda / Python 3.12，Windows。候选提取 3 个工作进程，每个数值核 1 线程；整轮提取约 94.5 s（含两套证据、CSV 和人工先验），随后融合、消融和导出约 91.7 s。每通道单次估计器和主投票计 6.01–35.13 s，双背景证据与其表整理另计 0.64–5.53 s；B0 0.21–1.02 s、B1 0.13–0.78 s、B2 0.19–0.96 s。8 个估计器与投票加总 235.16 s，其中低频 GLRT 110.14 s、主投票 36.27 s。候选进程的 Windows 峰值工作集 231–543 MiB（进程高水位，会保留前一路的峰值，不作算法独占内存）。这些是并发条件下的实测实现成本，未推断在线延迟。[耗时明细](../../../artifacts/TASK-018/data/readout_v1/timing.csv)

## 文件与 Git 边界

Research 起始工作树和暂存区为空，分支 `codex/research_2/global-path-ridge-v2`，HEAD `c7ae6e9a222300658dc9bfd59fe5e0efa98f3e0e`。Research HEAD、分支、index 内容、raw（含 `.gitkeep`）、`src` 和 TASK-017 artifacts 的 SHA-256/mtime 前后一致。新增只在 `scripts/research/task018`、`docs/tasks/TASK-018`、一个 `tests/unit` 测试及忽略的 `artifacts/TASK-018`，另写指定 Obsidian 记录。无源数据覆盖、GUI 修改、依赖安装、打包、commit、push、merge 或 promotion。任务缓存保留在 `artifacts/TASK-018/tmp`，约 23 MB，可重建。

**Production 前后快照不一致。** TASK-018 对 Production 仅使用 `git --no-optional-locks` 的查询和只读 SHA-256/mtime 盘点，不从 Production import 或读取实验输入。同期 Production 工作树出现 `research_TASK19` 产物及 GUI、打包等修改，文件快照 1,280 新增、169 移除、20 内容改变；`.git` 文件快照有 1 新增、4 移除，均在 `refs/codex/turn-diffs/`。Production 的 `main` 和 HEAD `677a22df0566f8403786a0b4d8eac11ff55bcf4f` 在这两个快照中相同。盘点并非原子快照；其后只读状态查询也观察到暂存区变化。这些变化没有回退，也不影响 Research 数据对照。严格的 Production 同一性检查因此返回失败；不能将本次边界结论表述为 Production 前后相同。[边界判定](../../../artifacts/TASK-018/data/boundary/comparison.json) · [完整变更路径](../../../artifacts/TASK-018/data/boundary/production_delta.json)

## 重跑

在仓库根目录用 PowerShell 7，保留当前交付物。以下名称应为新目录；复用已核验的 TASK-017 冻结产物。协议 SHA-256 已写入 [预检清单](../../../artifacts/TASK-018/data/inputs_v1/preflight.json)。同中心、同参数的 B0/B1 和四个原生估计器与 TASK-017 逐值复核通过；B2、GLRT 在本轮新条件下执行。

```powershell
$task018Python = 'D:/miniconda3/envs/dps-studio/python.exe'
& scripts/dev/run.ps1 -Task TASK-018 -Python $task018Python -m scripts.research.task018.boundary before --output boundary_replay
& scripts/dev/run.ps1 -Task TASK-018 -Python $task018Python -m scripts.research.task018.extract --output inputs_replay
& scripts/dev/run.ps1 -Task TASK-018 -Python $task018Python -m scripts.research.task018.audit --input inputs_replay --output audit_replay
& scripts/dev/run.ps1 -Task TASK-018 -Python $task018Python -m scripts.research.task018.fuse --input inputs_replay --audit audit_replay --output stack_replay
& scripts/dev/run.ps1 -Task TASK-018 -Python $task018Python -m scripts.research.task018.summarize --input inputs_replay --stack stack_replay --output readout_replay
& scripts/dev/run.ps1 -Task TASK-018 -Python $task018Python -m scripts.research.task018.figures --input inputs_replay --audit audit_replay --stack stack_replay --tag replay --gallery gallery_replay.html
& scripts/dev/run.ps1 -Task TASK-018 -Python $task018Python -m scripts.research.task018.supplement --stack stack_replay --figures replay --output paired_replay
& scripts/dev/run.ps1 -Task TASK-018 -Python $task018Python -m scripts.research.task018.validate --output validation_replay --run-tests
& scripts/dev/run.ps1 -Task TASK-018 -Python $task018Python -m scripts.research.task018.boundary after --output boundary_replay
```

`validate` 的交付检查针对本次已发布的 v1 数据和复核图册；重跑结果与其逐中心比较时应排除计时、机器环境和图文件元数据。若其他进程并行改动 Production，独立记录差异，不应替换前快照来让检查通过。
