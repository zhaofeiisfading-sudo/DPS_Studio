"""Shared delimiter semantics for signal-file readers and previews."""

from __future__ import annotations

import csv
from typing import Protocol, TextIO, cast


WHITESPACE_DELIMITER = "whitespace"
"""Delimiter mode that collapses one or more Unicode whitespace characters."""


class DelimitedRowReader(Protocol):
    """Iterator contract shared by CSV and whitespace row readers."""

    line_num: int

    def __iter__(self) -> DelimitedRowReader:
        """Return the row reader iterator."""
        ...

    def __next__(self) -> list[str]:
        """Return the next tokenized record."""
        ...


class _WhitespaceRowReader:
    """Split each physical line on runs of Unicode whitespace."""

    __slots__ = ("_handle", "line_num")

    def __init__(self, handle: TextIO) -> None:
        self._handle = handle
        self.line_num = 0

    def __iter__(self) -> _WhitespaceRowReader:
        return self

    def __next__(self) -> list[str]:
        line = next(self._handle)
        self.line_num += 1
        return line.split()


def create_delimited_row_reader(
    handle: TextIO,
    *,
    delimiter: str,
) -> DelimitedRowReader:
    """Create a reader using the shared explicit or whitespace delimiter contract."""
    if delimiter == WHITESPACE_DELIMITER:
        return _WhitespaceRowReader(handle)
    return cast(
        DelimitedRowReader,
        csv.reader(
            handle,
            delimiter=delimiter,
            skipinitialspace=delimiter != " ",
            strict=True,
        ),
    )


__all__ = [
    "DelimitedRowReader",
    "WHITESPACE_DELIMITER",
    "create_delimited_row_reader",
]
