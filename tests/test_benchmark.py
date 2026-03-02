"""Tests for CUE Benchmark Framework (Phase 3)."""

from __future__ import annotations

import tempfile
from pathlib import Path
import yaml

from cue.types import (
    BenchmarkTask, BenchmarkResult, TaskMetrics, SuccessCriterion,
    FailureCategory, AblationResult,
)
from cue.config import CUEConfig, BenchmarkConfig


class TestTaskLoader:
    def _get_loader(self):
        from cue.benchmark.task_loader import TaskLoader
        return TaskLoader()

    def test_load_bundled_mini(self):
        loader = self._get_loader()
        tasks = loader.load_suite("mini")
        assert len(tasks) >= 1
        assert all(isinstance(t, BenchmarkTask) for t in tasks)

    def test_load_custom_yaml(self):
        loader = self._get_loader()
        with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
            yaml.dump([{
                "id": "test-001", "app": "TestApp", "difficulty": "easy",
                "instruction": "Click button", "human_baseline_steps": 1,
            }], f)
            f.flush()
            tasks = loader.load_file(Path(f.name))
        assert len(tasks) == 1
        assert tasks[0].id == "test-001"

    def test_available_suites(self):
        loader = self._get_loader()
        suites = loader.get_available_suites()
        assert isinstance(suites, list)


class TestSuccessChecker:
    def _get_checker(self):
        from cue.benchmark.checkers import SuccessChecker
        return SuccessChecker()

    def test_cell_value_check_pass(self):
        checker = self._get_checker()
        criterion = SuccessCriterion(
            type="cell_value_check",
            checks=[{"cell": "A1", "condition": "==", "value": "Hello"}],
        )
        ok, reason = checker.check(criterion, {"cells": {"A1": "Hello"}})
        assert ok

    def test_cell_value_check_fail(self):
        checker = self._get_checker()
        criterion = SuccessCriterion(
            type="cell_value_check",
            checks=[{"cell": "A1", "condition": "==", "value": "Hello"}],
        )
        ok, reason = checker.check(criterion, {"cells": {"A1": "World"}})
        assert not ok

    def test_url_check(self):
        checker = self._get_checker()
        criterion = SuccessCriterion(
            type="url_check",
            checks=[{"condition": "contains", "value": "google.com"}],
        )
        ok, _ = checker.check(criterion, {"active_url": "https://www.google.com"})
        assert ok

    def test_file_content_check(self):
        checker = self._get_checker()
        criterion = SuccessCriterion(
            type="file_content_check",
            checks=[{"file": "main.py", "condition": "contains", "value": "def hello"}],
        )
        ok, _ = checker.check(criterion, {"file_contents": {"main.py": "def hello():\n    pass"}})
        assert ok

    def test_tab_count_check(self):
        checker = self._get_checker()
        criterion = SuccessCriterion(
            type="tab_count",
            checks=[{"condition": "==", "value": 2}],
        )
        ok, _ = checker.check(criterion, {"tab_count": 2})
        assert ok

    def test_unknown_checker_type(self):
        checker = self._get_checker()
        criterion = SuccessCriterion(type="nonexistent", checks=[])
        ok, reason = checker.check(criterion, {})
        assert not ok
        assert "unknown" in reason.lower() or "unsupported" in reason.lower()


class TestMetricsCollector:
    def _get_collector(self):
        from cue.benchmark.metrics import MetricsCollector
        return MetricsCollector()

    def test_collect_single_task(self):
        mc = self._get_collector()
        task = BenchmarkTask(id="t1", app="App", human_baseline_steps=5)
        mc.start_task(task)
        mc.record_step(1, "click", True, 100)
        mc.record_step(2, "type", True, 150)
        metrics = mc.end_task(success=True)
        assert metrics.success
        assert metrics.steps_taken == 2
        assert metrics.tokens_used == 250

    def test_aggregate_results(self):
        mc = self._get_collector()
        metrics_list = [
            TaskMetrics(task_id="t1", success=True, steps_taken=3, total_time=10.0, tokens_used=300),
            TaskMetrics(task_id="t2", success=False, steps_taken=5, total_time=20.0, tokens_used=500,
                       failure_category=FailureCategory.GROUNDING),
        ]
        result = mc.aggregate(metrics_list)
        assert result.success_rate == 50.0
        assert result.avg_steps == 4.0

    def test_to_markdown(self):
        mc = self._get_collector()
        result = BenchmarkResult(
            suite_name="mini", success_rate=75.0, total_tasks=4,
            successful_tasks=3, avg_steps=5.0, avg_time=15.0,
        )
        md = mc.to_markdown(result)
        assert "75.0%" in md
        assert "mini" in md


class TestAblationRunner:
    def _get_runner(self):
        from cue.benchmark.ablation import AblationRunner
        return AblationRunner(config=CUEConfig())

    def test_configs_exist(self):
        runner = self._get_runner()
        assert "baseline" in runner.CONFIGS
        assert "full_cue" in runner.CONFIGS
        assert len(runner.CONFIGS) >= 8

    def test_analyze_contributions(self):
        runner = self._get_runner()
        # Mock results
        results = {
            "baseline": AblationResult(config_name="baseline", success_rate=50.0),
            "full_cue": AblationResult(config_name="full_cue", success_rate=80.0),
        }
        for module in ["grounding", "planning", "execution", "verification", "memory", "efficiency"]:
            results[f"+{module}"] = AblationResult(config_name=f"+{module}", success_rate=55.0)
            results[f"cue-{module}"] = AblationResult(config_name=f"cue-{module}", success_rate=75.0)

        contributions = runner.analyze_contributions(results)
        assert "grounding" in contributions
        assert contributions["grounding"]["solo_contribution"] == 5.0
        # interaction = (full - ablated) - solo = (80 - 75) - 5 = 0
        assert contributions["grounding"]["interaction_effect"] == 0.0


class TestFailureAnalyzer:
    def _get_analyzer(self):
        from cue.benchmark.analysis import FailureAnalyzer
        return FailureAnalyzer()

    def test_categorize_grounding(self):
        analyzer = self._get_analyzer()
        tm = TaskMetrics(failure_reason="click target element not found")
        cat = analyzer.categorize_failure(tm)
        assert cat == FailureCategory.GROUNDING

    def test_categorize_planning(self):
        analyzer = self._get_analyzer()
        tm = TaskMetrics(failure_reason="subtask decomposition failed")
        cat = analyzer.categorize_failure(tm)
        assert cat == FailureCategory.PLANNING

    def test_categorize_timeout(self):
        analyzer = self._get_analyzer()
        tm = TaskMetrics(failure_reason="timeout exceeded")
        cat = analyzer.categorize_failure(tm)
        assert cat == FailureCategory.TIMEOUT

    def test_analyze_results(self):
        analyzer = self._get_analyzer()
        result = BenchmarkResult(
            suite_name="mini", total_tasks=3, successful_tasks=1, success_rate=33.3,
            task_metrics=[
                TaskMetrics(task_id="t1", success=True),
                TaskMetrics(task_id="t2", success=False, failure_category=FailureCategory.GROUNDING),
                TaskMetrics(task_id="t3", success=False, failure_category=FailureCategory.PLANNING),
            ],
        )
        analysis = analyzer.analyze(result)
        assert "by_category" in analysis
        assert "by_app" in analysis
