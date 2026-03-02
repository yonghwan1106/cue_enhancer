"""3-Level Reflection Engine for CUE verification."""

from __future__ import annotations

import logging

from cue.types import (
    Action,
    ActionReflection,
    GlobalReflection,
    ReflectionDecision,
    StepRecord,
    SubTask,
    TrajectoryReflection,
)

logger = logging.getLogger(__name__)


class ReflectionEngine:
    """3-level reflection engine: action, trajectory, and global."""

    TRAJECTORY_CHECK_INTERVAL = 3
    MAX_REPEATED_FAILURES = 3

    async def reflect_action(self, step: StepRecord) -> ActionReflection:
        """Reflect on a single action result and decide next move."""
        if step.success:
            return ActionReflection(
                success=True,
                decision=ReflectionDecision.CONTINUE,
                reason="Action succeeded",
            )

        # Check if it was a coordinate miss (click missed target)
        reason_lower = (
            step.verification.reason.lower() if step.verification else ""
        )
        is_coord_miss = any(
            kw in reason_lower
            for kw in ("coordinate", "miss", "click missed", "no change", "pixel")
        )

        if is_coord_miss and step.action.coordinate is not None:
            x, y = step.action.coordinate
            # Slight offset: try 5px down-right
            retry = step.action.with_coordinate(x + 5, y + 5)
            return ActionReflection(
                success=False,
                decision=ReflectionDecision.RETRY,
                retry_action=retry,
                reason="Coordinate miss detected — retrying with slight offset (+5, +5)",
            )

        return ActionReflection(
            success=False,
            decision=ReflectionDecision.RETRY,
            reason=f"Action failed: {step.verification.reason if step.verification else 'unknown'}",
        )

    async def reflect_trajectory(
        self,
        recent_steps: list[StepRecord],
        task_context: str | SubTask | None = None,
    ) -> TrajectoryReflection:
        """Reflect on the recent trajectory and decide if replanning is needed."""
        window = recent_steps[-self.TRAJECTORY_CHECK_INTERVAL:]

        if not window:
            return TrajectoryReflection(
                making_progress=True,
                decision=ReflectionDecision.CONTINUE,
                reason="No steps to evaluate",
            )

        failures = [s for s in window if not s.success]
        all_failed = len(failures) == len(window) and len(window) > 0

        # Check for repeated failure with the same reason
        if len(failures) >= 2:
            failure_reasons = [
                s.verification.reason if s.verification else ""
                for s in failures
            ]
            first_reason = failure_reasons[0]
            same_reason_count = sum(
                1 for r in failure_reasons if r and first_reason and r == first_reason
            )
            if same_reason_count >= 2:
                return TrajectoryReflection(
                    making_progress=False,
                    decision=ReflectionDecision.REPLAN,
                    reason=f"Repeated failure with same reason ({same_reason_count}x): {first_reason}",
                )

        if all_failed:
            return TrajectoryReflection(
                making_progress=False,
                decision=ReflectionDecision.STRATEGY_CHANGE,
                reason=f"All {len(window)} recent steps failed — strategy change required",
            )

        return TrajectoryReflection(
            making_progress=True,
            decision=ReflectionDecision.CONTINUE,
            reason=f"{len(window) - len(failures)}/{len(window)} recent steps succeeded",
        )

    async def reflect_global(
        self,
        all_steps: list[StepRecord],
        task: str,
        subtasks: list[SubTask],
        completed_subtasks: int,
    ) -> GlobalReflection:
        """Reflect on global task progress and decide if strategy revision is needed."""
        total_steps = len(all_steps)
        total_subtasks = len(subtasks)

        if total_steps == 0 or total_subtasks == 0:
            return GlobalReflection(
                on_track=True,
                decision=ReflectionDecision.CONTINUE,
                reason="Insufficient data for global reflection",
            )

        # Compare completion ratio vs step consumption ratio
        # Using a reasonable max_steps estimate (5 steps per subtask)
        max_steps_estimate = total_subtasks * 5
        step_consumption_ratio = total_steps / max(max_steps_estimate, 1)
        completion_ratio = completed_subtasks / total_subtasks

        if step_consumption_ratio > 0.5 and completion_ratio < 0.3:
            return GlobalReflection(
                on_track=False,
                decision=ReflectionDecision.STRATEGY_CHANGE,
                revised_strategy=(
                    f"Over 50% of budget consumed but only {completion_ratio:.0%} complete. "
                    "Consider shortcutting remaining subtasks or using alternative approach."
                ),
                reason=(
                    f"Progress too slow: {completion_ratio:.0%} done "
                    f"after {step_consumption_ratio:.0%} of estimated budget"
                ),
            )

        # Check failure rate trend: compare recent half vs early half
        if total_steps >= 4:
            mid = total_steps // 2
            early_rate = self._calc_failure_rate(all_steps[:mid])
            recent_rate = self._calc_failure_rate(all_steps[mid:])
            if recent_rate > early_rate + 0.3 and recent_rate > 0.5:
                return GlobalReflection(
                    on_track=False,
                    decision=ReflectionDecision.STRATEGY_CHANGE,
                    revised_strategy=(
                        f"Failure rate increased from {early_rate:.0%} to {recent_rate:.0%}. "
                        "Current approach is degrading — pivot strategy."
                    ),
                    reason=f"Failure rate trend worsening: {early_rate:.0%} -> {recent_rate:.0%}",
                )

        return GlobalReflection(
            on_track=True,
            decision=ReflectionDecision.CONTINUE,
            reason=(
                f"{completed_subtasks}/{total_subtasks} subtasks done, "
                f"failure rate {self._calc_failure_rate(all_steps):.0%}"
            ),
        )

    def _calc_failure_rate(self, steps: list[StepRecord]) -> float:
        """Return the fraction of failed steps."""
        if not steps:
            return 0.0
        failures = sum(1 for s in steps if not s.success)
        return failures / len(steps)
