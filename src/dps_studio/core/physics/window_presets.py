"""Named user coefficient sets for the existing fixed window formula."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from dps_studio.core.physics.models import LIF_RIGG_2014_1550NM, LiFWindowCorrectionModel
from dps_studio.core.physics.exceptions import VelocityConfigurationError


BUILTIN_NAME = "LiF"
PARAMETER_UNITS = {
    "b1": "dimensionless coefficient with velocity normalized to 1 km/s",
    "b2": "dimensionless",
    "reference_wavelength_m": "m",
    "input_velocity": "m/s",
    "output_velocity": "m/s",
    "formula_velocity_unit": "km/s",
}


def is_builtin_window(model: LiFWindowCorrectionModel) -> bool:
    return model == LIF_RIGG_2014_1550NM


def window_configuration_name(model: LiFWindowCorrectionModel) -> str:
    return model.configuration_name or (BUILTIN_NAME if is_builtin_window(model) else "自定义配置")


class WindowPresetError(ValueError):
    """Invalid, unreadable or unwritable preset library; no silent reset."""


class WindowPresetRepository:
    """Atomic local persistence; read failures prohibit overwriting damaged data."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, LiFWindowCorrectionModel]:
        try:
            if not self.path.exists():
                return {}
            document = json.loads(self.path.read_text(encoding="utf-8"))
            if document["schema_version"] != 1 or document["units"] != PARAMETER_UNITS:
                raise ValueError("Unsupported schema or parameter units")
            entries = document["presets"]
            if not isinstance(entries, list):
                raise ValueError("presets must be a list")
            presets: dict[str, LiFWindowCorrectionModel] = {}
            for entry in entries:
                model = LiFWindowCorrectionModel(**entry)
                name = self._name(model.configuration_name)
                if name.casefold() in {item.casefold() for item in presets}:
                    raise ValueError("Duplicate preset name")
                self._validate_formula(model)
                presets[name] = model
            return presets
        except (OSError, ValueError, TypeError, KeyError, VelocityConfigurationError) as exc:
            raise WindowPresetError(f"Cannot read window presets {self.path}: {exc}") from exc

    def next_name(self) -> str:
        existing = {name.casefold() for name in self.load()}
        index = 1
        while f"新材料{index}".casefold() in existing:
            index += 1
        return f"新材料{index}"

    def save(self, model: LiFWindowCorrectionModel, *, original_name: str | None = None) -> None:
        """Explicitly save edits/rename of one entry or create a new entry.

        A different existing entry can never be overwritten through a rename.
        The built-in preset is never part of this file.
        """
        name = self._name(model.configuration_name)
        self._validate_formula(model)
        entries = self.load()
        if original_name is not None and original_name not in entries:
            raise WindowPresetError("Original preset no longer exists; reload before saving.")
        if any(key.casefold() == name.casefold() and key != original_name for key in entries):
            raise WindowPresetError(f"Preset name already exists: {name}")
        if original_name is not None:
            entries.pop(original_name)
        entries[name] = model
        self._write(entries)

    @staticmethod
    def _name(value: object) -> str:
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise WindowPresetError("Preset name must be non-empty text without outer whitespace.")
        if value.casefold() == BUILTIN_NAME.casefold() or any(ord(char) < 32 for char in value):
            raise WindowPresetError("Preset name is reserved or contains control characters.")
        return value

    @staticmethod
    def _validate_formula(model: LiFWindowCorrectionModel) -> None:
        if model.model != LIF_RIGG_2014_1550NM.model or model.paper_velocity_unit != "km/s":
            raise WindowPresetError("Only the existing Rigg2014_Eq16 coefficient form is supported.")

    def _write(self, entries: dict[str, LiFWindowCorrectionModel]) -> None:
        document: dict[str, Any] = {
            "schema_version": 1,
            "units": PARAMETER_UNITS,
            "presets": [asdict(model) for model in entries.values()],
        }
        temporary: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                json.dump(document, handle, ensure_ascii=False, indent=2, allow_nan=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError, TypeError) as exc:
            raise WindowPresetError(f"Cannot save window presets {self.path}: {exc}") from exc
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
