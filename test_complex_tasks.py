"""Complex task tests for CUE Agent on VPS with Xvfb :99 + openbox WM.

Run with:
    python3 test_complex_tasks.py

Requires:
    - DISPLAY=:99 Xvfb running
    - ANTHROPIC_API_KEY in .env
    - mousepad, xterm, xdotool installed on VPS
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import time

os.environ["DISPLAY"] = ":99"
sys.path.insert(0, "/opt/cue_enhancer")

from dotenv import load_dotenv

load_dotenv("/opt/cue_enhancer/.env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)

# ── helpers ────────────────────────────────────────────────────────────────

PASS = "PASSED"
FAIL = "FAILED"


def _print_banner(title: str) -> None:
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def _run_shell(cmd: str, timeout: int = 10) -> tuple[int, str, str]:
    """Run a shell command; return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "DISPLAY": ":99"},
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _make_agent(max_steps: int = 12, timeout: int = 90):
    """Build a CUEAgent with task-appropriate settings."""
    from cue.agent import CUEAgent
    from cue.config import CUEConfig

    config = CUEConfig.load()
    config.agent.max_steps = max_steps
    config.agent.timeout_seconds = timeout
    config.agent.screenshot_width = 1920
    config.agent.screenshot_height = 1080
    config.agent.model = "claude-sonnet-4-6"
    return CUEAgent(config)


# ── Task 1: Text file editing with mousepad ────────────────────────────────

async def task1_mousepad_edit() -> tuple[str, float, str]:
    """
    Setup   : write a file, open it in mousepad.
    Execute : CUE selects all text and types new content.
    Verify  : read the file back and check content.
    """
    task_name = "Task 1: mousepad text editing"
    test_file = "/tmp/cue_test_edit.txt"
    expected_text = "Hello from CUE Agent"

    _print_banner(task_name)
    t0 = time.monotonic()

    # ── Setup ──────────────────────────────────────────────────────────────
    print("[setup] writing initial content to", test_file)
    with open(test_file, "w") as fh:
        fh.write("Original content that should be replaced.\n")

    print("[setup] launching mousepad")
    subprocess.Popen(
        ["mousepad", test_file],
        env={**os.environ, "DISPLAY": ":99"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await asyncio.sleep(3)  # wait for GUI to appear

    # ── Execute ────────────────────────────────────────────────────────────
    agent = _make_agent(max_steps=12, timeout=90)
    task_prompt = (
        "In the mousepad text editor window that is open, "
        "select all the text (Ctrl+A), then type 'Hello from CUE Agent'. "
        "After typing, save the file with Ctrl+S. "
        "The task is complete when the file is saved."
    )
    print("[execute] running CUE agent")
    try:
        result = await agent.run(task_prompt)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        msg = f"Agent raised exception: {exc}"
        print(f"[execute] {msg}")
        return FAIL, elapsed, msg

    await asyncio.sleep(1)  # let mousepad flush the save

    # ── Verify ─────────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t0
    try:
        with open(test_file) as fh:
            content = fh.read().strip()
    except OSError as exc:
        return FAIL, elapsed, f"Could not read {test_file}: {exc}"

    print(f"[verify] file content: {content!r}")

    if expected_text in content:
        print(f"[verify] content matches expected text")
        return PASS, elapsed, f"File contains '{expected_text}'"
    else:
        return (
            FAIL,
            elapsed,
            f"Expected '{expected_text}' in file, got: {content!r}. "
            f"Agent result: success={result.success} steps={result.steps_taken}",
        )


# ── Task 2: Terminal multi-step ─────────────────────────────────────────────

async def task2_terminal_multistep() -> tuple[str, float, str]:
    """
    Execute : CUE creates a directory, cd into it, writes a file.
    Verify  : check /root/cue_test/hello.txt exists with correct content.
    """
    task_name = "Task 2: terminal multi-step (mkdir + cd + write)"
    target_dir = "/root/cue_test"
    target_file = "/root/cue_test/hello.txt"
    expected_content = "CUE was here"

    _print_banner(task_name)
    t0 = time.monotonic()

    # ── Setup: clean prior run ──────────────────────────────────────────────
    _run_shell(f"rm -rf {target_dir}")

    # ── Execute ────────────────────────────────────────────────────────────
    agent = _make_agent(max_steps=12, timeout=90)
    task_prompt = (
        "In the terminal window, run these commands in order:\n"
        "1. mkdir -p /root/cue_test\n"
        "2. cd /root/cue_test\n"
        "3. echo 'CUE was here' > hello.txt\n"
        "Type each command and press Enter after each one. "
        "The task is complete when all three commands have been executed."
    )
    print("[execute] running CUE agent")
    try:
        result = await agent.run(task_prompt)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        msg = f"Agent raised exception: {exc}"
        print(f"[execute] {msg}")
        return FAIL, elapsed, msg

    await asyncio.sleep(1)

    # ── Verify ─────────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t0
    rc, stdout, _ = _run_shell(f"cat {target_file}")
    print(f"[verify] cat {target_file} -> rc={rc} stdout={stdout!r}")

    if rc == 0 and expected_content in stdout:
        return PASS, elapsed, f"{target_file} contains '{expected_content}'"
    else:
        return (
            FAIL,
            elapsed,
            f"{target_file} not found or wrong content. "
            f"cat rc={rc} stdout={stdout!r}. "
            f"Agent: success={result.success} steps={result.steps_taken}",
        )


# ── Task 3: Window management ───────────────────────────────────────────────

async def task3_window_management() -> tuple[str, float, str]:
    """
    Execute : CUE clicks the terminal, types the xterm command, presses Enter.
    Verify  : xdotool search finds a window titled 'TestWindow'.
    """
    task_name = "Task 3: window management (open new xterm)"
    _print_banner(task_name)
    t0 = time.monotonic()

    # ── Execute ────────────────────────────────────────────────────────────
    agent = _make_agent(max_steps=12, timeout=90)
    task_prompt = (
        "Click on the terminal window to make sure it has focus, "
        "then type the command: xterm -title TestWindow &\n"
        "and press Enter to run it. "
        "The task is complete when you have pressed Enter after typing the command."
    )
    print("[execute] running CUE agent")
    try:
        result = await agent.run(task_prompt)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        msg = f"Agent raised exception: {exc}"
        print(f"[execute] {msg}")
        return FAIL, elapsed, msg

    await asyncio.sleep(3)  # wait for xterm to open

    # ── Verify ─────────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t0
    rc, stdout, stderr = _run_shell("xdotool search --name TestWindow", timeout=10)
    print(f"[verify] xdotool search --name TestWindow -> rc={rc} stdout={stdout!r}")

    if rc == 0 and stdout.strip():
        return PASS, elapsed, f"TestWindow found (xdotool wid={stdout.strip()!r})"
    else:
        return (
            FAIL,
            elapsed,
            f"TestWindow not found via xdotool (rc={rc}, stderr={stderr!r}). "
            f"Agent: success={result.success} steps={result.steps_taken}",
        )


# ── Main runner ────────────────────────────────────────────────────────────

async def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print("=" * 60)
    print("CUE Agent — Complex Task Tests")
    print(f"Time    : {time.strftime('%H:%M:%S')}")
    print(f"Display : {os.environ.get('DISPLAY', 'not set')}")
    print(f"API Key : {api_key[:8]}..." if api_key else "API Key : MISSING")
    print("=" * 60)

    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set. Aborting.")
        sys.exit(1)

    tasks = [
        ("Task 1: mousepad edit", task1_mousepad_edit),
        ("Task 2: terminal multi-step", task2_terminal_multistep),
        ("Task 3: window management", task3_window_management),
    ]

    results: list[tuple[str, str, float, str]] = []

    for label, coro_fn in tasks:
        try:
            status, elapsed, detail = await coro_fn()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            status, elapsed, detail = FAIL, 0.0, f"Unhandled exception: {exc}"

        results.append((label, status, elapsed, detail))
        symbol = "OK" if status == PASS else "!!"
        print(f"\n[{symbol}] {label}: {status} ({elapsed:.1f}s)")
        print(f"     {detail}")

    # ── Summary ────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    passed = sum(1 for _, s, _, _ in results if s == PASS)
    total = len(results)
    for label, status, elapsed, detail in results:
        mark = "PASS" if status == PASS else "FAIL"
        print(f"  [{mark}] {label} ({elapsed:.1f}s)")
    print("-" * 60)
    print(f"  {passed}/{total} tasks passed")
    print("=" * 60)

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
