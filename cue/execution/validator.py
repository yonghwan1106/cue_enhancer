"""Pre-action validation (VeriSafe-inspired): 5 sequential checks before execution."""

from __future__ import annotations

from cue.types import (
    Action,
    ElementMap,
    ValidationCheck,
    ValidationResult,
    ValidationStatus,
)

CLICK_TYPES = {"left_click", "double_click", "right_click"}
SEARCH_RADIUS = 20


class PreActionValidator:
    """Runs up to 5 checks on a click action before it is executed.

    Non-click actions always receive a SAFE result.
    """

    def validate(
        self,
        action: Action,
        elements: ElementMap,
        screen_size: tuple[int, int],
    ) -> ValidationResult:
        """Return a :class:`ValidationResult` for *action*."""
        if action.type not in CLICK_TYPES or action.coordinate is None:
            return ValidationResult(
                status=ValidationStatus.SAFE,
                checks=[
                    ValidationCheck(
                        name="skip",
                        passed=True,
                        reason="Non-click action – validation skipped.",
                    )
                ],
            )

        x, y = action.coordinate
        screen_w, screen_h = screen_size
        checks: list[ValidationCheck] = []

        # ── Check 1: target_exists ────────────────────────────────────────────
        nearest = elements.find_nearest(x, y, radius=SEARCH_RADIUS)
        target_exists = nearest is not None
        checks.append(
            ValidationCheck(
                name="target_exists",
                passed=target_exists,
                reason=(
                    f"Element found: '{nearest.label}'" if target_exists
                    else "No UI element within 20px of target coordinate."
                ),
                fix_action=action.with_metadata({"suggest_zoom": True}) if not target_exists else None,
            )
        )

        # ── Check 2: target_visible ───────────────────────────────────────────
        topmost = elements.get_topmost_at(x, y)
        if target_exists and nearest is not None:
            target_visible = topmost is not None and topmost is nearest
        else:
            target_visible = False

        checks.append(
            ValidationCheck(
                name="target_visible",
                passed=target_visible,
                reason=(
                    "Target element is the topmost element at the click point."
                    if target_visible
                    else "Target element may be obscured by another element."
                ),
                # No automatic fix available for visibility issues.
                fix_action=None,
            )
        )

        # ── Check 3: target_enabled ───────────────────────────────────────────
        if target_exists and nearest is not None:
            target_enabled = "disabled" not in nearest.sources and not any(
                "disabled" in s.lower() for s in nearest.sources
            )
            # UIElement.sources holds source labels; states live on
            # AccessibilityNode.  UIElement has no 'states' field directly, so
            # we check label text as a proxy.
            label_disabled = "disabled" in nearest.label.lower()
            target_enabled = not label_disabled
        else:
            target_enabled = False

        checks.append(
            ValidationCheck(
                name="target_enabled",
                passed=target_enabled,
                reason=(
                    "Target element appears enabled."
                    if target_enabled
                    else "Target element appears disabled (label contains 'disabled')."
                ),
                fix_action=None,
            )
        )

        # ── Check 4: target_in_viewport ───────────────────────────────────────
        in_viewport = 0 <= x < screen_w and 0 <= y < screen_h
        scroll_fix: Action | None = None
        if not in_viewport:
            # Suggest scrolling toward the target.
            if y >= screen_h:
                scroll_fix = Action(
                    type="scroll",
                    coordinate=(screen_w // 2, screen_h // 2),
                    delta_y=3,
                )
            elif y < 0:
                scroll_fix = Action(
                    type="scroll",
                    coordinate=(screen_w // 2, screen_h // 2),
                    delta_y=-3,
                )

        checks.append(
            ValidationCheck(
                name="target_in_viewport",
                passed=in_viewport,
                reason=(
                    "Target coordinate is within screen bounds."
                    if in_viewport
                    else f"Target ({x}, {y}) is outside screen {screen_size}."
                ),
                fix_action=scroll_fix,
            )
        )

        # ── Check 5: no_blocking_overlay ─────────────────────────────────────
        # Phase 1: not implemented – always pass.
        checks.append(
            ValidationCheck(
                name="no_blocking_overlay",
                passed=True,
                reason="Overlay detection not implemented in Phase 1.",
                fix_action=None,
            )
        )

        # ── Classify overall status ───────────────────────────────────────────
        failed = [c for c in checks if not c.passed]

        if not failed:
            status = ValidationStatus.SAFE
        elif all(c.fix_action is not None for c in failed):
            status = ValidationStatus.NEEDS_FIX
        else:
            status = ValidationStatus.BLOCKED

        fix_actions = [c.fix_action for c in failed if c.fix_action is not None]

        return ValidationResult(status=status, checks=checks, fix_actions=fix_actions)
