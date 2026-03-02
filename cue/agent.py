"""CUEAgent: Main orchestrator integrating all enhancement modules."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from typing import Any

import anthropic
import numpy as np
from PIL import Image

from cue.config import CUEConfig, EnhancerLevel
from cue.types import (
    Action,
    ActionResult,
    EnhancedContext,
    ExpectedOutcome,
    ScreenState,
    TaskResult,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class CUEAgent:
    """Main agent loop integrating all CUE enhancement modules.

    10-step loop (Phase 1):
    1. Take screenshot
    2. Grounding enhancement
    3. Safety check (screen)
    4. Build enhanced prompt for Claude
    5. Call Claude API
    6. Parse Claude's action
    7. Safety check (action)
    8. Execute action with enhancements
    9. Verify result
    10. Repeat or finish
    """

    def __init__(self, config: CUEConfig | None = None):
        self.config = config or CUEConfig.load()
        self.client = anthropic.Anthropic()
        self._environment = None
        self._grounding = None
        self._execution = None
        self._verification = None
        self._safety = None
        self._initialized = False

    async def _init_modules(self) -> None:
        """Lazily initialize all modules."""
        if self._initialized:
            return

        from cue.platform import create_environment

        self._environment = create_environment()

        if self.config.is_module_enabled("grounding"):
            from cue.grounding import GroundingEnhancer

            self._grounding = GroundingEnhancer(self.config.grounding)

        if self.config.is_module_enabled("execution"):
            from cue.execution import ExecutionEnhancer

            self._execution = ExecutionEnhancer(self.config.execution)

        if self.config.is_module_enabled("verification"):
            from cue.verification import VerificationOrchestrator

            self._verification = VerificationOrchestrator(self.config.verification)

        if self.config.is_module_enabled("safety"):
            from cue.safety import SafetyGate

            self._safety = SafetyGate(self.config.safety)

        self._initialized = True

    async def run(self, task: str) -> TaskResult:
        """Execute a task with the full CUE enhancement loop."""
        await self._init_modules()
        start_time = time.monotonic()

        logger.info("Starting task: %s", task)

        messages: list[dict[str, Any]] = []
        step_count = 0
        max_steps = self.config.agent.max_steps
        timeout = self.config.agent.timeout_seconds

        # System prompt with CUE augmentation
        system_prompt = self._build_system_prompt(task)

        # Initial user message
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": f"Task: {task}"}],
        })

        while step_count < max_steps:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                logger.warning("Task timed out after %.1fs", elapsed)
                return TaskResult(
                    success=False,
                    task=task,
                    steps_taken=step_count,
                    total_time_seconds=elapsed,
                    error="Task timed out",
                )

            # Step 1: Take screenshot
            screenshot = await self._take_screenshot()
            screen_state = await self._build_screen_state(screenshot)

            # Step 2: Grounding enhancement
            enhanced_context = await self._enhance_grounding(screenshot, task)

            # Step 3: Safety check (screen)
            if self._safety:
                screen_safety = self._safety.check_screen(screen_state)
                if screen_safety.level.value == "blocked":
                    logger.warning("Screen safety blocked: %s", screen_safety.reason)

            # Step 4: Build enhanced content for Claude
            content = self._build_message_content(screenshot, enhanced_context)

            # Add screenshot + context to messages
            if step_count == 0:
                messages[0]["content"].extend(content)
            else:
                messages.append({"role": "user", "content": content})

            # Step 5: Call Claude API
            response = await self._call_claude(system_prompt, messages)

            # Parse response
            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # Step 6: Extract action from response
            action = self._parse_action(assistant_content)

            if action is None:
                # Claude returned text only — task may be complete
                text_response = self._extract_text(assistant_content)
                if self._is_task_complete(text_response):
                    elapsed = time.monotonic() - start_time
                    return TaskResult(
                        success=True,
                        task=task,
                        steps_taken=step_count,
                        total_time_seconds=elapsed,
                    )
                # Continue the loop — Claude might need more context
                step_count += 1
                continue

            # Step 7: Safety check (action)
            if self._safety:
                action_safety = self._safety.check_action(action)
                if action_safety.level.value == "blocked":
                    logger.warning("Action blocked by safety: %s", action_safety.reason)
                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "text",
                            "text": f"[CUE Safety] Action blocked: {action_safety.reason}. "
                                    "Please choose a different approach.",
                        }],
                    })
                    step_count += 1
                    continue
                elif action_safety.level.value == "needs_confirmation":
                    logger.info("Action needs confirmation: %s", action_safety.reason)
                    # In Phase 1, auto-confirm (real confirmation UI in Phase 2)

            # Step 8: Execute with enhancements
            before_screenshot = np.array(screenshot)
            action_result = await self._execute_action(action, enhanced_context)

            # Step 9: Verify result
            after_screenshot_img = await self._take_screenshot()
            after_screenshot = np.array(after_screenshot_img)
            verification = await self._verify_action(
                before_screenshot, after_screenshot, screen_state, action
            )

            # Build result message for Claude
            result_text = self._build_result_text(action_result, verification)
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": result_text}],
            })

            step_count += 1
            logger.info(
                "Step %d: action=%s success=%s verification=%s",
                step_count, action.type,
                action_result.success, verification.success if verification else "n/a",
            )

        elapsed = time.monotonic() - start_time
        return TaskResult(
            success=False,
            task=task,
            steps_taken=step_count,
            total_time_seconds=elapsed,
            error=f"Max steps ({max_steps}) reached",
        )

    # ─── Internal methods ──────────────────────────────────

    async def _take_screenshot(self) -> Image.Image:
        cfg = self.config.agent
        return await self._environment.take_screenshot(cfg.screenshot_width, cfg.screenshot_height)

    async def _build_screen_state(self, screenshot: Image.Image) -> ScreenState:
        a11y_tree = None
        if self._grounding:
            try:
                a11y_tree = await self._environment.get_a11y_tree()
            except Exception:
                pass

        window_info = await self._environment.get_active_window_info()
        return ScreenState(
            screenshot=screenshot,
            a11y_tree=a11y_tree,
            timestamp=time.time(),
            app_name=window_info.get("app_name", ""),
            window_title=window_info.get("title", ""),
        )

    async def _enhance_grounding(
        self, screenshot: Image.Image, task_context: str
    ) -> EnhancedContext:
        if not self._grounding:
            return EnhancedContext(elements=[], element_description="")

        result = await self._grounding.enhance(screenshot, task_context)
        return EnhancedContext(
            elements=result.elements,
            element_description=result.element_description,
        )

    async def _call_claude(
        self, system: str, messages: list[dict]
    ) -> anthropic.types.Message:
        """Call Claude API with computer use tools."""
        cfg = self.config.agent

        # Serialize messages — convert content blocks for API
        api_messages = self._prepare_messages(messages)

        response = self.client.messages.create(
            model=cfg.model,
            max_tokens=4096,
            system=system,
            messages=api_messages,
            tools=[
                {
                    "type": "computer_20241022",
                    "name": "computer",
                    "display_width_px": cfg.screenshot_width,
                    "display_height_px": cfg.screenshot_height,
                    "display_number": 1,
                },
            ],
            betas=cfg.api_betas,
        )
        return response

    def _prepare_messages(self, messages: list[dict]) -> list[dict]:
        """Prepare messages for the Claude API, ensuring proper format."""
        prepared = []
        for msg in messages:
            if isinstance(msg.get("content"), list):
                # Already structured content
                prepared.append(msg)
            elif isinstance(msg.get("content"), str):
                prepared.append({
                    "role": msg["role"],
                    "content": [{"type": "text", "text": msg["content"]}],
                })
            else:
                prepared.append(msg)
        return prepared

    def _build_system_prompt(self, task: str) -> str:
        return (
            "You are a computer use agent. You can see the screen and interact with it "
            "to complete tasks. Use the computer tool to take actions.\n\n"
            "Guidelines:\n"
            "- Click on the exact center of UI elements\n"
            "- Use keyboard shortcuts when possible for efficiency\n"
            "- Verify each action's result before proceeding\n"
            "- If an action fails, try alternative approaches\n"
            "- Report completion when the task is done\n"
        )

    def _build_message_content(
        self, screenshot: Image.Image, context: EnhancedContext
    ) -> list[dict]:
        """Build message content with screenshot and enhanced context."""
        content: list[dict] = []

        # Screenshot as base64
        buffered = io.BytesIO()
        screenshot.save(buffered, format="PNG")
        img_b64 = base64.b64encode(buffered.getvalue()).decode("utf-8")

        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64,
            },
        })

        # Enhanced context description
        if context.element_description:
            content.append({
                "type": "text",
                "text": f"[CUE Grounding] Detected UI elements:\n{context.element_description}",
            })

        return content

    def _parse_action(self, content: Any) -> Action | None:
        """Extract an Action from Claude's response content."""
        if not isinstance(content, list):
            return None

        for block in content:
            if hasattr(block, "type") and block.type == "tool_use":
                if block.name == "computer":
                    return self._tool_input_to_action(block.input)
        return None

    def _tool_input_to_action(self, tool_input: dict) -> Action:
        """Convert Claude's tool_use input to an Action."""
        action_type = tool_input.get("action", "")
        coordinate = tool_input.get("coordinate")
        text = tool_input.get("text")

        coord_tuple = None
        if coordinate and isinstance(coordinate, (list, tuple)) and len(coordinate) == 2:
            coord_tuple = (int(coordinate[0]), int(coordinate[1]))

        return Action(
            type=action_type,
            coordinate=coord_tuple,
            text=text,
        )

    async def _execute_action(
        self, action: Action, context: EnhancedContext
    ) -> ActionResult:
        """Execute an action, optionally with execution enhancement."""
        if self._execution:
            return await self._execution.execute(
                action=action,
                context=context,
                execute_fn=self._raw_execute,
                screenshot_fn=self._take_screenshot,
            )

        # Direct execution without enhancement
        try:
            await self._raw_execute(action)
            return ActionResult(success=True, action_type=action.type)
        except Exception as e:
            return ActionResult(
                success=False, action_type=action.type, error=str(e)
            )

    async def _raw_execute(self, action: Action) -> None:
        """Execute a raw action on the environment."""
        env = self._environment

        if action.type in ("left_click", "double_click", "right_click"):
            if not action.coordinate:
                raise ValueError(f"{action.type} requires coordinate")
            x, y = action.coordinate
            button = "left" if action.type != "right_click" else "right"
            click_count = 2 if action.type == "double_click" else 1
            await env.click(x, y, button=button, click_count=click_count)

        elif action.type == "triple_click":
            if not action.coordinate:
                raise ValueError("triple_click requires coordinate")
            x, y = action.coordinate
            await env.click(x, y, button="left", click_count=3)

        elif action.type == "type":
            if action.text:
                await env.send_keys(action.text)

        elif action.type == "key":
            if action.text:
                await env.send_key(action.text)

        elif action.type == "scroll":
            x, y = action.coordinate or (0, 0)
            await env.scroll(x, y, delta_x=action.delta_x, delta_y=action.delta_y)

        elif action.type == "mouse_move":
            if action.coordinate:
                await env.mouse_move(*action.coordinate)

        elif action.type == "mouse_down":
            if action.coordinate:
                await env.mouse_down(*action.coordinate)

        elif action.type == "mouse_up":
            if action.coordinate:
                await env.mouse_up(*action.coordinate)

        elif action.type == "screenshot":
            pass  # No-op; screenshot is taken by the loop

        elif action.type == "wait":
            duration = (action.duration_ms or 1000) / 1000.0
            await asyncio.sleep(duration)

        else:
            logger.warning("Unknown action type: %s", action.type)

    async def _verify_action(
        self,
        before: np.ndarray,
        after: np.ndarray,
        screen_state: ScreenState,
        action: Action,
    ) -> VerificationResult | None:
        """Verify the result of an action."""
        if not self._verification:
            return None

        before_tree = screen_state.a11y_tree
        after_tree = None
        try:
            after_tree = await self._environment.get_a11y_tree()
        except Exception:
            pass

        expected = ExpectedOutcome(description=f"Action {action.type} should have an effect")

        return await self._verification.verify_step(
            before_screenshot=before,
            after_screenshot=after,
            before_tree=before_tree,
            after_tree=after_tree,
            action=action,
            expected=expected,
        )

    def _build_result_text(
        self, result: ActionResult, verification: VerificationResult | None
    ) -> str:
        """Build a result summary for Claude."""
        parts = [f"Action executed: {result.action_type}"]
        if result.success:
            parts.append("Status: Success")
        else:
            parts.append(f"Status: Failed — {result.error or 'unknown error'}")

        if result.fallback_used:
            parts.append(f"Fallback strategy used: {result.fallback_used}")

        if verification:
            parts.append(
                f"Verification (Tier {verification.tier}): "
                f"{'passed' if verification.success else 'failed'} "
                f"(confidence: {verification.confidence:.2f})"
            )
            if verification.diagnosis:
                parts.append(f"Diagnosis: {verification.diagnosis}")

        return "[CUE] " + " | ".join(parts)

    def _extract_text(self, content: Any) -> str:
        """Extract text from Claude's response content."""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for block in content:
                if hasattr(block, "text"):
                    texts.append(block.text)
                elif isinstance(block, dict) and "text" in block:
                    texts.append(block["text"])
            return " ".join(texts)
        return ""

    def _is_task_complete(self, text: str) -> bool:
        """Heuristic to detect if Claude thinks the task is complete."""
        completion_phrases = [
            "task is complete",
            "task has been completed",
            "successfully completed",
            "done with the task",
            "finished the task",
            "task is done",
            "completed successfully",
        ]
        text_lower = text.lower()
        return any(phrase in text_lower for phrase in completion_phrases)
