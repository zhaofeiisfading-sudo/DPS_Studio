# TASK-010｜长窗口与高重叠 STFT 性能研究

2026-11-05，状态：实验完成，Research only。**推荐可选768/1024点＋H64/H32；保留原基准，不把2048＋H1作为通用默认。** 固定窗口下加密步长没有改善共同中心的频率/速度估计，只增加密度和相关性。长窗对平稳低速有条件收益，瞬态代价不能靠高重叠消除。

- [完整比较、结论与适用边界](COMPARISON.md)
- [论文图件、中文图注、PNG预览](FIGURE_INDEX.md)
- [注册协议](PROTOCOL.md)与[配置](config.json)
- [关键结果表](tables/key_results.csv)、[完整汇总](summary/v02/summary.csv)、[配对区间](summary/v02/paired_bootstrap.csv)、[原14方法重评分](summary/v02/frozen_summary.csv)
- [每配置时间采样密度、边界余量及中心跨度](tables/temporal_support.csv)
- [验证记录](VALIDATION.md)与[边界核验](checks/boundary_verification.json)

170条GT波形（96原主分布、50低速初相压力、24新种子确认），6714条合成配置结果；13真实原始文件、17电压流、170条实测配置；原14方法2044条冻结轨迹保留并在共同中心重评分。没有因NaN、消光、坏记录或负结果排除案例。原生与共同网格分开评价，支持RMSE/覆盖/含缺失失败同时报告。真实记录没有GT，1550 nm速度是假设等效表观速度，校正速度独立为NaN。

关键负结果：H1没有改善整体谱阈值起跳MAE；W512由3.512 ns变为4.042 ns，W2048由10.317 ns变为11.319 ns（成功检测者均值，漏检另报）。H1下W512/W2048的双频混合10–90%宽度约3.416/13.572 ns。主分布中，匹配宽带去均值W2048及双尺度选择相对W512的含缺失失败分别增加约3.22/0.91个百分点。

本地完整数据与源码以本目录为准。逐案例表、数据及轨迹在`runs/v01/`，完整合成指标为`runs/v01/tables/synthetic_metrics.csv`，实测指标为`runs/v01/tables/real_metrics.csv`。H>1主矩阵通过`trajectory`列指向同窗H1结果，按`(sample_indices−W/2) % H == 0`还原准确视图，不需插值；视图耗时留空。成本在`cost/v01/measurements.csv`独立计时，不能使用复用耗时。

## 复现

使用现有环境，不安装新依赖；PowerShell7，仓库根目录运行。所有输出目录必须不存在，重复运行请换名字。原基准仍可由TASK-009入口单独重放。

```powershell
$task10Py = 'D:\miniconda3\envs\dps-studio\python.exe'
$env:PYTHONPATH = "$PWD\src;$PWD"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
& $task10Py -B -m artifacts.research_clean_task10.run --output artifacts/research_clean_task10/runs/new_run
& $task10Py -B -m artifacts.research_clean_task10.benchmark --output artifacts/research_clean_task10/cost/new_cost
& $task10Py -B -m artifacts.research_clean_task10.transient --output artifacts/research_clean_task10/transient/new_transient
& $task10Py -B -m artifacts.research_clean_task10.summarize --run artifacts/research_clean_task10/runs/new_run --cost artifacts/research_clean_task10/cost/new_cost --output artifacts/research_clean_task10/summary/new_summary
& $task10Py -B -m artifacts.research_clean_task10.plot --run artifacts/research_clean_task10/runs/new_run --summary artifacts/research_clean_task10/summary/new_summary --transient artifacts/research_clean_task10/transient/new_transient --output artifacts/research_clean_task10/figures/new_figures
```

`plot.py`同时生成Origin原生伴随工程的数据规范；`scripts/render_origin.ps1`使用私有隐藏COM、ASCII导入与逐点读回，`publish_native.py`嵌入PDF字体并导出SVG/600dpi PNG。复杂矩阵用Matplotlib矢量单元格，全部主图保留可编辑SVG文字；两张Origin伴随图保留可编辑OPJU，SVG字形为路径。PDF先解析为JSON，再渲染与人工视觉检查。

## 文件、边界与云端

源码都在`artifacts/research_clean_task10/`，新增测试在`tests/unit/test_research_task010.py`；不改`src`、生产配置、旧Research实现或TASK-008/009结果。全部raw前后SHA-256、Git HEAD/index及Production代码/raw审计另附。未commit/push/promotion。

G盘路径在开始时确认可访问。手机成果副本位于`G:\我的云端硬盘\codex\pdv_studio_research\research_clean_task10`；复制关键文档、图件和表格，保留本地完整NPZ与源码。实际复制清单及逐文件SHA回读见`checks/cloud_sync.json`。不移动或删除本地文件，不覆盖云端不同版本。

`summary/v01`是成本测量前的完整速度汇总；`summary/v02`为加入独立成本表的最终汇总。失败和已弃用渲染版本若存在均保留，以FIGURE_INDEX列出的成品为准。
