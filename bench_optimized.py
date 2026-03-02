"""3-way benchmark: Baseline vs CUE FULL vs CUE BASIC (optimized)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ.setdefault(_k.strip(), _v.strip())
os.environ.setdefault("DISPLAY", ":99")

TASKS = [
    {"id": "mini-001", "description": "Type 'echo hello' in the terminal and press Enter"},
    {"id": "mini-002", "description": "Click on the terminal window and type 'pwd'"},
    {"id": "mini-003", "description": "Type 'date' in the terminal and press Enter"},
]
MODEL = "claude-sonnet-4-6"
MAX_STEPS = 8
TIMEOUT_SECONDS = 45
INTER_TASK_DELAY = 3.0
RETRY_DELAY = 60.0
SEP = "=" * 72


@dataclass
class RunResult:
    task_id: str
    mode: str
    success: bool
    steps_taken: int
    elapsed: float
    error: str = ""


def _make_config(mode: str):
    from cue.config import CUEConfig, EnhancerLevel
    cfg = CUEConfig()
    cfg.agent.max_steps = MAX_STEPS
    cfg.agent.timeout_seconds = TIMEOUT_SECONDS
    cfg.agent.model = MODEL
    modules = [
        cfg.grounding, cfg.planning, cfg.verification,
        cfg.execution, cfg.safety, cfg.memory, cfg.efficiency,
    ]
    if mode == "baseline":
        for mod in modules:
            mod.level = EnhancerLevel.OFF
    elif mode == "cue_basic":
        for mod in modules:
            mod.level = EnhancerLevel.BASIC
    else:  # cue_full
        for mod in modules:
            mod.level = EnhancerLevel.FULL
    return cfg


async def run_task(task, config, mode):
    from cue.agent import CUEAgent
    tid = task["id"]
    desc = task["description"][:50]
    print("  [%10s] %s: %s..." % (mode, tid, desc))
    agent = CUEAgent(config=config)
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            agent.run(task["description"]),
            timeout=TIMEOUT_SECONDS + 5,
        )
        elapsed = time.monotonic() - start
        return RunResult(tid, mode, result.success, result.steps_taken, elapsed, result.error or "")
    except asyncio.TimeoutError:
        return RunResult(tid, mode, False, 0, time.monotonic() - start, "timeout")
    except Exception as exc:
        err = str(exc)
        if "429" in err or "rate_limit" in err.lower() or "overloaded" in err.lower():
            print("    -> RATE LIMIT. Waiting %.0fs..." % RETRY_DELAY)
            await asyncio.sleep(RETRY_DELAY)
        print("    -> ERROR: %s" % err[:80])
        return RunResult(tid, mode, False, 0, time.monotonic() - start, err[:120])


async def run_phase(mode):
    cfg = _make_config(mode)
    results = []
    for i, task in enumerate(TASKS):
        if i > 0:
            await asyncio.sleep(INTER_TASK_DELAY)
        res = await run_task(task, cfg, mode)
        status = "OK" if res.success else "FAIL"
        print("    -> %s | steps=%d | time=%.1fs" % (status, res.steps_taken, res.elapsed))
        results.append(res)
    return results


async def main_async():
    all_results = {}
    for mode in ["baseline", "cue_full", "cue_basic"]:
        print("\n" + SEP)
        print("PHASE: %s" % mode.upper())
        print(SEP)
        all_results[mode] = await run_phase(mode)
        print("  (waiting 5s before next phase...)")
        await asyncio.sleep(5)
    return all_results


def print_report(all_results):
    print("\n" + SEP)
    print("BENCHMARK RESULTS - 3-way Comparison (Optimized)")
    print(SEP)
    print("%-12s %6s %10s %10s %12s" % ("Mode", "Pass", "AvgSteps", "AvgTime", "TotalTime"))
    print("-" * 72)
    for mode in ["baseline", "cue_full", "cue_basic"]:
        results = all_results[mode]
        n = len(results)
        passed = sum(1 for r in results if r.success)
        avg_steps = sum(r.steps_taken for r in results) / n if n else 0
        avg_time = sum(r.elapsed for r in results) / n if n else 0
        total_time = sum(r.elapsed for r in results)
        print("%-12s  %d/%d %10.1f %9.1fs %11.1fs" % (
            mode, passed, n, avg_steps, avg_time, total_time
        ))
    print("-" * 72)

    base_total = sum(r.elapsed for r in all_results["baseline"])
    full_total = sum(r.elapsed for r in all_results["cue_full"])
    basic_total = sum(r.elapsed for r in all_results["cue_basic"])

    if base_total > 0:
        print("\nOverhead vs Baseline:")
        print("  CUE FULL:  %.2fx (was ~3.17x before optimization)" % (full_total / base_total))
        print("  CUE BASIC: %.2fx (target: <1.5x)" % (basic_total / base_total))
    print(SEP + "\n")

    # Save JSON
    out = {}
    for mode, results in all_results.items():
        out[mode] = [
            {"task_id": r.task_id, "success": r.success, "steps": r.steps_taken,
             "time": round(r.elapsed, 2), "error": r.error}
            for r in results
        ]
    out["summary"] = {
        "base_total": round(base_total, 2),
        "full_total": round(full_total, 2),
        "basic_total": round(basic_total, 2),
        "full_overhead": round(full_total / base_total, 2) if base_total > 0 else 0,
        "basic_overhead": round(basic_total / base_total, 2) if base_total > 0 else 0,
    }
    out_dir = Path("/opt/cue_enhancer/.cue/benchmark_results")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "optimized_bench.json"
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    print("Results saved to %s" % out_path)


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY not set.")
        sys.exit(1)
    print("CUE 3-Way Benchmark (Optimized)")
    print("  Model: %s | Tasks: %d | MaxSteps: %d | Timeout: %ds" % (
        MODEL, len(TASKS), MAX_STEPS, TIMEOUT_SECONDS
    ))
    all_results = asyncio.run(main_async())
    print_report(all_results)


if __name__ == "__main__":
    main()
