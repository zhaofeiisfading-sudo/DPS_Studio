# TASK-014 · PDV Studio Research

任务日期 2026-11-06；本地最终验收跨至 11-07。研究分支 `codex/research_2/global-path-ridge-v2`，起点 `301689a`。

**Windows 测试包**：[下载 ZIP](PDV_Studio_Research_TASK014_Windows_x64.zip)。完整解压，运行文件夹内的 `PDV Studio Research TASK014.exe`。本地原生 Windows 验收通过。GitHub 工作流尚未远端验证。

- **低频平台**：在 16 条新种子波形的 1266 个共同支持中心，2048 点匹配 FFT 的 RMSE 为 1.497 m/s，单峰局部拟合为 0.268 m/s。单峰用时低于双峰，但整个 48 条波形集上，给简单阶段映射增加低频精修只将含缺失失败率从 14.67% 降至 14.64%。保留专用研究实现，未把它加入自动默认路径。[算法报告](ALGORITHM_REPORT.md)
- **默认窗**：Research Balanced 采用 1024/64。TASK-010 的共同中心结果支持覆盖与失败率取舍。快速起跳可用 512/128；极快或长稳态段有单独的实验预设。相邻帧共享样本，输出间隔不等于可分辨瞬态宽度。
- **软件**：修复确认事件后导出零点无法启用；人工时刻和用户采用的自动候选都可以作为另一通道的导出零点。取消常驻开发说明和失效 STFT 控件，保留 SI 换算、质量标志和导出来源。冻结旧研究网格，修复历史回放随默认窗漂移。[流程审计](CODE_AUDIT.md)
- **验收边界**：真实数据 13 文件、17 通道；仅报告可观测频差与覆盖。Windows 包实际完成双通道经典与人工分段分析、导出、修正和五轮切换。历史指纹与缺失归档导致非 GUI 回归仍有 5 项失败，具体文件和原因见[验收记录](VALIDATION.md)。

## 数据与复现

`synthetic.csv` 保留各阶段、候选及经门控结果。汇总使用 `summary.csv`，共同支持分析使用 `low_paired.csv`，真实观测在 `real.csv`。科研图存于 `figures/`，检查和界面截图存于 `checks/`，当前解包版在 `portable/`。实验数据、图件和 ZIP 在本地交付，Git 仅纳入轻量源码与文档。

从仓库根目录运行；路径示例使用新建的结果目录，避免覆盖本次数据。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -c scripts/build/windows-constraints.txt -e ".[dev,research]"
$env:PYTHONPATH = "$PWD/src;$PWD"
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$r = "artifacts/TASK-014/replay_new"
.\.venv\Scripts\python -m scripts.research.task014.study --output $r
.\.venv\Scripts\python -m scripts.research.task014.summarize --run $r
.\.venv\Scripts\python -m scripts.research.task014.paired --run $r
```

研究复现需要本地 TASK-009 索引及其只读数据。桌面安装与打包不需要这些输入。Windows x64 构建可按根 README 执行 PyInstaller，或在 GitHub Actions 运行 **Windows Research test build**。任务不自动推送或创建标签。
