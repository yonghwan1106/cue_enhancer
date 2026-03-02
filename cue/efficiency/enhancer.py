"""EfficiencyEngine — unified facade over step, latency, and context optimizers."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from cue.config import EfficiencyConfig
from cue.efficiency.context import ContextManager
from cue.efficiency.latency import LatencyOptimizer
from cue.efficiency.step_optimizer import StepOptimizer
from cue.types import OptimizationResult, SubTask


class EfficiencyEngine:
    """Facade that wires StepOptimizer, LatencyOptimizer, and ContextManager.

    Components are lazily constructed on first use so modules that are
    disabled in config never allocate resources.
    """

    def __init__(self, config: EfficiencyConfig) -> None:
        self._config = config
        self._step_optimizer: StepOptimizer | None = None
        self._latency_optimizer: LatencyOptimizer | None = None
        self._context_manager: ContextManager | None = None

    # ── Lazy accessors ───────────────────────────────────────

    def _get_step_optimizer(self) -> StepOptimizer:
        if self._step_optimizer is None:
            self._step_optimizer = StepOptimizer()
        return self._step_optimizer

    def _get_latency_optimizer(self) -> LatencyOptimizer:
        if self._latency_optimizer is None:
            self._latency_optimizer = LatencyOptimizer(
                cache_ttl=self._config.cache_ttl_seconds
            )
        return self._latency_optimizer

    def _get_context_manager(self) -> ContextManager:
        if self._context_manager is None:
            self._context_manager = ContextManager(self._config)
        return self._context_manager

    # ── Public API ───────────────────────────────────────────

    def optimize_plan(
        self,
        subtasks: list[SubTask],
        app_knowledge: dict[str, Any] | None = None,
    ) -> tuple[list[SubTask], OptimizationResult]:
        """Optimize a subtask plan using the StepOptimizer.

        Returns the original plan unchanged if step optimization is disabled.
        """
        if not self._config.enable_step_optimizer:
            return subtasks, OptimizationResult(
                original_steps=len(subtasks),
                optimized_steps=len(subtasks),
                reduction_pct=0.0,
                methods_applied=[],
            )
        return self._get_step_optimizer().optimize_plan(subtasks, app_knowledge)

    async def get_cached_state(
        self,
        key: str,
        compute_fn: Callable[[], Awaitable[Any]],
    ) -> Any:
        """Return a cached grounding/state result, or compute and cache it.

        Falls through to compute_fn directly when latency optimizer is disabled.
        """
        if not self._config.enable_latency_optimizer:
            return await compute_fn()
        return await self._get_latency_optimizer().get_or_compute(key, compute_fn)

    def should_send_screenshot(
        self,
        screenshot_hash: str,
        a11y_hash: str,
    ) -> str:
        """Decide screenshot send policy: 'skip' | 'crop' | 'full'.

        Always returns 'full' when context manager is disabled.
        """
        if not self._config.enable_context_manager:
            return "full"
        return self._get_context_manager().should_send_screenshot(
            screenshot_hash, a11y_hash
        )

    def get_cache_stats(self) -> dict[str, Any]:
        """Return latency cache statistics.

        Returns zeroed stats when the latency optimizer has not been used.
        """
        if self._latency_optimizer is None:
            return {"hit_rate": 0.0, "enabled": False}
        return {
            "hit_rate": self._latency_optimizer.hit_rate,
            "enabled": self._config.enable_latency_optimizer,
        }

    def invalidate_cache(self) -> None:
        """Clear the latency cache if it has been initialised."""
        if self._latency_optimizer is not None:
            self._latency_optimizer.invalidate()
