"""CUEAgent: Main orchestrator integrating all enhancement modules."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
import uuid
from typing import Any

import anthropic
import numpy as np
from PIL import Image

from cue.config import CUEConfig, EnhancerLevel
from cue.types import (
    Action,
    ActionResult,
    EnhancedContext,
    Episode,
    ExpectedOutcome,
    MemoryContext,
    ScreenState,
    StepRecord,
    SubTask,
    TaskResult,
    VerificationResult,
)

logger = logging.getLogger(__name__)


class CUEAgent:
    """Main agent loop integrating all CUE enhancement modules.

    Phase 2 — 10-step loop:
    1. Screenshot capture
    2. Efficiency check (cache hit → skip grounding)
    3. Grounding enhancement (parallel 3-expert)
    4. Safety gate — screen content injection check
    5. Planning enhancement (subtask + app KB + lessons)
    6. Claude API call (with enhanced context)
    7. Safety gate — proposed action validation
    8. Execution enhancement (coord refinement + timing)
    9. Verification (3-tier) + Reflection
    10. Memory update (working + episodic + reflexion)
    """

    def __init__(self, config: CUEConfig | None = None):
        self.config = config or CUEConfig.load()
        self.client = anthropic.AsyncAnthropic()
        self._environment = None
        self._grounding = None
        self._execution = None
        self._verification = None
        self._safety = None
        self._planning = None
        self._memory = None
        self._efficiency = None
        self._reflection = None
        self._checkpoint = None
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

            # Phase 2: Tier 3 + Reflection + Checkpoint
            if self.config.verification.tier3_enabled:
                from cue.verification.tier3 import Tier3Verifier

                tier3 = Tier3Verifier(self.client, self.config.agent.model)
                self._verification.set_tier3(tier3)

            from cue.verification.reflection import ReflectionEngine
            from cue.verification.checkpoint import CheckpointManager

            self._reflection = ReflectionEngine()
            self._checkpoint = CheckpointManager()

        if self.config.is_module_enabled("safety"):
            from cue.safety import SafetyGate

            self._safety = SafetyGate(self.config.safety)

        # Phase 2 modules
        if self.config.is_module_enabled("planning"):
            from cue.planning import PlanningEnhancer

            self._planning = PlanningEnhancer(self.config.planning)

        if self.config.is_module_enabled("memory"):
            from cue.memory import ThreeLayerMemory

            self._memory = ThreeLayerMemory(self.config.memory)

        if self.config.is_module_enabled("efficiency"):
            from cue.efficiency import EfficiencyEngine

            self._efficiency = EfficiencyEngine(self.config.efficiency)

        self._initialized = True

    async def run(self, task: str) -> TaskResult:
        """Execute a task with the full CUE enhancement loop."""
        await self._init_modules()
        start_time = time.monotonic()
        episode_id = str(uuid.uuid4())[:8]

        logger.info("Starting task: %s (episode=%s)", task, episode_id)

        messages: list[dict[str, Any]] = []
        step_records: list[StepRecord] = []
        step_count = 0
        max_steps = self.config.agent.max_steps
        timeout = self.config.agent.timeout_seconds
        subtasks: list[SubTask] = []
        completed_subtasks = 0

        # Step 5 (pre-loop): Planning enhancement — retrieve memory + plan
        memory_context = MemoryContext()
        app_name = ""
        if self._memory:
            memory_context = await self._memory.remember(task, "")

        # System prompt with CUE augmentation
        system_prompt = self._build_system_prompt(task, memory_context)

        # Initial user message
        messages.append({
            "role": "user",
            "content": [{"type": "text", "text": f"Task: {task}"}],
        })

        # Safety: start episode timer for emergency stop
        if self._safety:
            self._safety.start_episode()

        while step_count < max_steps:
            elapsed = time.monotonic() - start_time
            if elapsed > timeout:
                logger.warning("Task timed out after %.1fs", elapsed)
                break

            # Step 1: Take screenshot
            screenshot = await self._take_screenshot()
            screen_state = await self._build_screen_state(screenshot)

            # Detect app for planning/memory
            if not app_name and screen_state.app_name:
                app_name = screen_state.app_name
                if self._memory:
                    memory_context = await self._memory.remember(task, app_name)

            # Step 2: Efficiency check (cache)
            screenshot_hash = ""
            if self._efficiency:
                import hashlib
                small = screenshot.resize((64, 64))
                screenshot_hash = hashlib.md5(small.tobytes()).hexdigest()
                send_mode = self._efficiency.should_send_screenshot(
                    screenshot_hash, str(hash(str(screen_state.a11y_tree)))
                )
            else:
                send_mode = "full"

            # Step 3: Grounding enhancement
            enhanced_context = await self._enhance_grounding(screenshot, task)

            # Step 4: Safety check (screen)
            if self._safety:
                screen_safety = self._safety.check_screen(screen_state)
                if screen_safety.level.value == "blocked":
                    logger.warning("Screen safety blocked: %s", screen_safety.reason)

            # Step 5: Planning enhancement (inject subtasks + knowledge + lessons)
            planning_text = ""
            if self._planning and step_count == 0:
                planning_text = self._planning.enhance_prompt(
                    task, screen_state, memory_context
                )
                subtasks = self._planning._decompose_task(task, app_name, None)

                # Optimize plan with efficiency engine
                if self._efficiency and subtasks:
                    app_knowledge = None
                    if self._planning and self._planning._knowledge:
                        app_knowledge = self._planning._knowledge.get_knowledge(app_name)
                    subtasks, opt_result = self._efficiency.optimize_plan(
                        subtasks, app_knowledge
                    )
                    if opt_result.methods_applied:
                        logger.info(
                            "Plan optimized: %d→%d steps (%s)",
                            opt_result.original_steps,
                            opt_result.optimized_steps,
                            ", ".join(opt_result.methods_applied),
                        )

            # Build enhanced content for Claude
            content = self._build_message_content(
                screenshot, enhanced_context, planning_text, send_mode
            )

            if step_count == 0:
                messages[0]["content"].extend(content)
            else:
                messages.append({"role": "user", "content": content})

            # Step 6: Call Claude API
            response = await self._call_claude(system_prompt, messages)

            assistant_content = response.content
            messages.append({"role": "assistant", "content": assistant_content})

            # Extract action from response
            action = self._parse_action(assistant_content)

            if action is None:
                text_response = self._extract_text(assistant_content)
                if self._is_task_complete(text_response):
                    break
                step_count += 1
                continue

            # Step 7: Safety check (action) + emergency stop
            if self._safety:
                emergency = self._safety.check_emergency(action)
                if emergency.level.value == "blocked":
                    logger.warning("Emergency stop: %s", emergency.reason)
                    break
                action_safety = self._safety.check_with_permission(action)
                if action_safety.level.value == "blocked":
                    logger.warning("Action blocked: %s", action_safety.reason)
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

            # Step 8: Execute with enhancements
            before_screenshot = np.array(screenshot)
            action_result = await self._execute_action(action, enhanced_context)

            # Step 9: Verify result + Reflection
            after_screenshot_img = await self._take_screenshot()
            after_screenshot = np.array(after_screenshot_img)
            verification = await self._verify_action(
                before_screenshot, after_screenshot, screen_state, action
            )

            # Build step record
            step_record = StepRecord(
                num=step_count + 1,
                action=action,
                success=verification.success if verification else action_result.success,
                verification=verification,
                timestamp=time.time(),
            )
            step_records.append(step_record)

            # Working memory update
            if self._memory:
                self._memory.working.add_step(step_record)

            # Checkpoint on success
            if self._checkpoint and step_record.success:
                await self._checkpoint.save_checkpoint(
                    screenshot_hash=screenshot_hash,
                    a11y_tree_hash=str(hash(str(screen_state.a11y_tree))),
                    step_num=step_count + 1,
                    subtask_index=completed_subtasks,
                    action_history=[sr.action for sr in step_records],
                )

            # Reflection (action-level)
            if self._reflection:
                action_ref = await self._reflection.reflect_action(step_record)
                if action_ref.decision.value == "retry" and action_ref.retry_action:
                    logger.info("Reflection: retrying with adjusted action")
                    try:
                        await self._raw_execute(action_ref.retry_action)
                    except Exception as e:
                        logger.warning("Reflection retry failed: %s", e)

                # Trajectory reflection every 3 steps
                if len(step_records) >= 3 and len(step_records) % 3 == 0:
                    traj_ref = await self._reflection.reflect_trajectory(
                        step_records[-3:], task
                    )
                    if traj_ref.decision.value in ("strategy_change", "replan"):
                        logger.warning("Trajectory reflection: strategy change needed")

            # Build result message
            result_text = self._build_result_text(action_result, verification)
            messages.append({
                "role": "user",
                "content": [{"type": "text", "text": result_text}],
            })

            step_count += 1
            logger.info(
                "Step %d: action=%s success=%s verification=%s",
                step_count, action.type,
                action_result.success,
                verification.success if verification else "n/a",
            )

        # Post-loop: Step 10 — Memory update (episodic + reflexion)
        elapsed = time.monotonic() - start_time
        task_success = self._is_task_complete(
            self._extract_text(messages[-1].get("content", "")) if messages else ""
        )

        if self._memory:
            episode = Episode(
                id=episode_id,
                task=task,
                app=app_name,
                success=task_success,
                steps=step_records,
                subtasks=subtasks,
                completed_subtasks=completed_subtasks,
                start_time=start_time,
                end_time=time.time(),
            )
            try:
                await self._memory.learn(episode)
            except Exception as e:
                logger.warning("Failed to store episode: %s", e)

        if elapsed > timeout:
            return TaskResult(
                success=False, task=task, steps_taken=step_count,
                total_time_seconds=elapsed, error="Task timed out",
            )

        if step_count >= max_steps:
            return TaskResult(
                success=False, task=task, steps_taken=step_count,
                total_time_seconds=elapsed, error=f"Max steps ({max_steps}) reached",
            )

        return TaskResult(
            success=True, task=task, steps_taken=step_count,
            total_time_seconds=elapsed,
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

        # Use efficiency cache if available
        if self._efficiency:
            import hashlib
            small = screenshot.resize((64, 64))
            cache_key = hashlib.md5(small.tobytes()).hexdigest()
            cached = await self._efficiency.get_cached_state(
                cache_key,
                lambda: self._grounding.enhance(screenshot, task_context),
            )
            if cached:
                return EnhancedContext(
                    elements=cached.elements,
                    element_description=cached.element_description,
                )

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
        api_messages = self._prepare_messages(messages)

        response = await self.client.messages.create(
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
        """Prepare messages for the Claude API."""
        prepared = []
        for msg in messages:
            if isinstance(msg.get("content"), list):
                prepared.append(msg)
            elif isinstance(msg.get("content"), str):
                prepared.append({
                    "role": msg["role"],
                    "content": [{"type": "text", "text": msg["content"]}],
                })
            else:
                prepared.append(msg)
        return prepared

    def _build_system_prompt(
        self, task: str, memory_context: MemoryContext | None = None
    ) -> str:
        parts = [
            "You are a computer use agent. You can see the screen and interact with it "
            "to complete tasks. Use the computer tool to take actions.\n\n"
            "Guidelines:\n"
            "- Click on the exact center of UI elements\n"
            "- Use keyboard shortcuts when possible for efficiency\n"
            "- Verify each action's result before proceeding\n"
            "- If an action fails, try alternative approaches\n"
            "- Report completion when the task is done\n"
        ]

        # Inject memory context (lessons + past episodes)
        if memory_context and (memory_context.lessons or memory_context.similar_episodes):
            parts.append("\n" + memory_context.to_prompt_text())

        return "\n".join(parts)

    def _build_message_content(
        self,
        screenshot: Image.Image,
        context: EnhancedContext,
        planning_text: str = "",
        send_mode: str = "full",
    ) -> list[dict]:
        """Build message content with screenshot and enhanced context."""
        content: list[dict] = []

        # Screenshot (respect efficiency send_mode)
        if send_mode != "skip":
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

        # Planning context (only on first step)
        if planning_text:
            content.append({
                "type": "text",
                "text": f"[CUE Planning]\n{planning_text}",
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

        return Action(type=action_type, coordinate=coord_tuple, text=text)

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
        try:
            await self._raw_execute(action)
            return ActionResult(success=True, action_type=action.type)
        except Exception as e:
            return ActionResult(success=False, action_type=action.type, error=str(e))

    async def _raw_execute(self, action: Action) -> bool:
        """Execute a raw action on the environment. Returns True on success."""
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
            pass

        elif action.type == "wait":
            duration = (action.duration_ms or 1000) / 1000.0
            await asyncio.sleep(duration)

        else:
            logger.warning("Unknown action type: %s", action.type)
            return False

        return True

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
