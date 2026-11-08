"""Ground-truth-informed external spectral mixing diagnostic, never an estimator."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np

from scripts.research.task010.audit import OUT, write_json
from scripts.research.task010.experiment import VELOCITY, WINDOWS
from scripts.research.task010.run import frozen_case, write_csv


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists() or not output.is_relative_to(OUT):
        parser.error("Use a new TASK-010 subdirectory")
    output.mkdir(parents=True, exist_ok=False)
    records = []
    curves: list[dict[str, Any]] = []
    for instance in range(8):
        case = frozen_case("fresh", "two_shock", instance)
        signal = case.signal
        for width in WINDOWS:
            starts = np.arange(0, len(signal.time_s)-width+1)
            centers = starts+width//2
            times = signal.time_s[centers]
            take = (times >= 65e-9) & (times <= 145e-9)
            starts, centers, times = starts[take], centers[take], times[take]
            window = np.hanning(width+1)[:-1]
            tau = np.arange(width)/signal.fs
            # These two frequencies are diagnostic labels from the generator.
            # They are NEVER fed into any reconstruction or selection routine.
            atoms = np.exp(-2j*np.pi*np.array([240., 1150.])[:, None]/VELOCITY*tau)
            frames = np.lib.stride_tricks.sliding_window_view(signal.voltage_v, width)
            fraction = np.zeros(len(starts))
            for left in range(0, len(starts), 256):
                right = min(left+256, len(starts))
                values = frames[starts[left:right]] * window
                power = abs(values @ atoms.T)**2
                fraction[left:right] = power[:, 1]/np.maximum(power.sum(axis=1), 1e-300)
            for hop in (128, 32, 1):
                chosen = starts % hop == 0
                t, y = times[chosen], fraction[chosen]
                crossings = []
                for q in (.1, .5, .9):
                    cross = np.flatnonzero(y >= q)
                    crossings.append(float(t[cross[0]]) if len(cross) else None)
                records.append(dict(case_id=case.signal.name, window=width, hop=hop,
                    t10_ns=crossings[0]*1e9 if crossings[0] is not None else None,
                    t50_error_ns=(crossings[1]-105e-9)*1e9 if crossings[1] is not None else None,
                    t90_ns=crossings[2]*1e9 if crossings[2] is not None else None,
                    mixing_10_90_width_ns=(crossings[2]-crossings[0])*1e9
                    if crossings[0] is not None and crossings[2] is not None else None))
                if instance == 0:
                    curves.extend(dict(case_id=case.signal.name, window=width, hop=hop,
                                       time_ns=float(x*1e9), high_component_power_fraction=float(v))
                                  for x, v in zip(t, y, strict=True))
    write_csv(output / "spectral_mixing_metrics.csv", records)
    write_csv(output / "spectral_mixing_curves.csv", curves)
    write_json(output / "methodology.json", dict(
        scope="external diagnostic, NOT blind reconstruction", cases="fixed eight two_shock cases",
        query_frequencies_hz=[240/VELOCITY, 1150/VELOCITY],
        ratio="abs(F_high)^2 / (abs(F_low)^2 + abs(F_high)^2)",
        uncertainty="eight independent waveforms; no frame-independent inference",
        no_truth_feedback=True, no_interpolation=True, no_dc_removal=True))


if __name__ == "__main__":
    main()
