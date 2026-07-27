# DPS Studio 组会汇报生成报告

## 交付结果

| 交付物 | 路径 | 结果 |
| --- | --- | --- |
| 可编辑 PowerPoint | `presentation/redesign_v3/DPS_Studio_组会汇报.pptx` | 18 页；PowerPoint 可正常打开 |
| PDF | `presentation/redesign_v3/DPS_Studio_组会汇报.pdf` | 18 页 |
| 逐页渲染 | `presentation/redesign_v3/rendered_slides/` | 18 张 PNG；每张 1920×1080 |
| 页面结构 | `presentation/redesign_v3/presentation_outline.md` | 18 页逐页论点、图源、版式和科学边界 |
| 图像清单 | `presentation/redesign_v3/image_inventory.md` | 54 张图、14 个 CSV、3 个 JSON；另纳入原始双通道图与 legacy CSV |
| 来源映射 | `presentation/redesign_v3/source_map.md` | 逐页图像、代码、配置、manifest 和数值映射 |
| 生成脚本 | `presentation/redesign_v3/generate_editable_deck.js` | PptxGenJS 原生对象生成 |

文件指纹：

- PPTX SHA-256：`4E9E571EB2F3CD0999D4ED0CADE84A0A3D7B36E9BF14555A039CD972154BA116`
- PDF SHA-256：`4D1309EF1DECB7074214C09B18088180A8DB0743A26244D5B04907492DAD4D95`

## 制作方式

- 使用 `ppt-master` 的材料盘点、叙事组织、样式约束、来源记录和渲染验收方法。
- 根据用户对可编辑普通 PPT 的明确要求，没有采用整页图片式生成；PPT 由 PptxGenJS 原生文本、表格、图形、公式、流程和标注构成。
- 真实实验图只作为普通图片对象嵌入；没有用图像生成工具制作实验波形、频谱、速度曲线或软件截图。
- 没有重新运行数据分析脚本：现有正式 run 和 diagnostic 材料已经覆盖全部必需图类，避免参数变化后被误认为默认结果。
- 没有修改项目源码、测试、配置或 `data/raw`；所有新增文件均位于 `presentation/redesign_v3/`。

## 编辑性检查

自动解析结果：

- 文本形状：748 个；
- 真实图片对象：14 个；
- 整页图片：0 个；
- 每页均含 PowerPoint 原生对象；
- 18 页均含讲稿备注；
- 公式、参数表、状态表、时间线、流程和页内标注均可单独编辑。

## 真实材料覆盖

PPT 已使用以下真实内容：

1. 原始双通道时间—电压波形；
2. 完整单边 STFT；
3. 事件附近局部 STFT；
4. 带离散/亚频点精修脊线的局部频谱；
5. 正式全时间表观速度；
6. 起跳、平台和下降段三类局部速度细节；
7. Balanced 与 High time 的真实 profile 对比；
8. 双通道表观速度对比；
9. 双通道逐帧谱诊断；
10. 旧软件与当前开发输出的历史对照。

主要材料目录：`presentations/data/`。项目中不存在 `presentation/data/`，因此把原请求中的单数路径视为目录名笔误；输出仍严格写入用户指定的 `presentation/redesign_v3/`。

## 科学边界检查

已在 PPT 正文和讲稿中明确：

- `vacuum_wavelength_m = 1.55e-6` 是配置演示值，实验记录尚未确认；
- 当前结果是无符号表观速度；
- 没有 LiF、折射率、入射角或窗口修正；
- 前事件零只存在于显示列，核心表观速度仍为 NaN；
- 显示桥只有两个端点，不写入中间 CSV 数据；
- 双通道独立计算，不平均、不融合、不自动择优；
- dB 值是描述性谱对比度，不是 SNR、准确度或置信度；
- High time 缩短时间支持，不代表更高准确度；
- 旧软件数据不是物理真值。

禁用措辞扫描：0 个命中。

## 渲染与修订记录

第一轮：

- 生成 18 页 PPTX；
- 发现 PowerPoint 对原生 `addTable` 生成的文件兼容性异常；
- 将两个表格改为由矩形、线条和文本组成的原生网格后，PowerPoint 可正常打开 18 页文件；
- 导出 PDF 和 18 张 1920×1080 PNG；
- 逐页蒙太奇检查发现第 7 页公式下标间距不理想。

第二轮：

- 将第 7 页公式改为单一可编辑 Times New Roman 文本对象；
- 重新生成 PPTX、PDF 和全部逐页 PNG；
- 复检封面、术语、表格、真实图、边界说明、页脚和来源；未发现遮挡、越界或裁切。

自动检查结果：

```text
PPTX slides: 18
PDF pages: 18
Rendered PNG: 18 × 1920×1080
Full-slide raster image: 0
Out-of-bounds shape: 0
Speaker notes: 18
Banned wording: 0
Scientific boundary checks: all passed
```

最终视觉检查文件：

- `_qa_tmp/montage_v2.png`
- `_qa_tmp/montage_v2_01_09.png`
- `_qa_tmp/montage_v2_10_18.png`
- `_qa_tmp/qa_summary.json`

## 项目检查

```text
pytest: 271 passed in 17.94s
ruff: All checks passed!
git diff --check: passed; only pre-existing LF/CRLF warnings were printed
```

测试使用 `PYTHONDONTWRITEBYTECODE=1`、禁用 pytest cache，并把临时目录放在本交付目录内；临时测试目录已清理。

## 尚未找到或尚未核验

- 未找到 `presentation/data/`；真实材料目录为 `presentations/data/`。
- 未找到能够确认 1.55 µm 的实验记录。
- 旧软件速度曲线的来源、参数和处理步骤尚未由实验组确认。
- 当前代码未实现 LiF、折射率、入射角、窗口修正、有符号速度和经实验验证的物理分支判据。
- 没有多批次数据足以支持跨实验准确度或稳健性结论。

## Git 状态说明

本任务没有提交，也没有改动用户已有源码差异。最终新增内容汇总为未跟踪目录 `presentation/`；既有 `presentations/` 和其他工作树差异保持原状。
