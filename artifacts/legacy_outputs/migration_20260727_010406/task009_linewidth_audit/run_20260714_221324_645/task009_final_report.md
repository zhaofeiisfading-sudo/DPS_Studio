# TASK-009 前序处理链审计、速度图细线化与最终参数终审报告

*完成日期：2026-07-14｜运行环境：D:\miniconda3\envs\dps-studio\python.exe｜结论：建议方案 A*

---

## ✅ 最终结论

TASK-001～TASK-007 均已按真实 import 与调用关系完成审计，除当前范围内没有实现证据的 TASK-004 外，其余任务仍在默认 BAT 的真实数值链中。TASK-008A 与 TASK-008B 会重算同一固定主链，再只读地产生诊断，不修改 ridge、速度或前序数组。没有发现核心数值 bug、隐藏平滑、去趋势、边界补帧、重采样、时间轴错位或非均匀采样误用。

本轮只修改默认总控实际调用的绘图脚本，并添加绘图数据完整性测试。修改前后完整数值指纹逐字节一致，8 个 CSV 逐字节一致，原始 CSV 的 SHA-256 前后不变。最终建议保留方案 A：`window=768, overlap=640, hop=128, nfft=4096`；没有达到运行 hop 64 对照的触发条件。

## 📋 二十一项交付清单

| # | 必须报告项 | 结果 / 证据位置 |
|---:|---|---|
| 1 | 开始前审计 | 本报告“开始前状态”；HEAD、status、diff、cached、测试基线和原始 SHA 均已记录 |
| 2 | TASK-001～008B 实际调用链 | `call_chain_report.md` 的时序图与任务映射表 |
| 3 | 核心与 legacy standalone preview 分类 | 当前核心链与两个未调用的 `plot_real_*` 脚本已明确分开 |
| 4 | TASK-004 真实状态 | `src/`、`scripts/`、`tests/`、`docs/` 范围内无实现、API、调用者或 BAT 入口证据 |
| 5 | TASK-001/002 原始数据保留 | 80,000 行、两通道各 80,000 点，独立读取逐点一致，无静默丢行 |
| 6 | `compute_stft` 完整关键参数 | 本报告“STFT 与前序数值审计” |
| 7 | 隐藏处理与时间轴错误 | 均未发现；4096 点 FFT 的窗内零填充已与时域边界补帧区分 |
| 8 | TASK-005/006/007 时间细节 | 无跨帧处理；005 逐帧 argmax，006 逐点换算，007 仅同帧三个频率 bin |
| 9 | 实际修改绘图文件 | `scripts/compare_real_ridge_refinement.py`；另新增绘图回归测试 |
| 10 | 修改前后 linewidth | 审计前散落的 1.5～1.7 主线宽；审计后集中常量 0.50～0.85，详见样式表 |
| 11 | 数值完全一致证据 | 前后完整指纹 SHA 均为 `293B...C8B4`；8 个 CSV 全部精确相同 |
| 12 | 与旧软件红线视觉比较 | 已生成对比图；仅作形状级参照，不伪装为同参数逐点比较 |
| 13 | hop 128 是否足够 | 足够；平台、下降、双通道、008A/008B 均无帧密度不足证据 |
| 14 | 最终默认参数建议 | 方案 A：768/640/128/4096 |
| 15 | 测试与质量门 | 221 passed；ruff、mypy、diff-check 全部通过 |
| 16 | 原始 SHA-256 | 前后均为 `ab9f656e...7db68f7353` |
| 17 | `git diff --stat` | 既有 tracked 差异仍为 3 files、329 insertions、5 deletions |
| 18 | 完整 `git status` | 本报告末尾原样列出 |
| 19 | 暂存区为空 | `git diff --cached --stat` 与 `--name-only` 均无输出 |
| 20 | 未 add、未提交 | 未执行 `git add` 或 `git commit`；HEAD 未变化 |
| 21 | 禁止范围 | 未做平滑、插值、删点、补点、自动跟踪、分支切换、通道选择、融合、LiF、GUI 或 AI |

## 🧾 开始前状态

- HEAD：`4cfaa500ab47800dec4259d9bb0cd6fe29db6943`。
- 工作区已有大量用户 tracked 与 untracked 内容；全程未删除、覆盖、回退或清理这些内容。
- 开始时 tracked diff stat：`scripts/plot_real_velocity.py`、`src/dps_studio/core/ridge/__init__.py`、`src/dps_studio/core/ridge/models.py`，合计 3 files changed、329 insertions、5 deletions。
- 开始时暂存区为空。
- 测试基线：218 passed；ruff 基线通过。pytest 仅有 `.pytest_cache` 写权限警告。
- 原始数据开始前 SHA-256：`ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353`。

## 🔗 真实调用链与文件分类

默认入口依次为 `run_demo_pipeline.bat` → `scripts/run_demo_pipeline.py` → 主分析/008A/008B 运行函数 → core API。详细 Mermaid 时序图、公开 API、直接调用者以及“影响数值 / 仅展示 / legacy”分类见 `call_chain_report.md`。

主数值链是：

```text
read_delimited_signals
  → SignalRecord
  → compute_stft
  → extract_peak_ridge
  → refine_peak_ridge_subbin
  → convert_ridge_to_apparent_velocity
```

`scripts/plot_real_stft.py` 与 `scripts/plot_real_velocity.py` 没有被 BAT 或 Python 总控导入、调用，标记为 `legacy standalone preview`；其旧参数未参与本轮判断，也未删除这些文件。

TASK-004 在本次规定搜索范围中没有实际实现、公开 API、直接调用者或当前主链痕迹。该结论只描述当前仓库状态，不推测仓库外历史。

## 📥 原始数据保真

真实 CSV 为 80,000 × 3；两个 `SignalRecord` 各保留 80,000 个样本。时间范围为 0.00055396025426～0.00055596022926 s，中位采样间隔 2.5000000008525147e-11 s，推导采样率 39,999,999,986.359764 Hz。重复时间点和非递增时间点均为 0。

读取器输出的时间列和两路电压列与独立 `numpy.loadtxt` 读取结果逐点完全一致。没有重采样、插值、滤波、单位猜测或双通道平均。时间间隔的最大相对偏差为 4.33680868846314e-09，当前记录通过均匀采样检查；非均匀记录会显式报错而非自动改写。

## 🪟 STFT 与前序数值审计

| 参数 | 实际传入值 |
|---|---|
| `window` | `get_window('hann', 768, fftbins=True)`，periodic Hann |
| `window_length_samples` | 768 |
| `overlap_samples` | 640 |
| `hop_samples` | 128 |
| `nfft` | 4096 |
| `detrend` | `False` |
| `return_onesided` | `True` |
| `boundary` | `None` |
| `padded` | `False` |
| `scaling` | `spectrum` |
| `axis` | 未覆盖 SciPy 默认值 `-1` |
| sample rate 来源 | 严格检查后的时间列中位采样间隔 |
| STFT 时间坐标 | 窗中心；绝对时间为记录起点加 SciPy 相对中心时间 |

768 点 Hann 窗的固定时间支持约 19.2 ns；hop 128 的帧间隔约 3.2 ns；`nfft=4096` 只在每个 768 点窗内零填充并加密频率网格。代码没有额外去趋势、自动去均值、归一化、重采样、时间方向平均或时域边界补零，也没有把高 overlap 描述成真实时间分辨率提升。

TASK-005 在严格 0.1～2.0 GHz 闭区间内逐帧独立 argmax，并列值选择数组中的第一个频点。TASK-006 使用 `v_app = lambda_0 f / 2` 和 `lambda_0=1550e-9 m` 逐点输出 m/s，表观候选速度与展示速度分开。TASK-007 只读取同一帧相邻三个频率 bin；失败或偏移超出 `[-0.5, 0.5]` 时保留 `NaN` 与状态，不跨帧平滑、不跟踪、不补值。两通道均为 244/244 候选成功细化。

## 🎨 绘图层修改

实际绘图修改只发生在 `scripts/compare_real_ridge_refinement.py`。新增 `tests/unit/test_demo_plot_rendering.py` 验证 Line2D 保留全部有限点和原始 `NaN` 位置、长度不变，并验证 `path.simplify=False` 只在保存上下文中生效且不会污染全局配置。

| 图类 | 修改前 | 修改后 |
|---|---:|---:|
| 主 full display | 散落粗线宽，主线范围 1.5～1.7 | 0.80 |
| presentation | 散落粗线宽，主线范围 1.5～1.7 | 0.80 |
| two-channel presentation | 散落粗线宽，主线范围 1.5～1.7 | 两通道同为 0.75 |
| discrete/refined frequency 与 velocity | 分散局部值 | 0.70 |
| plateau detail | 粗线/marker | 0.50 / marker 1.5 |
| decline detail | 修改前无独立图 | 0.50 / marker 1.5 |
| STFT discrete/refined ridge | 分散局部值 | 0.70 / 0.85 |

主展示图保存 DPI 提高到 300。所有速度显示图通过局部 `matplotlib.rc_context({'path.simplify': False})` 保存；没有全局修改 Matplotlib 配置、锐化、后处理、透明叠影或样条曲线。下降区细节图只使用固定 viewport，不修改数据、时间数组或主图坐标范围。

## 🧬 修改前后数值一致性

修改前后分别保存了完整递归数值指纹，覆盖 TASK-001～007 的 STFT 时间/频率/复频谱、基线 ridge、细化 ridge、离散/细化/展示速度和来源状态，以及 TASK-008A、008B 的全部数组和状态序列。每个浮点/复数数组同时记录数据 SHA、形状、dtype、`NaN` 数量和 `NaN` 掩码 SHA。

- 修改前指纹文件 SHA-256：`293B59481357053A316F63269E5182F2F79F7BAC78BF55F7F4F507C3E829C8B4`。
- 修改后指纹文件 SHA-256：`293B59481357053A316F63269E5182F2F79F7BAC78BF55F7F4F507C3E829C8B4`。
- 8 个前后 CSV 的逐文件 SHA-256 均完全一致。
- 共有 28 张同名 PNG：13 张预期的主线/overlay 图发生变化，15 张诊断或纯 STFT 图字节不变；新增 2 张下降段局部图。
- 因此数值与 `NaN` 位置为精确一致，不依赖宽松容差；变化限于预期 PNG 和新增报告/测试产物。

## 🖼️ 真实数据与旧软件比较

独立输出目录保存了修改前、修改后和对比图。新细线图完整保留 244 个候选点，平台小起伏与下降段共享转折比旧粗线输出更可辨；两通道在平台和下降段保持紧密一致，没有出现因细线化而新增的孤立跳点。

旧软件红线截图显示相似的上升—平台—下降总体形态。截图可见的旧参数包含 FFT 2048、窗口 256、重叠 128，以及四阶九点多项式拟合；当前链使用 4096/768/640 和同帧三点亚频点细化，时间原点及处理链也未证明完全相同。因此本报告只给出形状级视觉接近判断，不做逐点误差、时间对齐或“旧软件为真值”的宣称。

## 🎯 Hop 128 终审

平台段有 131 个候选点覆盖约 0.42 µs，下降段有 88 个候选点覆盖约 0.282 µs。TASK-008A 的峰值对背景中位数为平台 CH1/CH2 53.692/56.554 dB、下降 CH1/CH2 30.255/48.023 dB；峰值对竞争峰中位数均超过 12 dB，244 个候选全部可评估。

TASK-008B 中两通道各有 242 个连续性可评估点，无非法间隔、数组不匹配或细化不可用。平台相邻绝对频率步长中位数约 0.675/0.690 MHz，下降段约 3.382/3.326 MHz；双通道步长绝对差中位数约 0.059 MHz。下降段的较大转折在两通道相同时间出现，支持共同信号变化而不是随机单通道跳点。

当前两通道数值重算约 0.10～0.13 s；完整绘图/诊断流水线约 13.1 s。hop 64 预计将帧数从 620 增至约 1,239、帧间距降至约 1.6 ns，并近似增加一倍计算和绘图工作量，但不会改变 19.2 ns 的真实窗支持。现有细线图、平台、下降、通道一致性及 008A/008B 证据均没有显示帧密度不足，因此按任务约束没有运行 hop 64。

最终推荐：**A，保持 768/640/128/4096**。

## 🧪 测试、哈希与质量门

| 检查 | 结果 |
|---|---|
| `D:\miniconda3\envs\dps-studio\python.exe -m pytest` | 221 passed，1 个非阻塞 `.pytest_cache` 权限警告 |
| `D:\miniconda3\envs\dps-studio\python.exe -m ruff check .` | All checks passed |
| `D:\miniconda3\envs\dps-studio\python.exe -m mypy src` | 34 source files，no issues |
| `git diff --check` | 通过；仅既有 LF/CRLF 提示 |
| 原始数据 SHA-256（前） | `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353` |
| 原始数据 SHA-256（后） | `ab9f656e3563ab96d0e842db88510076f6368e246853fd3427d8fd7db68f7353` |

## 🌿 Git 最终状态

最终 HEAD 仍为 `4cfaa500ab47800dec4259d9bb0cd6fe29db6943`。`git diff --cached --stat` 和 `git diff --cached --name-only` 均为空；未执行 `git add`、`git commit`、分支切换、清理或回退。

`git diff --stat`：

```text
 scripts/plot_real_velocity.py         |   2 +-
 src/dps_studio/core/ridge/__init__.py |  37 ++++-
 src/dps_studio/core/ridge/models.py   | 295 +++++++++++++++++++++++++++++++++-
 3 files changed, 329 insertions(+), 5 deletions(-)
```

完整 `git status --short --branch`：

```text
## main
 M scripts/plot_real_velocity.py
 M src/dps_studio/core/ridge/__init__.py
 M src/dps_studio/core/ridge/models.py
?? docs/
?? outputs/
?? run_demo_pipeline.bat
?? scripts/assess_real_ridge_diagnostics.py
?? scripts/assess_real_ridge_quality.py
?? scripts/compare_real_ridge_refinement.py
?? scripts/plot_real_stft.py
?? scripts/run_demo_pipeline.py
?? src/dps_studio/core/ridge/diagnostic_models.py
?? src/dps_studio/core/ridge/diagnostics.py
?? src/dps_studio/core/ridge/quality_models.py
?? src/dps_studio/core/ridge/refinement.py
?? src/dps_studio/core/ridge/spectral_quality.py
?? tests/fixtures/test.csv
?? tests/unit/test_demo_plot_rendering.py
?? tests/unit/test_ridge_diagnostics.py
?? tests/unit/test_ridge_refinement.py
?? tests/unit/test_ridge_spectral_quality.py
?? tests/unit/test_window_length_diagnostics.py
```

## 📦 输出索引

- `before/`：修改前固定参数真实数据输出与数值指纹。
- `after/`：细线版真实数据输出、两张新增下降段局部图与数值指纹。
- `comparisons/linewidth_before_after_comparison.png`：旧 linewidth 与新细线并排对比。
- `comparisons/old_software_red_line_vs_new_thin_line.png`：旧软件红线与当前细线形状级对比。
- `call_chain_report.md`：当前真实调用链、任务映射和 legacy 分类。
- `preprocessing_audit_report.md`：逐层数值细节、TASK-008 证据和 hop 终审。

## 🛡️ 明确未实施事项

没有实施平滑、插值、删点、补点、噪声或随机扰动、自动 ridge 跟踪、自动分支切换、通道择优、双通道融合、正式 LiF 修正、GUI 或 AI。没有改动 `data/raw`、核心数值算法、横纵坐标数据、时间窗口、y 轴范围、颜色含义、候选状态或诊断数值。
