"""Success checkers for benchmark task criteria."""

from __future__ import annotations

from typing import Any, Callable

from cue.types import SuccessCriterion


# Registry mapping check type strings to handler functions
_CHECKER_REGISTRY: dict[str, Callable[[list[dict[str, Any]], dict[str, Any]], tuple[bool, str]]] = {}


def _register(name: str) -> Callable:
    def decorator(fn: Callable) -> Callable:
        _CHECKER_REGISTRY[name] = fn
        return fn
    return decorator


# ------------------------------------------------------------------
# Individual check implementations
# ------------------------------------------------------------------


@_register("cell_value_check")
def _cell_value_check(checks: list[dict[str, Any]], env_state: dict[str, Any]) -> tuple[bool, str]:
    """Check spreadsheet cell values."""
    cells: dict[str, Any] = env_state.get("cells", {})
    for check in checks:
        cell = check.get("cell", "")
        condition = check.get("condition", "==")
        expected = check.get("value")
        ref_cell = check.get("reference_cell")

        actual = cells.get(cell)
        if actual is None:
            return False, f"Cell {cell!r} not found in env_state"

        # Resolve reference_cell
        if ref_cell is not None:
            expected = cells.get(ref_cell)
            if expected is None:
                return False, f"Reference cell {ref_cell!r} not found in env_state"

        # Evaluate condition
        try:
            if condition == "==":
                ok = str(actual) == str(expected)
            elif condition == ">=":
                ok = float(actual) >= float(expected)
            elif condition == "<=":
                ok = float(actual) <= float(expected)
            elif condition == "contains":
                ok = str(expected) in str(actual)
            else:
                return False, f"Unknown condition {condition!r}"
        except (TypeError, ValueError) as exc:
            return False, f"Comparison error for cell {cell!r}: {exc}"

        if not ok:
            return False, f"Cell {cell!r}: {actual!r} {condition} {expected!r} failed"

    return True, "All cell checks passed"


@_register("url_check")
def _url_check(checks: list[dict[str, Any]], env_state: dict[str, Any]) -> tuple[bool, str]:
    """Check the active URL in the browser."""
    active_url: str = env_state.get("active_url", "")
    for check in checks:
        condition = check.get("condition", "contains")
        expected = str(check.get("value", ""))
        if condition == "contains":
            ok = expected in active_url
        elif condition == "==":
            ok = active_url == expected
        else:
            return False, f"Unknown url_check condition {condition!r}"
        if not ok:
            return False, f"URL {active_url!r} does not satisfy {condition} {expected!r}"
    return True, "URL check passed"


@_register("file_content_check")
def _file_content_check(checks: list[dict[str, Any]], env_state: dict[str, Any]) -> tuple[bool, str]:
    """Check file contents for contains / not_contains."""
    file_contents: dict[str, str] = env_state.get("file_contents", {})
    for check in checks:
        file_path = check.get("file", "")
        condition = check.get("condition", "contains")
        expected = str(check.get("value", ""))
        content = file_contents.get(file_path)
        if content is None:
            return False, f"File {file_path!r} not found in env_state"
        if condition == "contains":
            ok = expected in content
        elif condition == "not_contains":
            ok = expected not in content
        else:
            return False, f"Unknown file_content_check condition {condition!r}"
        if not ok:
            return False, f"File {file_path!r} content check ({condition}) failed for {expected!r}"
    return True, "File content checks passed"


@_register("tab_count")
def _tab_count_check(checks: list[dict[str, Any]], env_state: dict[str, Any]) -> tuple[bool, str]:
    """Check the number of open tabs."""
    tab_count: int = env_state.get("tab_count", 0)
    for check in checks:
        condition = check.get("condition", "==")
        expected = int(check.get("value", 0))
        if condition == "==":
            ok = tab_count == expected
        elif condition == ">=":
            ok = tab_count >= expected
        elif condition == "<=":
            ok = tab_count <= expected
        else:
            return False, f"Unknown tab_count condition {condition!r}"
        if not ok:
            return False, f"tab_count {tab_count} {condition} {expected} failed"
    return True, "Tab count check passed"


@_register("clipboard_check")
def _clipboard_check(checks: list[dict[str, Any]], env_state: dict[str, Any]) -> tuple[bool, str]:
    """Check clipboard contents."""
    clipboard: str = env_state.get("clipboard", "")
    for check in checks:
        condition = check.get("condition", "contains")
        expected = str(check.get("value", ""))
        if condition == "contains":
            ok = expected in clipboard
        elif condition == "==":
            ok = clipboard == expected
        else:
            return False, f"Unknown clipboard_check condition {condition!r}"
        if not ok:
            return False, f"Clipboard {clipboard!r} does not satisfy {condition} {expected!r}"
    return True, "Clipboard check passed"


@_register("screenshot_diff")
def _screenshot_diff_check(checks: list[dict[str, Any]], env_state: dict[str, Any]) -> tuple[bool, str]:
    """Check that the screenshot hash differs from the initial hash."""
    current_hash: str = env_state.get("screenshot_hash", "")
    initial_hash: str = env_state.get("initial_screenshot_hash", "")
    if not current_hash:
        return False, "screenshot_hash not present in env_state"
    if current_hash == initial_hash:
        return False, "Screenshot has not changed from initial state"
    return True, "Screenshot differs from initial state"


@_register("app_state_check")
def _app_state_check(checks: list[dict[str, Any]], env_state: dict[str, Any]) -> tuple[bool, str]:
    """Check key-value pairs in env_state['app_state']."""
    app_state: dict[str, Any] = env_state.get("app_state", {})
    for check in checks:
        key = check.get("key", "")
        expected = check.get("value")
        condition = check.get("condition", "==")
        actual = app_state.get(key)
        if actual is None:
            return False, f"app_state key {key!r} not found"
        if condition == "==":
            ok = actual == expected
        elif condition == "contains":
            ok = str(expected) in str(actual)
        elif condition == ">=":
            ok = float(actual) >= float(expected)
        elif condition == "<=":
            ok = float(actual) <= float(expected)
        else:
            return False, f"Unknown app_state_check condition {condition!r}"
        if not ok:
            return False, f"app_state[{key!r}]: {actual!r} {condition} {expected!r} failed"
    return True, "App state checks passed"


# ------------------------------------------------------------------
# Public class
# ------------------------------------------------------------------


class SuccessChecker:
    """Check success criteria against an environment state snapshot."""

    def check(
        self, criterion: SuccessCriterion, env_state: dict[str, Any]
    ) -> tuple[bool, str]:
        """Evaluate *criterion* against *env_state*.

        Returns
        -------
        (success, reason)
            ``success`` is ``True`` if all checks pass; ``reason`` explains the
            outcome.
        """
        handler = _CHECKER_REGISTRY.get(criterion.type)
        if handler is None:
            return False, f"Unknown check type {criterion.type!r}"
        return handler(criterion.checks, env_state)
