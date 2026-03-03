"""Metrics collection and aggregation for benchmark runs."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cue.types import BenchmarkResult, BenchmarkTask, FailureCategory, TaskMetrics


@dataclass
class _StepRecord:
    step_num: int
    action_type: str
    success: bool
    tokens: int


@dataclass
class _TaskContext:
    task: BenchmarkTask
    start_time: float
    step_records: list[_StepRecord] = field(default_factory=list)
    tokens_total: int = 0
    api_calls: int = 0


class MetricsCollector:
    """Collect and aggregate metrics across benchmark task runs."""

    def __init__(self) -> None:
        self._current: _TaskContext | None = None

    # ------------------------------------------------------------------
    # Per-task lifecycle
    # ------------------------------------------------------------------

    def start_task(self, task: BenchmarkTask) -> None:
        """Record start time and reset per-task state."""
        self._current = _TaskContext(task=task, start_time=time.monotonic())

    def record_step(
        self,
        step_num: int,
        action_type: str,
        success: bool,
        tokens: int,
    ) -> None:
        """Track a single step within the current task."""
        if self._current is None:
            return
        self._current.step_records.append(
            _StepRecord(step_num=step_num, action_type=action_type, success=success, tokens=tokens)
        )
        self._current.tokens_total += tokens
        self._current.api_calls += 1

    def end_task(
        self,
        success: bool,
        failure_category: FailureCategory | None = None,
        failure_reason: str = "",
    ) -> TaskMetrics:
        """Finalise the current task and return its TaskMetrics."""
        ctx = self._current
        if ctx is None:
            return TaskMetrics()

        elapsed = time.monotonic() - ctx.start_time
        steps_taken = len(ctx.step_records)

        # step_efficiency_ratio
        baseline = ctx.task.human_baseline_steps or 1
        step_efficiency_ratio = steps_taken / baseline

        # first_attempt_success_rate — fraction of steps that succeeded on
        # first try (no preceding failure for the same step_num).
        first_attempts: dict[int, bool] = {}
        for rec in ctx.step_records:
            if rec.step_num not in first_attempts:
                first_attempts[rec.step_num] = rec.success
        if first_attempts:
            first_attempt_success_rate = sum(1 for v in first_attempts.values() if v) / len(first_attempts)
        else:
            first_attempt_success_rate = 1.0 if success else 0.0

        # error_recovery_rate — among failed steps, how many were eventually
        # followed by a successful step with the same step_num?
        failed_step_nums = {rec.step_num for rec in ctx.step_records if not rec.success}
        if failed_step_nums:
            recovered = 0
            for snum in failed_step_nums:
                if any(r.step_num == snum and r.success for r in ctx.step_records):
                    recovered += 1
            error_recovery_rate = recovered / len(failed_step_nums)
        else:
            error_recovery_rate = 1.0

        metrics = TaskMetrics(
            task_id=ctx.task.id,
            success=success,
            steps_taken=steps_taken,
            total_time=elapsed,
            tokens_used=ctx.tokens_total,
            api_calls=ctx.api_calls,
            failure_category=failure_category or FailureCategory.UNKNOWN,
            failure_reason=failure_reason,
            step_efficiency_ratio=step_efficiency_ratio,
            first_attempt_success_rate=first_attempt_success_rate,
            error_recovery_rate=error_recovery_rate,
        )
        self._current = None
        return metrics

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(
        self,
        task_metrics: list[TaskMetrics],
        suite_name: str = "",
        config_name: str = "full_cue",
    ) -> BenchmarkResult:
        """Aggregate a list of TaskMetrics into a BenchmarkResult."""
        total = len(task_metrics)
        if total == 0:
            return BenchmarkResult(suite_name=suite_name, config_name=config_name)

        successful = [m for m in task_metrics if m.success]
        success_rate = len(successful) / total * 100.0

        avg_steps = sum(m.steps_taken for m in task_metrics) / total
        avg_time = sum(m.total_time for m in task_metrics) / total
        avg_tokens = int(sum(m.tokens_used for m in task_metrics) / total)
        avg_api_calls = sum(m.api_calls for m in task_metrics) / total

        # by_difficulty
        by_difficulty: dict[str, list[bool]] = {}
        # by_app
        by_app: dict[str, list[bool]] = {}
        # by_failure_type
        by_failure_type: dict[str, int] = {}

        # We need task details — correlate by task_id using a simple lookup.
        # task_metrics carries failure_category but not difficulty/app.
        # The runner is expected to pass tasks alongside metrics.  Here we
        # work only with what TaskMetrics stores.
        for m in task_metrics:
            cat = m.failure_category.value if not m.success else "success"
            if not m.success:
                by_failure_type[cat] = by_failure_type.get(cat, 0) + 1

        # difficulty / app breakdowns are populated by the runner via the
        # _aggregate_with_tasks helper below when tasks are available.
        return BenchmarkResult(
            suite_name=suite_name,
            config_name=config_name,
            total_tasks=total,
            successful_tasks=len(successful),
            success_rate=success_rate,
            avg_steps=avg_steps,
            avg_time=avg_time,
            avg_tokens=avg_tokens,
            avg_api_calls=avg_api_calls,
            task_metrics=task_metrics,
            by_difficulty=by_difficulty,
            by_app=by_app,
            by_failure_type=by_failure_type,
            run_timestamp=time.time(),
        )

    def aggregate_with_tasks(
        self,
        paired: list[tuple[BenchmarkTask, TaskMetrics]],
        suite_name: str = "",
        config_name: str = "full_cue",
    ) -> BenchmarkResult:
        """Aggregate metrics with task metadata for full breakdowns."""
        task_metrics = [m for _, m in paired]
        result = self.aggregate(task_metrics, suite_name=suite_name, config_name=config_name)

        by_difficulty: dict[str, list[bool]] = {}
        by_app: dict[str, list[bool]] = {}
        for task, m in paired:
            by_difficulty.setdefault(task.difficulty, []).append(m.success)
            by_app.setdefault(task.app, []).append(m.success)

        result.by_difficulty = {
            diff: sum(vals) / len(vals) * 100.0 for diff, vals in by_difficulty.items()
        }
        result.by_app = {
            app: sum(vals) / len(vals) * 100.0 for app, vals in by_app.items()
        }
        return result

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def to_json(self, result: BenchmarkResult, path: str) -> None:
        """Save a BenchmarkResult to a JSON file."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        data = _benchmark_result_to_dict(result)
        with open(out, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def to_markdown(self, result: BenchmarkResult) -> str:
        """Generate a markdown report table for a BenchmarkResult."""
        lines = [
            f"# Benchmark Report - {result.suite_name}",
            "",
            f"**Config**: {result.config_name}  ",
            f"**Total tasks**: {result.total_tasks}  ",
            f"**Success rate**: {result.success_rate:.1f}%  ",
            f"**Avg steps**: {result.avg_steps:.1f}  ",
            f"**Avg time**: {result.avg_time:.1f}s  ",
            f"**Avg tokens**: {result.avg_tokens}",
            "",
        ]

        if result.by_difficulty:
            lines += [
                "## By Difficulty",
                "",
                "| Difficulty | Success Rate |",
                "|---|---|",
            ]
            for diff, rate in sorted(result.by_difficulty.items()):
                lines.append(f"| {diff} | {rate:.1f}% |")
            lines.append("")

        if result.by_app:
            lines += [
                "## By App",
                "",
                "| App | Success Rate |",
                "|---|---|",
            ]
            for app, rate in sorted(result.by_app.items()):
                lines.append(f"| {app} | {rate:.1f}% |")
            lines.append("")

        if result.by_failure_type:
            lines += [
                "## Failure Breakdown",
                "",
                "| Failure Type | Count |",
                "|---|---|",
            ]
            for ftype, count in sorted(result.by_failure_type.items(), key=lambda x: -x[1]):
                lines.append(f"| {ftype} | {count} |")
            lines.append("")

        return "\n".join(lines)


# ------------------------------------------------------------------
# Serialisation helper
# ------------------------------------------------------------------

def _task_metrics_to_dict(m: TaskMetrics) -> dict[str, Any]:
    return {
        "task_id": m.task_id,
        "success": m.success,
        "steps_taken": m.steps_taken,
        "total_time": m.total_time,
        "tokens_used": m.tokens_used,
        "api_calls": m.api_calls,
        "failure_category": m.failure_category.value,
        "failure_reason": m.failure_reason,
        "step_efficiency_ratio": m.step_efficiency_ratio,
        "grounding_accuracy": m.grounding_accuracy,
        "first_attempt_success_rate": m.first_attempt_success_rate,
        "error_recovery_rate": m.error_recovery_rate,
    }


def _benchmark_result_to_dict(r: BenchmarkResult) -> dict[str, Any]:
    return {
        "suite_name": r.suite_name,
        "config_name": r.config_name,
        "total_tasks": r.total_tasks,
        "successful_tasks": r.successful_tasks,
        "success_rate": r.success_rate,
        "avg_steps": r.avg_steps,
        "avg_time": r.avg_time,
        "avg_tokens": r.avg_tokens,
        "avg_api_calls": r.avg_api_calls,
        "by_difficulty": r.by_difficulty,
        "by_app": r.by_app,
        "by_failure_type": r.by_failure_type,
        "run_timestamp": r.run_timestamp,
        "task_metrics": [_task_metrics_to_dict(m) for m in r.task_metrics],
    }
