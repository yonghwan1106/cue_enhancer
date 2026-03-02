"""Checkpoint & Recovery manager for CUE verification."""

from __future__ import annotations

import logging
import time

from cue.types import Action, Checkpoint

logger = logging.getLogger(__name__)


class CheckpointManager:
    """Saves state snapshots and supports rollback to prior checkpoints."""

    MAX_CHECKPOINTS = 10
    MAX_ROLLBACK_DEPTH = 3

    def __init__(self) -> None:
        self._checkpoints: list[Checkpoint] = []

    async def save_checkpoint(
        self,
        screenshot_hash: str,
        a11y_tree_hash: str,
        step_num: int,
        subtask_index: int,
        action_history: list[Action],
    ) -> Checkpoint:
        """Save a checkpoint, evicting the oldest if over MAX_CHECKPOINTS."""
        cp = Checkpoint(
            step_num=step_num,
            screenshot_hash=screenshot_hash,
            a11y_tree_hash=a11y_tree_hash,
            action_history=list(action_history),
            current_subtask_index=subtask_index,
            timestamp=time.time(),
        )
        self._checkpoints.append(cp)
        if len(self._checkpoints) > self.MAX_CHECKPOINTS:
            self._checkpoints.pop(0)
        logger.debug("Checkpoint saved at step %d (total: %d)", step_num, len(self._checkpoints))
        return cp

    def get_latest(self) -> Checkpoint | None:
        """Return the most recent checkpoint, or None if empty."""
        if not self._checkpoints:
            return None
        return self._checkpoints[-1]

    def get_at_step(self, step_num: int) -> Checkpoint | None:
        """Return the checkpoint at a specific step number, or None."""
        for cp in reversed(self._checkpoints):
            if cp.step_num == step_num:
                return cp
        return None

    def truncate_after(self, step_num: int) -> None:
        """Remove all checkpoints saved after the given step number."""
        before = len(self._checkpoints)
        self._checkpoints = [cp for cp in self._checkpoints if cp.step_num <= step_num]
        removed = before - len(self._checkpoints)
        if removed:
            logger.debug("Truncated %d checkpoint(s) after step %d", removed, step_num)

    def clear(self) -> None:
        """Reset all checkpoints."""
        self._checkpoints.clear()
        logger.debug("All checkpoints cleared")
