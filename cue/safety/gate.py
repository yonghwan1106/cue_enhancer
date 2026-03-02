"""Safety Gate: classifies actions as SAFE, NEEDS_CONFIRMATION, or BLOCKED."""

from __future__ import annotations

import logging
import re

from cue.config import EnhancerLevel, SafetyConfig
from cue.types import Action, SafetyDecision, SafetyLevel

logger = logging.getLogger(__name__)


class SafetyGate:
    """Three-level action classifier based on configurable pattern lists."""

    def __init__(self, config: SafetyConfig | None = None) -> None:
        self._config = config or SafetyConfig()

        # Pre-compile regex patterns for performance
        self._blocked_patterns: list[tuple[str, re.Pattern[str]]] = [
            (raw, re.compile(re.escape(raw), re.IGNORECASE))
            for raw in self._config.blocked_commands
        ]
        self._confirmation_patterns: list[tuple[str, re.Pattern[str]]] = [
            (raw, re.compile(r"\b" + re.escape(raw) + r"\b", re.IGNORECASE))
            for raw in self._config.confirmation_patterns
        ]
        self._sensitive_paths: list[str] = self._config.sensitive_paths

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_action(self, action: Action) -> SafetyDecision:
        """Classify the action and return a SafetyDecision."""
        if self._config.level == EnhancerLevel.OFF:
            return SafetyDecision(
                level=SafetyLevel.SAFE,
                reason="Safety gate disabled (level=off)",
            )

        # Gather text fields to inspect
        candidates: list[str] = []
        if action.text:
            candidates.append(action.text)
        if action.key:
            candidates.append(action.key)

        combined = " ".join(candidates)

        # 1. BLOCKED check
        for raw, pattern in self._blocked_patterns:
            if pattern.search(combined):
                logger.warning("Safety BLOCKED: pattern=%r action=%s", raw, action.type)
                return SafetyDecision(
                    level=SafetyLevel.BLOCKED,
                    reason=f"Matched blocked command pattern: {raw!r}",
                    pattern_matched=raw,
                )

        # 2. NEEDS_CONFIRMATION: confirmation words
        for raw, pattern in self._confirmation_patterns:
            if pattern.search(combined):
                logger.info(
                    "Safety NEEDS_CONFIRMATION (word): pattern=%r action=%s",
                    raw,
                    action.type,
                )
                return SafetyDecision(
                    level=SafetyLevel.NEEDS_CONFIRMATION,
                    reason=f"Matched confirmation pattern: {raw!r}",
                    pattern_matched=raw,
                )

        # 3. NEEDS_CONFIRMATION: sensitive path access in text
        for path in self._sensitive_paths:
            if path.lower() in combined.lower():
                logger.info(
                    "Safety NEEDS_CONFIRMATION (path): path=%r action=%s",
                    path,
                    action.type,
                )
                return SafetyDecision(
                    level=SafetyLevel.NEEDS_CONFIRMATION,
                    reason=f"Sensitive path access detected: {path!r}",
                    pattern_matched=path,
                )

        return SafetyDecision(
            level=SafetyLevel.SAFE,
            reason="No safety patterns matched",
        )

    def check_screen(self, screen_state: object) -> SafetyDecision:
        """Screen-state safety check (placeholder for Phase 1).

        Always returns SAFE. Phase 2 will add VLM-based screen analysis.
        """
        return SafetyDecision(
            level=SafetyLevel.SAFE,
            reason="Screen check not implemented (Phase 1 placeholder)",
        )
