"""Deterministic Chinese C/G/S explanations; no inference of target identity."""

from __future__ import annotations

import math

from .models import (
    CLUSTER_WIDTH_HZ,
    COMPARED_CURVE_METHODS,
    DIAGNOSTIC_FMIN_HZ,
    EVIDENCE_BG_GAIN_MIN_DB,
    EVIDENCE_CONTRAST_MIN_DB,
    EVIDENCE_MIN_CYCLES_256,
    EVIDENCE_MIN_R2,
    CandidateEntry,
    ClusterSummary,
    DiagnosticBundle,
    FrameSummaryText,
)

PHYSICAL_IDENTITY_CAVEAT_ZH = (
    "S=True 仅确认局部原波形对正弦/Chirp 模型的支持，不确认物理主目标支路身份；"
    "多支路或身份不确定时，仍需实验信息确认，不能把共识或平滑当作真实值。"
)
_NATIVE_REASONS = {
    "PRE_EVENT": "PRE_EVENT：原生事件触发前，门控抑制",
    "NO_EVENT": "NO_EVENT：未确认能量变化，不能解释为测得零频率",
    "LOW_CONTRAST": "LOW_CONTRAST：原生谱对比度不足",
    "LOW_WAVEFORM_SUPPORT": "LOW_WAVEFORM_SUPPORT：原生波形门限未通过",
    "UNOBSERVABLE_NOT_ZERO": "UNOBSERVABLE_NOT_ZERO：不可观测，不是零频率测量",
}


def explain_candidate(
    candidate: CandidateEntry,
    *,
    cluster: ClusterSummary | None = None,
    dc_leak_hint: bool = False,
    fmin_hz: float = DIAGNOSTIC_FMIN_HZ,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    """Keep candidate existence, native gate, and four independent S gates distinct."""
    yes: list[str] = []
    no: list[str] = []
    c = candidate
    if c.c_present:
        yes.append(f"C=1：带内候选 {c.frequency_hz / 1e9:.6f} GHz")
    elif math.isfinite(c.raw_frequency_hz) and (
        c.raw_frequency_hz < fmin_hz or c.raw_frequency_hz > c.evaluation_max_hz
    ):
        no.append(
            f"C=0：原始提议超出评估频带 {fmin_hz / 1e6:g} MHz–"
            f"{c.evaluation_max_hz / 1e9:g} GHz，保留原始值"
        )
    else:
        no.append(f"C=0：无适用带内候选（{c.run_status}）")
    if c.g_accepted:
        yes.append("G=1：算法原生门控通过")
    else:
        no.append(
            "G=0：算法原生门控未通过" if c.native_rank == 1 else "G=0：次级极点没有定义原生发布门控"
        )
        no.extend(text for token, text in _NATIVE_REASONS.items() if token in c.native_quality)
    gates = (
        (c.spectral_contrast_db, EVIDENCE_CONTRAST_MIN_DB, "局部频带谱底对比", "dB"),
        (c.background_gain_db, EVIDENCE_BG_GAIN_MIN_DB, "静默前缀中位背景增益", "dB"),
        (c.cycles_256, EVIDENCE_MIN_CYCLES_256, "256 点证据窗周期数", ""),
        (
            max(c.raw_tone_r2, c.raw_chirp_r2)
            if math.isfinite(c.raw_tone_r2) and math.isfinite(c.raw_chirp_r2)
            else math.nan,
            EVIDENCE_MIN_R2,
            "max(原波形 Tone R², Chirp R²)",
            "",
        ),
    )
    for value, threshold, label, unit in gates:
        if not math.isfinite(value):
            no.append(f"S 门限：{label}不可用，未通过 ≥ {threshold:g} {unit}".rstrip())
        elif value >= threshold:
            yes.append(f"S 门限：{label} {value:.3f} ≥ {threshold:g} {unit}".rstrip())
        else:
            no.append(f"S 门限：{label} {value:.3f} < {threshold:g} {unit}".rstrip())
    if c.raw_chirp_r2 >= EVIDENCE_MIN_R2 and c.raw_tone_r2 < EVIDENCE_MIN_R2:
        yes.append(
            f"Chirp 调频救回：Tone R²={c.raw_tone_r2:.3f}，"
            f"Chirp R²={c.raw_chirp_r2:.3f}；S 仍须四项门限全部通过"
        )
    if c.g_accepted and not c.s_supported:
        no.append("⚠️ 可疑：算法原生门控通过(G=1)，但原波形证据未通过(S=0)")
    if not c.g_accepted and c.s_supported:
        yes.append("🔍 隐藏信号：原波形支持通过(S=1)，但被原生门控(G=0)抑制")
    if dc_leak_hint:
        no.append(
            "DC / 低频泄漏提示：B0 的 <250 MHz 候选无 S，"
            "B1/S2 在 ≥250 MHz 有 S；需结合原始与去均值谱检查"
        )
    if cluster is not None:
        if cluster.high_without_s:
            no.append("多家族 S1 高共识缺乏原波形 S 支持（high_without_s）")
        if cluster.s_clusters_at_center > 1:
            no.append("存在多个通过 S 的竞争支路（S_clusters_at_center > 1）")
    code = (
        "NO_C"
        if not c.c_present
        else "G_S"
        if c.g_accepted and c.s_supported
        else "G_WITHOUT_S"
        if c.g_accepted
        else "S_WITHOUT_G"
        if c.s_supported
        else "C_ONLY"
    )
    return code, tuple(yes), tuple(no)


def summarize_frame_diagnosis(bundle: DiagnosticBundle, frame_idx: int) -> FrameSummaryText:
    if not 0 <= frame_idx < len(bundle.common_sample_indices):
        raise IndexError(frame_idx)
    readings: list[tuple[str, float]] = []
    for name in COMPARED_CURVE_METHODS:
        curve = bundle.curves.get(name)
        if (
            curve is not None
            and curve.selected[frame_idx]
            and math.isfinite(float(curve.frequency_hz[frame_idx]))
        ):
            readings.append((name, float(curve.frequency_hz[frame_idx])))
    text = "；".join(f"{name}={hz / 1e9:.6f} GHz" for name, hz in readings) or "无已选带内候选"
    pairs = [
        f"{a}/{b}"
        for i, (a, f) in enumerate(readings)
        for b, g in readings[i + 1 :]
        if abs(f - g) > CLUSTER_WIDTH_HZ
    ]
    text += "；分歧 >100 MHz：" + "、".join(pairs) if pairs else "；有效方法间无 >100 MHz 分歧"
    yes: list[str] = []
    no: list[str] = []
    warnings: list[str] = []
    clusters = {c.cluster_id: c for c in bundle.clusters_by_frame[frame_idx]}
    b0 = bundle.curves.get("B0")
    dc = bool(
        b0 is not None
        and b0.selected[frame_idx]
        and b0.frequency_hz[frame_idx] < 250e6
        and not b0.s_supported[frame_idx]
        and any(
            name in bundle.curves
            and bundle.curves[name].selected[frame_idx]
            and bundle.curves[name].s_supported[frame_idx]
            and bundle.curves[name].frequency_hz[frame_idx] >= 250e6
            for name in ("B1", "S2")
        )
    )
    for c in bundle.candidates_by_frame[frame_idx]:
        _, accepted, rejected = explain_candidate(
            c,
            cluster=clusters.get(c.cluster_id),
            dc_leak_hint=dc and c.estimator == "B0",
            fmin_hz=bundle.eval_fmin_hz,
        )
        label = f"{c.estimator}[{c.native_rank}]："
        yes.extend(label + s for s in accepted)
        no.extend(label + s for s in rejected)
    for name, curve in bundle.curves.items():
        if curve.selected[frame_idx]:
            rule = (
                "B1 候选通过共同 S 筛选"
                if name == "B+S"
                else "S 支持家族投票；按优先级选实测候选，不平均频率"
                if name == "S2"
                else "保留 C 候选；原生发布需另查 G"
            )
            yes.append(f"{name} 已选：{rule}，来源 {curve.selected_source[frame_idx]}")
        else:
            no.append(f"{name} 未选：{curve.quality[frame_idx]}")
    if any(c.s_clusters_at_center > 1 for c in clusters.values()):
        warnings.append("多个 S 支持支路竞争，局部拟合不能判定物理身份")
    if any(c.high_without_s for c in clusters.values()):
        warnings.append("high_without_s：多家族共识未通过原波形支持")
    if bundle.compute_mode == "fast_core":
        warnings.append("FAST_CORE 未运行 S2；当前候选簇仅来自已运行估计器")
    return FrameSummaryText(
        text, tuple(yes), tuple(no), tuple(warnings), PHYSICAL_IDENTITY_CAVEAT_ZH
    )
