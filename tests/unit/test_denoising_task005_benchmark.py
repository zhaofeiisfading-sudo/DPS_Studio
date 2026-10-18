"""Independent voltage synthesis and denominators for the TASK005 auxiliary check."""
from __future__ import annotations

from importlib import import_module
from importlib.util import find_spec
from typing import Any

import numpy as np
import pytest


def benchmark() -> Any:
    return import_module("dps_studio.research.denoising_task005_benchmark")


def test_task005_auxiliary_benchmark_has_its_own_module() -> None:
    assert find_spec("dps_studio.research.denoising_task005_benchmark") is not None


def test_voltage_cases_are_deterministic_and_disjoint_from_old_registration() -> None:
    m = benchmark()
    rows = m.registration()
    assert len(rows) == 12
    assert len({r["case_id"] for r in rows}) == 12
    assert len({r["seed"] for r in rows}) == 12
    assert all(53051000 <= r["seed"] < 53052000 for r in rows)
    a = m.generate("persistent_competitor", 50580001)
    b = m.generate("persistent_competitor", 50580001)
    np.testing.assert_array_equal(a.record.voltage_v, b.record.voltage_v)
    assert len(a.record.time_s) == 32000
    assert a.record.sample_rate_hz == pytest.approx(40e9)
    assert a.record.voltage_v.std() > .2
    assert np.ptp(a.truth_frequency_hz) > 500e6


def test_absence_and_mixed_stft_windows_are_explicit() -> None:
    m = benchmark()
    case = m.generate("target_absence", 50580002)
    t = np.array([100e-9, 330e-9, 400e-9, 480e-9, 600e-9])
    labels = m.frame_truth(case, t, 768)
    assert labels["target_absent"].tolist() == [False, False, True, False, False]
    assert labels["mixed_window"].tolist() == [False, True, False, True, False]
    assert np.isnan(labels["truth_hz"][[1, 2, 3]]).all()
    assert np.isfinite(labels["truth_hz"][[0, 4]]).all()


def test_missing_outputs_are_not_counted_as_success_and_harms_are_separate() -> None:
    m = benchmark()
    truth = np.array([1., 1., 1., 1., 1., np.nan])
    baseline = np.array([1., 3., 1., 3., 1., 4.])
    output = np.array([3., 1., np.nan, np.nan, 1., 5.])
    result = m.score_path(output, truth, baseline=baseline, tolerance_hz=.2)
    assert result["present_frames"] == 5
    assert result["finite_present_frames"] == 3
    assert result["coverage"] == pytest.approx(.6)
    assert result["wrong_frames"] == 1
    assert result["missing_frames"] == 2
    assert result["failure_frames"] == 3
    assert result["failure_rate"] == pytest.approx(.6)
    assert result["corrected_frames"] == 1
    assert result["harmed_frames"] == 1
    assert result["abstained_previously_correct"] == 1
    assert result["finite_absent_frames"] == 1
    assert result["rmse_hz"] == pytest.approx(np.sqrt(4/3))


def test_mixed_windows_are_excluded_from_absence_counts_with_the_explicit_mask() -> None:
    m = benchmark()
    case = m.generate("target_absence", 50580002)
    t = np.array([100e-9, 330e-9, 400e-9, 480e-9, 600e-9])
    labels = m.frame_truth(case, t, 768)
    output = np.full(len(t), 1.7e9)
    score = m.score_path(output, labels["truth_hz"], absent_mask=labels["target_absent"])
    assert score["present_frames"] == 2
    assert score["finite_absent_frames"] == 1


@pytest.mark.parametrize("family", ["normal_chirp", "curved_competitor", "resolved_approach",
                                   "rapid_return"])
def test_registered_families_are_actual_finite_voltage_records(family: str) -> None:
    case = benchmark().generate(family, 50580003)
    assert np.isfinite(case.record.voltage_v).all()
    assert np.isfinite(case.record.time_s).all()
    assert case.seed_frequency_hz > 0
    assert case.seed_time_s == pytest.approx(100e-9)
