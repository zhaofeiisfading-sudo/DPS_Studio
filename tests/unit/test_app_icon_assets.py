"""Regression coverage for alpha cleanup and the actual Windows ICO frames."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from dps_studio.runtime_paths import package_resource_path


SPEC = importlib.util.spec_from_file_location(
    "build_app_icon", Path(__file__).resolve().parents[2] / "tools" / "build_app_icon.py"
)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def test_cleanup_preserves_body_and_aa_but_removes_remote_contamination() -> None:
    rgba = np.zeros((32, 32, 4), dtype=np.uint8)
    rgba[8:24, 8:24] = (4, 35, 140, 253)
    rgba[7, 8:24] = (230, 240, 255, 128)
    rgba[2, 2] = (255, 255, 255, 8)
    rgba[0, 0] = (255, 255, 255, 0)
    cleaned, report = builder.clean_alpha(Image.fromarray(rgba))
    result = np.asarray(cleaned)
    assert np.array_equal(result[8:24, 8:24, :3], rgba[8:24, 8:24, :3])
    assert np.all(result[8:24, 8:24, 3] == 255)
    assert np.all((result[7, 8:24, 3] > 0) & (result[7, 8:24, 3] < 255))
    assert np.all(result[7, 8:24, :3] == (4, 35, 140))
    assert np.all(result[2, 2] == 0)
    assert np.all(result[0, 0] == 0)
    assert report["removed_pixels"] == 1


def test_resize_ignores_hidden_white_rgb_and_has_no_remote_ringing() -> None:
    rgba = np.full((128, 128, 4), (255, 255, 255, 0), dtype=np.uint8)
    rgba[32:96, 32:96] = (0, 0, 200, 255)
    resized = np.asarray(builder.resize_icon(Image.fromarray(rgba), 16))
    assert np.all(resized[:4] == 0)
    assert np.all(resized[-4:] == 0)
    assert np.all(resized[..., :2] == 0)
    assert resized[8, 8, 3] == 255


def test_master_is_opaque_inside_and_has_clean_transparent_margin() -> None:
    path = package_resource_path("gui", "icons", "pdv_studio_master.png")
    with Image.open(path) as image:
        rgba = np.asarray(image)
    assert np.all(rgba[300:950, 300:950, 3] == 255)
    assert np.all(rgba[:90] == 0)
    assert np.all(rgba[-90:] == 0)
    assert np.all(rgba[rgba[..., 3] == 0] == 0)
    assert np.any((rgba[..., 3] > 0) & (rgba[..., 3] < 255))


def test_ico_contains_all_nine_transparent_frames() -> None:
    path = package_resource_path("gui", "icons", "pdv_studio.ico")
    with Image.open(path) as ico:
        assert ico.ico.sizes() == {(s, s) for s in builder.ICON_SIZES}
        for size in builder.ICON_SIZES:
            rgba = np.asarray(ico.ico.getimage((size, size)).convert("RGBA"))
            assert rgba[0, 0, 3] == 0
            assert rgba[size // 2, size // 2, 3] == 255
            assert np.any((rgba[..., 3] > 0) & (rgba[..., 3] < 255))


def test_builder_refuses_overwrite(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(source)
    existing = tmp_path / "out"
    existing.mkdir()
    protected = existing / "pdv_studio.ico"
    protected.write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        builder.build(source, existing, tmp_path / "diagnostics")
    assert protected.read_bytes() == b"keep"


def test_empty_body_is_rejected() -> None:
    with pytest.raises(ValueError, match="No opaque body"):
        builder.clean_alpha(Image.new("RGBA", (16, 16)))
