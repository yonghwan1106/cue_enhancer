"""Task Planner — rule-based task decomposition into SubTask lists."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from cue.types import SubTask

logger = logging.getLogger(__name__)

# ─── Decomposition Rules ───────────────────────────────────────────────────────

# Ordered list of (pattern, action_type, target_template) tuples.
# The first matching rule wins for a phrase.
_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\b(open|launch|start)\b", re.I), "navigate", "application"),
    (re.compile(r"\b(navigate|go to|visit|open url|browse to)\b", re.I), "navigate", "url/location"),
    (re.compile(r"\b(search|find|look up|query)\b", re.I), "search", "search target"),
    (re.compile(r"\b(click|press|tap|select|choose)\b", re.I), "click", "element"),
    (re.compile(r"\b(type|enter|input|fill|write)\b", re.I), "type", "text field"),
    (re.compile(r"\b(scroll|page down|page up)\b", re.I), "scroll", "region"),
    (re.compile(r"\b(download|save|export)\b", re.I), "download", "file"),
    (re.compile(r"\b(upload|attach|import)\b", re.I), "upload", "file"),
    (re.compile(r"\b(delete|remove|clear)\b", re.I), "delete", "item"),
    (re.compile(r"\b(copy|duplicate)\b", re.I), "copy", "content"),
    (re.compile(r"\b(paste)\b", re.I), "paste", "content"),
    (re.compile(r"\b(close|quit|exit)\b", re.I), "navigate", "close"),
    (re.compile(r"\b(verify|check|confirm|ensure|assert)\b", re.I), "verify", "state"),
    (re.compile(r"\b(format|bold|italic|underline)\b", re.I), "format", "content"),
    (re.compile(r"\b(sort|filter|group)\b", re.I), "data_op", "data"),
    (re.compile(r"\b(submit|send|publish|post)\b", re.I), "submit", "form/message"),
]

# Action types considered navigation-oriented.
_NAVIGATION_TYPES = {"navigate", "search"}
# Action types that are verification-only.
_VERIFICATION_TYPES = {"verify"}


class TaskPlanner:
    """Decomposes a natural-language task into a list of SubTask objects.

    Uses keyword/regex rules only — no LLM calls.
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def decompose(
        self,
        task: str,
        app: str = "",
        knowledge: object | None = None,
    ) -> list[SubTask]:
        """Break *task* into ordered SubTask objects.

        Parameters
        ----------
        task:
            Natural-language task description.
        app:
            Name of the target application (used for shortcut injection).
        knowledge:
            Optional AppKnowledge object with shortcut/navigation data.

        Returns
        -------
        list[SubTask]
            Ordered list of sub-tasks, re-decomposed hierarchically if > step_limit.
        """
        phrases = _split_into_phrases(task)
        subtasks: list[SubTask] = []

        for phrase in phrases:
            subtask = _phrase_to_subtask(phrase, app, knowledge)
            subtasks.append(subtask)

        # If no rules matched, create a single generic subtask.
        if not subtasks:
            subtasks = [SubTask(description=task, action_type="generic", target="task")]

        return self._hierarchical_redecompose(subtasks)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _hierarchical_redecompose(
        self,
        subtasks: list[SubTask],
        step_limit: int = 7,
    ) -> list[SubTask]:
        """If there are more than *step_limit* subtasks, group related ones.

        This respects Miller's Law — humans (and agents) work best with ≤7
        concurrent items in working memory.
        """
        if len(subtasks) <= step_limit:
            return subtasks

        max_groups = step_limit
        grouped = self._group_related(subtasks, max_groups)
        return grouped

    def _group_related(
        self,
        subtasks: list[SubTask],
        max_groups: int,
    ) -> list[SubTask]:
        """Greedily group adjacent related subtasks into compound SubTasks."""
        if not subtasks:
            return []

        groups: list[list[SubTask]] = []
        current_group: list[SubTask] = [subtasks[0]]

        for subtask in subtasks[1:]:
            if len(groups) < max_groups - 1 and self._is_related(current_group[-1], subtask):
                current_group.append(subtask)
            else:
                groups.append(current_group)
                current_group = [subtask]
        groups.append(current_group)

        result: list[SubTask] = []
        for group in groups:
            if len(group) == 1:
                result.append(group[0])
            else:
                compound = SubTask(
                    description=_group_description(group),
                    action_type=group[0].action_type,
                    target=group[0].target,
                    method=group[0].method,
                    is_compound=True,
                    sub_steps=group,
                    steps=[st.description for st in group],
                    action_description=f"Compound: {len(group)} related steps",
                )
                result.append(compound)

        return result

    @staticmethod
    def _is_related(task1: SubTask, task2: SubTask) -> bool:
        """Return True if two subtasks are similar enough to group together.

        Criteria (any one is sufficient):
        - Same action_type.
        - Both navigation-oriented.
        - Both verification-only.
        - Shared non-trivial target keyword.
        """
        if task1.action_type == task2.action_type:
            return True
        if task1.is_navigation and task2.is_navigation:
            return True
        if task1.is_verification_only and task2.is_verification_only:
            return True
        # Shared meaningful target token.
        t1_tokens = {w for w in task1.target.lower().split() if len(w) > 3}
        t2_tokens = {w for w in task2.target.lower().split() if len(w) > 3}
        if t1_tokens & t2_tokens:
            return True
        return False


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _split_into_phrases(task: str) -> list[str]:
    """Split a task string into individual action phrases.

    Splits on coordinating conjunctions, punctuation, and numbered steps
    while preserving meaningful sub-phrases.
    """
    # Remove leading/trailing whitespace.
    task = task.strip()

    # Split on "then", "and then", ", then", ";", numbered steps like "1.", "2.".
    # We use a separator that captures the delimiters but discards them.
    patterns = [
        r"\band then\b",
        r"\bthen\b",
        r"\bafter that\b",
        r"\bnext\b(?=,?\s)",
        r"\bfinally\b(?=,?\s)",
        r"\bfirst\b(?=,?\s)",
        r"[;]",
        r",\s*(?=\b(?:open|click|type|search|navigate|scroll|download|close|verify)\b)",
        r"\b\d+\.\s+",
    ]
    combined = "|".join(patterns)
    parts = re.split(combined, task, flags=re.I)

    # Filter and clean.
    phrases = [p.strip().strip(",").strip() for p in parts if p and p.strip()]
    phrases = [p for p in phrases if len(p) > 3]

    return phrases if phrases else [task]


def _phrase_to_subtask(phrase: str, app: str, knowledge: object | None) -> SubTask:
    """Convert a single phrase into a SubTask using rule matching."""
    action_type = "generic"
    target = phrase

    for pattern, atype, target_tmpl in _RULES:
        if pattern.search(phrase):
            action_type = atype
            target = _extract_target(phrase, pattern) or target_tmpl
            break

    is_nav = action_type in _NAVIGATION_TYPES
    is_verify = action_type in _VERIFICATION_TYPES

    # Attempt shortcut injection when keyboard is preferred.
    shortcut: str | None = None
    method = "mouse"
    if knowledge is not None:
        sc = _find_shortcut_for(knowledge, app, phrase)
        if sc is not None:
            shortcut = sc.keys
            method = "keyboard"

    return SubTask(
        description=phrase,
        action_type=action_type,
        target=target,
        method=method,
        shortcut=shortcut,
        is_navigation=is_nav,
        is_verification_only=is_verify,
        action_description=f"{action_type}: {target}",
    )


def _extract_target(phrase: str, matched_pattern: re.Pattern[str]) -> str:
    """Extract the object of the action from a phrase by stripping the verb."""
    # Remove the matched verb and surrounding articles/prepositions.
    cleaned = matched_pattern.sub("", phrase, count=1)
    cleaned = re.sub(r"^\s*(the|a|an|to|into|on|at|from)\s+", "", cleaned, flags=re.I)
    return cleaned.strip() or phrase


def _find_shortcut_for(knowledge: object, app: str, phrase: str) -> object | None:
    """Safely call knowledge.find_shortcut if the method exists."""
    find = getattr(knowledge, "find_shortcut", None)
    if callable(find):
        return find(app, phrase)
    return None


def _group_description(group: list[SubTask]) -> str:
    """Build a human-readable description for a compound subtask group."""
    if len(group) <= 2:
        return " and ".join(st.description for st in group)
    return f"{group[0].description} (+ {len(group) - 1} related steps)"
