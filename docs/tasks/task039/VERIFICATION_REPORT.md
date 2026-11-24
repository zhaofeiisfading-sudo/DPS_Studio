# TASK-039 验收报告 — 软件更新系统、意见反馈与 Windows 正式发行包

- **任务编号**：`TASK-039`（`task039`）
- **日期**：`2026-11-21`
- **仓库 / 分支 / 基线 HEAD**：`D:\Code\Python_Projects\DPS_Studio`（Production）/ `main` / `c03edbb639f0e8652f873563e06b6a6426ebf10d`
- **状态 / 结论**：`COMPLETED` / **PASS（软件更新检查与校验下载、意见反馈、Ruff / mypy strict / 1,028 项 pytest、正式 Windows x64 安装包构建与原位覆盖升级实测、用户 PDF 与 Agent 说明书更新、最终发布压缩包全部交付并通过核验）**

---

## 一、实现与修改文件

- **更新与反馈后端（纯标准库，无 GUI 依赖、无新增第三方包）**：
  - `src/dps_studio/updates.py`：基于仓库 `origin`（`zhaofeiisfading-sudo/DPS_Studio`、`main` 分支）查询 GitHub Releases API，严格过滤草稿、预发行版本、非 `main` 目标及非三段正式数字版本号；仅允许 HTTPS 及 GitHub 白名单域名（含跳转拦截校验）；通过 Release API `digest` 或 `PDV-Studio-Setup-x64.exe.sha256` 强制校验 SHA-256；流式缓存至 `<安装目录>\userdata\cache\updates\<version>\`（校验失败或取消即删除 `.part` 并阻断启动）；启动安装前传入 `/CURRENTUSER` 与 `/DIR=<安装目录>`，不绕过 Windows 安全提示。
  - `src/dps_studio/feedback.py`：提供 `bug` / `enhancement` / `feedback` 类别、Markdown 格式化及 GitHub Issues 预填 URL 构造（超长自动退化为剪贴板+仅标题 URL）；仅允许按用户主动勾选附带 5 项安全环境字段（`app_version`、`os`、`architecture`、`runtime_mode`、`ui_language`），绝不收集文件路径、用户名或实验数据。
- **GUI 窗口、菜单与双语资源**：
  - `src/dps_studio/gui/update_dialog.py`、`src/dps_studio/gui/feedback_dialog.py`、`src/dps_studio/gui/main_window.py`：在 `帮助` 菜单新增 `检查更新…` 与 `意见反馈…`；异步 `QThread` 检查/下载并在关闭窗口时协作取消与回收；支持启动时异步静默检查更新（`updates/auto_check_on_startup`，离线失败零弹窗，smoke/offscreen 模式自动跳过）；安装前明确提示保存结果并关闭其他 GUI 与 `pdv.exe` 后再退出安装。
  - `src/dps_studio/gui/translations/pdv_studio_en.ts` 与 `pdv_studio_en.qm`：补全全部新增 UI 英文译文并经 `pyside6-lrelease.exe` 编译（796 条）。
- **测试、发行说明与用户/Agent 文档**：
  - `tests/unit/test_updates.py`、`tests/unit/test_feedback.py`、`tests/unit/gui/test_update_and_feedback_dialogs.py`
  - `docs/RELEASE_NOTES_0.2.0.md`、`docs/USER_QUICK_START.md`、`docs/README_for_agent.md`、`docs/说明书.pdf`

---

## 二、正式交付物与校验摘要

| 产物 | 路径 | 大小 (bytes) | SHA-256 |
| --- | --- | ---: | --- |
| Windows x64 安装包 | `release/PDV-Studio-Setup-x64.exe` | 74,079,896 | `f0e0215455df273e4568066c5d7d31a24965035b4309fe53414d72cb8e879988` |
| 安装包校验文件 | `release/PDV-Studio-Setup-x64.exe.sha256` | 92 | 匹配上述 SHA-256 |
| 人类用户图文说明书 | `docs/说明书.pdf`（6 页 A4） | 1,608,421 | `d19dd132967eb9f5e55c6fad522ca2264c8fe99f400519f9d248991ac1f75783` |
| Agent 专用说明书 | `docs/README_for_agent.md` | 6,320 | `1c7a1703168ce0a4f2bcddbfd80be5531af62c3fb2647b817ae4ad5fcef9f0fe` |
| 最终发布压缩包 | `release/PDV_Studio_v0.2.0_Windows.zip` | 74,898,963 | `3d1cbc9fc9655c72346c3f5f74b92d5aca2ec30a04f145f5f7b4d7d35a74459c` |

- `release/PDV_Studio_v0.2.0_Windows.zip` 解压根目录 `PDV_Studio_v0.2.0/` 含 3 个文件（`PDV-Studio-Setup-x64.exe`、`说明书.pdf`、`README_for_agent.md`），经 `ZipFile.testzip()` 与逐成员 SHA-256 回读完全一致。

---

## 三、自动化检查与实机打包验证结果

| 检查项 | 结果 |
| --- | --- |
| `ruff check src tests scripts/build/build_windows_installer.py scripts/maintenance/check_repo_hygiene.py` | **All checks passed!** |
| `mypy --strict src/dps_studio` | **Success: no issues found in 102 source files** |
| 全量 `pytest tests` | **1028 passed in 196.53s**（含更新逻辑 61 项、反馈逻辑 7 项、GUI 对话框与 200% 小屏适配 20 项及全部已有 GUI/CLI/核心测试） |
| CLI 导入隔离 | `import dps_studio.cli` 后 `PySide6`、`dps_studio.updates`、`dps_studio.feedback` 均未加载 |
| 正式安装器端到端构建 (`scripts/build/build_windows_installer.py`) | **Exit 0**：PyInstaller 双入口构建 + 100%/125%/150%/200% ZH/EN GUI 烟测 + `data/raw/20260607.csv` 双通道 620 行 GUI/CLI CSV 逐字节一致 + 中文空格路径普通用户安装 + 原位覆盖升级保留 `settings.ini` 与自定义材料 + 保留/清除双模式卸载 + `%APPDATA%`/`%LOCALAPPDATA%` 零写入（清单：`build/task039_windows_installer/release_manifest.json`） |
| 弹窗与 PDF 视觉复核 | 实机截取 `06_update_dialog.png`、`07_feedback_dialog.png` 并经 Chrome + `pdftoppm` 逐页审查 6 页 `docs/说明书.pdf` |
| 边界与原始数据完整性 | `src/dps_studio/core/**`、`configs/**`、`AGENTS.md`、`.gitignore` 零改动；`data/raw/` 全部 24 个文件 SHA-256 前后 100% 一致；未执行 `git commit`/`push`/GitHub Release |
| 仓库卫生 (`check_repo_hygiene.py`) | `unexpected_root: 0`、`tracked_generated: 0`、`large_tracked: 0`、`duplicate_packages: 0`、`raw_copies_in_artifacts: 0`（仅存 5 个历史遗留 `build/task029..031` ZIP） |

## 四、已知与剩余事项

- `github.com/zhaofeiisfading-sudo/DPS_Studio` 仓库当前尚未公开发布正式 GitHub Release（联网实测返回空正式版本列表），因此端到端联网自动下载新版仅待首个正式 GitHub Release 发布后在线验证；下载缓存、断点隔离、进度回调、SHA-256 校验失败阻断及原位覆盖升级均已在本地自动化测试与 Inno Setup 实机测试中完成验证。
- `PDV-Studio-Setup-x64.exe` 仍为未配置商业代码签名证书的 `NotSigned` 安装包，按要求未绕过 Windows SmartScreen 提示，已在 `docs/说明书.pdf` 中给出标准提示说明。
