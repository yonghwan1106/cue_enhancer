"""Shared data types for CUE modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
from PIL import Image


# ─── Environment State ─────────────────────────────────────


@dataclass
class ScreenState:
    """Current screen state captured from the environment."""

    screenshot: Image.Image
    a11y_tree: AccessibilityTree | None = None
    timestamp: float = 0.0
    app_name: str = ""
    window_title: str = ""


@dataclass
class AccessibilityNode:
    """Single node in the accessibility tree."""

    id: str = ""
    role: str = ""
    name: str = ""
    bbox: tuple[int, int, int, int] = (0, 0, 0, 0)  # (x1, y1, x2, y2)
    states: list[str] = field(default_factory=list)
    children: list[AccessibilityNode] = field(default_factory=list)
    depth: int = 0


@dataclass
class AccessibilityTree:
    """Parsed accessibility tree from the OS."""

    root: AccessibilityNode | None = None
    app_name: str = ""

    def flatten(self) -> list[AccessibilityNode]:
        """Return all nodes as a flat list."""
        if not self.root:
            return []
        result: list[AccessibilityNode] = []
        self._flatten_recursive(self.root, result)
        return result

    def _flatten_recursive(
        self, node: AccessibilityNode, result: list[AccessibilityNode]
    ) -> None:
        result.append(node)
        for child in node.children:
            self._flatten_recursive(child, result)

    def get_all_text(self) -> str:
        """Get all text content from the tree."""
        return " ".join(n.name for n in self.flatten() if n.name)

    def find_blocking_overlays(self) -> list[AccessibilityNode]:
        """Find overlay/modal nodes that may block interaction."""
        return [
            n
            for n in self.flatten()
            if n.role in ("dialog", "modal", "overlay", "popup", "alert")
        ]


# ─── Grounding Enhancer Types ──────────────────────────────


@dataclass
class UIElement:
    """Identified UI element from grounding."""

    type: str  # button, input, menu, checkbox, icon, text_field, panel, unknown
    bbox: tuple[int, int, int, int]  # (x1, y1, x2, y2)
    label: str = ""
    confidence: float = 0.0
    sources: list[str] = field(default_factory=list)  # ["visual", "text", "structural"]

    @property
    def center(self) -> tuple[int, int]:
        return (
            (self.bbox[0] + self.bbox[2]) // 2,
            (self.bbox[1] + self.bbox[3]) // 2,
        )

    @property
    def width(self) -> int:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> int:
        return self.bbox[3] - self.bbox[1]

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass
class VisualElement:
    """Element detected by the visual expert (OpenCV)."""

    type: str
    bbox: tuple[int, int, int, int]
    confidence: float = 0.0


@dataclass
class TextElement:
    """Element detected by the text expert (OCR)."""

    text: str
    bbox: tuple[int, int, int, int]
    confidence: float = 0.0


@dataclass
class StructuralElement:
    """Element from the accessibility tree (structural expert)."""

    role: str
    name: str
    bbox: tuple[int, int, int, int]
    states: list[str] = field(default_factory=list)
    depth: int = 0
    actionable: bool = False


@dataclass
class GroundingStats:
    """Statistics from a grounding pass."""

    visual_count: int = 0
    text_count: int = 0
    structural_count: int = 0
    merged_count: int = 0
    avg_confidence: float = 0.0
    duration_ms: float = 0.0


@dataclass
class GroundingResult:
    """Complete output from the GroundingEnhancer."""

    elements: list[UIElement] = field(default_factory=list)
    element_description: str = ""
    zoom_recommendations: list[UIElement] = field(default_factory=list)
    stats: GroundingStats = field(default_factory=GroundingStats)


@dataclass
class EnhancedContext:
    """Augmented context produced by grounding, passed to Claude."""

    screen_state: ScreenState | None = None
    elements: list[UIElement] = field(default_factory=list)
    element_description: str = ""
    app_knowledge: dict[str, Any] | None = None


# ─── Execution Enhancer Types ──────────────────────────────


@dataclass
class Action:
    """An action to be executed on the environment."""

    type: str  # left_click, double_click, right_click, key, type, scroll, etc.
    coordinate: tuple[int, int] | None = None
    text: str | None = None
    key: str | None = None
    delta_x: int = 0
    delta_y: int = 0
    duration_ms: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_coordinate(self, x: int, y: int) -> Action:
        """Return a copy with updated coordinates."""
        return Action(
            type=self.type,
            coordinate=(x, y),
            text=self.text,
            key=self.key,
            delta_x=self.delta_x,
            delta_y=self.delta_y,
            duration_ms=self.duration_ms,
            metadata=dict(self.metadata),
        )

    def with_metadata(self, extra: dict[str, Any]) -> Action:
        """Return a copy with merged metadata."""
        merged = {**self.metadata, **extra}
        return Action(
            type=self.type,
            coordinate=self.coordinate,
            text=self.text,
            key=self.key,
            delta_x=self.delta_x,
            delta_y=self.delta_y,
            duration_ms=self.duration_ms,
            metadata=merged,
        )


class ValidationStatus(Enum):
    SAFE = "safe"
    NEEDS_FIX = "needs_fix"
    BLOCKED = "blocked"


@dataclass
class ValidationCheck:
    """Single validation check result."""

    name: str
    passed: bool
    reason: str | None = None
    fix_action: Action | None = None


@dataclass
class ValidationResult:
    """Pre-action validation result."""

    status: ValidationStatus
    checks: list[ValidationCheck] = field(default_factory=list)
    fix_actions: list[Action] = field(default_factory=list)

    @property
    def can_proceed(self) -> bool:
        return self.status in (ValidationStatus.SAFE, ValidationStatus.NEEDS_FIX)


@dataclass
class ActionResult:
    """Result of executing an action."""

    success: bool
    action_type: str = ""
    before_screenshot: np.ndarray | None = None
    after_screenshot: np.ndarray | None = None
    error: str | None = None
    fallback_used: str | None = None
    steps_taken: list[str] = field(default_factory=list)


@dataclass
class StabilityResult:
    """Result from timing controller's UI stability check."""

    is_stable: bool
    wait_duration_ms: float = 0.0
    final_diff: float = 0.0
    frames_checked: int = 0


# ─── Verification Types ────────────────────────────────────


@dataclass
class VerificationResult:
    """Result from the verification loop."""

    tier: int = 1
    success: bool = False
    confidence: float = 0.0
    reason: str = ""
    needs_escalation: bool = False
    details: dict[str, Any] | None = None
    diagnosis: str | None = None


@dataclass
class ExpectedOutcome:
    """What we expect to see after an action."""

    description: str = ""
    text_markers: list[str] = field(default_factory=list)
    screen_region: tuple[int, int, int, int] | None = None


@dataclass
class TreeDiff:
    """Diff between two accessibility trees."""

    added: list[AccessibilityNode] = field(default_factory=list)
    removed: list[AccessibilityNode] = field(default_factory=list)
    state_changed: list[tuple[AccessibilityNode, AccessibilityNode]] = field(
        default_factory=list
    )


# ─── Safety Types ──────────────────────────────────────────


class SafetyLevel(Enum):
    SAFE = "safe"
    NEEDS_CONFIRMATION = "needs_confirmation"
    BLOCKED = "blocked"


@dataclass
class SafetyDecision:
    """Safety gate decision for an action."""

    level: SafetyLevel
    reason: str = ""
    pattern_matched: str | None = None


# ─── Task / Agent Types ────────────────────────────────────


@dataclass
class TaskResult:
    """Final result of a complete task execution."""

    success: bool
    task: str = ""
    steps_taken: int = 0
    total_time_seconds: float = 0.0
    error: str | None = None
    verification: VerificationResult | None = None


@dataclass
class ElementMap:
    """Spatial index of UI elements for fast lookup."""

    elements: list[UIElement] = field(default_factory=list)

    def find_nearest(
        self, x: int, y: int, radius: int = 20
    ) -> UIElement | None:
        """Find the nearest UI element within radius."""
        best: UIElement | None = None
        best_dist = float("inf")
        for elem in self.elements:
            cx, cy = elem.center
            dist = ((cx - x) ** 2 + (cy - y) ** 2) ** 0.5
            if dist < radius and dist < best_dist:
                best = elem
                best_dist = dist
        return best

    def get_topmost_at(self, x: int, y: int) -> UIElement | None:
        """Get the topmost element at coordinates (last in list = topmost)."""
        for elem in reversed(self.elements):
            x1, y1, x2, y2 = elem.bbox
            if x1 <= x <= x2 and y1 <= y <= y2:
                return elem
        return None

    def find_by_label(self, label: str) -> list[UIElement]:
        """Find elements matching a label (case-insensitive)."""
        label_lower = label.lower()
        return [e for e in self.elements if label_lower in e.label.lower()]
