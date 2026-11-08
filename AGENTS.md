# DPS Studio Research：长期工作约定

## 边界与科学计算

- 唯一可修改的工程是当前 Research 仓库。Production 及其 Git 只读；不自动 commit、push、merge 或改写历史，不用 `git clean -fdx`、`git reset --hard`。
- `data/raw/` 永远只读，不移动、覆盖或删除。保留有效未提交源码、唯一科研成果和冻结记录；无法确认用途或唯一性的对象只列人工清理清单。
- 内部使用 SI；表观速度与修正速度分开存储。保留测量、实验先验、算法推断、质量诊断及手工操作来源；不静默插值、平滑、删点或填补不可靠测量，使用 NaN 和质量标志。
- 物理修正以 `core/physics/` 当前已验证实现及其测试/来源记录为准：角度投影与 LiF Rigg 2014、1550 nm、[100] 模型的单位、配置和适用边界必须显式保留。不得另加静态折射率因子或未经核验的公式；本条不扩展模型适用范围。

## 目录与依赖

| 路径 | 职责 |
|---|---|
| `src/dps_studio/` | 完整可安装的软件：core、gui、algorithms、research 等真实职责；core 不依赖 GUI |
| `scripts/` | dev、build、launchers、maintenance、workflows 与 research 执行入口 |
| `tests/`、`configs/` | 测试/轻量确定性夹具、正式配置与可复现参数 |
| `docs/tasks/TASK-NNN/` | 研究报告、协议、任务记录；继承的旧工作区记录在 `docs/tasks/inherited/` |
| `artifacts/TASK-NNN/` | 图像、结果、实验输出；`tmp/` 集中缓存与临时文件 |
| `release/` | 手动构建的最终发布包 |
| `data/`、`.github/`、`.agents/skills/` | 只读实验输入、仓库自动化、仓库专用 Skill |

- 根目录仅放标准入口和少量工程配置。禁止创建 TASK 专属脚本、缓存、临时环境、pytest 目录和构建中间目录；不随意增加一级目录。
- 正式源码不放 artifacts，研究报告不放 src；不复制整套算法形成第二份实现。研究执行脚本按任务放 `scripts/research/taskNNN/`，继承研究放其 `inherited/` 子树。
- 移动文件须同步修复 import、测试、配置、资源、构建入口、GitHub Actions 和当前使用的文档链接；保持单一职责、合理类型标注及功能一致，不进行无关大重构。

## 开发、缓存与构建

- Windows 使用 PowerShell 7。通过 `scripts/dev/run.ps1 -Task TASK-NNN -Python <python> ...` 启动开发、测试和检查；它配置 TMP/TEMP、pytest basetemp、Ruff/mypy、Matplotlib、pip 与构建缓存，集中到当前任务的 `artifacts/.../tmp/`。明确设置的仓库外缓存也可使用。
- Python 字节码默认禁写；直接调用工具时遵守同样的缓存约束。任务结束清理已确认可重建的临时文件，保留必要指标和验证结论。
- 维护的 PyInstaller 配置在 `scripts/build/`；手动构建用其入口。构建不依赖私有 raw、artifacts 或 Production；运行所需资源必须纳入源码/包配置。
- Git 跟踪轻量源码、测试、配置和正式文档；artifacts、release、构建输出、缓存、环境、大型数据和安装包不进入 Git。解除历史产物跟踪不得删除本地唯一成果。

## 每次 TASK 的开始与收尾

- 按需检查 `AGENTS.md`、`.gitignore` 和目录规范。涉及结构调整、Git 治理、构建目录管理或收尾检查时，优先使用 [repo-hygiene](.agents/skills/repo-hygiene/SKILL.md)。
- 新增文件类型、缓存目录、实验输出或构建产物时检查忽略规则；改变结构、流程、构建方式或长期约束时检查本文件。已有规则足够时不改文件，不重复追加规则，不新增 TASK 专属白名单。
- 增加与改动风险相称的测试，运行 pytest、Ruff 和适当的 mypy/回归检查，如实记录失败。检查新根目录文件、Git 状态/暂存区、构建依赖及必要资源，防止大型误提交或运行必需文件被忽略；核对 raw/Production 边界。
- 在 `docs/tasks/TASK-NNN/` 写简洁结论；在 `D:\Research\Notes\05项目\dps` 留轻量 Obsidian 日志，含任务、日期、分支、状态、结论、改动文件、artifact、核心结果、测试、Git/raw/Production 边界和下一步。完成请求后停止。
