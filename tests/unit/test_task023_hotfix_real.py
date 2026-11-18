"""Production balanced-profile checks on the original oscilloscope channels."""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.io import read_delimited_signals
from dps_studio.core.quality import SignalState
from dps_studio.core.workflow import (
    PRE_EVENT_DISPLAY_ORIGIN, analyze_stft_results, compute_profile_stfts,
    configure_channel_event_reference, load_workflow_config,
)
from dps_studio.core.workflow.acceleration import channel_acceleration, channel_dechirp


ROOT = Path(__file__).resolve().parents[2]


def _analyze(filename: str, column: int):
    config = load_workflow_config(ROOT / "configs/pdv_studio_defaults.toml", repository_root=ROOT)
    name = f"pdv_channel_{column}"
    records = read_delimited_signals(
        ROOT / "data/raw" / filename, time_column=0, voltage_columns={name: column},
        delimiter=",", has_header=False, encoding="utf-8", time_scale=1.0,
        voltage_scales={name: 1.0},
    ).records
    profile = config.analysis.default_profile
    stfts = compute_profile_stfts(records, profile=profile)
    stft = stfts[name]
    result = analyze_stft_results(
        stfts, minimum_frequency_hz=profile.minimum_frequency_hz,
        maximum_frequency_hz=profile.maximum_frequency_hz,
        analysis_start_time_s=float(stft.time_s[0]), analysis_end_time_s=float(stft.time_s[-1]),
        vacuum_wavelength_m=config.analysis.vacuum_wavelength_m,
        detection_config=config.quality.signal_detection, event_candidate_config=config.event_candidate,
        automatic_ridge_selection_config=config.automatic_ridge_selection,
        velocity_correction_config=config.velocity_correction,
        background_guard_window_scale=config.quality.background_guard_window_scale,
        minimum_background_bin_count=config.quality.minimum_background_bin_count,
        assume_pre_event_zero_for_display=True,
    )[name]
    return records[name], result

@pytest.mark.parametrize(("filename", "column"), [
    ("20260607.csv", 1), ("20260630-1.csv", 2), ("20260630-2.csv", 1), ("20260701.csv", 1),
    ("ch2.csv", 1), ("ch3.csv", 1), ("ch4.csv", 1),
])
def test_balanced_velocity_semantics(filename, column):
    record, analysis = _analyze(filename, column)
    detection = analysis.signal_detection_result
    time = detection.time_s
    measured = np.array([s is SignalState.MEASURED for s in detection.signal_states])
    assert detection.manual_event_reference_time_s is None
    assert analysis.velocity_origins == tuple(s.value for s in detection.signal_states)
    for vector in (
        analysis.working_frequency_hz, analysis.continuous_apparent_velocity_m_s,
        analysis.continuous_corrected_velocity_m_s, analysis.plot_velocity_m_s,
        analysis.apparent_velocity_m_s, analysis.corrected_velocity_m_s,
    ):
        np.testing.assert_array_equal(np.isfinite(vector), measured)
        assert np.isnan(vector[~measured]).all()
    assert np.isnan(channel_acceleration(analysis).acceleration_m_s2[~measured]).all()

    reference = analysis.stream_event_candidates.primary_candidate_time_s
    assert reference is not None
    active = configure_channel_event_reference(
        analysis, event_reference_time_s=reference, event_reference_source="user_adopted",
        enable_pre_event_display=True, pre_event_display_velocity_m_s=0.0,
    )
    platform = np.array(active.velocity_origins) == PRE_EVENT_DISPLAY_ORIGIN
    assert platform.any() and np.all(time[platform] < reference)
    assert not (platform & measured).any()
    np.testing.assert_array_equal(active.plot_velocity_m_s[platform], 0.0)
    np.testing.assert_array_equal(active.plot_velocity_m_s[measured], analysis.corrected_velocity_m_s[measured])
    assert np.isnan(active.plot_velocity_m_s[~(platform | measured)]).all()
    assert np.isnan(active.corrected_velocity_m_s[platform]).all()
    if filename == "20260607.csv":
        assert not measured[time < reference].any()
        assert platform[:100].sum() >= 90
    elif filename == "20260630-1.csv":
        assert platform[:100].sum() >= 90
        assert analysis.apparent_velocity_m_s[1015] == pytest.approx(163.819, abs=0.001)
        assert measured[697:700].all()
        assert not platform[700:].any()
    elif filename == "20260630-2.csv":
        assert time[153] < reference and np.isnan(active.plot_velocity_m_s[153])
    elif filename == "ch2.csv":
        assert (time[355:360] < reference).all()
        assert np.isnan(active.plot_velocity_m_s[355:360]).all()
    elif filename in ("ch3.csv", "ch4.csv"):
        spikes = [9, 21] if filename == "ch3.csv" else [55, 65, 67]
        assert not measured[spikes].any()

    # The supplied JSON covers the first two records. The additional hashes
    # were captured with the same entry point on Production b6557b0 before editing.
    oracle = json.loads((ROOT / "tests/reference/task023_pass1_before_sha256.json").read_text())
    if filename not in oracle:
        return
    baseline = ROOT / "artifacts/task023_hotfix/baseline/before_metrics.json"
    if baseline.exists():
        supplied = json.loads(baseline.read_text()).get(filename)
        if supplied:
            assert oracle[filename] == {k: supplied[k]["sha256"] for k in oracle[filename]}
    apparent = analysis.apparent_velocity_m_s.copy()
    corrected = analysis.corrected_velocity_m_s.copy()
    if filename == "20260607.csv":
        # Restore the two rejected values on comparison copies only, so the
        # original full-array digests verify every other byte, including NaNs.
        apparent[[20, 111]] = [2655.8947848000603, 1837.9313652481494]
        corrected[[20, 111]] = [2080.101232769797, 1443.8228924341954]
    arrays = {
        "stft_spectrum": analysis.stft_result.spectrum, "stft_time_s": time,
        "stft_freq_hz": analysis.stft_result.frequency_hz,
        "formal_apparent": apparent, "formal_corrected": corrected,
        "dechirp_accel": channel_dechirp(record, analysis).apparent_acceleration_m_s2,
    }
    for field, values in arrays.items():
        assert hashlib.sha256(values.tobytes()).hexdigest() == oracle[filename][field], field
