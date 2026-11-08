"""Force the correct local source tree before loading the Research-only entry."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if ROOT.name != "DPS_Studio_RESEARCH_CLEAN":
    raise RuntimeError("Run this script from the correct target checkout")
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]

from dps_studio.research.task009_runtime import main  # noqa: E402

if __name__ == "__main__":
    main()
