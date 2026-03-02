"""Tests for CUE Verification extensions (Phase 2)."""

import asyncio

from cue.types import (
    Action,
    ActionReflection,
    Checkpoint,
    GlobalReflection,
    ReflectionDecision,
    StepRecord,
    SubTask,
    TrajectoryReflection,
    VerificationResult,
)


class TestReflectionEngine:
    def _get_engine(self):
        from cue.verification.reflection import ReflectionEngine
        return ReflectionEngine()

    def _make_step(self, num, success=True, reason=""):
        return StepRecord(
            num=num,
            action=Action(type="left_click", coordinate=(100, 100)),
            success=success,
            verification=VerificationResult(
                tier=1, success=success, reason=reason
            ),
        )

    def test_action_reflect_success(self):
        engine = self._get_engine()
        step = self._make_step(1, success=True)
        result = asyncio.run(engine.reflect_action(step))
        assert isinstance(result, ActionReflection)
        assert result.decision == ReflectionDecision.CONTINUE

    def test_action_reflect_failure(self):
        engine = self._get_engine()
        step = self._make_step(1, success=False, reason="click missed")
        result = asyncio.run(engine.reflect_action(step))
        assert result.decision == ReflectionDecision.RETRY

    def test_trajectory_continue(self):
        engine = self._get_engine()
        steps = [self._make_step(i, success=True) for i in range(3)]
        result = asyncio.run(engine.reflect_trajectory(steps, "test task"))
        assert isinstance(result, TrajectoryReflection)
        assert result.making_progress is True

    def test_trajectory_replan_repeated_failures(self):
        engine = self._get_engine()
        steps = [
            self._make_step(1, success=False, reason="same error"),
            self._make_step(2, success=False, reason="same error"),
            self._make_step(3, success=False, reason="same error"),
        ]
        result = asyncio.run(engine.reflect_trajectory(steps, "test task"))
        assert result.making_progress is False
        assert result.decision in (ReflectionDecision.REPLAN, ReflectionDecision.STRATEGY_CHANGE)

    def test_trajectory_too_few_steps(self):
        engine = self._get_engine()
        steps = [self._make_step(1)]
        result = asyncio.run(engine.reflect_trajectory(steps, "test"))
        assert result.making_progress is True

    def test_global_on_track(self):
        engine = self._get_engine()
        steps = [self._make_step(i, success=True) for i in range(5)]
        subtasks = [SubTask(description=f"task {i}") for i in range(3)]
        result = asyncio.run(engine.reflect_global(steps, "test", subtasks, 2))
        assert isinstance(result, GlobalReflection)
        assert result.on_track is True

    def test_global_efficiency_crisis(self):
        engine = self._get_engine()
        # 26+ steps consumed (>50% of 50), but only 0 of 5 subtasks done
        steps = [self._make_step(i) for i in range(26)]
        subtasks = [SubTask(description=f"task {i}") for i in range(5)]
        result = asyncio.run(engine.reflect_global(steps, "test", subtasks, 0))
        assert result.on_track is False
        assert result.decision == ReflectionDecision.STRATEGY_CHANGE


class TestCheckpointManager:
    def _get_manager(self):
        from cue.verification.checkpoint import CheckpointManager
        return CheckpointManager()

    def test_save_and_get(self):
        mgr = self._get_manager()
        asyncio.run(mgr.save_checkpoint(
            screenshot_hash="abc", a11y_tree_hash="def",
            step_num=1, subtask_index=0, action_history=[],
        ))
        latest = mgr.get_latest()
        assert latest is not None
        assert latest.step_num == 1

    def test_max_checkpoints(self):
        mgr = self._get_manager()
        for i in range(15):
            asyncio.run(mgr.save_checkpoint(
                screenshot_hash=f"h{i}", a11y_tree_hash=f"t{i}",
                step_num=i, subtask_index=0, action_history=[],
            ))
        assert len(mgr._checkpoints) <= 10

    def test_get_at_step(self):
        mgr = self._get_manager()
        for i in range(5):
            asyncio.run(mgr.save_checkpoint(
                screenshot_hash=f"h{i}", a11y_tree_hash=f"t{i}",
                step_num=i + 1, subtask_index=0, action_history=[],
            ))
        cp = mgr.get_at_step(3)
        assert cp is not None
        assert cp.step_num == 3

    def test_truncate_after(self):
        mgr = self._get_manager()
        for i in range(5):
            asyncio.run(mgr.save_checkpoint(
                screenshot_hash=f"h{i}", a11y_tree_hash=f"t{i}",
                step_num=i + 1, subtask_index=0, action_history=[],
            ))
        mgr.truncate_after(3)
        assert len(mgr._checkpoints) == 3
        assert mgr.get_latest().step_num == 3

    def test_clear(self):
        mgr = self._get_manager()
        asyncio.run(mgr.save_checkpoint(
            screenshot_hash="a", a11y_tree_hash="b",
            step_num=1, subtask_index=0, action_history=[],
        ))
        mgr.clear()
        assert len(mgr._checkpoints) == 0
        assert mgr.get_latest() is None


class TestTier3Verifier:
    """Basic tests for Tier3Verifier (without actual API calls)."""

    def _get_verifier(self):
        from cue.verification.tier3 import Tier3Verifier

        class MockClient:
            pass

        return Tier3Verifier(client=MockClient(), model="test-model")

    def test_call_limit(self):
        v = self._get_verifier()
        v.call_count = 3  # At limit
        import numpy as np
        img = np.zeros((10, 10, 3), dtype=np.uint8)
        result = asyncio.run(v.verify(img, img, "test action"))
        assert result.success is False
        assert "limit" in result.reason.lower()

    def test_reset_episode(self):
        v = self._get_verifier()
        v.call_count = 3
        v.reset_episode()
        assert v.call_count == 0
