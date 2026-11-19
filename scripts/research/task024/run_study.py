"""Run TASK-024 Phase 1 from the repository root."""
from __future__ import annotations

import argparse

from scripts.research.task024.replay import OUTPUT, replay


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resume", action="store_true", help="Reuse completed center arrays")
    args = parser.parse_args()
    if OUTPUT.resolve() != OUTPUT:
        raise ValueError(f"Study output must be inside this checkout: {OUTPUT}")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    screens, timing, wide, checked = replay(OUTPUT, resume=args.resume)
    print(f"Finished real-data replay: {len(screens)} channels, {checked} archive centers",
          flush=True)
    from scripts.research.task024.reporting import report

    report(OUTPUT, screens, timing, wide, checked)


if __name__ == "__main__":
    main()
