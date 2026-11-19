"""TASK-024 production-path parity, scientific evidence, and cancellation."""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from threading import Event, Thread
from time import perf_counter

import numpy as np
import pytest

from dps_studio.core.models import SignalRecord
from dps_studio.core.stft_m4 import (
    ComparisonCancelledError,
    DiffCategory,
    Estimate,
    classify_differences,
    compute_b1_stft,
    compute_comparison_bundle,
    compute_m4_phase_coherent,
    convert_frequency_for_display,
    inspect_frame_waveform,
)
from dps_studio.core.stft_m4.models import RawEvidence


def test_core_package_headless() -> None:
    proc = subprocess.run(
        [sys.executable, "-B", "-c",
         "import sys; import dps_studio.core.stft_m4; "
         "assert not {'PySide6','pyqtgraph','matplotlib','scripts'} & "
         "{name.split('.')[0] for name in sys.modules}"],
        env=os.environ.copy(), capture_output=True, text=True, timeout=20, check=False,
    )
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("channel,rate", [
    ("20201211m_ch1", 40e9), ("20221017a_ch1", 80e9), ("20260630-1_ch1", 40e9),
])
def test_real_channel_exact_parity(channel: str, rate: float) -> None:
    from scripts.research.task023.common import load_channel, run_baselines
    from scripts.research.task023.phase_coherent import m4_phase_coherent

    frozen = load_channel(channel)
    record = SignalRecord(frozen.t, frozen.y)
    assert record.sample_rate_hz == pytest.approx(rate, rel=1e-8)
    expected_b1 = run_baselines(frozen)["B1"]
    b1, raster = compute_b1_stft(record)
    np.testing.assert_array_equal(raster.time_s, frozen.t[frozen.q])
    np.testing.assert_array_equal(b1.sample_index, frozen.q)
    for name in ("accepted_hz", "candidate_hz", "chirp_hz_s"):
        np.testing.assert_array_equal(getattr(b1, name), getattr(expected_b1, name), err_msg=name)
    start = perf_counter()
    expected = m4_phase_coherent(frozen)
    ref_wall = perf_counter()-start
    start = perf_counter()
    actual = compute_m4_phase_coherent(record)
    core_wall = perf_counter()-start
    print(f"{channel}: TASK-023 {ref_wall:.6f} s, core {core_wall:.6f} s")
    for name in ("accepted_hz", "candidate_hz", "chirp_hz_s"):
        np.testing.assert_array_equal(getattr(actual, name), getattr(expected, name), err_msg=name)
    for name in ("secondary_hz", "persistent_cw_overlap", "verification_window_ns"):
        np.testing.assert_array_equal(getattr(actual, name), expected.diagnostics[name], err_msg=name)
    for name in ("raw_tone_r2_64ns", "raw_chirp_r2_64ns", "raw_chirp_r2_256ns",
                 "split_half_coherence_256ns", "local_center_snr_32ns"):
        np.testing.assert_allclose(getattr(actual.raw, name), getattr(expected.raw, name), atol=1e-12)
    if channel == "20260630-1_ch1":
        assert core_wall < ref_wall
        i = int(np.argmin(abs(raster.time_s-747.026015e-6)))
        assert actual.m4_rejection_reason_code[i] == "pre_edge_side_veto"


def _record(n: int = 8192) -> SignalRecord:
    t = np.arange(n)/40e9
    centered = t-80e-9
    signal = np.where(centered > 0., .04+.015*np.cos(2*np.pi*(
        .65e9*centered + .5e16*centered**2)), 0.)
    return SignalRecord(t, signal + np.random.default_rng(24).normal(0., .0004, n))


def test_cancel_during_verification() -> None:
    record = _record(20000)
    cancel, verifying = Event(), Event()
    progress: list[int] = []
    cancellation_times: list[float] = []

    def progress_callback(percent: int, _stage: str) -> None:
        progress.append(percent)
        if percent == 58:
            verifying.set()

    def external_cancel() -> None:
        if verifying.wait(15):
            cancellation_times.append(perf_counter())
            cancel.set()

    trigger = Thread(target=external_cancel)
    trigger.start()
    try:
        with pytest.raises(ComparisonCancelledError):
            compute_comparison_bundle(record, cancel_event=cancel, progress_callback=progress_callback)
    finally:
        trigger.join()
    assert cancellation_times and perf_counter()-cancellation_times[0] < .25
    assert progress[0] == 0 and 58 in progress and progress == sorted(progress) and 100 not in progress


def test_default_frequency_confirmed_velocity() -> None:
    input_hz = np.array([0., 5e9, np.nan])
    values, unit, velocity = convert_frequency_for_display(input_hz)
    assert (unit, velocity) == ("GHz", False)
    np.testing.assert_array_equal(values, input_hz/1e9)
    wave = 1550e-9
    values, unit, velocity = convert_frequency_for_display(input_hz, confirmed_wavelength_m=wave)
    assert (unit, velocity) == ("m/s", True)
    np.testing.assert_array_equal(values, (wave/2)*input_hz)
    for invalid in (0., -1., float("inf"), float("nan"), True):
        with pytest.raises(ValueError):
            convert_frequency_for_display(input_hz, confirmed_wavelength_m=invalid)
    for invalid in (-1., float("inf"), -float("inf")):
        with pytest.raises(ValueError):
            convert_frequency_for_display([invalid], confirmed_wavelength_m=wave)


def test_classification_exhaustive_at_thresholds() -> None:
    b_hz = np.array([500, np.nan, np.nan, 500, 500, 500, 500, np.nan, np.nan])*1e6
    m_hz = np.array([550, 500, 500, 750, 751, np.nan, np.nan, np.nan, 500])*1e6
    q = np.arange(len(b_hz), dtype=np.int64)
    z = np.zeros(len(q))
    raw_b = RawEvidence(z, np.array([0., 0., 0., 0., 0., .149, .15, 0., 0.]), z, z, z)
    raw_m = RawEvidence(z, np.array([0., .15, .5, 0., 0., 0., 0., 0., 0.]),
                        np.r_[z[:-1], .04], np.r_[z[:-1], .58], z)
    cw = z.astype(np.bool_)
    cw[2] = True
    b1 = Estimate(q, b_hz, b_hz, z, raw_b, {}, ("",)*len(q))
    m4 = replace(b1, accepted_hz=m_hz, candidate_hz=m_hz, raw=raw_m,
                 diagnostics={"persistent_cw_overlap": cw})
    assert classify_differences(b1, m4) == (*DiffCategory, DiffCategory.M4_ADDED_SUPPORTED)


def test_bundle_immutable_with_local_original_voltage() -> None:
    progress = []
    record = _record()
    bundle = compute_comparison_bundle(
        record, include_matched_stft=True, fmax_hz=25e9,
        progress_callback=lambda percent, _stage: progress.append(percent),
    )
    assert progress == sorted(progress) and progress[0] == 0 and progress[-1] == 100
    assert bundle.record is record
    assert bundle.fmax_hz == .49*record.sample_rate_hz
    assert len(bundle.diff_categories) == len(bundle.q)
    assert bundle.matched_stft is not None
    assert np.isnan(bundle.matched_stft.candidate_hz[0])
    coherent = bundle.m4_coherent_map
    assert coherent is not None
    np.testing.assert_array_equal(coherent.time_s, bundle.b1_spectrogram.time_s)
    assert coherent.power_db.shape == (len(bundle.q), len(coherent.frequency_hz))
    assert np.isfinite(coherent.power_db).mean() > .5
    assert np.diff(coherent.frequency_hz).mean() > np.diff(bundle.b1_spectrogram.frequency_hz).mean()
    assert np.isfinite(coherent.power_db).any()
    for array in (bundle.b1.accepted_hz, bundle.q, coherent.power_db, bundle.rail_mask):
        with pytest.raises(ValueError):
            array.setflags(write=True)
    i = len(bundle.q)//2
    inspected = inspect_frame_waveform(bundle, i)
    positions = np.searchsorted(record.time_s, inspected.time_s)
    np.testing.assert_array_equal(inspected.voltage_v, record.voltage_v[positions])
    np.testing.assert_allclose(inspected.baseline_v+inspected.residual_v, inspected.voltage_v)
    assert len(inspected.fit_time_s) == len(inspected.b1_fit_v) == len(inspected.m4_fit_v) == 256
    assert inspected.fit_window_s[1]-inspected.fit_window_s[0] == pytest.approx(6.4e-9)
    assert inspected.center_time_s == bundle.frame_time_s[i]
    assert inspected.reason.value == bundle.m4.m4_rejection_reason_code[i]
    assert inspected.category == bundle.diff_categories[i]
    with pytest.raises(IndexError):
        inspect_frame_waveform(bundle, -1)


def test_empty_center_grid_and_irregular_time() -> None:
    assert compute_comparison_bundle(_record(512)).q.size == 0
    with pytest.raises(ValueError, match="均匀采样"):
        compute_comparison_bundle(SignalRecord([0., 1e-9, 3e-9], [0., 1., 0.]))
