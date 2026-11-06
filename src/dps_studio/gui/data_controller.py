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
    original_voltage_unit: str | None = None


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
    original_time_unit: str | None = None


class DataImportController:
    """Load immutable core records without adding parsing logic to the GUI."""

    def load(self, request: SignalLoadRequest) -> DelimitedSignalLoadResult:
        """Call the public reader with explicit units and column mappings."""
        if not isinstance(request, SignalLoadRequest):
            raise TypeError("request must be a SignalLoadRequest.")
        if not request.channels:
            raise ValueError("At least one voltage channel must be configured.")
        if len(request.channels) > 3:
            raise ValueError("The GUI import supports at most three voltage channels.")
        names = tuple(channel.name.strip() for channel in request.channels)
        if any(not name for name in names):
            raise ValueError("Voltage channel names must not be empty.")
        if len(set(names)) != len(names):
            raise ValueError("Voltage channel names must be unique.")
        columns = tuple(channel.column_index for channel in request.channels)
        if request.time_column < 0 or any(column < 0 for column in columns):
            raise ValueError("Column indices must be non-negative.")
        if request.time_column in columns:
            raise ValueError("The time column cannot also be a voltage column.")
        if len(set(columns)) != len(columns):
            raise ValueError("Voltage column indices must be unique.")
        voltage_columns = {
            name: channel.column_index
            for name, channel in zip(names, request.channels, strict=True)
        }
        voltage_scales = {
            name: channel.voltage_scale
            for name, channel in zip(names, request.channels, strict=True)
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
            original_time_unit=request.original_time_unit,
            original_voltage_units={
                name: channel.original_voltage_unit
                for name, channel in zip(names, request.channels, strict=True)
                if channel.original_voltage_unit is not None
            },
        )


__all__ = [
    "ChannelImportSpec",
    "DataImportController",
    "SignalLoadRequest",
]
