"""OmniParser V2 grounding backend for CUE."""

from __future__ import annotations

import logging

from PIL import Image

from cue.config import OmniParserConfig
from cue.types import OmniParserElement, OmniParserResult, UIElement

logger = logging.getLogger(__name__)


class OmniParserGrounder:
    """Wraps OmniParser V2 for UI element detection.

    When the model weights are not configured or not loadable, all methods
    degrade gracefully: is_available() returns False, parse() returns an empty
    OmniParserResult, and detect_elements() returns an empty list.
    """

    def __init__(self, config: OmniParserConfig | None = None) -> None:
        self._config = config or OmniParserConfig()
        self._model = None
        self._loaded = False

        if self._config.enabled and self._config.model_path:
            self._try_load()

    # ── Public API ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True only when the model is loaded and ready."""
        return self._loaded and self._model is not None

    def parse(self, image: Image.Image) -> OmniParserResult:
        """Run OmniParser inference on *image*.

        Returns an empty OmniParserResult when the model is unavailable.
        """
        if not self.is_available():
            return OmniParserResult()

        try:
            return self._run_inference(image)
        except Exception:
            logger.exception("OmniParser inference failed")
            return OmniParserResult()

    def detect_elements(self, image: Image.Image) -> list[UIElement]:
        """Detect UI elements and return them as UIElement objects.

        Returns an empty list when the model is unavailable.
        """
        result = self.parse(image)
        return self.convert_to_ui_elements(result)

    def convert_to_ui_elements(self, result: OmniParserResult) -> list[UIElement]:
        """Convert an OmniParserResult into the shared UIElement format."""
        ui_elements: list[UIElement] = []
        for elem in result.elements:
            ui_elem = UIElement(
                type=elem.element_type or "unknown",
                bbox=elem.bbox,
                label=elem.label,
                confidence=elem.confidence,
                sources=["omniparser"],
            )
            ui_elements.append(ui_elem)
        return ui_elements

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _try_load(self) -> None:
        """Attempt to load the OmniParser model weights."""
        try:
            import importlib.util
            spec = importlib.util.find_spec("omniparser")
            if spec is None:
                logger.debug("OmniParser package not installed; skipping model load.")
                return

            import omniparser  # type: ignore[import]
            self._model = omniparser.load(
                self._config.model_path,
                device=self._config.device,
            )
            self._loaded = True
            logger.info("OmniParser V2 loaded from: %s", self._config.model_path)
        except Exception:
            logger.debug("OmniParser model load failed; degrading to unavailable.")

    def _run_inference(self, image: Image.Image) -> OmniParserResult:
        """Run the loaded model. Only called when is_available() is True."""
        import time
        t0 = time.perf_counter()

        raw = self._model.predict(  # type: ignore[union-attr]
            image,
            confidence=self._config.confidence_threshold,
            max_elements=self._config.max_elements,
        )

        latency_ms = (time.perf_counter() - t0) * 1000
        elements: list[OmniParserElement] = []
        for det in raw.get("detections", []):
            elements.append(OmniParserElement(
                label=det.get("label", ""),
                bbox=tuple(det.get("bbox", (0, 0, 0, 0))),  # type: ignore[arg-type]
                element_type=det.get("type", "unknown"),
                confidence=float(det.get("confidence", 0.0)),
                ocr_text=det.get("ocr_text", ""),
                icon_class=det.get("icon_class", ""),
                is_interactive=bool(det.get("interactive", False)),
            ))

        return OmniParserResult(
            elements=elements,
            latency_ms=latency_ms,
            model_version=getattr(self._model, "version", "v2"),
            screenshot_size=image.size,
        )
