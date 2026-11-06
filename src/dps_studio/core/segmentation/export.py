"""Non-overwriting CSV/JSON export with per-frame algorithm and segment identity."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from .models import SegmentedResult


def jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)):
        return [jsonable(item) for item in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def export_segmented_results(
    results: Mapping[str, SegmentedResult], destination: Path, *,
    source_path: Path | None = None, time_origin_s: float = 0.0,
    protected_directories: tuple[Path, ...] = (),
) -> tuple[Path, ...]:
    if not results or not math.isfinite(time_origin_s):
        raise ValueError("Export requires results and a finite SI time origin")
    destination = destination.resolve()
    if any(destination.is_relative_to(path.resolve()) for path in protected_directories):
        raise ValueError("Export destination is protected")
    if any(parent.name.lower() == "raw" and parent.parent.name.lower() == "data"
           for parent in (destination, *destination.parents)):
        raise ValueError("Raw data directories are read-only")
    if destination.exists():
        raise FileExistsError("Choose a new export directory; previous results are preserved")
    destination.mkdir(parents=True, exist_ok=False)
    source_sha: str | None = None
    if source_path is not None and source_path.is_file():
        with source_path.open("rb") as handle:
            source_sha = hashlib.file_digest(handle, "sha256").hexdigest()
    paths: list[Path] = []
    for channel_index, (channel, result) in enumerate(results.items(), 1):
        safe_name = re.sub(r"[^\w.-]", "_", channel)[:60] or "channel"
        stem = f"{channel_index:02d}_{safe_name}_segmented"
        csv_path, meta_path = destination / f"{stem}.csv", destination / f"{stem}.metadata.json"
        stage_by_id = {segment.id: segment.stage for segment in result.segments}
        with csv_path.open("x", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("time_s", "absolute_time_s", "frequency_hz",
                             "candidate_frequency_hz", "apparent_velocity_m_s",
                             "angle_corrected_velocity_m_s", "corrected_velocity_m_s",
                             "valid", "quality", "segment_id", "stage", "algorithm_id"))
            for index, t in enumerate(result.time_s):
                writer.writerow((format(float(t - time_origin_s), ".17g"), format(float(t), ".17g"),
                                 result.frequency_hz[index], result.candidate_frequency_hz[index],
                                 result.apparent_velocity_m_s[index],
                                 result.angle_corrected_velocity_m_s[index],
                                 result.corrected_velocity_m_s[index], int(result.valid[index]),
                                 result.quality[index], result.segment_ids[index],
                                 stage_by_id[result.segment_ids[index]], result.algorithm_ids[index]))
        metadata = {**dict(result.metadata), "channel": channel, "source_path": source_path,
                    "source_sha256": source_sha, "segments": result.segments,
                    "vacuum_wavelength_m": result.wavelength_m, "time_origin_s": time_origin_s,
                    "sample_count": len(result.time_s), "valid_count": int(result.valid.sum()),
                    "units": {"time": "s", "frequency": "Hz", "velocity": "m/s"},
                    "missing_value": "NaN in CSV; null in JSON",
                    "velocity_sign": "nonnegative beat magnitude; motion direction unresolved"}
        with meta_path.open("x", encoding="utf-8") as handle:
            json.dump(jsonable(metadata), handle, ensure_ascii=False, indent=2, allow_nan=False)
        paths.extend((csv_path, meta_path))
    return tuple(paths)
