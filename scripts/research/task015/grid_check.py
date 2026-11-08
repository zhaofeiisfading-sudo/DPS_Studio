"""Diagnose floating timestamp lookup without changing any frequency estimate."""
import json
from pathlib import Path
import numpy as np
from scripts.research.task015.experiment import request, common_grid
from dps_studio.algorithms.waveform.common import Signal
from dps_studio.core.segmentation import default_pool
from dps_studio.research.task009_data import inventory, read_raw

rows=[]
for item in inventory():
    if item['kind'] != 'RAW':
        continue
    for original in read_raw(item):
        signal=Signal(original.time_s,original.voltage_v)
        e=default_pool().estimate('stft',request(signal,50e6))
        native=np.rint((e.time_s-signal.time_s[0])*signal.fs).astype(np.int64)
        q=common_grid(signal)
        idx=np.searchsorted(native,q)
        exact=bool(np.array_equal(native[idx],q))
        error=float(np.max(abs(e.time_s[idx]-signal.time_s[q])))
        rows.append(dict(channel=original.name,integer_centers_match=exact,max_time_error_s=error,
                         candidate_hash=__import__('hashlib').sha256(e.candidate_frequency_hz[idx].tobytes()).hexdigest()))
        assert exact and error < 5e-15
print(json.dumps(rows,indent=2))
((Path(__file__).resolve().parents[3] / "artifacts/TASK-015") / 'data').joinpath('grid_check.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
