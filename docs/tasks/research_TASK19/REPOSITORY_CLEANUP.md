# research_TASK19｜仓库治理

在 `D:\Code\Python_Projects\DPS_Studio` 的 `main` 工作；开始时状态干净、比 `origin/main` 多 1 个既有提交。Production 和 `DPS_Studio_RESEARCH_CLEAN` 的 `.git` 是不同的本地目录。Production 的历史 worktree 列表仍有旧注册记录；没有执行 prune、迁移或历史改写。历史 macOS 报告原样保留。

下表为文件长度总和，不代表 NTFS 实际分配块。全树数为采样快照，测试和截图还会向本任务目录追加文件。可比口径将整个 `artifacts/research_TASK19/` 排除。

| 范围 | 治理前：文件 / MiB | 治理后：文件 / MiB |
|---|---:|---:|
| 全树（剔除本任务隔离目录与生成物） | 26,526 / 12,951.60 | 24,844 / 11,687.48 |
| `build/` | 20,647 / 4,125.83 | 19,144 / 2,886.81 |
| `release/` | 3,620 / 2,286.38 | 3,620 / 2,286.38 |
| `outputs/` | 529 / 97.76 | 529 / 97.76 |
| `data/raw/` | 24 / 38.83 | 24 / 38.83 |
| 全树（含本任务目录，采样时） | 26,815 / 12,967.00 | 29,297 / 13,096.76 |

前后一级和二级目录统计在 `artifacts/research_TASK19/checks/disk_before.json` 与 `disk_after.json`。从活动目录移入隔离区的 1,704 个文件共 1,325,382,947 字节（1,263.98 MiB）：Python/pytest/Ruff/mypy 缓存、PyInstaller 工作文件、三个重复 ZIP 和三个与发布目录逐文件相同的 dist 树。每个原路径、字节数和判定依据见 `checks/cleanup_manifest.json`。自动审批拒绝永久删除，返回 `blocked by policy`；采用可逆移动，没有永久删除，也没有释放隔离区所占磁盘空间。

工程迁移：

- Windows/macOS 构建、图标及 macOS 数值参考工具集中至 `scripts/build/`。macOS workflow、spec 提示、图标开发说明和调用测试已更新。维护的 spec 和约束文件仍在 `packaging/`；历史报告保留当时执行的旧命令。
- 只读卫生检查器位于 `scripts/maintenance/`；任务验收工具在 `scripts/dev/`。默认 pytest、Ruff、mypy 缓存归入 `artifacts/.cache/`。
- `artifacts/` 中 1,081 个历史生成文件只从 Git 索引移出，原文件和历史提交仍在。没有用 Git 清理工作目录。历史输出位置及 CLI 的 `outputs/production_runs/` 保留。
- `docs/原始数据.csv` 是既有 macOS 可移植数值参考的实际输入，保留其文件路径和内容。此文件与只读的 `data/raw/` 是不同的维护边界。仓库中没有发现应移除的根目录虚拟环境。

人工处理建议：

| 完整路径 | 理由 |
|---|---|
| `D:\Code\Python_Projects\DPS_Studio\artifacts\research_TASK19\quarantine` | 仅含清单确认的 1,704 个可重建或重复文件；可在人工核查后整体清除，理论释放约 1.23 GiB 的文件长度。 |
| `D:\Code\Python_Projects\DPS_Studio\build` | 余下约 2.82 GiB，包括 v0.1.x 的独有验收图、数值基线、日志及未证实重复的历史分发树。按历史发布任务审阅后再清理。 |
| `D:\Code\Python_Projects\DPS_Studio\release` | 约 2.23 GiB 的历史正式版本和压缩包。需要保留哪些版本由发布负责人决定。 |
| `D:\Code\Python_Projects\DPS_Studio\outputs` | 约 97.76 MiB 的既有分析输出及最近一次运行指针。需要决定保留哪些实验结果。 |

`.git` 约 6.06 GiB，包含版本历史和本地 worktree 元数据，本次没有做对象清理。卫生检查器以 25 MiB 为默认大文件报告阈值，严格模式只对异常根目录项和误跟踪生成物报错，不会删除文件。
