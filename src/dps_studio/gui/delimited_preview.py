"""Compatibility imports for the core delimited-file preview API."""

from dps_studio.core.io.delimited_preview import (
    DelimitedFilePreview,
    DelimitedPreviewError,
    preview_delimited_file,
)


__all__ = [
    "DelimitedFilePreview",
    "DelimitedPreviewError",
    "preview_delimited_file",
]
