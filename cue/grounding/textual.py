"""Text grounding expert using OCR (tesseract or easyocr)."""

from __future__ import annotations

import asyncio

from PIL import Image

from cue.types import TextElement


class TextGrounder:
    """Extracts text elements from a screenshot via OCR."""

    def __init__(
        self,
        engine: str = "tesseract",
        languages: list[str] | None = None,
        confidence_threshold: float = 0.6,
    ) -> None:
        self._engine = engine
        self._languages = languages or ["eng"]
        self._confidence_threshold = confidence_threshold
        self._easyocr_reader: object | None = None  # lazy-loaded

    async def extract(self, screenshot: Image.Image) -> list[TextElement]:
        """Extract text elements from screenshot using the configured OCR engine."""
        if self._engine == "easyocr":
            return await self._extract_easyocr(screenshot)
        return await self._extract_tesseract(screenshot)

    # ------------------------------------------------------------------
    # Tesseract backend
    # ------------------------------------------------------------------

    async def _extract_tesseract(self, screenshot: Image.Image) -> list[TextElement]:
        try:
            import pytesseract  # type: ignore[import]
        except ImportError:
            return []

        data = await asyncio.to_thread(
            pytesseract.image_to_data,
            screenshot,
            config="--psm 6",
            output_type=pytesseract.Output.DICT,
        )

        elements: list[TextElement] = []
        n = len(data["text"])
        for i in range(n):
            raw_conf = data["conf"][i]
            # pytesseract returns conf as int -1..100; filter by > 60
            if raw_conf < 60:
                continue
            text = str(data["text"][i]).strip()
            if not text:
                continue
            x = int(data["left"][i])
            y = int(data["top"][i])
            w = int(data["width"][i])
            h = int(data["height"][i])
            if w <= 0 or h <= 0:
                continue
            elements.append(
                TextElement(
                    text=text,
                    bbox=(x, y, x + w, y + h),
                    confidence=round(raw_conf / 100.0, 4),
                )
            )

        return elements

    # ------------------------------------------------------------------
    # EasyOCR backend (lazy import)
    # ------------------------------------------------------------------

    async def _extract_easyocr(self, screenshot: Image.Image) -> list[TextElement]:
        try:
            import easyocr  # type: ignore[import]
        except ImportError:
            return []

        if self._easyocr_reader is None:
            self._easyocr_reader = easyocr.Reader(self._languages, verbose=False)

        import numpy as np

        img_array = np.array(screenshot.convert("RGB"))
        raw_results = await asyncio.to_thread(
            self._easyocr_reader.readtext, img_array  # type: ignore[union-attr]
        )

        elements: list[TextElement] = []
        for bbox_pts, text, conf in raw_results:
            if conf < 0.5:
                continue
            text = str(text).strip()
            if not text:
                continue
            # EasyOCR returns 4-point polygon [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
            xs = [int(p[0]) for p in bbox_pts]
            ys = [int(p[1]) for p in bbox_pts]
            x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
            elements.append(
                TextElement(
                    text=text,
                    bbox=(x1, y1, x2, y2),
                    confidence=round(float(conf), 4),
                )
            )

        return elements
