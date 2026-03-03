"""Precise drag-and-drop using decomposed mouse events."""

from __future__ import annotations

import asyncio
from typing import Callable, Awaitable

from cue.types import Action, ActionResult


class PreciseDragExecutor:
    """Executes drag-and-drop using mouse_down/mouse_move/mouse_up sequence.

    Advantages over left_click_drag:
    - Intermediate waypoint support (curved drags)
    - Modifier key combinations (Shift+drag, Ctrl+drag)
    - Per-step verification capability
    - More reliable on slow-rendering UIs
    """

    async def execute_drag(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        execute_fn: Callable[[Action], Awaitable[bool]],
        modifier_key: str | None = None,
        intermediate_points: list[tuple[int, int]] | None = None,
        step_delay_ms: int = 50,
    ) -> ActionResult:
        """Execute a precise drag-and-drop operation.

        Parameters
        ----------
        start: Starting coordinates (x, y)
        end: Ending coordinates (x, y)
        execute_fn: Async callable to execute individual actions
        modifier_key: Optional modifier to hold during drag (e.g., "shift", "ctrl")
        intermediate_points: Optional waypoints between start and end
        step_delay_ms: Delay between each step in milliseconds
        """
        steps: list[str] = []

        try:
            # 1. Hold modifier key if specified
            if modifier_key:
                hold_action = Action(type="key", key=modifier_key, metadata={"hold": True})
                await execute_fn(hold_action)
                steps.append(f"hold_key:{modifier_key}")

            # 2. Move to start position and press mouse button
            move_start = Action(type="mouse_move", coordinate=start)
            await execute_fn(move_start)
            steps.append(f"move_to_start:{start}")

            down_action = Action(type="mouse_down", coordinate=start)
            await execute_fn(down_action)
            steps.append(f"mouse_down:{start}")

            if step_delay_ms > 0:
                await asyncio.sleep(step_delay_ms / 1000.0)

            # 3. Move through intermediate points
            if intermediate_points:
                for i, point in enumerate(intermediate_points):
                    move_action = Action(type="mouse_move", coordinate=point)
                    await execute_fn(move_action)
                    steps.append(f"waypoint_{i}:{point}")
                    if step_delay_ms > 0:
                        await asyncio.sleep(step_delay_ms / 1000.0)

            # 4. Move to end position
            move_end = Action(type="mouse_move", coordinate=end)
            await execute_fn(move_end)
            steps.append(f"move_to_end:{end}")

            if step_delay_ms > 0:
                await asyncio.sleep(step_delay_ms / 1000.0)

            # 5. Release mouse button
            up_action = Action(type="mouse_up", coordinate=end)
            await execute_fn(up_action)
            steps.append(f"mouse_up:{end}")

            # 6. Release modifier key if held
            if modifier_key:
                release_action = Action(type="key", key=modifier_key, metadata={"release": True})
                await execute_fn(release_action)
                steps.append(f"release_key:{modifier_key}")

            return ActionResult(
                success=True,
                action_type="precise_drag",
                steps_taken=steps,
            )

        except Exception as exc:
            # Ensure mouse is released on error
            try:
                up_action = Action(type="mouse_up", coordinate=end)
                await execute_fn(up_action)
            except Exception:
                pass

            if modifier_key:
                try:
                    release = Action(type="key", key=modifier_key, metadata={"release": True})
                    await execute_fn(release)
                except Exception:
                    pass

            steps.append(f"error:{exc}")
            return ActionResult(
                success=False,
                action_type="precise_drag",
                error=str(exc),
                steps_taken=steps,
            )

    def interpolate_points(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        num_points: int = 5,
    ) -> list[tuple[int, int]]:
        """Generate intermediate points for smooth drag motion."""
        points = []
        for i in range(1, num_points + 1):
            t = i / (num_points + 1)
            x = int(start[0] + t * (end[0] - start[0]))
            y = int(start[1] + t * (end[1] - start[1]))
            points.append((x, y))
        return points
