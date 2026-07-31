"""Adapter between file-import controls and the public core reader."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dps_studio.core.io import DelimitedSignalLoadResult, read_delimited_signals


@dataclass(frozen=True, slots=True)
class ChannelImportSpec:
    """Explicit source column and SI conversion for one voltage channel."""

    name: str
    column_index: int
    voltage_scale: float


@dataclass(frozen=True, slots=True)
class SignalLoadRequest:
    """All explicit inputs required by :func:`read_delimited_signals`."""

    path: Path
    time_column: int
    channels: tuple[ChannelImportSpec, ...]
    delimiter: str
    has_header: bool
    encoding: str
    time_scale: float


class DataImportController:
    """Load immutable core records without adding parsing logic to the GUI."""

    def load(self, request: SignalLoadRequest) -> DelimitedSignalLoadResult:
        """Call the public reader with explicit units and column mappings."""
        if not isinstance(request, SignalLoadRequest):
            raise TypeError("request must be a SignalLoadRequest.")
        if not request.channels:
            raise ValueError("At least one voltage channel must be configured.")
        voltage_columns = {
            channel.name: channel.column_index for channel in request.channels
        }
        voltage_scales = {
            channel.name: channel.voltage_scale for channel in request.channels
        }
        return read_delimited_signals(
            request.path,
            time_column=request.time_column,
            voltage_columns=voltage_columns,
            delimiter=request.delimiter,
            has_header=request.has_header,
            encoding=request.encoding,
            time_scale=request.time_scale,
            voltage_scales=voltage_scales,
        )


__all__ = [
    "ChannelImportSpec",
    "DataImportController",
    "SignalLoadRequest",
]
