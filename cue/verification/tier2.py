"""Tier 2 verifier: action-type-specific region and motion checks."""

from __future__ import annotations

import logging

import numpy as np

from cue.types import Action, VerificationResult

logger = logging.getLogger(__name__)

# Score thresholds (from VerificationConfig defaults)
_PASS_SCORE = 0.6
_FAIL_SCORE = 0.2

# Crop half-size (pixels) around click coordinates for region check
_CLICK_CROP_HALF = 80


def _images_same_size(a: np.ndarray, b: np.ndarray) -> bool:
    return a.shape == b.shape


def _region_diff(
    img_a: np.ndarray,
    img_b: np.ndarray,
    cx: int,
    cy: int,
    half: int = _CLICK_CROP_HALF,
) -> float:
    """Return normalised mean absolute pixel diff in a region around (cx, cy)."""
    h, w = img_a.shape[:2]
    x1 = max(0, cx - half)
    y1 = max(0, cy - half)
    x2 = min(w, cx + half)
    y2 = min(h, cy + half)
    crop_a = img_a[y1:y2, x1:x2].astype(np.float32)
    crop_b = img_b[y1:y2, x1:x2].astype(np.float32)
    if crop_a.size == 0:
        return 0.0
    return float(np.mean(np.abs(crop_a - crop_b))) / 255.0


def _overall_diff(img_a: np.ndarray, img_b: np.ndarray) -> float:
    """Return normalised mean absolute pixel diff across the whole image."""
    a = img_a.astype(np.float32)
    b = img_b.astype(np.float32)
    return float(np.mean(np.abs(a - b))) / 255.0


def _any_change(img_a: np.ndarray, img_b: np.ndarray, threshold: float = 0.003) -> bool:
    return _overall_diff(img_a, img_b) >= threshold


class Tier2Verifier:
    """Action-type-aware verification using pixel-level region comparisons."""

    def __init__(
        self,
        pass_score: float = _PASS_SCORE,
        fail_score: float = _FAIL_SCORE,
    ) -> None:
        self._pass_score = pass_score
        self._fail_score = fail_score

    async def verify(
        self,
        before_screenshot: np.ndarray,
        after_screenshot: np.ndarray,
        action: Action,
        tier1_details: dict | None = None,
    ) -> VerificationResult:
        details: dict = {"action_type": action.type, "tier1_details": tier1_details}

        if not _images_same_size(before_screenshot, after_screenshot):
            # Cannot compare — treat as changed (score = 0.7)
            details["note"] = "image size mismatch, assuming change"
            return VerificationResult(
                tier=2,
                success=True,
                confidence=0.5,
                reason="Tier2: image size mismatch, assuming action had effect",
                needs_escalation=False,
                details=details,
            )

        score = self._score_for_action(before_screenshot, after_screenshot, action, details)
        details["weighted_score"] = score
        logger.debug("Tier2 action=%s score=%.3f", action.type, score)

        if score >= self._pass_score:
            return VerificationResult(
                tier=2,
                success=True,
                confidence=0.6 + 0.3 * min((score - self._pass_score) / (1.0 - self._pass_score), 1.0),
                reason=f"Tier2 pass: score={score:.2f}",
                needs_escalation=False,
                details=details,
            )
        if score <= self._fail_score:
            return VerificationResult(
                tier=2,
                success=False,
                confidence=0.7,
                reason=f"Tier2 fail: score={score:.2f}",
                needs_escalation=False,
                details=details,
            )

        # Ambiguous
        return VerificationResult(
            tier=2,
            success=False,
            confidence=0.3,
            reason=f"Tier2 ambiguous: score={score:.2f}",
            needs_escalation=True,
            details=details,
        )

    # ------------------------------------------------------------------
    # Per-action-type scoring
    # ------------------------------------------------------------------

    def _score_for_action(
        self,
        before: np.ndarray,
        after: np.ndarray,
        action: Action,
        details: dict,
    ) -> float:
        action_type = action.type

        if action_type == "left_click":
            return self._score_click(before, after, action, details)

        if action_type == "double_click":
            return self._score_double_click(before, after, details)

        if action_type in ("type", "key"):
            return self._score_type_key(before, after, details)

        if action_type == "scroll":
            return self._score_scroll(before, after, details)

        # Fallback: any change at all
        changed = _any_change(before, after)
        details["fallback_changed"] = changed
        return 0.7 if changed else 0.1

    def _score_click(
        self,
        before: np.ndarray,
        after: np.ndarray,
        action: Action,
        details: dict,
    ) -> float:
        """Check if the region around the click coordinate changed."""
        if action.coordinate:
            cx, cy = action.coordinate
        else:
            # No coordinate — fall back to overall diff
            changed = _any_change(before, after)
            details["click_region_diff"] = None
            return 0.65 if changed else 0.1

        region_diff = _region_diff(before, after, cx, cy)
        details["click_region_diff"] = region_diff

        # Weighted: region diff counts most, overall change as secondary
        overall = _overall_diff(before, after)
        details["overall_diff"] = overall

        region_score = min(region_diff / 0.02, 1.0)  # normalise to [0,1]
        overall_score = min(overall / 0.01, 1.0)
        return 0.7 * region_score + 0.3 * overall_score

    def _score_double_click(
        self,
        before: np.ndarray,
        after: np.ndarray,
        details: dict,
    ) -> float:
        """Double-click should produce a significant screen change (open, select)."""
        overall = _overall_diff(before, after)
        details["overall_diff"] = overall
        # Expect more change than a single click — threshold 0.015
        score = min(overall / 0.015, 1.0)
        return score

    def _score_type_key(
        self,
        before: np.ndarray,
        after: np.ndarray,
        details: dict,
    ) -> float:
        """Typing or key press should produce some change (cursor move, text input)."""
        changed = _any_change(before, after, threshold=0.001)
        overall = _overall_diff(before, after)
        details["overall_diff"] = overall
        details["any_change"] = changed
        if changed:
            return max(0.65, min(overall / 0.005, 1.0))
        return 0.1

    def _score_scroll(
        self,
        before: np.ndarray,
        after: np.ndarray,
        details: dict,
    ) -> float:
        """Scroll should shift content — detect vertical or horizontal shift."""
        overall = _overall_diff(before, after)
        details["overall_diff"] = overall

        # Check vertical shift by comparing strips
        h = before.shape[0]
        strip_h = max(1, h // 10)
        top_before = before[:strip_h].astype(np.float32)
        top_after = after[:strip_h].astype(np.float32)
        bot_before = before[h - strip_h:].astype(np.float32)
        bot_after = after[h - strip_h:].astype(np.float32)
        top_diff = float(np.mean(np.abs(top_before - top_after))) / 255.0
        bot_diff = float(np.mean(np.abs(bot_before - bot_after))) / 255.0
        details["scroll_top_diff"] = top_diff
        details["scroll_bot_diff"] = bot_diff

        shift_score = min((top_diff + bot_diff) / 0.02, 1.0)
        overall_score = min(overall / 0.01, 1.0)
        return 0.6 * shift_score + 0.4 * overall_score
