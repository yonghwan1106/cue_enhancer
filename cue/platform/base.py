"""Abstract base class for platform-specific environment interactions."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod

from PIL import Image

from cue.types import AccessibilityTree


class EnvironmentAbstraction(ABC):
    """Abstract interface for OS-level interactions.

    Each platform (Linux, macOS, Windows) provides a concrete implementation
    that handles screenshots, keyboard/mouse input, and accessibility tree access.
    """

    @abstractmethod
    async def take_screenshot(self, width: int = 1024, height: int = 768) -> Image.Image:
        """Capture a screenshot of the current screen, resized to target dimensions."""

    @abstractmethod
    async def get_a11y_tree(self) -> AccessibilityTree:
        """Get the accessibility tree of the currently focused window."""

    @abstractmethod
    async def send_keys(self, text: str) -> None:
        """Type text using keyboard input."""

    @abstractmethod
    async def send_key(self, key: str) -> None:
        """Send a single key or key combination (e.g., 'Return', 'ctrl+s')."""

    @abstractmethod
    async def click(
        self, x: int, y: int, button: str = "left", click_count: int = 1
    ) -> None:
        """Click at screen coordinates."""

    @abstractmethod
    async def mouse_move(self, x: int, y: int) -> None:
        """Move the mouse cursor to coordinates."""

    @abstractmethod
    async def mouse_down(self, x: int, y: int, button: str = "left") -> None:
        """Press mouse button down at coordinates."""

    @abstractmethod
    async def mouse_up(self, x: int, y: int, button: str = "left") -> None:
        """Release mouse button at coordinates."""

    @abstractmethod
    async def scroll(self, x: int, y: int, delta_x: int = 0, delta_y: int = 0) -> None:
        """Scroll at the given coordinates."""

    @abstractmethod
    async def get_clipboard(self) -> str:
        """Get current clipboard text content."""

    @abstractmethod
    async def set_clipboard(self, text: str) -> None:
        """Set clipboard text content."""

    @abstractmethod
    async def get_active_window_info(self) -> dict[str, str]:
        """Get info about the active window (app_name, title)."""

    @abstractmethod
    async def get_screen_size(self) -> tuple[int, int]:
        """Get the screen resolution (width, height)."""


def create_environment() -> EnvironmentAbstraction:
    """Factory: detect platform and return the appropriate implementation."""
    if sys.platform == "linux":
        from cue.platform.linux import LinuxEnvironment

        return LinuxEnvironment()
    elif sys.platform == "darwin":
        raise NotImplementedError("macOS support is planned for Phase 2")
    elif sys.platform == "win32":
        from cue.platform.windows import WindowsEnvironment

        return WindowsEnvironment()
    else:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")
