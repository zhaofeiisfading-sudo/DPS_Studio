"""Supplementary local-model diagnostics from saved arrays, with no estimator rerun."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

from scripts.freeze_task026 import load_json
from scripts.summarize_task026 import save


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    output = parser.parse_args().output
    rows: list[dict[str, Any]] = []
    for row in load_json(output/'seed_registration.json'):
        if row['dataset'] != 'SINGLE' or row['split'] != 'HELD_OUT':
            continue
        for profile in ('balanced', 'high_time_resolution'):
            with np.load(output/'streams'/f'{row["waveform"]}__{profile}.npz') as arrays:
                focus = arrays['focus']
                rate = arrays['R3_chirp_rate_hz_per_s'][focus, 0]
                truth_rate = np.full(len(rate), row['chirp_hz_per_s'])
                if row['family'] == 'nonlinear_chirp':
                    curvature = (2*row['fade_depth']-1)*8e23
                    truth_rate += curvature*(arrays['time_s'][focus]-25.6e-9)
                error = rate-truth_rate
                rows.append(dict(waveform=row['waveform'], family=row['family'], profile=profile,
                    snr_db=row['snr_db'], chirp_rate_hz_per_s=row['chirp_hz_per_s'],
                    chirp_rate_rmse_hz_per_s=float(np.sqrt(np.mean(error**2))),
                    chirp_rate_bias_hz_per_s=float(np.mean(error)),
                    chirp_rate_p95_abs_hz_per_s=float(np.percentile(np.abs(error), 95)),
                    bank_boundary_fraction=float(np.mean(np.abs(rate) == 2e17)),
                    weighted_residual_fraction=float(np.mean(arrays['R3_residual_fraction'][focus])),
                    uncertainty='GRID_HALF_STEP_5e15_Hz_per_s_NOT_CONFIDENCE_INTERVAL'))
    save(pd.DataFrame(rows), output/'local_chirp_fit_diagnostics.csv')


if __name__ == '__main__':
    main()
