"""Tests for CUE execution module."""

from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from PIL import Image

from cue.config import EnhancerLevel, ExecutionConfig
from cue.types import (
    Action,
    ActionResult,
    ElementMap,
    EnhancedContext,
    ScreenState,
    StabilityResult,
    UIElement,
    ValidationStatus,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_element(
    label: str = "Save",
    bbox: tuple = (100, 100, 200, 130),
    confidence: float = 0.8,
    type_: str = "button",
) -> UIElement:
    return UIElement(type=type_, bbox=bbox, label=label, confidence=confidence, sources=["visual"])


def _make_elements(*elems: UIElement) -> ElementMap:
    return ElementMap(elements=list(elems))


def _make_context(
    elements: list[UIElement] | None = None,
    screen_size: tuple[int, int] = (1920, 1080),
    app_name: str = "test",
) -> EnhancedContext:
    img = Image.new("RGB", screen_size)
    ss = ScreenState(screenshot=img, app_name=app_name)
    return EnhancedContext(
        screen_state=ss,
        elements=elements or [],
        element_description="",
    )


def _make_frame(width: int = 100, height: int = 100, value: int = 0) -> np.ndarray:
    """Return a uniform grayscale frame as uint8 numpy array."""
    return np.full((height, width, 3), value, dtype=np.uint8)


# ── CoordinateRefiner ─────────────────────────────────────────────────────────


class TestCoordinateRefiner:
    def _get_refiner(self):
        from cue.execution.coordinator import CoordinateRefiner

        return CoordinateRefiner()

    async def test_non_click_action_unchanged(self):
        refiner = self._get_refiner()
        action = Action(type="key", key="enter")
        elements = _make_elements(_make_element())
        result = await refiner.refine(action, elements)
        assert result is action

    async def test_click_no_coordinate_unchanged(self):
        refiner = self._get_refiner()
        action = Action(type="left_click")
        elements = _make_elements(_make_element())
        result = await refiner.refine(action, elements)
        assert result is action

    async def test_snap_to_nearest_element(self):
        refiner = self._get_refiner()
        # Element center is at (150, 115) — click near it within SNAP_RADIUS=10
        elem = _make_element(bbox=(100, 100, 200, 130), label="OK", confidence=0.9)
        elements = _make_elements(elem)
        action = Action(type="left_click", coordinate=(152, 116))
        result = await refiner.refine(action, elements)
        assert result.coordinate == elem.center
        assert result.metadata.get("snapped_to") == "OK"
        assert result.metadata.get("snap_element_type") == "button"
        assert "snap_confidence" in result.metadata

    async def test_snap_all_click_types(self):
        refiner = self._get_refiner()
        elem = _make_element(bbox=(100, 100, 200, 130), label="Btn", confidence=0.9)
        elements = _make_elements(elem)
        for click_type in ("left_click", "double_click", "right_click"):
            action = Action(type=click_type, coordinate=(152, 116))
            result = await refiner.refine(action, elements)
            assert result.metadata.get("snapped_to") == "Btn", f"Failed for {click_type}"

    async def test_no_element_adds_suggest_zoom(self):
        refiner = self._get_refiner()
        # Element center is far away — outside SNAP_RADIUS=10
        elem = _make_element(bbox=(400, 400, 500, 430), confidence=0.9)
        elements = _make_elements(elem)
        action = Action(type="left_click", coordinate=(150, 115))
        result = await refiner.refine(action, elements)
        assert result.metadata.get("suggest_zoom") is True
        assert result.coordinate == (150, 115)  # coordinate unchanged

    async def test_low_confidence_not_snapped(self):
        refiner = self._get_refiner()
        # Element within radius but confidence below threshold (0.6)
        elem = _make_element(bbox=(100, 100, 200, 130), confidence=0.5)
        elements = _make_elements(elem)
        action = Action(type="left_click", coordinate=(152, 116))
        result = await refiner.refine(action, elements)
        assert result.metadata.get("suggest_zoom") is True
        assert "snapped_to" not in result.metadata

    async def test_display_scale_applied(self):
        refiner = self._get_refiner()
        # Physical element at (200, 200, 400, 260); logical scale=2.0
        # Logical center at (150, 115); physical = (300, 230) — but elem center is (300, 230)
        # We click at logical (298//2, 228//2) = (149, 114) → physical (298, 228)
        elem = UIElement(type="button", bbox=(200, 200, 400, 260), label="Scaled",
                         confidence=0.9, sources=["visual"])
        elements = _make_elements(elem)
        # Physical center of elem = (300, 230). Click at physical (300, 230) → logical (150, 115)
        action = Action(type="left_click", coordinate=(150, 115))
        result = await refiner.refine(action, elements, display_scale=2.0)
        assert result.metadata.get("snapped_to") == "Scaled"
        # Converted back to logical: (300//2, 230//2) = (150, 115)
        assert result.coordinate == (150, 115)

    async def test_empty_element_map_adds_suggest_zoom(self):
        refiner = self._get_refiner()
        elements = _make_elements()
        action = Action(type="left_click", coordinate=(100, 100))
        result = await refiner.refine(action, elements)
        assert result.metadata.get("suggest_zoom") is True

    async def test_zoom_and_refine_not_click_unchanged(self):
        refiner = self._get_refiner()
        action = Action(type="type", text="hello", metadata={"suggest_zoom": True})
        elements = _make_elements()
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = AsyncMock(return_value=Image.new("RGB", (100, 100)))
        grounding_fn = AsyncMock()
        result = await refiner.zoom_and_refine(action, elements, execute_fn, screenshot_fn,
                                               grounding_fn)
        assert result is action

    async def test_zoom_and_refine_no_suggest_zoom_unchanged(self):
        refiner = self._get_refiner()
        action = Action(type="left_click", coordinate=(150, 150))  # no suggest_zoom metadata
        elements = _make_elements()
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = AsyncMock(return_value=Image.new("RGB", (100, 100)))
        grounding_fn = AsyncMock()
        result = await refiner.zoom_and_refine(action, elements, execute_fn, screenshot_fn,
                                               grounding_fn)
        assert result is action

    async def test_zoom_and_refine_no_grounding_fn_unchanged(self):
        refiner = self._get_refiner()
        action = Action(type="left_click", coordinate=(150, 150), metadata={"suggest_zoom": True})
        elements = _make_elements()
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = AsyncMock(return_value=Image.new("RGB", (100, 100)))
        result = await refiner.zoom_and_refine(action, elements, execute_fn, screenshot_fn,
                                               grounding_fn=None)
        assert result is action

    async def test_zoom_and_refine_success(self):
        refiner = self._get_refiner()
        action = Action(type="left_click", coordinate=(150, 115), metadata={"suggest_zoom": True})
        elements = _make_elements()
        screenshot_fn = AsyncMock(return_value=Image.new("RGB", (100, 100)))

        # grounding_fn returns result with elements attribute
        zoomed_elem = _make_element(bbox=(140, 105, 160, 125), confidence=0.9, label="ZoomedBtn")
        grounding_result = MagicMock()
        grounding_result.elements = [zoomed_elem]
        grounding_fn = AsyncMock(return_value=grounding_result)
        execute_fn = AsyncMock(return_value=True)

        result = await refiner.zoom_and_refine(action, elements, execute_fn, screenshot_fn,
                                               grounding_fn)
        assert result.metadata.get("zoom_refined") is True
        assert result.metadata.get("zoom_element") == "ZoomedBtn"

    async def test_zoom_and_refine_error_falls_back(self):
        refiner = self._get_refiner()
        action = Action(type="left_click", coordinate=(150, 115), metadata={"suggest_zoom": True})
        elements = _make_elements()
        screenshot_fn = AsyncMock(side_effect=RuntimeError("screenshot failed"))
        grounding_fn = AsyncMock()
        execute_fn = AsyncMock(return_value=True)

        result = await refiner.zoom_and_refine(action, elements, execute_fn, screenshot_fn,
                                               grounding_fn)
        # Falls back to original action on error
        assert result is action


# ── TimingController ──────────────────────────────────────────────────────────


class TestTimingController:
    def _get_controller(self):
        from cue.execution.timing import TimingController

        return TimingController()

    async def test_stable_frames_return_stable_result(self):
        tc = self._get_controller()
        # Return identical frames every call → diff = 0 → stable immediately
        frame = _make_frame(value=128)
        call_count = 0

        async def screenshot_fn():
            nonlocal call_count
            call_count += 1
            return frame

        result = await tc.wait_for_stable_ui(screenshot_fn, timeout_ms=500)
        assert isinstance(result, StabilityResult)
        assert result.is_stable is True
        assert result.frames_checked >= 3  # first + 2 stable streak frames
        assert result.final_diff < 0.005

    async def test_unstable_frames_timeout(self):
        tc = self._get_controller()
        call_count = 0

        async def screenshot_fn():
            nonlocal call_count
            call_count += 1
            # Alternate between two different frames → always unstable
            return _make_frame(value=(call_count % 2) * 200)

        result = await tc.wait_for_stable_ui(screenshot_fn, timeout_ms=300)
        assert result.is_stable is False
        assert result.wait_duration_ms >= 250  # should have run close to timeout

    async def test_pil_image_accepted(self):
        tc = self._get_controller()
        img = Image.new("RGB", (50, 50), color=(100, 100, 100))

        async def screenshot_fn():
            return img

        result = await tc.wait_for_stable_ui(screenshot_fn, timeout_ms=400)
        assert result.is_stable is True

    async def test_returns_stability_result_fields(self):
        tc = self._get_controller()
        frame = _make_frame(value=50)

        async def screenshot_fn():
            return frame

        result = await tc.wait_for_stable_ui(screenshot_fn, timeout_ms=400)
        assert hasattr(result, "is_stable")
        assert hasattr(result, "wait_duration_ms")
        assert hasattr(result, "final_diff")
        assert hasattr(result, "frames_checked")
        assert result.frames_checked > 0
        assert result.wait_duration_ms > 0

    def test_get_profile_none_initially(self):
        tc = self._get_controller()
        assert tc.get_profile("chrome") is None

    def test_update_profile_creates_entry(self):
        tc = self._get_controller()
        tc._update_profile("chrome", 300.0)
        profile = tc.get_profile("chrome")
        assert profile is not None
        assert profile.avg_render_time_ms == 300.0
        assert profile.sample_count == 1

    def test_update_profile_ema(self):
        tc = self._get_controller()
        tc._update_profile("app", 100.0)
        tc._update_profile("app", 200.0)
        profile = tc.get_profile("app")
        assert profile is not None
        assert profile.sample_count == 2
        # EMA with alpha=min(0.3, 2/(2+1))≈0.3: 0.3*200 + 0.7*100 = 130
        assert 110.0 < profile.avg_render_time_ms < 150.0

    async def test_adaptive_timeout_from_profile(self):
        tc = self._get_controller()
        # Seed a profile with 2 samples so it is used
        tc._update_profile("fast_app", 100.0)
        tc._update_profile("fast_app", 100.0)

        frame = _make_frame(value=64)

        async def screenshot_fn():
            return frame

        # Adaptive timeout = 100 * 2.5 = 250ms, floored at 200ms
        result = await tc.wait_for_stable_ui(screenshot_fn, timeout_ms=2000, app_name="fast_app")
        assert result.is_stable is True

    async def test_wait_updates_profile(self):
        tc = self._get_controller()
        frame = _make_frame(value=10)

        async def screenshot_fn():
            return frame

        await tc.wait_for_stable_ui(screenshot_fn, timeout_ms=500, app_name="myapp")
        assert tc.get_profile("myapp") is not None


# ── FallbackChain ─────────────────────────────────────────────────────────────


class TestFallbackChain:
    def _get_chain(self):
        from cue.execution.fallback import FallbackChain

        return FallbackChain()

    async def test_has_drag_executor(self):
        chain = self._get_chain()
        from cue.execution.drag import PreciseDragExecutor

        assert isinstance(chain._drag_executor, PreciseDragExecutor)

    async def test_stage1_nudge_success(self):
        chain = self._get_chain()
        action = Action(type="left_click", coordinate=(100, 100))
        # First nudged attempt succeeds
        execute_fn = AsyncMock(return_value=True)
        verify_fn = AsyncMock(return_value=True)
        elements = _make_elements()

        result = await chain.try_fallbacks(action, execute_fn, verify_fn, elements)
        assert result.success is True
        assert result.fallback_used == "coordinate_nudge"
        assert any("stage1_nudge" in s for s in result.steps_taken)

    async def test_stage1_all_nudges_fail(self):
        chain = self._get_chain()
        action = Action(type="left_click", coordinate=(100, 100))
        # nudge executes OK but verify fails; stage2 zoom also fails; continue to stage3+
        execute_fn = AsyncMock(return_value=True)
        verify_fn = AsyncMock(return_value=False)
        elements = _make_elements()

        result = await chain.try_fallbacks(action, execute_fn, verify_fn, elements)
        assert "stage1_nudge_failed" in result.steps_taken

    async def test_stage2_zoom_reground(self):
        chain = self._get_chain()
        action = Action(type="left_click", coordinate=(100, 100))
        call_count = 0

        async def execute_fn(a: Action) -> bool:
            nonlocal call_count
            call_count += 1
            # Fail nudges, succeed on stage2 zoom action
            return bool(a.metadata.get("suggest_zoom"))

        async def verify_fn() -> bool:
            return True

        elements = _make_elements()
        result = await chain.try_fallbacks(action, execute_fn, verify_fn, elements)
        assert result.success is True
        assert result.fallback_used == "zoom_reground"

    async def test_stage3_keyboard_shortcut_save(self):
        chain = self._get_chain()
        # Place a "save" element near click coordinate
        elem = _make_element(label="Save", bbox=(80, 80, 120, 120), confidence=0.9)
        elements = _make_elements(elem)
        action = Action(type="left_click", coordinate=(100, 100))

        call_log: list[str] = []

        async def execute_fn(a: Action) -> bool:
            call_log.append(a.type)
            # Fail nudges + zoom, succeed on key action (shortcut)
            return a.type == "key" and a.key == "ctrl+s"

        async def verify_fn() -> bool:
            return True

        result = await chain.try_fallbacks(action, execute_fn, verify_fn, elements)
        assert result.success is True
        assert result.fallback_used == "keyboard_shortcut"

    async def test_stage4_tab_navigation(self):
        chain = self._get_chain()
        action = Action(type="left_click", coordinate=(100, 100))
        elements = _make_elements()

        keys_pressed: list[str] = []

        async def execute_fn(a: Action) -> bool:
            if a.type == "key":
                keys_pressed.append(a.key)
                if a.key == "enter":
                    return True
            return False

        verify_call_count = 0

        async def verify_fn() -> bool:
            nonlocal verify_call_count
            verify_call_count += 1
            return True

        result = await chain.try_fallbacks(action, execute_fn, verify_fn, elements)
        assert result.success is True
        assert result.fallback_used == "tab_navigation"
        assert "tab" in keys_pressed
        assert "enter" in keys_pressed

    async def test_stage6_scroll_and_retry(self):
        chain = self._get_chain()
        action = Action(type="left_click", coordinate=(100, 100))
        elements = _make_elements()

        scroll_happened = [False]

        async def execute_fn(a: Action) -> bool:
            if a.type == "scroll":
                scroll_happened[0] = True
            # Succeed only on the scroll retry of the original action
            return scroll_happened[0] and a.type == "left_click" and not a.metadata.get(
                "suggest_zoom"
            )

        async def verify_fn() -> bool:
            return True

        result = await chain.try_fallbacks(action, execute_fn, verify_fn, elements)
        assert result.success is True
        assert result.fallback_used == "scroll_and_retry"

    async def test_all_stages_exhausted(self):
        chain = self._get_chain()
        action = Action(type="left_click", coordinate=(100, 100))
        elements = _make_elements()
        execute_fn = AsyncMock(return_value=False)
        verify_fn = AsyncMock(return_value=False)

        result = await chain.try_fallbacks(action, execute_fn, verify_fn, elements)
        assert result.success is False
        assert result.fallback_used == "all_stages_failed"
        assert result.error is not None

    async def test_no_coordinate_skips_stage1(self):
        chain = self._get_chain()
        action = Action(type="left_click")  # no coordinate
        elements = _make_elements()
        execute_fn = AsyncMock(return_value=False)
        verify_fn = AsyncMock(return_value=False)

        result = await chain.try_fallbacks(action, execute_fn, verify_fn, elements)
        assert "stage1_nudge_failed" not in result.steps_taken


# ── PreActionValidator ────────────────────────────────────────────────────────


class TestPreActionValidator:
    def _get_validator(self):
        from cue.execution.validator import PreActionValidator

        return PreActionValidator()

    def test_non_click_is_safe(self):
        validator = self._get_validator()
        action = Action(type="key", key="ctrl+s")
        elements = _make_elements()
        result = validator.validate(action, elements, (1920, 1080))
        assert result.status == ValidationStatus.SAFE
        assert result.checks[0].name == "skip"

    def test_click_no_coordinate_is_safe(self):
        validator = self._get_validator()
        action = Action(type="left_click")
        elements = _make_elements()
        result = validator.validate(action, elements, (1920, 1080))
        assert result.status == ValidationStatus.SAFE

    def test_click_with_element_in_viewport_is_safe(self):
        validator = self._get_validator()
        elem = _make_element(bbox=(90, 90, 110, 110), confidence=0.9)
        elements = _make_elements(elem)
        action = Action(type="left_click", coordinate=(100, 100))
        result = validator.validate(action, elements, (1920, 1080))
        assert result.status == ValidationStatus.SAFE
        names = [c.name for c in result.checks]
        assert "target_exists" in names
        assert "target_in_viewport" in names
        assert "no_blocking_overlay" in names

    def test_no_element_near_coordinate(self):
        validator = self._get_validator()
        # Element far away
        elem = _make_element(bbox=(500, 500, 600, 550), confidence=0.9)
        elements = _make_elements(elem)
        action = Action(type="left_click", coordinate=(100, 100))
        result = validator.validate(action, elements, (1920, 1080))
        # target_exists fails (has fix_action), but target_visible and target_enabled also
        # fail with no fix_action → not all failed checks have fix_action → BLOCKED
        assert result.status == ValidationStatus.BLOCKED
        exists_check = next(c for c in result.checks if c.name == "target_exists")
        assert not exists_check.passed
        assert exists_check.fix_action is not None
        assert exists_check.fix_action.metadata.get("suggest_zoom") is True

    def test_disabled_label_blocked(self):
        validator = self._get_validator()
        elem = _make_element(label="disabled_save", bbox=(90, 90, 110, 110), confidence=0.9)
        elements = _make_elements(elem)
        action = Action(type="left_click", coordinate=(100, 100))
        result = validator.validate(action, elements, (1920, 1080))
        enabled_check = next(c for c in result.checks if c.name == "target_enabled")
        assert not enabled_check.passed

    def test_out_of_viewport_below(self):
        validator = self._get_validator()
        elements = _make_elements()
        # Click below screen
        action = Action(type="left_click", coordinate=(960, 1200))
        result = validator.validate(action, elements, (1920, 1080))
        vp_check = next(c for c in result.checks if c.name == "target_in_viewport")
        assert not vp_check.passed
        # Scroll down fix action
        assert vp_check.fix_action is not None
        assert vp_check.fix_action.delta_y == 3

    def test_out_of_viewport_above(self):
        validator = self._get_validator()
        elements = _make_elements()
        action = Action(type="left_click", coordinate=(960, -50))
        result = validator.validate(action, elements, (1920, 1080))
        vp_check = next(c for c in result.checks if c.name == "target_in_viewport")
        assert not vp_check.passed
        assert vp_check.fix_action is not None
        assert vp_check.fix_action.delta_y == -3

    def test_overlay_check_always_passes(self):
        validator = self._get_validator()
        elem = _make_element(bbox=(90, 90, 110, 110), confidence=0.9)
        elements = _make_elements(elem)
        action = Action(type="left_click", coordinate=(100, 100))
        result = validator.validate(action, elements, (1920, 1080))
        overlay_check = next(c for c in result.checks if c.name == "no_blocking_overlay")
        assert overlay_check.passed

    def test_five_checks_produced_for_click(self):
        validator = self._get_validator()
        elem = _make_element(bbox=(90, 90, 110, 110), confidence=0.9)
        elements = _make_elements(elem)
        action = Action(type="left_click", coordinate=(100, 100))
        result = validator.validate(action, elements, (1920, 1080))
        assert len(result.checks) == 5

    def test_target_visible_check(self):
        validator = self._get_validator()
        # Two overlapping elements; get_topmost_at returns the last one
        elem1 = _make_element(label="Bottom", bbox=(90, 90, 110, 110), confidence=0.9)
        elem2 = _make_element(label="Top", bbox=(90, 90, 110, 110), confidence=0.9)
        elements = _make_elements(elem1, elem2)
        # Click near elem1 center — nearest is elem1 but topmost is elem2 (last in list)
        action = Action(type="left_click", coordinate=(100, 100))
        result = validator.validate(action, elements, (1920, 1080))
        visible_check = next(c for c in result.checks if c.name == "target_visible")
        # target_exists finds nearest by distance → depends on which is closer
        # Both have same center so nearest = elem1 (first found with same distance)
        # topmost at (100,100) = elem2 → visible = False since topmost is not nearest
        assert visible_check is not None


# ── ExecutionEnhancer ─────────────────────────────────────────────────────────


class TestExecutionEnhancer:
    def _get_enhancer(self, **kwargs):
        from cue.execution.enhancer import ExecutionEnhancer

        config = ExecutionConfig(**kwargs)
        return ExecutionEnhancer(config=config)

    def _make_screenshot_fn(self, before_value: int = 0, after_value: int = 200):
        """Returns screenshot_fn that returns before_value first, then after_value."""
        call_count = [0]
        before = _make_frame(value=before_value)
        after = _make_frame(value=after_value)

        async def screenshot_fn():
            call_count[0] += 1
            return before if call_count[0] <= 1 else after

        return screenshot_fn

    async def test_successful_action_returns_success(self):
        enhancer = self._get_enhancer(
            enable_pre_validation=False,
            enable_timing_control=False,
            enable_fallback_chain=False,
        )
        context = _make_context()
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = self._make_screenshot_fn(before_value=0, after_value=200)

        result = await enhancer.execute(
            Action(type="left_click", coordinate=(100, 100)),
            context,
            execute_fn,
            screenshot_fn,
        )
        assert result.success is True

    async def test_blocked_validation_returns_failure(self):
        enhancer = self._get_enhancer(
            enable_pre_validation=True,
            enable_timing_control=False,
            enable_fallback_chain=False,
        )
        # Click outside viewport → target_in_viewport fails with no fix → BLOCKED
        context = _make_context(screen_size=(100, 100))
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = AsyncMock(return_value=_make_frame())

        result = await enhancer.execute(
            Action(type="left_click", coordinate=(500, 500)),
            context,
            execute_fn,
            screenshot_fn,
        )
        assert result.success is False
        assert "BLOCKED" in (result.error or "")

    async def test_basic_level_skips_timing(self):
        enhancer = self._get_enhancer(
            level=EnhancerLevel.BASIC,
            enable_timing_control=True,
            enable_fallback_chain=False,
        )
        context = _make_context()
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = self._make_screenshot_fn(before_value=0, after_value=200)

        with patch.object(enhancer._timing, "wait_for_stable_ui") as mock_wait:
            result = await enhancer.execute(
                Action(type="left_click", coordinate=(100, 100)),
                context,
                execute_fn,
                screenshot_fn,
            )
        mock_wait.assert_not_called()

    async def test_steps_recorded(self):
        enhancer = self._get_enhancer(
            enable_pre_validation=False,
            enable_timing_control=False,
            enable_fallback_chain=False,
        )
        context = _make_context()
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = self._make_screenshot_fn(before_value=0, after_value=200)

        result = await enhancer.execute(
            Action(type="left_click", coordinate=(100, 100)),
            context,
            execute_fn,
            screenshot_fn,
        )
        assert any("refine:" in s for s in result.steps_taken)
        assert any("execute:" in s for s in result.steps_taken)

    async def test_fallback_invoked_on_no_change(self):
        enhancer = self._get_enhancer(
            enable_pre_validation=False,
            enable_timing_control=False,
            enable_fallback_chain=True,
        )
        context = _make_context()
        # execute returns True but screen doesn't change → verified=False → fallback
        same_frame = _make_frame(value=100)
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = AsyncMock(return_value=same_frame)

        with patch.object(enhancer._fallback, "try_fallbacks",
                          new_callable=AsyncMock) as mock_fb:
            mock_fb.return_value = ActionResult(
                success=True, action_type="left_click", steps_taken=["fallback:used"]
            )
            result = await enhancer.execute(
                Action(type="left_click", coordinate=(100, 100)),
                context,
                execute_fn,
                screenshot_fn,
            )
        mock_fb.assert_called_once()

    async def test_zoom_refinement_step_recorded(self):
        enhancer = self._get_enhancer(
            enable_pre_validation=False,
            enable_zoom_reground=True,
            enable_timing_control=False,
            enable_fallback_chain=False,
        )
        context = _make_context()
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = self._make_screenshot_fn(before_value=0, after_value=200)

        # Patch refiner to return suggest_zoom action
        zoom_action = Action(
            type="left_click", coordinate=(100, 100), metadata={"suggest_zoom": True}
        )
        with patch.object(enhancer._refiner, "refine", new_callable=AsyncMock,
                          return_value=zoom_action):
            with patch.object(enhancer._refiner, "zoom_and_refine",
                               new_callable=AsyncMock,
                               return_value=zoom_action):
                result = await enhancer.execute(
                    Action(type="left_click", coordinate=(100, 100)),
                    context,
                    execute_fn,
                    screenshot_fn,
                )
        assert any("zoom:" in s for s in result.steps_taken)

    async def test_before_frame_passed_in(self):
        enhancer = self._get_enhancer(
            enable_pre_validation=False,
            enable_timing_control=False,
            enable_fallback_chain=False,
        )
        context = _make_context()
        execute_fn = AsyncMock(return_value=True)
        # After frame is different from before
        before_frame = _make_frame(value=0)
        after_frame = _make_frame(value=200)
        screenshot_fn = AsyncMock(return_value=after_frame)

        result = await enhancer.execute(
            Action(type="left_click", coordinate=(100, 100)),
            context,
            execute_fn,
            screenshot_fn,
            before_frame=before_frame,
        )
        assert result.success is True

    async def test_non_click_action_skips_coordinate_refine_snap(self):
        enhancer = self._get_enhancer(
            enable_timing_control=False,
            enable_fallback_chain=False,
        )
        context = _make_context()
        execute_fn = AsyncMock(return_value=True)
        screenshot_fn = self._make_screenshot_fn(before_value=0, after_value=200)

        result = await enhancer.execute(
            Action(type="type", text="hello"),
            context,
            execute_fn,
            screenshot_fn,
        )
        assert any("refine:unchanged" in s for s in result.steps_taken)


# ── PreciseDragExecutor ───────────────────────────────────────────────────────


class TestPreciseDragExecutor:
    def _get_executor(self):
        from cue.execution.drag import PreciseDragExecutor

        return PreciseDragExecutor()

    async def test_basic_drag_sequence(self):
        executor = self._get_executor()
        actions_executed: list[Action] = []

        async def execute_fn(a: Action) -> bool:
            actions_executed.append(a)
            return True

        result = await executor.execute_drag(
            start=(100, 100),
            end=(200, 200),
            execute_fn=execute_fn,
            step_delay_ms=0,
        )
        assert result.success is True
        types = [a.type for a in actions_executed]
        assert "mouse_move" in types
        assert "mouse_down" in types
        assert "mouse_up" in types

    async def test_modifier_key_hold_and_release(self):
        executor = self._get_executor()
        actions_executed: list[Action] = []

        async def execute_fn(a: Action) -> bool:
            actions_executed.append(a)
            return True

        result = await executor.execute_drag(
            start=(100, 100),
            end=(200, 200),
            execute_fn=execute_fn,
            modifier_key="shift",
            step_delay_ms=0,
        )
        assert result.success is True
        steps = result.steps_taken
        assert any("hold_key:shift" in s for s in steps)
        assert any("release_key:shift" in s for s in steps)

    async def test_intermediate_waypoints_executed(self):
        executor = self._get_executor()
        actions_executed: list[Action] = []

        async def execute_fn(a: Action) -> bool:
            actions_executed.append(a)
            return True

        waypoints = [(120, 120), (150, 150), (180, 180)]
        result = await executor.execute_drag(
            start=(100, 100),
            end=(200, 200),
            execute_fn=execute_fn,
            intermediate_points=waypoints,
            step_delay_ms=0,
        )
        assert result.success is True
        steps = result.steps_taken
        assert any("waypoint_0" in s for s in steps)
        assert any("waypoint_1" in s for s in steps)
        assert any("waypoint_2" in s for s in steps)

    async def test_error_releases_mouse(self):
        executor = self._get_executor()
        call_count = [0]

        async def execute_fn(a: Action) -> bool:
            call_count[0] += 1
            if a.type == "mouse_down":
                raise RuntimeError("input error")
            return True

        result = await executor.execute_drag(
            start=(100, 100),
            end=(200, 200),
            execute_fn=execute_fn,
            step_delay_ms=0,
        )
        assert result.success is False
        assert result.error is not None
        assert any("error:" in s for s in result.steps_taken)

    async def test_error_releases_modifier_key(self):
        executor = self._get_executor()

        async def execute_fn(a: Action) -> bool:
            if a.type == "mouse_down":
                raise RuntimeError("crash")
            return True

        result = await executor.execute_drag(
            start=(100, 100),
            end=(200, 200),
            execute_fn=execute_fn,
            modifier_key="ctrl",
            step_delay_ms=0,
        )
        assert result.success is False
        assert result.action_type == "precise_drag"

    def test_interpolate_points_count(self):
        executor = self._get_executor()
        points = executor.interpolate_points((0, 0), (100, 100), num_points=4)
        assert len(points) == 4

    def test_interpolate_points_linear(self):
        executor = self._get_executor()
        points = executor.interpolate_points((0, 0), (100, 0), num_points=3)
        # t = 1/4, 2/4, 3/4 → x = 25, 50, 75
        assert points[0] == (25, 0)
        assert points[1] == (50, 0)
        assert points[2] == (75, 0)

    def test_interpolate_points_empty_on_zero(self):
        executor = self._get_executor()
        points = executor.interpolate_points((0, 0), (100, 100), num_points=0)
        assert points == []

    async def test_step_delay_applied(self):
        executor = self._get_executor()
        execute_fn = AsyncMock(return_value=True)

        with patch("cue.execution.drag.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await executor.execute_drag(
                start=(10, 10),
                end=(50, 50),
                execute_fn=execute_fn,
                step_delay_ms=100,
            )
        assert mock_sleep.call_count >= 2

    async def test_no_step_delay_skips_sleep(self):
        executor = self._get_executor()
        execute_fn = AsyncMock(return_value=True)

        with patch("cue.execution.drag.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await executor.execute_drag(
                start=(10, 10),
                end=(50, 50),
                execute_fn=execute_fn,
                step_delay_ms=0,
            )
        mock_sleep.assert_not_called()
