"""Safety Gate: classifies actions as SAFE, NEEDS_CONFIRMATION, or BLOCKED."""

from __future__ import annotations

import logging
import re
import time

from cue.config import EnhancerLevel, SafetyConfig
from cue.types import Action, PermissionLevel, SafetyDecision, SafetyLevel

logger = logging.getLogger(__name__)


class EmergencyStop:
    """Detects repeated actions and timeouts to prevent infinite loops."""

    def __init__(self, max_repeated: int = 5, timeout: int = 600):
        self.max_repeated = max_repeated
        self.timeout = timeout
        self._action_history: list[str] = []
        self._start_time: float = 0.0

    def start(self) -> None:
        """Start the episode timer."""
        self._start_time = time.time()
        self._action_history.clear()

    def check(self, action: Action) -> tuple[bool, str]:
        """Check if execution should continue. Returns (safe, reason)."""
        # Timeout check
        if self._start_time > 0 and time.time() - self._start_time > self.timeout:
            return False, f"Timeout exceeded ({self.timeout}s)"

        # Repeated action check
        action_key = f"{action.type}:{action.text}:{action.coordinate}"
        self._action_history.append(action_key)

        if len(self._action_history) >= self.max_repeated:
            recent = self._action_history[-self.max_repeated:]
            if len(set(recent)) == 1:
                return False, f"Repeated action detected ({self.max_repeated}x): {action_key}"

        return True, ""

    def reset(self) -> None:
        """Reset for a new episode."""
        self._action_history.clear()
        self._start_time = 0.0


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

        # Phase 3: permission level and emergency stop
        self._permission_level = PermissionLevel(self._config.permission_level)
        self._emergency_stop = EmergencyStop(
            max_repeated=self._config.max_repeated_actions,
            timeout=600,
        )

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

    def check_with_permission(self, action: Action) -> SafetyDecision:
        """Classify action applying the configured permission level.

        Calls check_action() for the base decision, then adjusts based on
        self._permission_level.
        """
        base = self.check_action(action)
        level = self._permission_level

        if base.level == SafetyLevel.BLOCKED:
            # Always blocked regardless of permission level
            return base

        if base.level == SafetyLevel.NEEDS_CONFIRMATION:
            if level == PermissionLevel.OBSERVE:
                return SafetyDecision(
                    level=SafetyLevel.BLOCKED,
                    reason="Observe mode: user must execute",
                    pattern_matched=base.pattern_matched,
                )
            if level == PermissionLevel.CONFIRM:
                return base
            if level == PermissionLevel.AUTO_SAFE:
                return base
            # FULL_AUTO: auto-approve
            return SafetyDecision(
                level=SafetyLevel.SAFE,
                reason="Full-auto mode: action auto-approved",
                pattern_matched=base.pattern_matched,
            )

        # base.level == SafetyLevel.SAFE
        if level == PermissionLevel.OBSERVE:
            return SafetyDecision(
                level=SafetyLevel.NEEDS_CONFIRMATION,
                reason="Observe mode: user approval required",
                pattern_matched=base.pattern_matched,
            )
        if level == PermissionLevel.CONFIRM:
            return SafetyDecision(
                level=SafetyLevel.NEEDS_CONFIRMATION,
                reason="Confirm mode: all actions need approval",
                pattern_matched=base.pattern_matched,
            )
        # AUTO_SAFE or FULL_AUTO: safe actions pass through
        return base

    def check_emergency(self, action: Action) -> SafetyDecision:
        """Check the emergency stop conditions for the given action."""
        safe, reason = self._emergency_stop.check(action)
        if not safe:
            return SafetyDecision(
                level=SafetyLevel.BLOCKED,
                reason=reason,
            )
        return SafetyDecision(
            level=SafetyLevel.SAFE,
            reason="Emergency stop conditions not triggered",
        )

    def start_episode(self) -> None:
        """Start a new episode, resetting the emergency stop timer."""
        self._emergency_stop.start()

    def reset_episode(self) -> None:
        """Reset episode state in the emergency stop."""
        self._emergency_stop.reset()

    @property
    def permission_level(self) -> PermissionLevel:
        """Return the configured permission level."""
        return self._permission_level
