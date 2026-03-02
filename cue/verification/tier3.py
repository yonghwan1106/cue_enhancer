"""Tier 3: Semantic verification using Claude API (~2-3 seconds)."""

from __future__ import annotations

import base64
import io
import json
import logging

import numpy as np
from PIL import Image

from cue.types import VerificationResult

logger = logging.getLogger(__name__)


class Tier3Verifier:
    """Claude API-based semantic verification.

    Only called for ~5% of verifications where Tier 1+2 are inconclusive.
    Budget: max 3 calls per episode.
    """

    MAX_CALLS_PER_EPISODE = 3

    def __init__(self, client, model: str = "claude-sonnet-4-6-20250514"):
        self.client = client
        self.model = model
        self.call_count = 0

    async def verify(
        self,
        before_screenshot: np.ndarray | Image.Image,
        after_screenshot: np.ndarray | Image.Image,
        action_description: str,
        expected_outcome: str = "",
        tier2_details: dict | None = None,
    ) -> VerificationResult:
        """Ask Claude to judge action success from before/after screenshots."""
        if self.call_count >= self.MAX_CALLS_PER_EPISODE:
            return VerificationResult(
                tier=3, success=False, confidence=0.3,
                reason="Tier 3: episode call limit exceeded"
            )

        self.call_count += 1

        try:
            before_b64 = self._encode_image(before_screenshot)
            after_b64 = self._encode_image(after_screenshot)

            response = self.client.messages.create(
                model=self.model,
                max_tokens=150,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": (
                            f"Judge if this GUI action succeeded.\n"
                            f"Action: {action_description}\n"
                            f"Expected: {expected_outcome}\n"
                            f"First image = before, second = after.\n"
                            f"Reply JSON: {{\"success\": true/false, \"reason\": \"...\"}}"
                        )},
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/png",
                            "data": before_b64}},
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/png",
                            "data": after_b64}},
                    ]
                }]
            )

            result = self._parse_response(response)
            return VerificationResult(
                tier=3, success=result.get("success", False),
                confidence=0.95,
                reason=f"Tier 3 (Claude): {result.get('reason', 'no reason')}"
            )
        except Exception as e:
            logger.warning("Tier 3 verification failed: %s", e)
            return VerificationResult(
                tier=3, success=False, confidence=0.2,
                reason=f"Tier 3 error: {e}"
            )

    def reset_episode(self) -> None:
        self.call_count = 0

    def _encode_image(self, img: np.ndarray | Image.Image) -> str:
        if isinstance(img, np.ndarray):
            img = Image.fromarray(img)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def _parse_response(self, response) -> dict:
        text = response.content[0].text.strip()
        try:
            # Handle markdown code blocks
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except (json.JSONDecodeError, IndexError):
            # Fallback: look for success/fail keywords
            lower = text.lower()
            success = "success" in lower and "not" not in lower.split("success")[0][-10:]
            return {"success": success, "reason": text[:100]}
