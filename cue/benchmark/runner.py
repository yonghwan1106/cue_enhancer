"""BenchmarkRunner — orchestrates a full suite run."""

from __future__ import annotations

from cue.config import CUEConfig
from cue.types import BenchmarkResult
from cue.benchmark.task_loader import TaskLoader
from cue.benchmark.metrics import MetricsCollector
from cue.types import FailureCategory, TaskMetrics


class BenchmarkRunner:
    """Run a benchmark suite and return aggregated results."""

    def __init__(self, config: CUEConfig | None = None) -> None:
        self._config = config or CUEConfig()
        self._loader = TaskLoader()
        self._collector = MetricsCollector()

    async def run_suite(self, suite: str = "mini") -> BenchmarkResult:
        """Load tasks and simulate running them (mock implementation).

        Returns a BenchmarkResult with mock metrics so the CLI and tests work
        without a live environment.
        """
        tasks_dir = self._config.benchmark.tasks_dir
        tasks = self._loader.load_suite(suite, tasks_dir)

        if not tasks:
            return BenchmarkResult(suite_name=suite)

        paired = []
        for task in tasks:
            self._collector.start_task(task)
            # Mock: record two steps
            self._collector.record_step(1, "left_click", True, 200)
            self._collector.record_step(2, "type", True, 300)
            metrics = self._collector.end_task(success=True)
            paired.append((task, metrics))

        return self._collector.aggregate_with_tasks(
            paired, suite_name=suite, config_name="full_cue"
        )
