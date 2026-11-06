# 验证与复现

2026-11-06，Research only。正式结果：`runs/evaluation_v02`、`runs/real_v02`、`runs/sensitivity_v02`、`runs/cost_v03`、`statistics/final_v02`和`figures/final_v02`。开发轮不混入正式统计；首轮种子重用的evaluation_v01及早期图表完整保留为探索记录。

| 检查 | 结果与权威记录 |
| --- | --- |
| 相关pytest | 135通过；`checks/pytest_release.xml`与同名log。包含真实临时Git索引拦截、算法梯度、DC/低周期拒绝、整数中心、基准一致、缺失分母、边界隔离、全场景开发/测试种子不重用、输入字节保护及TASK-008～011相关回归。不是全仓GUI测试声明。 |
| Ruff | 本任务源码/测试`checks/ruff_release.log`；54份新纳入版本管理的既有研究Python源码`checks/ruff_existing_sources.log`。 |
| mypy | 严格项目配置，`--explicit-package-bases --follow-imports=silent`；本任务17个Python文件，冻结依赖静默跟随；`checks/mypy_release.log`。 |
| 合成正式实验 | 290波形×13方法/控制/映射＝3770配置，0异常；`runs/evaluation_v02/completion.json`，完整分阶段/候选/支持统计。 |
| 独立新种子 | 144条、16族；36条开发波形另存，不计入正式结果；146条旧波形明确标为旧分布。 |
| 全场景随机流独立性 | `checks/independence_audit_v02.json`确认开发/新测试及旧样本/新测试种子交集均为空。首轮12个跨场景重用已在v01审计披露，正式重跑全部290条，不剔除案例。 |
| STFT整数中心修复 | 580条方法×案例的候选/支持逐值完全相同，最大差0 Hz；`checks/integer_grid_parity.json`。 |
| 缺失与分母 | NaN、消光不剔除；`statistics/final_v02/checks.json`核对全案例/全方法、无遗漏异常与缺失控制。 |
| 实测观测 | 13份indexed raw、17路完整记录、221条观察结果；`runs/real_v02/completion.json`，不报告真实准确率或支路真值。 |
| 标注敏感性 | 12条独立场景×4标注扰动×3方法/映射；`runs/sensitivity_v02/metrics.csv`，全部负结果保留。 |
| 成本 | 8记录×13方法×3次串行独立测量＝312次，包含初始化；`runs/cost_v03/measurements.csv`。 |
| Git/raw/Production | `checks/boundary_verification_final.json`所有unchanged为true。raw、发布包、src/configs与Production完整.git用SHA-256；旧大型生成结果使用路径/大小/mtime清单，不冒充全部内容哈希。 |
| 科研图 | 六组PNG600dpi＋SVG，逐张视觉核对；`checks/visual_review.json`。 |

早期直接运行旧TASK-008测试时，绕过TASK-009 owning data adapter，只看到10个物理raw，导致1项inventory断言失败；支持的回归入口安装本地索引适配后，完整相关测试通过，未改旧测试来伪造结果。实测首轮浮点中心对齐失败保留在real_v01；整数索引修复不改变任何主实验数值。cost_v01因实验并发被中止，不用于公平成本；新成本在其他任务计算停止后串行完成。

## 复现命令

PowerShell 7；使用既有`D:miniconda3envsdps-studiopython.exe`，未全局安装依赖。下例从仓库根运行，输出名必须是未存在的新目录；原冻结TASK-008数据和TASK-009 index/raw supplement需作为本地研究输入保留。Git只跟踪轻量代码/索引，不含原始或数值数组。

```powershell
$task13Python = 'D:miniconda3envsdps-studiopython.exe'
$env:PYTHONPATH = "$PWD/src;$PWD"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
& $task13Python -B -m artifacts.research_clean_task13.repro.verify tests --tag replay2
& $task13Python -B -m artifacts.research_clean_task13.repro.experiment evaluate --output artifacts/research_clean_task13/runs/replay2 --workers 4
& $task13Python -B -m artifacts.research_clean_task13.repro.observations real --output artifacts/research_clean_task13/runs/real_replay2
& $task13Python -B -m artifacts.research_clean_task13.repro.observations sensitivity --output artifacts/research_clean_task13/runs/sensitivity_replay2
# 成本必须在其他实验计算结束后独立串行运行。
& $task13Python -B -m artifacts.research_clean_task13.repro.experiment benchmark --output artifacts/research_clean_task13/runs/cost_replay2
& $task13Python -B -m artifacts.research_clean_task13.repro.summarize --run artifacts/research_clean_task13/runs/replay2 --cost artifacts/research_clean_task13/runs/cost_replay2 --sensitivity artifacts/research_clean_task13/runs/sensitivity_replay2 --output artifacts/research_clean_task13/statistics/replay2
& $task13Python -B -m artifacts.research_clean_task13.repro.plot --run artifacts/research_clean_task13/runs/replay2 --summary artifacts/research_clean_task13/statistics/replay2 --output artifacts/research_clean_task13/figures/replay2
```

`git_governance.py`是本次一次性Git取证/隔离记录，不是需要重新执行的常规复现步骤。未push、未promotion、未改GUI或正式默认值；GIT_CLEANUP.md提供恢复边界。
