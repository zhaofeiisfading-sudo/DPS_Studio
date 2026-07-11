from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.models import (
    DPSStudioError,
    NonFiniteSignalError,
    NonMonotonicTimeError,
    SignalConversionError,
    SignalLengthError,
    SignalRecord,
    SignalShapeError,
    SignalValidationError,
)


def test_uniform_signal_has_expected_data_and_sampling_information() -> None:
    record = SignalRecord(
        time_s=[1.0, 1.25, 1.5],
        voltage_v=[0.5, -0.25, 1.0],
    )

    np.testing.assert_array_equal(record.time_s, np.array([1.0, 1.25, 1.5]))
    np.testing.assert_array_equal(record.voltage_v, np.array([0.5, -0.25, 1.0]))
    assert record.sample_count == 3
    assert record.representative_sample_interval_s == pytest.approx(0.25)
    assert record.sample_rate_hz == pytest.approx(4.0)
    assert record.nyquist_frequency_hz == pytest.approx(2.0)
    assert record.start_time_s == pytest.approx(1.0)
    assert record.end_time_s == pytest.approx(1.5)
    assert record.duration_s == pytest.approx(0.5)
    assert record.maximum_relative_interval_deviation == pytest.approx(0.0)
    assert record.is_uniformly_sampled is True


def test_python_lists_are_converted_to_float64_arrays() -> None:
    record = SignalRecord([0, 1, 2], [3, 4, 5])

    assert record.time_s.dtype == np.float64
    assert record.voltage_v.dtype == np.float64


def test_integer_arrays_are_copied_and_converted_to_float64() -> None:
    time_s = np.array([0, 1, 2], dtype=np.int64)
    voltage_v = np.array([10, 11, 12], dtype=np.int64)

    record = SignalRecord(time_s, voltage_v)

    assert record.time_s.dtype == np.float64
    assert record.voltage_v.dtype == np.float64
    np.testing.assert_array_equal(record.time_s, time_s.astype(np.float64))
    np.testing.assert_array_equal(record.voltage_v, voltage_v.astype(np.float64))


def test_mismatched_array_lengths_report_both_lengths() -> None:
    with pytest.raises(SignalLengthError, match=r"time_s length 3.*voltage_v length 2"):
        SignalRecord([0.0, 1.0, 2.0], [1.0, 2.0])


@pytest.mark.parametrize("sample_count", [0, 1])
def test_fewer_than_two_samples_are_rejected(sample_count: int) -> None:
    samples = [0.0] * sample_count

    with pytest.raises(SignalLengthError, match=rf"at least two samples; got {sample_count}"):
        SignalRecord(samples, samples)


@pytest.mark.parametrize(
    ("time_s", "voltage_v", "field_name"),
    [
        ([[0.0, 1.0], [2.0, 3.0]], [1.0, 2.0], "time_s"),
        ([0.0, 1.0], [[1.0, 2.0], [3.0, 4.0]], "voltage_v"),
    ],
)
def test_two_dimensional_arrays_are_rejected(
    time_s: object, voltage_v: object, field_name: str
) -> None:
    with pytest.raises(SignalShapeError, match=rf"{field_name}.*2 dimensions"):
        SignalRecord(time_s, voltage_v)


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("time_s", np.nan),
        ("time_s", np.inf),
        ("time_s", -np.inf),
        ("voltage_v", np.nan),
        ("voltage_v", np.inf),
        ("voltage_v", -np.inf),
    ],
)
def test_non_finite_samples_are_rejected_with_location(
    field_name: str, invalid_value: float
) -> None:
    time_s = [0.0, 1.0, 2.0]
    voltage_v = [3.0, 4.0, 5.0]
    if field_name == "time_s":
        time_s[1] = invalid_value
    else:
        voltage_v[1] = invalid_value

    with pytest.raises(NonFiniteSignalError, match=rf"{field_name}.*index 1"):
        SignalRecord(time_s, voltage_v)


@pytest.mark.parametrize(
    ("time_s", "message"),
    [
        ([2.0, 1.0, 0.0], r"decreases.*index 0.*index 1"),
        ([0.0, 2.0, 1.0], r"decreases.*index 1.*index 2"),
        ([0.0, 1.0, 1.0], r"duplicate.*indices 1 and 2"),
    ],
)
def test_non_increasing_time_is_rejected(time_s: list[float], message: str) -> None:
    with pytest.raises(NonMonotonicTimeError, match=message):
        SignalRecord(time_s, [1.0, 2.0, 3.0])


def test_non_uniform_signal_is_preserved_and_uses_median_interval() -> None:
    time_s = np.array([0.0, 1.0, 3.0, 6.0])
    record = SignalRecord(time_s, [0.0, 1.0, 0.0, -1.0])

    np.testing.assert_array_equal(record.time_s, time_s)
    assert record.representative_sample_interval_s == pytest.approx(2.0)
    assert record.sample_rate_hz == pytest.approx(0.5)
    assert record.nyquist_frequency_hz == pytest.approx(0.25)
    assert record.maximum_relative_interval_deviation == pytest.approx(0.5)
    assert record.is_uniformly_sampled is False


def test_uniformity_tolerance_can_be_overridden() -> None:
    record = SignalRecord(
        [0.0, 1.0, 2.0000005],
        [1.0, 2.0, 3.0],
        uniformity_relative_tolerance=1e-8,
    )

    assert record.uniformity_relative_tolerance == pytest.approx(1e-8)
    assert record.maximum_relative_interval_deviation > 1e-8
    assert record.is_uniformly_sampled is False


@pytest.mark.parametrize("tolerance", [-1.0, np.nan, np.inf, -np.inf])
def test_invalid_uniformity_tolerance_is_rejected(tolerance: float) -> None:
    with pytest.raises(
        SignalValidationError,
        match=r"uniformity_relative_tolerance.*finite and non-negative",
    ):
        SignalRecord(
            [0.0, 1.0],
            [1.0, 2.0],
            uniformity_relative_tolerance=tolerance,
        )


def test_zero_tolerance_performs_strict_uniformity_check() -> None:
    record = SignalRecord(
        [0.0, 0.5, 1.0],
        [1.0, 2.0, 3.0],
        uniformity_relative_tolerance=0.0,
    )

    assert record.uniformity_relative_tolerance == 0.0
    assert record.maximum_relative_interval_deviation == 0.0
    assert record.is_uniformly_sampled is True


def test_two_samples_have_zero_deviation_and_are_uniform() -> None:
    record = SignalRecord([10.0, 10.25], [1.0, 2.0])

    assert record.maximum_relative_interval_deviation == pytest.approx(0.0)
    assert record.is_uniformly_sampled is True


def test_extreme_finite_times_with_overflowing_interval_are_rejected() -> None:
    maximum_float = np.finfo(np.float64).max

    with pytest.raises(SignalValidationError, match=r"interval.*indices 0 and 1.*non-finite"):
        SignalRecord([-maximum_float, maximum_float], [1.0, 2.0])


def test_original_input_arrays_do_not_share_storage_with_record() -> None:
    time_s = np.array([0.0, 1.0, 2.0])
    voltage_v = np.array([3.0, 4.0, 5.0])
    record = SignalRecord(time_s, voltage_v)

    time_s[0] = 100.0
    voltage_v[0] = 200.0

    assert record.time_s[0] == pytest.approx(0.0)
    assert record.voltage_v[0] == pytest.approx(3.0)


def test_public_arrays_are_read_only() -> None:
    record = SignalRecord([0.0, 1.0], [2.0, 3.0])

    time_view = record.time_s
    voltage_view = record.voltage_v

    assert time_view.flags.owndata is False
    assert voltage_view.flags.owndata is False
    assert time_view.flags.writeable is False
    assert voltage_view.flags.writeable is False
    assert isinstance(time_view.base, np.ndarray)
    assert isinstance(voltage_view.base, np.ndarray)
    assert time_view.base.flags.writeable is False
    assert voltage_view.base.flags.writeable is False

    with pytest.raises(ValueError, match="read-only"):
        record.time_s[0] = 10.0
    with pytest.raises(ValueError, match="read-only"):
        record.voltage_v[0] = 10.0

    with pytest.raises(ValueError, match="WRITEABLE"):
        record.time_s.setflags(write=True)
    with pytest.raises(ValueError, match="WRITEABLE"):
        record.voltage_v.setflags(write=True)
    with pytest.raises(ValueError, match="WRITEABLE"):
        time_view.setflags(write=True)
    with pytest.raises(ValueError, match="WRITEABLE"):
        voltage_view.setflags(write=True)
    with pytest.raises(ValueError, match="WRITEABLE"):
        time_view.base.setflags(write=True)
    with pytest.raises(ValueError, match="WRITEABLE"):
        voltage_view.base.setflags(write=True)

    assert record.time_s[0] == pytest.approx(0.0)
    assert record.voltage_v[0] == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("attribute_name", "expected_first_value"),
    [("time_s", 0.0), ("voltage_v", 2.0)],
)
def test_complete_public_array_base_chain_cannot_modify_record(
    attribute_name: str, expected_first_value: float
) -> None:
    record = SignalRecord([0.0, 1.0], [2.0, 3.0])
    current: object = getattr(record, attribute_name)
    visited_object_ids: set[int] = set()

    while isinstance(current, np.ndarray):
        assert id(current) not in visited_object_ids
        visited_object_ids.add(id(current))
        assert current.flags.writeable is False
        with pytest.raises(ValueError, match="WRITEABLE"):
            current.setflags(write=True)
        with pytest.raises(ValueError, match="read-only"):
            current[0] = -999.0
        current = current.base

    assert isinstance(current, bytes)
    assert memoryview(current).readonly is True
    assert getattr(record, attribute_name)[0] == pytest.approx(expected_first_value)


def test_metadata_is_deep_copied_during_construction_and_access() -> None:
    metadata = {
        "experiment": {
            "operators": ["Ada", "Lin"],
            "settings": {"trigger": "external"},
        }
    }
    record = SignalRecord([0.0, 1.0], [2.0, 3.0], metadata=metadata)

    metadata["experiment"]["operators"].append("External mutation")
    metadata["experiment"]["settings"]["trigger"] = "changed"
    first_result = record.metadata
    assert first_result == {
        "experiment": {
            "operators": ["Ada", "Lin"],
            "settings": {"trigger": "external"},
        }
    }

    first_result["experiment"]["operators"].append("Returned mutation")
    first_result["experiment"]["settings"]["trigger"] = "returned change"
    assert record.metadata == {
        "experiment": {
            "operators": ["Ada", "Lin"],
            "settings": {"trigger": "external"},
        }
    }


def test_relative_source_path_is_preserved_without_resolution_or_existence_check() -> None:
    relative_path = Path("relative") / "path" / "that-does-not-exist.pdv"

    record = SignalRecord([0.0, 1.0], [2.0, 3.0], source_path=relative_path)

    assert record.source_path == relative_path
    assert record.source_path is not None
    assert record.source_path.is_absolute() is False


def test_string_source_path_is_converted_to_path() -> None:
    record = SignalRecord([0.0, 1.0], [2.0, 3.0], source_path="signal.dat")

    assert record.source_path == Path("signal.dat")


@pytest.mark.parametrize("field_name", ["time_s", "voltage_v"])
def test_conversion_errors_identify_field_and_preserve_cause(field_name: str) -> None:
    time_s: object = [0.0, 1.0]
    voltage_v: object = [2.0, 3.0]
    if field_name == "time_s":
        time_s = ["not-a-number", "still-not-a-number"]
    else:
        voltage_v = ["not-a-number", "still-not-a-number"]

    with pytest.raises(SignalConversionError, match=field_name) as error_info:
        SignalRecord(time_s, voltage_v)

    assert isinstance(error_info.value, DPSStudioError)
    assert isinstance(error_info.value.__cause__, (TypeError, ValueError))


def test_signal_record_equality_uses_identity_without_array_comparison() -> None:
    first = SignalRecord([0.0, 1.0], [2.0, 3.0])
    second = SignalRecord([0.0, 1.0], [2.0, 3.0])

    assert first == first
    assert first != second


def test_public_import_exposes_signal_record() -> None:
    assert SignalRecord.__module__ == "dps_studio.core.models.signal"
