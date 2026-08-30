"""Bounded structural preview using the production delimiter contract."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from itertools import islice
from pathlib import Path

from dps_studio.core.io.delimiter import (
    WHITESPACE_DELIMITER,
    create_delimited_row_reader,
)


_PREVIEW_SAMPLE_CHARACTERS = 32_768
_CANDIDATE_EXPLICIT_DELIMITERS = ",;|"


@dataclass(frozen=True, slots=True)
class DelimitedFilePreview:
    """A bounded structural sample used to configure signal import."""

    column_count: int
    delimiter: str
    encoding: str
    has_header: bool
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


class DelimitedPreviewError(ValueError):
    """Raised when a bounded structural preview cannot be produced."""


def preview_delimited_file(
    path: Path,
    *,
    delimiter: str | None = None,
    encoding: str = "utf-8",
    max_data_rows: int = 4,
) -> DelimitedFilePreview:
    """Inspect an initial sample with the production reader's delimiter semantics.

    ``None`` requests automatic detection. ``WHITESPACE_DELIMITER`` collapses
    runs of Unicode whitespace exactly as the formal reader does.
    """
    _validate_preview_delimiter(delimiter)
    if max_data_rows < 1:
        raise ValueError("max_data_rows must be positive.")

    try:
        with Path(path).open("r", encoding=encoding, newline="") as handle:
            sample = handle.read(_PREVIEW_SAMPLE_CHARACTERS)
            if not sample:
                raise DelimitedPreviewError("The selected file is empty.")
            selected_delimiter = delimiter or detect_delimiter(sample)
            handle.seek(0)
            reader = create_delimited_row_reader(
                handle,
                delimiter=selected_delimiter,
            )
            records = tuple(
                tuple(field.strip() for field in record)
                for record in islice(reader, max_data_rows + 1)
            )
    except (OSError, UnicodeError, csv.Error) as exc:
        raise DelimitedPreviewError(str(exc)) from exc

    if not records or not records[0]:
        raise DelimitedPreviewError("No delimited columns were found.")
    column_count = len(records[0])
    if any(len(record) != column_count for record in records):
        raise DelimitedPreviewError(
            "Preview rows do not have a consistent number of columns."
        )

    has_header = _tentative_header(records)
    header = records[0] if has_header else ()
    data_start = 1 if has_header else 0
    return DelimitedFilePreview(
        column_count=column_count,
        delimiter=selected_delimiter,
        encoding=encoding,
        has_header=has_header,
        header=header,
        rows=records[data_start : data_start + max_data_rows],
    )


def detect_delimiter(sample: str) -> str:
    """Detect an explicit delimiter or the shared whitespace mode."""
    try:
        return csv.Sniffer().sniff(
            sample,
            delimiters=_CANDIDATE_EXPLICIT_DELIMITERS,
        ).delimiter
    except csv.Error as explicit_error:
        if _has_consistent_tab_columns(sample):
            return "\t"
        if _has_consistent_whitespace_columns(sample):
            return WHITESPACE_DELIMITER
        raise DelimitedPreviewError(
            "Could not detect a comma, semicolon, tab, pipe, or whitespace delimiter."
        ) from explicit_error


def _validate_preview_delimiter(delimiter: str | None) -> None:
    if delimiter is None or delimiter == WHITESPACE_DELIMITER:
        return
    if len(delimiter) != 1 or delimiter in {"\r", "\n"}:
        raise DelimitedPreviewError(
            "Delimiter must be exactly one character or the whitespace mode."
        )


def _has_consistent_whitespace_columns(sample: str) -> bool:
    records = [line.split() for line in sample.splitlines() if line.strip()]
    if not records:
        return False
    column_count = len(records[0])
    return column_count > 1 and all(len(record) == column_count for record in records)


def _has_consistent_tab_columns(sample: str) -> bool:
    lines = [line for line in sample.splitlines() if line.strip()]
    if not lines or any(any(character.isspace() and character != "\t" for character in line) for line in lines):
        return False
    records = [line.split("\t") for line in lines]
    column_count = len(records[0])
    return (
        column_count > 1
        and all(len(record) == column_count for record in records)
        and all(all(field for field in record) for record in records)
    )


def _tentative_header(records: tuple[tuple[str, ...], ...]) -> bool:
    normalized_handle = StringIO(newline="")
    csv.writer(normalized_handle).writerows(records)
    try:
        return csv.Sniffer().has_header(normalized_handle.getvalue())
    except csv.Error:
        return False


__all__ = [
    "DelimitedFilePreview",
    "DelimitedPreviewError",
    "detect_delimiter",
    "preview_delimited_file",
]
