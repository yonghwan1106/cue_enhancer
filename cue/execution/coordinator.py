"""Coordinate refinement: snap click coordinates to nearest UI element center."""

from __future__ import annotations

import math

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
