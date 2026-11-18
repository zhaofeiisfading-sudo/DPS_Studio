# Production TASK-023 Hotfix · Pass 2

Production `main`，HEAD `b6557b015683d34428c384291d4a828824962cee`。

## 文件拖放与导入

Windows 文件拖放的源端需要等待目标端返回。原来的 `dropEvent()` 在返回之前读取文件预览并进入导入设置的模态事件循环。现在拖动阶段只检查 MIME 数据中的本地文件 URL。放下时优先接收复制操作，保存路径并注册零延时回调。回调在 `dropEvent()` 返回后检查当前工作状态，再进入与“打开数据”相同的导入流程。

- 取拖放内容中的首个本地路径。同一轮事件处理前连续收到的拖放只处理最后一次。已有模态窗口或导入、分析任务时丢弃待处理拖放，关闭窗口时清空待处理路径。
- 原始信号、时频图、脊线、速度、加速度和结果比较的绘图控件及 viewport 均将文件拖放交给主窗口。
- 缺失、非普通文件或无法访问的路径显示提示。结构预览只读取并解析前 32,768 个字符附近的有界样本，遇到截断的物理行时舍去该行。设置对话框保留分隔符、编码、表头和映射的手动调整，并在预览无效或所选列无法通过数值检查时阻止确认。确认后仍由后台读取器校验完整文件。
- 回归测试以 Qt 事件驱动模态设置对话框与后台读取器。`20260630-1.csv` 导入了 200,001 行、两路信号，测试核对了首点时间和电压。覆盖打开文件、取消选择、取消设置、重复导入、活动模态窗口、活动导入任务、关闭窗口及异常文件后的恢复。现有 `ImportWorker` 没有运行中取消接口。

## 快速分析图标

使用 24×24 坐标内的单个实心三角形，顶点为 `(7, 5)`、`(19, 12)`、`(7, 19)`，默认颜色为 `#1e293b`。像素测试覆盖 1× 和 2×，同时核对原折线区域全透明。Windows 原生 Qt 工具栏截图已目视核对，快速分析按钮与相邻按钮等高、同一水平线，图标逻辑尺寸为 20×20。截图位于 `artifacts/task023_hotfix/figures/pass2_toolbar_windows.png`。

拖放顺序和图面事件传播由 Qt 回归测试验证。未手动操作 Windows 资源管理器进行原生 OLE 拖放。

## 检查结果

| 检查 | 结果 |
|---|---|
| 定向 pytest | 83 passed in 21.80s |
| 全量 pytest | 871 passed in 156.23s |
| Ruff | 通过 |
| `mypy --strict src/dps_studio` | 96 个源文件，0 个问题 |
| `pyside6-lrelease` | 758 条已完成译文，0 条未完成 |
| `git diff --check` | 通过 |
| 仓库卫生严格检查 | 退出码 1，仍为已有的 5 个 `build/` ZIP；意外根目录项、索引内生成物、重复包和 artifacts 内 raw 副本均为 0 |

`20260630-1.csv` 的 SHA-256 在修改前后均为 `203b182e477e1e08214551977a00313eaf6f17a71391d83875f6f879dc3a0a74`。`data/raw/`、`configs/`、`AGENTS.md` 的 Git 状态干净。HEAD 未改变，暂存区为空。

## 代码和测试文件

- `src/dps_studio/gui/main_window.py`
- `src/dps_studio/core/io/delimited_preview.py`
- `src/dps_studio/gui/import_dialog.py`
- `src/dps_studio/gui/plot_chrome.py`
- `src/dps_studio/gui/icons.py`
- `src/dps_studio/gui/translations/pdv_studio_en.ts`
- `src/dps_studio/gui/translations/pdv_studio_en.qm`
- `tests/unit/gui/test_task023_inspector.py`
- `tests/unit/gui/test_task023_hotfix.py`
