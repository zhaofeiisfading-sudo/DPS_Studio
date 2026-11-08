# TASK-015 验收与限制

开始 2026-11-07，验收 2026-11-08。Windows x64；Research 分支 `codex/research_2/global-path-ridge-v2`，起点 `31270d1e20606a54bda1e5daab4c858d3a664ad2`。本任务改动保留在工作树，不提交、不 push、不 merge、不 promotion。

| 范围 | 当前证据 | 结果 |
|---|---|---|
| 开发/独立合成 | `data/development_v02/complete.json`、`data/heldout/complete.json` | 72 开发 + 288 held-out；所有案例完成，保留候选、门控、误差与失败 |
| 独立冻结 | `data/heldout/freeze.json`、`data/heldout_source_check.json` | 估计代码及协议 SHA-256 与独立测试冻结一致 |
| 边界/误标 | `data/sensitivity_v02/complete.json`、`SENSITIVITY_NOTE.md` | 336 次配对扰动，四个 SNR 层；首轮 84 个 −8 dB 扰动未删除、不重复合并 |
| 时间分辨 | `data/resolution/complete.json` | 20 个脉冲，2–32 ns；保留漏检、假高频点、宽度偏差，不宣称亚纳秒精度 |
| 完整真实数据 | `data/real_v02/complete.json`、`diagnostics.csv` | 13 文件、17 流、102 行策略诊断；无真值，无真实速度准确度结论 |
| 真实网格 | `data/grid_check.json` | 17 流均为同一整数原采样中心；最大时间舍入差 1.696×10⁻¹⁵ s，没有轨迹插值 |
| 全量非 GUI pytest | `logs/all_core.log` | **1162 passed、5 failed**；下表列明历史失败，未改写冻结清单 |
| 新策略合同 | `logs/strategy_tests_v03.log` | 10 passed；低频强杂散、初相、DC、少周期、错误标签、原始波形不变、边界隔离、修正和导出 |
| GUI 相关回归 | `logs/gui_v01.log`、`gui_final.log`、`gui_prior_plot_v02.log` | 38 项相关流程 + 7 项 shell + 1 项新增联动/先验图检查，共 46 个不同测试通过 |
| Ruff | `logs/ruff_delivery.log`、`logs/ruff_delivery_audit.log` | core、GUI、变更测试、TASK-015 轻量脚本及交付检查脚本通过 |
| mypy | `logs/mypy_delivery.log` | core/GUI 94 个源文件严格检查通过 |
| 冻结程序真实工作流 | `data/native_acceptance/report.json` 及截图 | Windows Qt、窗口可见、两通道；五种新增策略均执行无算法异常；经典/分段、角度/LiF 链、加速度、导出读回、5 次模式往返、三种窗口尺寸通过 |
| ZIP 成员核验 | `data/package.json` | 452 文件、未压缩 240,831,152 bytes；每个 ZIP 成员 SHA-256 等于已运行目录；未检出 raw 内容摘要 |
| 完整解压再启动 | `data/zip_startup.json` | 事件循环进入、Windows 平台、可见窗口与包内运行库；后台启动快照 `window_exposed=false`，不把它报告为已 exposed |

## 保留的未通过项与已修复的执行问题

1. `test_task023a_imm_mht_tracker::test_fixed_upstream_and_raw_guardrails`：旧冻结 `stft.py`/`candidates.py` 摘要不符。
2. `test_task023f_proposal_recovery::test_frozen_e4_constants_and_no_production_writes`：旧记录中的 Production 固定摘要不同；不能据此推断本轮写入，另用任务前后完整内容快照核验。
3. `test_task023g_retention_audit::test_frozen_f_source_production_and_raw_hashes`：旧 `task023f_audit.py` 指纹不符。
4. `test_task025_informative_interval::test_frozen_original_source_and_config_hashes`：旧 `configs/pdv_studio_defaults.toml` 摘要不符。
5. `test_task025_informative_interval::test_calibration_provenance_excludes_held_out_and_is_immutable`：旧归档缺少 `streams/T25_CORE_amplitude_exchange_08_balanced.npz`。

上述五项与 TASK-014 的已记录失败相同，相关目标源码/配置未被 TASK-015 修改。没有伪造缺失流、重写旧清单或用排除选项宣称全绿。

初轮 `pool_tests_v01.log` 的两个 setup error 来自 PowerShell 的 `PYTEST_ADDOPTS` 中 Windows 反斜杠被解析；已改为正斜杠、每进程独立临时目录，随后 24/24 通过。初轮真实诊断的浮点时间匹配失败在 `logs/real.log`，整数中心修复后 17 流完成。新增先验图测试首轮用 `QTest.qWait` 等待 Python 工作线程超时；按原生验收已有模式改用释放 GIL 的 `sleep(.01)`，同一实际分析与图形断言在 1.26 s 通过。没有为过测削弱断言或修改算法门槛。

## Windows 测试包

`release/PDV_Studio_Research_TASK015_Windows_x64.zip`，95,766,267 bytes，SHA-256：

`01e47e0ffd9e185be301a31c4d974b7a740c9b430d86630643467790a81f77b5`

这是未签名 Research 测试包。此次只保留一个 TASK-015 ZIP；历史版本按安全规则保留，不用“一个包”的要求反向授权删除历史测试版。打包中间目录和独立解压验证目录在核验后清理，执行记录见 `disk_governance/task15_build_cleanup.json`。云端 CI、其他 Windows 版本和混合 DPI 热切换不在本轮已验证范围。

## 磁盘、原始数据与 Git

起点工作区 79,798 文件、11.6729 GiB。已清理六个明确可重建路径的 358 个文件，共 468,913,516 bytes（447.19 MiB）；删除前核对逐文件 SHA-256、路径边界及运行中进程依赖。旧虚拟环境、历史结果、发布包、未知测试输出均保留并分类；见 `cleanup_manifest.json`、`cleanup_executed.json`。不以目录数减少为目标。

Production 完整快照覆盖 26,529 文件、13,580,735,707 bytes，含 `.git`；最终 SHA-256、大小与 mtime 比对全部一致，Production Git 状态一致。raw 与 TASK-009 补充 raw 的前后比对也全部一致，见 `disk_governance/boundary_comparison.json`；完整清单为 `boundaries_before.json` / `boundaries_after.json`。Research 独立 `.git` 已验证，HEAD 保持起点不变。大数组、图件、缓存、EXE、ZIP、测试输出继续被 Git 忽略，仅轻量源码、测试、文档和复现脚本可进入版本管理。

清理和实验后的工作区快照为 81,961 文件、12.0021 GiB，相对起点净增加约 0.3292 GiB；此快照在最后少量交付文档写入之前。新增可复核实验数据大于旧缓存清理量，不宣称项目净缩小。任务内构建和解压验收的三份中间目录另已删除，共 518,028,623 bytes，未计入上述 447.19 MiB 历史缓存清理量。

交付一致性检查见 `data/delivery_audit.json`：核对实验数量、冻结代码、测试日志、包及源码摘要、唯一 TASK-015 ZIP、图件格式、Git 轻量文件边界和研究笔记。该检查只汇总已有证据，不替代上列实际实验与 GUI 验收。

## 科学适用范围

GLRT 的局部背景模型、Clutter VarPro 的持续前缀背景和阶段标签均是可失败的条件；R²、谱支持与平滑外观不确认物理目标身份。新模型没有校准的后验区间/CFAR 假警率，不能把合成 RMSE 当仪器误差条。不同支持集合的 RMSE必须配合完整分母失败、覆盖和候选结果；漂移、误标与不显著增益均保留。源数据无修改、无重采样，输出无静默填零/平滑/桥接；物理修正沿用原链，无新增 LiF 公式。
