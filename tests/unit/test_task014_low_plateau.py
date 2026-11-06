from types import SimpleNamespace

import numpy as np
import pytest

from artifacts.research_clean_task13.repro import stage
from artifacts.research_clean_task13.repro.cases import VELOCITY, fresh
from artifacts.research_clean_task14.study import one_peak


def test_refinement_preserves_support_and_resolves_stationary_tone() -> None:
    case = fresh("low_plateau", 100)
    signal = case.signal
    before = signal.voltage_v.tobytes()
    matched = stage.local_estimate(signal, case.plan, "clip_stft2048")
    refined = one_peak(signal, case.plan)
    truth = case.truth_hz[stage.grid(signal)]
    common = np.isfinite(matched.accepted_hz) & np.isfinite(refined.accepted_hz)
    assert common.any()
    # Missing and rejected estimates stay in the output on the original grid.
    assert len(refined.accepted_hz) == len(truth)
    assert np.all(np.isnan(refined.accepted_hz[refined.r2 < .20]))
    assert np.mean(((refined.accepted_hz[common] - truth[common])*VELOCITY)**2) < np.mean(
        ((matched.accepted_hz[common] - truth[common])*VELOCITY)**2
    )
    assert signal.voltage_v.tobytes() == before



def test_failed_refinement_leaves_a_flagged_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    case = fresh("low_plateau", 100)
    monkeypatch.setattr("artifacts.research_clean_task14.study.minimize_scalar",
                        lambda *args, **kwargs: SimpleNamespace(success=False))
    trace = one_peak(case.signal, case.plan)
    assert np.isnan(trace.accepted_hz).all()
    assert np.all(trace.quality == "FIT_FAILED")
