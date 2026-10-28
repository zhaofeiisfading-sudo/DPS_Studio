# TASK-007 — PDV 超带宽信号恢复探索（2026-10-28）

独立研究入口：[README_TASK007](../results/task007_bandwidth_20261028/README_TASK007.md)。
完整判决：[TASK007_VERDICT](../results/task007_bandwidth_20261028/TASK007_VERDICT.md)。
产物位于当前工作区 `results/task007_bandwidth_20261028`（既有 Git ignore），
避免与外部 junction 的旧 `artifacts/clean_task7` 论文图组撞名。

384 条合成波形、5 种对照方法支持有条件的残余信号估频。未混叠单频测试中，
VP_tone 正确输出率 61.81%，现有门控 STFT 59.08%。没有证明可靠识别的带宽倍数普遍扩大。
4 组真实片段的 751 帧均未通过新原型的残差门；真实超带宽恢复未获验证。
未知混叠阶数、零响应与量化信息消失不能纯软件逆转。

新增独立研究模块 `bandwidth_task007.py`、`bandwidth_task007_simulation.py`；
复现/审计/评价/补充/诊断入口均为 `scripts/*bandwidth_task007.py`。
14 个新增测试通过；全套 pytest 1007 通过、7 个既有失败；Ruff、strict mypy 通过。
raw SHA-256 前后一致，未改原 core、GUI、configs 或 Production；未 commit/push/promotion。
