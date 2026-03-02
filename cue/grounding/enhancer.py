"""Grounding Enhancer orchestrator: runs three experts in parallel and merges results."""

from __future__ import annotations

import asyncio
import hashlib
import time
from typing import Any

from PIL import Image

from cue.config import GroundingConfig
from cue.grounding.merger import SourceMerger
from cue.grounding.structural import StructuralGrounder
from cue.grounding.textual import TextGrounder
from cue.grounding.visual import OpenCVGrounder
from cue.types import (
    GroundingResult,
    GroundingStats,
    StructuralElement,
    TextElement,
    UIElement,
    VisualElement,
)

_HALLUCINATION_CONF_THRESHOLD = 0.2


class GroundingEnhancer:
    """Orchestrates visual, textual, and structural grounders into a GroundingResult."""

    def __init__(self, config: GroundingConfig | None = None) -> None:
        self._config = config or GroundingConfig()
        self._visual = OpenCVGrounder(nms_iou_threshold=self._config.nms_iou_threshold)
        self._text = TextGrounder(
            engine=self._config.ocr_engine,
            languages=self._config.ocr_languages,
            confidence_threshold=self._config.confidence_threshold,
        )
        self._structural = StructuralGrounder()
        self._merger = SourceMerger()

        # Simple dict cache: key -> (result, expiry_timestamp)
        self._cache: dict[str, tuple[GroundingResult, float]] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enhance(
        self, screenshot: Image.Image, task_context: str = ""
    ) -> GroundingResult:
        """Run all three experts in parallel and return a merged GroundingResult."""
        cache_key = self._cache_key(screenshot, task_context)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        t0 = time.monotonic()

        visual_elements, text_elements, structural_elements = await asyncio.gather(
            self._visual.detect(screenshot),
            self._text.extract(screenshot),
            self._structural.parse(),
        )

        merged = self._merger.merge(visual_elements, text_elements, structural_elements)
        merged = self._filter_hallucinations(merged)

        duration_ms = (time.monotonic() - t0) * 1000.0
        stats = GroundingStats(
            visual_count=len(visual_elements),
            text_count=len(text_elements),
            structural_count=len(structural_elements),
            merged_count=len(merged),
            avg_confidence=(
                sum(e.confidence for e in merged) / len(merged) if merged else 0.0
            ),
            duration_ms=round(duration_ms, 2),
        )

        description = self._build_description(merged, task_context)
        zoom_recommendations = self._zoom_candidates(merged)

        result = GroundingResult(
            elements=merged,
            element_description=description,
            zoom_recommendations=zoom_recommendations,
            stats=stats,
        )

        self._put_cached(cache_key, result)
        return result

    async def locate(
        self, screenshot: Image.Image, target: str
    ) -> UIElement | None:
        """Find the best-matching UIElement for a target label string."""
        result = await self.enhance(screenshot)
        target_lower = target.lower()

        # Exact label match first (case-insensitive)
        for elem in result.elements:
            if elem.label.lower() == target_lower:
                return elem

        # Partial label match
        for elem in result.elements:
            if target_lower in elem.label.lower():
                return elem

        # Type match
        for elem in result.elements:
            if target_lower in elem.type.lower():
                return elem

        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_hallucinations(elements: list[UIElement]) -> list[UIElement]:
        """Remove low-confidence elements that appear in only one source."""
        return [
            e
            for e in elements
            if not (e.confidence < _HALLUCINATION_CONF_THRESHOLD and len(e.sources) <= 1)
        ]

    @staticmethod
    def _build_description(elements: list[UIElement], task_context: str) -> str:
        """Generate a natural-language summary of detected elements."""
        if not elements:
            return "No UI elements detected on screen."

        type_counts: dict[str, int] = {}
        for elem in elements:
            type_counts[elem.type] = type_counts.get(elem.type, 0) + 1

        parts: list[str] = []
        for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            label = etype.replace("_", " ")
            parts.append(f"{count} {label}{'s' if count > 1 else ''}")

        summary = f"Detected {len(elements)} UI elements: {', '.join(parts)}."

        # Highlight high-confidence labelled elements
        labelled = [e for e in elements if e.label and e.confidence >= 0.6][:5]
        if labelled:
            names = ", ".join(f'"{e.label}"' for e in labelled)
            summary += f" Notable elements include {names}."

        if task_context:
            summary += f" Task context: {task_context}."

        return summary

    @staticmethod
    def _zoom_candidates(elements: list[UIElement]) -> list[UIElement]:
        """Return elements where confidence is low enough to warrant a zoom-in."""
        return [e for e in elements if e.confidence < 0.4]

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(screenshot: Image.Image, task_context: str) -> str:
        img_bytes = screenshot.tobytes()
        digest = hashlib.md5(img_bytes + task_context.encode()).hexdigest()
        return digest

    def _get_cached(self, key: str) -> GroundingResult | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        result, expiry = entry
        if time.monotonic() > expiry:
            del self._cache[key]
            return None
        return result

    def _put_cached(self, key: str, result: GroundingResult) -> None:
        expiry = time.monotonic() + self._config.cache_ttl_seconds
        self._cache[key] = (result, expiry)
