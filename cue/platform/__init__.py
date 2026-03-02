"""Platform abstraction layer for CUE."""

import sys

from cue.platform.base import EnvironmentAbstraction, create_environment

__all__ = ["EnvironmentAbstraction", "create_environment"]

if sys.platform == "win32":
    try:
        from cue.platform.windows import WindowsEnvironment

        __all__ = ["EnvironmentAbstraction", "create_environment", "WindowsEnvironment"]
    except ImportError:
        pass
