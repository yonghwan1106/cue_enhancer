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


# ─── Planning Types ───────────────────────────────────────


@dataclass
class SubTask:
    """A decomposed sub-task from the planning enhancer."""

    description: str
    action_type: str = ""  # click, type, scroll, key, navigate, etc.
    target: str = ""
    target_region: str = ""
    method: str = "mouse"  # mouse | keyboard | batch | direct
    shortcut: str | None = None
    original_method: str | None = None
    is_compound: bool = False
    is_navigation: bool = False
    is_verification_only: bool = False
    sub_steps: list[SubTask] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    batch_items: list[SubTask] = field(default_factory=list)
    action_description: str = ""

    def with_method(self, method: str, shortcut: str = "",
                    original_method: str = "") -> SubTask:
        """Return a copy with updated method."""
        return SubTask(
            description=self.description,
            action_type=self.action_type,
            target=self.target,
            target_region=self.target_region,
            method=method,
            shortcut=shortcut or self.shortcut,
            original_method=original_method or self.original_method,
            is_compound=self.is_compound,
            sub_steps=list(self.sub_steps),
            steps=list(self.steps),
            action_description=self.action_description,
        )


@dataclass
class StepRecord:
    """Record of a single step in an episode."""

    num: int = 0
    action: Action = field(default_factory=lambda: Action(type=""))
    success: bool = False
    verification: VerificationResult | None = None
    strategy_used: str = ""
    was_recovery: bool = False
    original_action: str = ""
    is_milestone: bool = False
    context_description: str = ""
    timestamp: float = 0.0

    def to_detailed_text(self) -> str:
        status = "success" if self.success else "failure"
        parts = [f"Step {self.num}: {self.action.type} -> {status}"]
        if self.verification and self.verification.reason:
            parts.append(f"  Reason: {self.verification.reason}")
        return "\n".join(parts)

    def is_retry_of(self, other: StepRecord) -> bool:
        return (self.action.type == other.action.type and
                self.context_description == other.context_description)


# ─── Memory Types ─────────────────────────────────────────


@dataclass
class Lesson:
    """Generalized lesson — basic unit of Semantic Memory."""

    id: str = ""
    app: str = ""
    situation: str = ""
    failed_approach: str = ""
    successful_approach: str = ""
    confidence: float = 0.7
    success_count: int = 0
    failure_count: int = 0
    created_at: float = field(default_factory=lambda: __import__("time").time())
    last_used: float = field(default_factory=lambda: __import__("time").time())
    task_context: str = ""
    text: str = ""
    reinforcement_count: int = 0


@dataclass
class EpisodeRecord:
    """Episode record — basic unit of Episodic Memory."""

    id: str = ""
    task: str = ""
    app: str = ""
    success: bool = False
    total_steps: int = 0
    steps_summary: str = ""
    failure_patterns: list[str] = field(default_factory=list)
    recovery_strategies: list[str] = field(default_factory=list)
    reflection: str = ""
    created_at: float = field(default_factory=lambda: __import__("time").time())
    embedding: list[float] | None = None


@dataclass
class MemoryContext:
    """Memory context to inject into the current task."""

    lessons: list[Lesson] = field(default_factory=list)
    similar_episodes: list[EpisodeRecord] = field(default_factory=list)
    total_tokens: int = 0

    def to_prompt_text(self) -> str:
        parts = []
        if self.lessons:
            parts.append("## Past Lessons")
            for lesson in self.lessons[:5]:
                parts.append(
                    f"- [{lesson.app}] {lesson.situation}: "
                    f"Use '{lesson.successful_approach}' instead of "
                    f"'{lesson.failed_approach}' "
                    f"(confidence {lesson.confidence:.0%})"
                )
        if self.similar_episodes:
            parts.append("\n## Similar Past Episodes")
            for ep in self.similar_episodes[:3]:
                status = "SUCCESS" if ep.success else "FAILURE"
                parts.append(
                    f"- [{status}] {ep.task} ({ep.total_steps} steps): "
                    f"{ep.reflection[:100]}"
                )
        return "\n".join(parts)


@dataclass
class CompressedHistory:
    """ACON-compressed history for token optimization."""

    recent_full: list[StepRecord] = field(default_factory=list)
    mid_summary: list[str] = field(default_factory=list)
    old_summary: str | None = None
    token_count: int = 0

    def to_prompt_text(self) -> str:
        parts = []
        if self.old_summary:
            parts.append(f"[Previous Summary] {self.old_summary}")
        if self.mid_summary:
            parts.append("[Mid Steps]")
            for s in self.mid_summary:
                parts.append(f"  - {s}")
        parts.append("[Recent Steps]")
        for step in self.recent_full:
            parts.append(step.to_detailed_text())
        return "\n".join(parts)


# ─── Reflection Types ─────────────────────────────────────


class ReflectionDecision(Enum):
    CONTINUE = "continue"
    RETRY = "retry"
    REPLAN = "replan"
    STRATEGY_CHANGE = "strategy"


@dataclass
class ActionReflection:
    success: bool = False
    decision: ReflectionDecision = ReflectionDecision.CONTINUE
    retry_action: Action | None = None
    reason: str = ""


@dataclass
class TrajectoryReflection:
    making_progress: bool = True
    decision: ReflectionDecision = ReflectionDecision.CONTINUE
    new_plan: list[SubTask] | None = None
    reason: str = ""


@dataclass
class GlobalReflection:
    on_track: bool = True
    decision: ReflectionDecision = ReflectionDecision.CONTINUE
    revised_strategy: str | None = None
    reason: str = ""


# ─── Checkpoint Types ─────────────────────────────────────


@dataclass
class Checkpoint:
    """State snapshot after a successful step."""

    step_num: int = 0
    screenshot_hash: str = ""
    a11y_tree_hash: str = ""
    action_history: list[Action] = field(default_factory=list)
    current_subtask_index: int = 0
    timestamp: float = 0.0


@dataclass
class RecoveryResult:
    success: bool = False
    recovered_to_step: int = -1
    method: str = "failed"  # ctrl_z | re_navigate | failed
    steps_lost: int = 0


# ─── Efficiency Types ─────────────────────────────────────


@dataclass
class OptimizationResult:
    """Result of step optimization."""

    original_steps: int = 0
    optimized_steps: int = 0
    reduction_pct: float = 0.0
    methods_applied: list[str] = field(default_factory=list)


@dataclass
class Episode:
    """Complete episode data for memory storage."""

    id: str = ""
    task: str = ""
    app: str = ""
    success: bool = False
    steps: list[StepRecord] = field(default_factory=list)
    subtasks: list[SubTask] = field(default_factory=list)
    completed_subtasks: int = 0
    start_time: float = 0.0
    end_time: float = 0.0


# ─── Benchmark Types (Phase 3) ─────────────────────────────


class PermissionLevel(Enum):
    """4-level permission system for Safety Gate v2."""

    OBSERVE = 0      # Agent suggests, human executes
    CONFIRM = 1      # All actions need approval
    AUTO_SAFE = 2    # Safe actions auto-execute (default)
    FULL_AUTO = 3    # All except BLOCKED auto-execute (sandbox only)


class FailureCategory(str, Enum):
    """Classification of task failure types."""

    GROUNDING = "grounding"
    PLANNING = "planning"
    EXECUTION = "execution"
    NAVIGATION = "navigation"
    VERIFICATION = "verification"
    TIMEOUT = "timeout"
    SAFETY_BLOCK = "safety_block"
    UNKNOWN = "unknown"


@dataclass
class SuccessCriterion:
    """Automated success check for a benchmark task."""

    type: str = ""  # cell_value_check, url_check, file_content_check, tab_count, etc.
    checks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BenchmarkTask:
    """Definition of a single benchmark task."""

    id: str = ""
    app: str = ""
    difficulty: str = "medium"  # easy | medium | hard
    failure_type: str = ""  # primary failure type this task tests
    instruction: str = ""
    initial_state: str = ""  # VM snapshot or setup script
    success_criteria: SuccessCriterion = field(default_factory=SuccessCriterion)
    human_baseline_steps: int = 0
    timeout_seconds: int = 120
    tags: list[str] = field(default_factory=list)


@dataclass
class TaskMetrics:
    """Metrics collected for a single task execution."""

    task_id: str = ""
    success: bool = False
    steps_taken: int = 0
    total_time: float = 0.0
    tokens_used: int = 0
    api_calls: int = 0
    failure_category: FailureCategory = FailureCategory.UNKNOWN
    failure_reason: str = ""
    step_efficiency_ratio: float = 0.0  # agent_steps / human_baseline_steps
    grounding_accuracy: float = 0.0
    first_attempt_success_rate: float = 0.0
    error_recovery_rate: float = 0.0


@dataclass
class BenchmarkResult:
    """Aggregated result of a benchmark suite run."""

    suite_name: str = ""
    config_name: str = "full_cue"
    total_tasks: int = 0
    successful_tasks: int = 0
    success_rate: float = 0.0
    avg_steps: float = 0.0
    avg_time: float = 0.0
    avg_tokens: int = 0
    avg_api_calls: float = 0.0
    task_metrics: list[TaskMetrics] = field(default_factory=list)
    by_difficulty: dict[str, float] = field(default_factory=dict)
    by_app: dict[str, float] = field(default_factory=dict)
    by_failure_type: dict[str, int] = field(default_factory=dict)
    run_timestamp: float = 0.0


@dataclass
class AblationResult:
    """Result of an ablation study configuration run."""

    config_name: str = ""
    modules_enabled: dict[str, bool] = field(default_factory=dict)
    success_rate: float = 0.0
    avg_steps: float = 0.0
    avg_tokens: int = 0
    avg_time: float = 0.0
    runs: list[BenchmarkResult] = field(default_factory=list)


@dataclass
class FailureRecord:
    """Detailed record of a single task failure for analysis."""

    task_id: str = ""
    category: FailureCategory = FailureCategory.UNKNOWN
    step_num: int = 0
    action_attempted: str = ""
    expected_outcome: str = ""
    actual_outcome: str = ""
    screen_description: str = ""
    recovery_attempted: bool = False
    recovery_success: bool = False
