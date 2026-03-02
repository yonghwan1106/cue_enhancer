"""Tests for CUE grounding module — merger logic and enhancer."""

from cue.types import (
    StructuralElement,
    TextElement,
    UIElement,
    VisualElement,
)


class TestSourceMerger:
    """Test the SourceMerger IOU-based merge logic."""

    def _get_merger(self):
        from cue.grounding.merger import SourceMerger

        return SourceMerger()

    def test_empty_inputs(self):
        merger = self._get_merger()
        result = merger.merge([], [], [])
        assert result == []

    def test_visual_only(self):
        merger = self._get_merger()
        visual = [VisualElement(type="button", bbox=(100, 100, 200, 130), confidence=0.5)]
        result = merger.merge(visual, [], [])
        assert len(result) == 1
        assert result[0].confidence == 0.4  # visual-only base
        assert "visual" in result[0].sources

    def test_text_only(self):
        merger = self._get_merger()
        text = [TextElement(text="Save", bbox=(100, 100, 150, 120), confidence=0.8)]
        result = merger.merge([], text, [])
        assert len(result) == 1
        assert result[0].label == "Save"
        assert "text" in result[0].sources

    def test_structural_only(self):
        merger = self._get_merger()
        structural = [
            StructuralElement(
                role="push button", name="OK", bbox=(100, 100, 160, 130),
                states=["enabled"], actionable=True,
            )
        ]
        result = merger.merge([], [], structural)
        assert len(result) == 1
        assert result[0].type == "push button"
        assert result[0].confidence == 0.35

    def test_visual_text_overlap(self):
        merger = self._get_merger()
        visual = [VisualElement(type="button", bbox=(100, 100, 200, 130), confidence=0.5)]
        text = [TextElement(text="Save", bbox=(105, 102, 195, 128), confidence=0.9)]
        result = merger.merge(visual, text, [])
        assert len(result) == 1
        assert result[0].label == "Save"
        assert "visual" in result[0].sources
        assert "text" in result[0].sources
        assert result[0].confidence >= 0.6  # visual (0.4) + text (0.25)

    def test_all_three_overlap(self):
        merger = self._get_merger()
        visual = [VisualElement(type="button", bbox=(100, 100, 200, 130), confidence=0.6)]
        text = [TextElement(text="Apply", bbox=(102, 101, 198, 129), confidence=0.9)]
        structural = [
            StructuralElement(
                role="push button", name="Apply", bbox=(100, 100, 200, 130),
                states=["enabled"], actionable=True,
            )
        ]
        result = merger.merge(visual, text, structural)
        assert len(result) == 1
        assert len(result[0].sources) == 3
        assert result[0].confidence == 1.0  # capped at 1.0

    def test_no_overlap_separate_elements(self):
        merger = self._get_merger()
        visual = [VisualElement(type="button", bbox=(100, 100, 200, 130), confidence=0.5)]
        text = [TextElement(text="Search", bbox=(400, 300, 500, 320), confidence=0.8)]
        result = merger.merge(visual, text, [])
        assert len(result) == 2

    def test_sorted_by_confidence(self):
        merger = self._get_merger()
        visual = [
            VisualElement(type="button", bbox=(100, 100, 200, 130), confidence=0.3),
            VisualElement(type="icon", bbox=(300, 300, 330, 330), confidence=0.7),
        ]
        structural = [
            StructuralElement(
                role="push button", name="OK", bbox=(100, 100, 200, 130),
                states=[], actionable=True,
            )
        ]
        result = merger.merge(visual, [], structural)
        # The one with structural match should have higher confidence
        assert result[0].confidence >= result[-1].confidence


class TestIoUCalculation:
    def _get_merger(self):
        from cue.grounding.merger import SourceMerger

        return SourceMerger()

    def test_identical_boxes(self):
        merger = self._get_merger()
        iou = merger._calc_iou((0, 0, 100, 100), (0, 0, 100, 100))
        assert abs(iou - 1.0) < 0.01

    def test_no_overlap(self):
        merger = self._get_merger()
        iou = merger._calc_iou((0, 0, 50, 50), (100, 100, 200, 200))
        assert iou == 0.0

    def test_partial_overlap(self):
        merger = self._get_merger()
        iou = merger._calc_iou((0, 0, 100, 100), (50, 50, 150, 150))
        # intersection = 50*50 = 2500, union = 10000 + 10000 - 2500 = 17500
        expected = 2500 / 17500
        assert abs(iou - expected) < 0.01

    def test_contained(self):
        merger = self._get_merger()
        iou = merger._calc_iou((0, 0, 100, 100), (25, 25, 75, 75))
        # intersection = 50*50 = 2500, union = 10000 + 2500 - 2500 = 10000
        expected = 2500 / 10000
        assert abs(iou - expected) < 0.01
