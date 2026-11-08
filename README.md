# PDV Studio Research

Windows x64 的 PDV 信号分析与研究源码仓库。经典 STFT 和人工分段工作区共用只读输入；算法池保留参数、人工先验、质量标志及算法来源。表观速度和物理修正速度分别保存，内部使用 SI。Research Balanced 使用 W1024/H64；真实实验数据没有物理真值，质量合格不等于物理分支已确认。

## 目录

```text
src/dps_studio/
  core/                    数值处理、物理修正、分段、导出
  gui/                     Qt 应用、工作区、图标和翻译
  algorithms/waveform/     唯一的波形估计器实现
  research/                可安装的研究支持模块
scripts/
  dev/                     统一环境、测试和 GUI 检查入口
  build/                   手动构建入口、约束和 PyInstaller spec
  launchers/               兼容的 Windows 启动器
  maintenance/             只读治理检查及迁移审计
  workflows/               文件分析和导出工作流
  research/taskNNN/        独立研究复现；inherited/ 保存继承研究
configs/                   正式配置和数据索引（不含私有数据）
tests/                     单元、集成、GUI 回归与轻量夹具
docs/tasks/TASK-NNN/        报告、协议、任务和验证记录
artifacts/TASK-NNN/         本地科研结果；tmp/ 集中缓存（不进入 Git）
release/                   现有发布 ZIP 与将来的手动发布输出（不进入 Git）
data/                      本地实验输入；raw/ 永远只读
.github/                   手动 GitHub Actions 构建
.agents/skills/repo-hygiene/ 仓库专用 Codex Skill
```

TASK-016 的结构、迁移、清理和验证见 [任务记录](docs/tasks/TASK-016/README.md)。旧工作区任务记录保存在 `docs/tasks/inherited/`，与本 Research TASK 编号分开。

## 环境与源码运行

使用 PowerShell 7 和 Python 3.12 x64。把环境建在仓库外；已有合适环境可直接复用，无须重新安装。

```powershell
# 用你的 Python 3.12 路径创建仓库外 venv，并安装项目与开发/研究依赖。
pwsh -File scripts/dev/setup_env.ps1 -Python 'C:\path\to\Python312\python.exe'
$researchPython = Join-Path $env:LOCALAPPDATA 'DPS-Studio/venvs/research/Scripts/python.exe'

pwsh -File scripts/dev/run.ps1 -Python $researchPython -Task DEV -m dps_studio.gui
```

`environment.yml` 也定义了独立的 `dps-studio-research` Conda 环境；从仓库根目录使用它。不要更新或裁剪 Production 的既有环境。兼容的 `.bat` 默认使用这个 Research 环境；复用旧环境时显式设置 `DPS_STUDIO_CONDA_ENV`。

统一入口会临时设置 TMP/TEMP、pytest basetemp、Ruff/mypy、Matplotlib、pip 和 PyInstaller 缓存到 `artifacts/<Task>/tmp/`，结束后恢复调用进程的环境。Python 字节码默认禁写。根目录不保存临时环境或构建中间目录。

## 检查与回归

```powershell
# 只读，检查根目录、缓存、已跟踪 blob 大小及暂存产物；退出码 0/1/2 = 无问题/发现问题/检查失败。
& $researchPython -B scripts/maintenance/check_repo_hygiene.py
& $researchPython -B scripts/maintenance/check_repo_hygiene.py --staged-only

pwsh -File scripts/dev/run.ps1 -Python $researchPython -Task DEV -m ruff check src scripts tests
pwsh -File scripts/dev/run.ps1 -Python $researchPython -Task DEV -m mypy src/dps_studio/core src/dps_studio/gui
pwsh -File scripts/dev/run.ps1 -Python $researchPython -Task DEV -m pytest tests/unit --ignore tests/unit/gui -q
pwsh -File scripts/dev/run.ps1 -Python $researchPython -Task DEV scripts/dev/check_gui.py --task DEV
```

历史科研回归需要本地 `artifacts/` 冻结结果和 `configs/research/task009_data_index.json` 所列只读实验输入；这些数据不在 Git。完整套件的历史失败和 Qt 生命周期限制应读 [VALIDATION](docs/tasks/TASK-016/VALIDATION.md)，不能据此声称全绿。

不含私有数据的基础回归可直接运行：

```powershell
pwsh -File scripts/dev/run.ps1 -Python $researchPython -Task DEV -m pytest -q tests/unit/test_repo_hygiene.py tests/unit/test_analysis_profiles.py tests/unit/test_local_peak_candidates.py tests/unit/test_acceleration.py tests/unit/test_local_acceleration.py tests/unit/test_acceleration_export.py tests/unit/test_task015_stage_strategies.py tests/unit/gui/test_task014_export.py
```

必要时按用例隔离有 Qt 生命周期问题的模块：

```powershell
pwsh -File scripts/dev/run.ps1 -Python $researchPython -Task DEV scripts/dev/check_gui.py --task DEV --only test_task012_workspaces --isolate-cases
```

## 手动构建

从 GitHub 克隆源码后安装 `.[dev]` 即可检查和构建软件，不需要 Production、私有 raw 或本地科研 artifacts。当前配置将图标、翻译和默认配置纳入发行目录；普通安装的配置由 Hatch 的包资源映射纳入。

```powershell
# 只核验 spec、入口、资源和动态算法路径，不产生包。
pwsh -File scripts/build/build_windows.ps1 -Python $researchPython -Task DEV -CheckOnly

# 仅在你需要发行时手动执行；生成 release/PDV_Studio_Research/，拒绝覆盖既有目录。
pwsh -File scripts/build/build_windows.ps1 -Python $researchPython -Task DEV
```

GitHub Actions 的 **Windows Research manual build** 只通过 `workflow_dispatch` 启动，构建目录在 `artifacts/CI/`。TASK-016 没有执行 PyInstaller、生成新 EXE/ZIP、启动云端构建或更新远程仓库。只有你审阅并提交/推送这些本地变更后，远程克隆才会包含本次治理结果。

## 研究复现与数据边界

```powershell
# 列出 14 个已迁移波形方法；无需加载 raw 或 artifacts。
pwsh -File scripts/dev/run.ps1 -Python $researchPython -Task DEV -m dps_studio.research.task009_runtime list
```

研究执行脚本按模块运行，例如 `-m scripts.research.task010.run --help`。结果写到 `artifacts/TASK-NNN/`；报告在 `docs/tasks/TASK-NNN/`。TASK-008 的协议与原始源码冻结记录保存在 [TASK-008](docs/tasks/TASK-008/PROTOCOL.md) 和其 `provenance/`；迁移链记录在 [SOURCE_MIGRATION](docs/tasks/TASK-016/SOURCE_MIGRATION.json)，不会重写原始科研冻结哈希。

当前物理修正以 `core/physics/` 的已验证实现及适用条件为准，包含角度投影和指定条件的 LiF 模型；不额外叠加静态折射率因子。不得将演示波长或真实数据的算法输出宣称为已确认物理速度。

开始和收尾遵循 [AGENTS.md](AGENTS.md)；结构/Git/缓存/构建目录治理优先使用 [repo-hygiene Skill](.agents/skills/repo-hygiene/SKILL.md)。规则已经覆盖时不重复修改 AGENTS 或添加 TASK 白名单。
