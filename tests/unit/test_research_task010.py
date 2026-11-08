"""Independent contracts for STFT attribution, missingness, and boundaries."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from dps_studio.algorithms.waveform.common import Signal, event_detector, projection
from scripts.research.task010.experiment import (
    Spec,
    adaptive,
    common_centers,
    estimate,
    metric,
    support,
)
from scripts.research.task010.run import select
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import extract_peak_ridge, refine_peak_ridge_subbin
from dps_studio.core.time_frequency import compute_stft


@pytest.fixture
def signal() -> Signal:
    rng = np.random.default_rng(1010)
    time = np.arange(4096) / 40e9
    phase = 2 * np.pi * (450e6 * time + .5 * 1e16 * time**2)
    voltage = .04 * np.cos(phase) + .003 * rng.normal(size=len(time)) + .008
    return Signal(time, voltage)


@pytest.mark.parametrize("width,hop,nfft", [(512, 128, 4096), (768, 32, 4096),
    (1024, 16, 2048), (1536, 8, 4096), (2048, 1, 8192)])
def test_chunked_estimates_match_unchanged_core(signal: Signal, width: int,
                                               hop: int, nfft: int) -> None:
    before = signal.voltage_v.tobytes()
    result = estimate(signal, Spec(width, hop, nfft), batch_frames=37)
    stft = compute_stft(SignalRecord(signal.time_s, signal.voltage_v),
        window_length_samples=width, overlap_samples=width-hop, nfft=nfft)
    ridge = extract_peak_ridge(stft, minimum_frequency_hz=50e6, maximum_frequency_hz=6e9)
    refined = refine_peak_ridge_subbin(stft, ridge)
    np.testing.assert_array_equal(result.discrete_hz, ridge.frequency_hz)
    np.testing.assert_allclose(result.frequency_hz, refined.refined_frequency_hz,
                               rtol=1e-12, atol=1e-3, equal_nan=True)
    np.testing.assert_allclose(signal.time_s[result.indices], stft.time_s, atol=1e-20)
    assert before == signal.voltage_v.tobytes()


@pytest.mark.parametrize("width", [512, 768, 1024, 1536, 2048])
def test_hop_only_samples_the_identical_estimator(signal: Signal, width: int) -> None:
    dense = estimate(signal, Spec(width, 1))
    grid = common_centers(len(signal.time_s))
    for hop in (128, 64, 32, 16, 8):
        direct = estimate(signal, Spec(width, hop))
        view = select(dense, hop)
        np.testing.assert_allclose(direct.frequency_hz, view.frequency_hz,
                                   rtol=1e-12, atol=1e-3, equal_nan=True)
        np.testing.assert_array_equal(view.indices[np.searchsorted(view.indices, grid)], grid)


def test_missing_estimates_remain_in_failure_denominator() -> None:
    row = metric(np.array([1e9, np.nan, 2e9]), np.array([1e9, 1e9, 1e9]),
                 np.ones(3, dtype=bool), "")
    assert row["target_n"] == 3
    assert row["finite_n"] == 2
    assert row["failure_n"] == 2
    assert row["failure_fraction"] == pytest.approx(2 / 3)


def test_equal_validation_support_matches_direct_projection(signal: Signal) -> None:
    centers = np.array([512, 1024, 1536], dtype=np.int64)
    frequencies = np.array([500e6, 700e6, 900e6])
    r2, conditions = support(signal, centers, frequencies, 1000)
    for i, center in enumerate(centers):
        left = max(int(center) - 128, 1000 if center >= 1000 else 0)
        right = int(center) + 128
        y = signal.voltage_v[left:right]
        phase = 2 * np.pi * frequencies[i] * (np.arange(left, right) - center) / signal.fs
        _, residual, condition = projection(y, phase)
        expected = 1 - float(residual @ residual) / float(np.sum((y-y.mean())**2))
        assert r2[i] == pytest.approx(expected, abs=1e-10)
        assert conditions[i] == pytest.approx(condition, rel=1e-8)


def test_boundary_failure_does_not_become_discrete_fallback() -> None:
    time = np.arange(4096) / 40e9
    result = estimate(Signal(time, .1 + 1e-4 * np.cos(2*np.pi*900e6*time)), Spec(512, 128))
    assert np.isfinite(result.discrete_hz).all()
    assert np.isnan(result.frequency_hz).all()
    assert np.isnan(result.accepted_hz).all()


def test_adaptive_selection_copies_an_existing_value_without_blending(signal: Signal) -> None:
    onset, _ = event_detector(signal)
    short = estimate(signal, Spec(512, 32, minimum_hz=5e6, maximum_hz=8e9, demean=True))
    long = estimate(signal, Spec(2048, 32, minimum_hz=5e6, maximum_hz=8e9, demean=True))
    result = adaptive(short, long, signal, onset)
    si = np.searchsorted(short.indices, result.indices)
    li = np.searchsorted(long.indices, result.indices)
    use_short = np.char.startswith(result.flags, "SELECT_W512")
    expected = np.where(use_short, short.frequency_hz[si], long.frequency_hz[li])
    np.testing.assert_array_equal(result.frequency_hz, expected)


def test_declared_protocol_has_full_parameter_matrix_and_no_promotion() -> None:
    root = Path(__file__).resolve().parents[2]
    config = json.loads((root / "configs/research/task010.json").read_text())
    assert config["windows"] == [512, 768, 1024, 1536, 2048]
    assert config["hops"] == [128, 64, 32, 16, 8, 1]
    assert config["production_defaults_changed"] is False


def test_cloud_copy_preserves_a_different_version(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.research.task010 import sync_cloud
    local=tmp_path/"local"
    local.mkdir()
    (local/"COMPARISON.md").write_text("new research",encoding="utf-8")
    (local/"README.md").write_text("new readme",encoding="utf-8")
    cloud=tmp_path/"cloud"
    cloud.mkdir()
    (cloud/"README.md").write_text("older version",encoding="utf-8")
    monkeypatch.setattr(sync_cloud,"OUT",local)
    result=sync_cloud.copy_package([local/"README.md",local/"COMPARISON.md"],cloud)
    assert (cloud/"README.md").read_text(encoding="utf-8")=="older version"
    assert Path(result["destination"]).is_relative_to(cloud/"versions")
    assert result["all_sha_readbacks_match"]
    assert (local/"README.md").read_text(encoding="utf-8")=="new readme"


def test_cloud_copy_keeps_identical_file(tmp_path: Path,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.research.task010 import sync_cloud
    local=tmp_path/"local"
    local.mkdir()
    cloud=tmp_path/"cloud"
    cloud.mkdir()
    for folder in (local,cloud):
        (folder/"README.md").write_text("same bytes",encoding="utf-8")
    before=(cloud/"README.md").stat().st_mtime_ns
    monkeypatch.setattr(sync_cloud,"OUT",local)
    result=sync_cloud.copy_package([local/"README.md"],cloud)
    assert result["records"][0]["action"]=="IDENTICAL_KEPT"
    assert (cloud/"README.md").stat().st_mtime_ns==before


def test_cloud_copy_rejects_source_outside_research(tmp_path: Path,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.research.task010 import sync_cloud
    local=tmp_path/"local"
    local.mkdir()
    source=tmp_path/"outside.md"
    source.write_text("must not copy",encoding="utf-8")
    monkeypatch.setattr(sync_cloud,"OUT",local)
    with pytest.raises(ValueError):
        sync_cloud.copy_package([source],tmp_path/"cloud")
