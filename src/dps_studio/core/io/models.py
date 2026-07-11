"""Immutable file-level results for signal input."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from dps_studio.core.models import SignalRecord


@dataclass(frozen=True, slots=True, eq=False)
class DelimitedSignalLoadResult:
    """Signals and structural metadata loaded from one delimited text file."""

    source_path: Path
    records: Mapping[str, SignalRecord]
    row_count: int
    column_count: int
    channel_names: tuple[str, ...]
    header: tuple[str, ...] | None
    time_column_index: int
    voltage_column_indices: Mapping[str, int]
    unselected_column_indices: tuple[int, ...]
    delimiter: str
    encoding: str

    def __post_init__(self) -> None:
        """Detach public mappings from mutable caller-owned mappings."""
        object.__setattr__(self, "records", MappingProxyType(dict(self.records)))
        object.__setattr__(
            self,
            "voltage_column_indices",
            MappingProxyType(dict(self.voltage_column_indices)),
        )
