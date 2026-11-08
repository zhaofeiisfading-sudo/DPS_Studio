"""Historical strongest M0 must preserve its explicit discrete fallback."""
from __future__ import annotations

import importlib

import numpy as np
import pytest

from dps_studio.research.waveform import common


@pytest.mark.parametrize("window", [512, 768])
def test_historical_m0_retains_boundary_candidate_without_mutating_raw(window: int) -> None:
    t = np.arange(4096)/40e9
    x = .1+1e-4*np.cos(2*np.pi*900e6*t+.2)
    signal = common.Signal(np.asarray(t), np.asarray(x))
    before = signal.voltage_v.tobytes()
    context = common.Context(signal)
    result = importlib.import_module(
        f"dps_studio.algorithms.waveform.legacy_m0_{window}.implementation").run(context)
    assert signal.voltage_v.tobytes() == before
    assert np.isfinite(result.frequency_hz).all()
    assert np.isnan(result.extra["strict_refined_hz"]).all()
    np.testing.assert_array_equal(result.frequency_hz, result.extra["discrete_hz"])
    assert np.isnan(result.accepted_hz).all()
