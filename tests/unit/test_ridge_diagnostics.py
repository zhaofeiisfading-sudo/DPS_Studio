from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.ridge import (
    RefinedRidgeResult,
    RelatedFrequencyEvidenceResult,
    RelatedFrequencyEvidenceStatus,
    RidgeConfigurationError,
    RidgeContinuityResult,
    RidgeContinuityStatus,
    RidgeQualityFlag,
    RidgeRefinementStatus,
    RidgeSpectralQualityResult,
    assess_related_frequency_evidence,
    assess_ridge_continuity,
    assess_ridge_spectral_quality,
)
from dps_studio.core.time_frequency import STFTResult


FREQUENCY_AXIS_HZ = np.arange(0.0, 110.0, 10.0)
SOURCE_PATH = Path("relative") / "signal.csv"


def _refined_result(
    refined_frequency_hz: np.ndarray,
    *,
    time_s: np.ndarray | None = None,
    event_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    failed_frames: dict[int, RidgeRefinementStatus] | None = None,
    source_path: Path | None = SOURCE_PATH,
) -> RefinedRidgeResult:
    refined_values = np.asarray(refined_frequency_hz, dtype=np.float64)
    if time_s is None:
        time_s = np.arange(refined_values.size, dtype=np.float64)
    failed_frames = failed_frames or {}
    discrete = np.full(refined_values.size, np.nan)
    stored_refined = np.full(refined_values.size, np.nan)
    bins = np.full(refined_values.size, -1, dtype=np.int64)
    offsets = np.full(refined_values.size, np.nan)
    magnitudes = np.full(refined_values.size, np.nan)
    quality_flags: list[RidgeQualityFlag] = []
    refinement_statuses: list[RidgeRefinementStatus] = []

    for index, (time_value, requested_refined) in enumerate(
        zip(time_s, refined_values)
    ):
        if event_start_time_s is not None and time_value < event_start_time_s:
            quality_flags.append(RidgeQualityFlag.PRE_EVENT)
            refinement_statuses.append(RidgeRefinementStatus.PRE_EVENT)
            continue
        if analysis_end_time_s is not None and time_value > analysis_end_time_s:
            quality_flags.append(RidgeQualityFlag.OUTSIDE_ANALYSIS_WINDOW)
            refinement_statuses.append(
                RidgeRefinementStatus.OUTSIDE_ANALYSIS_WINDOW
            )
            continue

        quality_flags.append(RidgeQualityFlag.CANDIDATE)
        status = failed_frames.get(index, RidgeRefinementStatus.REFINED)
        refinement_statuses.append(status)
        reference_hz = requested_refined if np.isfinite(requested_refined) else 40.0
        bin_index = int(np.clip(np.rint(reference_hz / 10.0), 1, 9))
        bins[index] = bin_index
        discrete[index] = FREQUENCY_AXIS_HZ[bin_index]
        magnitudes[index] = 20.0
        if status is RidgeRefinementStatus.REFINED:
            stored_refined[index] = requested_refined
            offsets[index] = (requested_refined - discrete[index]) / 10.0

    return RefinedRidgeResult(
        time_s=time_s,
        discrete_frequency_hz=discrete,
        refined_frequency_hz=stored_refined,
        discrete_frequency_bin_index=bins,
        frequency_bin_offset=offsets,
        peak_magnitude=magnitudes,
        quality_flags=tuple(quality_flags),
        refinement_statuses=tuple(refinement_statuses),
        minimum_frequency_hz=10.0,
        maximum_frequency_hz=90.0,
        event_start_time_s=event_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        refinement_method=RefinedRidgeResult.REFINEMENT_METHOD,
        source_path=source_path,
    )


def _related_inputs(
    *,
    refined_frequency_hz: float = 40.0,
    time_s: np.ndarray | None = None,
    event_start_time_s: float | None = None,
    analysis_end_time_s: float | None = None,
    failed_frames: dict[int, RidgeRefinementStatus] | None = None,
    source_path: Path | None = SOURCE_PATH,
) -> tuple[STFTResult, RefinedRidgeResult, RidgeSpectralQualityResult]:
    if time_s is None:
        time_s = np.array([0.0])
    refined = _refined_result(
        np.full(time_s.size, refined_frequency_hz),
        time_s=time_s,
        event_start_time_s=event_start_time_s,
        analysis_end_time_s=analysis_end_time_s,
        failed_frames=failed_frames,
        source_path=source_path,
    )
    spectrum = np.ones((FREQUENCY_AXIS_HZ.size, time_s.size), dtype=np.complex128)
    for frame_index, flag in enumerate(refined.quality_flags):
        if flag is RidgeQualityFlag.CANDIDATE:
            main_bin = int(refined.discrete_frequency_bin_index[frame_index])
            spectrum[main_bin, frame_index] = 20.0
            spectrum[2, frame_index] = 2.0
            spectrum[8, frame_index] = 4.0
    stft = STFTResult(
        time_s=time_s,
        frequency_hz=FREQUENCY_AXIS_HZ,
        spectrum=spectrum,
        window_name="hann",
        window_length_samples=20,
        overlap_samples=10,
        hop_samples=10,
        nfft=20,
        sample_rate_hz=200.0,
        source_path=source_path,
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )
    quality = assess_ridge_spectral_quality(
        stft,
        refined,
        background_exclusion_half_width_hz=1.0,
        minimum_background_bin_count=1,
    )
    return stft, refined, quality


def _assess_related(
    stft: STFTResult,
    refined: RefinedRidgeResult,
    quality: RidgeSpectralQualityResult,
    *,
    search_half_width_hz: float = 1.0,
) -> RelatedFrequencyEvidenceResult:
    return assess_related_frequency_evidence(
        stft,
        refined,
        quality,
        search_half_width_hz=search_half_width_hz,
    )


def _assert_all_nan_at(result: object, names: tuple[str, ...], indices: list[int]) -> None:
    for name in names:
        assert np.isnan(getattr(result, name)[indices]).all()


def _assert_bytes_backed_immutable(array: np.ndarray) -> None:
    current: object = array
    visited_ids: set[int] = set()
    while isinstance(current, np.ndarray):
        assert id(current) not in visited_ids
        visited_ids.add(id(current))
        assert current.flags.writeable is False
        with pytest.raises(ValueError, match="WRITEABLE"):
            current.setflags(write=True)
        with pytest.raises(ValueError, match="read-only"):
            current.flat[0] = -999
        current = current.base
    assert isinstance(current, bytes)
    assert memoryview(current).readonly is True


def test_continuity_linear_frequency_sequence_has_exact_differences() -> None:
    refined = _refined_result(np.array([10.0, 20.0, 30.0, 40.0]))

    result = assess_ridge_continuity(refined)

    np.testing.assert_allclose(result.frequency_step_hz[1:], 10.0)
    np.testing.assert_allclose(result.absolute_frequency_step_hz[1:], 10.0)
    np.testing.assert_allclose(result.frequency_slope_hz_s[1:], 10.0)
    np.testing.assert_allclose(result.frequency_second_difference_hz[2:], 0.0)
    assert result.continuity_statuses == (
        RidgeContinuityStatus.NO_PREVIOUS_CANDIDATE,
        RidgeContinuityStatus.NO_TWO_PREVIOUS_CANDIDATES,
        RidgeContinuityStatus.ASSESSED,
        RidgeContinuityStatus.ASSESSED,
    )


def test_continuity_quadratic_sequence_has_exact_second_difference() -> None:
    refined = _refined_result(np.array([10.0, 20.0, 40.0, 70.0]))

    result = assess_ridge_continuity(refined)

    np.testing.assert_allclose(result.frequency_second_difference_hz[2:], 10.0)


def test_continuity_uses_actual_nonuniform_frame_interval() -> None:
    refined = _refined_result(
        np.array([20.0, 30.0, 50.0]),
        time_s=np.array([0.0, 0.5, 2.5]),
    )

    result = assess_ridge_continuity(refined)

    np.testing.assert_allclose(result.frame_interval_s[1:], [0.5, 2.0])
    np.testing.assert_allclose(result.frequency_slope_hz_s[1:], [20.0, 10.0])


def test_continuity_pre_event_and_outside_frames_are_fully_masked() -> None:
    refined = _refined_result(
        np.array([30.0, 40.0, 50.0]),
        event_start_time_s=1.0,
        analysis_end_time_s=1.0,
    )

    result = assess_ridge_continuity(refined)

    assert result.continuity_statuses == (
        RidgeContinuityStatus.PRE_EVENT,
        RidgeContinuityStatus.NO_PREVIOUS_CANDIDATE,
        RidgeContinuityStatus.OUTSIDE_ANALYSIS_WINDOW,
    )
    _assert_all_nan_at(
        result,
        (
            "refined_frequency_hz",
            "previous_refined_frequency_hz",
            "frame_interval_s",
            "frequency_step_hz",
            "absolute_frequency_step_hz",
            "frequency_slope_hz_s",
            "frequency_second_difference_hz",
        ),
        [0, 2],
    )


def test_continuity_does_not_cross_refinement_failure() -> None:
    refined = _refined_result(
        np.array([20.0, np.nan, 40.0, 50.0, 60.0]),
        failed_frames={1: RidgeRefinementStatus.BOUNDARY_PEAK},
    )

    result = assess_ridge_continuity(refined)

    assert result.continuity_statuses == (
        RidgeContinuityStatus.NO_PREVIOUS_CANDIDATE,
        RidgeContinuityStatus.REFINEMENT_UNAVAILABLE,
        RidgeContinuityStatus.NO_PREVIOUS_CANDIDATE,
        RidgeContinuityStatus.NO_TWO_PREVIOUS_CANDIDATES,
        RidgeContinuityStatus.ASSESSED,
    )
    assert np.isnan(result.frequency_step_hz[:3]).all()
    assert result.frequency_step_hz[3] == 10.0


def test_continuity_rejects_nonincreasing_time_axis() -> None:
    refined = _refined_result(np.array([20.0, 30.0]))
    object.__setattr__(refined, "time_s", np.array([0.0, 0.0]))

    with pytest.raises(RidgeConfigurationError, match="strictly increasing"):
        assess_ridge_continuity(refined)


def test_continuity_rejects_mismatched_input_array_length() -> None:
    refined = _refined_result(np.array([20.0, 30.0]))
    object.__setattr__(refined, "refined_frequency_hz", np.array([20.0]))

    with pytest.raises(RidgeConfigurationError, match="match time_s"):
        assess_ridge_continuity(refined)


def test_continuity_preserves_relative_source_path_and_metadata() -> None:
    refined = _refined_result(np.array([20.0, 30.0]))

    result = assess_ridge_continuity(refined)

    assert result.source_path == SOURCE_PATH
    assert result.source_path is not None and not result.source_path.is_absolute()
    assert result.minimum_frequency_hz == 10.0
    assert result.maximum_frequency_hz == 90.0
    assert result.continuity_method == RidgeContinuityResult.CONTINUITY_METHOD


def test_known_double_and_half_frequency_evidence_is_recovered_exactly() -> None:
    stft, refined, quality = _related_inputs()

    result = _assess_related(stft, refined, quality)

    assert result.double_frequency_target_hz[0] == 80.0
    assert result.double_frequency_peak_hz[0] == 80.0
    assert result.double_frequency_peak_magnitude[0] == 4.0
    assert result.main_to_double_frequency_db[0] == pytest.approx(
        20.0 * np.log10(20.0 / 4.0)
    )
    assert result.half_frequency_target_hz[0] == 20.0
    assert result.half_frequency_peak_hz[0] == 20.0
    assert result.half_frequency_peak_magnitude[0] == 2.0
    assert result.main_to_half_frequency_db[0] == pytest.approx(20.0)
    assert result.double_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.ASSESSED,
    )
    assert result.half_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.ASSESSED,
    )


def test_related_search_uses_only_explicit_local_band() -> None:
    stft, refined, quality = _related_inputs()
    corrupted = stft.spectrum.copy()
    corrupted[7, 0] = 1000.0
    object.__setattr__(stft, "spectrum", corrupted)

    result = _assess_related(
        stft,
        refined,
        quality,
        search_half_width_hz=4.0,
    )

    assert result.double_frequency_peak_hz[0] == 80.0
    assert result.double_frequency_peak_magnitude[0] == 4.0


def test_related_peak_offset_retains_sign_and_units() -> None:
    stft, refined, quality = _related_inputs(refined_frequency_hz=42.5)
    spectrum = stft.spectrum.copy()
    spectrum[8, 0] = 6.0
    spectrum[2, 0] = 3.0
    object.__setattr__(stft, "spectrum", spectrum)

    result = _assess_related(
        stft,
        refined,
        quality,
        search_half_width_hz=6.0,
    )

    assert result.double_frequency_target_hz[0] == 85.0
    assert result.double_frequency_peak_hz[0] == 80.0
    assert result.double_frequency_peak_offset_hz[0] == -5.0
    assert result.half_frequency_target_hz[0] == 21.25
    assert result.half_frequency_peak_hz[0] == 20.0
    assert result.half_frequency_peak_offset_hz[0] == -1.25


def test_double_target_out_of_range_does_not_hide_valid_half_evidence() -> None:
    stft, refined, quality = _related_inputs(refined_frequency_hz=60.0)
    spectrum = stft.spectrum.copy()
    spectrum[3, 0] = 5.0
    object.__setattr__(stft, "spectrum", spectrum)

    result = _assess_related(stft, refined, quality)

    assert result.double_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.TARGET_OUT_OF_RANGE,
    )
    assert np.isnan(result.double_frequency_target_hz[0])
    assert result.half_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.ASSESSED,
    )
    assert result.half_frequency_peak_hz[0] == 30.0


def test_half_target_outside_explicit_analysis_band_is_masked() -> None:
    stft, refined, quality = _related_inputs(refined_frequency_hz=15.0)

    result = _assess_related(
        stft,
        refined,
        quality,
        search_half_width_hz=6.0,
    )

    assert result.half_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.TARGET_OUT_OF_RANGE,
    )
    _assert_all_nan_at(
        result,
        (
            "half_frequency_target_hz",
            "half_frequency_peak_hz",
            "half_frequency_peak_magnitude",
            "half_frequency_peak_offset_hz",
            "main_to_half_frequency_db",
        ),
        [0],
    )


def test_in_range_target_without_bins_has_explicit_status() -> None:
    stft, refined, quality = _related_inputs(refined_frequency_hz=42.5)

    result = _assess_related(
        stft,
        refined,
        quality,
        search_half_width_hz=0.1,
    )

    assert result.double_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.INSUFFICIENT_SEARCH_BINS,
    )
    assert result.double_frequency_target_hz[0] == 85.0
    assert np.isnan(result.double_frequency_peak_hz[0])
    assert result.half_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.INSUFFICIENT_SEARCH_BINS,
    )


@pytest.mark.parametrize("invalid_main", [0.0, np.nan, np.inf])
def test_nonpositive_or_nonfinite_main_peak_has_explicit_status(
    invalid_main: float,
) -> None:
    stft, refined, quality = _related_inputs()
    object.__setattr__(quality, "peak_magnitude", np.array([invalid_main]))

    result = _assess_related(stft, refined, quality)

    assert result.double_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.INVALID_MAIN_PEAK_MAGNITUDE,
    )
    assert result.half_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.INVALID_MAIN_PEAK_MAGNITUDE,
    )
    assert np.isnan(result.main_peak_magnitude[0])


@pytest.mark.parametrize("invalid_related", [0.0, np.nan, np.inf])
def test_nonpositive_or_nonfinite_related_peak_has_explicit_status(
    invalid_related: float,
) -> None:
    stft, refined, quality = _related_inputs()
    corrupted = stft.spectrum.copy()
    corrupted[8, 0] = invalid_related
    object.__setattr__(stft, "spectrum", corrupted)

    result = _assess_related(stft, refined, quality)

    assert result.double_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.INVALID_RELATED_FREQUENCY_MAGNITUDE,
    )
    assert result.double_frequency_target_hz[0] == 80.0
    assert np.isnan(result.double_frequency_peak_magnitude[0])
    assert result.half_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.ASSESSED,
    )


def test_related_pre_event_and_outside_frames_are_fully_masked() -> None:
    stft, refined, quality = _related_inputs(
        time_s=np.array([0.0, 1.0, 2.0]),
        event_start_time_s=1.0,
        analysis_end_time_s=1.0,
    )

    result = _assess_related(stft, refined, quality)

    assert result.double_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.PRE_EVENT,
        RelatedFrequencyEvidenceStatus.ASSESSED,
        RelatedFrequencyEvidenceStatus.OUTSIDE_ANALYSIS_WINDOW,
    )
    assert result.half_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.PRE_EVENT,
        RelatedFrequencyEvidenceStatus.ASSESSED,
        RelatedFrequencyEvidenceStatus.OUTSIDE_ANALYSIS_WINDOW,
    )
    _assert_all_nan_at(
        result,
        (
            "refined_frequency_hz",
            "main_peak_magnitude",
            "double_frequency_target_hz",
            "main_to_double_frequency_db",
            "half_frequency_target_hz",
            "main_to_half_frequency_db",
        ),
        [0, 2],
    )


def test_refinement_failure_blocks_only_diagnostic_evidence() -> None:
    stft, refined, quality = _related_inputs(
        failed_frames={0: RidgeRefinementStatus.BOUNDARY_PEAK}
    )

    result = _assess_related(stft, refined, quality)

    assert result.double_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE,
    )
    assert result.half_frequency_statuses == (
        RelatedFrequencyEvidenceStatus.REFINEMENT_UNAVAILABLE,
    )
    assert refined.discrete_frequency_hz[0] == 40.0
    assert np.isnan(result.refined_frequency_hz[0])


def test_related_ratio_is_not_clipped_when_related_peak_is_stronger() -> None:
    stft, refined, quality = _related_inputs()
    spectrum = stft.spectrum.copy()
    spectrum[8, 0] = 200.0
    object.__setattr__(stft, "spectrum", spectrum)

    result = _assess_related(stft, refined, quality)

    assert result.main_to_double_frequency_db[0] == pytest.approx(-20.0)


@pytest.mark.parametrize("invalid_width", [True, 0.0, -1.0, np.nan, np.inf])
def test_related_search_half_width_must_be_finite_and_positive(
    invalid_width: float,
) -> None:
    stft, refined, quality = _related_inputs()

    with pytest.raises(RidgeConfigurationError, match="greater than zero"):
        _assess_related(
            stft,
            refined,
            quality,
            search_half_width_hz=invalid_width,
        )


def test_related_search_half_width_cannot_exceed_nyquist() -> None:
    stft, refined, quality = _related_inputs()

    with pytest.raises(RidgeConfigurationError, match="Nyquist"):
        _assess_related(
            stft,
            refined,
            quality,
            search_half_width_hz=100.1,
        )


def test_related_time_axis_mismatch_is_rejected() -> None:
    stft, refined, quality = _related_inputs()
    object.__setattr__(stft, "time_s", np.array([1.0]))

    with pytest.raises(RidgeConfigurationError, match="time_s axes"):
        _assess_related(stft, refined, quality)


def test_related_source_path_mismatch_is_rejected() -> None:
    stft, refined, quality = _related_inputs()
    object.__setattr__(quality, "source_path", Path("other.csv"))

    with pytest.raises(RidgeConfigurationError, match="source_path"):
        _assess_related(stft, refined, quality)


def test_related_frequency_and_time_range_mismatch_is_rejected() -> None:
    stft, refined, quality = _related_inputs()
    object.__setattr__(quality, "maximum_frequency_hz", 80.0)

    with pytest.raises(RidgeConfigurationError, match="frequency/time ranges"):
        _assess_related(stft, refined, quality)


@pytest.mark.parametrize("invalid_bin", [-1, 11])
def test_related_candidate_bin_index_must_be_in_stft_bounds(
    invalid_bin: int,
) -> None:
    stft, refined, quality = _related_inputs()
    object.__setattr__(
        refined,
        "discrete_frequency_bin_index",
        np.array([invalid_bin], dtype=np.int64),
    )
    object.__setattr__(
        quality,
        "discrete_frequency_bin_index",
        np.array([invalid_bin], dtype=np.int64),
    )

    with pytest.raises(RidgeConfigurationError, match="valid bin|out of bounds"):
        _assess_related(stft, refined, quality)


def test_related_analysis_band_must_lie_within_stft_and_nyquist() -> None:
    stft, refined, quality = _related_inputs()
    object.__setattr__(stft, "sample_rate_hz", 100.0)

    with pytest.raises(RidgeConfigurationError, match="Nyquist"):
        _assess_related(stft, refined, quality)


def test_public_diagnostic_imports_identity_equality_and_metadata() -> None:
    stft, refined, quality = _related_inputs()
    first_continuity = assess_ridge_continuity(refined)
    second_continuity = assess_ridge_continuity(refined)
    evidence = _assess_related(stft, refined, quality)

    assert first_continuity == first_continuity
    assert first_continuity != second_continuity
    assert RidgeContinuityResult.__module__.endswith("diagnostic_models")
    assert RelatedFrequencyEvidenceResult.__module__.endswith("diagnostic_models")
    assert assess_ridge_continuity.__module__.endswith("diagnostics")
    assert assess_related_frequency_evidence.__module__.endswith("diagnostics")
    assert evidence.search_half_width_hz == 1.0
    assert evidence.evidence_method == RelatedFrequencyEvidenceResult.EVIDENCE_METHOD
    assert evidence.source_path == SOURCE_PATH
    assert evidence.related_frequency_statuses == (
        (
            RelatedFrequencyEvidenceStatus.ASSESSED,
            RelatedFrequencyEvidenceStatus.ASSESSED,
        ),
    )


def test_mutating_inputs_after_diagnostics_does_not_change_results() -> None:
    stft, refined, quality = _related_inputs()
    continuity = assess_ridge_continuity(refined)
    evidence = _assess_related(stft, refined, quality)
    continuity_snapshot = continuity.refined_frequency_hz.copy()
    evidence_snapshot = evidence.double_frequency_peak_magnitude.copy()

    object.__setattr__(refined, "refined_frequency_hz", np.array([80.0]))
    object.__setattr__(stft, "spectrum", np.zeros_like(stft.spectrum))
    object.__setattr__(quality, "peak_magnitude", np.array([999.0]))

    np.testing.assert_array_equal(
        continuity.refined_frequency_hz,
        continuity_snapshot,
    )
    np.testing.assert_array_equal(
        evidence.double_frequency_peak_magnitude,
        evidence_snapshot,
    )


def test_all_diagnostic_array_base_chains_are_bytes_backed_and_immutable() -> None:
    stft, refined, quality = _related_inputs(
        time_s=np.array([0.0, 1.0, 2.0])
    )
    continuity = assess_ridge_continuity(refined)
    evidence = _assess_related(stft, refined, quality)

    continuity_arrays = (
        continuity.time_s,
        continuity.refined_frequency_hz,
        continuity.previous_refined_frequency_hz,
        continuity.frame_interval_s,
        continuity.frequency_step_hz,
        continuity.absolute_frequency_step_hz,
        continuity.frequency_slope_hz_s,
        continuity.frequency_second_difference_hz,
    )
    evidence_arrays = (
        evidence.time_s,
        evidence.refined_frequency_hz,
        evidence.discrete_frequency_bin_index,
        evidence.main_peak_magnitude,
        evidence.double_frequency_target_hz,
        evidence.double_frequency_peak_hz,
        evidence.double_frequency_peak_magnitude,
        evidence.double_frequency_peak_offset_hz,
        evidence.main_to_double_frequency_db,
        evidence.half_frequency_target_hz,
        evidence.half_frequency_peak_hz,
        evidence.half_frequency_peak_magnitude,
        evidence.half_frequency_peak_offset_hz,
        evidence.main_to_half_frequency_db,
    )
    for array in (*continuity_arrays, *evidence_arrays):
        _assert_bytes_backed_immutable(array)
