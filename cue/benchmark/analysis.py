"""Failure analysis for benchmark results."""

from __future__ import annotations

import re
from typing import Any

from cue.types import BenchmarkResult, FailureCategory, TaskMetrics


# Keyword patterns for failure categorization
_CATEGORY_PATTERNS: list[tuple[FailureCategory, list[str]]] = [
    (FailureCategory.GROUNDING, [
        "element not found", "click target", "cannot locate", "grounding",
        "ui element", "bounding box", "ocr", "visual", "no element",
    ]),
    (FailureCategory.PLANNING, [
        "subtask", "decomposition", "planning", "plan failed", "subgoal",
        "task decomp", "strategy", "replan",
    ]),
    (FailureCategory.EXECUTION, [
        "execution", "action failed", "click failed", "type failed",
        "keyboard", "mouse", "scroll failed", "drag failed",
    ]),
    (FailureCategory.NAVIGATION, [
        "navigation", "navigate", "page not found", "url", "tab", "window",
        "back", "forward", "redirect",
    ]),
    (FailureCategory.VERIFICATION, [
        "verification", "verify", "expected outcome", "mismatch",
        "check failed", "assertion",
    ]),
    (FailureCategory.TIMEOUT, [
        "timeout", "timed out", "time limit", "exceeded",
    ]),
    (FailureCategory.SAFETY_BLOCK, [
        "safety", "blocked", "dangerous", "permission denied", "not allowed",
    ]),
]


class FailureAnalyzer:
    """Categorize and analyze benchmark task failures."""

    def categorize_failure(self, metrics: TaskMetrics) -> FailureCategory:
        """Determine the failure category from the failure reason string."""
        if metrics.failure_category not in (FailureCategory.UNKNOWN, None):
            # Already categorized
            if metrics.failure_category != FailureCategory.UNKNOWN:
                return metrics.failure_category

        reason_lower = metrics.failure_reason.lower()
        if not reason_lower:
            return FailureCategory.UNKNOWN

        for category, keywords in _CATEGORY_PATTERNS:
            for kw in keywords:
                if kw in reason_lower:
                    return category

        return FailureCategory.UNKNOWN

    def analyze(self, result: BenchmarkResult) -> dict[str, Any]:
        """Produce a structured analysis of failures in a BenchmarkResult."""
        failures = [m for m in result.task_metrics if not m.success]

        # Count by category
        by_category: dict[str, int] = {}
        for m in failures:
            cat = self.categorize_failure(m).value
            by_category[cat] = by_category.get(cat, 0) + 1

        # Count by app (need task correlation — use task_id prefix heuristic)
        by_app: dict[str, int] = {}
        for m in failures:
            # task_id pattern: "app-NNN" or "mini-NNN"
            app = m.task_id.split("-")[0] if m.task_id else "unknown"
            by_app[app] = by_app.get(app, 0) + 1

        top_failures = sorted(by_category.items(), key=lambda x: -x[1])

        return {
            "total_failures": len(failures),
            "by_category": by_category,
            "by_app": by_app,
            "top_failure_category": top_failures[0][0] if top_failures else None,
            "recommendations": self._recommendations(by_category),
        }

    def generate_report_from_json(self, data: dict[str, Any]) -> str:
        """Generate a text report from a JSON-serialized BenchmarkResult dict."""
        lines = [
            f"Suite: {data.get('suite_name', 'unknown')}",
            f"Success rate: {data.get('success_rate', 0):.1%}",
            f"Total tasks: {data.get('total_tasks', 0)}",
            f"Successful: {data.get('successful_tasks', 0)}",
            "",
            "Failure breakdown:",
        ]
        by_failure = data.get("by_failure_type", {})
        if by_failure:
            for cat, count in sorted(by_failure.items(), key=lambda x: -x[1]):
                lines.append(f"  {cat}: {count}")
        else:
            lines.append("  (no failure data)")
        return "\n".join(lines)

    def _recommendations(self, by_category: dict[str, int]) -> list[str]:
        """Return improvement recommendations based on failure categories."""
        recs: list[str] = []
        if by_category.get(FailureCategory.GROUNDING.value, 0) > 0:
            recs.append("Improve grounding: enable visual + structural fusion")
        if by_category.get(FailureCategory.PLANNING.value, 0) > 0:
            recs.append("Improve planning: add more app-specific knowledge")
        if by_category.get(FailureCategory.TIMEOUT.value, 0) > 0:
            recs.append("Increase timeout or optimize step efficiency")
        if by_category.get(FailureCategory.EXECUTION.value, 0) > 0:
            recs.append("Enable fallback chain and timing control")
        return recs
