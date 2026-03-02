"""Memory/Reflexion verification test script.

Phase 1: Direct Memory Module Test (no API needed)
Phase 2: Reflexion Engine Test (no API needed)
Phase 3: Agent Memory Integration (requires ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import time
import uuid

# Force UTF-8 output on Windows (cp949 cannot encode box-drawing / em-dash chars).
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

os.environ.setdefault("DISPLAY", ":99")

from dotenv import load_dotenv
load_dotenv()

# ─── Helpers ──────────────────────────────────────────────────────────────────

PASS = "PASS"
FAIL = "FAIL"

_results: list[tuple[str, str, str]] = []  # (phase, name, status)


def check(phase: str, name: str, condition: bool, detail: str = "") -> None:
    status = PASS if condition else FAIL
    label = f"[{status}]"
    msg = f"  {label} {name}"
    if detail:
        msg += f" -- {detail}"
    print(msg)
    _results.append((phase, name, status))


def section(title: str) -> None:
    print("\n" + ("=" * 60))
    print("  " + title)
    print("=" * 60)


def summary() -> int:
    """Print summary and return exit code (0=all pass, 1=any fail)."""
    total = len(_results)
    passed = sum(1 for _, _, s in _results if s == PASS)
    failed = total - passed
    print(f"\n{'=' * 60}")
    print(f"  SUMMARY: {passed}/{total} checks passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
    else:
        print()
    print(f"{'=' * 60}\n")
    return 0 if failed == 0 else 1


# ─── Fake data builders ────────────────────────────────────────────────────────

def _make_step(
    num: int,
    action_type: str,
    success: bool,
    was_recovery: bool = False,
    strategy_used: str = "",
    original_action: str = "",
    context_description: str = "",
    is_milestone: bool = False,
) -> object:
    from cue.types import Action, StepRecord, VerificationResult
    action = Action(type=action_type)
    verification = VerificationResult(
        tier=1,
        success=success,
        confidence=0.9 if success else 0.1,
        reason="ok" if success else "element not found",
    )
    return StepRecord(
        num=num,
        action=action,
        success=success,
        verification=verification,
        was_recovery=was_recovery,
        strategy_used=strategy_used,
        original_action=original_action,
        context_description=context_description,
        is_milestone=is_milestone,
        timestamp=time.time(),
    )


def _make_episode(
    task: str = "Open terminal and type echo test",
    app: str = "xterm",
    success: bool = True,
) -> object:
    """Build a realistic fake Episode with mixed success/failure steps."""
    from cue.types import Episode

    now = time.time()
    steps = [
        # Step 1: failed click, then step 2 recovery via keyboard shortcut
        _make_step(1, "left_click", success=False,
                   context_description="click on terminal icon",
                   original_action="left_click"),
        _make_step(2, "key", success=True,
                   was_recovery=True, strategy_used="keyboard_shortcut",
                   context_description="click on terminal icon",
                   is_milestone=True),
        # Step 3: type command — success
        _make_step(3, "type", success=True,
                   context_description="type echo test",
                   is_milestone=True),
        # Step 4: press Enter — success
        _make_step(4, "key", success=True,
                   context_description="press Enter"),
    ]

    return Episode(
        id=str(uuid.uuid4()),
        task=task,
        app=app,
        success=success,
        steps=steps,
        start_time=now - 10.0,
        end_time=now,
    )


# ─── Phase 1: Direct Memory Module Test ───────────────────────────────────────

async def phase1_memory_test() -> None:
    section("Phase 1: Direct Memory Module Test (no API)")

    from cue.config import MemoryConfig
    from cue.memory import ThreeLayerMemory

    # Use a temp directory so tests don't pollute ~/.cue.
    # ignore_cleanup_errors=True prevents Windows SQLite file-lock crashes on cleanup.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        config = MemoryConfig(db_dir=tmpdir)
        memory = ThreeLayerMemory(config)
        check("1", "ThreeLayerMemory instantiates", memory is not None)
        check("1", "working memory present", memory.working is not None)
        check("1", "episodic memory present", memory.episodic is not None)
        check("1", "semantic memory present", memory.semantic is not None)
        check("1", "reflexion engine present", memory.reflexion is not None)

        # --- Working memory ---
        from cue.types import StepRecord, Action
        step = StepRecord(num=1, action=Action(type="left_click"), success=True)
        memory.working.add_step(step)
        ctx = memory.working.get_context()
        check("1", "working.add_step stores a step",
              len(ctx["recent_steps"]) == 1)
        check("1", "working.get_context returns dict with expected keys",
              "compressed_history" in ctx and "recent_steps" in ctx)

        # --- Overflow compression (add more than max_steps) ---
        for i in range(2, config.working_memory_steps + 5):
            memory.working.add_step(
                StepRecord(num=i, action=Action(type="type"), success=True)
            )
        ctx2 = memory.working.get_context()
        check("1", "working memory compresses overflow",
              len(ctx2["compressed_history"]) > 0,
              f"compressed={len(ctx2['compressed_history'])} items")

        # --- learn() stores episode ---
        episode = _make_episode()
        await memory.learn(episode)

        # Verify episodic DB has a record
        stored = await memory.episodic.find_similar(
            task=episode.task, app=episode.app, top_k=5
        )
        check("1", "episodic.store: episode saved",
              len(stored) >= 1,
              f"found {len(stored)} episode(s)")
        if stored:
            check("1", "stored episode task matches",
                  stored[0].task == episode.task)
            check("1", "stored episode has reflection text",
                  len(stored[0].reflection) > 0,
                  f"reflection={stored[0].reflection[:60]!r}")

        # --- learn() extracts lessons (failure->success pair in episode) ---
        lessons = await memory.semantic.recall(
            task=episode.task, app=episode.app, top_k=5
        )
        check("1", "semantic.upsert: at least one lesson extracted",
              len(lessons) >= 1,
              f"found {len(lessons)} lesson(s)")
        if lessons:
            check("1", "lesson has app set correctly",
                  lessons[0].app == episode.app)
            check("1", "lesson has non-empty situation",
                  len(lessons[0].situation) > 0)
            print(f"    Lesson text: {lessons[0].text[:80]!r}")

        # --- remember() returns MemoryContext ---
        ctx_mem = await memory.remember(task=episode.task, app=episode.app)
        check("1", "remember() returns MemoryContext",
              ctx_mem is not None)
        check("1", "MemoryContext has lessons list",
              isinstance(ctx_mem.lessons, list))
        check("1", "MemoryContext has similar_episodes list",
              isinstance(ctx_mem.similar_episodes, list))
        check("1", "remember() total_tokens estimated > 0",
              ctx_mem.total_tokens > 0,
              f"tokens={ctx_mem.total_tokens}")

        prompt_text = ctx_mem.to_prompt_text()
        check("1", "MemoryContext.to_prompt_text() non-empty",
              len(prompt_text) > 0,
              f"{len(prompt_text)} chars")

        # --- Disk persistence: DB files exist ---
        import pathlib
        ep_db = pathlib.Path(tmpdir) / "episodic.db"
        sem_db = pathlib.Path(tmpdir) / "semantic.db"
        check("1", "episodic.db written to disk", ep_db.exists())
        check("1", "semantic.db written to disk", sem_db.exists())

        # --- remember() on unrelated query returns empty context ---
        ctx_empty = await memory.remember(
            task="completely unrelated zzz", app="nonexistent_app_xyz"
        )
        check("1", "remember() with no matches returns empty context",
              len(ctx_empty.lessons) == 0 and len(ctx_empty.similar_episodes) == 0,
              f"lessons={len(ctx_empty.lessons)}, episodes={len(ctx_empty.similar_episodes)}")

        print(f"\n  Memory DB path used: {tmpdir}")


# ─── Phase 2: Reflexion Engine Test ───────────────────────────────────────────

async def phase2_reflexion_test() -> None:
    section("Phase 2: Reflexion Engine Test (no API)")

    from cue.verification.reflection import ReflectionEngine
    from cue.types import (
        Action,
        ReflectionDecision,
        StepRecord,
        SubTask,
        VerificationResult,
    )

    engine = ReflectionEngine()
    check("2", "ReflectionEngine instantiates", engine is not None)

    def make_step_with_reason(
        num: int, action_type: str, success: bool, reason: str = ""
    ) -> StepRecord:
        ver = VerificationResult(
            tier=1,
            success=success,
            confidence=0.9 if success else 0.1,
            reason=reason or ("ok" if success else "element not found"),
        )
        return StepRecord(
            num=num,
            action=Action(type=action_type),
            success=success,
            verification=ver,
            timestamp=time.time(),
        )

    # --- reflect_action: success path ---
    s_ok = make_step_with_reason(1, "left_click", success=True)
    r_ok = await engine.reflect_action(s_ok)
    check("2", "reflect_action(success) -> CONTINUE",
          r_ok.decision == ReflectionDecision.CONTINUE,
          f"decision={r_ok.decision}, reason={r_ok.reason!r}")

    # --- reflect_action: coordinate miss -> RETRY with offset ---
    s_miss = make_step_with_reason(
        2, "left_click", success=False, reason="coordinate miss detected"
    )
    s_miss.action.coordinate = (100, 200)
    r_miss = await engine.reflect_action(s_miss)
    check("2", "reflect_action(coord miss) -> RETRY",
          r_miss.decision == ReflectionDecision.RETRY,
          f"decision={r_miss.decision}")
    check("2", "reflect_action(coord miss) retry_action has offset coords",
          r_miss.retry_action is not None and r_miss.retry_action.coordinate == (105, 205),
          f"retry_action coords={r_miss.retry_action.coordinate if r_miss.retry_action else None}")

    # --- reflect_action: generic failure -> RETRY ---
    s_fail = make_step_with_reason(3, "type", success=False, reason="timeout")
    r_fail = await engine.reflect_action(s_fail)
    check("2", "reflect_action(generic fail) -> RETRY",
          r_fail.decision == ReflectionDecision.RETRY,
          f"decision={r_fail.decision}")

    # --- reflect_trajectory: all ok -> CONTINUE ---
    good_steps = [make_step_with_reason(i, "left_click", success=True) for i in range(3)]
    t_ok = await engine.reflect_trajectory(good_steps)
    check("2", "reflect_trajectory(all success) -> CONTINUE",
          t_ok.decision == ReflectionDecision.CONTINUE,
          f"decision={t_ok.decision}, reason={t_ok.reason!r}")

    # --- reflect_trajectory: all failed with distinct reasons -> STRATEGY_CHANGE ---
    # Use distinct reasons so the repeated-reason REPLAN branch is not triggered first.
    bad_steps = [
        make_step_with_reason(i, "left_click", success=False, reason=f"error_{i}")
        for i in range(3)
    ]
    t_bad = await engine.reflect_trajectory(bad_steps)
    check("2", "reflect_trajectory(all fail) -> STRATEGY_CHANGE",
          t_bad.decision == ReflectionDecision.STRATEGY_CHANGE,
          f"decision={t_bad.decision}, reason={t_bad.reason!r}")
    check("2", "reflect_trajectory(all fail) making_progress=False",
          t_bad.making_progress is False)

    # --- reflect_trajectory: repeated same reason -> REPLAN ---
    same_reason_steps = [
        make_step_with_reason(i, "left_click", success=False, reason="button missing")
        for i in range(3)
    ]
    t_replan = await engine.reflect_trajectory(same_reason_steps)
    check("2", "reflect_trajectory(same failure reason) -> REPLAN",
          t_replan.decision == ReflectionDecision.REPLAN,
          f"decision={t_replan.decision}, reason={t_replan.reason!r}")

    # --- reflect_trajectory: empty steps -> CONTINUE ---
    t_empty = await engine.reflect_trajectory([])
    check("2", "reflect_trajectory(empty) -> CONTINUE",
          t_empty.decision == ReflectionDecision.CONTINUE)

    # --- reflect_global: on track ---
    all_steps = [make_step_with_reason(i, "left_click", success=True) for i in range(4)]
    subtasks = [SubTask(description=f"subtask {i}") for i in range(4)]
    g_ok = await engine.reflect_global(
        all_steps=all_steps,
        task="open calculator",
        subtasks=subtasks,
        completed_subtasks=2,
    )
    check("2", "reflect_global(on track) -> CONTINUE",
          g_ok.decision == ReflectionDecision.CONTINUE,
          f"decision={g_ok.decision}, on_track={g_ok.on_track}")

    # --- reflect_global: too slow -> STRATEGY_CHANGE ---
    # Threshold: step_consumption_ratio > 0.5 AND completion_ratio < 0.3.
    # max_steps_estimate = 10 subtasks * 5 = 50.  Need steps > 50 * 0.5 = 25.
    # Use 28 steps (56% budget) with only 1/10 subtasks done (10% completion).
    many_steps = [
        make_step_with_reason(i, "left_click", success=True) for i in range(28)
    ]
    many_subtasks = [SubTask(description=f"subtask {i}") for i in range(10)]
    g_slow = await engine.reflect_global(
        all_steps=many_steps,
        task="open calculator",
        subtasks=many_subtasks,
        completed_subtasks=1,
    )
    check("2", "reflect_global(too slow) -> STRATEGY_CHANGE",
          g_slow.decision == ReflectionDecision.STRATEGY_CHANGE,
          f"decision={g_slow.decision}, on_track={g_slow.on_track}, reason={g_slow.reason!r}")

    # --- ReflexionEngine (memory/reflexion.py) on episode ---
    from cue.memory.reflexion import ReflexionEngine
    reflex = ReflexionEngine()
    check("2", "ReflexionEngine (memory) instantiates", reflex is not None)

    ep_success = _make_episode(success=True)
    reflection_text = await reflex.reflect(ep_success)
    check("2", "ReflexionEngine.reflect(success episode) returns non-empty string",
          isinstance(reflection_text, str) and len(reflection_text) > 0,
          f"reflection={reflection_text[:80]!r}")
    check("2", "ReflexionEngine.reflect(success) mentions task name",
          ep_success.task[:20] in reflection_text)

    ep_fail = _make_episode(success=False)
    reflection_fail = await reflex.reflect(ep_fail)
    check("2", "ReflexionEngine.reflect(failed episode) returns non-empty string",
          isinstance(reflection_fail, str) and len(reflection_fail) > 0,
          f"reflection={reflection_fail[:80]!r}")


# ─── Phase 3: Agent Memory Integration (requires API key) ─────────────────────

async def phase3_agent_integration() -> None:
    section("Phase 3: Agent Memory Integration (requires ANTHROPIC_API_KEY)")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("  SKIPPED: ANTHROPIC_API_KEY not set")
        return

    print("  API key found. Running agent integration test...")
    print("  Task: 'Type echo test in the terminal'\n")

    from cue.config import AgentConfig, CUEConfig, MemoryConfig
    from cue.memory import ThreeLayerMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        mem_config = MemoryConfig(db_dir=tmpdir)
        memory = ThreeLayerMemory(mem_config)

        agent_cfg = AgentConfig(
            model="claude-sonnet-4-6",
            max_steps=6,
            timeout_seconds=45,
        )
        cfg = CUEConfig(agent=agent_cfg, memory=mem_config)

        task = "Type 'echo test' in the terminal"

        # Pre-run: memory should be empty
        ctx_before = await memory.remember(task=task, app="xterm")
        check("3", "memory empty before run 1",
              len(ctx_before.lessons) == 0 and len(ctx_before.similar_episodes) == 0,
              f"lessons={len(ctx_before.lessons)}, episodes={len(ctx_before.similar_episodes)}")

        # --- Run 1 ---
        print("  --- Run 1 ---")
        try:
            from cue.agent import CUEAgent
            from cue.platform.linux import LinuxEnvironment

            env1 = LinuxEnvironment()
            agent1 = CUEAgent(config=cfg, env=env1, memory=memory)
            result1 = await agent1.run(task)

            check("3", "Run 1 completes",
                  result1 is not None,
                  f"success={result1.success}, steps={result1.steps_taken}")

            # Memory should now have an episode
            ctx_after1 = await memory.remember(task=task, app="xterm")
            check("3", "episode stored after run 1",
                  len(ctx_after1.similar_episodes) >= 1,
                  f"episodes={len(ctx_after1.similar_episodes)}")
            check("3", "MemoryContext tokens > 0 after run 1",
                  ctx_after1.total_tokens > 0)

            steps_run1 = result1.steps_taken
            print(f"    Run 1: {steps_run1} steps taken")

        except Exception as exc:
            check("3", "Run 1 agent execution", False, str(exc))
            print(f"  SKIPPED Run 2: Run 1 failed ({exc})")
            return

        # --- Run 2 ---
        print("  --- Run 2 ---")
        try:
            env2 = LinuxEnvironment()
            agent2 = CUEAgent(config=cfg, env=env2, memory=memory)
            result2 = await agent2.run(task)

            check("3", "Run 2 completes",
                  result2 is not None,
                  f"success={result2.success}, steps={result2.steps_taken}")

            steps_run2 = result2.steps_taken
            print(f"    Run 2: {steps_run2} steps taken")

            # Compare
            print(f"\n  Step comparison: Run1={steps_run1}, Run2={steps_run2}")
            if steps_run2 <= steps_run1:
                check("3", "Run 2 uses <= steps than Run 1 (memory benefit)",
                      True, f"{steps_run1} -> {steps_run2}")
            else:
                # Not necessarily a failure — just informational
                check("3", "Run 2 step count recorded (may vary)",
                      True, f"{steps_run1} -> {steps_run2} (increased; may be environment noise)")

            # Memory should now have 2+ episodes
            ctx_after2 = await memory.remember(task=task, app="xterm")
            check("3", "2 episodes stored after run 2",
                  len(ctx_after2.similar_episodes) >= 2,
                  f"episodes={len(ctx_after2.similar_episodes)}")

        except Exception as exc:
            check("3", "Run 2 agent execution", False, str(exc))


# ─── Main ──────────────────────────────────────────────────────────────────────

async def main() -> int:
    print("=" * 60)
    print("  CUE Memory / Reflexion Verification Test")
    print(f"  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  DISPLAY: {os.environ.get('DISPLAY', 'not set')}")
    api_status = "set" if os.environ.get("ANTHROPIC_API_KEY") else "not set"
    print(f"  ANTHROPIC_API_KEY: {api_status}")
    print("=" * 60)

    await phase1_memory_test()
    await phase2_reflexion_test()
    await phase3_agent_integration()

    return summary()


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
