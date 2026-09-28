"""Tests of feasibility decisions, not claims of recovered physical branches."""

import numpy as np
import pytest

from dps_studio.research import task023d_smooth_branch_rescue as old
from dps_studio.research.task023e_proposal_audit import (
    audit_frames, collect_beams, feasibility_gate, terminal_beam,
)
from scripts import run_task023d_smooth_branch_rescue as runner


def test_majority_stop_is_strict_and_zero_denominator_is_safe():
    def rows(n, blocked):
        return [{"candidate_correctable": True, "proposal_blocked": i < blocked}
                for i in range(n)]
    assert not feasibility_gate([])["stop_scorer"]
    assert not feasibility_gate(rows(4, 2))["stop_scorer"]
    assert feasibility_gate(rows(4, 3))["stop_scorer"]


def test_beam_width_cannot_be_tuned():
    with pytest.raises(ValueError, match="eight"):
        terminal_beam((), 0, 0, None, None, None, old.BranchCompetitionConfig(beam_width=9),
                      np.array([]))


def test_exposed_beam_equals_existing_search_and_preserves_provenance():
    case = runner._smooth_case("test_audit_edge", "trailing_smooth")
    candidates = runner._candidate_set(case)
    snapshot = candidates.candidates_by_frame
    config = old.BranchCompetitionConfig()
    result = runner._optimize(candidates, old.SmoothBranchMethod.E3_CORE_TRIM_BRANCH,
                              old.CoreTrimConfig(), config, case.stft)
    strongest = result.strongest.frequency_hz.copy()
    beams = collect_beams(result, candidates, runner.AMBIGUITY_CONFIG, config, case.stft)
    assert beams
    for beam in beams:
        assert 1 <= len(beam.states) <= 8
        for state in beam.states:
            for frame, frequency in zip(beam.indices, state.frequencies_hz, strict=True):
                assert frequency in [c.transition_frequency_hz
                                     for c in candidates.candidates_by_frame[frame]]
    rows = audit_frames(case.case_id, candidates, case.truth_hz, result, beams)
    assert len(rows) == len(case.truth_hz)
    assert candidates.candidates_by_frame == snapshot
    np.testing.assert_array_equal(result.strongest.frequency_hz, strongest)
    for row in rows:
        assert row["oracle_error_hz"] <= abs(row["task023c_hz"] - row["truth_hz"])


def test_no_truth_does_not_count_as_correctable_error():
    case = runner._smooth_case("test_audit_no_truth", "correct_smooth")
    candidates = runner._candidate_set(case)
    result = runner._optimize(candidates, old.SmoothBranchMethod.E3_CORE_TRIM_BRANCH,
                              old.CoreTrimConfig(), old.BranchCompetitionConfig(), case.stft)
    rows = audit_frames(case.case_id, candidates, np.full(len(case.truth_hz), np.nan),
                        result, ())
    assert not any(row["truth_valid"] or row["candidate_correctable"] for row in rows)
    assert not feasibility_gate(rows)["stop_scorer"]
