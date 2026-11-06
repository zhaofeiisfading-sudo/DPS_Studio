"""Validate the export produced through native input in the final packaged GUI."""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "artifacts/research_clean_task11"
CHECKS = ARTIFACT / "checks"
EXPORT = CHECKS / "PDV_TASK011_20261106_111332_372186"


def main() -> None:
    metadata = json.loads(next(EXPORT.glob("*.metadata.json")).read_text(encoding="utf-8"))
    with next(EXPORT.glob("*.csv")).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    values = {key: np.array([float(row[key]) for row in rows]) for key in (
        "absolute_time_s", "frequency_hz", "apparent_velocity_m_s",
        "angle_corrected_velocity_m_s", "corrected_velocity_m_s", "valid")}
    assert len(rows) == metadata["sample_count"] == 550
    assert sum(values["valid"]) == metadata["valid_count"] == 386
    assert {row["algorithm_id"] for row in rows} == {"stft", "dechirp"}
    assert np.all(np.diff(values["absolute_time_s"]) > 0)
    segments = metadata["segments"]
    assert segments[0]["end_s"] == segments[1]["start_s"]
    assert np.all(values["absolute_time_s"] >= segments[0]["start_s"])
    assert np.all(values["absolute_time_s"] <= segments[-1]["end_s"])
    np.testing.assert_allclose(values["apparent_velocity_m_s"],
        values["frequency_hz"] * metadata["vacuum_wavelength_m"] / 2,
        rtol=1e-14, atol=0, equal_nan=True)
    correction = metadata["physical_correction"]
    angle = correction["angle"]["angle_rad"]
    np.testing.assert_allclose(values["angle_corrected_velocity_m_s"],
        values["apparent_velocity_m_s"] / np.cos(angle), rtol=1e-14, equal_nan=True)
    window = correction["window"]
    assert window["model"] == "Rigg2014_Eq16" and window["enabled"]
    expected = 1000 * window["b1"] * (values["angle_corrected_velocity_m_s"] / 1000) ** window["b2"]
    np.testing.assert_allclose(values["corrected_velocity_m_s"], expected, rtol=1e-14, equal_nan=True)
    assert np.array_equal(values["valid"].astype(bool), np.isfinite(values["corrected_velocity_m_s"]))
    source = Path(metadata["source_path"])
    with source.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    assert digest == metadata["source_sha256"]
    assert all(part["error"] is None for part in metadata["algorithms"])
    result = {"passed": True, "export": str(EXPORT), "rows": len(rows), "valid": 386,
        "algorithm_ids": ["stft", "dechirp"], "strict_time_order": True,
        "roi_s": [segments[0]["start_s"], segments[-1]["end_s"]],
        "boundary_context_rows": sum("BOUNDARY_CONTEXT" in row["quality"] for row in rows),
        "apparent_angle_lif_readback_validated": True, "source_sha256": digest}
    with (CHECKS / "native_export_roundtrip_v4.json").open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
