# 验收与边界核验

日期：2026-11-08；分支 `codex/research_2/global-path-ridge-v2`；HEAD `31270d1e20606a54bda1e5daab4c858d3a664ad2`。本轮没有 commit、push、merge、reset、Git 历史改写或外部构建。

## 回归与质量

| 检查 | 实际结果与范围 |
|---|---|
| 迁移前非 GUI | 1161 通过、6 失败，约 92 s |
| 最终完整非 GUI | 1173 通过、5 个既有失败，约 102 s；新增的去重路径用例见下项 |
| 最终迁移专项 | 110 / 110，含最新跨路径/复制安装布局/源码指纹/波形/策略回归 |
| 治理相关最终用例 | 40 项通过，包含 force-add、索引大 blob、本地文件更小/消失、只读性、Unicode 路径、资源与去重指纹链 |
| GUI | 24 个模块 154 项通过；TASK-012 的 26 项逐用例隔离通过；合计 180 项 |
| Ruff | `src scripts tests` 全部通过 |
| mypy | `src` 全部 185 文件通过；未新增忽略错误规则 |
| Python/PowerShell | Python AST：185 src、160 scripts、114 tests；10 个 PS 脚本在 PowerShell 7 语法解析通过 |
| 构建输入 | 4 份 spec 的入口、资源和动态算法路径有效，使用惰性 stub，未执行 PyInstaller |
| GitHub Actions | YAML 及 9 个本地脚本引用有效；仅 workflow_dispatch；没有云端运行；冻结启动显式使用 Windows Qt 插件 |
| 忽略与依赖 | 8 个必需资源/配置/Skill/构建入口可见，7 类输出被忽略；没有 artifacts/release 路径进入当前索引 |
| 只读检查器及 hook | Python 3.9/3.12 均可运行；完整/暂存检查 clean；真实 pre-commit hook 检查通过 |

经典 STFT、人工分段/算法池、LiF/角度修正和 CSV 导出由上述单元/集成/GUI 回归覆盖；本次没有作新的物理准确率判断或算法研究。

迁移前完整单进程 pytest 在既有 `test_task016_guided_analysis` 的 Qt 生命周期位置中止，不能声称单进程完整套件通过。模块隔离的初次 TASK-012 以 180 秒限时超时；其 26 项之后逐项隔离全部通过。当前 GUI 驱动默认限时 300 秒并保留可配置参数。不能把隔离通过写成原聚合运行通过。

保留的 5 项既有失败：

- `tests.unit.test_task023a_imm_mht_tracker::test_fixed_upstream_and_raw_guardrails`
- `tests.unit.test_task023f_proposal_recovery::test_frozen_e4_constants_and_no_production_writes`
- `tests.unit.test_task023g_retention_audit::test_frozen_f_source_production_and_raw_hashes`
- `tests.unit.test_task025_informative_interval::test_frozen_original_source_and_config_hashes`
- `tests.unit.test_task025_informative_interval::test_calibration_provenance_excludes_held_out_and_is_immutable`

前 4 项是历史冻结源码/配置指纹；最后一项缺少旧 TASK-025 归档 stream。失败名与迁移前一致。原第 6 项 logical raw inventory 失败由正式数据索引接入而修复，13 文件/17 streams 均验证输入哈希。没有修改旧期望指纹来制造绿色结果。

收尾曾手动将 Ruff 缓存移到 C 盘而 TMP 在另一盘，触发 OS error 17（跨盘重命名）；该次日志保留为 `validation/ruff-cache-cross-volume.log`。最后采用 `--no-cache` 完成全仓只读 Ruff 检查并通过；统一 run 入口的 tmp/cache 同盘流程此前正常。失败缓存仅生成两个标签文件，已清理。

## 脱离原工作区启动与构建边界

复制 src 与 configs 到独立安装布局，禁止读取原 Research、Production 和旧 TASK021A 路径，验证默认配置、算法池和 14 方法注册后，实际进入 Windows Qt 事件循环。保留 `validation/isolated-startup.json`。这是安装布局与资源映射模拟验证，没有构建 wheel/安装包，也不等于云端或冻结程序的实际构建验收。

维护入口为 `scripts/build/build_windows.ps1`；`-CheckOnly` 实测成功、`built=false`。spec 根路径已修复；默认图标、SVG、qm 和 configs 均存在且未被错误忽略。普通安装的 configs 通过 Hatch force-include 映射；未安装新全局依赖，现有共享环境未改写。

## Skill 验收

`.agents/skills/repo-hygiene/SKILL.md` 采用 name/description YAML frontmatter，`agents/openai.yaml` 提供元数据，遵循 [OpenAI Skills 文档](https://developers.openai.com/codex/skills/)。skill-creator 的 quick_validate 通过。

实际调用当前 Codex app-server 的 `skills/list`、`forceReload=true`，返回 `name=repo-hygiene`、`scope=repo`、`enabled=true` 和本仓路径。没有启动模型或新 chat。证据：`validation/skill-discovery.json`。收尾已实际按此 Skill 执行。

## Git、raw、Production

- `data/raw` 的 11 个目录文件（含占位文件）SHA-256 前后相同；另外 3 个补充输入只移动，索引总计 13 个有效文件、17 路电压流 SHA-256 校验通过。
- Production 的 26,529 条物理文件元数据、1,473 项内容 SHA-256 和联接映射相同；可变 Git 元数据在比较范围内。没有向 Production 或其 Git 发出写操作。
- Research HEAD/分支相同；初始 TASK-015 的 12 个 src/tests 暂存 blob/模式条目保留。131 个生成目录路径仅从本地索引解除跟踪，必要文档/源码已迁出，唯一成果保留。
- 本轮重构的新路径及规则修改保留在工作区供审阅；**当前暂存区不是本轮完整可独立构建的快照**。用户提交前应整体审阅并暂存迁移的新路径和删除，不能仅提交原 TASK-015 暂存内容。
- 4 个 release ZIP 的哈希均互异，没有新 EXE、ZIP 或安装包；根目录没有本轮临时文件，TASK-016/tmp 已清理。

当前检查器只审计工作树布局、工具缓存和当前索引 blob，不扫描/修改历史；`clean` 表示治理检查无问题，**不表示 Git 工作区无改动或全部历史 pytest 通过**。

证据分为 `artifacts/TASK-016/audit/` 与 `validation/`，保护边界见 `audit/boundary-validation.json`；前后物理目录清单见 `audit/inventory-before.json`、`inventory-after.json`。所有目录扫描均跳过外部 symlink/junction，不访问其目标来做清理。
