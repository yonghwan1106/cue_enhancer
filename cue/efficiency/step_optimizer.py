"""Step Minimization — reduce subtask count before execution."""

from __future__ import annotations

from typing import Any

from cue.types import OptimizationResult, SubTask


class StepOptimizer:
    """Optimize a subtask plan by minimizing steps needed to complete it."""

    def optimize_plan(
        self,
        subtasks: list[SubTask],
        app_knowledge: dict[str, Any] | None = None,
    ) -> tuple[list[SubTask], OptimizationResult]:
        """Apply all optimization passes in sequence.

        Returns the optimized subtask list and a result object describing
        what changed.
        """
        original_count = len(subtasks)
        methods_applied: list[str] = []

        current = list(subtasks)

        current, changed = self._apply_keyboard_shortcuts(current, app_knowledge)
        if changed:
            methods_applied.append("keyboard_shortcuts")

        current, changed = self._eliminate_redundant_nav(current, app_knowledge)
        if changed:
            methods_applied.append("eliminate_redundant_nav")

        current, changed = self._apply_direct_navigation(current, app_knowledge)
        if changed:
            methods_applied.append("direct_navigation")

        current, changed = self._batch_similar_actions(current)
        if changed:
            methods_applied.append("batch_similar_actions")

        optimized_count = len(current)
        reduction_pct = (
            (original_count - optimized_count) / original_count * 100.0
            if original_count > 0
            else 0.0
        )

        result = OptimizationResult(
            original_steps=original_count,
            optimized_steps=optimized_count,
            reduction_pct=round(reduction_pct, 1),
            methods_applied=methods_applied,
        )
        return current, result

    # ── Private Passes ───────────────────────────────────────

    def _apply_keyboard_shortcuts(
        self,
        subtasks: list[SubTask],
        knowledge: dict[str, Any] | None,
    ) -> tuple[list[SubTask], bool]:
        """Replace mouse actions with keyboard shortcuts when reliable enough."""
        if not knowledge:
            return subtasks, False

        shortcuts: dict[str, dict[str, Any]] = knowledge.get("shortcuts", {})
        if not shortcuts:
            return subtasks, False

        result: list[SubTask] = []
        changed = False

        for task in subtasks:
            shortcut_info = shortcuts.get(task.action_type) or shortcuts.get(
                task.target
            )
            if (
                shortcut_info
                and shortcut_info.get("reliability", 0.0) > 0.8
                and task.method != "keyboard"
            ):
                result.append(
                    task.with_method(
                        method="keyboard",
                        shortcut=shortcut_info.get("key", ""),
                        original_method=task.method,
                    )
                )
                changed = True
            else:
                result.append(task)

        return result, changed

    def _batch_similar_actions(
        self,
        subtasks: list[SubTask],
    ) -> tuple[list[SubTask], bool]:
        """Merge 3+ consecutive same-action/same-region tasks into one batch."""
        if len(subtasks) < 3:
            return subtasks, False

        result: list[SubTask] = []
        changed = False
        i = 0

        while i < len(subtasks):
            # Find run of same (action_type, target_region)
            j = i + 1
            while j < len(subtasks) and self._can_batch(subtasks[i], subtasks[j]):
                j += 1

            run_length = j - i
            if run_length >= 3:
                result.append(self._merge_to_batch(subtasks[i:j]))
                changed = True
            else:
                result.extend(subtasks[i:j])

            i = j

        return result, changed

    def _eliminate_redundant_nav(
        self,
        subtasks: list[SubTask],
        knowledge: dict[str, Any] | None,
    ) -> tuple[list[SubTask], bool]:
        """Remove navigation steps that go where we already are, and
        remove standalone verification steps when the preceding step
        already verified."""
        result: list[SubTask] = []
        changed = False
        current_location: str | None = None
        last_was_verification = False

        for task in subtasks:
            # Track location from navigation steps
            if task.is_navigation:
                destination = task.target or task.target_region
                if destination and destination == current_location:
                    # Already here — drop this nav step
                    changed = True
                    continue
                current_location = destination or current_location
                last_was_verification = False
                result.append(task)
                continue

            # Drop redundant standalone verification steps
            if task.is_verification_only:
                if last_was_verification:
                    changed = True
                    continue
                last_was_verification = True
                result.append(task)
                continue

            last_was_verification = False
            result.append(task)

        return result, changed

    def _apply_direct_navigation(
        self,
        subtasks: list[SubTask],
        knowledge: dict[str, Any] | None,
    ) -> tuple[list[SubTask], bool]:
        """Replace multi-step scroll sequences with single direct navigation."""
        if len(subtasks) < 2:
            return subtasks, False

        direct_nav = knowledge.get("direct_navigation", {}) if knowledge else {}

        result: list[SubTask] = []
        changed = False
        i = 0

        while i < len(subtasks):
            task = subtasks[i]

            # Detect consecutive scroll actions targeting the same region
            if task.action_type == "scroll" and i + 1 < len(subtasks):
                j = i + 1
                while j < len(subtasks) and subtasks[j].action_type == "scroll":
                    j += 1

                scroll_count = j - i
                if scroll_count >= 2:
                    target = task.target or task.target_region
                    nav_key = direct_nav.get(target, "Ctrl+G")
                    merged = SubTask(
                        description=f"Navigate directly to {target}",
                        action_type="key",
                        target=target,
                        target_region=task.target_region,
                        method="keyboard",
                        shortcut=nav_key,
                        original_method="scroll",
                        is_navigation=True,
                        action_description=f"Press {nav_key} to jump directly",
                    )
                    result.append(merged)
                    changed = True
                    i = j
                    continue

            result.append(task)
            i += 1

        return result, changed

    def _can_batch(self, task1: SubTask, task2: SubTask) -> bool:
        """Return True if task2 can be batched with task1."""
        return (
            task1.action_type == task2.action_type
            and task1.target_region == task2.target_region
            and not task1.is_compound
            and not task2.is_compound
            and not task1.is_navigation
            and not task2.is_navigation
        )

    def _merge_to_batch(self, group: list[SubTask]) -> SubTask:
        """Merge a group of similar subtasks into one batch subtask."""
        first = group[0]
        descriptions = [t.description for t in group]
        return SubTask(
            description=f"Batch: {first.action_type} x{len(group)} in {first.target_region}",
            action_type=first.action_type,
            target=first.target,
            target_region=first.target_region,
            method="batch",
            is_compound=True,
            batch_items=list(group),
            action_description="; ".join(descriptions),
            steps=[t.description for t in group],
        )
