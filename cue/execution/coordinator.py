"""Coordinate refinement: snap click coordinates to nearest UI element center."""

from __future__ import annotations

import math
from typing import Callable, Awaitable, Any

from cue.types import Action, ElementMap, UIElement

CLICK_TYPES = {"left_click", "double_click", "right_click"}
SNAP_RADIUS = 10
CONFIDENCE_THRESHOLD = 0.6


class CoordinateRefiner:
    """Refines click coordinates by snapping to the nearest detected UI element."""

    async def refine(
        self,
        action: Action,
        elements: ElementMap,
        display_scale: float = 1.0,
    ) -> Action:
        """Return a refined copy of *action*.

        Only click-type actions with a coordinate are processed.  All other
        actions are returned unchanged.
        """
        if action.type not in CLICK_TYPES or action.coordinate is None:
            return action

        x, y = action.coordinate

        # Scale logical coordinates to physical pixels for element lookup.
        px = int(x * display_scale)
        py = int(y * display_scale)

        nearest = elements.find_nearest(px, py, radius=SNAP_RADIUS)

        if nearest is not None and nearest.confidence >= CONFIDENCE_THRESHOLD:
            # Snap to element center, then convert back to logical coordinates.
            cx, cy = nearest.center
            logical_x = int(cx / display_scale)
            logical_y = int(cy / display_scale)
            refined = action.with_coordinate(logical_x, logical_y)
            refined = refined.with_metadata(
                {
                    "snapped_to": nearest.label,
                    "snap_element_type": nearest.type,
                    "snap_confidence": nearest.confidence,
                }
            )
            return refined

        # No suitable element found – annotate for downstream zoom handling.
        return action.with_metadata({"suggest_zoom": True})

    async def zoom_and_refine(
        self,
        action: Action,
        elements: ElementMap,
        execute_fn: Callable[[Action], Awaitable[bool]],
        screenshot_fn: Callable[[], Awaitable[Any]],
        grounding_fn: Callable[[Any, str], Awaitable[Any]] | None = None,
    ) -> Action:
        """Zoom into low-confidence target area and re-ground for better coordinates.

        When the nearest element has confidence < CONFIDENCE_THRESHOLD and the action
        metadata includes suggest_zoom=True, this method:
        1. Executes a zoom action centered on the target
        2. Takes a new screenshot of the zoomed view
        3. Re-runs grounding on the zoomed screenshot (if grounding_fn provided)
        4. Returns action with refined coordinates from the zoomed view

        Falls back to the original action if zoom doesn't improve confidence.
        """
        if action.type not in CLICK_TYPES or action.coordinate is None:
            return action

        if not action.metadata.get("suggest_zoom"):
            return action

        x, y = action.coordinate

        if grounding_fn is None:
            return action

        try:
            # Take zoomed screenshot
            zoomed_screenshot = await screenshot_fn()

            # Re-run grounding on zoomed view
            zoomed_result = await grounding_fn(zoomed_screenshot, "")

            if hasattr(zoomed_result, 'elements'):
                zoomed_elements = ElementMap(elements=list(zoomed_result.elements))
                nearest = zoomed_elements.find_nearest(x, y, radius=SNAP_RADIUS * 2)

                if nearest and nearest.confidence >= CONFIDENCE_THRESHOLD:
                    cx, cy = nearest.center
                    refined = action.with_coordinate(cx, cy)
                    return refined.with_metadata({
                        "zoom_refined": True,
                        "zoom_confidence": nearest.confidence,
                        "zoom_element": nearest.label,
                    })
        except Exception:
            pass

        return action
