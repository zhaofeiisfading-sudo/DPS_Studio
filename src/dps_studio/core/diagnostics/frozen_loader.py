"""Optional TASK-017/018 adapters. CSV/gzip/JSON parsing uses the standard library.

The installed core has no artifact requirement. Missing stacks return None;
present but malformed/incompatible stacks raise ValueError instead of falling back.
"""

from __future__ import annotations

import csv
import gzip
import json
from math import isfinite
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from time import perf_counter

import numpy as np
from numpy.typing import ArrayLike

from dps_studio.core.io import DelimitedSignalLoadResult, read_delimited_signals

from .engine import _record, assemble_bundle, background_stop_for_stages, curves_from_candidates
from .models import (
    DIAGNOSTIC_FMAX_HZ,
    DIAGNOSTIC_FMIN_HZ,
    CandidateEntry,
    ClusterSummary,
    DiagnosticBundle,
    DiagnosticComputeMode,
    DiagnosticPreset,
    FloatArray,
    IntArray,
    MethodCurve,
    StageSegment,
)

_SHOWCASES = {
    "20201210m_ch1": "DC 前驱与起跳：B0 低频泄漏、B1 去均值恢复；自动事件可能漏检",
    "ch3_ch1": "起跳调频：Tone 支持不足时检查 Dechirp / S2 的 Chirp 救回",
    "20260630-1_ch2": "弱信号多支路竞争：比较 B+S 与 S2 的候选选择",
    "20201214m_ch1": "约 6.3 GHz 平台超出主评估频带；查看 10 GHz 背景谱",
}


def discover_presets(repo_root: Path) -> tuple[DiagnosticPreset, ...]:
    """Discover actual raw inputs, using inventory unit mappings when available."""
    inventory = repo_root / "artifacts/TASK-017/data/inventory.json"
    presets: list[DiagnosticPreset] = []
    if inventory.is_file():
        value = json.loads(inventory.read_text(encoding="utf-8"))
        for item in value["channels"]:
            path = Path(item["file"])
            if not (repo_root / path).is_file():
                continue
            channel = str(item["id"])
            presets.append(
                DiagnosticPreset(
                    channel,
                    path,
                    int(item["column"]),
                    _SHOWCASES.get(channel, "真实 PDV 全通道候选、原生门控与原波形支持对照"),
                    float(item.get("time_scale_to_s", 1.0)),
                    float(item.get("voltage_scale_to_v", 1.0)),
                    bool(item.get("has_header", False)),
                    str(item.get("delimiter", ",")),
                    str(item.get("unit_status", "Inherited headerless mapping")),
                )
            )
    else:
        for path in sorted((repo_root / "data/raw").rglob("*")):
            if not path.is_file() or path.suffix.lower() not in (".csv", ".dat"):
                continue
            if "result" in path.stem.lower():
                continue
            with path.open(encoding="utf-8-sig", newline="") as stream:
                row = next(csv.reader(stream), [])
            try:
                numeric = [float(s) for s in row]
            except ValueError:
                continue  # No unit/header/column guesses for an unknown format.
            for column in range(1, len(numeric)):
                channel = f"{path.stem}_ch{column}"
                presets.append(
                    DiagnosticPreset(
                        channel,
                        path.relative_to(repo_root),
                        column,
                        _SHOWCASES.get(channel, "原始通道；单位映射需核对"),
                        unit_provenance="UNVERIFIED: numeric seconds/volts assumed without inventory",
                    )
                )
    order = {name: i for i, name in enumerate(_SHOWCASES)}
    return tuple(sorted(presets, key=lambda p: (order.get(p.channel_id, len(order)), p.channel_id)))


def load_raw_channel_result(preset: DiagnosticPreset, repo_root: Path) -> DelimitedSignalLoadResult:
    """Use the same strict core reader as MainWindow; retain import metadata."""
    return read_delimited_signals(
        repo_root / preset.relative_path,
        time_column=0,
        voltage_columns={preset.channel_id: preset.voltage_column},
        delimiter=preset.delimiter,
        has_header=preset.has_header,
        time_scale=preset.time_scale_to_s,
        voltage_scales={preset.channel_id: preset.voltage_scale_to_v},
    )


def load_raw_channel_arrays(
    preset: DiagnosticPreset, repo_root: Path
) -> tuple[FloatArray, FloatArray]:
    record = load_raw_channel_result(preset, repo_root).records[preset.channel_id]
    return record.time_s, record.voltage_v


def load_stage_segments(channel_id: str, repo_root: Path) -> tuple[StageSegment, ...]:
    path = repo_root / "artifacts/TASK-017/data/visual_annotations.json"
    if not path.is_file():
        return ()
    plans = json.loads(path.read_text(encoding="utf-8"))["plans"]
    result: list[StageSegment] = []
    for row in plans.get(channel_id, []):
        bounds = row.get("start_range_s")
        result.append(
            StageSegment(
                str(row["id"]),
                float(row["start_s"]),
                float(row["end_s"]),
                str(row["stage"]),
                str(row.get("visual_evidence", "")),
                str(row.get("confidence", "unspecified")),
                str(row.get("physical_branch", "requires experimental confirmation")),
                (float(bounds[0]), float(bounds[1])) if bounds is not None else None,
            )
        )
    return tuple(result)


def _rows(path: Path, *, methods: tuple[str, ...] = ()) -> Iterator[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        method_index = header.index("method") if methods else -1
        for row in reader:
            if len(row) != len(header):
                raise ValueError(f"Malformed frozen CSV row in {path}")
            if methods and row[method_index] not in methods:
                continue
            yield dict(zip(header, row, strict=True))


def _float(row: dict[str, str], key: str, default: float = np.nan) -> float:
    text = row.get(key, "")
    return float(text) if text else default


def _int(row: dict[str, str], key: str, default: int = -1) -> int:
    value = _float(row, key)
    if not isfinite(value):
        return default
    if value != int(value):
        raise ValueError(f"Nonintegral {key}: {value}")
    return int(value)


def _bool(row: dict[str, str], key: str) -> bool:
    text = row.get(key, "")
    if text not in ("", "True", "False", "true", "false", "1", "0"):
        raise ValueError(f"Invalid boolean {key}: {text}")
    return text in ("True", "true", "1")


def _candidate(r: dict[str, str]) -> CandidateEntry:
    return CandidateEntry(
        source_row=_int(r, "source_row"),
        sample_index=_int(r, "sample_index"),
        time_s=float(r["time_s"] or "nan"),
        estimator=r["estimator"],
        family=r["family"],
        native_rank=_int(r, "native_rank"),
        source_label=r["source"],
        raw_frequency_hz=float(r["raw_frequency_hz"] or "nan"),
        frequency_hz=float(r["frequency_hz"] or "nan"),
        native_gated_hz=float(r["native_gated_hz"] or "nan"),
        chirp_hz_s=float(r["chirp_hz_s"] or "nan"),
        native_quality=r["native_quality"],
        applicable=_bool(r, "applicable"),
        run_status=r["run_status"],
        c_present=_bool(r, "C"),
        g_accepted=_bool(r, "G"),
        s_supported=_bool(r, "S"),
        spectral_contrast_db=float(r["spectral_contrast_db"] or "nan"),
        background_gain_db=float(r["background_gain_db"] or "nan"),
        relative_strongest_db=float(r["relative_strongest_db"] or "nan"),
        competitor_advantage_db=float(r["competitor_advantage_db"] or "nan"),
        raw_tone_r2=float(r["raw_tone_r2"] or "nan"),
        raw_chirp_r2=float(r["raw_chirp_r2"] or "nan"),
        raw_tone_residual_rms_v=float(r["raw_tone_residual_rms_v"] or "nan"),
        raw_chirp_residual_rms_v=float(r["raw_chirp_residual_rms_v"] or "nan"),
        cycles_256=float(r["cycles_256"] or "nan"),
        cluster_id=_int(r, "cluster"),
        s0_score=float(r["S0_score"] or "nan"),
        s1_score=float(r["S1_score"] or "nan"),
        s2_score=float(r["S2_score"] or "nan"),
        family_votes=_int(r, "family_votes", 0),
        supported_family_votes=_int(r, "supported_family_votes", 0),
        competing_clusters=_int(r, "competing_clusters", 0),
        s0_selected=_bool(r, "S0_selected"),
        s1_selected=_bool(r, "S1_selected"),
        s2_selected=_bool(r, "S2_selected"),
        evaluation_max_hz=float(r["evaluation_max_hz"] or "nan"),
    )


def _cluster(r: dict[str, str]) -> ClusterSummary:
    return ClusterSummary(
        _int(r, "sample_index"),
        float(r["time_s"] or "nan"),
        _int(r, "cluster"),
        float(r["frequency_lo_hz"] or "nan"),
        float(r["frequency_hi_hz"] or "nan"),
        float(r["frequency_hz"] or "nan"),
        _int(r, "members"),
        _int(r, "branches_at_center"),
        _int(r, "S_clusters_at_center"),
        _bool(r, "conflict"),
        _bool(r, "high_consensus"),
        _bool(r, "high_without_S"),
        _bool(r, "harmonic_like"),
        _bool(r, "edge_like"),
        _bool(r, "low_background_gain"),
        float(r["S0_score"] or "nan"),
        float(r["S1_score"] or "nan"),
        float(r["S2_score"] or "nan"),
        _int(r, "S2_voters"),
        _int(r, "S2_eligible"),
        _bool(r, "S2_G"),
        _bool(r, "S2_S"),
        _bool(r, "S2_selected"),
        tuple(filter(None, r["S2_contributors"].split("|"))),
    )


def _loaded_curve(
    method: str, rows: list[dict[str, str]], q: IntArray, times: FloatArray
) -> MethodCurve:
    rows.sort(key=lambda r: _int(r, "sample_index"))
    if [int(r["sample_index"]) for r in rows] != q.tolist():
        raise ValueError(f"Frozen {method} does not match the common sample grid")
    return MethodCurve(
        method,
        q,
        times,
        np.array([_bool(r, "C") for r in rows]),
        np.array([_bool(r, "G") for r in rows]),
        np.array([_bool(r, "S") for r in rows]),
        np.array([_bool(r, "selected") for r in rows]),
        np.array([_float(r, "frequency_hz") for r in rows]),
        np.array([_float(r, "proposal_hz") for r in rows]),
        tuple(r["selected_source"] for r in rows),
        tuple(r["quality"] for r in rows),
        np.array([_int(r, "cluster") for r in rows], dtype=np.int64),
    )


def load_precomputed_bundle(
    channel_id: str,
    time_s: ArrayLike,
    voltage_v: ArrayLike,
    *,
    repo_root: Path,
    source_path: Path | None = None,
    display_fmax_hz: float = 10e9,
) -> DiagnosticBundle | None:
    started = perf_counter()
    if Path(channel_id).name != channel_id or "/" in channel_id or "\\" in channel_id:
        raise ValueError("channel_id must be a simple identifier")
    parent = repo_root / "artifacts/TASK-018/data/stack_v1"
    files = {
        kind: parent / f"{channel_id}__{kind}.csv.gz" for kind in ("candidates", "curves", "peaks")
    }
    if not all(path.is_file() for path in files.values()):
        return None
    record = _record(time_s, voltage_v)
    q = np.arange(0, record.sample_count, 128, dtype=np.int64)
    frames: list[list[CandidateEntry]] = [[] for _ in q]
    peaks: list[list[ClusterSummary]] = [[] for _ in q]

    def frame_index(sample: int, time: float) -> int:
        if sample < 0 or sample >= record.sample_count or sample % 128:
            raise ValueError("Frozen sample index outside common grid")
        if not isfinite(time) or abs(time - float(record.time_s[sample])) > 5e-15:
            raise ValueError("Frozen physical time does not match raw channel")
        return sample // 128

    for r in _rows(files["candidates"]):
        c = _candidate(r)
        frames[frame_index(c.sample_index, c.time_s)].append(c)
    if any(not row for row in frames):
        raise ValueError("Frozen candidate table has missing common frames")
    for r in _rows(files["peaks"]):
        cluster = _cluster(r)
        peaks[frame_index(cluster.sample_index, cluster.time_s)].append(cluster)
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in _rows(files["curves"], methods=("B0", "B1", "S2")):
        frame_index(_int(r, "sample_index"), _float(r, "time_s"))
        grouped[r["method"]].append(r)
    curves = curves_from_candidates(q, record.time_s[q], frames)
    for method in ("B0", "B1", "S2"):
        curves[method] = _loaded_curve(method, grouped[method], q, record.time_s[q])
    stages = load_stage_segments(channel_id, repo_root)
    bundle = assemble_bundle(
        record,
        channel_name=channel_id,
        source_path=source_path,
        stop=background_stop_for_stages(record.time_s, stages),
        low=DIAGNOSTIC_FMIN_HZ,
        high=DIAGNOSTIC_FMAX_HZ,
        stages=stages,
        curves=curves,
        candidates=tuple(tuple(row) for row in frames),
        clusters=tuple(tuple(row) for row in peaks),
        mode=DiagnosticComputeMode.PRECOMPUTED_STACK,
        display_fmax_hz=display_fmax_hz,
        metrics={
            "frozen_csv_parse_s": perf_counter() - started,
            "background_reference": "FROZEN_VISUAL_ONSET"
            if any(s.stage == "onset" for s in stages)
            else "UNVERIFIED_FIXED_PREFIX_WITHOUT_VISUAL_ANNOTATIONS",
        },
        provenance=f"TASK-018 stack_v1 CSV snapshots from {parent}; B0/B1/S2 loaded; "
        "B+S=B1 where S; Dechirp/VarPro from lowercase candidate rows. "
        "Raw voltage provided by caller; S is not physical identity.",
    )
    bundle.summary_metrics["wall_s"] = perf_counter() - started
    return bundle
