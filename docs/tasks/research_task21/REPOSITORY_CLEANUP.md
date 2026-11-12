# research_task21｜仓库治理

根目录的 `tools/` 已迁入 `scripts/dev/legacy/`：9 个 Python 文件，原脚本的项目路径解析同步更新。TASK-019 的 5 个构建入口留在 `scripts/build/`；spec、约束和运行资源仍由 `packaging/`、`resources/` 管理。`notebooks/` 保留。`outputs/production_runs/` 是既有 CLI 接口；`logs/` 和 `results/` 各只有一个已跟踪的占位文件。未改动 Research 工作区或 Git 历史。

Windows 和 macOS 的构建入口要求在 `build/<task-id>/` 使用新目录，验证过的 ZIP 才发布到 `release/`，禁止覆盖既有 ZIP。没有运行构建；macOS 复建需另行生成与当前源码和环境一致的 Windows 数值参考。更新了 `.gitignore`、`AGENTS.md`、卫生技能和只读检查器，识别异常根目录、误跟踪、安装包位置、SHA-256 重复包及 artifacts 内与 raw 相同的文件。

| 范围 | 初次扫描文件长度总和 | 交付扫描文件长度总和 |
|---|---:|---:|
| TASK-019 隔离区 | 1,325,382,947 B | 1,325,382,947 B |
| `build/` | 3,027,041,222 B | 3,027,041,222 B |
| `release/` | 457,030,365 B | 457,030,365 B |
| `outputs/` | 102,513,207 B | 102,513,207 B |
| `artifacts/`（含本任务新增证据） | 1,922,315,717 B | 2,043,141,803 B |

**本轮实际释放 0 B。** 用户已确认两批删除；复核通过，但执行工具的自动审批以 `blocked by policy` 拒绝了整批删除命令，也拒绝了单独删除空 `dist/` 的尝试。没有文件被删除。NTFS 文件分配量由 `FileStandardInfo` 读取：隔离区 1,328,579,152 B，加 macOS CI 外层 ZIP 66,756,608 B，另有 5 份哈希一致的历史 raw 副本，占 18,964,480 B；合计 1,414,300,240 B（约 1.32 GiB）。文件分配量不含目录和 MFT 元数据；整卷剩余空间还受其他进程影响。

已确认但尚未删除的范围（清单见 `artifacts/research_task21/audit/{storage_pre_delete,verified_individual_deletions}.json`）：

- `artifacts/research_TASK19/quarantine/`：63 项、1,704 个文件。源码名下仅有 `__pycache__` 中的字节码；其余为工具缓存、已知 PyInstaller 中间物、3 个与保留正式 ZIP SHA 一致的 ZIP，以及 3 棵已逐文件核对的分发树。v0.1.4 的树与 `build/task030_release_v014/PDV_Studio_v0.1.4.zip` 一致，与正式 ZIP 不同。候选 ZIP 保留。
- `build/task031_phase2_retry_20261009/release_artifact.zip`：唯一成员与 `release/PDV_Studio_v0.1.4_macos_arm64.zip` 的 SHA-256 一致。另有空的根目录 `dist/`。
- 5 份副本：TASK-019 冻结源码中的 `docs/原始数据.csv` 副本、3 份 TASK-019 测试副本、1 份本轮初始基线测试副本。确认卡片估计 6 份，现场只找到这 5 份；它们与 `data/raw/20260607.csv` 一致。现行测试已改为直接只读使用既有参考文件。仓库根下**已跟踪**的 `docs/原始数据.csv` 同样与该 raw 文件一致，是历史 macOS 复现的引用输入，本轮未移动、修改或重新暂存；发布负责人应另行决定它的公开范围及参考迁移。

`release/` 的 5 份现有正式 ZIP 原地保留：Windows v0.1.3 iconfix、v0.1.4、v0.1.5、v0.1.6，以及 macOS arm64 v0.1.4。以下历史候选的 SHA-256 与正式 ZIP 不同，保留其证据和用途，未提升为正式发布：

| `build/` 下的路径 | SHA-256 前缀 | 用途或待确认 |
|---|---|---|
| `task029_release/PDV_Studio_v0.1.3.zip` | `554304eeb9bc` | 初次构建候选 |
| `task029_release_verified/PDV_Studio_v0.1.3.zip` | `c695f5cd4387` | TASK-029 验证交付，早于 iconfix；历史留存待决定 |
| `task030_release_v014/PDV_Studio_v0.1.4.zip` | `0e6db59fbb16` | TASK-030 候选，包含隔离分发树的等价成员 |
| `task031_windows_release/PDV_Studio_v0.1.4.zip` | `744256ae8ef3` | Windows/macOS 比对候选 |
| `task031_windows_release_final/PDV_Studio_v0.1.4.zip` | `5aeba841d1f9` | TASK-031 Windows 参考验证包 |

其余历史构建目录混有独有的验收结果、日志与 PyInstaller 产物，逐目录体积见 `audit/build_inventory.txt`。未批量删除。`dist`、这些候选及尚未删除的副本使卫生严格模式仍返回 1；Git 索引项检查通过。Production 根目录已更接近 Research，但存储治理尚未达到同等整洁程度。

可在用户自己的 PowerShell 7 中运行 [清理脚本](../../../artifacts/research_task21/audit/apply_confirmed_cleanup.ps1)。默认只复核，显式加 `-Apply` 才删除并写入 `cleanup_applied.json`（含整卷前后可用空间）。脚本拒绝越界、链接、非空 `dist/`、不匹配的哈希或变更后的隔离清单。运行后重新检查 raw、包和 Git；脚本不暂存、不提交。

发布收尾时复核了用户已执行的清理。隔离区、外层 ZIP、空 `dist/` 和 5 份副本均已移除。D 盘可用空间在该次清理前后增加 1,414,197,248 B。5 份正式旧 ZIP 的 SHA-256 与清理前一致。卫生严格模式仍列出 `build/` 中 5 份不同哈希的历史候选。

`docs/原始数据.csv`、旧参考表和生成的说明书副本及导出移出 Git 索引，本地文件保留。完整回归的真实数据用例直接只读访问本地 raw，公开 CI 采用显式排除清单，mock 测试使用自建的合成输入。Git 既有历史按原样保留。
