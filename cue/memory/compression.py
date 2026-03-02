"""ACON Context Compression — adaptive compression of step history."""

from __future__ import annotations

from cue.types import CompressedHistory, StepRecord


class ACONCompressor:
    """Compresses step history into token-efficient representations."""

    RECENT_WINDOW: int = 5
    MID_WINDOW: int = 5
    MAX_TOKENS: int = 2000

    def compress(
        self, step_history: list[StepRecord], max_tokens: int = 2000
    ) -> CompressedHistory:
        """Compress step history using 3-zone ACON strategy.

        - <=5 steps: all as recent_full
        - 6-10 steps: recent 5 full, rest as mid_summary
        - 11+ steps: recent 5 full, next 5 mid_summary, rest as old_summary
        """
        n = len(step_history)

        if n <= self.RECENT_WINDOW:
            token_count = self._count_tokens_full(step_history)
            return CompressedHistory(
                recent_full=list(step_history),
                mid_summary=[],
                old_summary=None,
                token_count=token_count,
            )

        recent = step_history[-self.RECENT_WINDOW :]

        if n <= self.RECENT_WINDOW + self.MID_WINDOW:
            mid_steps = step_history[: n - self.RECENT_WINDOW]
            mid_summaries = [self._summarize_step(s) for s in mid_steps]
            token_count = self._count_tokens_full(recent) + self._count_tokens_summaries(
                mid_summaries
            )
            return CompressedHistory(
                recent_full=recent,
                mid_summary=mid_summaries,
                old_summary=None,
                token_count=token_count,
            )

        # 11+ steps
        mid_start = n - self.RECENT_WINDOW - self.MID_WINDOW
        mid_steps = step_history[mid_start : n - self.RECENT_WINDOW]
        old_steps = step_history[:mid_start]

        mid_summaries = [self._summarize_step(s) for s in mid_steps]
        old_paragraph = self._paragraph_summary(old_steps) if old_steps else None

        token_count = (
            self._count_tokens_full(recent)
            + self._count_tokens_summaries(mid_summaries)
            + (self._count_tokens_text(old_paragraph) if old_paragraph else 0)
        )

        return CompressedHistory(
            recent_full=recent,
            mid_summary=mid_summaries,
            old_summary=old_paragraph,
            token_count=token_count,
        )

    def _summarize_step(self, step: StepRecord) -> str:
        """Produce a one-line summary of a single step."""
        status = "ok" if step.success else "fail"
        action_type = step.action.type if step.action else "unknown"
        parts = [f"Step {step.num}: {action_type} [{status}]"]
        if step.strategy_used:
            parts.append(f"strategy={step.strategy_used}")
        if step.was_recovery:
            parts.append("recovery")
        if step.context_description:
            desc = step.context_description[:60]
            parts.append(f"ctx={desc}")
        return " | ".join(parts)

    def _paragraph_summary(self, steps: list[StepRecord]) -> str:
        """Produce a brief paragraph summarizing a block of steps."""
        if not steps:
            return ""
        total = len(steps)
        successes = sum(1 for s in steps if s.success)
        failures = total - successes
        action_types = list({s.action.type for s in steps if s.action})
        actions_str = ", ".join(action_types[:5])
        recovery_count = sum(1 for s in steps if s.was_recovery)
        summary = (
            f"Earlier {total} steps ({successes} success, {failures} failed): "
            f"actions=[{actions_str}]"
        )
        if recovery_count:
            summary += f", {recovery_count} recoveries"
        return summary

    def _count_tokens_full(self, steps: list[StepRecord]) -> int:
        """Estimate token count for full step records (~300 per step)."""
        return len(steps) * 300

    def _count_tokens_summaries(self, summaries: list[str]) -> int:
        """Estimate token count for one-line summaries."""
        return sum(self._count_tokens_text(s) for s in summaries)

    def _count_tokens_text(self, text: str) -> int:
        """Estimate token count for a text string (~4 chars per token)."""
        if not text:
            return 0
        return max(1, len(text) // 4)
