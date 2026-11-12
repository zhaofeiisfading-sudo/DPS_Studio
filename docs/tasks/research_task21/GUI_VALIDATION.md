# research_task21｜GUI 验收

主图区的「速度曲线」和「加速度曲线」是两个独立标签；各自只有一个物理量轴。速度与加速度之间直接切换时，沿用通道、结果来源和横向时间视野；仍可在各页单独平移、放大、恢复范围。加速度图使用 10⁹ m/s² 刻度，CSV 用 m/s²。速度的角度和窗口面板维持 TASK-019 布局；Dechirp 本身不应用这些修正。

加速度页的两个算法入口是「速度差分」和「Dechirp 直接估计」。原始差分为默认，「算法设置」中可选旧局部线性拟合；Dechirp 下同一区域显示窗点数、斜率上限和最低 R²。切换到直接估计会立即清空原曲线；后台完成后才画拟合通过点。更换算法、数据或关闭标签会取消未使用的计算。通过帧数可见，悬停查看逐类质量数量。空值留断点。

用 Production 真实 `20260607.csv` 的 ch1 启动 Windows Qt 窗口，通过鼠标点击切页和移动光标。核对两算法的图形数组，切回差分再核对一次；放大后切回速度，时间范围一致。复核页勾选原始差分、局部拟合和 Dechirp 后执行实际导出，再读取加速度 CSV 与 metadata，逐点核对直接加速度、质量标记和窗口参数。

| 证据 | 原生窗口截图 |
|---|---|
| 速度 | [velocity.png](../../../artifacts/research_task21/native_final/velocity.png) |
| 速度差分 | [difference.png](../../../artifacts/research_task21/native_final/difference.png) |
| Dechirp 与光标 | [dechirp.png](../../../artifacts/research_task21/native_final/dechirp.png) |
| 高级参数 | [dechirp_settings.png](../../../artifacts/research_task21/native_final/dechirp_settings.png) |
| 速度复核与三类导出 | [export.png](../../../artifacts/research_task21/native_final/export.png) |

截图为 Qt Windows 后端从已显示的窗口抓取，1320 × 780 逻辑像素，DPR 2；记录见同目录 `desktop.json`。完整运行命令：

```powershell
$env:PYTHONPATH = 'src'
python -m scripts.research.research_task21.validate artifacts/research_task21/native_new --desktop
```
