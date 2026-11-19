"""Exact center alignment, band isolation and frozen-replay checks."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scripts.research.task023.common import Channel
from scripts.research.task023.methods import m4_phase_coherent
from scripts.research.task023.phase1_run import OUT, _centers, _run_channel
from scripts.research.task023.phase2_run import PHASE2_METHODS, _audit
from scripts.research.task023.phase3_pairs import (
    PairComparison, agreement_metrics, align_centers, pair_rows, raw_sample_lag,
)
from scripts.research.task023.phase3_run import (
    PHASE2B_OUTPUT, verify_archived_centers, wide_band_estimates,
)
from scripts.research.task023.waveform import FMAX


def test_exact_centers_are_independent_of_raw_lag() -> None:
    fs = 40e9
    samples = np.random.default_rng(114).normal(size=4096)
    delayed = 3.6*np.r_[np.zeros(7), samples[:-7]] + 1.2
    lag = raw_sample_lag(samples, delayed, fs)
    assert lag.samples == -7
    assert lag.seconds == -7/fs
    assert lag.correlation == pytest.approx(1.)
    a = np.array([1., 2., 3., 4.])*1e-6
    b = np.array([a[1], np.nextafter(a[2], np.inf), a[3]])
    time, i1, i2 = align_centers(a, b)
    np.testing.assert_array_equal(time, a[[1, 3]])
    np.testing.assert_array_equal(i1, [1, 3])
    np.testing.assert_array_equal(i2, [0, 2])
    with pytest.raises(ValueError, match="strictly increasing"):
        align_centers(a, np.array([a[1], a[1]]))


def test_pair_agreement_counts_thresholds_and_strata() -> None:
    a = np.array([100., 100., 100., 100., np.nan, 100., np.nan])*1e6
    b = np.array([130., 200., 350., 351., 100., np.nan, np.nan])*1e6
    assert agreement_metrics(a, b) == {
        "paired_centers": 7, "both_accepted_n": 4, "only_ch1_n": 1, "only_ch2_n": 1,
        "both_rejected_n": 1, "median_abs_diff_mhz": 175., "mean_abs_diff_mhz": 157.75,
        "agree_30mhz_frac": .25, "agree_100mhz_frac": .50, "disagree_250mhz_n": 1,
    }
    samples = np.random.default_rng(95).normal(size=256)
    pair = PairComparison(
        "test", np.arange(7, dtype=np.float64)*3.2e-9,
        np.array(["onset", "onset", "weak_signal", "weak_signal", "noise", "noise", "noise"]),
        np.array([True, False, False, True, False, False, False]),
        np.array([True, False, True, False, False, False, False]),
        dict.fromkeys(PHASE2_METHODS, a), dict.fromkeys(PHASE2_METHODS, b),
        raw_sample_lag(samples, samples, 40e9), 0, 0,
    )
    rows = {(row["visual_stage"], row["clipping"]): row for row in pair_rows(pair)
            if row["method"] == "M4"}
    assert rows["all", "clipped"]["paired_centers"] == 3
    assert rows["all", "unclipped"]["paired_centers"] == 4
    assert rows["weak_signal", "clipped"]["disagree_250mhz_n"] == 1
    assert rows["weak_signal", "unclipped"]["paired_centers"] == 0
    missing = rows["noise", "unclipped"]
    assert missing["both_accepted_n"] == 0
    assert missing["only_ch1_n"] == missing["only_ch2_n"] == missing["both_rejected_n"] == 1
    assert np.isnan(float(str(missing["agree_30mhz_frac"])))


def test_8ghz_diagnostic_does_not_change_primary_band() -> None:
    fs, hz = 40e9, 6.3e9
    t = np.arange(4096)/fs
    y = np.random.default_rng(15).normal(0., .001, len(t))
    y[1024:] += .09*np.cos(2*np.pi*hz*t[1024:])
    ch = Channel("outside-primary-band", t, y, fs)
    before = m4_phase_coherent(ch)
    wide, traces = wide_band_estimates(ch)
    assert wide.fmax == 8e9
    assert ch.fmax == FMAX == 6e9
    assert ch.quiet.frequency_hz[-1] <= FMAX < wide.quiet.frequency_hz[-1]
    settled = (ch.q >= 1792) & ch.primary
    for method in ("B1_8G", "M4_8G"):
        assert np.count_nonzero(abs(traces[method].accepted_hz[settled] - hz) < 30e6) >= 9
    after = m4_phase_coherent(ch)
    assert not np.any(before.accepted_hz > FMAX)
    np.testing.assert_array_equal(before.accepted_hz, after.accepted_hz)
    np.testing.assert_array_equal(before.candidate_hz, after.candidate_hz)


def test_default_replay_matches_both_frozen_center_csvs(tmp_path: Path) -> None:
    channel = "20201211m_ch1"
    timing: list[dict[str, object]] = []
    audit = _audit(_run_channel(channel, timing), timing)
    actual = tmp_path / "centers.csv"
    _centers(actual, audit.screen, audit.columns())
    phase1 = OUT / "tables" / f"phase1_centers_{channel}.csv"
    phase2b = PHASE2B_OUTPUT / "tables" / f"phase2_centers_{channel}.csv"
    assert verify_archived_centers(actual, phase1) > 0
    assert verify_archived_centers(actual, phase2b) > 0
    assert actual.read_bytes() == phase2b.read_bytes()
