"""Tests for CUE Safety Gate v2 (Phase 3)."""

from __future__ import annotations

import time

import pytest

from cue.config import SafetyConfig
from cue.safety.gate import EmergencyStop, SafetyGate
from cue.types import Action, PermissionLevel, SafetyLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_action() -> Action:
    """A click with no pattern match -> SAFE."""
    return Action(type="left_click", coordinate=(100, 100))


def _confirm_action() -> Action:
    """Contains 'send email' -> NEEDS_CONFIRMATION."""
    return Action(type="key", text="send email")


def _blocked_action() -> Action:
    """Contains 'rm -rf' -> BLOCKED."""
    return Action(type="key", text="rm -rf /")


# ---------------------------------------------------------------------------
# TestEmergencyStop
# ---------------------------------------------------------------------------


class TestEmergencyStop:
    def test_start_clears_history_and_sets_time(self):
        es = EmergencyStop(max_repeated=5, timeout=600)
        es._action_history.append("dummy")
        es.start()
        assert es._action_history == []
        assert es._start_time > 0

    def test_check_returns_safe_for_normal_action(self):
        es = EmergencyStop(max_repeated=5, timeout=600)
        es.start()
        safe, reason = es.check(_safe_action())
        assert safe is True
        assert reason == ""

    def test_repeated_action_triggers_stop(self):
        es = EmergencyStop(max_repeated=5, timeout=600)
        es.start()
        action = Action(type="left_click", coordinate=(50, 50))
        for _ in range(4):
            safe, _ = es.check(action)
            assert safe is True
        # 5th identical action triggers stop
        safe, reason = es.check(action)
        assert safe is False
        assert "Repeated action detected" in reason
        assert "5x" in reason

    def test_mixed_actions_do_not_trigger(self):
        es = EmergencyStop(max_repeated=5, timeout=600)
        es.start()
        actions = [
            Action(type="left_click", coordinate=(i * 10, i * 10))
            for i in range(1, 6)
        ]
        for action in actions:
            safe, reason = es.check(action)
            assert safe is True, f"Expected safe but got blocked: {reason}"

    def test_timeout_detection(self):
        es = EmergencyStop(max_repeated=5, timeout=600)
        # Set _start_time 601 seconds in the past to exceed the 600s timeout
        es._start_time = time.time() - 601
        safe, reason = es.check(_safe_action())
        assert safe is False
        assert "Timeout exceeded" in reason
        assert "600s" in reason

    def test_reset_clears_state(self):
        es = EmergencyStop(max_repeated=5, timeout=600)
        es.start()
        es._action_history.extend(["a", "b", "c"])
        es.reset()
        assert es._action_history == []
        assert es._start_time == 0.0

    def test_no_timeout_when_start_not_called(self):
        """_start_time == 0.0 means no timeout check is performed."""
        es = EmergencyStop(max_repeated=5, timeout=600)
        # _start_time is 0.0 by default; timeout guard skips the check
        safe, reason = es.check(_safe_action())
        assert safe is True


# ---------------------------------------------------------------------------
# TestPermissionLevels
# ---------------------------------------------------------------------------


class TestPermissionLevels:
    def _gate(self, level: int) -> SafetyGate:
        return SafetyGate(SafetyConfig(permission_level=level))

    # OBSERVE (0)
    def test_observe_safe_action_becomes_needs_confirmation(self):
        gate = self._gate(0)
        decision = gate.check_with_permission(_safe_action())
        assert decision.level == SafetyLevel.NEEDS_CONFIRMATION
        assert "Observe mode" in decision.reason

    def test_observe_blocked_action_stays_blocked(self):
        gate = self._gate(0)
        decision = gate.check_with_permission(_blocked_action())
        assert decision.level == SafetyLevel.BLOCKED

    def test_observe_confirm_action_becomes_blocked(self):
        """In observe mode, NEEDS_CONFIRMATION -> BLOCKED (user must execute)."""
        gate = self._gate(0)
        decision = gate.check_with_permission(_confirm_action())
        assert decision.level == SafetyLevel.BLOCKED
        assert "Observe mode" in decision.reason

    # CONFIRM (1)
    def test_confirm_safe_action_becomes_needs_confirmation(self):
        gate = self._gate(1)
        decision = gate.check_with_permission(_safe_action())
        assert decision.level == SafetyLevel.NEEDS_CONFIRMATION

    def test_confirm_needs_confirmation_stays(self):
        gate = self._gate(1)
        decision = gate.check_with_permission(_confirm_action())
        assert decision.level == SafetyLevel.NEEDS_CONFIRMATION

    def test_confirm_blocked_stays_blocked(self):
        gate = self._gate(1)
        decision = gate.check_with_permission(_blocked_action())
        assert decision.level == SafetyLevel.BLOCKED

    # AUTO_SAFE (2)
    def test_auto_safe_safe_action_stays_safe(self):
        gate = self._gate(2)
        decision = gate.check_with_permission(_safe_action())
        assert decision.level == SafetyLevel.SAFE

    def test_auto_safe_needs_confirmation_stays(self):
        gate = self._gate(2)
        decision = gate.check_with_permission(_confirm_action())
        assert decision.level == SafetyLevel.NEEDS_CONFIRMATION

    def test_auto_safe_blocked_stays_blocked(self):
        gate = self._gate(2)
        decision = gate.check_with_permission(_blocked_action())
        assert decision.level == SafetyLevel.BLOCKED

    # FULL_AUTO (3)
    def test_full_auto_safe_action_stays_safe(self):
        gate = self._gate(3)
        decision = gate.check_with_permission(_safe_action())
        assert decision.level == SafetyLevel.SAFE

    def test_full_auto_needs_confirmation_auto_approved(self):
        gate = self._gate(3)
        decision = gate.check_with_permission(_confirm_action())
        assert decision.level == SafetyLevel.SAFE
        assert "auto-approved" in decision.reason

    def test_full_auto_blocked_always_blocked(self):
        gate = self._gate(3)
        decision = gate.check_with_permission(_blocked_action())
        assert decision.level == SafetyLevel.BLOCKED


# ---------------------------------------------------------------------------
# TestSafetyGateV2Integration
# ---------------------------------------------------------------------------


class TestSafetyGateV2Integration:
    def test_check_with_permission_works(self):
        gate = SafetyGate(SafetyConfig(permission_level=2))
        decision = gate.check_with_permission(_safe_action())
        assert decision.level == SafetyLevel.SAFE

    def test_check_emergency_safe_for_normal_action(self):
        gate = SafetyGate()
        gate.start_episode()
        decision = gate.check_emergency(_safe_action())
        assert decision.level == SafetyLevel.SAFE

    def test_check_emergency_blocks_repeated_actions(self):
        gate = SafetyGate(SafetyConfig(max_repeated_actions=5))
        gate.start_episode()
        action = Action(type="left_click", coordinate=(10, 10))
        for _ in range(4):
            gate.check_emergency(action)
        decision = gate.check_emergency(action)
        assert decision.level == SafetyLevel.BLOCKED
        assert "Repeated action" in decision.reason

    def test_start_episode_and_reset_episode(self):
        gate = SafetyGate()
        gate.start_episode()
        assert gate._emergency_stop._start_time > 0
        gate.reset_episode()
        assert gate._emergency_stop._start_time == 0.0
        assert gate._emergency_stop._action_history == []

    def test_permission_level_property(self):
        gate = SafetyGate(SafetyConfig(permission_level=3))
        assert gate.permission_level == PermissionLevel.FULL_AUTO

    def test_permission_level_default(self):
        gate = SafetyGate()
        assert gate.permission_level == PermissionLevel.AUTO_SAFE

    def test_backward_compat_check_action_still_works(self):
        gate = SafetyGate()
        assert gate.check_action(_safe_action()).level == SafetyLevel.SAFE
        assert gate.check_action(_confirm_action()).level == SafetyLevel.NEEDS_CONFIRMATION
        assert gate.check_action(_blocked_action()).level == SafetyLevel.BLOCKED

    def test_backward_compat_check_screen_still_works(self):
        gate = SafetyGate()
        decision = gate.check_screen(object())
        assert decision.level == SafetyLevel.SAFE
