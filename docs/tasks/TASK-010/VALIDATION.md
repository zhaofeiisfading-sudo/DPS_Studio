# TASK-010 验证记录

2026-11-05。最终检查通过；没有遗留失败项目。检查范围为本任务Research代码、相关基准和STFT测试，不将此表述为全仓回归通过。

| 项目 | 实际结果 | 证据 |
| --- | --- | --- |
| 新增测试 | 18项：core一致、步长独立、缺失分母、验证支撑、边界NaN、直接双尺度选择、云端版本保护 | tests/unit/test_research_task010.py |
| 相关pytest | 141 passed | checks/pytest_final.log |
| Ruff | All checks passed | checks/ruff_final.log |
| mypy | Success，严格项目配置，显式namespace bases；冻结依赖静默跟随 | checks/mypy_final_v02.log |
| 逐点冻结基准核验 | 292条，NaN位置相同，最大频差2.0266×10⁻⁵ Hz | runs/v01/checks/frozen_strict_equivalence.json |
| 全矩阵归因 | 730个波形×窗口组合，6种步长的所有共同评分严格相同 | summary/v02/hop_invariance.csv |
| 输入与分母 | 6714合成、170实测结果；340条代表轨迹核验校正速度NaN分离 | checks/release_verification.json |
| 成本 | 189次独立计时，30个研究参数×2长度×3次，另3个core配置×3次 | cost/v01/measurements.csv |
| PDF | 9张单页，字体全嵌入、0栅格image对象、0页面外文字 | checks/pdf_qa_v01/qa_summary.json |
| 视觉复核 | 主图和Origin伴随图已查看；低速保留全幅异常并加局部放大 | checks/visual_review.json |
| Git/raw/Production | 全部保护检查通过 | checks/boundary_verification.json |

最终pytest通过TASK-009入口启用本地原始数据索引，范围为test_stft、test_ridge_refinement、test_peak_ridge、TASK-008、TASK-008 baseline audit、TASK-009 migration/figures以及TASK-010；缓存与临时目录均在TASK-010检查目录。使用现有dps-studio Python3.12环境、PowerShell7，无依赖安装。

Ruff检查整个TASK-010目录及新增测试；mypy使用`--explicit-package-bases --follow-imports=silent`，逐一检查本任务顶层Python脚本和新增测试。早期检查遇到namespace重复与SciPy无类型存根，采用显式包根和与现有项目一致的import-untyped注释修复，没有安装存根或降低项目strict配置。其他本任务静态检查错误已修正，最终日志为准。

文档生成曾因相对路径校验失败而中止，修正为解析绝对路径，保留已写且相同的关键表，随后成功生成完整报告；未重跑或修改实验结果。图件v01保留，v02增加低速局部放大并调整图例和图注，未改变任何轨迹数值。Origin COM数据逐点读回核验，PDF嵌字前版本保留，最终使用_embedded.pdf。

run.py实验后只增加SciPy类型注释，AST与运行快照一致；experiment.py与运行快照SHA完全一致，证据见checks/entrypoint_ast_comparison.json。最终脚本、协议、配置、测试和所调用core入口SHA见checks/source_freeze.json。

data/raw包括占位文件在内11个文件前后SHA相同；全部10个真正原始输入均被运行；补充3个同SHA文件仍在TASK-009归档。TASK-008的11121个文件和整个TASK-009目录前后哈希一致。Production的代码、raw、分支、HEAD、index、Git状态均保持；目标已有代码字节不变，仅新增Research成果和一个测试，未commit/push/promotion。
