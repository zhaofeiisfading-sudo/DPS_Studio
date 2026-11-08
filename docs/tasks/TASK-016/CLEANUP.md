# 安全清理结果

日期：2026-11-08。计量为文件逻辑字节数（GiB = 2³⁰ bytes），不等同于 NTFS 压缩/硬链接后的实际可用空间增量；未用磁盘剩余量作基线。

| 范围 | 审计删除量 |
|---|---:|
| 历史构建、临时环境、测试输出、缓存与重复数组 | 9,458,651,524 bytes（8.809 GiB） |
| 本轮已完成测试/工具的 tmp 与被替代迭代日志 | 160,470,592 bytes |
| 清理执行表合计 | 9,619,122,116 bytes（8.959 GiB），159 个候选 |
| 工作树盘点净变化 | 12.004 → 3.219 GiB；排除 Git 和外部联接目标 |
| 当前 `.git` | 5,215,669 bytes；历史未改写 |

清理包括旧 pytest 根目录和错误拼接目录、两个临时 venv、PyInstaller 中间文件与旧 onedir staging、历史工具缓存、已完成的 TASK-016 临时测试/安装布局副本。未创建垃圾备份。

release TASK-012 解压目录的 455 个成员、TASK-014 解压目录的 452 个成员，与保留 ZIP 逐个 SHA-256 一致且没有额外文件，才删除解压副本。其余 staging 由 `.toc`、`pyvenv.cfg`、`_internal` 和 PDV exe 等实际工具结构核验为可重建输出。4 个现有最终 ZIP 哈希互不相同，全部保留。

额外去重的数值回归 NPZ 均逐文件核对大小和 SHA-256：保留 `artifacts/TASK-011/checks/real_reference_v2/` 原数组，移除相同副本，保留每份原 report.json 和显式去向映射。没有删除唯一科研数组、冻结指标、协议、最终图件或原始输入。

根目录的旧 packaging、tools 和空 task008 树已可逆迁至 `artifacts/TASK-016/retained_empty_directories/`。自动审批两次拒绝了空目录删除，仅给出 `blocked by policy`；未绕过该拒绝删除这些目录。原 `.codex`、`.vscode` 保留。

无法证明安全删除的对象单独列在 [RETAINED_ITEMS.md](RETAINED_ITEMS.md)，包括 46 个外部联接、历史 Git 备份和未完成逐项取证的旧图版/快照。它们是人工判定对象，默认保留，不代表建议直接删除。

逐项清单：`artifacts/TASK-016/audit/cleanup*-plan.json` 与对应 `*-executed.json`；目录计量见 [DIRECTORY_INVENTORY.md](DIRECTORY_INVENTORY.md)。
