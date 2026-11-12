# research_TASK19｜最终验收

| 检查 | 结果 |
|---|---|
| 修改前完整 pytest | 795 通过；无历史失败 |
| 完整非 GUI pytest | 655 通过；`checks/acceptance_non_gui.txt` |
| 全部 GUI 单元与交互 pytest | 147 通过；`checks/verified_gui.txt` |
| Ruff | `ruff check .` 通过 |
| strict mypy | 应用源码、macOS 构建/参考工具和卫生检查器，95 个文件通过 |
| 卫生检查与技能 | `--strict` 通过；异常根项 0，误跟踪生成文件 0，大于等于 25 MiB 的跟踪文件 0；技能校验通过 |
| Windows 桌面 | Qt `windows`，两个缩放条件；新版两组各 12 张实窗截图、旧版 10 张 |
| 真实数据与导出 | 三条记录的数组和 9 个 CSV 逐字节一致，三个 JSON 仅时间戳不同 |
| Git | `git diff --check` 与 `git diff --cached --check` 通过；仅历史 artifacts 的取消跟踪留在索引，源码和文档变更留在工作区 |
| 原始数据 | `data/raw` 的 24 个相对路径及 SHA-256 前后一致；`raw_before.json`、`raw_after.json` |
| Research | 独立 `.git`；仅只读查询。两次采样的 HEAD 与索引 SHA-256 相同，工作树新增 TASK-018 报告/脚本；并行变动未被当作本任务产物。 |

日志路径以 `artifacts/research_TASK19/` 为根。环境为 Windows、Python 3.12.13、PySide6 6.11.1、PyQtGraph 0.14.0。自动化 GUI 测试使用 offscreen；单独的桌面验收使用真实 Windows 平台窗口，未混用。

迭代曾出现旧布局断言和英文文案断言失败、导入列初值边界及导航联动问题。修复后保留了几何、定位、交互及科学断言；更新的断言对应明确改变的 GUI 行为，最终无未解决的测试回归。详见 [Bug 审计](BUG_AUDIT.md) 的功能及性能边界。

没有构建安装包，没有执行 commit、push、merge 或 rebase。macOS 流程的脚本路径、解析器和参考测试已验证，未在 Windows 上代跑 macOS 原生构建。仓库清理的永久删除被自动审批拦截，隔离目录仍占空间。
