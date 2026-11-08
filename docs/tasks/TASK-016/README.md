# TASK-016：仓库结构与长期治理

日期：2026-11-08。分支：`codex/research_2/global-path-ridge-v2`。状态：工程治理完成；5 项既有科研归档/冻结测试失败保留并如实记录。

本次将报告、脚本、配置和波形实现从生成产物中分离，完成 291 次逐文件迁移、5 份相同源码合并，以及 7 个失效的一次性入口的非执行归档。估计器原有 25 条源文件记录的 SHA-256 前后相同，没有修改算法公式、参数或 GUI 交互设计。

| 项目 | 结果 |
|---|---|
| 本地物理文件逻辑大小 | 12.00 → 3.22 GiB；不含 `.git`、外部联接目标 |
| 历史清理列表 | 8.809 GiB |
| 含本轮临时数据的全部清理列表 | 8.959 GiB，159 个文件/目录候选 |
| Git 历史产物路径解除跟踪 | 131 条，仅改本地索引；唯一成果保留 |
| 治理检查 | `clean`，默认只读 |
| pytest 非 GUI | 1173 通过、5 个既有失败；最终补充迁移回归 110/110 |
| GUI | 180 项隔离通过；整进程/模块限时限制见 VALIDATION |
| Ruff / mypy | 全 `src scripts tests` Ruff 通过；全 `src` mypy 185 文件通过 |
| Skill | 官方格式验证通过；真实 `skills/list` 返回 repo / enabled=true |
| 边界 | raw 11 项目录文件哈希一致；Production 元数据/内容哈希一致；12 条既有源码暂存项保留 |

## 最终结构

```text
src/dps_studio/              core、gui、algorithms/waveform、research 等软件职责
scripts/dev/                run.ps1、setup_env.ps1、check_gui.py
scripts/build/              手动构建入口、约束、spec 与历史配置
scripts/maintenance/        只读 hygiene 检查、物理盘点、TASK-016 审计工具
scripts/workflows/          文件分析与导出入口
scripts/research/taskNNN/    独立科研执行；inherited/ 保存继承研究
configs/                    配置与轻量数据索引
tests/                     单元、GUI、集成与夹具
docs/tasks/TASK-NNN/        报告和协议；inherited/ 区分旧工作区编号
artifacts/TASK-NNN/         本地科研结果；当前 TASK-016 下分 audit/ 与 validation/
release/TASK-NNN/           4 个既有最终 ZIP
data/raw/                  永远只读；补充输入在 data/research/TASK-009/
.github/、.agents/skills/   手动 CI 与仓库 Skill
```

根目录只有 6 个标准文件和职责目录/标准元数据目录。`packaging`、`tools`、历史 pytest 根目录、根 build 和错误拼接的缓存目录均已退出根目录；空目录的审批限制与可逆迁移见 CLEANUP。

- [MIGRATION.md](MIGRATION.md)：关键路径与源码指纹链。
- [CLEANUP.md](CLEANUP.md)：删除证据、计量口径和人工判定清单。
- [VALIDATION.md](VALIDATION.md)：测试、构建、Skill、Git/raw/Production 边界。
- [DIRECTORY_INVENTORY.md](DIRECTORY_INVENTORY.md)：一、二级目录大小、文件数与用途。
- [SOURCE_MIGRATION.json](SOURCE_MIGRATION.json)：逐文件原/新路径及双向指纹。

日常治理复用根 AGENTS 与 repo-hygiene Skill，不重复追加规则。运行及手动构建命令见根 README。本次没有生成安装包、EXE、ZIP，没有 commit、push、merge、改写历史或启动云端构建。远程克隆要包含本次结果，仍需用户审阅并提交/推送本地变更。
