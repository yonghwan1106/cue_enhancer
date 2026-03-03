"""Comprehensive unit tests for CUEAgent orchestrator."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from cue.config import (
    CUEConfig,
    EnhancerLevel,
    GroundingConfig,
    ExecutionConfig,
    MemoryConfig,
    PlanningConfig,
    EfficiencyConfig,
    VerificationConfig,
)
from cue.types import (
    Action,
    ActionResult,
    EnhancedContext,
    Lesson,
    EpisodeRecord,
    MemoryContext,
    ScreenState,
    UIElement,
    VerificationResult,
)
from cue.agent import CUEAgent


def _make_image(width: int = 1024, height: int = 768) -> Image.Image:
    return Image.new("RGB", (width, height), color=(30, 30, 30))


def _make_config(**overrides) -> CUEConfig:
    """Return a CUEConfig with all modules disabled (fast unit tests)."""
    return CUEConfig(
        grounding=GroundingConfig(level=EnhancerLevel.OFF),
        execution=ExecutionConfig(level=EnhancerLevel.OFF),
        verification=VerificationConfig(level=EnhancerLevel.OFF),
        memory=MemoryConfig(level=EnhancerLevel.OFF),
        planning=PlanningConfig(level=EnhancerLevel.OFF),
        efficiency=EfficiencyConfig(level=EnhancerLevel.OFF),
        **overrides,
    )


# ─── __init__ ──────────────────────────────────────────────


class TestCUEAgentInit:
    def test_default_config_created_when_none(self):
        with patch("cue.agent.CUEConfig.load", return_value=_make_config()):
            with patch("cue.agent.anthropic.AsyncAnthropic"):
                agent = CUEAgent()
        assert agent.config is not None

    def test_provided_config_used(self):
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            agent = CUEAgent(cfg)
        assert agent.config is cfg

    def test_all_modules_none_before_init(self):
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            agent = CUEAgent(cfg)
        assert agent._environment is None
        assert agent._grounding is None
        assert agent._execution is None
        assert agent._verification is None
        assert agent._safety is None
        assert agent._planning is None
        assert agent._memory is None
        assert agent._efficiency is None
        assert agent._reflection is None
        assert agent._checkpoint is None

    def test_not_initialized(self):
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            agent = CUEAgent(cfg)
        assert agent._initialized is False

    def test_screenshot_cache_fields_initialized(self):
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            agent = CUEAgent(cfg)
        assert agent._last_screenshot is None
        assert agent._last_screenshot_time == 0.0


# ─── _init_modules ─────────────────────────────────────────


class TestInitModules:
    async def test_sets_initialized_true(self):
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            agent = CUEAgent(cfg)

        mock_env = MagicMock()
        with patch("cue.platform.create_environment", return_value=mock_env):
            await agent._init_modules()

        assert agent._initialized is True

    async def test_idempotent_second_call(self):
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            agent = CUEAgent(cfg)

        mock_env = MagicMock()
        with patch("cue.platform.create_environment", return_value=mock_env):
            await agent._init_modules()
            await agent._init_modules()  # second call — no side effects

        assert agent._initialized is True

    async def test_modules_stay_none_when_off(self):
        cfg = _make_config()  # all OFF
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            agent = CUEAgent(cfg)

        mock_env = MagicMock()
        with patch("cue.platform.create_environment", return_value=mock_env):
            await agent._init_modules()

        assert agent._grounding is None
        assert agent._execution is None
        assert agent._verification is None
        assert agent._memory is None
        assert agent._planning is None
        assert agent._efficiency is None

    async def test_environment_always_created(self):
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            agent = CUEAgent(cfg)

        mock_env = MagicMock()
        with patch("cue.platform.create_environment", return_value=mock_env) as mock_create:
            await agent._init_modules()

        mock_create.assert_called_once()
        assert agent._environment is mock_env


# ─── _take_screenshot ──────────────────────────────────────


class TestTakeScreenshot:
    def _make_agent_with_env(self, cfg: CUEConfig) -> tuple[CUEAgent, MagicMock]:
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            agent = CUEAgent(cfg)
        mock_env = AsyncMock()
        mock_env.take_screenshot = AsyncMock(return_value=_make_image())
        agent._environment = mock_env
        agent._initialized = True
        return agent, mock_env

    async def test_returns_fresh_screenshot_first_call(self):
        cfg = _make_config()
        agent, mock_env = self._make_agent_with_env(cfg)

        result = await agent._take_screenshot()

        assert isinstance(result, Image.Image)
        mock_env.take_screenshot.assert_called_once()

    async def test_returns_cached_screenshot_within_200ms(self):
        cfg = _make_config()
        agent, mock_env = self._make_agent_with_env(cfg)

        first = await agent._take_screenshot()
        # Simulate second call within 200ms — cache still valid
        agent._last_screenshot_time = time.monotonic()
        second = await agent._take_screenshot()

        assert first is second
        mock_env.take_screenshot.assert_called_once()  # only one real capture

    async def test_returns_fresh_screenshot_after_cache_expiry(self):
        cfg = _make_config()
        agent, mock_env = self._make_agent_with_env(cfg)

        img1 = _make_image()
        img2 = _make_image()
        mock_env.take_screenshot = AsyncMock(side_effect=[img1, img2])

        first = await agent._take_screenshot()
        # Force cache expiry
        agent._last_screenshot_time = time.monotonic() - 0.3
        second = await agent._take_screenshot()

        assert first is img1
        assert second is img2
        assert mock_env.take_screenshot.call_count == 2

    async def test_updates_cache_timestamp_after_fresh_capture(self):
        cfg = _make_config()
        agent, mock_env = self._make_agent_with_env(cfg)

        before = time.monotonic()
        await agent._take_screenshot()
        after = time.monotonic()

        assert before <= agent._last_screenshot_time <= after

    async def test_cache_stores_returned_image(self):
        cfg = _make_config()
        agent, mock_env = self._make_agent_with_env(cfg)

        img = _make_image()
        mock_env.take_screenshot = AsyncMock(return_value=img)
        await agent._take_screenshot()

        assert agent._last_screenshot is img


# ─── _parse_action ─────────────────────────────────────────


class TestParseAction:
    def _agent(self) -> CUEAgent:
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            return CUEAgent(cfg)

    def _make_tool_use_block(self, name: str, input_data: dict, block_id: str = "tu_001"):
        block = MagicMock()
        block.type = "tool_use"
        block.name = name
        block.input = input_data
        block.id = block_id
        return block

    def test_extracts_action_from_computer_tool_use(self):
        agent = self._agent()
        block = self._make_tool_use_block(
            "computer", {"action": "left_click", "coordinate": [200, 300]}
        )
        action, tool_id = agent._parse_action([block])

        assert action is not None
        assert action.type == "left_click"
        assert action.coordinate == (200, 300)
        assert tool_id == "tu_001"

    def test_returns_none_none_for_non_list_content(self):
        agent = self._agent()
        action, tool_id = agent._parse_action("some text string")
        assert action is None
        assert tool_id is None

    def test_returns_none_none_for_empty_list(self):
        agent = self._agent()
        action, tool_id = agent._parse_action([])
        assert action is None
        assert tool_id is None

    def test_returns_none_none_when_no_tool_use_block(self):
        agent = self._agent()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "I will click the button."
        action, tool_id = agent._parse_action([text_block])
        assert action is None
        assert tool_id is None

    def test_returns_none_none_for_non_computer_tool(self):
        agent = self._agent()
        block = self._make_tool_use_block("bash", {"command": "ls"})
        action, tool_id = agent._parse_action([block])
        assert action is None
        assert tool_id is None

    def test_skips_text_blocks_finds_tool_use(self):
        agent = self._agent()
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "Clicking now."
        tool_block = self._make_tool_use_block(
            "computer", {"action": "type", "text": "hello"}, "tu_002"
        )
        action, tool_id = agent._parse_action([text_block, tool_block])
        assert action is not None
        assert action.type == "type"
        assert tool_id == "tu_002"


# ─── _tool_input_to_action ─────────────────────────────────


class TestToolInputToAction:
    def _agent(self) -> CUEAgent:
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            return CUEAgent(cfg)

    def test_maps_action_type_and_coordinate(self):
        agent = self._agent()
        result = agent._tool_input_to_action(
            {"action": "left_click", "coordinate": [100, 200]}
        )
        assert result.type == "left_click"
        assert result.coordinate == (100, 200)

    def test_coordinate_converted_to_ints(self):
        agent = self._agent()
        result = agent._tool_input_to_action(
            {"action": "left_click", "coordinate": [100.7, 200.3]}
        )
        assert result.coordinate == (100, 200)
        assert isinstance(result.coordinate[0], int)

    def test_text_field_mapped(self):
        agent = self._agent()
        result = agent._tool_input_to_action({"action": "type", "text": "Hello World"})
        assert result.text == "Hello World"

    def test_missing_coordinate_yields_none(self):
        agent = self._agent()
        result = agent._tool_input_to_action({"action": "key", "text": "ctrl+s"})
        assert result.coordinate is None

    def test_missing_text_yields_none(self):
        agent = self._agent()
        result = agent._tool_input_to_action({"action": "screenshot"})
        assert result.text is None

    def test_empty_input_returns_action_with_empty_type(self):
        agent = self._agent()
        result = agent._tool_input_to_action({})
        assert result.type == ""
        assert result.coordinate is None
        assert result.text is None


# ─── _build_system_prompt ──────────────────────────────────


class TestBuildSystemPrompt:
    def _agent(self) -> CUEAgent:
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            return CUEAgent(cfg)

    def test_contains_base_guidelines(self):
        agent = self._agent()
        prompt = agent._build_system_prompt("open browser")
        assert "computer use agent" in prompt.lower()
        assert "Guidelines" in prompt

    def test_no_memory_section_when_context_empty(self):
        agent = self._agent()
        prompt = agent._build_system_prompt("open browser", MemoryContext())
        assert "Past Lessons" not in prompt
        assert "Similar Past Episodes" not in prompt

    def test_injects_lessons_when_present(self):
        agent = self._agent()
        lesson = Lesson(
            app="Chrome",
            situation="opening URL",
            failed_approach="type in wrong field",
            successful_approach="click address bar first",
            confidence=0.9,
        )
        ctx = MemoryContext(lessons=[lesson])
        prompt = agent._build_system_prompt("open browser", ctx)
        assert "Past Lessons" in prompt
        assert "Chrome" in prompt

    def test_injects_similar_episodes_when_present(self):
        agent = self._agent()
        ep = EpisodeRecord(
            task="open Chrome",
            app="Chrome",
            success=True,
            total_steps=2,
            reflection="Worked well.",
        )
        ctx = MemoryContext(similar_episodes=[ep])
        prompt = agent._build_system_prompt("open browser", ctx)
        assert "Similar Past Episodes" in prompt
        assert "open Chrome" in prompt

    def test_no_memory_section_when_context_is_none(self):
        agent = self._agent()
        prompt = agent._build_system_prompt("open browser", None)
        assert "Past Lessons" not in prompt


# ─── _build_message_content ────────────────────────────────


class TestBuildMessageContent:
    def _agent(self) -> CUEAgent:
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            return CUEAgent(cfg)

    def _empty_context(self) -> EnhancedContext:
        return EnhancedContext(elements=[], element_description="")

    def test_includes_base64_image_for_full_mode(self):
        agent = self._agent()
        img = _make_image()
        content = agent._build_message_content(img, self._empty_context(), send_mode="full")
        image_blocks = [b for b in content if b.get("type") == "image"]
        assert len(image_blocks) == 1
        assert image_blocks[0]["source"]["type"] == "base64"

    def test_skips_screenshot_for_skip_mode(self):
        agent = self._agent()
        img = _make_image()
        content = agent._build_message_content(img, self._empty_context(), send_mode="skip")
        image_blocks = [b for b in content if b.get("type") == "image"]
        assert len(image_blocks) == 0

    def test_includes_image_for_text_only_mode(self):
        agent = self._agent()
        img = _make_image()
        # send_mode other than "skip" → include image
        content = agent._build_message_content(img, self._empty_context(), send_mode="text_only")
        image_blocks = [b for b in content if b.get("type") == "image"]
        assert len(image_blocks) == 1

    def test_includes_planning_text_when_provided(self):
        agent = self._agent()
        img = _make_image()
        content = agent._build_message_content(
            img, self._empty_context(), planning_text="Step 1: click OK", send_mode="full"
        )
        text_blocks = [b for b in content if b.get("type") == "text"]
        texts = " ".join(b["text"] for b in text_blocks)
        assert "Step 1: click OK" in texts
        assert "[CUE Planning]" in texts

    def test_no_planning_block_when_empty(self):
        agent = self._agent()
        img = _make_image()
        content = agent._build_message_content(
            img, self._empty_context(), planning_text="", send_mode="full"
        )
        text_blocks = [b for b in content if b.get("type") == "text"]
        assert all("[CUE Planning]" not in b["text"] for b in text_blocks)

    def test_includes_grounding_description_when_present(self):
        agent = self._agent()
        img = _make_image()
        ctx = EnhancedContext(
            elements=[UIElement(type="button", bbox=(0, 0, 50, 30), label="OK")],
            element_description="OK button at (0,0)-(50,30)",
        )
        content = agent._build_message_content(img, ctx, send_mode="full")
        text_blocks = [b for b in content if b.get("type") == "text"]
        texts = " ".join(b["text"] for b in text_blocks)
        assert "CUE Grounding" in texts
        assert "OK button" in texts

    def test_no_grounding_block_when_description_empty(self):
        agent = self._agent()
        img = _make_image()
        content = agent._build_message_content(
            img, self._empty_context(), send_mode="full"
        )
        text_blocks = [b for b in content if b.get("type") == "text"]
        assert all("CUE Grounding" not in b["text"] for b in text_blocks)


# ─── _is_task_complete ─────────────────────────────────────


class TestIsTaskComplete:
    def _agent(self) -> CUEAgent:
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            return CUEAgent(cfg)

    @pytest.mark.parametrize(
        "text",
        [
            "The task is complete.",
            "The task has been completed successfully.",
            "I have successfully completed the task.",
            "Done with the task — all steps finished.",
            "I finished the task.",
            "Task is done.",
            "Everything completed successfully.",
        ],
    )
    def test_returns_true_for_completion_phrases(self, text: str):
        agent = self._agent()
        assert agent._is_task_complete(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "I am clicking the button.",
            "Opening the browser now.",
            "Waiting for the page to load.",
            "",
            "Error occurred during execution.",
        ],
    )
    def test_returns_false_for_non_completion_text(self, text: str):
        agent = self._agent()
        assert agent._is_task_complete(text) is False

    def test_case_insensitive(self):
        agent = self._agent()
        assert agent._is_task_complete("TASK IS COMPLETE") is True
        assert agent._is_task_complete("SUCCESSFULLY COMPLETED the job") is True


# ─── _build_result_text ────────────────────────────────────


class TestBuildResultText:
    def _agent(self) -> CUEAgent:
        cfg = _make_config()
        with patch("cue.agent.anthropic.AsyncAnthropic"):
            return CUEAgent(cfg)

    def test_includes_action_type(self):
        agent = self._agent()
        result = ActionResult(success=True, action_type="left_click")
        text = agent._build_result_text(result, None)
        assert "left_click" in text

    def test_includes_success_status(self):
        agent = self._agent()
        result = ActionResult(success=True, action_type="type")
        text = agent._build_result_text(result, None)
        assert "Success" in text

    def test_includes_failure_status(self):
        agent = self._agent()
        result = ActionResult(success=False, action_type="left_click", error="element not found")
        text = agent._build_result_text(result, None)
        assert "Failed" in text
        assert "element not found" in text

    def test_includes_fallback_info_when_present(self):
        agent = self._agent()
        result = ActionResult(success=True, action_type="left_click", fallback_used="keyboard_nav")
        text = agent._build_result_text(result, None)
        assert "keyboard_nav" in text
        assert "Fallback" in text

    def test_no_fallback_section_when_not_used(self):
        agent = self._agent()
        result = ActionResult(success=True, action_type="left_click", fallback_used=None)
        text = agent._build_result_text(result, None)
        assert "Fallback" not in text

    def test_includes_verification_tier_and_confidence(self):
        agent = self._agent()
        result = ActionResult(success=True, action_type="left_click")
        verification = VerificationResult(tier=2, success=True, confidence=0.85)
        text = agent._build_result_text(result, verification)
        assert "Tier 2" in text
        assert "0.85" in text

    def test_includes_verification_diagnosis_when_present(self):
        agent = self._agent()
        result = ActionResult(success=True, action_type="left_click")
        verification = VerificationResult(
            tier=1, success=False, confidence=0.3, diagnosis="Button did not depress"
        )
        text = agent._build_result_text(result, verification)
        assert "Button did not depress" in text

    def test_no_verification_section_when_none(self):
        agent = self._agent()
        result = ActionResult(success=True, action_type="screenshot")
        text = agent._build_result_text(result, None)
        assert "Verification" not in text

    def test_text_prefixed_with_cue_tag(self):
        agent = self._agent()
        result = ActionResult(success=True, action_type="key")
        text = agent._build_result_text(result, None)
        assert text.startswith("[CUE]")
