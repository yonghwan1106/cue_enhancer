"""Visual grounding expert using OpenCV edge detection and contour analysis."""

from __future__ import annotations

import math

import cv2
import numpy as np
from PIL import Image

from cue.types import VisualElement


class OpenCVGrounder:
    """Detects UI elements from a screenshot using OpenCV contour analysis."""

    _MIN_W = 15
    _MIN_H = 10
    _MAX_W = 800
    _MAX_H = 600

    def __init__(self, nms_iou_threshold: float = 0.5) -> None:
        self._nms_iou = nms_iou_threshold

    async def detect(self, screenshot: Image.Image) -> list[VisualElement]:
        """Detect UI elements via Canny edges + contour filtering + NMS."""
        img = np.array(screenshot.convert("RGB"))
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)

        edges = cv2.Canny(gray, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        candidates: list[VisualElement] = []
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            if not (self._MIN_W <= w <= self._MAX_W and self._MIN_H <= h <= self._MAX_H):
                continue
            elem_type = self._classify(w, h)
            confidence = self._confidence(cnt, w, h)
            candidates.append(
                VisualElement(
                    type=elem_type,
                    bbox=(x, y, x + w, y + h),
                    confidence=confidence,
                )
            )

        return self._nms(candidates)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(w: int, h: int) -> str:
        ratio = w / max(h, 1)
        if ratio > 3 and h < 40:
            return "text_field"
        if 0.8 < ratio < 1.5 and w < 50:
            return "icon"
        if ratio > 2 and h < 35:
            return "button"
        if w > 200 and h > 100:
            return "panel"
        return "unknown"

    @staticmethod
    def _confidence(contour: np.ndarray, w: int, h: int) -> float:
        """Score in [0, 1] based on rectangularity and circularity."""
        area = float(cv2.contourArea(contour))
        if area < 1:
            return 0.0

        # Rectangularity: how close is the contour area to its bounding rect area
        rect_area = float(w * h)
        rectangularity = min(area / rect_area, 1.0)

        # Circularity: 4*pi*area / perimeter^2  (=1 for perfect circle)
        perimeter = cv2.arcLength(contour, True)
        if perimeter < 1:
            circularity = 0.0
        else:
            circularity = min((4 * math.pi * area) / (perimeter ** 2), 1.0)

        return round(0.6 * rectangularity + 0.4 * circularity, 4)

    def _nms(self, elements: list[VisualElement]) -> list[VisualElement]:
        """Non-Maximum Suppression over bounding boxes sorted by confidence."""
        if not elements:
            return []

        sorted_elems = sorted(elements, key=lambda e: e.confidence, reverse=True)
        kept: list[VisualElement] = []

        for candidate in sorted_elems:
            suppressed = False
            for accepted in kept:
                if self._iou(candidate.bbox, accepted.bbox) > self._nms_iou:
                    suppressed = True
                    break
            if not suppressed:
                kept.append(candidate)

        return kept

    @staticmethod
    def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
        ix1 = max(a[0], b[0])
        iy1 = max(a[1], b[1])
        ix2 = min(a[2], b[2])
        iy2 = min(a[3], b[3])
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        return inter / (area_a + area_b - inter)
