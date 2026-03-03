"""BenchmarkRunner — orchestrates a full suite run."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from cue.config import CUEConfig, EnhancerLevel
from cue.types import BenchmarkResult, BenchmarkTask, FailureCategory, TaskMetrics
from cue.benchmark.task_loader import TaskLoader
from cue.benchmark.metrics import MetricsCollector
from cue.benchmark.checkers import SuccessChecker

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """Run a benchmark suite and return aggregated results."""

    def __init__(
        self,
        config: CUEConfig | None = None,
        dry_run: bool = False,
    ) -> None:
        self._config = config or CUEConfig()
        self._loader = TaskLoader()
        self._collector = MetricsCollector()
        self._checker = SuccessChecker()
        self._dry_run = dry_run

    async def run_suite(
        self,
        suite: str = "mini",
        max_tasks: int | None = None,
    ) -> BenchmarkResult:
        """Load tasks and run them through CUEAgent.

        Args:
            suite: Name of the benchmark suite YAML file.
            max_tasks: Optional limit on number of tasks to run.

        When dry_run=True, simulates execution without Claude API calls
        to validate the pipeline end-to-end.
        """
        tasks_dir = self._config.benchmark.tasks_dir
        tasks = self._loader.load_suite(suite, tasks_dir)

        if not tasks:
            return BenchmarkResult(suite_name=suite)

        if max_tasks is not None:
            tasks = tasks[:max_tasks]

        paired: list[tuple[BenchmarkTask, TaskMetrics]] = []

        for i, task in enumerate(tasks):
            logger.info(
                "[%d/%d] Running task %s (%s, %s)",
                i + 1, len(tasks), task.id, task.app, task.difficulty,
            )
            metrics = await self._run_single_task(task)
            paired.append((task, metrics))
            logger.info(
                "  → %s (steps=%d, time=%.1fs)",
                "PASS" if metrics.success else "FAIL",
                metrics.steps_taken,
                metrics.total_time,
            )

        return self._collector.aggregate_with_tasks(
            paired, suite_name=suite, config_name="full_cue"
        )

    async def _run_single_task(self, task: BenchmarkTask) -> TaskMetrics:
        """Run a single benchmark task and return its metrics."""
        self._collector.start_task(task)

        if self._dry_run:
            return await self._run_dry(task)

        return await self._run_live(task)

    async def _run_dry(self, task: BenchmarkTask) -> TaskMetrics:
        """Dry-run mode: simulate task execution without Claude API.

        Validates the full pipeline (loader → runner → checker → metrics)
        without incurring API costs. Reports simulated success based on
        task difficulty.
        """
        # Simulate step timing
        steps = task.human_baseline_steps or 3
        for step_num in range(1, steps + 1):
            await asyncio.sleep(0.01)  # minimal delay
            self._collector.record_step(step_num, "simulated", True, 0)

        # Simulate success rate by difficulty
        import random
        success_prob = {"easy": 0.95, "medium": 0.75, "hard": 0.50}
        success = random.random() < success_prob.get(task.difficulty, 0.7)

        failure_cat = None if success else FailureCategory.UNKNOWN
        failure_reason = "" if success else "dry_run simulated failure"

        return self._collector.end_task(
            success=success,
            failure_category=failure_cat,
            failure_reason=failure_reason,
        )

    async def _run_live(self, task: BenchmarkTask) -> TaskMetrics:
        """Live mode: run task with real CUEAgent and Claude API."""
        from cue.agent import CUEAgent
        from cue.benchmark.env_extractor import EnvStateExtractor

        agent = CUEAgent(config=self._config)
        extractor = EnvStateExtractor()

        # Capture initial screenshot hash
        initial_hash = await extractor.extract_initial_screenshot_hash()

        try:
            # Run the task through CUEAgent
            result = await asyncio.wait_for(
                agent.run(task.instruction),
                timeout=task.timeout_seconds,
            )

            # Record steps from the agent's step records
            # CUEAgent.run() returns TaskResult with steps_taken
            steps = result.steps_taken or 1
            for step_num in range(1, steps + 1):
                self._collector.record_step(
                    step_num,
                    "agent_step",
                    True,
                    0,  # token count not available from TaskResult
                )

            # Extract environment state for success checking
            env_state = await extractor.extract(task)
            env_state["initial_screenshot_hash"] = initial_hash

            # Check success criteria
            check_success, check_reason = self._checker.check(
                task.success_criteria, env_state
            )

            # Use checker result, but also consider agent's own assessment
            success = check_success
            failure_cat = None
            failure_reason = ""

            if not success:
                failure_reason = check_reason
                # Categorize failure based on task's failure_type
                failure_cat = _map_failure_type(task.failure_type)

        except asyncio.TimeoutError:
            success = False
            failure_cat = FailureCategory.TIMEOUT
            failure_reason = f"Task timed out after {task.timeout_seconds}s"
        except Exception as exc:
            success = False
            failure_cat = FailureCategory.EXECUTION
            failure_reason = f"Execution error: {exc}"
            logger.error("Task %s failed with exception: %s", task.id, exc)

        return self._collector.end_task(
            success=success,
            failure_category=failure_cat,
            failure_reason=failure_reason,
        )


def _map_failure_type(failure_type: str) -> FailureCategory:
    """Map a task's failure_type string to a FailureCategory enum."""
    mapping = {
        "grounding": FailureCategory.GROUNDING,
        "planning": FailureCategory.PLANNING,
        "execution": FailureCategory.EXECUTION,
        "navigation": FailureCategory.NAVIGATION,
        "verification": FailureCategory.VERIFICATION,
    }
    return mapping.get(failure_type, FailureCategory.UNKNOWN)
