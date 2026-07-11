"""Strict reader for explicitly configured delimited signal files."""

from __future__ import annotations

import codecs
import csv
import math
from collections.abc import Iterator, Mapping
from numbers import Integral, Real
from os import PathLike
from pathlib import Path
from typing import TextIO

from dps_studio.core.io.exceptions import (
    SignalColumnError,
    SignalConfigurationError,
    SignalEncodingError,
    SignalFileNotFoundError,
    SignalFileTypeError,
    SignalIOError,
    SignalParseError,
)
from dps_studio.core.io.models import DelimitedSignalLoadResult
from dps_studio.core.models import SignalRecord, SignalValidationError


def read_delimited_signals(
    path: str | PathLike[str],
    *,
    time_column: int,
    voltage_columns: Mapping[str, int],
    delimiter: str = ",",
    has_header: bool = False,
    encoding: str = "utf-8",
    time_scale: float = 1.0,
    voltage_scales: Mapping[str, float] | None = None,
) -> DelimitedSignalLoadResult:
    """Load explicitly selected time and voltage columns into signal records.

    Column indices are zero based. Only selected columns are interpreted as
    numeric data, but every field must be non-empty and every data record must
    have the same number of columns.
    """
    source_path = _normalize_path(path)
    validated_time_column = _validate_column_index(time_column, name="time_column")
    validated_voltage_columns = _validate_voltage_columns(voltage_columns)
    _validate_distinct_columns(validated_time_column, validated_voltage_columns)
    validated_delimiter = _validate_delimiter(delimiter)
    validated_has_header = _validate_has_header(has_header)
    validated_encoding = _validate_encoding(encoding)
    validated_time_scale = _validate_scale(
        time_scale,
        name="time_scale",
        allow_negative=False,
    )
    validated_voltage_scales = _validate_voltage_scales(
        voltage_scales,
        channel_names=tuple(validated_voltage_columns),
    )

    _validate_source_file(source_path)
    try:
        with source_path.open(
            mode="r",
            encoding=validated_encoding,
            newline="",
        ) as handle:
            return _read_open_file(
                handle,
                source_path=source_path,
                time_column=validated_time_column,
                voltage_columns=validated_voltage_columns,
                delimiter=validated_delimiter,
                has_header=validated_has_header,
                encoding=validated_encoding,
                time_scale=validated_time_scale,
                voltage_scales=validated_voltage_scales,
            )
    except UnicodeError as exc:
        raise SignalEncodingError(
            f"Could not decode signal file {source_path!s} using encoding "
            f"{validated_encoding!r}."
        ) from exc
    except FileNotFoundError as exc:
        raise SignalFileNotFoundError(
            f"Signal file does not exist: {source_path!s}."
        ) from exc
    except OSError as exc:
        raise SignalIOError(f"Could not read signal file {source_path!s}.") from exc


def _normalize_path(path: str | PathLike[str]) -> Path:
    try:
        return Path(path)
    except (TypeError, ValueError) as exc:
        raise SignalConfigurationError(
            "path must be a string or os.PathLike object."
        ) from exc


def _validate_column_index(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise SignalConfigurationError(
            f"{name} must be a non-negative integer and cannot be bool; got {value!r}."
        )
    return int(value)


def _validate_voltage_columns(value: object) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise SignalConfigurationError("voltage_columns must be a non-empty mapping.")
    if not value:
        raise SignalConfigurationError("voltage_columns must not be empty.")

    validated: dict[str, int] = {}
    for channel_name, column_index in value.items():
        if not isinstance(channel_name, str) or not channel_name.strip():
            raise SignalConfigurationError(
                "Every voltage channel name must be a non-empty string; "
                f"got {channel_name!r}."
            )
        validated[channel_name] = _validate_column_index(
            column_index,
            name=f"voltage column for channel {channel_name!r}",
        )
    return validated


def _validate_distinct_columns(
    time_column: int,
    voltage_columns: Mapping[str, int],
) -> None:
    selected_voltage_indices = list(voltage_columns.values())
    if time_column in selected_voltage_indices:
        raise SignalConfigurationError(
            f"time_column {time_column} cannot also be selected as a voltage column."
        )
    if len(set(selected_voltage_indices)) != len(selected_voltage_indices):
        raise SignalConfigurationError(
            "Each voltage channel must select a distinct source column."
        )


def _validate_delimiter(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 1
        or value in {"\r", "\n"}
    ):
        raise SignalConfigurationError(
            "delimiter must be one character and cannot be a newline or carriage return; "
            f"got {value!r}."
        )
    return value


def _validate_has_header(value: object) -> bool:
    if not isinstance(value, bool):
        raise SignalConfigurationError(
            f"has_header must be bool; got {value!r}."
        )
    return value


def _validate_encoding(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise SignalConfigurationError(
            f"encoding must be a non-empty string; got {value!r}."
        )
    try:
        codecs.lookup(value)
    except LookupError as exc:
        raise SignalConfigurationError(f"Unknown text encoding {value!r}.") from exc
    return value


def _validate_scale(value: object, *, name: str, allow_negative: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SignalConfigurationError(
            f"{name} must be a real number and cannot be bool; got {value!r}."
        )
    try:
        scale = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SignalConfigurationError(
            f"{name} could not be converted to a finite float."
        ) from exc
    if not math.isfinite(scale):
        raise SignalConfigurationError(f"{name} must be finite; got {scale!r}.")
    if allow_negative:
        if scale == 0.0:
            raise SignalConfigurationError(f"{name} must be non-zero.")
    elif scale <= 0.0:
        raise SignalConfigurationError(f"{name} must be strictly positive.")
    return scale


def _validate_voltage_scales(
    value: object,
    *,
    channel_names: tuple[str, ...],
) -> dict[str, float]:
    if value is None:
        return dict.fromkeys(channel_names, 1.0)
    if not isinstance(value, Mapping):
        raise SignalConfigurationError("voltage_scales must be a mapping or None.")

    expected_names = set(channel_names)
    actual_names = set(value)
    if actual_names != expected_names:
        missing = tuple(name for name in channel_names if name not in actual_names)
        extra = tuple(name for name in actual_names if name not in expected_names)
        raise SignalConfigurationError(
            "voltage_scales keys must exactly match voltage_columns keys; "
            f"missing={missing!r}, extra={extra!r}."
        )

    return {
        channel_name: _validate_scale(
            value[channel_name],
            name=f"voltage scale for channel {channel_name!r}",
            allow_negative=True,
        )
        for channel_name in channel_names
    }


def _validate_source_file(source_path: Path) -> None:
    if not source_path.exists():
        raise SignalFileNotFoundError(
            f"Signal file does not exist: {source_path!s}."
        )
    if not source_path.is_file():
        raise SignalFileTypeError(
            f"Signal path is not a regular file: {source_path!s}."
        )


def _read_open_file(
    handle: TextIO,
    *,
    source_path: Path,
    time_column: int,
    voltage_columns: Mapping[str, int],
    delimiter: str,
    has_header: bool,
    encoding: str,
    time_scale: float,
    voltage_scales: Mapping[str, float],
) -> DelimitedSignalLoadResult:
    reader = csv.reader(
        handle,
        delimiter=delimiter,
        skipinitialspace=delimiter != " ",
        strict=True,
    )
    try:
        return _parse_records(
            reader,
            source_path=source_path,
            time_column=time_column,
            voltage_columns=voltage_columns,
            delimiter=delimiter,
            has_header=has_header,
            encoding=encoding,
            time_scale=time_scale,
            voltage_scales=voltage_scales,
        )
    except csv.Error as exc:
        raise SignalParseError(
            f"Invalid CSV structure in {source_path!s} at physical line "
            f"{reader.line_num}: {exc}."
        ) from exc


def _parse_records(
    reader: Iterator[list[str]],
    *,
    source_path: Path,
    time_column: int,
    voltage_columns: Mapping[str, int],
    delimiter: str,
    has_header: bool,
    encoding: str,
    time_scale: float,
    voltage_scales: Mapping[str, float],
) -> DelimitedSignalLoadResult:
    header: tuple[str, ...] | None = None
    if has_header:
        header_row = next(reader, None)
        if header_row is None:
            raise SignalParseError(f"Signal file {source_path!s} is empty.")
        header = tuple(field.strip() for field in header_row)

    first_data_row = next(reader, None)
    if first_data_row is None:
        detail = " contains a header but no data records" if has_header else " is empty"
        raise SignalParseError(f"Signal file {source_path!s}{detail}.")

    column_count = len(first_data_row)
    first_data_line = _reader_line_number(reader)
    if column_count == 0:
        raise SignalParseError(
            f"Signal file {source_path!s} has an empty data record at physical line "
            f"{first_data_line}."
        )
    if header is not None and len(header) != column_count:
        raise SignalColumnError(
            f"Header in {source_path!s} has {len(header)} columns, but the first data "
            f"record at physical line {first_data_line} has {column_count}."
        )

    _validate_requested_columns_exist(
        source_path=source_path,
        column_count=column_count,
        time_column=time_column,
        voltage_columns=voltage_columns,
    )

    time_values: list[float] = []
    voltage_values: dict[str, list[float]] = {
        channel_name: [] for channel_name in voltage_columns
    }
    _parse_data_row(
        first_data_row,
        physical_line=first_data_line,
        source_path=source_path,
        time_column=time_column,
        voltage_columns=voltage_columns,
        time_scale=time_scale,
        voltage_scales=voltage_scales,
        time_values=time_values,
        voltage_values=voltage_values,
    )

    for row in reader:
        physical_line = _reader_line_number(reader)
        if len(row) != column_count:
            raise SignalColumnError(
                f"Inconsistent column count in {source_path!s} at physical line "
                f"{physical_line}: expected {column_count}, got {len(row)}."
            )
        _parse_data_row(
            row,
            physical_line=physical_line,
            source_path=source_path,
            time_column=time_column,
            voltage_columns=voltage_columns,
            time_scale=time_scale,
            voltage_scales=voltage_scales,
            time_values=time_values,
            voltage_values=voltage_values,
        )

    records = _build_signal_records(
        source_path=source_path,
        time_column=time_column,
        voltage_columns=voltage_columns,
        time_scale=time_scale,
        voltage_scales=voltage_scales,
        time_values=time_values,
        voltage_values=voltage_values,
    )
    selected_columns = {time_column, *voltage_columns.values()}
    unselected_columns = tuple(
        index for index in range(column_count) if index not in selected_columns
    )
    return DelimitedSignalLoadResult(
        source_path=source_path,
        records=records,
        row_count=len(time_values),
        column_count=column_count,
        channel_names=tuple(voltage_columns),
        header=header,
        time_column_index=time_column,
        voltage_column_indices=voltage_columns,
        unselected_column_indices=unselected_columns,
        delimiter=delimiter,
        encoding=encoding,
    )


def _reader_line_number(reader: Iterator[list[str]]) -> int:
    line_number = getattr(reader, "line_num", None)
    if isinstance(line_number, int):
        return line_number
    raise RuntimeError("csv.reader did not expose a physical line number")


def _validate_requested_columns_exist(
    *,
    source_path: Path,
    column_count: int,
    time_column: int,
    voltage_columns: Mapping[str, int],
) -> None:
    if time_column >= column_count:
        raise SignalColumnError(
            f"Requested time column {time_column} does not exist in {source_path!s}; "
            f"data records have {column_count} columns."
        )
    for channel_name, column_index in voltage_columns.items():
        if column_index >= column_count:
            raise SignalColumnError(
                f"Requested voltage column {column_index} for channel "
                f"{channel_name!r} does not exist in {source_path!s}; data records "
                f"have {column_count} columns."
            )


def _parse_data_row(
    row: list[str],
    *,
    physical_line: int,
    source_path: Path,
    time_column: int,
    voltage_columns: Mapping[str, int],
    time_scale: float,
    voltage_scales: Mapping[str, float],
    time_values: list[float],
    voltage_values: dict[str, list[float]],
) -> None:
    stripped_row = tuple(field.strip() for field in row)
    channel_by_column = {
        column_index: channel_name
        for channel_name, column_index in voltage_columns.items()
    }
    for column_index, (raw_field, stripped_field) in enumerate(zip(row, stripped_row)):
        if not stripped_field:
            channel_name = channel_by_column.get(column_index)
            channel_context = (
                f" for channel {channel_name!r}" if channel_name is not None else ""
            )
            raise SignalParseError(
                f"Empty field in {source_path!s} at physical line {physical_line}, "
                f"zero-based column {column_index}{channel_context}; "
                f"original field {raw_field!r}."
            )

    time_values.append(
        _parse_numeric_field(
            row[time_column],
            physical_line=physical_line,
            source_path=source_path,
            column_index=time_column,
            channel_name=None,
        )
        * time_scale
    )
    for channel_name, column_index in voltage_columns.items():
        voltage_values[channel_name].append(
            _parse_numeric_field(
                row[column_index],
                physical_line=physical_line,
                source_path=source_path,
                column_index=column_index,
                channel_name=channel_name,
            )
            * voltage_scales[channel_name]
        )


def _parse_numeric_field(
    raw_field: str,
    *,
    physical_line: int,
    source_path: Path,
    column_index: int,
    channel_name: str | None,
) -> float:
    try:
        return float(raw_field.strip())
    except (ValueError, OverflowError) as exc:
        channel_context = (
            f" for channel {channel_name!r}" if channel_name is not None else ""
        )
        raise SignalParseError(
            f"Non-numeric field in {source_path!s} at physical line {physical_line}, "
            f"zero-based column {column_index}{channel_context}; "
            f"original field {raw_field!r}."
        ) from exc


def _build_signal_records(
    *,
    source_path: Path,
    time_column: int,
    voltage_columns: Mapping[str, int],
    time_scale: float,
    voltage_scales: Mapping[str, float],
    time_values: list[float],
    voltage_values: Mapping[str, list[float]],
) -> dict[str, SignalRecord]:
    records: dict[str, SignalRecord] = {}
    for channel_name, voltage_column in voltage_columns.items():
        try:
            records[channel_name] = SignalRecord(
                time_values,
                voltage_values[channel_name],
                source_path=source_path,
                metadata={
                    "channel_name": channel_name,
                    "time_column_index": time_column,
                    "voltage_column_index": voltage_column,
                    "time_scale": time_scale,
                    "voltage_scale": voltage_scales[channel_name],
                },
            )
        except SignalValidationError as exc:
            exc.add_note(
                f"Loaded from {source_path!s}; channel {channel_name!r}; "
                f"time column {time_column}; voltage column {voltage_column}."
            )
            raise
    return records
