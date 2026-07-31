"""Workflow states for the desktop interface."""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    """Ordered availability states for the first desktop workflow."""

    EMPTY = "empty"
    DATA_LOADED = "data_loaded"
    RANGE_DEFINED = "range_defined"
    STFT_READY = "stft_ready"
    RIDGE_READY = "ridge_ready"
    RESULT_READY = "result_ready"


_STATE_ORDER = {
    WorkflowState.EMPTY: 0,
    WorkflowState.DATA_LOADED: 1,
    WorkflowState.RANGE_DEFINED: 2,
    WorkflowState.STFT_READY: 3,
    WorkflowState.RIDGE_READY: 4,
    WorkflowState.RESULT_READY: 5,
}


def state_reaches(current: WorkflowState, required: WorkflowState) -> bool:
    """Return whether *current* has reached *required* in the workflow."""
    return _STATE_ORDER[current] >= _STATE_ORDER[required]


__all__ = ["WorkflowState", "state_reaches"]
