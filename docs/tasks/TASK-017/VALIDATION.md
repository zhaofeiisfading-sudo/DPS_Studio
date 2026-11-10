# 验证、复现与边界

限定范围 pytest **100 passed**；包括既有非波形/非 GUI 单元测试和新增真实输入契约。没有运行会生成合成波形的旧算法测试，以遵守本次零合成要求；不能写成全仓测试全部通过。核心算法数值未改，全部 raw 上25方法+3控制实际执行，0方法异常；另完成边界起始/结束±2/±5ns及长支撑低频核查。

| 检查 | exit_code |
| --- | --- |
| pytest | 0 |
| ruff | 0 |
| mypy | 0 |
| hygiene | 0 |
| hygiene_json | 0 |
| hygiene_staged | 0 |

保护边界完整内容和 mtime 核对：

| 边界 | 前后相同 |
| --- | --- |
| production_git | True |
| production | True |
| raw | True |
| source | True |

Production manifest 跳过目录 symlink/junction，不读取或写入其外部目标；Production .git 的实际文件也纳入。Research初始工作树/暂存区干净，HEAD为 `4fea2c4493cb2758f85e8473e0442dd51607c590`，分支 `codex/research_2/global-path-ridge-v2`。只增加 scripts/research/task017、tests/unit/test_task017_real_research.py、docs/tasks/TASK-017 与被忽略的 artifacts，另写用户指定 Obsidian 日志。没有修改 src、GUI、默认参数、正式导出、.gitignore 或 AGENTS，现有规则已覆盖。无 Git 写命令、打包、全局/局部依赖安装；未触及 raw/Production 写权限。

## 开发失败与处理

早期 mypy 因 namespace module 重复定位、缺少科学库 stubs 和少量类型/未使用导入报错，用 explicit-package-bases、准确类型和局部 import-untyped 注解修复，没有安装新依赖。validation_v01 为84项阶段检查，validation_v02、validation_final、validation_delivery保留静态检查修正过程；100项真实/元数据测试均已通过。最终静态检查以validation_release为准，其中pytest记录明确复用validation_delivery的通过日志，未重复运行已通过测试。

首轮路由的6GHz限制在未删的原组件上重新组装；最终数值与所有图的时间/候选/门控/短窗支持逐元素验证相同。开发版4096窗背景循环恰好空范围，导致长窗支持诊断无效；analysis_v01/v02的 long4096_* 不用于结论。已修正为允许恰好完整的背景窗，用 low_support_v01 单列有效性。最终 analysis_v03 删除全部无效长窗列，新增真实背景可用性回归测试。20201210m原始前背景仍不足4096点，保留 unavailable，不作零支持负结果。

未删除旧结果或临时缓存。小型可重建工具缓存仍集中 artifacts/TASK-017/tmp；无根目录缓存/环境；若要清理，只应人工确认此 tmp 的用途，不能删冻结结果。

## 复现

Python 3.12/3.13；本次既有环境见 validation_release/environment.json。所有数据输出选不存在的新目录，脚本会拒绝覆盖。视觉阶段由实际看图形成，不能用自动检测重新冒充视觉标注；冻结文件已经交付。

```powershell
$task17Python = 'D:\miniconda3\envs\dps-studio\python.exe'
& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.compare --output artifacts/TASK-017/data/replay_new --workers 3
& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.dc_controls --output artifacts/TASK-017/data/dc_new
& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.sensitivity --output artifacts/TASK-017/data/sensitivity_new
& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.analyze --run artifacts/TASK-017/data/replay_new --controls artifacts/TASK-017/data/dc_new --output artifacts/TASK-017/data/analysis_new
& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.plot --analysis artifacts/TASK-017/data/analysis_new --output artifacts/TASK-017/figures/replay_new
& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.highlights --analysis artifacts/TASK-017/data/analysis_new --output artifacts/TASK-017/figures/cards_new
& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.low_support --analysis artifacts/TASK-017/data/analysis_new --output artifacts/TASK-017/data/low_new
& scripts/dev/run.ps1 -Task TASK-017 -Python $task17Python -m scripts.research.task017.validate --output validation_new
```

DC控制入口 dc_controls.py，长窗核查 low_support.py，重点卡图 highlights.py，归档门控 audit15.py。DC控制直接读取当前raw及冻结阶段；卡图/长窗核查可用--analysis显式选择新结果。测试和报告编译默认校验本次冻结交付路径。首次 raw 盘点/图片/冻结脚本只在干净任务目录运行，现有 freeze 不应重写。
