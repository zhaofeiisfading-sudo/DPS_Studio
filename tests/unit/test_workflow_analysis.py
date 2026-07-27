from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from dps_studio.core import (
    BALANCED_PROFILE,
    HIGH_TIME_RESOLUTION_PROFILE,
    EventCandidateConfig,
)
from dps_studio.core.models import SignalRecord
from dps_studio.core.ridge import RidgeQualityFlag, RidgeRefinementStatus
from dps_studio.core.workflow import (
    analyze_profile,
    derive_background_exclusion_half_width_hz,
)


SAMPLE_RATE_HZ = 40.0e9
START_TIME_S = 554.65e-6
EVENT_START_TIME_S = 554.668e-6
ANALYSIS_END_TIME_S = 554.69e-6


def _records(source_path: Path) -> dict[str, SignalRecord]:
    sample_count = 1536
    relative_time_s = np.arange(sample_count, dtype=np.float64) / SAMPLE_RATE_HZ
    time_s = START_TIME_S + relative_time_s
    return {
        name: SignalRecord(
            time_s,
            np.sin(2.0 * np.pi * frequency_hz * relative_time_s),
            source_path=source_path,
        )
        for name, frequency_hz in (
            ("pdv_channel_1", 0.63e9),
            ("pdv_channel_2", 0.66e9),
        )
    }


def _analyze(records: dict[str, SignalRecord], *, wavelength_m: float) -> object:
    return analyze_profile(
        records,
        profile=BALANCED_PROFILE,
        event_start_time_s=EVENT_START_TIME_S,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
        vacuum_wavelength_m=wavelength_m,
        background_guard_window_scale=2.0,
        minimum_background_bin_count=2,
    )


def test_nondefault_1064_nm_controls_discrete_and_refined_velocity(
    tmp_path: Path,
) -> None:
    wavelength_m = 1064e-9
    analyses = _analyze(_records(tmp_path / "source.csv"), wavelength_m=wavelength_m)
    for analysis in analyses.values():
        candidate = np.asarray(
            [
                flag is RidgeQualityFlag.CANDIDATE
                for flag in analysis.ridge_result.quality_flags
            ]
        )
        np.testing.assert_allclose(
            analysis.discrete_velocity_m_s[candidate],
            wavelength_m * analysis.ridge_result.frequency_hz[candidate] / 2.0,
            rtol=0.0,
            atol=0.0,
        )
        refined = np.asarray(
            [
                status is RidgeRefinementStatus.REFINED
                for status in analysis.refined_result.refinement_statuses
            ]
        )
        np.testing.assert_allclose(
            analysis.refined_velocity_m_s[refined],
            wavelength_m
            * analysis.refined_result.refined_frequency_hz[refined]
            / 2.0,
            rtol=0.0,
            atol=0.0,
        )
        assert analysis.discrete_velocity_result.vacuum_wavelength_m == wavelength_m
        assert np.array_equal(
            np.isnan(analysis.refined_velocity_m_s),
            ~refined,
        )


def test_channels_are_independent_and_profiles_are_not_fused(tmp_path: Path) -> None:
    records = _records(tmp_path / "source.csv")
    balanced_before = _analyze(records, wavelength_m=1064e-9)
    high = analyze_profile(
        records,
        profile=HIGH_TIME_RESOLUTION_PROFILE,
        event_start_time_s=EVENT_START_TIME_S,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
        vacuum_wavelength_m=1064e-9,
        background_guard_window_scale=2.0,
        minimum_background_bin_count=2,
    )
    balanced_after = _analyze(records, wavelength_m=1064e-9)
    np.testing.assert_array_equal(
        balanced_before["pdv_channel_1"].stft_result.spectrum,
        balanced_after["pdv_channel_1"].stft_result.spectrum,
    )
    assert high["pdv_channel_1"].stft_result.window_length_samples == 512
    assert balanced_after["pdv_channel_1"].stft_result.window_length_samples == 768
    assert not np.array_equal(
        balanced_after["pdv_channel_1"].refined_velocity_m_s,
        balanced_after["pdv_channel_2"].refined_velocity_m_s,
        equal_nan=True,
    )


def test_quality_guard_derivation_is_validated_and_exact() -> None:
    assert derive_background_exclusion_half_width_hz(
        sample_rate_hz=40.0e9,
        window_length_samples=768,
        window_scale=2.0,
    ) == pytest.approx(2.0 * 40.0e9 / 768)
    for kwargs in (
        {"sample_rate_hz": 0.0, "window_length_samples": 768, "window_scale": 2.0},
        {"sample_rate_hz": 40.0e9, "window_length_samples": 0, "window_scale": 2.0},
        {"sample_rate_hz": 40.0e9, "window_length_samples": 768, "window_scale": 0.0},
    ):
        with pytest.raises(ValueError):
            derive_background_exclusion_half_width_hz(**kwargs)


def test_core_workflow_has_no_script_or_matplotlib_dependency() -> None:
    workflow_directory = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "dps_studio"
        / "core"
        / "workflow"
    )
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in workflow_directory.glob("*.py")
    )
    assert "scripts." not in source
    assert "matplotlib" not in source


def test_event_candidate_config_changes_only_event_metadata(
    tmp_path: Path,
) -> None:
    records = _records(tmp_path / "source.csv")
    permissive = analyze_profile(
        records,
        profile=BALANCED_PROFILE,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
        vacuum_wavelength_m=1064e-9,
        event_candidate_config=EventCandidateConfig(
            minimum_segment_frames=1,
            minimum_segment_duration_s=0.0,
        ),
    )
    strict = analyze_profile(
        records,
        profile=BALANCED_PROFILE,
        analysis_end_time_s=ANALYSIS_END_TIME_S,
        vacuum_wavelength_m=1064e-9,
        event_candidate_config=EventCandidateConfig(
            minimum_segment_frames=100,
        ),
    )
    for channel_name in records:
        first = permissive[channel_name]
        second = strict[channel_name]
        assert (
            first.stream_event_candidates.primary_candidate_time_s
            != second.stream_event_candidates.primary_candidate_time_s
        )
        assert (
            first.signal_detection_result.signal_states
            == second.signal_detection_result.signal_states
        )
        for field_name in (
            "refined_frequency_hz",
            "apparent_velocity_m_s",
            "peak_to_background_db",
            "peak_to_competitor_db",
            "cycles_in_window",
        ):
            np.testing.assert_array_equal(
                getattr(first.signal_detection_result, field_name),
                getattr(second.signal_detection_result, field_name),
            )
        assert np.count_nonzero(np.isfinite(first.refined_velocity_m_s)) == (
            np.count_nonzero(np.isfinite(second.refined_velocity_m_s))
        )
