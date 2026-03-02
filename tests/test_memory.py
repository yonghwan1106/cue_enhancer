"""Tests for CUE Experience Memory module."""

import tempfile
from pathlib import Path

from cue.types import (
    Action,
    CompressedHistory,
    Episode,
    EpisodeRecord,
    Lesson,
    MemoryContext,
    StepRecord,
    VerificationResult,
)


class TestWorkingMemory:
    def _get_wm(self):
        from cue.memory.working import WorkingMemory
        return WorkingMemory(max_steps=5)

    def _make_step(self, num, success=True):
        return StepRecord(
            num=num,
            action=Action(type="left_click", coordinate=(100, 100)),
            success=success,
            verification=VerificationResult(tier=1, success=success),
            timestamp=1000.0 + num,
        )

    def test_add_steps(self):
        wm = self._get_wm()
        for i in range(3):
            wm.add_step(self._make_step(i + 1))
        assert len(wm._steps) == 3

    def test_compression_on_overflow(self):
        wm = self._get_wm()
        for i in range(8):
            wm.add_step(self._make_step(i + 1))
        assert len(wm._steps) <= 5
        assert len(wm._compressed_history) > 0

    def test_get_context(self):
        wm = self._get_wm()
        for i in range(3):
            wm.add_step(self._make_step(i + 1))
        ctx = wm.get_context()
        assert "recent_steps" in ctx
        assert len(ctx["recent_steps"]) <= 5

    def test_clear(self):
        wm = self._get_wm()
        wm.add_step(self._make_step(1))
        wm.clear()
        assert len(wm._steps) == 0


class TestACONCompressor:
    def _get_compressor(self):
        from cue.memory.compression import ACONCompressor
        return ACONCompressor()

    def _make_step(self, num, success=True):
        return StepRecord(
            num=num,
            action=Action(type="left_click"),
            success=success,
        )

    def test_no_compression_few_steps(self):
        comp = self._get_compressor()
        steps = [self._make_step(i) for i in range(3)]
        result = comp.compress(steps)
        assert isinstance(result, CompressedHistory)
        assert len(result.recent_full) == 3
        assert result.old_summary is None

    def test_mid_compression(self):
        comp = self._get_compressor()
        steps = [self._make_step(i) for i in range(8)]
        result = comp.compress(steps)
        assert len(result.recent_full) == 5
        assert len(result.mid_summary) == 3
        assert result.old_summary is None

    def test_full_compression(self):
        comp = self._get_compressor()
        steps = [self._make_step(i) for i in range(15)]
        result = comp.compress(steps)
        assert len(result.recent_full) == 5
        assert len(result.mid_summary) == 5
        assert result.old_summary is not None

    def test_empty_steps(self):
        comp = self._get_compressor()
        result = comp.compress([])
        assert len(result.recent_full) == 0

    def test_to_prompt_text(self):
        comp = self._get_compressor()
        steps = [self._make_step(i) for i in range(12)]
        result = comp.compress(steps)
        text = result.to_prompt_text()
        assert "[Previous Summary]" in text
        assert "[Recent Steps]" in text


class TestEpisodicMemory:
    def _get_memory(self):
        from cue.memory.episodic import EpisodicMemory
        tmpdir = tempfile.mkdtemp()
        return EpisodicMemory(db_path=str(Path(tmpdir) / "episodic.db"))

    async def _async_test(self, coro):
        import asyncio
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_store_and_find(self):
        import asyncio
        mem = self._get_memory()
        record = EpisodeRecord(
            id="ep1", task="Sort column A", app="LibreOffice Calc",
            success=True, total_steps=5, reflection="Used Alt+D shortcut",
        )
        asyncio.run(mem.store(record))
        results = asyncio.run(mem.find_similar("Sort data", "LibreOffice Calc"))
        assert len(results) >= 1
        assert results[0].id == "ep1"

    def test_cleanup(self):
        import asyncio
        mem = self._get_memory()
        old_record = EpisodeRecord(
            id="old", task="Old task", app="App",
            success=False, total_steps=10,
            created_at=0.0,  # epoch = very old
        )
        asyncio.run(mem.store(old_record))
        asyncio.run(mem.cleanup(max_age_days=1))
        results = asyncio.run(mem.find_similar("Old task", "App"))
        assert len(results) == 0


class TestSemanticMemory:
    def _get_memory(self):
        from cue.memory.semantic import SemanticMemory
        tmpdir = tempfile.mkdtemp()
        return SemanticMemory(db_path=str(Path(tmpdir) / "semantic.db"))

    def test_upsert_and_recall(self):
        import asyncio
        mem = self._get_memory()
        lesson = Lesson(
            id="lesson1", app="Firefox",
            situation="Opening downloads",
            failed_approach="Click Downloads menu item",
            successful_approach="Use Ctrl+J shortcut",
            confidence=0.8,
        )
        asyncio.run(mem.upsert(lesson))
        results = asyncio.run(mem.recall("Check downloads", "Firefox"))
        assert len(results) >= 1
        assert results[0].successful_approach == "Use Ctrl+J shortcut"

    def test_confidence_increase_on_repeat(self):
        import asyncio
        mem = self._get_memory()
        lesson = Lesson(
            id="l1", app="Calc", situation="Open data menu",
            failed_approach="click", successful_approach="Alt+D",
            confidence=0.7,
        )
        asyncio.run(mem.upsert(lesson))
        # Upsert same situation with higher confidence
        # Formula: existing + (new - existing) * 0.3 = 0.7 + (1.0 - 0.7) * 0.3 = 0.79
        lesson2 = Lesson(
            id="l2", app="Calc", situation="Open data menu",
            failed_approach="click", successful_approach="Alt+D",
            confidence=1.0,
        )
        asyncio.run(mem.upsert(lesson2))
        results = asyncio.run(mem.recall("Data menu", "Calc"))
        assert results[0].confidence > 0.7


class TestReflexionEngine:
    def _get_engine(self):
        from cue.memory.reflexion import ReflexionEngine
        return ReflexionEngine()

    def test_reflect_success(self):
        import asyncio
        engine = self._get_engine()
        episode = Episode(
            id="ep1", task="Sort column", app="Calc", success=True,
            steps=[
                StepRecord(num=1, action=Action(type="key", text="Alt+D"), success=True, strategy_used="keyboard"),
                StepRecord(num=2, action=Action(type="left_click"), success=True),
            ],
        )
        result = asyncio.run(engine.reflect(episode))
        assert isinstance(result, str)
        assert len(result) > 0

    def test_reflect_failure(self):
        import asyncio
        engine = self._get_engine()
        episode = Episode(
            id="ep2", task="Sort column", app="Calc", success=False,
            steps=[
                StepRecord(
                    num=1, action=Action(type="left_click"), success=False,
                    verification=VerificationResult(tier=1, success=False, reason="click missed"),
                ),
            ],
        )
        result = asyncio.run(engine.reflect(episode))
        assert isinstance(result, str)


class TestMemoryContext:
    def test_to_prompt_text_empty(self):
        ctx = MemoryContext()
        assert ctx.to_prompt_text() == ""

    def test_to_prompt_text_with_lessons(self):
        ctx = MemoryContext(
            lessons=[Lesson(
                app="Firefox", situation="menu", failed_approach="click",
                successful_approach="shortcut", confidence=0.9,
            )],
        )
        text = ctx.to_prompt_text()
        assert "Past Lessons" in text
        assert "shortcut" in text
