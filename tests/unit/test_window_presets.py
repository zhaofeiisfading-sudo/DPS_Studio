from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from dps_studio.core.physics import (
    LIF_RIGG_2014_1550NM, VelocityConfigurationError,
    VelocityCorrectionConfig, apply_velocity_corrections, velocity_correction_metadata,
)
from dps_studio.core.physics.window_presets import WindowPresetError, WindowPresetRepository
from dps_studio.core.workflow import load_workflow_config


def test_roundtrip_chinese_rename_save_as_and_immutable_builtin(tmp_path: Path) -> None:
    repository = WindowPresetRepository(tmp_path / "config" / "window_presets.json")
    assert repository.next_name() == "新材料1"
    first = replace(LIF_RIGG_2014_1550NM, b1=.8, configuration_name="新材料1")
    repository.save(first)
    assert repository.next_name() == "新材料2"
    second = replace(first, configuration_name="样品甲", b2=1.05)
    repository.save(second)
    renamed = replace(first, configuration_name="中文重命名")
    repository.save(renamed, original_name="新材料1")
    assert WindowPresetRepository(repository.path).load() == {"样品甲": second, "中文重命名": renamed}
    assert LIF_RIGG_2014_1550NM.b1 == .7895
    assert LIF_RIGG_2014_1550NM.configuration_name is None


def test_duplicate_rename_cannot_replace_another_entry(tmp_path: Path) -> None:
    repository = WindowPresetRepository(tmp_path / "presets.json")
    for name in ["A", "B"]:
        repository.save(replace(LIF_RIGG_2014_1550NM, configuration_name=name))
    before = repository.path.read_bytes()
    with pytest.raises(WindowPresetError, match="already exists"):
        repository.save(replace(LIF_RIGG_2014_1550NM, configuration_name="B"), original_name="A")
    assert repository.path.read_bytes() == before


@pytest.mark.parametrize("name", ["", " ", "LiF", "lif", " A ", "A\nB"])
def test_bad_names(tmp_path: Path, name: str) -> None:
    with pytest.raises((WindowPresetError, VelocityConfigurationError)):
        WindowPresetRepository(tmp_path / "presets.json").save(
            replace(LIF_RIGG_2014_1550NM, configuration_name=name),
        )


@pytest.mark.parametrize("parameter,value", [("b1", -1.), ("b2", float("nan")),
                                            ("reference_wavelength_m", 0.), ("b1", True)])
def test_invalid_parameters(parameter: str, value: object) -> None:
    with pytest.raises(VelocityConfigurationError):
        replace(LIF_RIGG_2014_1550NM, **{parameter: value})


@pytest.mark.parametrize("text", ["broken", "[]", '{"schema_version": 9}', '{}'])
def test_damaged_library_is_never_overwritten(tmp_path: Path, text: str) -> None:
    path = tmp_path / "presets.json"
    path.write_text(text, encoding="utf-8")
    repository = WindowPresetRepository(path)
    with pytest.raises(WindowPresetError):
        repository.load()
    with pytest.raises(WindowPresetError):
        repository.save(replace(LIF_RIGG_2014_1550NM, configuration_name="新材料1"))
    assert path.read_text(encoding="utf-8") == text


def test_atomic_write_failure_retains_previous_file(tmp_path: Path, monkeypatch: Any) -> None:
    repository = WindowPresetRepository(tmp_path / "presets.json")
    first = replace(LIF_RIGG_2014_1550NM, configuration_name="甲")
    repository.save(first)
    before = repository.path.read_bytes()

    def failed(*args: object) -> None:
        raise OSError("disk failure")

    monkeypatch.setattr("dps_studio.core.physics.window_presets.os.replace", failed)
    with pytest.raises(WindowPresetError, match="disk failure"):
        repository.save(replace(first, b1=.9), original_name="甲")
    assert repository.path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_metadata_name_changes_preserve_numbers_and_snapshot(tmp_path: Path) -> None:
    first = replace(LIF_RIGG_2014_1550NM, b1=.8, configuration_name="甲")
    results = [apply_velocity_corrections([1000., 2000.], vacuum_wavelength_m=1550e-9,
               config=VelocityCorrectionConfig(lif_model=replace(first, configuration_name=name)))
               for name in ["甲", "乙"]]
    np.testing.assert_array_equal(results[0].corrected_velocity_m_s, results[1].corrected_velocity_m_s)
    window = velocity_correction_metadata(results[0])["window"]
    assert window["configuration_name"] == "甲"  # type: ignore[index]
    assert window["configuration_type"] == "custom"  # type: ignore[index]


def test_old_toml_coefficients_remain_custom_without_migration(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "configs/pdv_studio_defaults.toml").read_text(encoding="utf-8")
    text = text.replace("lif_b1 = 0.7895", "lif_b1 = 0.8123")
    path = tmp_path / "legacy.toml"
    path.write_text(text, encoding="utf-8")
    config = load_workflow_config(path, repository_root=root)
    assert config.velocity_correction.lif_model.b1 == .8123
    result = apply_velocity_corrections([1000.], vacuum_wavelength_m=1550e-9,
                                      config=config.velocity_correction)
    assert velocity_correction_metadata(result)["window"]["custom_parameters"]  # type: ignore[index]
    assert path.read_text(encoding="utf-8") == text


def test_invalid_json_coefficients_report_preset_error(tmp_path: Path) -> None:
    repository = WindowPresetRepository(tmp_path / "presets.json")
    repository.save(replace(LIF_RIGG_2014_1550NM, configuration_name="甲"))
    document = json.loads(repository.path.read_text(encoding="utf-8"))
    document["presets"][0]["b1"] = -1
    repository.path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(WindowPresetError):
        repository.load()
