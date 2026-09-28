"""Pre-observation tests of conjunctive representation acceptance."""
from __future__ import annotations

import pytest

from scripts.summarize_task026 import gate_verdict


@pytest.mark.parametrize('failed', range(6))
def test_each_failed_condition_prevents_support(failed: int) -> None:
    values = [True]*6
    values[failed] = False
    assert gate_verdict(*values) != 'SUPPORTED'


def test_supported_and_accuracy_only_mixed() -> None:
    assert gate_verdict(True, True, True, True, True, True) == 'SUPPORTED'
    assert gate_verdict(True, True, False, True, True, True) == 'MIXED'
    assert gate_verdict(False, True, False, True, True, False) == 'NOT SUPPORTED'
