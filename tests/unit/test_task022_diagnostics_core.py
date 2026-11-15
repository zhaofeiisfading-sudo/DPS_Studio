"""Numerical replay, waveform fits, dependency isolation, and diagnostic semantics."""

from __future__ import annotations

import csv
import gzip
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError, fields, replace
from functools import lru_cache
from pathlib import Path
from threading import Event
from time import perf_counter

import numpy as np
import pytest

from dps_studio.core.diagnostics import (
    COMPARED_CURVE_METHODS,
    CandidateEntry,
    DiagnosticBundle,
    DiagnosticCancelledError,
    DiagnosticComputeMode,
    DiagnosticPreset,
    StageSegment,
    compute_diagnostic_bundle,
    discover_presets,
    explain_candidate,
    inspect_frame,
    load_precomputed_bundle,
    load_raw_channel_arrays,
    load_raw_channel_result,
    load_stage_segments,
    summarize_frame_diagnosis,
)
from dps_studio.core.diagnostics.models import BoolArray, FloatArray
from dps_studio.core.models import SignalRecord, SignalValidationError

ROOT = Path(__file__).resolve().parents[2]
STACK = ROOT / "artifacts/TASK-018/data/stack_v1"


@pytest.fixture(scope="module")
def synthetic() -> tuple[FloatArray, FloatArray, tuple[StageSegment, ...]]:
    fs = 40e9
    t = np.arange(8192, dtype=np.float64) / fs
    rng = np.random.default_rng(22)
    s = np.maximum(t - t[2048], 0.0)
    ramp = np.minimum(s, 12e-9)
    phase = 2 * np.pi * (1e9 * s + 0.5 * 4e17 * ramp**2 + 4e17 * 12e-9 * np.maximum(s - 12e-9, 0.0))
    y = 8.0 + 0.02 * np.cos(2 * np.pi * 3.2e9 * t) + rng.normal(0.0, 0.002, len(t))
    y += (t >= t[2048]) * (1.0 + 0.4 * np.cos(phase))
    stages = (
        StageSegment("quiet", float(t[0]), float(t[2048]), "stationary"),
        StageSegment("rise", float(t[2048]), float(t[2560]), "onset"),
        StageSegment("fall", float(t[2560]), float(t[4096]), "decline"),
        StageSegment("weak", float(t[4096]), float(t[-1]), "weak_signal"),
    )
    return t, y, stages


@pytest.fixture(scope="module")
def fast(synthetic: tuple[FloatArray, FloatArray, tuple[StageSegment, ...]]) -> DiagnosticBundle:
    t, y, stages = synthetic
    return compute_diagnostic_bundle(t, y, channel_name="synthetic", stages=stages)


@pytest.fixture(scope="module")
def full(synthetic: tuple[FloatArray, FloatArray, tuple[StageSegment, ...]]) -> DiagnosticBundle:
    t, y, stages = synthetic
    return compute_diagnostic_bundle(
        SignalRecord(t, y),
        channel_name="synthetic",
        stages=stages,
        mode=DiagnosticComputeMode.FULL_S2,
    )


def test_modes_dc_and_spectrograms(fast: DiagnosticBundle, full: DiagnosticBundle) -> None:
    assert set(fast.curves) == set(COMPARED_CURVE_METHODS) - {"S2"}
    assert set(full.curves) == set(COMPARED_CURVE_METHODS)
    assert fast.summary_metrics["s2_status"] == "NOT_RUN"
    q = fast.common_sample_indices
    np.testing.assert_array_equal(q, np.arange(0, len(fast.time_s), 128))
    quiet = (q >= 1024) & (q <= 1536)
    assert np.all(fast.curves["B0"].frequency_hz[quiet] < 250e6)
    assert np.all(fast.curves["B1"].frequency_hz[quiet] > 3e9)
    assert np.all(fast.curves["B1"].frequency_hz[quiet] < 3.4e9)
    for layer in (fast.raw_spectrogram, fast.demeaned_spectrogram):
        assert layer.power_db.shape == (len(layer.frequency_hz), len(q))
        np.testing.assert_array_equal(layer.time_s, fast.common_times_s)
        assert layer.frequency_hz[-1] <= 10e9
        assert np.isnan(layer.power_db[:, 0]).all()
    assert np.all(fast.raw_spectrogram.power_db[0, quiet] > 10.0)
    assert np.all(fast.demeaned_spectrogram.power_db[0, quiet] < -25.0)
    assert {c.estimator for row in full.candidates_by_frame for c in row} == {
        "B0",
        "B1",
        "B2",
        "dechirp",
        "varpro",
        "clutter_varpro",
        "low_glrt",
        "matrix_pencil",
    }
    assert all(len(row) == 9 for row in full.candidates_by_frame)
    for name in fast.curves:
        np.testing.assert_array_equal(
            fast.curves[name].frequency_hz, full.curves[name].frequency_hz
        )
    b1, bs = full.curves["B1"], full.curves["B+S"]
    np.testing.assert_array_equal(
        bs.frequency_hz, np.where(b1.s_supported, b1.frequency_hz, np.nan)
    )
    np.testing.assert_array_equal(bs.selected, b1.s_supported)
    assert np.all(~b1.s_supported | full.curves["S2"].s_supported)


@pytest.mark.parametrize("width", [256, 512])
def test_exact_fit_vectors_and_chirp_rescue(
    synthetic: tuple[FloatArray, FloatArray, tuple[StageSegment, ...]],
    width: int,
) -> None:
    t, y, _ = synthetic
    q, rate = 2304, 4e17
    hz = 1e9 + rate * (t[q] - t[2048])
    ev = inspect_frame(
        t, y, q, 1800, focus_frequency_hz=float(hz), focus_chirp_hz_s=rate, window_width=width
    )
    assert ev.raw_chirp_r2 > 0.98
    if width == 256:
        assert ev.raw_tone_r2 < 0.20
        assert ev.spectrally_supported
    for model, r2, rms in (
        (ev.tone_fit_detrended_v, ev.raw_tone_r2, ev.raw_tone_residual_rms_v),
        (ev.chirp_fit_detrended_v, ev.raw_chirp_r2, ev.raw_chirp_residual_rms_v),
    ):
        assert model.shape == ev.tau_s.shape == (width,)
        error = ev.detrended_v - model
        assert 1 - float(error @ error) / float(ev.detrended_v @ ev.detrended_v) == pytest.approx(
            r2, abs=1e-14
        )
        assert np.sqrt(np.mean(error**2)) == pytest.approx(rms, abs=1e-14)
    np.testing.assert_array_equal(ev.chirp_fit_raw_v, ev.baseline_v + ev.chirp_fit_detrended_v)
    np.testing.assert_allclose(ev.raw_voltage_v, ev.baseline_v + ev.detrended_v, atol=1e-14)
    np.testing.assert_allclose(
        ev.tau_s, (np.arange(q - width // 2, q + width // 2) - q) / 40e9, atol=1e-22
    )
    assert ev.spectrum_freq_hz.shape == ev.local_psd_db.shape == ev.background_psd_db.shape
    assert ev.cycles_256 == pytest.approx(hz * float(np.ptp(ev.tau_s)))


def test_missing_background_and_edge_windows(fast: DiagnosticBundle) -> None:
    ev = inspect_frame(fast.time_s, fast.voltage_v, 0, 0, focus_frequency_hz=3.2e9)
    assert len(ev.tau_s) == 128
    assert np.isnan(ev.background_psd_db).all()
    assert np.isnan(ev.background_gain_db)
    assert not ev.spectrally_supported
    long = inspect_frame(
        fast.time_s, fast.voltage_v, 1024, 512, focus_frequency_hz=3.2e9, window_width=512
    )
    assert np.isfinite(long.background_psd_db).all()


def test_immutability_filters_and_tags(full: DiagnosticBundle) -> None:
    assert full.indices_for_filter("onset")
    assert full.indices_for_filter("decline")
    assert full.indices_for_filter("weak_signal")
    assert full.indices_for_filter("disagreement")
    assert full.frame_index_for_time(float(full.common_times_s[3]) + 1e-15) == 3
    for category, mask in (
        ("g_without_s", full.frame_tags.g_without_s_mask),
        ("s2_rescued", full.frame_tags.s2_rescued_mask),
        ("competing", full.frame_tags.competing_clusters_mask),
        ("high_without_s", full.frame_tags.high_without_s_mask),
    ):
        assert full.indices_for_filter(category) == np.flatnonzero(mask).tolist()
    with pytest.raises(ValueError):
        full.indices_for_filter("unknown_filter")
    with pytest.raises(ValueError):
        full.frame_index_for_time(np.nan)
    with pytest.raises(ValueError):
        full.curves["B1"].frequency_hz[0] = 0.0
    with pytest.raises(ValueError):
        full.voltage_v.setflags(write=True)
    with pytest.raises(FrozenInstanceError):
        setattr(full, "channel_name", "changed")


@pytest.mark.parametrize("at_step", ["before", "B1", "B0", "fusion", "complete"])
def test_cooperative_cancel(fast: DiagnosticBundle, at_step: str) -> None:
    cancel = Event()
    if at_step == "before":
        cancel.set()

    def progress(label: str) -> None:
        if label == at_step:
            cancel.set()

    with pytest.raises(DiagnosticCancelledError):
        compute_diagnostic_bundle(
            fast.time_s,
            fast.voltage_v,
            channel_name="cancel",
            progress_callback=progress,
            cancel_event=cancel,
        )


@pytest.mark.parametrize("case", ["nan", "uneven", "short", "band", "precomputed"])
def test_validation(fast: DiagnosticBundle, case: str) -> None:
    t, y = np.array(fast.time_s), np.array(fast.voltage_v)
    if case == "nan":
        y[100] = np.nan
    if case == "uneven":
        t[100] += 1e-12
    if case == "short":
        t, y = t[:500], y[:500]
    with pytest.raises((ValueError, SignalValidationError)):
        compute_diagnostic_bundle(
            t,
            y,
            channel_name="invalid",
            fmin_hz=-1.0 if case == "band" else 50e6,
            mode=DiagnosticComputeMode.PRECOMPUTED_STACK
            if case == "precomputed"
            else DiagnosticComputeMode.FAST_CORE,
        )


def _example(
    *,
    raw_frequency_hz: float = 3e9,
    c_present: bool = True,
    g_accepted: bool = True,
    s_supported: bool = True,
    native_quality: str = "",
    spectral_contrast_db: float = 15.0,
    background_gain_db: float = 8.0,
    cycles_256: float = 19.0,
    raw_tone_r2: float = 0.5,
    raw_chirp_r2: float = 0.5,
) -> CandidateEntry:
    return CandidateEntry(
        0,
        128,
        3.2e-9,
        "B1",
        "STFT",
        raw_frequency_hz=raw_frequency_hz,
        frequency_hz=3e9,
        applicable=True,
        run_status="RAN",
        c_present=c_present,
        g_accepted=g_accepted,
        s_supported=s_supported,
        native_quality=native_quality,
        spectral_contrast_db=spectral_contrast_db,
        background_gain_db=background_gain_db,
        cycles_256=cycles_256,
        raw_tone_r2=raw_tone_r2,
        raw_chirp_r2=raw_chirp_r2,
    )


@pytest.mark.parametrize(
    "g,s,code",
    [
        (True, True, "G_S"),
        (True, False, "G_WITHOUT_S"),
        (False, True, "S_WITHOUT_G"),
        (False, False, "C_ONLY"),
    ],
)
def test_explanation_c_g_s(g: bool, s: bool, code: str) -> None:
    verdict, yes, no = explain_candidate(_example(g_accepted=g, s_supported=s))
    assert verdict == code
    text = " ".join((*yes, *no))
    assert "C=1" in text and f"G={int(g)}" in text
    assert sum("S 门限" in x for x in (*yes, *no)) == 4
    if g and not s:
        assert "⚠️ 可疑" in text
    if s and not g:
        assert "🔍 隐藏信号" in text


@pytest.mark.parametrize("hz", [49e6, 6.3e9])
def test_explanation_outside_band(hz: float) -> None:
    code, _, no = explain_candidate(
        _example(raw_frequency_hz=hz, c_present=False, g_accepted=False, s_supported=False)
    )
    assert code == "NO_C"
    assert "50 MHz–6 GHz" in " ".join(no)


@pytest.mark.parametrize(
    "token",
    ["PRE_EVENT", "NO_EVENT", "LOW_CONTRAST", "LOW_WAVEFORM_SUPPORT", "UNOBSERVABLE_NOT_ZERO"],
)
def test_native_quality_tokens(token: str) -> None:
    _, _, no = explain_candidate(_example(g_accepted=False, native_quality=token))
    assert token in " ".join(no)


def test_chirp_gate_and_anomaly_explanations(full: DiagnosticBundle) -> None:
    cluster = next(c for row in full.clusters_by_frame for c in row)
    anomaly = replace(cluster, high_without_s=True, s_clusters_at_center=2)
    _, yes, no = explain_candidate(
        _example(raw_tone_r2=0.1, raw_chirp_r2=0.45), cluster=anomaly, dc_leak_hint=True
    )
    assert "Chirp 调频救回" in " ".join(yes)
    text = " ".join(no)
    assert "DC / 低频泄漏" in text
    assert "high_without_s" in text
    assert "竞争支路" in text
    _, _, no = explain_candidate(
        _example(
            spectral_contrast_db=9.0,
            background_gain_db=5.0,
            cycles_256=0.9,
            raw_tone_r2=0.19,
            raw_chirp_r2=0.19,
        )
    )
    assert sum("S 门限" in x for x in no) == 4
    summary = summarize_frame_diagnosis(full, 20)
    assert "GHz" in summary.agreement_zh
    assert "不确认物理主目标支路身份" in summary.physical_identity_caveat_zh
    assert summary.selection_reasons_zh and summary.rejection_reasons_zh


@lru_cache(maxsize=None)
def _real(channel: str) -> DiagnosticBundle:
    presets = {p.channel_id: p for p in discover_presets(ROOT)}
    if channel not in presets or not (STACK / f"{channel}__curves.csv.gz").is_file():
        pytest.skip("Optional real raw channel / TASK-018 frozen stack absent")
    t, y = load_raw_channel_arrays(presets[channel], ROOT)
    loaded = load_precomputed_bundle(
        channel, t, y, repo_root=ROOT, source_path=ROOT / presets[channel].relative_path
    )
    assert loaded is not None
    return loaded


def test_real_presets_loader_and_stages() -> None:
    b = _real("ch3_ch1")
    presets = discover_presets(ROOT)
    assert len(presets) == 14
    assert [p.channel_id for p in presets[:4]] == [
        "20201210m_ch1",
        "ch3_ch1",
        "20260630-1_ch2",
        "20201214m_ch1",
    ]
    assert set(b.curves) == set(COMPARED_CURVE_METHODS)
    assert {s.stage for s in b.stages} >= {"onset", "weak_signal"}
    assert _real("20201210m_ch1").indices_for_filter("decline")
    assert b.candidates_by_frame and b.clusters_by_frame
    assert all(len(row) == 9 for row in b.candidates_by_frame)
    assert b.compute_mode == "precomputed_stack"
    onset = next(s for s in b.stages if s.stage == "onset")
    assert onset.start_range_s is not None
    assert b.background_stop_index == min(
        4096, int(np.searchsorted(b.time_s, onset.start_range_s[0] - 2e-9))
    )


@pytest.mark.parametrize("channel", ["20201210m_ch1", "ch3_ch1"])
def test_live_all_estimators_exact_real_parity(channel: str) -> None:
    frozen = _real(channel)
    started = perf_counter()
    live = compute_diagnostic_bundle(
        frozen.time_s,
        frozen.voltage_v,
        channel_name=frozen.channel_name,
        mode=DiagnosticComputeMode.FULL_S2,
        stages=frozen.stages,
    )
    elapsed = perf_counter() - started
    assert live.background_stop_index == frozen.background_stop_index
    for name in COMPARED_CURVE_METHODS:
        a, b = live.curves[name], frozen.curves[name]
        for field in (
            "frequency_hz",
            "proposal_hz",
            "c_present",
            "g_accepted",
            "s_supported",
            "selected",
            "selected_source",
            "quality",
            "cluster_id",
        ):
            np.testing.assert_array_equal(
                getattr(a, field), getattr(b, field), err_msg=f"{name}.{field}"
            )
    for current_rows, archived_rows in zip(
        live.candidates_by_frame, frozen.candidates_by_frame, strict=True
    ):
        for ca, cb in zip(current_rows, archived_rows, strict=True):
            for model_field in fields(CandidateEntry):
                actual, expected = getattr(ca, model_field.name), getattr(cb, model_field.name)
                if isinstance(actual, float):
                    np.testing.assert_array_equal(actual, expected, err_msg=model_field.name)
                else:
                    assert actual == expected, model_field.name
    for current_clusters, archived_clusters in zip(
        live.clusters_by_frame, frozen.clusters_by_frame, strict=True
    ):
        assert current_clusters == archived_clusters
    (ROOT / f"artifacts/TASK-022/tmp/parity_{channel}.json").write_text(
        json.dumps(
            {
                "channel": frozen.channel_name,
                "frames": len(live.common_sample_indices),
                "all_six_curves": "exact array equality including NaN positions",
                "all_candidate_metrics": "exact",
                "all_clusters": "exact",
                "wall_s": elapsed,
                "timings": live.summary_metrics,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "channel,q,estimator",
    [
        ("20201210m_ch1", 2304, "B1"),
        ("ch3_ch1", 42752, "B0"),
        ("ch3_ch1", 42752, "B1"),
        ("ch3_ch1", 42752, "dechirp"),
        ("ch3_ch1", 42752, "varpro"),
        ("20260630-1_ch2", 130176, "B1"),
    ],
)
def test_inspect_real_candidate_metric_parity(channel: str, q: int, estimator: str) -> None:
    b = _real(channel)
    if channel == "20260630-1_ch2":
        idx = b.frame_index_for_time(float(b.time_s[0]) + 3254.4e-9)
        q = int(b.common_sample_indices[idx])
    else:
        idx = int(np.flatnonzero(b.common_sample_indices == q)[0])
    c = next(c for c in b.candidates_by_frame[idx] if c.estimator == estimator)
    assert c.c_present
    ev = inspect_frame(
        b.time_s,
        b.voltage_v,
        q,
        b.background_stop_index,
        focus_frequency_hz=c.frequency_hz,
        focus_chirp_hz_s=c.chirp_hz_s,
    )
    for field in (
        "spectral_contrast_db",
        "background_gain_db",
        "relative_strongest_db",
        "competitor_advantage_db",
        "raw_tone_r2",
        "raw_chirp_r2",
        "raw_tone_residual_rms_v",
        "raw_chirp_residual_rms_v",
        "cycles_256",
    ):
        np.testing.assert_array_equal(getattr(ev, field), getattr(c, field), err_msg=field)
    assert ev.spectrally_supported == c.s_supported
    if channel == "ch3_ch1":
        if estimator in ("dechirp", "varpro"):
            assert ev.raw_tone_r2 < 0.20 and ev.raw_chirp_r2 >= 0.40
            assert ev.spectrally_supported
        else:
            assert not ev.spectrally_supported


def test_real_dc_and_competing_showcases() -> None:
    b = _real("20201210m_ch1")
    a, short = b.curves["B0"], b.curves["B1"]
    mask = a.selected & (a.frequency_hz < 250e6) & ~a.s_supported & short.s_supported
    assert mask.any()
    idx = int(np.flatnonzero(mask)[0])
    summary = summarize_frame_diagnosis(b, idx)
    assert "DC / 低频泄漏" in " ".join(summary.rejection_reasons_zh)
    b = _real("20260630-1_ch2")
    idx = b.frame_index_for_time(float(b.time_s[0]) + 3254.4e-9)
    assert b.frame_tags.stage[idx] == "weak_signal"
    assert b.curves["B+S"].s_supported[idx] and b.curves["S2"].s_supported[idx]
    assert abs(b.curves["B+S"].frequency_hz[idx] - b.curves["S2"].frequency_hz[idx]) > 100e6
    assert b.frame_tags.competing_clusters_mask[idx]
    assert b.frame_tags.disagreement_mask[idx]
    chirp = _real("ch3_ch1")
    idx = int(np.flatnonzero(chirp.common_sample_indices == 42752)[0])
    assert chirp.frame_tags.s2_rescued_mask[idx]


def test_missing_artifacts_and_strict_raw_reader(tmp_path: Path) -> None:
    assert discover_presets(tmp_path) == ()
    assert load_precomputed_bundle("absent", [], [], repo_root=tmp_path) is None
    assert load_stage_segments("absent", tmp_path) == ()
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    path = raw / "headerless.dat"
    path.write_text("0,2,3\n1,4,5\n2,6,7\n", encoding="utf-8")
    assert len(discover_presets(tmp_path)) == 2
    p = DiagnosticPreset("test", path.relative_to(tmp_path), 2, "units", 1e-9, 0.001)
    result = load_raw_channel_result(p, tmp_path)
    assert result.row_count == 3 and result.header is None
    t, v = load_raw_channel_arrays(p, tmp_path)
    np.testing.assert_array_equal(t, np.array([0.0, 1.0, 2.0]) * 1e-9)
    np.testing.assert_array_equal(v, np.array([3.0, 5.0, 7.0]) * 0.001)


def test_imports_without_packaging_exclusions() -> None:
    code = """
import sys, importlib.abc
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        forbidden = ('PySide6','pyqtgraph','matplotlib','pandas','tkinter')
        if (fullname.split('.')[0] in forbidden
                or fullname.startswith(('dps_studio.research','scripts.'))):
            raise ImportError('Forbidden dependency: '+fullname)
sys.meta_path.insert(0, Block())
from dps_studio.core.diagnostics import compute_diagnostic_bundle
import numpy as np
t=np.arange(2048)/40e9
a=compute_diagnostic_bundle(t,np.sin(2*np.pi*2e9*t),channel_name='isolated')
assert 'S2' not in a.curves
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=90,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_frozen_curves_direct_csv_contract() -> None:
    b = _real("ch3_ch1")
    rows: dict[str, list[dict[str, str]]] = {k: [] for k in ("B0", "B1", "S2")}
    with gzip.open(STACK / "ch3_ch1__curves.csv.gz", "rt", encoding="utf-8") as handle:
        for r in csv.DictReader(handle):
            if r["method"] in rows:
                rows[r["method"]].append(r)
    for method, data in rows.items():
        data.sort(key=lambda r: int(r["sample_index"]))
        curve = b.curves[method]
        np.testing.assert_array_equal(
            curve.frequency_hz, [float(r["frequency_hz"] or "nan") for r in data]
        )
        for field, column in (("g_accepted", "G"), ("s_supported", "S"), ("selected", "selected")):
            actual: BoolArray = getattr(curve, field)
            np.testing.assert_array_equal(actual, [r[column] == "True" for r in data])
