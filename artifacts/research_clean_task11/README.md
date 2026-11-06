# PDV Studio Research / Test · TASK-011

任务日期 2026-11-05；2026-11-06 交付。状态：软件功能与验证完成；严格 .git 边界例外等待用户确认，目标尚未标记完成。基础 GUI/处理链来自 Production v0.1.6，开发分支 `codex/research_2/global-path-ridge-v2`，未提交分支变更。

## 打开测试版

本机可直接双击 [PDV Studio Research TASK011.exe](portable_v4/PDV_Studio_Research_TASK011/PDV%20Studio%20Research%20TASK011.exe)，也可使用本目录的 `Open_PDV_Research_TASK011.cmd`。
移至其他电脑时，完整解压 `PDV_Studio_Research_TASK011_Windows_x64.zip`，保留 EXE 旁的 `_internal` 文件夹。无需 Python 或 Conda。已在本机 Windows 桌面验证，尚未在另一台物理电脑验证；包未签名。

## 使用

1. 沿用原有“打开数据”流程，明确时间/电压单位和列。原有时频图中框选的时间与频带 ROI 会传入分段页；也可在分段页点击“ROI 范围”，拖动蓝色两端并松开确认时间范围。直接调整时间范围后使用当前全局频带参数；需要限定拍频时，在原有时频图中重新框选时间与频带。
2. 使用经典 STFT 时，原有快速分析、时频图、人工频率范围、速度修正和导出流程照常使用。
3. 切换“人工分段”，选通道，点击“新增分割线”；拖动竖线或使用数值框调节，选择分割线后可删除。逐段设置阶段和算法。
4. 点击“分析当前通道”，切换校正速度/表观速度/拍频复核；悬停可查看质量。各通道独立分析，可显式将方案应用到全部通道。编辑或参数变化后重新分析。
5. “导出结果”在所选位置新建目录，保留 CSV 与 metadata；“保存分段/载入分段”支持复用方案，不覆盖已有文件。分段导出使用实验绝对时间，不填事件前零平台。

算法池提供 STFT、Dechirp、VarPro、Clutter VarPro 和“不估计（NaN）”。阶段与建议不自动决定算法。STFT 参数来自原有面板；研究算法保留冻结窗口、128 点步长与事件/前缀假设，详见 metadata。跨段不插值、不平滑、不连接不同区段；边界窗口保留原始上下文并标记 `BOUNDARY_CONTEXT`。

## 验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| pytest | 1253 passed；7 项历史检查明确排除 | `checks/runtime_matrix_v3/core_research.xml`、`checks/runtime_gui_final_v5/` |
| Ruff | core、GUI、算法副本及本任务脚本/测试通过 | `checks/ruff_delivery_v4.log` |
| mypy | 严格项目配置，本任务类型边界通过；冻结依赖静默跟随 | `checks/mypy_delivery_v4.log` |
| 经典数值回归 | 13 文件、17 路；9 类数组逐点相同，质量/来源相同 | `checks/classic_parity/report.json` |
| 实测分段与导出 | 13 文件、17 路、四算法，无算法异常；CSV 回读相同 | `checks/real_manual/report.json` |
| 打包程序 | 正常数据及 ch1–ch4：经典、四算法分段、ROI 编辑失效/重算、方案往返、导出通过 | `checks/frozen_gui_v4/verification.json` |
| 桌面操作 | 独立 EXE 的原生交互复核通过 | `checks/native_interaction.json` |
| 安全边界 | Production 非 .git 内容、main/HEAD/index、两边 raw 及 TASK-008～010 保持；严格 .git 不变检查未通过，变化限于 Codex turn-diff 元数据及对象 | `boundary_verification_final.json`、`boundary_detail.json` |

7 项排除项的名称、原因见 `checks/runtime_matrix_v3/archived_exclusions.json`：两项旧 Production 启动器假设、四项过期源码/配置冻结假设、一项缺失的历史 TASK-025 轨迹。未修改旧归档以伪造通过；不把这些检查表述为已通过。较早验证中的迁入、长路径与 DLL 失败日志均保留，以本表列出的最终记录为准。

## 科学与运行边界

真实数据无物理真值，验证的是软件一致性、状态、质量和导出，不能据此宣称速度更准确或支路已确认。研究算法的安静前缀、可检测事件、杂波持续性与目标身份假设仍需实验员判断。Clutter VarPro 可能移除前缀中已存在的目标信号。候选点不等于通过质量门槛的结果；缺失保留 NaN。极短区段可无估计中心，metadata 记录 0 frames。

表观速度与校正速度分列；角度后接既有 LiF 修正。非负拍频不自动判断运动方向。研究算法可能耗时，分析中需等待完成；当前未实现取消任务。其他 Windows 版本、另一台电脑和特殊显卡/显示缩放尚未逐一实测。

配置命名空间独立为 `DPS Studio Research / PDV Studio TASK011 Test`。运行入口保护 Production 与 data/raw 写入；测试包不读取 Production 实时源码。未执行 commit、push、merge、promotion 或其他 Git 写命令。

恢复聊天后检测到共享 `.git/refs/codex/turn-diffs` 检查点及配套对象变化，路径与时间指向 Codex 客户端自动元数据。未清理或恢复这些文件，未把严格 `.git` 校验报告为通过；逐文件差异保留在 `boundary_detail.json`。例外确认状态以 `acceptance.json` 为准。
交付前再次逐文件核对 Production、两侧 raw 和 TASK-008～010，相对上述快照无新增变化，见 `checks/delivery_boundary_recheck.json`；该复核不消除先前的客户端元数据例外。

## 复现与来源

- [架构与适用边界](DESIGN.md)、`migration_manifest.json`、`test_migration_manifest.json`、`pre_migration/`。
- `scripts/build_task011.ps1`：PowerShell 7、本地既有 dps-studio 环境构建，拒绝覆盖既有构建目录。
- `scripts/task011_test_matrix.py`：pytest 分批隔离 Qt，使用短临时路径，不修改系统长路径设置。
- `scripts/task011_real_regression.py`、`scripts/task011_verify_package.py` 与 `scripts/task011_boundaries.py`：回归、独立 EXE 与全边界验证。
- `source_freeze.json`、`delivery_manifest.json` 与 ZIP SHA-256：源码、交付文件及包完整性。

`portable/` 是首次 DLL 依赖冲突的失败包，仅保留诊断；`portable_v2/`、`portable_v3/` 为中间验证版本。请使用 `portable_v4/` 或最终 ZIP。冲突与修复证据见 `checks/dll_resolution_fix.json`、`checks/dll_audit_v2.json`。中断留下的 `frozen_gui_v2/` 和较早版本 `frozen_gui_v3/` 不是最终验收记录。


## 2026-11-06 最新边界决定

用户明确答复：“保留严格边界，暂不接受该例外”。客户端 turn-diff 元数据例外未获接受；Production 含 .git 完全只读的要求继续有效，整体验收为未通过，目标保持 blocked。本条取代交付时“等待用户确认”的状态描述，既有功能验证结果与原始差异记录保留。不清理、不回滚 Production 或其 .git，不执行 Git 写命令。边界决定的机器可读记录见 artifact 中的 boundary_exception_decision_20261106.json。
