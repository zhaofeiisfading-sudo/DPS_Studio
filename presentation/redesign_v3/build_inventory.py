from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
INSPECTION = OUT / "_qa_tmp" / "material_inspection.json"

CATEGORY_NAMES = {
    1: "原始时间—电压波形",
    2: "完整频谱图",
    3: "事件区/局部频谱图",
    4: "带脊线频谱图",
    5: "完整时间—速度图",
    6: "平台/起跳/下降段细节",
    7: "参数或 profile 对比",
    8: "双通道对比",
    9: "质量诊断",
    10: "旧软件/当前软件对比",
}


def metadata_from_path(path: str) -> tuple[str, str, str]:
    lower = path.lower()
    if "run_20260724_004901_103968" in lower:
        run = "run_20260724_004901_103968"
    elif "balanced_diagnostic" in lower:
        run = "balanced_diagnostic（同一真实输入的开发诊断）"
    elif "legacy" in lower or "旧软件" in path:
        run = "legacy reference（来源待实验组确认）"
    else:
        run = "项目既有材料"

    if "/high_time_resolution/" in lower:
        profile = "high_time_resolution"
    elif "/balanced/" in lower or "balanced_diagnostic" in lower:
        profile = "balanced"
    else:
        profile = "不适用/未单列"

    if "pdv_channel_1" in lower:
        channel = "pdv_channel_1"
    elif "pdv_channel_2" in lower:
        channel = "pdv_channel_2"
    elif "two_channel" in lower:
        channel = "双通道"
    else:
        channel = "未单列"
    return run, profile, channel


def classify(path: str) -> int:
    name = Path(path).name.lower()
    if "raw_voltage" in name:
        return 1
    if "two_channel" in name:
        return 8
    if "旧软件" in path or "新软件" in path or "legacy_velocity" in name:
        return 10
    if "continuity" in name or "peak_to_" in name or "related_frequency" in name:
        return 9
    if "spectral_quality" in name or "quality_summary" in name:
        return 9
    if "decline_detail" in name or "plateau" in name or "event_detail" in name:
        return 6
    if "discrete_vs_refined" in name:
        return 7
    if "stft_analysis_band_with_ridge" in name:
        return 4
    if "stft_spectrogram_with_refined_ridge" in name:
        return 4
    if "stft_related_frequency_evidence" in name:
        return 4
    if "stft_detail" in name:
        return 3
    if "stft_full_band" in name or "完整频谱图" in path:
        return 2
    if "apparent_velocity_full" in name or "full_display_velocity" in name:
        return 5
    if "presentation_velocity" in name or "完整时间轴" in path:
        return 5
    if "refined_ridge_velocity" in name:
        return 6
    if "ridge_continuity" in name:
        return 9
    if "spectral_quality" in name:
        return 9
    if "apparent_velocity.csv" in name:
        return 5
    return 9


def content_description(path: str, category: int) -> str:
    name = Path(path).name
    if "full_preview" in name:
        return "完整 STFT 时间轴的质量未筛选开发预览；红段不是正式测量"
    if "stft_full_band" in name or "完整频谱图" in name:
        return "实际单边 STFT 全频段，0 至实际 Nyquist（约 20 GHz）"
    if "stft_analysis_band_with_ridge" in name:
        return "0–2 GHz 分析显示及 0.05–2 GHz 候选脊线"
    if "stft_spectrogram_with_refined_ridge" in name:
        return "局部频谱与离散/亚频点精修脊线叠加"
    if "stft_related_frequency_evidence" in name:
        return "主脊线及二倍频/半频局部峰的诊断叠加"
    if "stft_detail" in name:
        return "事件附近 0–2 GHz 局部 STFT 细节"
    if "event_detail" in name:
        return "事件起点附近的表观速度细节；含显示零与显示桥说明"
    if "decline_detail" in name:
        return "平台末段至下降段的逐帧亚频点表观速度"
    if "plateau" in name:
        return "平台全貌与平台逐帧波动细节"
    if "discrete_vs_refined_frequency" in name:
        return "离散频点与三点亚频点精修频率对比"
    if "discrete_vs_refined_velocity" in name:
        return "离散与精修表观速度对比；含显示零"
    if "full_display_velocity" in name or "presentation_velocity" in name:
        return "前事件显示零、平台和下降段的表观速度全貌"
    if "新软件" in path:
        return "当前正式 run 的表观速度全时间图；与旧软件曲线仅作开发历史对照"
    if "apparent_velocity_full_time" in name:
        return "正式候选表观速度全时间图；未测区不插值"
    if "continuity" in name:
        return "相邻成功帧的频率步长、斜率及状态诊断"
    if "peak_to_background" in name:
        return "主峰相对受保护频带外背景中位数的谱对比度（非 SNR）"
    if "peak_to_competitor" in name:
        return "主峰相对剩余最强峰的谱优势量（非置信度）"
    if "related_frequency" in name:
        return "主峰与二倍频/半频局部峰的描述性证据"
    if "two_channel_presentation_velocity" in name:
        return "同一输入两采集通道的表观速度叠加，仅作一致性观察"
    if "two_channel" in name:
        return "两采集通道的同类诊断量对比，不代表通道融合或准确度"
    if "quality_summary" in name:
        return "每通道候选帧、首帧、最低速度、谱对比度与连续性摘要"
    if "spectral_quality.csv" in name:
        return "逐帧谱背景和竞争峰对比度数据"
    if "related_frequency_evidence.csv" in name:
        return "逐帧主峰、二倍频/半频局部峰与状态"
    if "ridge_continuity.csv" in name:
        return "逐帧相邻频率步长与连续性状态"
    if "refined_ridge_velocity.csv" in name:
        return "离散/精修频率和表观速度的逐帧开发诊断"
    if "apparent_velocity.csv" in name:
        return "正式逐帧表观速度、状态、谱质量和显示列"
    if "旧软件" in path or "legacy_velocity" in name:
        return "旧软件导出速度—时间曲线，仅用于历史对照，非物理真值"
    if "raw_voltage" in name:
        return "原始 CSV 两个独立电压通道的时间波形；未平滑、未插值"
    return f"{CATEGORY_NAMES[category]}相关材料"


def suitability(path: str, category: int) -> str:
    name = Path(path).name.lower()
    if path.lower().endswith(".csv"):
        return "中：数据/标注来源，不直接铺满幻灯片"
    if "full_preview" in name:
        return "低：仅可用于解释开发预览与正式结果的边界"
    if "完整时间轴" in path or "完整频谱图" in path or "新软件速度" in path:
        return "低：与正式 run 文件完全重复"
    if category in {1, 2, 3, 4, 5, 6, 8, 10}:
        return "高：可作为对应主题页主图"
    if category in {7, 9}:
        return "中高：适合作为方法/诊断证据"
    return "中"


def escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def duplicate_label(
    path: str, exact_groups: list[list[str]], visual_groups: list[list[str]]
) -> str:
    for group in exact_groups:
        if path in group:
            canonical = group[0]
            return (
                "完全重复；基准："
                + canonical
                if path != canonical
                else "完全重复组基准"
            )
    for group in visual_groups:
        if path in group:
            peers = [item for item in group if item != path]
            if peers:
                return "视觉近似：" + "；".join(peers[:2])
    return "否"


def row(record: dict[str, Any], inspection: dict[str, Any]) -> str:
    path = record["path"]
    run, profile, channel = metadata_from_path(path)
    category = classify(path)
    duplicate = duplicate_label(
        path,
        inspection["exact_duplicate_groups"],
        inspection["same_average_hash_groups"],
    )
    return (
        f"| {category}. {CATEGORY_NAMES[category]} | `{escape(path)}` | "
        f"{escape(run)} | {escape(profile)} | {escape(channel)} | "
        f"{escape(content_description(path, category))} | "
        f"{escape(suitability(path, category))} | {escape(duplicate)} |"
    )


def main() -> None:
    inspection = json.loads(INSPECTION.read_text(encoding="utf-8"))
    records = sorted(
        [*inspection["images"], *inspection["csvs"]],
        key=lambda item: (classify(item["path"]), item["path"]),
    )

    extra_paths = [
        "presentations/group_meeting/20260726_redesign/assets/real/raw_voltage_dual_channel.png",
        "data/reference/legacy/legacy_velocity_time.csv",
    ]
    for extra_path in extra_paths:
        path = REPO / extra_path
        if not path.exists():
            continue
        records.append({"path": extra_path})
    records.sort(key=lambda item: (classify(item["path"]), item["path"]))

    lines = [
        "# DPS Studio 组会汇报图像与数据清单",
        "",
        "## 盘点范围与结论",
        "",
        "- 主目录：`presentations/data/`（项目中不存在 `presentation/data/`；本次按现有真实目录读取）。",
        f"- 已逐项读取：{inspection['counts']['images']} 张图、{inspection['counts']['csvs']} 个 CSV、{inspection['counts']['jsons']} 个 JSON 清单。",
        "- 额外纳入：既有原始双通道波形图与旧软件本地导出 CSV；两者均来自项目现有材料。",
        "- 三组完全重复文件：`完整时间轴.png`、`新软件速度时间图.png`、`完整频谱图.png` 分别与正式 run 中对应文件一致；PPT 优先引用正式 run 路径。",
        "- 未重新运行分析脚本：现有材料已经覆盖 10 类必需内容，避免改变参数后伪装成默认结果。",
        "",
        "## 分类统计",
        "",
    ]
    counts = {category: 0 for category in CATEGORY_NAMES}
    for record in records:
        counts[classify(record["path"])] += 1
    for category, name in CATEGORY_NAMES.items():
        lines.append(f"- {category}. {name}：{counts[category]} 项")

    lines.extend(
        [
            "",
            "## 全量清单",
            "",
            "| 类别 | 路径 | run | profile | 通道 | 内容 | PPT 适用性 | 重复性 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(row(record, inspection) for record in records)
    lines.extend(
        [
            "",
            "## 选图原则",
            "",
            "1. 主结果图优先使用 `run_20260724_004901_103968/` 下的正式输出。",
            "2. `balanced_diagnostic/` 仅用于解释亚频点精修、局部变化和描述性诊断，不替代正式输出。",
            "3. `apparent_velocity_full_preview.png` 明确标为质量未筛选开发预览，不用于展示正式测量结果。",
            "4. 双通道图只说明两个独立采集通道在这次数据中的同量级趋势，不能推出准确度、可信度或通道融合。",
            "5. 旧软件导出及其图像来源尚需实验组确认，只用于开发历史和接口差异对照。",
            "",
        ]
    )
    output = OUT / "image_inventory.md"
    output.write_text("\n".join(lines), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
