# 文件迁移与引用修复

日期：2026-11-08。所有移动限定当前 Research；raw 不移动、不修改。逐文件移动前后先核对 SHA-256，目标存在或内容变化即停止。

| 原路径 | 新路径 | 原因 |
|---|---|---|
| `artifacts/research_clean_task8/*/implementation.py` | `src/dps_studio/algorithms/waveform/*/implementation.py` | 14 个波形实现归入单一可安装源码包 |
| `src/dps_studio/algorithms/task008/` | `src/dps_studio/algorithms/waveform/` | 按职责命名；与 artifact 中 5 个相同副本合并 |
| TASK-008 的 data/runner/reproduce 等模块 | `src/dps_studio/research/waveform/` | 研究支持可安装；不从生成目录导入 |
| TASK-008 的 verify/report 一次性旧入口 | `docs/tasks/TASK-008/provenance/*.py.txt` | 无 Python 调用者，旧验收/笔记写入语义已关闭；保留非执行记录 |
| TASK-009/010/013/014/015 研究执行代码 | `scripts/research/taskNNN/` | 执行脚本与实验输出分开 |
| TASK-015 的 cleanup/package/delivery 等 5 个旧入口 | `docs/tasks/TASK-015/provenance/*.txt` | 关闭过期删除、打包和暂存操作，保留记录 |
| `artifacts/research_clean_task9/data_index.json` | `configs/research/task009_data_index.json` | 轻量索引可进入 Git/普通安装资源 |
| `artifacts/research_clean_task10/config.json` | `configs/research/task010.json` | 可复现配置归位 |
| TASK-008 源码冻结与补充注册 JSON | `docs/tasks/TASK-008/provenance/` | 保持原始字节，不重写历史科研指纹 |
| `artifacts/research_clean_task9/source_data/` | `data/research/TASK-009/source_data/` | 3 个只读补充输入，SHA-256 不变 |
| `artifacts/research_clean_task8`～`15` | `artifacts/TASK-008`～`TASK-015` | 生成结果统一命名，唯一科学结果保留 |
| artifact 中正式 Markdown、根 COMPARISON 等 | `docs/tasks/TASK-NNN/` | 正式报告与生成结果分开 |
| docs 根继承 TASK 报告 | `docs/tasks/inherited/TASK-.../` | 区分旧工作区同号 TASK |
| docs 根参考 CSV/DAT 与图片 | `data/reference/legacy_docs/`、`docs/reference/figures/` | 输入和参考图各归其位；raw 不动 |
| 根 `RESEARCH_WORKTREE.md` | `docs/development/RESEARCH_WORKTREE.md` | 工程说明归 docs |
| `packaging/*.spec` / 约束文件 | `scripts/build/specs/`、`scripts/build/windows-constraints.txt` | 单一维护构建入口 |
| 根 `.bat` | `scripts/launchers/` | 修复相对根路径，转接 PowerShell 7 统一缓存入口 |
| 原 scripts/tools 零散研究脚本 | `scripts/research/inherited/task.../` 等 | 按真实职责/研究任务分组，修复导入与 `__file__` 层级 |
| `scripts/check_git_hygiene.py` | `scripts/maintenance/check_repo_hygiene.py` | 替换历史 TASK 白名单；旧实现删除，hook 转接新只读检查器 |
| `results/`、`logs/` | `artifacts/inherited/` | 保留既有结果与日志，退出根目录 |
| artifact 内最终 ZIP | `release/TASK-NNN/` | 现有 4 个最终 ZIP 保留；未生成新包 |

`SOURCE_MIGRATION.json` 保存原路径、最终路径、迁移前/后指纹与去重去向。原冻结 JSON、原 README_before 均按初始哈希保留。原估计器 25 条记录（含 5 个副本，20 个唯一原文件）字节相同；缺失子包仅补标准 `__init__.py`，没有复制第二套数值实现。

动态 import、相对 import、测试、资源、配置、Windows 启动器、PyInstaller 和 GitHub Actions 已同步调整。`runtime_paths` 同时支持 src checkout、普通安装的 configs 资源映射和冻结程序；在无原仓库访问权限的复制布局中验证了启动。

冻结图件/旧报告内的来源路径保持历史语义，通过 `research/source_records.py` 的显式迁移链定位当前文件。17 组相同数值数组的副本去重后，原 report.json 保留；读取旧数组的复现入口使用映射找到保留的 reference。历史指纹原本不一致的测试不会被迁移链改判为一致。

26 份迁移文档的有效本地链接已重定位；历史快照/原文记录有意保留原始路径含义。盘点和审计脚本位于 `scripts/maintenance/TASK-016/`，是本次过程记录，不应对已治理仓库重复执行一次性 apply 操作。

完整清单见 `artifacts/TASK-016/audit/migration-plan.json`、`followup-migrations.json`、`output-migrations.json`、`cleanup-supplement-plan.json`。
