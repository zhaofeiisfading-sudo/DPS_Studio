"""Signal file input APIs and errors."""

from dps_studio.core.io.delimited import read_delimited_signals
from dps_studio.core.io.delimited_preview import (
    DelimitedFilePreview,
    DelimitedPreviewError,
    detect_delimiter,
    preview_delimited_file,
)
from dps_studio.core.io.delimiter import WHITESPACE_DELIMITER
from dps_studio.core.io.exceptions import (
    SignalColumnError,
    SignalConfigurationError,
    SignalEncodingError,
    SignalFileNotFoundError,
    SignalFileTypeError,
    SignalIOError,
    SignalParseError,
)
from dps_studio.core.io.models import DelimitedSignalLoadResult

__all__ = [
    "DelimitedSignalLoadResult",
    "DelimitedFilePreview",
    "DelimitedPreviewError",
    "SignalColumnError",
    "SignalConfigurationError",
    "SignalEncodingError",
    "SignalFileNotFoundError",
    "SignalFileTypeError",
    "SignalIOError",
    "SignalParseError",
    "WHITESPACE_DELIMITER",
    "detect_delimiter",
    "preview_delimited_file",
    "read_delimited_signals",
]
