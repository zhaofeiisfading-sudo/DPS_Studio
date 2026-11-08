# TASK-012 验证

日期：2026-11-06；分支：`codex/research_2/global-path-ridge-v2`。测试主机为 Windows 11 x64，build 26200。

完整日志、逐例报告及截图位于开发工作树 `artifacts/TASK-012/`；随包的此文件是验收摘要。

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 最终全量回归 | 1279 passed；7 个既有历史检查单独排除 | `pytest_delivery_full.log/.xml`、`historical_exclusions.json` |
| GUI 子集 | 177 passed，0 failures/errors；无原生访问异常 | 同一最终全量 JUnit 中的 GUI 用例 |
| TASK-012 交互合同 | 26 passed，含真正鼠标拖动、24 次 ROI 重建、10 次窗口重建、参考图 ROI/结果保留 | 同一最终全量 JUnit 中的 test_task012_workspaces 用例 |
| Ruff | 维护源码零错误；范围 src/tests/scripts/packaging | `ruff_final.log` |
| mypy | 150 个源码文件通过 | `mypy_final.log` |
| 数值回归 | 13 文件、17 流、每流 9 类数组及质量标志与 TASK-011 逐点一致 | `numerical_parity.json` |
| 包内源码核对 | 101 个应用模块代码对象与交付源码一致 | `bundle_code_parity_acceptance.json` |
| 独立 Windows EXE | 8/8 验收运行通过；Conda/Python 源路径从环境移除 | `release_acceptance_*/verification.json` |
| 原生鼠标键盘 | 工作区、增线、阶段推荐、撤销、参考图、自动候选及正常关闭通过 | `native_interaction_final.json`、`native_*.jpg` |
| 数据与 Git 边界 | 全部通过；无 commit/push/merge/promotion | `boundary_verification.json`、`boundary_final_check.json` |

最终 EXE 的 SHA-256：`7f9b0029198ed3988d9fd464a2df7d9fd381854c2c1ffc15eca7a9ad788318ac`。八次打包验证均记录同一 EXE 哈希。

实测覆盖 `20260607.csv` 两路及 ch1–ch4，经典 STFT、分段分析、通道切换、候选、模式往返、四种参考图分割线编辑、阶段与算法来源、速度/加速度、LiF/角度修正、CSV/metadata 逐点读回、过期结果与后台互锁。ch1/ch2/ch4 在本工作树 data/raw 中缺失，使用 TASK-009 的同 SHA 原样归档副本；映射位于其 data_index.json。

布局覆盖 1024×640、1280×800、1600×1000。Windows 原生 DPR=2；通过进程级 Qt 缩放得到有效 DPR=1/1.25/1.5/2（100/125/150/200%），不改系统设置。实际窗口、可见图形、侧栏尺寸均记录在逐例 report.json；超过当前屏幕可用面积的请求按 Qt 实际尺寸记录。分析和导出按钮始终位于可见固定区域。

## 遗留问题与边界

- 7 项旧检查涉及历史启动器合同、旧冻结哈希和缺失的 T25 归档 NPZ。完整首轮测试也保留了这些失败；本任务未改写历史证据以制造通过。排除清单沿用 TASK-011 记录。
- 开发中一次长进程 GUI 回归触发原生 ROI 访问异常。随后补充 Qt 延迟销毁与关闭清理，最终连续 GUI 与窗口/ROI 压力测试通过。失败日志保留为 `pytest_gui_release.log`。
- Dechirp/VarPro/Clutter VarPro 仍沿用冻结研究假设，真实实验无 GT；质量通过不等于支路物理身份已确认。没有宣称算法普遍胜出。
- 未验证多显示器混合 DPI 热切换、低于 1024×640 的窗口或其他 Windows 版本。测试包未签名。

Production 的 26598 个文件（含 .git）进行完整 SHA-256/大小/mtime 前后核对；raw 的全部 11 个文件再次核对 SHA-256；13 个索引原始输入也逐项匹配。收尾再次检查 Production 完整路径/大小/mtime、Git 与全量哈希后快照一致。算法、core 与 configs 不在改动列表中。

独立打包文件位于 `../../release/`，只保留一个程序文件夹和一个 ZIP。最终截图位于 `release_acceptance_normal/20260607_native/` 与 `release_acceptance_layout/`；其他 staging、source_smoke、frozen、final、acceptance 目录均为保留的开发过程，不是交付入口。
