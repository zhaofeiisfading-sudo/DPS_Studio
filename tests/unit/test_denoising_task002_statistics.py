"""Waveforms, rather than overlapping STFT frames, are the bootstrap units."""
from __future__ import annotations

import numpy as np
import pandas as pd  # type: ignore[import-untyped]
import pytest

from report_denoising_task002 import aggregate, paired_bootstrap
from dps_studio.research import denoising_task002 as bench


def _paired_table() -> pd.DataFrame:
    rows = []
    for case_id in ("a", "b", "absent"):
        for profile, error in (("balanced", 300e6), ("high_time", 600e6)):
            truth = np.array([np.nan if case_id == "absent" else 2e9])
            labels = dict(truth=truth, normal=np.array([True]), fast=np.array([False]),
                          focus=np.array([False]))
            old = np.array([2e9+error])
            for name in ("M0", "M1", "M2", "DIAG_NO_AMP"):
                path = old if name in ("M0", "M1") else np.array([2e9])
                rows.append(dict(case_id=case_id, profile=profile, method=name, reference="M1",
                    **bench.metrics(path, old, labels), candidate_recalled=int(np.isfinite(truth[0])),
                    strongest_correct=0))
    return pd.DataFrame(rows)


def test_bootstrap_groups_two_profiles_and_excludes_absent_frequency_truth() -> None:
    rows = paired_bootstrap(_paired_table())
    row = next(r for r in rows if r["comparison"] == "M2-M1" and r["metric"] == "rmse_hz")
    assert row["waveforms"] == 2
    expected = -np.sqrt((300e6**2+600e6**2)/2)
    assert row["mean_difference"] == pytest.approx(expected)
    assert row["ci_low"] == pytest.approx(expected)
    assert row["ci_high"] == pytest.approx(expected)
    assert row["improved"] == 2


def test_macro_rmse_combines_sse_before_profile_average() -> None:
    table = _paired_table()
    result = aggregate(table[table.method == "M1"])
    assert result["waveforms"] == 3
    assert result["truth_waveforms"] == 2
    expected = np.sqrt((300e6**2+600e6**2)/2)
    assert result["macro_rmse_hz"] == pytest.approx(expected)
    assert result["candidate_recall"] == 1
