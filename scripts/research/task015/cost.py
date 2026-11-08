"""Serial repeated timing, after concurrent experimental/build jobs have ended."""
import json
import platform
from pathlib import Path
import sys
from importlib.metadata import version
import numpy as np
import pandas as pd

from scripts.research.task015.experiment import make_case, run

OUT=(Path(__file__).resolve().parents[3] / "artifacts/TASK-015")
rows=[]
for family in ('low_spur','onset_step','fast_accel','plateau','weak_fixed','weak_drift'):
    case=make_case(family,5,'heldout')
    for repeat in range(3):
        traces=run(case.signal,case.plan,family)
        for name,tr in traces.items():
            rows.append(dict(family=family,method=name,repeat=repeat,runtime_ms=tr.runtime_s*1000,
                             cost_definition='full-record component sum for maps; actual measured call for individual estimators'))
    print(family,flush=True)
pd.DataFrame(rows).to_csv(OUT/'data/cost.csv',index=False)
environment=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),
                 versions={name:version(name) for name in ['numpy','scipy','matplotlib','pandas',
                             'PySide6','pyqtgraph','pytest','ruff','mypy','pyinstaller']},
                 repeats=3,numerical_threads=1,synthetic_samples=12800,fs_hz=40e9,
                 percentiles='describe across repetitions; not a hardware-independent speed claim',
                 numpy_version=np.__version__)
(OUT/'data/environment.json').write_text(json.dumps(environment,indent=2),encoding='utf-8')
