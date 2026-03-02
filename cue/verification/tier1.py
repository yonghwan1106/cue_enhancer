"""Tier 1 verifier: fast, heuristic-based screenshot + a11y diff checks."""

from __future__ import annotations

import logging

import numpy as np

from cue.types import (
    AccessibilityNode,
    AccessibilityTree,
    ExpectedOutcome,
    TreeDiff,
    VerificationResult,
)

logger = logging.getLogger(__name__)

SSIM_CHANGE = 0.005
SSIM_MINOR = 0.001


def _compute_ssim(
    img_a: np.ndarray, img_b: np.ndarray, fast_mode: bool = False
) -> float:
    """Return SSIM-like score between two screenshots (0-1, higher = more similar).

    When *fast_mode* is True, uses mean-absolute-diff on downscaled images
    (~16x faster, no scikit-image dependency).
    """
    # Downscale large images for performance
    h, w = img_a.shape[:2]
    scale = max(1, min(h // 270, w // 480))
    if scale > 1:
        img_a = img_a[::scale, ::scale]
        img_b = img_b[::scale, ::scale]

    # Convert to grayscale
    if img_a.ndim == 3:
        gray_a = np.mean(img_a, axis=2).astype(np.float32)
    else:
        gray_a = img_a.astype(np.float32)
    if img_b.ndim == 3:
        gray_b = np.mean(img_b, axis=2).astype(np.float32)
    else:
        gray_b = img_b.astype(np.float32)

    if fast_mode:
        # Fast mean-absolute-diff normalised to approximate SSIM range (0-1)
        mad = float(np.mean(np.abs(gray_a - gray_b)) / 255.0)
        return max(0.0, 1.0 - mad * 10.0)

    from skimage.metrics import structural_similarity  # type: ignore[import]
    score: float = structural_similarity(gray_a, gray_b, data_range=255.0)
    return score


def _diff_trees(
    before: AccessibilityTree | None,
    after: AccessibilityTree | None,
) -> TreeDiff:
    """Compute a shallow diff between two accessibility trees."""
    diff = TreeDiff()
    if before is None and after is None:
        return diff

    before_nodes: dict[str, AccessibilityNode] = {}
    after_nodes: dict[str, AccessibilityNode] = {}

    if before is not None:
        for node in before.flatten():
            if node.id:
                before_nodes[node.id] = node

    if after is not None:
        for node in after.flatten():
            if node.id:
                after_nodes[node.id] = node

    for nid, node in after_nodes.items():
        if nid not in before_nodes:
            diff.added.append(node)
        else:
            b = before_nodes[nid]
            if set(b.states) != set(node.states):
                diff.state_changed.append((b, node))

    for nid, node in before_nodes.items():
        if nid not in after_nodes:
            diff.removed.append(node)

    return diff


def _check_text_markers(
    tree: AccessibilityTree | None,
    markers: list[str],
) -> bool:
    """Return True if all non-empty markers are found in the tree text."""
    if not markers:
        return False
    if tree is None:
        return False
    text = tree.get_all_text().lower()
    return all(m.lower() in text for m in markers if m)


class Tier1Verifier:
    """Fast verification via SSIM, a11y tree diff, and text marker checks."""

    def __init__(
        self,
        ssim_change: float = SSIM_CHANGE,
        ssim_minor: float = SSIM_MINOR,
        fast_mode: bool = False,
    ) -> None:
        self._ssim_change = ssim_change
        self._ssim_minor = ssim_minor
        self._fast_mode = fast_mode

    async def verify(
        self,
        before_screenshot: np.ndarray,
        after_screenshot: np.ndarray,
        before_tree: AccessibilityTree | None,
        after_tree: AccessibilityTree | None,
        expected: ExpectedOutcome,
    ) -> VerificationResult:
        details: dict = {}

        # --- Signal 1: SSIM screenshot diff ---
        ssim_score = _compute_ssim(before_screenshot, after_screenshot, fast_mode=self._fast_mode)
        ssim_diff = 1.0 - ssim_score  # higher diff = more change
        details["ssim_score"] = ssim_score
        details["ssim_diff"] = ssim_diff
        screenshot_changed = ssim_diff >= self._ssim_change
        screenshot_very_still = ssim_diff < self._ssim_minor
        logger.debug("Tier1 SSIM diff=%.4f changed=%s", ssim_diff, screenshot_changed)

        # --- Signal 2: A11y tree diff ---
        tree_diff = _diff_trees(before_tree, after_tree)
        tree_changed = bool(
            tree_diff.added or tree_diff.removed or tree_diff.state_changed
        )
        details["tree_added"] = len(tree_diff.added)
        details["tree_removed"] = len(tree_diff.removed)
        details["tree_state_changed"] = len(tree_diff.state_changed)
        logger.debug("Tier1 tree diff added=%d removed=%d states=%d",
                     len(tree_diff.added), len(tree_diff.removed), len(tree_diff.state_changed))

        # --- Signal 3: Text marker check ---
        markers_found = _check_text_markers(after_tree, expected.text_markers)
        details["markers_found"] = markers_found
        details["markers_requested"] = expected.text_markers

        # Count positive signals
        positive_signals = sum([screenshot_changed, tree_changed, markers_found])
        details["positive_signals"] = positive_signals

        # --- Decision logic ---
        if positive_signals >= 2:
            confidence = 0.8 + 0.1 * min(positive_signals - 2, 2)
            return VerificationResult(
                tier=1,
                success=True,
                confidence=min(confidence, 1.0),
                reason=f"Tier1 pass: {positive_signals}/3 positive signals",
                needs_escalation=False,
                details=details,
            )

        if positive_signals == 0 and screenshot_very_still:
            return VerificationResult(
                tier=1,
                success=False,
                confidence=0.9,
                reason="Tier1 fail: no signals detected and screen unchanged",
                needs_escalation=False,
                details=details,
            )

        # Ambiguous — escalate
        return VerificationResult(
            tier=1,
            success=False,
            confidence=0.4,
            reason=f"Tier1 ambiguous: {positive_signals}/3 signals, escalating",
            needs_escalation=True,
            details=details,
        )
