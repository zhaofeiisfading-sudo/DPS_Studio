# TASK-013 Git 清理报告

**已完成；没有push、force push、远端分支删除、硬重置或破坏性清理。**

- 开始：Research分支`codex/research_2/global-path-ridge-v2`，HEAD`b8faed27ad63cfd19a7acfb657d6afddc149a98f`，工作区干净；远端研究分支实际为`26066704fbb924a1c70ef208d97ba81bc70407a0`。误提交仅在本地，未进入该远端分支；证据为`checks/git_before.json`中的实时ls-remote与提交关系。
- 原Research是Production的linked worktree，公用元数据位于Production/.git。为遵守绝对只读边界，在Research内建立独立.git，使用本地只读file传输导入远端基点的浅历史，没有复制6 GiB旧对象库，也没有改Production登记、refs、index或对象。旧worktree登记保留在原处，本任务未运行prune/repair/remove。
- 可恢复备份：原.git指针、原.gitignore、原未推送提交的已验证bundle（161,335,217字节；SHA-256 `457085cad31ff9024ded185b7545f5e026e11a2af0a5bfa20c79ab079a8bf673`），均保存在`git_backup/`。bundle以26066704为前提，基点在独立仓库中；原共享仓库的b8faed27引用仍保持原样。备份大对象不属于新仓库待推送历史。
- TASK-012的27个源码/测试/构建文件以本地提交`ea50506`完整保存，源码实际字节未变；发布包完全保留。release共456个文件、321.00 MiB，前后逐文件SHA-256一致。四份历史采集/生成表只解除跟踪，物理文件保留，见`checks/untracked_data_preservation.json`。
- `.gitignore`精确排除release/dist/build、EXE/DLL/打包ZIP、缓存、数值文件与生成图件；保留.spec、构建脚本、配置、TASK-008～013的选定轻量源码/报告和必要输入索引。审计文本清单与确定性测试CSV有明确例外，没有笼统忽略所有配置或所有artifacts。
- `.githooks/pre-commit`已通过本仓库的`core.hooksPath=.githooks`启用。标准库脚本检查实际暂存对象，拦截构建目录、二进制、数值数据和>2 MiB文件；强制add后的拦截也有真实临时Git测试。新克隆需自行运行`git config --local core.hooksPath .githooks`启用hook，ignore规则随代码生效。

后续正常提交不会重新纳入本地发布包或大型研究输出；不要使用`git add -f`或绕过hook来纳入生成物。Git仍保留远端26066704的既有祖先语义；不声称删除了远端旧历史中的数据。本地最终提交/对象审计、远端复核和clean状态见`checks/git_final.json`。

Production源码、配置、发布包、raw及完整.git逐文件SHA-256一致；其大型生成目录与TASK-008～012已有成果使用名称/大小/mtime清单核对一致。Research原src与configs未修改。恢复时先在新的研究恢复目录中读取bundle和基点，避免覆盖当前工作区。
