"""Working Memory — in-episode short-term memory."""

from __future__ import annotations

from cue.types import StepRecord


class WorkingMemory:
    """Manages the current episode's step history with compression."""

    def __init__(self, max_steps: int = 10) -> None:
        self._max_steps = max_steps
        self._steps: list[StepRecord] = []
        self._compressed_history: list[str] = []

    def add_step(self, step: StepRecord) -> None:
        """Add a step record; compress oldest steps when exceeding max."""
        self._steps.append(step)
        if len(self._steps) > self._max_steps:
            overflow = self._steps[: len(self._steps) - self._max_steps]
            self._steps = self._steps[len(self._steps) - self._max_steps :]
            self._compressed_history.extend(self._compress_old_steps(overflow))

    def get_context(self) -> dict[str, object]:
        """Return current memory context as a dict."""
        recent_window = 5
        mid_window = 5

        recent_steps = self._steps[-recent_window:]
        mid_steps = self._steps[
            max(0, len(self._steps) - recent_window - mid_window) : max(
                0, len(self._steps) - recent_window
            )
        ]

        return {
            "compressed_history": list(self._compressed_history),
            "recent_steps": recent_steps,
            "mid_steps": mid_steps,
        }

    def _compress_old_steps(self, old_steps: list[StepRecord]) -> list[str]:
        """Compress a list of steps to one-line summaries."""
        return [self._summarize_single(s) for s in old_steps]

    def _summarize(self, steps: list[StepRecord]) -> list[str]:
        """Return brief one-line summaries for a list of steps."""
        return [self._summarize_single(s) for s in steps]

    def _summarize_single(self, step: StepRecord) -> str:
        status = "ok" if step.success else "fail"
        action_type = step.action.type if step.action else "unknown"
        text = f"Step {step.num}: {action_type} [{status}]"
        if step.strategy_used:
            text += f" via {step.strategy_used}"
        if step.was_recovery:
            text += " (recovery)"
        return text

    def clear(self) -> None:
        """Reset working memory for a new episode."""
        self._steps = []
        self._compressed_history = []
