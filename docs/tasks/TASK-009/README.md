# TASK-009｜TASK-008 独立研究包与论文图件

任务日期：2026-11-05。目标工作树：`D:\Code\Python_Projects\DPS_Studio_RESEARCH_CLEAN`。本包仅用于 Research；保留 TASK-008 的冻结算法、协议、基准、结果与负结果。

- [图件索引与中文图注](FIGURE_INDEX.md)：10 张 Origin 原生主图、3 张补充图，成品在 `figures_final/`。每图有 PDF、SVG、600 dpi PNG、数值来源与图注；主图另有 `.opju`。
- [迁移报告](MIGRATION_REPORT.md)：来源、目标、修复、验证、已知限制。逐文件来源与 SHA 见 [migration_files.csv](../../../artifacts/TASK-009/migration_files.csv)。
- [原研究比较报告](../TASK-008/COMPARISON.md)、[冻结协议](../TASK-008/PROTOCOL.md)、[全部14方法的原统计表](../../../artifacts/TASK-008/tables)。
- [数据索引](../../../configs/research/task009_data_index.json)：13 个原始文件、17 个电压流；`result`、图片及占位文件不作为算法输入。

## 研究结论的边界

88 条有运动真值的独立合成波形共有 6952 个运动目标帧。Coherent-VP（静止杂散预测加 VarPro）的支持后含缺失失败率为 8.70%，完整 M0-768 为 13.64%；逐波形宏平均差的原配对 bootstrap 95%区间为 −11.51 至 +1.68 个百分点，跨零，不能宣布普遍优于完整基准。前者支持覆盖率为91.47%，有限支持点RMSE为8.90 m/s，必须结合覆盖与分母阅读。

连续强加速族中 Dechirp/VarPro 有条件收益；强静止杂散的可预测模型值得继续研究。15 m/s 初相压力下，VarPro/Pencil 候选RMSE分别约641.9/3523.3 m/s；时域优化也存在错误解。弱信号、真实支路身份和零速可辨识性均未解决。真实实验没有 Ground Truth，图中的 `v=λf/2` 仅采用1550 nm假设的等效速度；校正速度保持独立且为NaN。

## 在本工作树运行

使用已有 `dps-studio` 环境，不需要安装新依赖。命令在仓库根目录、PowerShell 7 中运行：

```powershell
$py = 'D:\miniconda3\envs\dps-studio\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = "$PWD\src;$PWD"
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'

& $py -B scripts/research/inherited/task009/run_task009_research.py list
& $py -B scripts/research/inherited/task009/run_task009_research.py replay --output artifacts/TASK-009/replays/new_smoke
& $py -B scripts/research/inherited/task009/run_task009_research.py run --input data/raw/20260607.csv --voltage-column 1 --method varpro --output artifacts/TASK-009/replays/new_raw
& $py -B scripts/research/inherited/task009/check_task009_research.py
```

输出目录必须尚不存在；`--method all` 可运行全部14方法。`replay --full` 可重跑96条独立合成、50条低速压力和全部真实电压流；本次复用冻结结果，仅重放必要的168条合成轨迹和42条真实轨迹。方法只获得原电压，不接收真值。`run` 输出候选频率、支持频率、质量标志、假设波长下的等效速度，以及单独的全NaN校正速度。

数据适配器只把冻结逻辑记录映射到目标中的同SHA文件，不修改算法、参数或电压。部分DAT在目标中采用平铺文件名，另外3个缺少的CSV原样保存在 `source_data/raw_supplement/`。旧测试以原逻辑13文件为合同，故使用上述测试入口激活索引；不通过改写冻结测试制造通过结果。

## 重绘而不重跑估计器

```powershell
& $py -B -m scripts.research.task009.prepare_figures --output artifacts/TASK-009/figure_data/new_version
& ./artifacts/TASK-009/scripts/render_origin.ps1 -DataDirectory artifacts/TASK-009/figure_data/new_version -OutputDirectory artifacts/TASK-009/renders/new_version
& $py -B -m scripts.research.task009.plot_supplements --output artifacts/TASK-009/supplements/new_version
& $py -B -m scripts.research.task009.publish_figures --data artifacts/TASK-009/figure_data/new_version --native artifacts/TASK-009/renders/new_version --supplements artifacts/TASK-009/supplements/new_version --output artifacts/TASK-009/new_figures
```

主图使用本机 Origin 2021 的私有 COM 会话，完成后关闭自己的会话。原生ASCII导入后逐点读回核验，NaN段分别绘制；没有重采样、平滑、抽稀或填补。Origin 2021原生SVG导出不可用，因此SVG由矢量PDF转换，字形为路径；文字/数据/样式的原生编辑使用OPJU。PDF经本机Ghostscript嵌入Times New Roman，主图保持矢量。补充热图的单元格为矢量；谱图在矢量容器内为600 dpi栅格。

本机依赖及版本记录于 `replays/independent_smoke/environment.json` 和 `provenance/junction_probe/checks/`。绘图脚本显式使用现有Windows字体及TeX Live/Poppler路径；更换机器需配置这些工具路径，算法本身不需要Origin。未强行安装软件，未伪造Origin工程。

`figures_final/` 为论文成品；`figures/`、`renders/`、`figure_data/v01`至旧版本、`checks/origin_smoke*` 为保留的开发与失败记录，不应混用。未迁移与TASK-008无关的其他历史研究，这些旧artifact仍可能通过保留的junction引用源目录，不属于TASK-008/TASK-009复现入口。
