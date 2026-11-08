"""Frozen twelve-method exploration plus explicit historical M0 contract audit."""
from .common import METHODS as EXPLORATION_METHODS
from pathlib import Path

METHODS = (*EXPLORATION_METHODS, "legacy_m0_512", "legacy_m0_768")


def run_folder(out: Path, method: str, stage: str, case_id: str) -> Path:
    audited = out/method/"runs"/("baseline_"+stage)/case_id
    return audited if audited.exists() else out/method/"runs"/stage/case_id
