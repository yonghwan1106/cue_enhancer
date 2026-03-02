"""ExecutionEnhancer: orchestrates validate → refine → wait → execute → verify."""

from __future__ import annotations

import asyncio
from typing import Callable, Awaitable

import numpy as np

from cue.config import EnhancerLevel, ExecutionConfig
from cue.types import (
    Action,
    ActionResult,
    ElementMap,
    EnhancedContext,
    ValidationStatus,
)
from cue.execution.coordinator import CoordinateRefiner
from cue.execution.fallback import FallbackChain
from cue.execution.timing import TimingController
from cue.execution.validator import PreActionValidator


class ExecutionEnhancer:
    """Orchestrates the full execution enhancement pipeline.

    Pipeline:
      1. Pre-action validation (PreActionValidator)
      2. Coordinate refinement  (CoordinateRefiner)
      3. UI stability wait      (TimingController)
      4. Execute action         (caller-supplied execute_fn)
      5. Verify result          (caller-supplied screenshot_fn → verify heuristic)
      6. Fallback chain on failure (FallbackChain)
    """

    def __init__(self, config: ExecutionConfig | None = None) -> None:
        self._config = config or ExecutionConfig()
        self._validator = PreActionValidator()
        self._refiner = CoordinateRefiner()
        self._timing = TimingController()
        self._fallback = FallbackChain()

    # ── Public API ────────────────────────────────────────────────────────────

    async def execute(
        self,
        action: Action,
        context: EnhancedContext,
        execute_fn: Callable[[Action], Awaitable[bool]],
        screenshot_fn: Callable[[], Awaitable[np.ndarray]],
        before_frame: np.ndarray | None = None,
    ) -> ActionResult:
        """Run the full pipeline and return an :class:`ActionResult`.

        Parameters
        ----------
        action:
            The action to execute.
        context:
            Grounding context containing detected UI elements.
        execute_fn:
            Async callable that performs the action; returns True on success.
        screenshot_fn:
            Async callable that returns the current screen as an ndarray.
        """
        cfg = self._config
        elements = ElementMap(elements=list(context.elements))
        screen_size = self._screen_size(context)
        app_name = context.screen_state.app_name if context.screen_state else None
        steps: list[str] = []

        # ── Step 1: Pre-action validation ─────────────────────────────────────
        if cfg.enable_pre_validation:
            validation = self._validator.validate(action, elements, screen_size)
            steps.append(f"validate:{validation.status.value}")

            if validation.status == ValidationStatus.BLOCKED:
                return ActionResult(
                    success=False,
                    action_type=action.type,
                    error=f"Pre-validation BLOCKED: {[c.reason for c in validation.checks if not c.passed]}",
                    steps_taken=steps,
                )

            # Apply any fix actions sequentially before proceeding.
            if validation.status == ValidationStatus.NEEDS_FIX:
                for fix in validation.fix_actions:
                    try:
                        await execute_fn(fix)
                        steps.append(f"fix:{fix.type}")
                    except Exception as exc:
                        steps.append(f"fix_failed:{exc}")

        # ── Step 2: Coordinate refinement ─────────────────────────────────────
        refined_action = await self._refiner.refine(action, elements)
        steps.append(
            "refine:snapped" if "snapped_to" in refined_action.metadata else "refine:unchanged"
        )

        # ── Step 3: Wait for stable UI (skipped for BASIC level) ──────────────
        if cfg.enable_timing_control and cfg.level != EnhancerLevel.BASIC:
            stability = await self._timing.wait_for_stable_ui(
                screenshot_fn,
                timeout_ms=cfg.stability_timeout_ms,
                app_name=app_name,
            )
            steps.append(
                f"stability:{'stable' if stability.is_stable else 'timeout'}"
                f"({stability.wait_duration_ms:.0f}ms)"
            )

        # ── Step 4: Execute ───────────────────────────────────────────────────
        if before_frame is None:
            raw_before = await screenshot_fn()
            before_frame = np.array(raw_before) if not isinstance(raw_before, np.ndarray) else raw_before
        try:
            success = await execute_fn(refined_action)
        except Exception as exc:
            success = False
            steps.append(f"execute_error:{exc}")

        steps.append(f"execute:{'ok' if success else 'fail'}")

        # ── Step 5: Verify (simple pixel-diff heuristic) ──────────────────────
        # Brief post-action delay (reduced from 200ms; stability already checked)
        await asyncio.sleep(cfg.post_action_delay_ms / 1000.0)
        raw_after = await screenshot_fn()
        after_frame = np.array(raw_after) if not isinstance(raw_after, np.ndarray) else raw_after
        if success:
            diff = float(
                np.mean(
                    np.abs(
                        after_frame.astype(np.float32)
                        - before_frame.astype(np.float32)
                    )
                )
                / 255.0
            )
            verified = diff > cfg.stability_threshold
            steps.append(f"verify:{'changed' if verified else 'no_change'}(diff={diff:.4f})")
        else:
            verified = False

        if verified or not cfg.enable_fallback_chain:
            return ActionResult(
                success=verified or success,
                action_type=action.type,
                before_screenshot=before_frame,
                after_screenshot=after_frame,
                steps_taken=steps,
            )

        # ── Step 6: Fallback chain ────────────────────────────────────────────
        steps.append("fallback:start")
        fallback_result = await self._fallback.try_fallbacks(
            refined_action,
            execute_fn,
            self._make_verify_fn(screenshot_fn, before_frame, cfg.stability_threshold),
            elements,
        )
        fallback_result.steps_taken = steps + fallback_result.steps_taken
        fallback_result.before_screenshot = before_frame
        return fallback_result

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _screen_size(context: EnhancedContext) -> tuple[int, int]:
        """Extract screen dimensions from context, defaulting to 1920×1080."""
        if context.screen_state and context.screen_state.screenshot:
            img = context.screen_state.screenshot
            return img.width, img.height
        return 1920, 1080

    @staticmethod
    def _make_verify_fn(
        screenshot_fn: Callable[[], Awaitable[np.ndarray]],
        before: np.ndarray,
        threshold: float,
    ) -> Callable[[], Awaitable[bool]]:
        """Return a verify callable that checks whether the screen changed."""

        async def _verify() -> bool:
            raw = await screenshot_fn()
            after = np.array(raw) if not isinstance(raw, np.ndarray) else raw
            if after.shape != before.shape:
                return True
            diff = float(
                np.mean(np.abs(after.astype(np.float32) - before.astype(np.float32)))
                / 255.0
            )
            return diff > threshold

        return _verify
