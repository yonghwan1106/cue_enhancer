"""Tests for CUE Efficiency Engine module."""

import asyncio

from cue.types import OptimizationResult, SubTask


class TestStepOptimizer:
    def _get_optimizer(self):
        from cue.efficiency.step_optimizer import StepOptimizer
        return StepOptimizer()

    def test_empty_plan(self):
        opt = self._get_optimizer()
        result_tasks, result = opt.optimize_plan([])
        assert result_tasks == []
        assert result.original_steps == 0

    def test_no_optimization_needed(self):
        opt = self._get_optimizer()
        tasks = [SubTask(description="Click save button", action_type="click")]
        result_tasks, result = opt.optimize_plan(tasks)
        assert len(result_tasks) == 1

    def test_batch_similar_actions(self):
        opt = self._get_optimizer()
        tasks = [
            SubTask(description=f"Format cell {i}", action_type="format", target_region="cells")
            for i in range(5)
        ]
        result_tasks, result = opt.optimize_plan(tasks)
        assert len(result_tasks) < 5
        assert "batch_similar_actions" in result.methods_applied

    def test_no_batch_for_different_types(self):
        opt = self._get_optimizer()
        tasks = [
            SubTask(description="Click button", action_type="click"),
            SubTask(description="Type text", action_type="type"),
            SubTask(description="Scroll down", action_type="scroll"),
        ]
        result_tasks, result = opt.optimize_plan(tasks)
        assert len(result_tasks) == 3

    def test_eliminate_nav_verification(self):
        opt = self._get_optimizer()
        # Implementation drops consecutive duplicate verification steps
        tasks = [
            SubTask(description="Click save", action_type="click"),
            SubTask(description="Verify saved", action_type="verify", is_verification_only=True),
            SubTask(description="Verify again", action_type="verify", is_verification_only=True),
            SubTask(description="Close dialog", action_type="click"),
        ]
        result_tasks, result = opt.optimize_plan(tasks)
        assert len(result_tasks) <= 3  # Second verify eliminated


class TestLatencyOptimizer:
    def _get_optimizer(self):
        from cue.efficiency.latency import LatencyOptimizer
        return LatencyOptimizer(cache_ttl=5.0)

    def test_cache_miss_then_hit(self):
        opt = self._get_optimizer()

        async def compute():
            return {"result": 42}

        result1 = asyncio.run(opt.get_or_compute("key1", compute))
        assert result1 == {"result": 42}
        assert opt.hit_rate < 1.0

        result2 = asyncio.run(opt.get_or_compute("key1", compute))
        assert result2 == {"result": 42}
        assert opt.hit_rate > 0.0

    def test_different_keys(self):
        opt = self._get_optimizer()
        call_count = 0

        async def compute():
            nonlocal call_count
            call_count += 1
            return call_count

        r1 = asyncio.run(opt.get_or_compute("a", compute))
        r2 = asyncio.run(opt.get_or_compute("b", compute))
        assert r1 != r2

    def test_invalidate(self):
        opt = self._get_optimizer()

        async def compute():
            return "data"

        asyncio.run(opt.get_or_compute("k", compute))
        opt.invalidate()
        assert opt.hit_rate == 0.0


class TestContextManager:
    def _get_manager(self):
        from cue.efficiency.context import ContextManager
        from cue.config import EfficiencyConfig
        return ContextManager(EfficiencyConfig())

    def test_first_screenshot_is_full(self):
        mgr = self._get_manager()
        mode = mgr.should_send_screenshot("hash1", "tree1")
        assert mode == "full"

    def test_same_screenshot_is_skip(self):
        mgr = self._get_manager()
        mgr.should_send_screenshot("hash1", "tree1")
        mode = mgr.should_send_screenshot("hash1", "tree1")
        assert mode == "skip"

    def test_changed_screenshot_is_full(self):
        mgr = self._get_manager()
        mgr.should_send_screenshot("hash1", "tree1")
        mode = mgr.should_send_screenshot("hash2", "tree2")
        assert mode == "full"


class TestEfficiencyEngine:
    def _get_engine(self):
        from cue.efficiency.enhancer import EfficiencyEngine
        from cue.config import EfficiencyConfig
        return EfficiencyEngine(EfficiencyConfig())

    def test_init(self):
        engine = self._get_engine()
        assert engine is not None

    def test_optimize_plan_passthrough(self):
        engine = self._get_engine()
        tasks = [SubTask(description="Click button")]
        result_tasks, result = engine.optimize_plan(tasks)
        assert isinstance(result, OptimizationResult)

    def test_cache_stats(self):
        engine = self._get_engine()
        stats = engine.get_cache_stats()
        assert "hit_rate" in stats
