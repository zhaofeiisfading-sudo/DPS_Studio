from pathlib import Path

import numpy as np
import pytest

import dps_studio.core.time_frequency.stft as stft_module
from dps_studio.core.models import DPSStudioError, SignalRecord
from dps_studio.core.time_frequency import (
    NonUniformSamplingError,
    STFTComputationError,
    STFTConfigurationError,
    STFTResult,
    TimeFrequencyError,
    compute_stft,
)


def _sine_record(
    *,
    sample_count: int = 1024,
    sample_rate_hz: float = 1024.0,
    frequency_hz: float = 128.0,
    start_time_s: float = 0.0,
    source_path: Path | None = None,
) -> SignalRecord:
    time_s = start_time_s + np.arange(sample_count, dtype=np.float64) / sample_rate_hz
    voltage_v = np.sin(2.0 * np.pi * frequency_hz * (time_s - start_time_s))
    return SignalRecord(time_s, voltage_v, source_path=source_path)


def _default_stft(record: SignalRecord, *, nfft: int | None = 256) -> STFTResult:
    return compute_stft(
        record,
        window_length_samples=256,
        overlap_samples=128,
        nfft=nfft,
        window_name="hann",
    )


def test_known_bin_centered_sine_has_expected_peak_and_metadata() -> None:
    result = _default_stft(_sine_record())

    peak_frequency_hz = result.frequency_hz[
        np.unravel_index(np.abs(result.spectrum).argmax(), result.spectrum.shape)[0]
    ]
    assert peak_frequency_hz == pytest.approx(128.0)
    assert result.spectrum.dtype == np.complex128
    assert result.window_name == "hann"
    assert result.window_length_samples == 256
    assert result.overlap_samples == 128
    assert result.hop_samples == 128
    assert result.scaling == "spectrum"
    assert result.is_one_sided is True
    assert result.detrend_applied is False
    assert result.boundary_padding_applied is False


def test_time_axis_is_absolute_shape_matches_and_tail_is_not_padded() -> None:
    sample_count = 1000
    record = _sine_record(sample_count=sample_count, start_time_s=10.0)

    result = _default_stft(record)

    expected_frame_count = (sample_count - 256) // 128 + 1
    assert result.time_s[0] == pytest.approx(10.0 + 128.0 / 1024.0)
    assert result.time_s.size == expected_frame_count
    assert result.spectrum.shape == (result.frequency_hz.size, result.time_s.size)


def test_frequency_axis_is_strictly_increasing_one_sided_and_bounded() -> None:
    record = _sine_record()

    result = _default_stft(record)

    assert result.frequency_hz[0] == pytest.approx(0.0)
    assert np.all(np.diff(result.frequency_hz) > 0.0)
    assert result.frequency_hz[-1] <= record.nyquist_frequency_hz


def test_nfft_none_resolves_to_window_length() -> None:
    result = _default_stft(_sine_record(), nfft=None)

    assert result.nfft == result.window_length_samples == 256
    assert result.frequency_hz.size == 129


def test_larger_nfft_densifies_grid_without_changing_frame_count() -> None:
    record = _sine_record()

    base = _default_stft(record, nfft=256)
    zero_padded = _default_stft(record, nfft=512)

    assert zero_padded.time_s.size == base.time_s.size
    assert zero_padded.frequency_hz.size > base.frequency_hz.size
    assert np.diff(zero_padded.frequency_hz)[0] < np.diff(base.frequency_hz)[0]


def test_constant_input_retains_dc_without_detrending_or_mean_removal() -> None:
    time_s = np.arange(512, dtype=np.float64) / 1024.0
    record = SignalRecord(time_s, np.full(time_s.size, 3.25))

    result = _default_stft(record)

    assert np.all(np.abs(result.spectrum[0]) == pytest.approx(3.25))
    assert np.all(np.abs(result.spectrum[0]) > np.max(np.abs(result.spectrum[1:]), axis=0))


def test_nonuniform_record_is_rejected_with_sampling_and_source_context() -> None:
    record = SignalRecord(
        [0.0, 1.0, 2.2, 3.2],
        [0.0, 1.0, 0.0, -1.0],
        source_path=Path("relative") / "nonuniform.csv",
    )

    with pytest.raises(NonUniformSamplingError) as error_info:
        compute_stft(record, window_length_samples=2, overlap_samples=1)

    message = str(error_info.value)
    assert "not approximately uniformly sampled" in message
    assert "maximum_relative_interval_deviation=" in message
    assert "uniformity_relative_tolerance=" in message
    assert str(record.source_path) in message


def test_record_must_be_signal_record() -> None:
    with pytest.raises(STFTConfigurationError, match="record must be a SignalRecord"):
        compute_stft(  # type: ignore[arg-type]
            object(),
            window_length_samples=2,
            overlap_samples=1,
        )


def test_invalid_window_lengths_are_rejected_before_scipy() -> None:
    record = _sine_record(sample_count=16)
    invalid_values = [1, 17, True]

    for value in invalid_values:
        with pytest.raises(STFTConfigurationError):
            compute_stft(
                record,
                window_length_samples=value,
                overlap_samples=0,
            )


def test_invalid_overlaps_are_rejected_before_scipy() -> None:
    record = _sine_record(sample_count=16)
    invalid_values = [-1, 8, True]

    for value in invalid_values:
        with pytest.raises(STFTConfigurationError):
            compute_stft(
                record,
                window_length_samples=8,
                overlap_samples=value,
            )


def test_invalid_nfft_values_are_rejected_before_scipy() -> None:
    record = _sine_record(sample_count=16)
    invalid_values = [7, True]

    for value in invalid_values:
        with pytest.raises(STFTConfigurationError):
            compute_stft(
                record,
                window_length_samples=8,
                overlap_samples=4,
                nfft=value,
            )


def test_blank_window_names_are_rejected() -> None:
    record = _sine_record(sample_count=16)

    for value in ["", "   "]:
        with pytest.raises(STFTConfigurationError, match="non-empty string"):
            compute_stft(
                record,
                window_length_samples=8,
                overlap_samples=4,
                window_name=value,
            )


@pytest.mark.parametrize(
    "window_name",
    ["hann", "hamming", "blackman", "blackmanharris", "boxcar"],
)
def test_formal_window_presets_run_without_changing_sampling_configuration(
    window_name: str,
) -> None:
    record = _sine_record(sample_count=1024)
    original_time = record.time_s.copy()
    original_voltage = record.voltage_v.copy()

    result = compute_stft(
        record,
        window_length_samples=256,
        overlap_samples=128,
        nfft=512,
        window_name=window_name,
    )

    assert result.window_name == window_name
    assert result.window_length_samples == 256
    assert result.overlap_samples == 128
    assert result.hop_samples == 128
    assert result.nfft == 512
    assert result.spectrum.shape == (257, 7)
    assert result.time_s.shape == (7,)
    assert result.frequency_hz.shape == (257,)
    np.testing.assert_array_equal(record.time_s, original_time)
    np.testing.assert_array_equal(record.voltage_v, original_voltage)


def test_unsupported_formal_window_is_rejected_without_hann_fallback() -> None:
    record = _sine_record(sample_count=16)

    with pytest.raises(
        STFTConfigurationError,
        match="Unsupported formal STFT window_name",
    ) as info:
        compute_stft(
            record,
            window_length_samples=8,
            overlap_samples=4,
            window_name="not-a-real-scipy-window",
        )

    assert info.value.__cause__ is None


def test_result_arrays_are_detached_and_entire_base_chains_are_immutable() -> None:
    time_s = np.array([1.0, 2.0])
    frequency_hz = np.array([0.0, 1.0, 2.0])
    spectrum = np.arange(6, dtype=np.complex128).reshape(3, 2)
    result = STFTResult(
        time_s=time_s,
        frequency_hz=frequency_hz,
        spectrum=spectrum,
        window_name="hann",
        window_length_samples=4,
        overlap_samples=2,
        hop_samples=2,
        nfft=4,
        sample_rate_hz=4.0,
        source_path=None,
        scaling="spectrum",
        is_one_sided=True,
        detrend_applied=False,
        boundary_padding_applied=False,
    )

    time_s[0] = 99.0
    frequency_hz[0] = 99.0
    spectrum[0, 0] = 99.0
    assert result.time_s[0] == pytest.approx(1.0)
    assert result.frequency_hz[0] == pytest.approx(0.0)
    assert result.spectrum[0, 0] == pytest.approx(0.0)

    for array in [result.time_s, result.frequency_hz, result.spectrum]:
        current: object = array
        visited_ids: set[int] = set()
        while isinstance(current, np.ndarray):
            assert id(current) not in visited_ids
            visited_ids.add(id(current))
            assert current.flags.writeable is False
            with pytest.raises(ValueError, match="WRITEABLE"):
                current.setflags(write=True)
            with pytest.raises(ValueError, match="read-only"):
                current.flat[0] = -999.0
            current = current.base
        assert isinstance(current, bytes)
        assert memoryview(current).readonly is True


def test_computation_does_not_modify_signal_record() -> None:
    record = _sine_record(source_path=Path("input.csv"))
    original_time = record.time_s.copy()
    original_voltage = record.voltage_v.copy()
    original_sampling = (
        record.sample_rate_hz,
        record.maximum_relative_interval_deviation,
        record.source_path,
        record.metadata,
    )

    _default_stft(record)

    np.testing.assert_array_equal(record.time_s, original_time)
    np.testing.assert_array_equal(record.voltage_v, original_voltage)
    assert (
        record.sample_rate_hz,
        record.maximum_relative_interval_deviation,
        record.source_path,
        record.metadata,
    ) == original_sampling


def test_relative_source_path_public_imports_and_identity_equality_are_preserved() -> None:
    relative_path = Path("relative") / "signal.csv"
    record = _sine_record(source_path=relative_path)

    first = _default_stft(record)
    second = _default_stft(record)

    assert first.source_path == relative_path
    assert first.source_path is not None
    assert first.source_path.is_absolute() is False
    assert first == first
    assert first != second
    assert STFTResult.__module__ == "dps_studio.core.time_frequency.models"
    assert compute_stft.__module__ == "dps_studio.core.time_frequency.stft"
    assert issubclass(TimeFrequencyError, DPSStudioError)


def test_unexpected_scipy_error_is_wrapped_without_exposing_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _sine_record(sample_count=16)

    def fail_stft(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic scipy failure")

    monkeypatch.setattr(stft_module.scipy.signal, "stft", fail_stft)
    with pytest.raises(STFTComputationError) as info:
        compute_stft(record, window_length_samples=8, overlap_samples=4)

    assert isinstance(info.value.__cause__, RuntimeError)
    assert "[" not in str(info.value)
