"""ThreeLayerMemory — integration manager for all memory layers."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from cue.config import MemoryConfig
from cue.types import Episode, EpisodeRecord, Lesson, MemoryContext


class ThreeLayerMemory:
    """Integrates working, episodic, and semantic memory layers."""

    def __init__(self, config: MemoryConfig) -> None:
        self._config = config
        db_dir = Path(config.db_dir).expanduser()

        # Lazy-import to avoid circular imports at module load time
        from cue.memory.working import WorkingMemory
        from cue.memory.episodic import EpisodicMemory
        from cue.memory.semantic import SemanticMemory
        from cue.memory.compression import ACONCompressor
        from cue.memory.reflexion import ReflexionEngine

        self.working = WorkingMemory(max_steps=config.working_memory_steps)
        self.episodic = EpisodicMemory(db_path=str(db_dir / "episodic.db"))
        self.semantic = SemanticMemory(db_path=str(db_dir / "semantic.db"))
        self.compressor = ACONCompressor()
        self.reflexion = ReflexionEngine()

    async def remember(self, task: str, app: str) -> MemoryContext:
        """Retrieve relevant lessons and similar episodes for a task."""
        lessons = await self.semantic.recall(
            task=task,
            app=app,
            top_k=self._config.max_lessons_per_query,
        )
        similar_episodes = await self.episodic.find_similar(
            task=task,
            app=app,
            top_k=self._config.max_episodes_per_query,
        )

        context = MemoryContext(
            lessons=lessons,
            similar_episodes=similar_episodes,
            total_tokens=self._estimate_tokens(lessons, similar_episodes),
        )

        if context.total_tokens > self._config.memory_token_budget:
            context = self._trim_to_budget(context, self._config.memory_token_budget)

        return context

    async def learn(self, episode: Episode) -> None:
        """Store the episode, extract lessons, and run episodic cleanup."""
        reflection = await self.reflexion.reflect(episode)

        failure_patterns = self._extract_failure_patterns(episode)
        recovery_strategies = self._extract_recovery_strategies(episode)
        steps_summary = self._build_steps_summary(episode)

        record = EpisodeRecord(
            id=episode.id or str(uuid.uuid4()),
            task=episode.task,
            app=episode.app,
            success=episode.success,
            total_steps=len(episode.steps),
            steps_summary=steps_summary,
            failure_patterns=failure_patterns,
            recovery_strategies=recovery_strategies,
            reflection=reflection,
            created_at=episode.end_time or time.time(),
        )

        await self.episodic.store(record)

        lessons = self._extract_lessons(episode)
        for lesson in lessons:
            await self.semantic.upsert(lesson)

        await self.episodic.cleanup(max_age_days=self._config.episodic_ttl_days)

    def _extract_lessons(self, episode: Episode) -> list[Lesson]:
        """Find failure->success pairs and convert to Lesson objects."""
        lessons: list[Lesson] = []
        steps = episode.steps

        for i, step in enumerate(steps):
            if step.success or not step.was_recovery:
                continue
            # This step was a failed recovery attempt — look forward for success
            for j in range(i + 1, min(i + 4, len(steps))):
                later = steps[j]
                if later.success and later.was_recovery:
                    situation = step.context_description or step.action.type
                    failed_approach = step.original_action or step.action.type
                    successful_approach = (
                        later.strategy_used or later.action.type
                    )
                    lesson = Lesson(
                        id=str(uuid.uuid4()),
                        app=episode.app,
                        situation=situation,
                        failed_approach=failed_approach,
                        successful_approach=successful_approach,
                        confidence=0.7,
                        success_count=1,
                        failure_count=0,
                        created_at=time.time(),
                        last_used=time.time(),
                        task_context=episode.task,
                        text=(
                            f"In {episode.app}, when {situation}, "
                            f"'{failed_approach}' fails; use '{successful_approach}' instead."
                        ),
                        reinforcement_count=0,
                    )
                    lessons.append(lesson)
                    break

        # Also extract from milestone steps: direct success after a failure
        for i, step in enumerate(steps):
            if not step.success:
                continue
            if i > 0 and not steps[i - 1].success and step.strategy_used:
                situation = step.context_description or step.action.type
                failed_approach = steps[i - 1].action.type
                successful_approach = step.strategy_used
                lesson = Lesson(
                    id=str(uuid.uuid4()),
                    app=episode.app,
                    situation=situation,
                    failed_approach=failed_approach,
                    successful_approach=successful_approach,
                    confidence=0.65,
                    success_count=1,
                    failure_count=1,
                    created_at=time.time(),
                    last_used=time.time(),
                    task_context=episode.task,
                    text=(
                        f"In {episode.app}, after '{failed_approach}' fails, "
                        f"'{successful_approach}' succeeds."
                    ),
                    reinforcement_count=0,
                )
                lessons.append(lesson)

        return lessons

    def _trim_to_budget(
        self, context: MemoryContext, max_tokens: int
    ) -> MemoryContext:
        """Trim context to fit within token budget."""
        # Estimate 50 tokens per lesson, 80 per episode
        tokens_per_lesson = 50
        tokens_per_episode = 80

        lessons = list(context.lessons)
        episodes = list(context.similar_episodes)

        while episodes and self._estimate_tokens(lessons, episodes) > max_tokens:
            episodes.pop()

        while lessons and self._estimate_tokens(lessons, episodes) > max_tokens:
            lessons.pop()

        return MemoryContext(
            lessons=lessons,
            similar_episodes=episodes,
            total_tokens=self._estimate_tokens(lessons, episodes),
        )

    def _estimate_tokens(
        self, lessons: list[Lesson], episodes: list[EpisodeRecord]
    ) -> int:
        """Rough token estimate: 50 per lesson, 80 per episode."""
        return len(lessons) * 50 + len(episodes) * 80

    def _extract_failure_patterns(self, episode: Episode) -> list[str]:
        patterns: dict[str, int] = {}
        for step in episode.steps:
            if not step.success:
                key = step.action.type if step.action else "unknown"
                patterns[key] = patterns.get(key, 0) + 1
        return [f"{k}:{v}" for k, v in patterns.items()]

    def _extract_recovery_strategies(self, episode: Episode) -> list[str]:
        strategies: list[str] = []
        for step in episode.steps:
            if step.was_recovery and step.success and step.strategy_used:
                if step.strategy_used not in strategies:
                    strategies.append(step.strategy_used)
        return strategies

    def _build_steps_summary(self, episode: Episode) -> str:
        total = len(episode.steps)
        successes = sum(1 for s in episode.steps if s.success)
        return f"{successes}/{total} steps succeeded"
