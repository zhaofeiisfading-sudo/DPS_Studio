# DPS Studio 组会汇报重制版提纲

## 汇报设定

- 日期：2026 年 7 月 26 日
- 页数：15 页
- 听众：课题组组会
- 主线：旧软件的证据链问题 → Python 数值链重建 → 真实数据结果 → 当前可信度边界 → 下一阶段依赖顺序
- 视觉：暖白背景、砖红强调、深灰正文、少量青绿色表示“初步实现”；不使用生成式图片、廉价图标、粗箭头和红框卡片堆叠。
- 字体：中文为微软雅黑；英文、数字、公式和物理符号为 Times New Roman；代码与路径为 Consolas。

## 逐页结构

### Slide 1：DPS Studio：从 PDV 原始信号到可追溯表观速度曲线

- 封面只保留题目、组会汇报和日期。
- 视觉角色：留白封面；用 `V(t) / S(t,f) / v_app(t)` 表示整套汇报对象，不放实验结果图。

### Slide 2：旧流程缺少参数、处理步骤与结果之间的可追溯映射

- 数据处理参数不透明，曲线无法对应到完整配置。
- 人工选峰和参数调整难复现，假峰也缺少可核验依据。
- 原始数据可能被直接处理或覆盖，输入与结果边界不清。
- 视觉角色：左侧一句结论，右侧为“看不到 / 说不清 / 回不去”的证据清单。

### Slide 3：当前优先级：数值链验证先于 GUI 完善

- 第一层：数据安全——只读输入、原始文件不覆盖、单位明确。
- 第二层：算法复刻——先复刻读取、STFT、脊线和速度换算。
- 第三层：可信判断——弱信号、假峰、双通道和修正模型需要证据。
- GUI 放在数值链稳定之后。
- 视觉角色：三层递进结构，用细线与大号层级编号，不用按钮式流程图。

### Slide 4：Python 的价值在于让计算、配置和检查留在同一份记录里

- NumPy / SciPy：数值计算与 STFT。
- Matplotlib：从相同数据和配置重复生成图。
- PySide6 / PyQtGraph：后续 GUI；不把尚未完成的 GUI 写成成果。
- pytest / Ruff / mypy：自动测试、代码检查和类型检查。
- Required source:
  - `pyproject.toml`
- 视觉角色：依赖分层与源码来源并列，不做 Python 优点百科。

### Slide 5：当前处理链已经到表观速度，物理修正仍在链路之外

- 原始时间—电压 → 文件读取 → SignalRecord → STFT → 脊线 → 拍频 → 表观速度 → 描述性质量 → 导出。
- 已实现：读取、数据模型、STFT、脊线、表观速度、CSV/图和 manifest。
- 初步实现：连续性与谱质量证据。
- 未完成或待核验：LiF 修正、双通道自动择优/融合、GUI。
- 视觉角色：横向细线流程带；节点只用小圆点和文字，状态用颜色与图例表达。

### Slide 6：输入层先保留差异，再决定如何比较

- SignalRecord 使用 SI 单位，并把时间与电压保存为只读数组。
- 非均匀采样不会被静默重采样；标准 STFT 会明确拒绝。
- 两个电压通道量程不同，不能在输入层直接平均。
- Required image:
  - `assets/real/raw_voltage_dual_channel.png`
  - 来源：`data/raw/20260607.csv`；只截取事件附近显示窗；无平滑、插值和重采样。
- 视觉角色：左侧三条输入约束，右侧一张大图。

### Slide 7：单次 FFT 无法定位拍频在何时改变

- STFT 同时保留时间位置与局部频率结构。
- 横轴为相对事件时间，纵轴为频率，颜色为相对 STFT 幅值。
- 白线为当前候选脊线；它仍需质量证据，不等于自动获得真实物理速度。
- Required image:
  - `assets/real/stft_balanced_channel1.png`
  - 来源：`outputs/production_runs/run_20260724_004901_103968/balanced/pdv_channel_1/stft_analysis_band_with_ridge.png`
- 视觉角色：上方一句解释，下方全宽大图。

### Slide 8：参数共同决定时间、频率分辨率与搜索范围

- 参数表对比 Balanced 与 High time resolution：
  - Hann window；768 / 512 samples。
  - overlap 640 / 384 samples。
  - hop 128 samples。
  - nfft 4096。
  - ridge search 0.05–2.0 GHz。
- 解释窗长、hop、nfft 与搜索带的作用和边界。
- Required code image:
  - `assets/code/analysis_profiles_balanced_excerpt.png`
  - 来源：`src/dps_studio/core/analysis_profiles.py:136-145`
- 其他来源：
  - `configs/demo_dual_profile.toml:17-31`
  - `outputs/production_runs/run_20260724_004901_103968/balanced/profile_manifest.json`
- 视觉角色：左侧参数表与原因说明，右侧小段源码截图。

### Slide 9：脊线先给出拍频，波长明确后才能换算表观速度

- 公式：`v_app = λ₀ f_b / 2`。
- 当前结果为一侧频谱得到的无符号表观速度。
- `λ₀ = 1.55 μm` 是配置中的演示值，尚未与实验记录核验。
- apparent velocity 与 corrected velocity 必须分开；当前没有 LiF、折射率或入射角修正。
- 视觉角色：大公式 + 三个物理边界，不放假曲线。

### Slide 10：同一次真实运行把时频脊线对应到表观速度曲线

- 左：Balanced / channel 1 的 STFT 分析带与精修脊线。
- 右：同一 profile / channel 的事件区表观速度。
- 只展示同一真实运行中的两张大图，不把 preview 当正式测量。
- Required images:
  - `assets/real/stft_balanced_channel1.png`
  - `assets/real/velocity_balanced_channel1_event.png`
- 来源：`outputs/production_runs/run_20260724_004901_103968/`。
- 视觉角色：两张大图并列，底部保留解释边界与来源。

### Slide 11：双通道一致性不能替代通道可信度判定

- 两通道分别计算，不在原始电压层平均。
- 最新 Balanced 输出中，两通道首个候选表观速度约为 538 m/s 与 532 m/s。
- 描述性 dB 指标可作为证据，但不是 SNR、可信阈值或自动择优规则。
- Required image:
  - `assets/real/two_channel_latest_candidates.png`
  - 来源：最新 production run 两份 `apparent_velocity.csv`，只绘制 formal candidate，未平滑、插值或融合。
- 数据来源：
  - `balanced/quality_summary.csv`
- 视觉角色：左侧大图，右侧实际数值与结论。

### Slide 12：目前已经复刻了核心数值链，但完成度不等于可信度

- 能力清单：只读读取、SignalRecord、STFT、脊线提取、亚频点精修、表观速度、双通道输出、诊断与导出、自动检查。
- 状态分为“已实现 / 初步实现 / 未完成”，不按 TASK 编号罗列。
- 视觉角色：一列能力账本，状态点与证据路径对齐。

### Slide 13：当前结果能展示流程，还不能宣称是最终科研结果

- 弱信号区可能追到错误谱线。
- 起跳前平台和零速度区还需要物理判据。
- 参数选择会改变时频图细节。
- 双通道择优尚无正式规则。
- LiF 修正公式与实验波长未核验。
- GUI、打包和跨机器验收未完成。
- 视觉角色：从“生成曲线”到“曲线可信”的细线间隙图，六项未解决问题沿线展开。

### Slide 14：下一阶段按依赖顺序推进，AI 只做后期辅助识别

1. 非 AI 谱线增强与连续性约束。
2. 起跳点、平台区和弱信号质量判据。
3. 双通道质量择优。
4. 波长、LiF 修正和实验条件核验。
5. GUI 操作流程。
6. 打包部署与用户测试。
- 视觉角色：垂直时间轴；每一步只写预期产物，不把计划写成成果。

### Slide 15：当前重点已由曲线生成转向谱线追踪的可信度验证

- 已完成：真实 PDV 原始数据到表观速度曲线的基础数值链。
- 当前重点：弱信号谱线约束、双通道证据、波长与窗口修正验证。
- 后续：可信判断稳定后再完善 GUI、打包和用户测试。
- 视觉角色：一段自然总结与三行事实，不喊口号。
