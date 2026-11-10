"""Real-input contracts only: no generated waves, noise, truth or speed calibration."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from scripts.research.task017.compare import align, common_centers, evidence, formal, frozen_plans
from scripts.research.task017.prepare import OUT, ROOT, load, records

RUN = OUT / "data/full_v01"
ANALYSIS = OUT / "data/analysis_v03"
AVAILABLE = (RUN / "complete.json").is_file() and (ANALYSIS / "provenance.json").is_file()
pytestmark = pytest.mark.skipif(not AVAILABLE, reason="Run the complete local real experiment first")


def read(channel: str, method: str, root: Path = ANALYSIS) -> Any:
    return dict(np.load(root / channel / f"{method}.npz"))


def test_inputs_are_only_current_raw_and_frozen_images_have_not_changed() -> None:
    items = records()
    assert len({r["file"] for r in items}) == 10
    assert len(items) == 14
    for item in items:
        path = (ROOT / item["file"]).resolve()
        assert path.is_relative_to(ROOT / "data/raw")
        with path.open("rb") as handle:
            assert hashlib.file_digest(handle, "sha256").hexdigest() == item["sha256"]
    lock = json.loads((OUT / "data/visual_freeze.json").read_text(encoding="utf-8"))
    assert len(lock["raw_review_images"]) == 28
    for name, digest in lock["raw_review_images"].items():
        with (OUT / "figures/visual_review" / name).open("rb") as handle:
            assert hashlib.file_digest(handle, "sha256").hexdigest() == digest


@pytest.mark.parametrize("item", records(), ids=lambda r: r["id"])
def test_frozen_manual_plan_has_exactly_one_owner_per_original_center(item: Any) -> None:
    t, _, _ = load(item)
    plan = frozen_plans()[item["id"]]
    assert plan[0]["start_s"] == t[0]
    assert plan[-1]["end_s"] == t[-1]
    q = common_centers(len(t))
    owners = np.zeros(len(q), dtype=int)
    for i, seg in enumerate(plan):
        owners += (t[q] >= seg["start_s"]) & (
            (t[q] <= seg["end_s"]) if i == len(plan)-1 else (t[q] < seg["end_s"]))
    assert np.all(owners == 1)


@pytest.mark.parametrize("item", records(), ids=lambda r: r["id"])
def test_retained_native_centers_match_original_integer_sample_times(item: Any) -> None:
    t, _, fs = load(item)
    meta = json.loads((RUN / item["id"] / "metadata.json").read_text(encoding="utf-8"))
    assert not meta["failures"]
    for method in meta["methods"]:
        v = read(item["id"], method)
        native = np.load(RUN / item["id"] / f"{method}__native.npz")
        _, matched = align(native["time_s"], t, fs, v["sample_index"])
        assert matched.any()
        np.testing.assert_array_equal(v["time_s"], t[v["sample_index"]])
        assert np.isnan(v["apparent_velocity_m_s"]).all()
        assert np.all(v["frequency_hz"][np.isfinite(v["frequency_hz"])] > 0)
        valid = np.isfinite(v["gated_frequency_hz"])
        assert np.isfinite(v["raw_frequency_hz"][valid]).all()
        np.testing.assert_allclose(v["gated_frequency_hz"][valid],
                                   v["raw_frequency_hz"][valid], rtol=1e-12)
        if method in ("M2_task014_gui", "M3_parameters", "M4_specialized"):
            assert np.all(v["gated_frequency_hz"][valid] <= 6e9)


def test_formal_baseline_parity_on_original_20201210_record() -> None:
    item = records()[0]
    t, y, fs = load(item)
    tr = formal(t, y)
    v = read(item["id"], "M1_balanced")
    pos, ok = align(tr.time, t, fs, v["sample_index"])
    np.testing.assert_allclose(v["raw_frequency_hz"][ok], tr.candidate[pos[ok]], equal_nan=True)
    np.testing.assert_allclose(v["gated_frequency_hz"][ok], tr.gated[pos[ok]], equal_nan=True)


def test_visual_onset_control_preserves_the_real_no_event_counterexample() -> None:
    original = read("20201210m_ch1", "varpro")
    manual = read("20201210m_ch1", "visual_onset_varpro")
    assert not np.isfinite(original["raw_frequency_hz"]).any()
    assert np.isfinite(manual["raw_frequency_hz"]).any()
    assert np.isnan(manual["apparent_velocity_m_s"]).all()


@pytest.mark.parametrize("item", records(), ids=lambda r: r["id"])
def test_final_28_method_values_match_plotted_data_and_no_invalid_long_diagnostic(item: Any) -> None:
    meta = json.loads((ANALYSIS / item["id"] / "metadata.json").read_text(encoding="utf-8"))
    assert len(meta["methods"]) == 28
    for name in meta["methods"]:
        final = read(item["id"], name)
        plotted = read(item["id"], name, OUT / "data/analysis_v02")
        assert not any(key.startswith("long4096_") for key in final)
        for key in ("time_s", "frequency_hz", "gated_frequency_hz", "spectrally_supported"):
            np.testing.assert_array_equal(final[key], plotted[key])


def test_long_background_uses_actual_available_prefix_and_not_an_empty_range() -> None:
    item = next(r for r in records() if r["id"] == "20260701_ch2")
    t, y, fs = load(item)
    value = evidence(t, y, fs, np.array([4096], dtype=np.int64), float(t[8192]), width=4096)
    assert np.isfinite(value["background"]).all()
    assert value["background"].max() > 0


def test_comparison_manifest_has_all_real_channels_and_required_curve_types() -> None:
    manifest = json.loads((OUT / "figures/comparison_v01/manifest.json").read_text(encoding="utf-8"))
    assert {r["channel"] for r in manifest} == {r["id"] for r in records()}
    for item in records():
        images = [r for r in manifest if r["channel"] == item["id"]]
        for required in ("full_curves.png", "onset_curves.png", "onset_spectral_overlay.png",
                         "frozen_segmentation.png", "full_spectral_overlay.png"):
            assert any(r["png"].endswith("/"+required) for r in images)
        for result in images:
            assert (OUT / result["png"]).stat().st_size > 1000
            assert (OUT / result["svg"]).stat().st_size > 1000


@pytest.mark.parametrize("item", records(), ids=lambda r: r["id"])
def test_clipped_support_never_contains_neighboring_stage_voltage(item: Any) -> None:
    t, _, _ = load(item)
    with gzip.open(RUN / item["id"] / "stft_short__details.json.gz", "rt", encoding="utf-8") as stream:
        details = json.load(stream)
    plan = frozen_plans()[item["id"]]
    for segment, result in zip(plan, details, strict=True):
        for frame in result["frames"]:
            left, right = frame["support_start_sample"], frame["support_end_sample"]
            assert t[left] >= segment["start_s"]
            assert t[right-1] < segment["end_s"] or right == len(t)
