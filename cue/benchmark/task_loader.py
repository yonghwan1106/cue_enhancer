"""Task loader for benchmark suites — reads YAML task definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from cue.types import BenchmarkTask, SuccessCriterion


class TaskLoader:
    """Load BenchmarkTask definitions from YAML files."""

    def load_suite(
        self,
        suite_name: str,
        tasks_dir: str = "",
        *,
        difficulty: str | None = None,
        app: str | None = None,
        failure_type: str | None = None,
    ) -> list[BenchmarkTask]:
        """Load all tasks for a suite, with optional filtering.

        Parameters
        ----------
        suite_name:
            Name of the suite (matches YAML filename without extension).
        tasks_dir:
            Directory to search. Defaults to the bundled ``tasks/`` folder.
        difficulty:
            If provided, only return tasks with this difficulty level.
        app:
            If provided, only return tasks for this app.
        failure_type:
            If provided, only return tasks with this failure_type.
        """
        base = Path(tasks_dir) if tasks_dir else Path(__file__).parent / "tasks"
        target = base / f"{suite_name}.yaml"
        if not target.exists():
            # Fallback: try loading all YAML files and filter by suite tag
            tasks: list[BenchmarkTask] = []
            for yaml_file in sorted(base.glob("*.yaml")):
                tasks.extend(self.load_file(yaml_file))
        else:
            tasks = self.load_file(target)

        # Apply filters
        if difficulty is not None:
            tasks = [t for t in tasks if t.difficulty == difficulty]
        if app is not None:
            tasks = [t for t in tasks if t.app == app]
        if failure_type is not None:
            tasks = [t for t in tasks if t.failure_type == failure_type]

        return tasks

    def load_file(self, path: Path) -> list[BenchmarkTask]:
        """Load a single YAML file and return a list of BenchmarkTask objects."""
        with open(path, encoding="utf-8") as f:
            raw: Any = yaml.safe_load(f)

        if not raw:
            return []

        tasks: list[BenchmarkTask] = []
        for item in raw:
            task = self._parse_task(item)
            tasks.append(task)
        return tasks

    def get_available_suites(self, tasks_dir: str = "") -> list[str]:
        """Return a sorted list of available suite names (YAML filenames without extension)."""
        base = Path(tasks_dir) if tasks_dir else Path(__file__).parent / "tasks"
        if not base.exists():
            return []
        return sorted(p.stem for p in base.glob("*.yaml"))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _parse_task(self, data: dict[str, Any]) -> BenchmarkTask:
        """Convert a raw dict into a BenchmarkTask."""
        criteria_raw: dict[str, Any] = data.get("success_criteria", {})
        criteria = SuccessCriterion(
            type=criteria_raw.get("type", ""),
            checks=criteria_raw.get("checks", []),
        )
        return BenchmarkTask(
            id=data.get("id", ""),
            app=data.get("app", ""),
            difficulty=data.get("difficulty", "medium"),
            failure_type=data.get("failure_type", ""),
            instruction=data.get("instruction", ""),
            initial_state=data.get("initial_state", ""),
            success_criteria=criteria,
            human_baseline_steps=data.get("human_baseline_steps", 0),
            timeout_seconds=data.get("timeout_seconds", 120),
            tags=data.get("tags", []),
        )
