"""Replay archived TASK-028 evidence without rewriting it or running the full benchmark."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.models import SignalRecord
from dps_studio.research import task028_benchmark as benchmark
from dps_studio.research import task028_consolidation as method
from dps_studio.research.task023e_waveform_benchmark import PROFILES, array_hash

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "artifacts/task028_candidate_method_consolidation/20260929T154018Z"
CASE = "T28_C_short_switch_00"


def test_portable_final_config_matches_literal_defaults() -> None:
    saved = json.loads((ROOT / "configs/research/task028_final_method.json").read_text())
    assert method.FinalMethodConfig.from_dict(saved).to_dict() == saved
    assert saved == method.FinalMethodConfig().to_dict()
    assert Path(method.__file__).resolve().is_relative_to(ROOT / "src")


@pytest.mark.parametrize("profile_index", [0, 1])
def test_saved_intervention_replays_exactly(profile_index: int) -> None:
    if not ARCHIVE.is_dir():
        pytest.skip("Requires the retained TASK-028 artifact archive")
    profile = PROFILES[profile_index]
    config = method.FinalMethodConfig.from_dict(json.loads(
        (ROOT / "configs/research/task028_final_method.json").read_text()
    ))
    assert config.to_dict() == json.loads((ARCHIVE / "final_method_config.json").read_text())
    generated = benchmark.generate("C_short_switch", 0)
    with np.load(ARCHIVE / "waveforms" / f"{CASE}.npz") as raw:
        np.testing.assert_array_equal(generated.record.time_s, raw["time_s"])
        np.testing.assert_array_equal(generated.record.voltage_v, raw["voltage_v"])
        record = SignalRecord(raw["time_s"].copy(), raw["voltage_v"].copy())
    original_hash = array_hash(record.voltage_v)
    assert original_hash == json.loads(
        (ARCHIVE / "literal_reproduction.json").read_text()
    )["voltage_sha256"]
    stft, peaks = method.frontend(record, profile)
    result = method.consolidate(stft, peaks, config)
    expected_path = ARCHIVE / "streams" / f"{CASE}__{profile.profile_id.value}.npz"
    with np.load(expected_path) as expected:
        np.testing.assert_array_equal(result.time_s, expected["time_s"])
        np.testing.assert_array_equal(result.ambiguity, expected["ambiguity"])
        strongest = [frame[0].transition_frequency_hz for frame in peaks.candidates_by_frame]
        np.testing.assert_array_equal(result.trajectories["M0"].frequency_hz, strongest)
        for name, trajectory in result.trajectories.items():
            np.testing.assert_array_equal(trajectory.frequency_hz, expected[name])
            np.testing.assert_array_equal(trajectory.candidate_rank, expected[name + "_rank"])
            np.testing.assert_array_equal(trajectory.quality_flags, expected[name + "_quality"])
            np.testing.assert_array_equal(
                trajectory.apparent_velocity_m_per_s, expected[name + "_velocity_m_per_s"]
            )
            assert np.isfinite(trajectory.frequency_hz).mean() == 1.0
            assert np.isnan(trajectory.validated_frequency_hz).all()
            assert np.isnan(trajectory.validated_apparent_velocity_m_per_s).all()
            assert all("HYPOTHESIS_UNCALIBRATED" in q for q in trajectory.quality_flags)
            for i, frame in enumerate(peaks.candidates_by_frame):
                candidate = next(c for c in frame if c.candidate_rank == trajectory.candidate_rank[i])
                assert trajectory.frequency_hz[i] == candidate.transition_frequency_hz
        assert result.trajectories["M2"].modified.any()
    assert array_hash(record.voltage_v) == original_hash
