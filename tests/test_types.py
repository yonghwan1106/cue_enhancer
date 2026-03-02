"""Tests for CUE shared types."""

from cue.types import (
    AccessibilityNode,
    AccessibilityTree,
    Action,
    ElementMap,
    SafetyDecision,
    SafetyLevel,
    UIElement,
    ValidationStatus,
    VerificationResult,
)


class TestUIElement:
    def test_center(self):
        elem = UIElement(type="button", bbox=(100, 200, 200, 240))
        assert elem.center == (150, 220)

    def test_dimensions(self):
        elem = UIElement(type="panel", bbox=(10, 20, 110, 120))
        assert elem.width == 100
        assert elem.height == 100
        assert elem.area == 10000

    def test_sources(self):
        elem = UIElement(
            type="button",
            bbox=(0, 0, 50, 30),
            label="OK",
            confidence=0.9,
            sources=["visual", "text", "structural"],
        )
        assert len(elem.sources) == 3
        assert "visual" in elem.sources

    def test_default_values(self):
        elem = UIElement(type="unknown", bbox=(0, 0, 0, 0))
        assert elem.label == ""
        assert elem.confidence == 0.0
        assert elem.sources == []


class TestAction:
    def test_with_coordinate(self):
        action = Action(type="left_click", coordinate=(100, 200))
        refined = action.with_coordinate(105, 195)
        assert refined.coordinate == (105, 195)
        assert refined.type == "left_click"
        # Original unchanged
        assert action.coordinate == (100, 200)

    def test_with_metadata(self):
        action = Action(type="scroll", metadata={"original": True})
        updated = action.with_metadata({"suggest_zoom": True})
        assert updated.metadata["original"] is True
        assert updated.metadata["suggest_zoom"] is True
        # Original unchanged
        assert "suggest_zoom" not in action.metadata

    def test_key_action(self):
        action = Action(type="key", text="ctrl+s")
        assert action.type == "key"
        assert action.text == "ctrl+s"
        assert action.coordinate is None

    def test_type_action(self):
        action = Action(type="type", text="Hello world")
        assert action.type == "type"
        assert action.text == "Hello world"


class TestElementMap:
    def _make_elements(self) -> list[UIElement]:
        return [
            UIElement(type="button", bbox=(100, 100, 150, 130), label="Save"),
            UIElement(type="button", bbox=(200, 100, 260, 130), label="Cancel"),
            UIElement(type="input", bbox=(100, 200, 400, 230), label="Search"),
            UIElement(type="icon", bbox=(50, 50, 70, 70), label="Logo"),
        ]

    def test_find_nearest(self):
        emap = ElementMap(elements=self._make_elements())
        result = emap.find_nearest(125, 115, radius=20)
        assert result is not None
        assert result.label == "Save"

    def test_find_nearest_none(self):
        emap = ElementMap(elements=self._make_elements())
        result = emap.find_nearest(500, 500, radius=20)
        assert result is None

    def test_find_nearest_radius(self):
        emap = ElementMap(elements=self._make_elements())
        # Just outside radius
        result = emap.find_nearest(180, 115, radius=5)
        assert result is None
        # With larger radius
        result = emap.find_nearest(180, 115, radius=60)
        assert result is not None

    def test_get_topmost_at(self):
        emap = ElementMap(elements=self._make_elements())
        result = emap.get_topmost_at(125, 115)
        assert result is not None
        assert result.label == "Save"

    def test_get_topmost_at_miss(self):
        emap = ElementMap(elements=self._make_elements())
        result = emap.get_topmost_at(500, 500)
        assert result is None

    def test_find_by_label(self):
        emap = ElementMap(elements=self._make_elements())
        results = emap.find_by_label("save")
        assert len(results) == 1
        assert results[0].label == "Save"

    def test_find_by_label_case_insensitive(self):
        emap = ElementMap(elements=self._make_elements())
        results = emap.find_by_label("CANCEL")
        assert len(results) == 1

    def test_find_by_label_no_match(self):
        emap = ElementMap(elements=self._make_elements())
        results = emap.find_by_label("nonexistent")
        assert len(results) == 0


class TestAccessibilityTree:
    def test_flatten(self):
        child1 = AccessibilityNode(id="c1", role="button", name="OK")
        child2 = AccessibilityNode(id="c2", role="text", name="Hello")
        root = AccessibilityNode(id="root", role="window", name="Main", children=[child1, child2])
        tree = AccessibilityTree(root=root)
        flat = tree.flatten()
        assert len(flat) == 3

    def test_flatten_empty(self):
        tree = AccessibilityTree(root=None)
        assert tree.flatten() == []

    def test_get_all_text(self):
        child = AccessibilityNode(id="c1", name="Hello World")
        root = AccessibilityNode(id="root", name="Window", children=[child])
        tree = AccessibilityTree(root=root)
        text = tree.get_all_text()
        assert "Hello World" in text
        assert "Window" in text

    def test_find_blocking_overlays(self):
        modal = AccessibilityNode(id="m1", role="dialog", name="Confirm")
        button = AccessibilityNode(id="b1", role="button", name="OK")
        root = AccessibilityNode(id="root", role="window", children=[modal, button])
        tree = AccessibilityTree(root=root)
        overlays = tree.find_blocking_overlays()
        assert len(overlays) == 1
        assert overlays[0].role == "dialog"


class TestVerificationResult:
    def test_defaults(self):
        v = VerificationResult()
        assert v.tier == 1
        assert v.success is False
        assert v.confidence == 0.0
        assert v.needs_escalation is False

    def test_success(self):
        v = VerificationResult(tier=1, success=True, confidence=0.9, reason="All signals match")
        assert v.success is True
        assert v.confidence == 0.9


class TestValidationStatus:
    def test_enum_values(self):
        assert ValidationStatus.SAFE.value == "safe"
        assert ValidationStatus.NEEDS_FIX.value == "needs_fix"
        assert ValidationStatus.BLOCKED.value == "blocked"


class TestSafetyLevel:
    def test_enum_values(self):
        assert SafetyLevel.SAFE.value == "safe"
        assert SafetyLevel.NEEDS_CONFIRMATION.value == "needs_confirmation"
        assert SafetyLevel.BLOCKED.value == "blocked"
