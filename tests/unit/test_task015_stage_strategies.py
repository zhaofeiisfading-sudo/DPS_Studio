"""Physical counterexamples and boundary/provenance contracts for TASK-015."""
from dataclasses import replace

import numpy as np
import pytest

from dps_studio.core.models import SignalRecord
from dps_studio.core.segmentation.models import EstimatorRequest, Segment
from dps_studio.core.segmentation.strategies import Strategy, estimate_strategy


def request(y: np.ndarray, stage: str = "stationary") -> EstimatorRequest:
    t = np.arange(len(y)) / 40e9
    return EstimatorRequest(SignalRecord(t, y), t[0], t[-1], 1550e-9,
        dict(window_length_samples=1024, overlap_samples=960, nfft=4096,
             window_name="hann", minimum_frequency_hz=5e6, maximum_frequency_hz=6e9),
        Segment("s", t[0], t[-1], stage))


@pytest.mark.parametrize("phase", [0., .7, 2.4, 4.9])
def test_real_projection_resolves_low_tone_under_stronger_spur(phase: float) -> None:
    t = np.arange(8192) / 40e9
    rng = np.random.default_rng(15015)
    y = .04*np.cos(2*np.pi*40e6*t+phase) + .2*np.cos(2*np.pi*2e9*t+.3)
    y += .1 + .05*(t/t[-1])**2 + rng.normal(0, .004, len(t))
    req = request(y)
    before = req.record.voltage_v.tobytes()
    result = estimate_strategy(req, "low_glrt", Strategy(width=4096, hop=1024,
                                                        mode="glrt", degree=2))
    finite = np.isfinite(result.frequency_hz)
    assert finite.sum() >= 6
    assert np.max(abs(result.frequency_hz[finite]-40e6)) < 1e6
    assert "LOCAL_NUISANCE_ASSUMPTION" in result.quality[3]
    assert result.details["frames"][3]["candidates"][0]["frequency_hz"] > 1e9
    assert before == req.record.voltage_v.tobytes()


def test_dc_polynomial_and_spur_are_not_a_zero_velocity_measurement() -> None:
    t = np.arange(8192)/40e9
    rng = np.random.default_rng(15115)
    y = .2 + .1*(t/t[-1])**2 + .15*np.cos(2*np.pi*2e9*t)
    y += rng.normal(0, .002, len(t))
    result = estimate_strategy(request(y), "low_glrt", Strategy(width=4096, hop=1024,
                                                               mode="glrt", degree=2))
    assert not np.isfinite(result.frequency_hz).any()
    assert all(frame["prior_zero_m_s"] == 0 for frame in result.details["frames"])
    assert result.details["prior_zero_is_measurement"] is False
    assert np.isfinite(result.candidate_frequency_hz).any()


def test_subcycle_cannot_be_promoted_by_large_snr() -> None:
    t = np.arange(4096)/40e9
    y = np.cos(2*np.pi*2e6*t+.2)
    req = request(y)
    req = replace(req, workflow_options={**req.workflow_options, "minimum_frequency_hz": 1e5})
    result = estimate_strategy(req, "low_glrt", Strategy(width=4096, hop=1024,
                                                        mode="glrt", degree=2))
    assert np.isnan(result.frequency_hz).all()
    assert any("TOO_FEW_CYCLES" in flag or "SEARCH_BOUNDARY" in flag for flag in result.quality)


def test_boundary_isolation_has_no_samples_from_adjacent_region() -> None:
    t = np.arange(4096)/40e9
    left = t[2048]
    y = np.cos(2*np.pi*700e6*t)
    req = request(y, "onset")
    req = replace(req, segment=Segment("s", left, t[-1], "onset"))
    a = estimate_strategy(req, "stft_short", Strategy(width=512, hop=128))
    changed = y.copy()
    changed[:2048] = 1e6
    b = estimate_strategy(replace(req, record=SignalRecord(t, changed)), "stft_short",
                          Strategy(width=512, hop=128))
    np.testing.assert_array_equal(a.candidate_frequency_hz, b.candidate_frequency_hz)
    np.testing.assert_array_equal(a.frequency_hz, b.frequency_hz)
    assert a.time_s[0] == left
    assert all(f["support_start_sample"] >= 2048 for f in a.details["frames"])


def test_motion_and_observation_quality_are_independent_and_legacy_noise_loads() -> None:
    for alias in ("噪声", "噪声干扰", "noise"):
        assert Segment("n", 0., 1., alias).stage == "noise"
    value = Segment("a", 0., 1., "acceleration", observation_quality="interference")
    assert value.stage == "acceleration" and value.observation_quality == "interference"
    with pytest.raises(ValueError, match="observation"):
        replace(value, observation_quality="invented")


def test_wrong_stationary_label_never_claims_prior_zero_as_data() -> None:
    t = np.arange(4096)/40e9
    y = np.cos(2*np.pi*1.8e9*t)
    result = estimate_strategy(request(y), "low_glrt", Strategy(width=4096, hop=1024,
                                                               mode="glrt", degree=2))
    assert np.isnan(result.frequency_hz).all()
    assert all(frame["source"] == "UNOBSERVABLE" for frame in result.details["frames"])


def test_segment_cache_support_and_export_keep_prior_separate(tmp_path) -> None:
    import csv
    import json
    from dps_studio.core.physics import VelocityCorrectionConfig, WindowMaterial
    from dps_studio.core.segmentation import analyze_segments
    from dps_studio.core.segmentation.export import export_segmented_results

    t = np.arange(8192)/40e9
    y = .1*np.cos(2*np.pi*100e6*t) + .4*np.cos(2*np.pi*2e9*t)
    req = replace(request(y), segment=None)
    plan = (Segment("left", t[0], t[4096], "stationary", "low_glrt", "interference"),
            Segment("right", t[4096], t[-1], "stationary", "low_glrt", "interference"))
    result = analyze_segments(req, plan, correction_config=VelocityCorrectionConfig(
        window_material=WindowMaterial.NONE, measurement_angle_rad=np.pi/3))
    assert np.all(np.diff(result.time_s) > 0)
    finite = result.valid
    assert finite.sum() > 50
    np.testing.assert_allclose(result.apparent_velocity_m_s[finite], 77.5, atol=.02)
    np.testing.assert_allclose(result.corrected_velocity_m_s[finite], 155., atol=.04)
    for segment, metadata in zip(plan, result.metadata["algorithms"], strict=True):
        assert all(segment.start_s <= t[frame["support_start_sample"]]
                   for frame in metadata["details"]["frames"])
        assert "BOUNDARY_CONTEXT" not in "|".join(result.quality)
    paths = export_segmented_results({"ch": result}, tmp_path/"out")
    with paths[0].open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert all(row["prior_source"] == "OPERATOR_PRIOR_NOT_MEASUREMENT" for row in rows)
    assert all(row["observation_quality"] == "interference" for row in rows)
    assert all(float(row["stationary_prior_m_s"]) == 0. for row in rows)
    assert all(float(row["frequency_hz"]) > 0 for row in rows if int(row["valid"]))
    meta = json.loads(paths[1].read_text(encoding="utf-8"))
    assert meta["algorithms"][0]["details"]["frames"][0]["candidates"]
