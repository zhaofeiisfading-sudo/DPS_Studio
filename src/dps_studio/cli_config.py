"""Explicit experimental input and analysis settings for the headless CLI."""

from __future__ import annotations

import json
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from dps_studio.core.analysis_profiles import AnalysisParameterOverrides
from dps_studio.core.physics.models import (
    LIF_RIGG_2014_1550NM,
    VelocityCorrectionConfig,
    WindowMaterial,
)
from dps_studio.core.physics.window_presets import WindowPresetRepository
from dps_studio.runtime_paths import window_preset_file_path

TIME_SCALES = {"s": 1.0, "ms": 1e-3, "us": 1e-6, "ns": 1e-9, "ps": 1e-12}
VOLTAGE_SCALES = {"V": 1.0, "mV": 1e-3}
REQUIRED_EXPERIMENT_PARAMETERS = (
    "time_column", "time_unit", "voltage_columns", "voltage_units",
    "vacuum_wavelength_m", "measurement_angle_deg", "window_material",
)
OPTIONAL_ANALYSIS_PARAMETERS = (
    "auto_columns", "auto_band_retry", "full_diagnostics", "pre_event_display",
    "time_origin", "delimiter", "encoding", "has_header", "profile",
    "analysis_start_time_s", "analysis_end_time_s", "minimum_frequency_hz",
    "maximum_frequency_hz", "window_length_samples", "overlap_samples", "nfft",
    "window_name", "event_reference_time_s", "include_acceleration",
    "acceleration_fit_window_s",
)
LIF_FIELDS = ("lif_b1", "lif_b2", "lif_reference_wavelength_m")


@dataclass(frozen=True, slots=True)
class Experiment:
    time_column: int
    time_unit: str
    voltage_columns: dict[str, int]
    voltage_units: dict[str, str]
    vacuum_wavelength_m: float
    window_material: str
    correction: VelocityCorrectionConfig


def read_config(path: Path | None) -> dict[str, object]:
    if path is None:
        return {}
    try:
        match path.suffix.lower():
            case ".json":
                document = json.loads(path.read_text(encoding="utf-8-sig"))
            case ".toml":
                with path.open("rb") as handle:
                    document = tomllib.load(handle)
            case _:
                raise ValueError("expected a .json or .toml configuration")
        if not isinstance(document, dict):
            raise ValueError("expected a configuration object")
        return dict(document)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot load configuration {path}: {exc}") from exc


def read_experiment(config: Mapping[str, object]) -> Experiment:
    missing = [name for name in REQUIRED_EXPERIMENT_PARAMETERS if config.get(name) is None]
    if "measurement_angle_deg" in missing and config.get("measurement_angle_rad") is not None:
        missing.remove("measurement_angle_deg")
    if missing:
        raise ValueError(f"Missing required experimental parameters: {', '.join(missing)}.")

    time_column = _column(config["time_column"], "time_column")
    time_unit = _unit(config["time_unit"], TIME_SCALES, "time_unit")
    columns = _voltage_columns(config["voltage_columns"])
    units = _voltage_units(config["voltage_units"], columns)
    wavelength = _finite(config["vacuum_wavelength_m"], "vacuum_wavelength_m")
    if wavelength <= 0:
        raise ValueError("vacuum_wavelength_m must be positive.")

    degrees = optional_number(config, "measurement_angle_deg")
    radians = optional_number(config, "measurement_angle_rad")
    if degrees is not None and radians is not None:
        raise ValueError("Specify either measurement_angle_deg or measurement_angle_rad.")
    angle = math.radians(degrees) if degrees is not None else radians
    assert angle is not None
    window_name = _text(config["window_material"], "window_material")
    if window_name.casefold() in {"lif", "none"}:
        window_name = "LiF" if window_name.casefold() == "lif" else "none"
    return Experiment(
        time_column, time_unit, columns, units, wavelength, window_name,
        _correction(config, window_name, angle),
    )


def analysis_overrides(config: Mapping[str, object]) -> AnalysisParameterOverrides:
    return AnalysisParameterOverrides(
        window_length_samples=_optional_integer(config, "window_length_samples", "window_length"),
        overlap_samples=_optional_integer(config, "overlap_samples", "overlap"),
        nfft=_optional_integer(config, "nfft"),
        window_name=optional_text(config, "window_name"),
        minimum_frequency_hz=optional_number(config, "minimum_frequency_hz"),
        maximum_frequency_hz=optional_number(config, "maximum_frequency_hz"),
    )


def optional_text(config: Mapping[str, object], key: str) -> str | None:
    value = config.get(key)
    return None if value is None else _text(value, key)


def optional_number(config: Mapping[str, object], key: str) -> float | None:
    value = config.get(key)
    return None if value is None else _finite(value, key)


def optional_bool(config: Mapping[str, object], key: str) -> bool | None:
    value = config.get(key)
    if value is not None and not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean.")
    return value


def delimiter_value(value: str | None) -> str | None:
    if value in {r"\t", "tab"}:
        return "\t"
    return value


def _text(value: object, key: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be non-empty text.")
    return value.strip()


def _finite(value: object, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a finite number.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{key} must be a finite number.")
    return number


def _optional_integer(config: Mapping[str, object], key: str, alias: str = "") -> int | None:
    value = config.get(key, config.get(alias))
    if value is None:
        return None
    return _column(value, key)


def _column(value: object, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer.")
    return value


def _unit(value: object, scales: Mapping[str, float], key: str) -> str:
    if not isinstance(value, str) or value not in scales:
        raise ValueError(f"{key} must be one of {', '.join(scales)}.")
    return value


def _pairs(value: str, key: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in value.split(","):
        name, separator, entry = item.partition("=")
        name = name.strip()
        if not separator or not name or not entry.strip() or name in pairs:
            raise ValueError(f"{key} expects unique channel=value pairs separated by commas.")
        pairs[name] = entry.strip()
    return pairs


def _voltage_columns(value: object) -> dict[str, int]:
    if isinstance(value, str):
        try:
            value = (
                {name: int(column) for name, column in _pairs(value, "voltage_columns").items()}
                if "=" in value else int(value)
            )
        except ValueError as exc:
            raise ValueError("voltage_columns expects a column index or channel=index pairs.") from exc
    if isinstance(value, int):
        value = {"pdv_channel_1": value}
    if not isinstance(value, dict) or not value:
        raise ValueError("voltage_columns must identify at least one channel and column.")
    columns: dict[str, int] = {}
    for name, index in value.items():
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Voltage channel names must be non-empty text.")
        columns[name] = _column(index, f"voltage_columns[{name!r}]")
    if len({name.casefold() for name in columns}) != len(columns):
        raise ValueError("Voltage channel names must be distinct ignoring case.")
    return columns


def _voltage_units(value: object, columns: Mapping[str, int]) -> dict[str, str]:
    if isinstance(value, str) and "=" in value:
        value = _pairs(value, "voltage_units")
    if isinstance(value, str):
        unit = _unit(value, VOLTAGE_SCALES, "voltage_units")
        return dict.fromkeys(columns, unit)
    if not isinstance(value, dict) or value.keys() != columns.keys():
        raise ValueError("voltage_units must specify a unit for every selected channel.")
    return {name: _unit(value[name], VOLTAGE_SCALES, f"voltage_units[{name!r}]") for name in columns}


def _correction(config: Mapping[str, object], name: str, angle: float) -> VelocityCorrectionConfig:
    if name == "none":
        return VelocityCorrectionConfig(window_material=WindowMaterial.NONE, measurement_angle_rad=angle)
    b1, b2, reference = (optional_number(config, key) for key in LIF_FIELDS)
    model = LIF_RIGG_2014_1550NM
    if any(value is not None for value in (b1, b2, reference)):
        if b1 is None or b2 is None or reference is None:
            raise ValueError(f"Explicit window coefficients require {', '.join(LIF_FIELDS)}.")
        model = replace(
            model, b1=b1, b2=b2, reference_wavelength_m=reference,
            configuration_name=name,
        )
    elif name != "LiF":
        presets = WindowPresetRepository(window_preset_file_path()).load()
        by_name = {key.casefold(): preset for key, preset in presets.items()}
        if name.casefold() not in by_name:
            raise ValueError(f"Unknown window preset {name!r}. Select LiF, none, or a saved preset.")
        model = by_name[name.casefold()]
    return VelocityCorrectionConfig(
        window_material=WindowMaterial.LIF, measurement_angle_rad=angle, lif_model=model,
    )
