# TASK-010 指标与源码入口

`config.json`和`PROTOCOL.md`为注册参数与方法。`experiment.py`不接收真值；`run.py`负责外部评分、原始数据核验、数据/轨迹保存、原冻结结果重评分。`summarize.py`按波形计算宏平均与配对bootstrap。`benchmark.py`逐参数独立子进程串行计时3次并探测Windows工作集及tracemalloc峰值。`transient.py`只做GT标记频率上的外部窗口混合诊断，不是重建算法。`plot.py`只读结果画图，`qa_pdf.py`先解析PDF到JSON再渲染。

候选、支持和校正速度分别存储；校正速度全NaN。原生帧数为floor((N−L)/H)+1，共同中心按整数索引选择，边界不补。全运动失败包含消光与缺失。静止/纯噪声不填零、不加入运动RMSE；假事件与假支持单列。低速RMSE、快变、起跳后40ns和全运动分别评价。主阈值77.5m/s，另有38.75/155m/s敏感性失败数。

源数据与物理原始数据全部保留。完整数值表在runs/v01/tables，逐案例表在runs/v01/cases。每个主矩阵H>1是所指H1轨迹的整数子集；读取它的runtime_s空值表示复用，不代表零耗时。成本看cost/v01和summary/v02/cost_summary.csv。原14方法保留frozen_tables原表及frozen_common_rescored的共同中心评分；新支持门控与旧门控不同，禁止把两者差异归为窗长。

未改变Production、core、默认参数或LiF公式；没有promotion、commit或push。任何将研究预设正式加入GUI/Production的实现是独立后续任务。
