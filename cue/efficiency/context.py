"""Context Manager — token-budget-aware context assembly for each agent step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Awaitable

from cue.config import EfficiencyConfig
from cue.types import CompressedHistory, MemoryContext, StepRecord

if TYPE_CHECKING:
    pass

# Rough token estimates per content type
_SCREENSHOT_TOKENS = 300   # compressed screenshot representation
_A11Y_TOKENS = 200         # accessibility tree text
_HISTORY_PER_STEP = 80     # tokens per step record in recent history
_LESSON_TOKENS = 60        # tokens per memory lesson


class ContextManager:
    """Assemble the minimum viable context for each agent step.

    Responsibilities:
    - Decide whether to send full/cropped/no screenshot based on hash deltas
    - Estimate token usage and trim context to stay within budget
    - Build a ready-to-use context dict for the agent loop
    """

    def __init__(self, config: EfficiencyConfig) -> None:
        self._config = config
        self._token_budget = config.token_budget_per_step
        self._prev_screenshot_hash: str | None = None
        self._prev_a11y_hash: str | None = None

    async def build_context(
        self,
        screenshot_hash: str,
        a11y_hash: str,
        step_history: list[StepRecord],
        memory_context: MemoryContext | None,
        compressor: Callable[[list[StepRecord]], Awaitable[CompressedHistory]] | None = None,
    ) -> dict[str, Any]:
        """Build an optimized context dict for the next agent call.

        Args:
            screenshot_hash: Hash of the current screenshot.
            a11y_hash: Hash of the current accessibility tree text.
            step_history: All step records so far in this episode.
            memory_context: Lessons/episodes from the memory module (may be None).
            compressor: Optional async callable that compresses step history.

        Returns:
            A dict with keys: screenshot_mode, history_text, memory_text,
            estimated_tokens, token_budget.
        """
        screenshot_mode = self.should_send_screenshot(screenshot_hash, a11y_hash)

        # Update hashes after decision
        self._prev_screenshot_hash = screenshot_hash
        self._prev_a11y_hash = a11y_hash

        # Compress or trim history to fit budget
        budget_remaining = self._token_budget
        history_text = ""

        if compressor is not None and step_history:
            compressed = await compressor(step_history)
            history_text = compressed.to_prompt_text()
            budget_remaining -= compressed.token_count
        elif step_history:
            # Fit as many recent steps as possible within budget
            max_steps = max(1, budget_remaining // _HISTORY_PER_STEP)
            recent = step_history[-max_steps:]
            history_text = "\n".join(s.to_detailed_text() for s in recent)
            budget_remaining -= len(recent) * _HISTORY_PER_STEP

        # Include memory context if budget allows
        memory_text = ""
        if memory_context is not None:
            estimated_memory = (
                len(memory_context.lessons) * _LESSON_TOKENS
                + len(memory_context.similar_episodes) * _LESSON_TOKENS
            )
            if estimated_memory <= budget_remaining:
                memory_text = memory_context.to_prompt_text()
                budget_remaining -= estimated_memory

        # Deduct screenshot cost from remaining budget estimate
        if screenshot_mode == "full":
            budget_remaining -= _SCREENSHOT_TOKENS
        elif screenshot_mode == "crop":
            budget_remaining -= _SCREENSHOT_TOKENS // 2

        return {
            "screenshot_mode": screenshot_mode,
            "history_text": history_text,
            "memory_text": memory_text,
            "estimated_tokens": self._token_budget - budget_remaining,
            "token_budget": self._token_budget,
        }

    def should_send_screenshot(
        self,
        current_hash: str,
        current_a11y_hash: str,
    ) -> str:
        """Decide how much visual information to send.

        Returns:
            "skip"  — screen is identical to the previous step; omit screenshot.
            "crop"  — only a11y tree changed (structural but not visual change);
                      send a cropped/region screenshot.
            "full"  — significant change or first step; send full screenshot.
        """
        if not self._config.enable_selective_screenshots:
            return "full"

        decision = "full"

        if (
            self._prev_screenshot_hash is not None
            and self._prev_a11y_hash is not None
        ):
            screenshot_same = current_hash == self._prev_screenshot_hash
            a11y_same = current_a11y_hash == self._prev_a11y_hash

            if screenshot_same and a11y_same:
                decision = "skip"
            elif screenshot_same and not a11y_same:
                # Structural change without visual change — partial crop is enough
                decision = "crop"

        # Always track the latest hashes so subsequent calls compare correctly
        self._prev_screenshot_hash = current_hash
        self._prev_a11y_hash = current_a11y_hash

        return decision

    def estimate_tokens(self, context_parts: dict[str, Any]) -> int:
        """Rough token estimate for a context parts dict.

        Counts characters across all string values and divides by 4
        (a standard heuristic for English text).
        """
        total_chars = 0
        for value in context_parts.values():
            if isinstance(value, str):
                total_chars += len(value)
            elif isinstance(value, (list, dict)):
                total_chars += len(str(value))
        return total_chars // 4
