"""PlanningEnhancer — integrates task decomposition and app knowledge into prompts."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from cue.config import EnhancerLevel, PlanningConfig
from cue.planning.knowledge import AppKnowledge, AppKnowledgeBase
from cue.planning.planner import TaskPlanner
from cue.types import Lesson, MemoryContext, ScreenState, SubTask

logger = logging.getLogger(__name__)

# Default bundled knowledge directory (sibling of the package).
_DEFAULT_KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"


class PlanningEnhancer:
    """Enhances agent prompts with task decomposition, app knowledge, and lessons.

    Given a task string and the current screen state it produces a structured
    prompt section that guides the downstream agent with:
    - Ordered subtask list (respecting Miller's Law, ≤7 steps).
    - App-specific keyboard shortcuts and navigation shortcuts.
    - Reflexion-style lessons from past experience.
    - Pitfall warnings for the active application.
    """

    def __init__(self, config: PlanningConfig) -> None:
        self._config = config
        self._planner = TaskPlanner()
        self._kb = AppKnowledgeBase()

        if config.enable_app_knowledge:
            knowledge_dir = (
                Path(config.knowledge_dir)
                if config.knowledge_dir
                else _DEFAULT_KNOWLEDGE_DIR
            )
            self._kb.load_all(knowledge_dir)
            logger.debug(
                "Loaded knowledge for apps: %s", self._kb.loaded_apps
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def enhance_prompt(
        self,
        task: str,
        screen_state: ScreenState,
        memory_context: MemoryContext | None = None,
    ) -> str:
        """Return an enhanced prompt string for *task*.

        Parameters
        ----------
        task:
            Natural-language task description.
        screen_state:
            Current captured screen state (used for app detection).
        memory_context:
            Optional memory context with past lessons and episodes.

        Returns
        -------
        str
            A structured prompt section to prepend/inject into the agent prompt.
        """
        if self._config.level == EnhancerLevel.OFF:
            return task

        app = self._identify_app(screen_state)
        knowledge = self._kb.get_knowledge(app) if self._config.enable_app_knowledge else None
        subtasks = self._decompose_task(task, app, knowledge)

        knowledge_text = (
            self._inject_knowledge(knowledge, task)
            if knowledge and self._config.enable_app_knowledge
            else ""
        )

        lesson_text = ""
        if memory_context and self._config.enable_reflexion:
            lesson_text = self._inject_lessons(memory_context.lessons, app)

        return self._build_enhanced_prompt(task, subtasks, knowledge_text, lesson_text)

    # ── Internal — App Detection ───────────────────────────────────────────────

    def _identify_app(self, screen_state: ScreenState) -> str:
        """Detect the active application name from screen state.

        Priority:
        1. screen_state.app_name (set by platform layer).
        2. Accessibility tree root app_name.
        3. Heuristic from window title.
        4. Empty string (unknown).
        """
        if screen_state.app_name:
            return screen_state.app_name

        if screen_state.a11y_tree and screen_state.a11y_tree.app_name:
            return screen_state.a11y_tree.app_name

        title = screen_state.window_title
        if title:
            return _heuristic_app_from_title(title)

        return ""

    # ── Internal — Task Decomposition ─────────────────────────────────────────

    def _decompose_task(
        self,
        task: str,
        app: str,
        knowledge: AppKnowledge | None,
    ) -> list[SubTask]:
        """Call TaskPlanner with knowledge context."""
        return self._planner.decompose(task, app=app, knowledge=knowledge)

    # ── Internal — Lesson Injection ───────────────────────────────────────────

    def _inject_lessons(self, lessons: list[Lesson], app: str) -> str:
        """Format past lessons relevant to *app* for prompt injection."""
        if not lessons:
            return ""

        # Prioritise lessons for this specific app, then include general ones.
        app_lower = app.lower()
        app_lessons = [l for l in lessons if l.app.lower() == app_lower]
        other_lessons = [l for l in lessons if l.app.lower() != app_lower]

        selected = (app_lessons + other_lessons)[: self._config.step_limit]
        if not selected:
            return ""

        lines = ["### Past Lessons (Reflexion)"]
        for lesson in selected:
            confidence_pct = f"{lesson.confidence:.0%}"
            lines.append(
                f"- [{lesson.app}] {lesson.situation}\n"
                f"  AVOID: {lesson.failed_approach}\n"
                f"  USE: {lesson.successful_approach} (confidence {confidence_pct})"
            )
        return "\n".join(lines)

    # ── Internal — Knowledge Injection ────────────────────────────────────────

    def _inject_knowledge(self, knowledge: AppKnowledge, task: str) -> str:
        """Format app knowledge (shortcuts, pitfalls, navigation) for prompt injection."""
        lines: list[str] = [f"### App Knowledge: {knowledge.app_name}"]

        # Keyboard shortcuts — always include all; highlight keyboard_first preference.
        if knowledge.shortcuts and self._config.keyboard_first:
            lines.append("\n**Keyboard Shortcuts** (prefer these over mouse):")
            for sc in knowledge.shortcuts:
                reliability_note = (
                    f" [reliability {sc.reliability:.0%}]" if sc.reliability < 1.0 else ""
                )
                lines.append(f"  - {sc.action}: `{sc.keys}`{reliability_note}")

        # Navigation shortcuts.
        if knowledge.navigation:
            lines.append("\n**Direct Navigation** (faster than menus):")
            for nav in knowledge.navigation:
                note = f" — {nav.notes}" if nav.notes else ""
                lines.append(f"  - {nav.target}: {nav.method}{note}")

        # Pitfalls — filter to those loosely related to the task.
        task_lower = task.lower()
        relevant_pitfalls = [
            p
            for p in knowledge.pitfalls
            if any(
                token in task_lower
                for token in p.situation.lower().split()
                if len(token) > 3
            )
        ]
        # Always include all pitfalls if none matched task; cap at 5.
        pitfalls_to_show = relevant_pitfalls or knowledge.pitfalls
        pitfalls_to_show = pitfalls_to_show[:5]

        if pitfalls_to_show:
            lines.append("\n**Known Pitfalls**:")
            for p in pitfalls_to_show:
                lines.append(
                    f"  - {p.situation}\n"
                    f"    AVOID: {p.avoid}\n"
                    f"    INSTEAD: {p.instead}"
                )

        return "\n".join(lines)

    # ── Internal — Prompt Assembly ────────────────────────────────────────────

    def _build_enhanced_prompt(
        self,
        task: str,
        subtasks: list[SubTask],
        knowledge_text: str,
        lesson_text: str,
    ) -> str:
        """Assemble the final enhanced prompt string from all components."""
        sections: list[str] = []

        sections.append(f"## Task\n{task}")

        # Subtask plan.
        if subtasks:
            plan_lines = ["## Execution Plan"]
            for i, st in enumerate(subtasks, 1):
                method_note = ""
                if st.shortcut:
                    method_note = f" [keyboard: `{st.shortcut}`]"
                elif st.method == "keyboard":
                    method_note = " [keyboard]"

                compound_note = " (compound)" if st.is_compound else ""
                plan_lines.append(
                    f"{i}. {st.description}{method_note}{compound_note}"
                )
                if st.is_compound and st.steps:
                    for sub in st.steps:
                        plan_lines.append(f"   - {sub}")
            sections.append("\n".join(plan_lines))

        # App knowledge.
        if knowledge_text:
            sections.append(knowledge_text)

        # Lessons.
        if lesson_text:
            sections.append(lesson_text)

        # Keyboard-first reminder.
        if self._config.keyboard_first:
            sections.append(
                "**Instruction**: Prefer keyboard shortcuts over mouse clicks "
                "wherever a shortcut is available — it is faster and more reliable."
            )

        return "\n\n".join(sections)


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _heuristic_app_from_title(title: str) -> str:
    """Extract a likely application name from a window title string.

    Common patterns:
    - "Document - LibreOffice Calc"  -> "LibreOffice Calc"
    - "New Tab - Mozilla Firefox"    -> "Mozilla Firefox"
    - "Firefox"                      -> "Firefox"
    """
    # Many windows put the app name after the last " - " separator.
    if " - " in title:
        return title.rsplit(" - ", 1)[-1].strip()
    # Some windows use " — " (em-dash).
    if " — " in title:
        return title.rsplit(" — ", 1)[-1].strip()
    return title.strip()
