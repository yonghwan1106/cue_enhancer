"""Verification orchestrator: runs Tier 1 then Tier 2 as needed."""

from __future__ import annotations

import logging

import numpy as np

from cue.config import EnhancerLevel, VerificationConfig
from cue.types import (
    AccessibilityTree,
    Action,
    ExpectedOutcome,
    VerificationResult,
)
from cue.verification.tier1 import Tier1Verifier
from cue.verification.tier2 import Tier2Verifier
from cue.verification.tier3 import Tier3Verifier

logger = logging.getLogger(__name__)


class VerificationOrchestrator:
    """Routes verification through Tier 1 → Tier 2 as needed.

    Tier 3 (VLM-based) is reserved for Phase 2 and not implemented here.
    """

    def __init__(
        self,
        config: VerificationConfig | None = None,
        tier3: Tier3Verifier | None = None,
    ) -> None:
        self._config = config or VerificationConfig()
        self._tier1 = Tier1Verifier(
            ssim_change=self._config.tier1_ssim_threshold,
            ssim_minor=self._config.tier1_minor_threshold,
            fast_mode=(self._config.level == EnhancerLevel.BASIC),
        )
        self._tier2 = Tier2Verifier(
            pass_score=self._config.tier2_pass_score,
            fail_score=self._config.tier2_fail_score,
        )
        self._tier3 = tier3

    async def verify_step(
        self,
        before_screenshot: np.ndarray,
        after_screenshot: np.ndarray,
        before_tree: AccessibilityTree | None,
        after_tree: AccessibilityTree | None,
        action: Action,
        expected: ExpectedOutcome,
    ) -> VerificationResult:
        """Run verification pipeline and return the final result."""

        # If verification is disabled, always succeed.
        if self._config.level == EnhancerLevel.OFF:
            logger.debug("Verification off — returning success")
            return VerificationResult(
                tier=0,
                success=True,
                confidence=1.0,
                reason="Verification disabled (level=off)",
                needs_escalation=False,
            )

        # --- Tier 1 ---
        logger.debug("Running Tier 1 verification")
        t1_result = await self._tier1.verify(
            before_screenshot=before_screenshot,
            after_screenshot=after_screenshot,
            before_tree=before_tree,
            after_tree=after_tree,
            expected=expected,
        )

        # BASIC level: Tier 1 only, never escalate to higher tiers
        if self._config.level == EnhancerLevel.BASIC:
            t1_result.needs_escalation = False
            return t1_result

        if not t1_result.needs_escalation:
            logger.debug(
                "Tier 1 decisive: success=%s confidence=%.2f",
                t1_result.success,
                t1_result.confidence,
            )
            return t1_result

        # --- Tier 2 ---
        logger.debug("Tier 1 escalated — running Tier 2 verification")
        t2_result = await self._tier2.verify(
            before_screenshot=before_screenshot,
            after_screenshot=after_screenshot,
            action=action,
            tier1_details=t1_result.details,
        )

        if not t2_result.needs_escalation:
            logger.debug(
                "Tier 2 decisive: success=%s confidence=%.2f",
                t2_result.success,
                t2_result.confidence,
            )
            return t2_result

        # --- Tier 3 (Claude API semantic verification) ---
        if self._tier3 is not None:
            logger.debug("Tier 2 escalated — running Tier 3 (Claude API) verification")
            t3_result = await self._tier3.verify(
                before_screenshot=before_screenshot,
                after_screenshot=after_screenshot,
                action_description=f"{action.type} at {action.coordinate}",
                expected_outcome=expected.description,
                tier2_details=t2_result.details,
            )
            logger.debug(
                "Tier 3 decisive: success=%s confidence=%.2f",
                t3_result.success,
                t3_result.confidence,
            )
            return t3_result

        logger.debug("Tier 2 escalated — Tier 3 not available, returning failure")
        return VerificationResult(
            tier=2,
            success=False,
            confidence=0.2,
            reason="Verification inconclusive after Tier 1 + Tier 2; Tier 3 not available",
            needs_escalation=False,
            details=t2_result.details,
            diagnosis="Action effect could not be confirmed heuristically. Manual review or Tier 3 (VLM) required.",
        )
