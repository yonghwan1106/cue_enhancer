"""Source merger: combines visual, text, and structural elements into UIElements."""

from __future__ import annotations

from cue.types import StructuralElement, TextElement, UIElement, VisualElement

# Confidence contributions
_CONF_VISUAL_ONLY = 0.40
_CONF_TEXT_BONUS = 0.25
_CONF_STRUCTURAL_BONUS = 0.35

_IOU_MATCH_THRESHOLD = 0.3


class SourceMerger:
    """Merges outputs from three grounding experts into a unified UIElement list."""

    def merge(
        self,
        visual: list[VisualElement],
        text: list[TextElement],
        structural: list[StructuralElement],
    ) -> list[UIElement]:
        """Produce a deduplicated, confidence-ranked list of UIElements."""
        # Start from visual elements as the base
        merged: list[UIElement] = []
        used_text: set[int] = set()
        used_structural: set[int] = set()

        for vel in visual:
            elem = UIElement(
                type=vel.type,
                bbox=vel.bbox,
                label="",
                confidence=_CONF_VISUAL_ONLY,
                sources=["visual"],
            )

            # Try to match a text element
            best_text_idx = self._best_match(vel.bbox, text, used_text)
            if best_text_idx is not None:
                tel = text[best_text_idx]
                used_text.add(best_text_idx)
                elem.label = tel.text
                elem.confidence += _CONF_TEXT_BONUS
                elem.sources.append("text")
                # text bbox takes priority over visual for precision
                elem.bbox = tel.bbox

            # Try to match a structural element
            best_struct_idx = self._best_match(elem.bbox, structural, used_structural)
            if best_struct_idx is not None:
                sel = structural[best_struct_idx]
                used_structural.add(best_struct_idx)
                if not elem.label:
                    elem.label = sel.name
                if sel.role:
                    elem.type = sel.role
                elem.confidence += _CONF_STRUCTURAL_BONUS
                elem.sources.append("structural")
                # structural bbox has highest priority
                elem.bbox = sel.bbox

            elem.confidence = round(min(elem.confidence, 1.0), 4)
            merged.append(elem)

        # Add unmatched text-only elements
        for i, tel in enumerate(text):
            if i in used_text:
                continue
            merged.append(
                UIElement(
                    type="text_field",
                    bbox=tel.bbox,
                    label=tel.text,
                    confidence=round(_CONF_TEXT_BONUS, 4),
                    sources=["text"],
                )
            )

        # Add unmatched structural-only elements
        for i, sel in enumerate(structural):
            if i in used_structural:
                continue
            merged.append(
                UIElement(
                    type=sel.role or "unknown",
                    bbox=sel.bbox,
                    label=sel.name,
                    confidence=round(_CONF_STRUCTURAL_BONUS, 4),
                    sources=["structural"],
                )
            )

        merged.sort(key=lambda e: e.confidence, reverse=True)
        return merged

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _best_match(
        self,
        ref_bbox: tuple[int, int, int, int],
        candidates: list[VisualElement] | list[TextElement] | list[StructuralElement],
        used: set[int],
    ) -> int | None:
        best_idx: int | None = None
        best_iou = _IOU_MATCH_THRESHOLD
        for i, cand in enumerate(candidates):
            if i in used:
                continue
            iou = self._calc_iou(ref_bbox, cand.bbox)
            if iou > best_iou:
                best_iou = iou
                best_idx = i
        return best_idx

    @staticmethod
    def _calc_iou(
        a: tuple[int, int, int, int],
        b: tuple[int, int, int, int],
    ) -> float:
        """Calculate Intersection over Union for two bounding boxes."""
        ix1 = max(a[0], b[0])
        iy1 = max(a[1], b[1])
        ix2 = min(a[2], b[2])
        iy2 = min(a[3], b[3])
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        union = area_a + area_b - inter
        if union <= 0:
            return 0.0
        return inter / union
