"""Reflexion Self-reflection Engine — generates natural language reflections."""

from __future__ import annotations

import asyncio

from cue.types import Episode


class ReflexionEngine:
    """Generates reflective summaries of completed episodes."""

    MAX_REFLECTION_TOKENS: int = 200

    async def reflect(self, episode: Episode) -> str:
        """Generate a natural language reflection for the episode."""
        return await asyncio.to_thread(self._reflect_sync, episode)

    def _reflect_sync(self, episode: Episode) -> str:
        if episode.success:
            text = self._reflect_success(episode)
        else:
            text = self._reflect_failure(episode)
        return self._trim_to_budget(text)

    def _reflect_success(self, episode: Episode) -> str:
        """Summarize what made this episode effective."""
        total = len(episode.steps)
        recoveries = [s for s in episode.steps if s.was_recovery]
        strategies = list({s.strategy_used for s in episode.steps if s.strategy_used})
        milestones = [s for s in episode.steps if s.is_milestone]

        parts = [f"Task '{episode.task}' completed successfully in {total} steps."]

        if strategies:
            parts.append(f"Effective strategies: {', '.join(strategies[:3])}.")

        if milestones:
            milestone_descs = [
                s.context_description for s in milestones[:3] if s.context_description
            ]
            if milestone_descs:
                parts.append(f"Key milestones: {'; '.join(milestone_descs)}.")

        if recoveries:
            parts.append(
                f"Recovered from {len(recoveries)} failure(s) during execution."
            )

        duration = episode.end_time - episode.start_time
        if duration > 0:
            parts.append(f"Total time: {duration:.1f}s.")

        return " ".join(parts)

    def _reflect_failure(self, episode: Episode) -> str:
        """Analyze failure causes and suggest improvements."""
        total = len(episode.steps)
        failed_steps = [s for s in episode.steps if not s.success]
        strategies_tried = list({s.strategy_used for s in episode.steps if s.strategy_used})

        parts = [
            f"Task '{episode.task}' failed after {total} steps "
            f"({len(failed_steps)} failures)."
        ]

        if strategies_tried:
            parts.append(f"Strategies attempted: {', '.join(strategies_tried[:3])}.")

        # Identify dominant failure action type
        if failed_steps:
            fail_types: dict[str, int] = {}
            for s in failed_steps:
                t = s.action.type if s.action else "unknown"
                fail_types[t] = fail_types.get(t, 0) + 1
            dominant = max(fail_types, key=lambda k: fail_types[k])
            parts.append(
                f"Most failures on '{dominant}' action "
                f"({fail_types[dominant]} times)."
            )

        # Suggest: if recoveries failed too, mention that
        recoveries = [s for s in episode.steps if s.was_recovery]
        if recoveries:
            failed_recoveries = [s for s in recoveries if not s.success]
            if failed_recoveries:
                parts.append(
                    f"Recovery attempts also failed "
                    f"({len(failed_recoveries)}/{len(recoveries)})."
                )
            parts.append("Consider alternative strategies or verifying UI state first.")
        else:
            parts.append("No recovery was attempted; consider adding fallback logic.")

        return " ".join(parts)

    def _trim_to_budget(self, text: str) -> str:
        """Trim text to MAX_REFLECTION_TOKENS (approx 4 chars/token)."""
        max_chars = self.MAX_REFLECTION_TOKENS * 4
        if len(text) <= max_chars:
            return text
        # Trim at last sentence boundary within budget
        truncated = text[:max_chars]
        last_period = truncated.rfind(". ")
        if last_period > max_chars // 2:
            return truncated[: last_period + 1]
        return truncated.rstrip() + "..."
