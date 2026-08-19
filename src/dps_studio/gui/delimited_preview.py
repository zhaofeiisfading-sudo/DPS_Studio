"""Bounded structural preview for the GUI delimited-file import dialog."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from itertools import islice
from pathlib import Path


_PREVIEW_SAMPLE_CHARACTERS = 32_768
_CANDIDATE_DELIMITERS = ",;\t|"


@dataclass(frozen=True, slots=True)
class DelimitedFilePreview:
    """A small, non-scientific sample used only to configure an import."""

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
    """Inspect only an initial file sample without replacing the strict reader."""
    if delimiter is not None and len(delimiter) != 1:
        raise DelimitedPreviewError("Delimiter must be exactly one character.")
    if max_data_rows < 1:
        raise ValueError("max_data_rows must be positive.")

    try:
        with Path(path).open("r", encoding=encoding, newline="") as handle:
            sample = handle.read(_PREVIEW_SAMPLE_CHARACTERS)
            if not sample:
                raise DelimitedPreviewError("The selected file is empty.")
            selected_delimiter = delimiter or _detect_delimiter(sample)
            handle.seek(0)
            records = tuple(
                tuple(field.strip() for field in record)
                for record in islice(
                    csv.reader(handle, delimiter=selected_delimiter, strict=True),
                    max_data_rows + 1,
                )
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

    has_header = _tentative_header(sample)
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


def _detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(
            sample,
            delimiters=_CANDIDATE_DELIMITERS,
        ).delimiter
    except csv.Error as exc:
        raise DelimitedPreviewError(
            "Could not detect a comma, semicolon, tab, or pipe delimiter."
        ) from exc


def _tentative_header(sample: str) -> bool:
    try:
        return csv.Sniffer().has_header(sample)
    except csv.Error:
        return False


__all__ = [
    "DelimitedFilePreview",
    "DelimitedPreviewError",
    "preview_delimited_file",
]
