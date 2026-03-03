"""Fallback chain: 6-stage recovery strategy when primary action execution fails."""

from __future__ import annotations

from typing import Callable, Awaitable, Any

from cue.types import Action, ActionResult, ElementMap
from cue.execution.drag import PreciseDragExecutor

# Common keyboard shortcuts for menu/command labels.
_SHORTCUTS: dict[str, str] = {
    "file": "alt+f",
    "save": "ctrl+s",
    "save as": "ctrl+shift+s",
    "open": "ctrl+o",
    "new": "ctrl+n",
    "close": "ctrl+w",
    "quit": "alt+f4",
    "undo": "ctrl+z",
    "redo": "ctrl+y",
    "copy": "ctrl+c",
    "cut": "ctrl+x",
    "paste": "ctrl+v",
    "select all": "ctrl+a",
    "find": "ctrl+f",
    "print": "ctrl+p",
    "help": "f1",
    "refresh": "f5",
}

# 8-directional nudge offsets (dx, dy) in pixels.
_NUDGE_OFFSETS: list[tuple[int, int]] = [
    (5, 0), (-5, 0), (0, 5), (0, -5),
    (5, 5), (-5, 5), (5, -5), (-5, -5),
]


class FallbackChain:
    """Attempts up to 6 recovery stages when primary execution fails.

    Each stage is tried in order; the chain stops at the first success.
    """

    def __init__(self) -> None:
        self._drag_executor = PreciseDragExecutor()

    async def try_fallbacks(
        self,
        action: Action,
        execute_fn: Callable[[Action], Awaitable[bool]],
        verify_fn: Callable[[], Awaitable[bool]],
        elements: ElementMap,
    ) -> ActionResult:
        """Run the 6-stage fallback chain and return an :class:`ActionResult`."""
        steps: list[str] = []

        # ── Stage 1: Coordinate nudge ─────────────────────────────────────────
        if action.coordinate is not None:
            x, y = action.coordinate
            for dx, dy in _NUDGE_OFFSETS:
                nudged = action.with_coordinate(x + dx, y + dy)
                try:
                    success = await execute_fn(nudged)
                    if success and await verify_fn():
                        steps.append(f"stage1_nudge({dx},{dy})")
                        return ActionResult(
                            success=True,
                            action_type=action.type,
                            fallback_used="coordinate_nudge",
                            steps_taken=steps,
                        )
                except Exception:
                    pass
            steps.append("stage1_nudge_failed")

        # ── Stage 2: Zoom re-ground ───────────────────────────────────────────
        # Actual zoom is handled by the calling agent.  We return a special
        # result so the agent can zoom in, re-ground, and retry.
        zoom_action = action.with_metadata({"suggest_zoom": True, "fallback_stage": 2})
        steps.append("stage2_zoom_reground_suggested")
        try:
            success = await execute_fn(zoom_action)
            if success and await verify_fn():
                return ActionResult(
                    success=True,
                    action_type=action.type,
                    fallback_used="zoom_reground",
                    steps_taken=steps,
                )
        except Exception:
            pass

        # ── Stage 3: Keyboard shortcut ────────────────────────────────────────
        label = ""
        if action.coordinate is not None:
            nearest = elements.find_nearest(*action.coordinate, radius=50)
            if nearest:
                label = nearest.label.lower()

        shortcut = _SHORTCUTS.get(label)
        if not shortcut:
            # Try partial match.
            for key, value in _SHORTCUTS.items():
                if key in label:
                    shortcut = value
                    break

        if shortcut:
            shortcut_action = Action(type="key", key=shortcut)
            try:
                success = await execute_fn(shortcut_action)
                if success and await verify_fn():
                    steps.append(f"stage3_shortcut({shortcut})")
                    return ActionResult(
                        success=True,
                        action_type=action.type,
                        fallback_used="keyboard_shortcut",
                        steps_taken=steps,
                    )
            except Exception:
                pass
        steps.append("stage3_shortcut_skipped_or_failed")

        # ── Stage 4: Tab navigation ───────────────────────────────────────────
        for _ in range(10):
            tab_action = Action(type="key", key="tab")
            try:
                await execute_fn(tab_action)
            except Exception:
                break

        enter_action = Action(type="key", key="enter")
        try:
            success = await execute_fn(enter_action)
            if success and await verify_fn():
                steps.append("stage4_tab_navigation")
                return ActionResult(
                    success=True,
                    action_type=action.type,
                    fallback_used="tab_navigation",
                    steps_taken=steps,
                )
        except Exception:
            pass
        steps.append("stage4_tab_navigation_failed")

        # ── Stage 5: Accessibility direct invoke ──────────────────────────────
        # Placeholder – full implementation deferred to Phase 2.
        steps.append("stage5_a11y_invoke_placeholder")

        # ── Stage 6: Scroll and retry ─────────────────────────────────────────
        scroll_action = Action(
            type="scroll",
            coordinate=action.coordinate or (0, 0),
            delta_y=3,
        )
        try:
            await execute_fn(scroll_action)
        except Exception:
            pass

        try:
            success = await execute_fn(action)
            if success and await verify_fn():
                steps.append("stage6_scroll_retry")
                return ActionResult(
                    success=True,
                    action_type=action.type,
                    fallback_used="scroll_and_retry",
                    steps_taken=steps,
                )
        except Exception:
            pass
        steps.append("stage6_scroll_retry_failed")

        # All stages exhausted.
        return ActionResult(
            success=False,
            action_type=action.type,
            error="All 6 fallback stages exhausted.",
            fallback_used="all_stages_failed",
            steps_taken=steps,
        )
