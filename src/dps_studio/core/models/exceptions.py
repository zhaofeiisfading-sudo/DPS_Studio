"""Exceptions raised by DPS Studio data models."""


class DPSStudioError(Exception):
    """Base exception for DPS Studio errors."""


class SignalValidationError(DPSStudioError):
    """Base exception for invalid signal data or sampling information."""


class SignalConversionError(SignalValidationError):
    """Raised when signal input cannot be converted to numeric data."""


class SignalShapeError(SignalValidationError):
    """Raised when a signal array has an invalid number of dimensions."""


class SignalLengthError(SignalValidationError):
    """Raised when signal arrays have invalid or inconsistent lengths."""


class NonFiniteSignalError(SignalValidationError):
    """Raised when a signal array contains NaN or infinite values."""


class NonMonotonicTimeError(SignalValidationError):
    """Raised when signal times are not strictly increasing."""
