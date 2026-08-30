from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest

from dps_studio.core.io import (
    WHITESPACE_DELIMITER,
    DelimitedSignalLoadResult,
    SignalColumnError,
    SignalConfigurationError,
    SignalEncodingError,
    SignalFileNotFoundError,
    SignalFileTypeError,
    SignalParseError,
    detect_delimiter,
    preview_delimited_file,
    read_delimited_signals,
)
from dps_studio.core.models import (
    NonFiniteSignalError,
    NonMonotonicTimeError,
    SignalRecord,
)


def _write_text_file(tmp_path: Path, content: str, *, name: str = "signal.data") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8", newline="")
    return path


def test_reads_headerless_single_channel_and_metadata(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1\n1,2\n2,3\n")

    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"pdv": 1},
    )

    assert result.source_path == path
    assert result.row_count == 3
    assert result.column_count == 2
    assert result.channel_names == ("pdv",)
    assert result.header is None
    assert result.time_column_index == 0
    assert dict(result.voltage_column_indices) == {"pdv": 1}
    assert result.unselected_column_indices == ()
    assert result.delimiter == ","
    assert result.encoding == "utf-8"
    np.testing.assert_array_equal(result.records["pdv"].time_s, [0.0, 1.0, 2.0])
    np.testing.assert_array_equal(result.records["pdv"].voltage_v, [1.0, 2.0, 3.0])
    assert result.records["pdv"].time_s.dtype == np.float64
    assert result.records["pdv"].metadata == {
        "channel_name": "pdv",
        "time_column_index": 0,
        "voltage_column_index": 1,
        "time_scale": 1.0,
        "voltage_scale": 1.0,
    }


def test_reads_two_channels_scientific_notation_spacing_and_crlf(tmp_path: Path) -> None:
    path = _write_text_file(
        tmp_path,
        "0.0e0, 1.0e1, -2.0e1\r\n1.0e0, 1.1e1, -2.1e1\r\n",
    )

    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"channel_2": 2, "channel_1": 1},
    )

    assert result.channel_names == ("channel_2", "channel_1")
    np.testing.assert_array_equal(result.records["channel_2"].voltage_v, [-20.0, -21.0])
    np.testing.assert_array_equal(result.records["channel_1"].voltage_v, [10.0, 11.0])


@pytest.mark.parametrize(
    "content",
    (
        "0 1\n1 2\n",
        "  0    1  \n  1  2  \n",
        "0\t1\n1\t2\n",
        " 0\t  1\n1  \t2 \n",
        "0\u20031\n1\u20032\n",
    ),
)
def test_whitespace_mode_collapses_unicode_whitespace_runs(
    tmp_path: Path,
    content: str,
) -> None:
    path = _write_text_file(tmp_path, content)

    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"pdv": 1},
        delimiter=WHITESPACE_DELIMITER,
    )

    assert result.column_count == 2
    assert result.delimiter == WHITESPACE_DELIMITER
    np.testing.assert_array_equal(result.records["pdv"].time_s, [0.0, 1.0])
    np.testing.assert_array_equal(result.records["pdv"].voltage_v, [1.0, 2.0])


def test_whitespace_mode_keeps_blank_rows_strict(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0 1\n\n1 2\n")

    with pytest.raises(
        SignalColumnError,
        match=r"physical line 2: expected 2, got 0",
    ):
        read_delimited_signals(
            path,
            time_column=0,
            voltage_columns={"pdv": 1},
            delimiter=WHITESPACE_DELIMITER,
        )


def test_explicit_comma_mode_preserves_empty_field_error(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,,1\n1,2,3\n")

    with pytest.raises(SignalParseError, match=r"zero-based column 1"):
        read_delimited_signals(
            path,
            time_column=0,
            voltage_columns={"pdv": 2},
            delimiter=",",
        )


def test_explicit_semicolon_delimiter_behavior_is_unchanged(tmp_path: Path) -> None:
    path = _write_text_file(
        tmp_path,
        '0;"unselected; text";1\n1;"other; text";2\n',
    )

    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"pdv": 2},
        delimiter=";",
    )

    assert result.column_count == 3
    assert result.unselected_column_indices == (1,)
    np.testing.assert_array_equal(result.records["pdv"].voltage_v, [1.0, 2.0])


@pytest.mark.parametrize(
    ("content", "expected_delimiter"),
    (
        ("0,1\n1,2\n", ","),
        ("0\t1\n1\t2\n", "\t"),
        ("0 1\n1 2\n", WHITESPACE_DELIMITER),
        ("  0   1\n 1\t 2\n", WHITESPACE_DELIMITER),
    ),
)
def test_auto_detection_and_formal_reader_share_tokenization(
    tmp_path: Path,
    content: str,
    expected_delimiter: str,
) -> None:
    path = _write_text_file(tmp_path, content)

    preview = preview_delimited_file(path)
    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"pdv": 1},
        delimiter=preview.delimiter,
        has_header=preview.has_header,
    )

    assert detect_delimiter(content) == expected_delimiter
    assert preview.delimiter == expected_delimiter
    assert preview.column_count == result.column_count == 2
    assert result.row_count == 2


def test_reads_and_strips_complete_header(tmp_path: Path) -> None:
    path = _write_text_file(
        tmp_path,
        " time_s , voltage , note \n0,1,first\n1,2,second\n",
    )

    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"pdv": 1},
        has_header=True,
    )

    assert result.header == ("time_s", "voltage", "note")
    assert result.row_count == 2
    assert result.column_count == 3
    assert result.unselected_column_indices == (2,)


def test_applies_time_and_independent_voltage_scales(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1,10\n2,2,20\n")

    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"positive": 1, "reversed": 2},
        time_scale=1e-6,
        voltage_scales={"positive": 2.0, "reversed": -0.5},
    )

    np.testing.assert_array_equal(result.records["positive"].time_s, [0.0, 2e-6])
    np.testing.assert_array_equal(result.records["positive"].voltage_v, [2.0, 4.0])
    np.testing.assert_array_equal(result.records["reversed"].voltage_v, [-5.0, -10.0])
    assert result.records["reversed"].metadata["voltage_scale"] == -0.5


def test_unselected_nonempty_text_is_allowed_and_reported(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1,unused-a,3\n1,2,unused-b,4\n")

    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"first": 1, "third": 3},
    )

    assert result.time_column_index == 0
    assert result.unselected_column_indices == (2,)
    np.testing.assert_array_equal(result.records["third"].voltage_v, [3.0, 4.0])


def test_quoted_unselected_text_with_comma_preserves_column_structure(
    tmp_path: Path,
) -> None:
    path = _write_text_file(
        tmp_path,
        '0.0, "text, with comma", 1.0\n1.0, "other, text", 2.0\n',
    )

    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"pdv": 2},
    )

    assert result.column_count == 3
    assert result.unselected_column_indices == (1,)
    np.testing.assert_array_equal(result.records["pdv"].voltage_v, [1.0, 2.0])


def test_all_selected_columns_produce_empty_unselected_tuple(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1,2\n1,3,4\n")

    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"a": 1, "b": 2},
    )

    assert result.unselected_column_indices == ()


def test_empty_field_in_selected_or_unselected_column_is_rejected(tmp_path: Path) -> None:
    cases = [
        ("0,1,\n1,2,text\n", 2, ","),
        ("0,,text\n1,2,text\n", 1, ","),
        ("0  1\n1  2\n", 1, " "),
    ]

    for case_number, (content, column_index, delimiter) in enumerate(cases):
        path = _write_text_file(tmp_path, content, name=f"empty-{case_number}.data")
        with pytest.raises(SignalParseError) as error_info:
            read_delimited_signals(
                path,
                time_column=0,
                voltage_columns={"pdv": 1},
                delimiter=delimiter,
            )

        message = str(error_info.value)
        assert str(path) in message
        assert "physical line 1" in message
        assert f"zero-based column {column_index}" in message
        assert "original field ''" in message


def test_inconsistent_row_width_is_rejected(tmp_path: Path) -> None:
    cases = [
        "0,1,2\n1,2\n",
        "0,1\n1,2,3\n",
    ]

    for case_number, content in enumerate(cases):
        path = _write_text_file(tmp_path, content, name=f"width-{case_number}.data")
        with pytest.raises(
            SignalColumnError,
            match=r"physical line 2: expected .* got",
        ):
            read_delimited_signals(path, time_column=0, voltage_columns={"pdv": 1})


def test_non_numeric_voltage_reports_full_field_context(tmp_path: Path) -> None:
    path = _write_text_file(
        tmp_path,
        "time,voltage\n0,1\n1, bad value \n",
    )

    with pytest.raises(SignalParseError) as error_info:
        read_delimited_signals(
            path,
            time_column=0,
            voltage_columns={"pdv_channel": 1},
            has_header=True,
        )

    message = str(error_info.value)
    assert str(path) in message
    assert "physical line 3" in message
    assert "zero-based column 1" in message
    assert "pdv_channel" in message
    assert repr("bad value ") in message
    assert isinstance(error_info.value.__cause__, ValueError)


def test_non_numeric_time_reports_time_column_context(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1\nnot-time,2\n")

    with pytest.raises(SignalParseError) as error_info:
        read_delimited_signals(path, time_column=0, voltage_columns={"pdv": 1})

    message = str(error_info.value)
    assert "physical line 2" in message
    assert "zero-based column 0" in message
    assert repr("not-time") in message


def test_requested_time_or_voltage_column_out_of_range_is_rejected(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1\n1,2\n")

    with pytest.raises(SignalColumnError, match=r"time column 2.*does not exist"):
        read_delimited_signals(path, time_column=2, voltage_columns={"pdv": 1})
    with pytest.raises(SignalColumnError, match=r"voltage column 3.*pdv.*does not exist"):
        read_delimited_signals(path, time_column=0, voltage_columns={"pdv": 3})


def test_conflicting_or_duplicate_selected_columns_are_rejected(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1,2\n1,2,3\n")

    with pytest.raises(SignalConfigurationError, match="also be selected"):
        read_delimited_signals(path, time_column=0, voltage_columns={"pdv": 0})
    with pytest.raises(SignalConfigurationError, match="distinct source column"):
        read_delimited_signals(
            path,
            time_column=0,
            voltage_columns={"first": 1, "second": 1},
        )


def test_voltage_scale_keys_must_exactly_match_channels(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1,2\n1,2,3\n")
    columns = {"a": 1, "b": 2}

    with pytest.raises(SignalConfigurationError, match=r"missing=\('b',\)"):
        read_delimited_signals(
            path,
            time_column=0,
            voltage_columns=columns,
            voltage_scales={"a": 1.0},
        )
    with pytest.raises(SignalConfigurationError, match=r"extra=\('c',\)"):
        read_delimited_signals(
            path,
            time_column=0,
            voltage_columns=columns,
            voltage_scales={"a": 1.0, "b": 1.0, "c": 1.0},
        )


def test_invalid_reader_configuration_is_rejected(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1\n1,2\n")
    invalid_calls = [
        {"time_column": True, "voltage_columns": {"pdv": 1}},
        {"time_column": -1, "voltage_columns": {"pdv": 1}},
        {"time_column": 0, "voltage_columns": {}},
        {"time_column": 0, "voltage_columns": {" ": 1}},
        {"time_column": 0, "voltage_columns": {"pdv": True}},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "delimiter": ""},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "delimiter": "::"},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "encoding": ""},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "encoding": "not-a-codec"},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "has_header": 1},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "time_scale": True},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "time_scale": 0.0},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "time_scale": -1.0},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "time_scale": np.nan},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "time_scale": np.inf},
        {"time_column": 0, "voltage_columns": {"pdv": 1}, "time_scale": 10**10000},
        {
            "time_column": 0,
            "voltage_columns": {"pdv": 1},
            "voltage_scales": {"pdv": 0.0},
        },
        {
            "time_column": 0,
            "voltage_columns": {"pdv": 1},
            "voltage_scales": {"pdv": False},
        },
        {
            "time_column": 0,
            "voltage_columns": {"pdv": 1},
            "voltage_scales": {"pdv": np.nan},
        },
        {
            "time_column": 0,
            "voltage_columns": {"pdv": 1},
            "voltage_scales": {"pdv": np.inf},
        },
    ]

    for kwargs in invalid_calls:
        with pytest.raises(SignalConfigurationError):
            read_delimited_signals(path, **kwargs)


def test_missing_file_is_rejected_with_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.csv"

    with pytest.raises(SignalFileNotFoundError, match="missing.csv"):
        read_delimited_signals(path, time_column=0, voltage_columns={"pdv": 1})


def test_directory_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SignalFileTypeError, match="not a regular file"):
        read_delimited_signals(tmp_path, time_column=0, voltage_columns={"pdv": 1})


def test_empty_file_and_header_only_file_are_rejected(tmp_path: Path) -> None:
    empty_path = _write_text_file(tmp_path, "", name="empty.csv")
    header_path = _write_text_file(tmp_path, "time,voltage\n", name="header.csv")

    with pytest.raises(SignalParseError, match="is empty"):
        read_delimited_signals(
            empty_path,
            time_column=0,
            voltage_columns={"pdv": 1},
        )
    with pytest.raises(SignalParseError, match="header but no data"):
        read_delimited_signals(
            header_path,
            time_column=0,
            voltage_columns={"pdv": 1},
            has_header=True,
        )


def test_decoding_error_preserves_original_exception(tmp_path: Path) -> None:
    path = tmp_path / "invalid-utf8.data"
    path.write_bytes(b"0,1\n1,\xff\n")

    with pytest.raises(SignalEncodingError, match="utf-8") as error_info:
        read_delimited_signals(path, time_column=0, voltage_columns={"pdv": 1})

    assert isinstance(error_info.value.__cause__, UnicodeDecodeError)


def test_result_mappings_are_immutable_and_detached_from_inputs(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1\n1,2\n")
    columns = {"pdv": 1}
    scales = {"pdv": 1.0}
    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns=columns,
        voltage_scales=scales,
    )

    columns["pdv"] = 99
    scales["pdv"] = 99.0
    assert dict(result.voltage_column_indices) == {"pdv": 1}
    assert result.records["pdv"].metadata["voltage_scale"] == 1.0
    with pytest.raises(TypeError):
        result.records["other"] = result.records["pdv"]
    with pytest.raises(TypeError):
        del result.records["pdv"]
    with pytest.raises(TypeError):
        result.voltage_column_indices["pdv"] = 2
    with pytest.raises(FrozenInstanceError):
        result.channel_names += ("new",)
    with pytest.raises(FrozenInstanceError):
        result.row_count = 99
    assert result.channel_names == ("pdv",)
    assert result.row_count == 2
    assert tuple(result.records) == ("pdv",)


def test_channels_receive_independent_signal_records_and_arrays(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1,2\n1,3,4\n")
    result = read_delimited_signals(
        path,
        time_column=0,
        voltage_columns={"a": 1, "b": 2},
    )

    first = result.records["a"]
    second = result.records["b"]
    assert first is not second
    np.testing.assert_array_equal(first.time_s, second.time_s)
    assert not np.shares_memory(first.time_s, second.time_s)
    assert not np.shares_memory(first.voltage_v, second.voltage_v)


def test_signal_validation_error_type_is_preserved_with_context_note(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1\n2,2\n1,3\n")

    with pytest.raises(NonMonotonicTimeError) as error_info:
        read_delimited_signals(path, time_column=0, voltage_columns={"pdv": 1})

    notes = error_info.value.__notes__
    assert len(notes) == 1
    assert str(path) in notes[0]
    assert "channel 'pdv'" in notes[0]
    assert "time column 0" in notes[0]
    assert "voltage column 1" in notes[0]


def test_later_channel_failure_preserves_model_error_and_returns_no_result(
    tmp_path: Path,
) -> None:
    path = _write_text_file(tmp_path, "0,1,3\n1,2,nan\n")

    with pytest.raises(NonFiniteSignalError) as error_info:
        read_delimited_signals(
            path,
            time_column=0,
            voltage_columns={"valid": 1, "invalid": 2},
        )

    assert "channel 'invalid'" in error_info.value.__notes__[0]
    assert "voltage column 2" in error_info.value.__notes__[0]


def test_nonuniform_time_is_preserved_and_marked(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, "0,1\n1,2\n3,3\n")

    result = read_delimited_signals(path, time_column=0, voltage_columns={"pdv": 1})

    np.testing.assert_array_equal(result.records["pdv"].time_s, [0.0, 1.0, 3.0])
    assert result.records["pdv"].is_uniformly_sampled is False


def test_relative_opaque_path_is_preserved_and_source_bytes_are_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = _write_text_file(tmp_path, "0,1\n1,2\n", name="signal.opaque")
    before = path.read_bytes()
    monkeypatch.chdir(tmp_path)

    result = read_delimited_signals(
        Path("signal.opaque"),
        time_column=0,
        voltage_columns={"pdv": 1},
    )

    assert result.source_path == Path("signal.opaque")
    assert result.source_path.is_absolute() is False
    assert path.read_bytes() == before


def test_malformed_csv_preserves_csv_error_chain(tmp_path: Path) -> None:
    path = _write_text_file(tmp_path, '"0,1\n1,2\n')

    with pytest.raises(SignalParseError, match=r"physical line 2") as error_info:
        read_delimited_signals(path, time_column=0, voltage_columns={"pdv": 1})

    assert error_info.value.__cause__ is not None


def test_public_io_imports_expose_stable_types() -> None:
    assert DelimitedSignalLoadResult.__module__ == "dps_studio.core.io.models"
    assert read_delimited_signals.__module__ == "dps_studio.core.io.delimited"
    assert SignalRecord.__module__ == "dps_studio.core.models.signal"
