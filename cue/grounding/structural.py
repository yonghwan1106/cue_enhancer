"""Structural grounding expert using platform accessibility APIs."""

from __future__ import annotations

import platform

from cue.types import StructuralElement

_MAX_DEPTH = 15

_ACTIONABLE_ROLES = {
    "button",
    "check box",
    "combo box",
    "entry",
    "link",
    "menu item",
    "push button",
    "radio button",
    "slider",
    "spin button",
    "text",
    "toggle button",
    "tree item",
}


class StructuralGrounder:
    """Parses the platform accessibility tree to produce StructuralElements."""

    async def parse(self) -> list[StructuralElement]:
        """Return structural elements from the accessibility tree.

        Falls back to an empty list on import errors or unsupported platforms.
        """
        system = platform.system().lower()
        if system == "linux":
            return self._parse_atspi()
        # Windows / macOS backends not yet implemented
        return []

    # ------------------------------------------------------------------
    # AT-SPI2 (Linux)
    # ------------------------------------------------------------------

    def _parse_atspi(self) -> list[StructuralElement]:
        try:
            from gi.repository import Atspi  # type: ignore[import]
        except Exception:
            return []

        try:
            desktop = Atspi.get_desktop(0)
        except Exception:
            return []

        elements: list[StructuralElement] = []
        for app_idx in range(desktop.get_child_count()):
            try:
                app = desktop.get_child_at_index(app_idx)
                if app is None:
                    continue
                self._traverse_atspi(app, elements, depth=0)
            except Exception:
                continue

        return elements

    def _traverse_atspi(
        self,
        node: object,
        elements: list[StructuralElement],
        depth: int,
    ) -> None:
        if depth > _MAX_DEPTH:
            return

        try:
            from gi.repository import Atspi  # type: ignore[import]

            role_name: str = node.get_role_name()  # type: ignore[union-attr]
            name: str = node.get_name() or ""  # type: ignore[union-attr]

            # Bounding box
            try:
                ext = node.get_extents(Atspi.CoordType.SCREEN)  # type: ignore[union-attr]
                bbox: tuple[int, int, int, int] = (
                    int(ext.x),
                    int(ext.y),
                    int(ext.x + ext.width),
                    int(ext.y + ext.height),
                )
            except Exception:
                bbox = (0, 0, 0, 0)

            # States
            try:
                state_set = node.get_state_set()  # type: ignore[union-attr]
                states: list[str] = [
                    s.value_nick
                    for s in Atspi.StateType.__members__.values()
                    if state_set.contains(s)
                ]
            except Exception:
                states = []

            actionable = role_name.lower() in _ACTIONABLE_ROLES

            elements.append(
                StructuralElement(
                    role=role_name,
                    name=name,
                    bbox=bbox,
                    states=states,
                    depth=depth,
                    actionable=actionable,
                )
            )

            child_count: int = node.get_child_count()  # type: ignore[union-attr]
            for i in range(child_count):
                try:
                    child = node.get_child_at_index(i)
                    if child is not None:
                        self._traverse_atspi(child, elements, depth + 1)
                except Exception:
                    continue

        except Exception:
            return
