# TASK-011 设计与迁入边界

本任务沿用 Research 分支 `codex/research_2/global-path-ridge-v2`，基线 HEAD `364b9878`。
Production 参考为 `main` / `677a22df`（v0.1.6）。任务日期 2026-11-05，跨日验证延续到 2026-11-06。

## 运行结构

- 选择性迁入共享 core 与成熟 GUI 的变更文件、资源路径和默认配置，不复制仓库、Git、原始数据、旧构建或生产用户配置。全部前像存于 `pre_migration/`，逐文件来源见 `migration_manifest.json`。
- `MainWindow` 保留 Production 处理流程；`ResearchMainWindow` 增加一个人工分段工作区。经典流程直接调用原有 adapter/core，不经过新分段调度。
- `core/segmentation` 不依赖 GUI。`EstimatorRequest` 使用绝对时间 s、电压 V、波长 m，`BeatEstimate` 返回原生时间中心、通过质量门槛的 Hz、未通过确认的候选 Hz、质量与实现来源。组装后以 `v_app = λ f / 2` 转为 m/s，再调用原有物理修正链。
- 算法注册表统一提供 STFT、Dechirp、VarPro、Clutter VarPro 和明确排除的 NaN 算法。新增算法实现 `Estimator` 协议并注册即可；GUI 选项直接来自同一注册表。
- 三个研究算法与 shared common 的本地副本来自 TASK-008，冻结算法字节保持；TASK-009/010 档案不作为 GUI 运行依赖。TASK-010 的高重叠/长窗能力由既有 STFT 参数控件设置，不添加研究算法或新默认值。

## 人工区段与质量

每个通道有独立方案。新增、拖动、数值调节和删除竖线产生连续区间；端点按 `[start,end)` 分配，最后端点包括在内。阶段仅为实验员标签，不认证真实物理支路；建议不自动更改算法。删除边界保留左段设置，应用到全部通道为显式操作。

Production 时频图中可见的矩形 ROI 决定分段页的时间范围与用户频带；不以旧版隐藏的全局时间控件替代框选结果。分段页的“ROI 范围”复用成熟 RawSignalView 蓝色范围项，松开两端即提交共享时间范围，裁剪分段方案并使旧结果失效；原始记录不裁切。

估计器接收完整原始记录；边界只选择输出中心，不裁剪窗口，也不重置事件检测、原始相位或安静前缀。跨人工边界的窗口标记 `BOUNDARY_CONTEXT`。不同算法保留原生中心，不插值对齐；绘图逐段断开，NaN 断线，不跨段计算新平滑轨迹。极短区段可能无中心，metadata 明确记录 0 frames。

STFT 分段使用正式质量通过频率；候选点单独保存。经典 Production 连续工作曲线和可选显示平台保持其既有行为与来源标记。分段输出不会继承显示平台或填零。研究算法的事件/前缀门槛、5 MHz–8 GHz 原生搜索范围、128 点步长与参数均明确记录；额外按用户频带筛选。启发式波形支持不是精度、目标身份或真实速度认证。

角度和 LiF 沿用 Production 已核验模型与参数来源，不新增物理公式。角度先于窗口修正；保留表观、角度修正与最终速度各列。原始拍频为非负幅值，不能据此自动判断运动方向。

## 状态、异常与文件

后台线程只执行不可变请求。编辑、ROI、数据或修正参数变化会使分段结果失效；旧版本回调被丢弃。逐算法异常转为 NaN 与 `ALGORITHM_ERROR`，无静默回退，其他区段继续。运行中防止关闭和冲突操作。

CSV 保留全部行、绝对时间、拍频、候选拍频、三种速度、valid、quality、segment、stage、algorithm。metadata 包含完整分段方案、源文件 SHA、算法参数、诊断和物理修正来源。保存分段 JSON、导出目录均拒绝覆盖旧结果。

应用独立使用 `DPS Studio Research / PDV Studio TASK011 Test` Qt 配置命名空间，窗口明确标注 Research/Test。入口启用 Production 与 data/raw 写保护。PyInstaller 只打包 Research 内模块、默认配置和 GUI 资源，不包含真实输入或历史实验成果。

Production 全目录（含 .git）与两侧 raw 的前后 SHA/mtime 核验由 `task011_boundaries.py` 记录。暂停前全目录核验通过；恢复聊天后，客户端在共享 `.git` 中生成 Codex turn-diff 检查点及对象，最终严格 `.git` 不变检查未通过，详见 `boundary_detail.json`。Production 非 `.git` 文件、main/HEAD/index、两侧 raw 与 TASK-008～010 冻结成果不变。未执行 Git 写命令；不切分支、不提交、不推送、不合并、不 promotion。客户端元数据例外确认状态见最终 `acceptance.json`。
