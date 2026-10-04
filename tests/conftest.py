"""Explicit public CI contract; the default suite keeps every raw regression."""

from __future__ import annotations

import pytest


REAL_DATA_TESTS = frozenset({
    "tests/unit/test_task018c_real_regression.py::"
    "test_frame_1015_is_formally_promoted_and_legacy_remains_recoverable",
    "tests/unit/test_legacy_velocity_audit.py::"
    "test_real_production_baseline_and_task008_fingerprints_are_unchanged",
    "tests/unit/gui/test_task015a_analysis.py::"
    "test_repository_raw_data_hash_is_stable_during_gui_tests",
    "tests/unit/gui/test_task015c_r_event_reference_views.py::"
    "test_cross_file_raw_hashes_and_gui_script_boundary_are_stable",
})
WINDOWS_RELEASE_MODULES = frozenset({
    "tests/unit/test_production_release.py",
    "tests/unit/test_v014_release_verification.py",
})


def portable_exclusion(nodeid: str) -> str | None:
    """Return a declared reason, never infer availability from a missing file."""
    if nodeid.split("[", 1)[0] in REAL_DATA_TESTS:
        return "private raw regression / Windows numerical byte fingerprint"
    if nodeid.split("::", 1)[0] in WINDOWS_RELEASE_MODULES:
        return "Windows release contract (retained in full Windows suite)"
    return None


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--portable-ci", action="store_true", default=False,
                     help="Public portable suite; explicitly deselect private raw/Windows release gates")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not config.getoption("--portable-ci"):
        return
    selected = [item for item in items if portable_exclusion(item.nodeid) is None]
    excluded = [item for item in items if portable_exclusion(item.nodeid) is not None]
    config.hook.pytest_deselected(items=excluded)
    items[:] = selected
    reporter = config.pluginmanager.getplugin("terminalreporter")
    if reporter is not None:
        reporter.write_line("PORTABLE CI: private raw regressions and Windows release gates excluded;")
        reporter.write_line("FULL LOCAL REAL-DATA SUITE is NOT VERIFIED by this invocation.")
        for item in excluded:
            reporter.write_line(f"  {item.nodeid}: {portable_exclusion(item.nodeid)}")
