"""Unit and guardrail tests for TASK-023A Research tracker."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

from dps_studio.core.ridge import GlobalPathConfig, RidgeCandidate, RidgeCandidateSet
from dps_studio.core.ridge.models import RidgeRefinementStatus
from dps_studio.research.task023a_imm_mht_tracker import (
    QualityFlag,
    TrackerConfig,
    combine_imm_state,
    imm_predict,
    imm_update,
    initialize_imm,
    track_candidates,
)


def _candidate(frame: int, time_s: float, rank: int, frequency_hz: float) -> RidgeCandidate:
    return RidgeCandidate(
        frame_index=frame,
        time_s=time_s,
        candidate_rank=rank,
        discrete_bin_index=rank + 2,
        discrete_frequency_hz=frequency_hz,
        refined_frequency_hz=frequency_hz,
        peak_amplitude=10.0 / rank,
        peak_to_background_db=14.0 - rank,
        peak_to_competitor_db=4.0 - rank,
        cycles_in_window=3.0,
        is_band_boundary=False,
        refinement_status=RidgeRefinementStatus.REFINED,
    )


def _set(
    paths: list[list[float]], *, dt: float = 2.5e-9, empty_frames: set[int] | None = None
) -> RidgeCandidateSet:
    count = len(paths[0])
    times = np.arange(count, dtype=np.float64) * dt
    empty = set() if empty_frames is None else empty_frames
    frames = tuple(
        tuple(
            _candidate(frame, float(times[frame]), rank + 1, path[frame])
            for rank, path in enumerate(paths)
        )
        if frame not in empty
        else tuple()
        for frame in range(count)
    )
    return RidgeCandidateSet(
        time_s=times,
        candidates_by_frame=frames,
        minimum_frequency_hz=0.05e9,
        maximum_frequency_hz=6.0e9,
        effective_candidate_separation_hz=50.0e6,
        effective_background_exclusion_half_width_hz=50.0e6,
        config=GlobalPathConfig(top_k=len(paths)),
        source_path=Path("synthetic.csv"),
    )


def test_imm_prediction_and_update_correctness() -> None:
    config = TrackerConfig()
    state = initialize_imm(1.0e9, config)
    predicted = imm_predict(state, 2.5e-9, config)
    prior_error = abs(combine_imm_state(predicted)[0][0] - 1.1e9)
    updated, evidence = imm_update(predicted, 1.1e9, config)
    posterior_error = abs(combine_imm_state(updated)[0][0] - 1.1e9)
    assert posterior_error < prior_error
    assert math.isclose(evidence.innovation_hz, 1.0e8, abs_tol=1.0e-6)
    assert np.all(np.linalg.eigvalsh(updated.covariances) >= -1.0e-6)


def test_mode_probability_normalization() -> None:
    config = TrackerConfig()
    state = initialize_imm(2.0e9, config)
    for measurement in (2.0e9, 2.05e9, 1.9e9):
        state = imm_predict(state, 2.5e-9, config)
        state, _ = imm_update(state, measurement, config)
        assert math.isclose(float(np.sum(state.probabilities)), 1.0, abs_tol=1.0e-12)


def test_constant_rate_synthetic_recovery() -> None:
    truth = (1.0e9 + np.arange(60) * 18.0e6).tolist()
    distractor = np.full(60, 2.8e9).tolist()
    result = track_candidates(_set([truth, distractor]), beam_width=8)
    rmse = float(np.sqrt(np.mean(np.square(result.frequency_hz - truth))))
    assert rmse < 80.0e6


def test_fast_descent_recovery() -> None:
    truth = np.concatenate((np.full(20, 3.8e9), 3.8e9 - np.arange(50) * 75.0e6))
    wrong = np.full(truth.size, 3.8e9)
    result = track_candidates(_set([truth.tolist(), wrong.tolist()]), beam_width=8)
    assert np.mean(np.abs(result.frequency_hz[-20:] - truth[-20:]) < 200.0e6) >= 0.8


def test_mht_beam_is_deterministic_and_width_one_is_single_hypothesis() -> None:
    first = np.full(50, 1.5e9)
    second = np.concatenate((np.full(25, 2.4e9), np.linspace(2.4e9, 0.8e9, 25)))
    candidate_set = _set([first.tolist(), second.tolist()])
    one_a = track_candidates(candidate_set, beam_width=1)
    one_b = track_candidates(candidate_set, beam_width=1)
    eight_a = track_candidates(candidate_set, beam_width=8)
    eight_b = track_candidates(candidate_set, beam_width=8)
    assert np.array_equal(one_a.frequency_hz, one_b.frequency_hz)
    assert np.array_equal(eight_a.selected_rank, eight_b.selected_rank)


def test_selected_frequency_is_candidate_or_explicit_prediction_and_no_nan() -> None:
    truth = np.full(30, 1.2e9)
    candidate_set = _set([truth.tolist()], empty_frames={10, 11, 12})
    result = track_candidates(candidate_set, beam_width=4)
    assert np.all(np.isfinite(result.frequency_hz))
    for index, step in enumerate(result.steps):
        if candidate_set.candidates_by_frame[index]:
            available = {
                candidate.transition_frequency_hz
                for candidate in candidate_set.candidates_by_frame[index]
            }
            assert step.frequency_hz in available
            assert QualityFlag.CANDIDATE_UPDATE in step.quality_flags
        else:
            assert QualityFlag.PREDICTED_GAP in step.quality_flags


def test_quality_flag_does_not_alter_trajectory() -> None:
    truth = np.full(20, 1.4e9)
    candidate_set = _set([truth.tolist()])
    normal = track_candidates(candidate_set, config=TrackerConfig(), beam_width=1)
    flagged = track_candidates(
        candidate_set,
        config=TrackerConfig(low_confidence_threshold=0.99),
        beam_width=1,
    )
    assert np.array_equal(normal.frequency_hz, flagged.frequency_hz)
    assert any(QualityFlag.LOW_CONFIDENCE in step.quality_flags for step in flagged.steps)


def test_fixed_upstream_and_raw_guardrails() -> None:
    root = Path(__file__).resolve().parents[2]
    protected = (
        root / "src/dps_studio/core/time_frequency/stft.py",
        root / "src/dps_studio/core/ridge/candidates.py",
        root / "src/dps_studio/core/ridge/global_path.py",
    )
    expected = {
        "stft.py": "45B693D4153B0EF563D3F15976566CEE77E6E3E014C6A342A39E43A1588E1323",
        "candidates.py": "3CA811265A909DFD18776603DB664DE14B35FCCA61062FCFF2FC9D96D6A97CFB",
        "global_path.py": "D9D3E827CC42B312C21AD6FBF7D8354264948DA2F268D149D08CBC81DC440566",
    }
    observed = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest().upper() for path in protected
    }
    # If a historical upstream file changes intentionally, this assertion forces review.
    assert observed == expected
    raw = root / "data/raw"
    assert all(path.is_file() for path in raw.rglob("*") if path.suffix)
