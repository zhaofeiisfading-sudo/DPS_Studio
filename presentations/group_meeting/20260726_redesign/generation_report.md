# DPS Studio 组会汇报重制版生成报告

## 交付结果

- 生成日期：2026-07-26
- 页面比例：16:9，13.333 × 7.5 in
- 幻灯片：15 页
- 演讲者备注：15 / 15 页
- 可编辑 PPT：
  `DPS_Studio_组会汇报_redesign.pptx`
- PowerPoint 实际导出的 PDF：
  `DPS_Studio_组会汇报_redesign.pdf`
- PowerPoint 实际导出的逐页预览：
  `rendered_slides/slide_01.png` 至 `slide_15.png`

## 制作方式

- 使用 `ppt-master` 的内容规划、来源约束和渲染 QA 方法。
- 为满足“普通、可编辑 PPT”要求，页面使用 PptxGenJS 原生文本框、形状、线条和表格对象构建。
- 未使用 image generation，也未把整页栅格化后铺入 PPT。
- 位图只用于真实科研图和一处真实源码摘录；所有标题、正文、流程、状态、公式说明和表格均可直接编辑。
- 结构检查得到 6 个图片对象，分布在第 6、7、8、10、11 页；最大图片覆盖率为单页的 36.12%，不存在全页图片。
- 字体规则：中文为 Microsoft YaHei；英文、数字和公式为 Times New Roman；代码和路径为 Consolas。

## 使用的真实图

1. `assets/real/raw_voltage_dual_channel.png`
   - 来源：`data/raw/20260607.csv`
   - 仅截取事件附近显示窗；无平滑、插值或重采样。
2. `assets/real/stft_balanced_channel1.png`
   - 来源：
     `outputs/production_runs/run_20260724_004901_103968/balanced/pdv_channel_1/stft_analysis_band_with_ridge.png`
3. `assets/real/velocity_balanced_channel1_event.png`
   - 来源：
     `outputs/production_runs/run_20260724_004901_103968/balanced/pdv_channel_1/apparent_velocity_event_detail.png`
4. `assets/real/two_channel_latest_candidates.png`
   - 来源：同一真实 run 的两份 `apparent_velocity.csv`
   - 只绘制 formal candidate；无平滑、插值、平均、择优或融合。
5. `assets/code/analysis_profiles_balanced_excerpt.png`
   - 来源：`src/dps_studio/core/analysis_profiles.py:136-145`
   - 这是源码摘录，不是科研结果图。

逐页来源、数值和边界说明见 `source_map.md`。

## 参数与物理边界

- Balanced / High time 参数：
  `src/dps_studio/core/analysis_profiles.py:136-168`
- 运行配置：
  `configs/demo_dual_profile.toml:17-31`
- 最新运行 manifest：
  `outputs/production_runs/run_20260724_004901_103968/balanced/profile_manifest.json`
- 拍频到表观速度：
  `src/dps_studio/core/physics/velocity.py:23-31`
- 依赖与检查工具：
  `pyproject.toml:11-27`
- `1.55 μm` 只作为配置中的 demonstration value 展示，未写成已核验实验波长。
- 当前结果明确表述为无符号 apparent velocity；未宣称 LiF、折射率、入射角或 corrected velocity 已实现。
- peak-to-background 与 peak-to-competitor 只称为描述性谱对比度，不称为 SNR 或自动择优阈值。

## 渲染 QA

- 使用本机 Microsoft PowerPoint 打开最终 PPT，并实际导出 15 页 PDF 与 1920 × 1080 PNG。
- 首轮发现并修复：目标页断词、GUI 窄列、工具页代码裁切、输入页文字拥挤、参数页孤立单位、真实结果页页底裁切、双通道结论框溢出、路线图尾注溢出。
- 第二轮发现并修复：封面姓名占位、代码字号与来源位置、公式下标、输入页结论重叠、参数页孤立标点。
- 最终逐页复核：无文本溢出、无裁切、无缺字方框、无占位符、无负坐标对象、无图片拉伸、无全页图片。
- 关键词扫描未发现：`______`、`Lorem`、`TODO`、`闭环`、`image generated`、`AI 生成图片`。
- PDF 页数：15。

## 可执行检查

- `pytest`：271 passed in 16.47s
- `ruff check . --no-cache`：All checks passed
- `git diff --check`：通过；只报告当前工作树已有文件的 LF/CRLF 提示
- 原始数据 SHA-256（生成前后保持一致）：
  `AB9F656E3563AB96D0E842DB88510076F6368E246853FD3427D8FD7DB68F7353`

## 文件哈希

- PPTX SHA-256：
  `0503B3E560600021360572B296A47D4930A2FD529B6E8723F8598A4EBC2FA545`
- PDF SHA-256：
  `8F27812B7B336FDF50978846647947ED0FDE81B6EFD42001C00FC564F1E39585`

## 仓库边界

- 所有新建文件均位于：
  `presentations/group_meeting/20260726_redesign/`
- 未修改 `data/raw`、`src`、`tests` 或 `outputs`。
- 未执行 Git commit。
