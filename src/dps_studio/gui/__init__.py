"""PySide6 desktop interface for PDV Studio.

The GUI depends on the public :mod:`dps_studio.core` APIs.  The numerical core
does not depend on this package.
"""

from dps_studio.gui.state import WorkflowState

__all__ = ["WorkflowState"]
