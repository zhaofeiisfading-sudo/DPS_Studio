"""Scientific figure contracts: denominators, source bytes and complete data."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np
import pytest

from artifacts.research_clean_task8.catalog import METHODS
from artifacts.research_clean_task9.prepare_figures import ROOT, T8, T9, VELOCITY, table

FIGURES = T9 / "figures_final"
MAIN = ["Fig01_GlobalPerformance", "Fig02_PairedEffect", "Fig03_LowVelocity", "Fig04_Onset",
        "Fig05_Acceleration", "Fig06_Clutter", "Fig07_DoubleShockFailure", "Fig08_SubcycleFailure",
        "Fig09_RealPDV", "Fig10_Cost"]
SUPPLEMENTS = ["SFig01_FamilyFailure", "SFig02_RealCoverage", "SFig03_RealSpectra"]


@pytest.mark.parametrize("identifier", MAIN + SUPPLEMENTS)
def test_figures_exist_with_traceable_sources_and_embedded_pdf_fonts(identifier: str) -> None:
    import hashlib
    folder = FIGURES / identifier
    spec = json.loads((folder / "figure.json").read_text(encoding="utf-8"))
    for extension in ["pdf", "svg", "png"] + (["opju"] if identifier in MAIN else []):
        assert (folder / f"{identifier}.{extension}").stat().st_size > 500
    assert (folder / "caption_zh.md").is_file()
    for item in spec["sources"]:
        path = (ROOT / item["path"]).resolve()
        assert path.is_relative_to(ROOT)
        with path.open("rb") as handle:
            assert hashlib.file_digest(handle, "sha256").hexdigest() == item["sha256"]
    pdf = json.loads((folder / "pdf_parsed.json").read_text(encoding="utf-8"))
    assert len(pdf["pages"]) == 1
    text = " ".join(w["text"] or "" for p in pdf["pages"] for w in p["words"])
    assert not re.search(r"%\(\d+\)", text), "Auto-legend introduced a gap segment as a method"
    assert float(pdf["pages"][0]["width"]) == pytest.approx(180 / 25.4 * 72, abs=0.9)
    font_rows = re.findall(r"\b(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+", pdf["fonts"])
    assert font_rows and all(row[0] == "yes" for row in font_rows)
    for page in pdf["pages"]:
        assert all(float(w["xMin"]) >= -0.5 and float(w["yMin"]) >= -0.5
                   and float(w["xMax"]) <= float(page["width"]) + 0.5
                   and float(w["yMax"]) <= float(page["height"]) + 0.5 for w in page["words"])


def test_global_denominator_keeps_every_missing_frame() -> None:
    rows = [r for r in table("fresh_summary.csv") if r["family"] == "ALL"
            and r["region"] == "motion" and r["channel"] == "accepted"]
    assert {r["method"] for r in rows} == set(METHODS)
    for row in rows:
        assert int(row["target_n"]) == 6952
        assert int(row["failure_n"]) == 6952 - int(row["finite_n"]) + int(row["wrong_finite_n"])
    fig = json.loads((FIGURES / MAIN[0] / "figure.json").read_text(encoding="utf-8"))
    assert all(len(p["series"]) == 14 for p in fig["panels"])


def test_low_velocity_levels_and_posthoc_failure_selection_are_actual_data() -> None:
    spec = json.loads((FIGURES / "Fig03_LowVelocity/figure.json").read_text(encoding="utf-8"))
    assert all(s["x"] == [15, 30, 50, 100, 200] for p in spec["panels"] for s in p["series"])
    bad = json.loads((FIGURES / "Fig08_SubcycleFailure/figure.json").read_text(encoding="utf-8"))
    assert "POST HOC DIAGNOSTIC" in bad["selection"]
    rows = [r for r in table("all_phase_stress_metrics.csv") if r["method"] == "varpro"
            and int(r["case_id"].rsplit("_", 1)[1]) % 5 == 0]
    assert len(rows) == 10
    worst = max(rows, key=lambda r: float(r["candidate_motion_rmse_m_s"]))
    assert worst["case_id"] in bad["selection"]


def test_truth_all_source_samples_and_nan_gaps_are_retained() -> None:
    folder = FIGURES / "Fig05_Acceleration"
    spec = json.loads((folder / "figure.json").read_text(encoding="utf-8"))
    with np.load(T8 / "datasets/fresh/fresh_fast_accel_00.npz") as truth:
        expected_x = truth["time_s"] * 1e9
        expected_y = truth["truth_hz"] * VELOCITY
    for p in spec["panels"]:
        s = p["series"][0]
        np.testing.assert_array_equal(np.asarray(s["x"], dtype=float), expected_x)
        np.testing.assert_allclose(np.asarray(s["y"], dtype=float), expected_y, rtol=0, atol=0, equal_nan=True)
        assert len(s["x"]) == 12800
    for identifier in MAIN:
        folder = FIGURES / identifier
        spec = json.loads((folder / "figure.json").read_text(encoding="utf-8"))
        logs = json.loads((folder / "origin_log.json").read_text(encoding="utf-8-sig"))
        for pi, p in enumerate(spec["panels"], 1):
            for s in p["series"]:
                log = next(r for r in logs if r.get("panel") == pi and r.get("series") == s["data_csv"])
                assert log["total_original_points"] == len(s["x"])
                assert log["finite_original_points"] == sum(x is not None and y is not None
                    for x, y in zip(s["x"], s["y"], strict=True))


def test_all_real_streams_are_retained_without_accuracy_claims() -> None:
    path = FIGURES / "SFig02_RealCoverage/stream_mapping.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 17
    assert len({r["raw_sha256"] for r in rows}) == 13
    assert all("result" not in Path(r["raw_path"]).name.lower() for r in rows)
    spec = json.loads((FIGURES / "SFig02_RealCoverage/figure.json").read_text(encoding="utf-8"))
    assert spec["matrix_shape"] == [14, 17]
    assert "不是准确率" in spec["caption_zh"]
