"""Mini benchmark: CUE-enhanced agent vs baseline on simple xterm tasks.

Run with:  python3 test_benchmark_mini.py

Requires:
- DISPLAY=:99 (Xvfb running) or set in environment
- ANTHROPIC_API_KEY in .env or environment
- xterm running on the display
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Load .env before importing anthropic ──────────────────────────────────────
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())

# Ensure DISPLAY is set for Xvfb
os.environ.setdefault("DISPLAY", ":99")

# ── Task definitions ───────────────────────────────────────────────────────────

TASKS = [
    {
        "id": "mini-001",
        "description": "Type 'echo hello' in the terminal and press Enter",
    },
    {
        "id": "mini-002",
        "description": "Click on the terminal window and type 'pwd'",
    },
    {
        "id": "mini-003",
        "description": "Type 'date' in the terminal and press Enter",
    },
]

MODEL = "claude-sonnet-4-6"
MAX_STEPS = 8
TIMEOUT_SECONDS = 45
INTER_TASK_DELAY = 3.0   # seconds between tasks to avoid rate limits
RETRY_DELAY = 60.0       # seconds to wait after a 429 error


# ── Result container ───────────────────────────────────────────────────────────

@dataclass
class RunResult:
    task_id: str
    description: str
    mode: str          # "cue" or "baseline"
    success: bool
    steps_taken: int
    elapsed: float
    error: str = ""


# ── CUEConfig builders ─────────────────────────────────────────────────────────

def _make_cue_config() -> Any:
    """Return a CUEConfig with grounding, planning, and verification ON (full)."""
    from cue.config import CUEConfig, EnhancerLevel
    cfg = CUEConfig()
    cfg.grounding.level = EnhancerLevel.FULL
    cfg.planning.level = EnhancerLevel.FULL
    cfg.verification.level = EnhancerLevel.FULL
    cfg.execution.level = EnhancerLevel.FULL
    cfg.safety.level = EnhancerLevel.FULL
    cfg.memory.level = EnhancerLevel.FULL
    cfg.efficiency.level = EnhancerLevel.FULL
    cfg.agent.max_steps = MAX_STEPS
    cfg.agent.timeout_seconds = TIMEOUT_SECONDS
    cfg.agent.model = MODEL
    return cfg


def _make_baseline_config() -> Any:
    """Return a CUEConfig with all enhancement modules OFF."""
    from cue.config import CUEConfig, EnhancerLevel
    cfg = CUEConfig()
    cfg.grounding.level = EnhancerLevel.OFF
    cfg.planning.level = EnhancerLevel.OFF
    cfg.verification.level = EnhancerLevel.OFF
    cfg.execution.level = EnhancerLevel.OFF
    cfg.safety.level = EnhancerLevel.OFF
    cfg.memory.level = EnhancerLevel.OFF
    cfg.efficiency.level = EnhancerLevel.OFF
    cfg.agent.max_steps = MAX_STEPS
    cfg.agent.timeout_seconds = TIMEOUT_SECONDS
    cfg.agent.model = MODEL
    return cfg


# ── Single task runner ─────────────────────────────────────────────────────────

async def run_task(task: dict, config: Any, mode: str) -> RunResult:
    """Run a single task with the given config. Returns a RunResult."""
    from cue.agent import CUEAgent
    from cue.types import TaskResult

    task_id = task["id"]
    desc = task["description"]
    print(f"  [{mode}] {task_id}: {desc[:55]}...")

    agent = CUEAgent(config=config)
    start = time.monotonic()

    try:
        result: TaskResult = await asyncio.wait_for(
            agent.run(desc),
            timeout=TIMEOUT_SECONDS + 5,  # outer safety margin
        )
        elapsed = time.monotonic() - start
        return RunResult(
            task_id=task_id,
            description=desc,
            mode=mode,
            success=result.success,
            steps_taken=result.steps_taken,
            elapsed=elapsed,
            error=result.error or "",
        )

    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        print(f"    -> TIMEOUT after {elapsed:.1f}s")
        return RunResult(
            task_id=task_id,
            description=desc,
            mode=mode,
            success=False,
            steps_taken=0,
            elapsed=elapsed,
            error="outer timeout",
        )

    except Exception as exc:
        elapsed = time.monotonic() - start
        err_str = str(exc)

        # Rate limit: back off and return a failure so the caller can retry or skip
        if "429" in err_str or "rate_limit" in err_str.lower() or "overloaded" in err_str.lower():
            print(f"    -> RATE LIMIT (429). Waiting {RETRY_DELAY:.0f}s before continuing...")
            await asyncio.sleep(RETRY_DELAY)

        print(f"    -> ERROR: {err_str[:80]}")
        return RunResult(
            task_id=task_id,
            description=desc,
            mode=mode,
            success=False,
            steps_taken=0,
            elapsed=elapsed,
            error=err_str[:120],
        )


# ── Benchmark runner ───────────────────────────────────────────────────────────

async def run_benchmark() -> tuple[list[RunResult], list[RunResult]]:
    """Run all tasks in CUE mode then baseline mode. Returns (cue_results, baseline_results)."""
    cue_cfg = _make_cue_config()
    baseline_cfg = _make_baseline_config()

    cue_results: list[RunResult] = []
    baseline_results: list[RunResult] = []

    print("\n" + "=" * 60)
    print("PHASE 1: CUE-enhanced agent")
    print("=" * 60)
    for i, task in enumerate(TASKS):
        if i > 0:
            print(f"  (waiting {INTER_TASK_DELAY:.0f}s between tasks...)")
            await asyncio.sleep(INTER_TASK_DELAY)
        res = await run_task(task, cue_cfg, mode="cue")
        cue_results.append(res)
        status = "OK" if res.success else "FAIL"
        print(f"    -> {status} | steps={res.steps_taken} | time={res.elapsed:.1f}s")

    print("\n" + "=" * 60)
    print("PHASE 2: Baseline agent (no CUE enhancements)")
    print("=" * 60)
    for i, task in enumerate(TASKS):
        if i > 0:
            print(f"  (waiting {INTER_TASK_DELAY:.0f}s between tasks...)")
            await asyncio.sleep(INTER_TASK_DELAY)
        res = await run_task(task, baseline_cfg, mode="baseline")
        baseline_results.append(res)
        status = "OK" if res.success else "FAIL"
        print(f"    -> {status} | steps={res.steps_taken} | time={res.elapsed:.1f}s")

    return cue_results, baseline_results


# ── Report printer ─────────────────────────────────────────────────────────────

def _pct(count: int, total: int) -> str:
    if total == 0:
        return "N/A"
    return f"{count / total * 100:.0f}%"


def print_comparison(cue_results: list[RunResult], baseline_results: list[RunResult]) -> None:
    """Print a side-by-side comparison table."""
    print("\n" + "=" * 72)
    print("BENCHMARK RESULTS — CUE vs Baseline")
    print("=" * 72)

    # Per-task rows
    col_w = [10, 40, 14, 14]
    header = (
        f"{'Task ID':<{col_w[0]}} "
        f"{'Description':<{col_w[1]}} "
        f"{'CUE':^{col_w[2]}} "
        f"{'Baseline':^{col_w[3]}}"
    )
    print(header)
    print("-" * 72)

    by_id_cue = {r.task_id: r for r in cue_results}
    by_id_base = {r.task_id: r for r in baseline_results}

    for task in TASKS:
        tid = task["id"]
        desc = task["description"][:38]
        cr = by_id_cue.get(tid)
        br = by_id_base.get(tid)

        def fmt(r: RunResult | None) -> str:
            if r is None:
                return "  --  "
            s = "PASS" if r.success else "FAIL"
            return f"{s} s={r.steps_taken} t={r.elapsed:.1f}s"

        print(
            f"{tid:<{col_w[0]}} "
            f"{desc:<{col_w[1]}} "
            f"{fmt(cr):^{col_w[2]}} "
            f"{fmt(br):^{col_w[3]}}"
        )

    print("-" * 72)

    # Aggregates
    total = len(TASKS)
    cue_pass = sum(1 for r in cue_results if r.success)
    base_pass = sum(1 for r in baseline_results if r.success)

    cue_avg_steps = (
        sum(r.steps_taken for r in cue_results) / len(cue_results)
        if cue_results else 0.0
    )
    base_avg_steps = (
        sum(r.steps_taken for r in baseline_results) / len(baseline_results)
        if baseline_results else 0.0
    )
    cue_avg_time = (
        sum(r.elapsed for r in cue_results) / len(cue_results)
        if cue_results else 0.0
    )
    base_avg_time = (
        sum(r.elapsed for r in baseline_results) / len(baseline_results)
        if baseline_results else 0.0
    )

    print(f"\n{'SUMMARY':}")
    print(f"  Success rate :  CUE {_pct(cue_pass, total)}  vs  Baseline {_pct(base_pass, total)}")
    print(f"  Avg steps    :  CUE {cue_avg_steps:.1f}      vs  Baseline {base_avg_steps:.1f}")
    print(f"  Avg time     :  CUE {cue_avg_time:.1f}s    vs  Baseline {base_avg_time:.1f}s")

    # Improvement delta
    if base_pass > 0 and cue_pass >= base_pass:
        print(f"\n  CUE improved success by +{cue_pass - base_pass} task(s) over baseline.")
    elif cue_pass < base_pass:
        print(f"\n  Baseline outperformed CUE by {base_pass - cue_pass} task(s) — check logs.")
    else:
        print("\n  Both modes had equal success rates.")

    if base_avg_steps > 0 and cue_avg_steps < base_avg_steps:
        reduction = (1 - cue_avg_steps / base_avg_steps) * 100
        print(f"  CUE reduced avg steps by {reduction:.1f}%.")

    print("=" * 72 + "\n")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set. Add it to .env or export it.")
        sys.exit(1)

    print(f"CUE Mini Benchmark")
    print(f"  Model   : {MODEL}")
    print(f"  Tasks   : {len(TASKS)}")
    print(f"  MaxSteps: {MAX_STEPS}  Timeout: {TIMEOUT_SECONDS}s")
    print(f"  DISPLAY : {os.environ.get('DISPLAY', '(not set)')}")

    cue_results, baseline_results = asyncio.run(run_benchmark())
    print_comparison(cue_results, baseline_results)


if __name__ == "__main__":
    main()
