"""CLI entry point for running CUE benchmarks."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from cue.config import CUEConfig
from cue.benchmark.runner import BenchmarkRunner
from cue.benchmark.ablation import AblationRunner
from cue.benchmark.analysis import FailureAnalyzer
from cue.benchmark.metrics import MetricsCollector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CUE Benchmark Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (no API calls) to validate pipeline
  python -m cue.benchmark.cli --dry-run

  # Run mini benchmark suite
  python -m cue.benchmark.cli --suite mini_benchmark

  # Run with max 3 tasks and save results
  python -m cue.benchmark.cli --suite mini_benchmark --max-tasks 3 --output results/

  # Run ablation study (14 configs x N runs)
  python -m cue.benchmark.cli --ablation --suite mini --runs-per-config 2

  # List available suites
  python -m cue.benchmark.cli --list-suites
        """,
    )
    parser.add_argument(
        "--suite", default="mini", help="Benchmark suite name (default: mini)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simulate execution without Claude API calls"
    )
    parser.add_argument(
        "--max-tasks", type=int, default=None,
        help="Maximum number of tasks to run"
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output directory for results (JSON + Markdown)"
    )
    parser.add_argument(
        "--ablation", action="store_true",
        help="Run ablation study instead of standard benchmark"
    )
    parser.add_argument(
        "--runs-per-config", type=int, default=3,
        help="Number of runs per ablation config (default: 3)"
    )
    parser.add_argument(
        "--list-suites", action="store_true",
        help="List available benchmark suites and exit"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to CUE config YAML file"
    )
    return parser.parse_args()


async def run_benchmark(args: argparse.Namespace) -> int:
    """Run the benchmark and return exit code."""
    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger = logging.getLogger("cue.benchmark")

    # Load config
    config = CUEConfig.load(args.config) if args.config else CUEConfig()

    # List suites mode
    if args.list_suites:
        from cue.benchmark.task_loader import TaskLoader
        loader = TaskLoader()
        suites = loader.get_available_suites(config.benchmark.tasks_dir)
        print("Available benchmark suites:")
        for s in suites:
            tasks = loader.load_suite(s, config.benchmark.tasks_dir)
            print(f"  {s} ({len(tasks)} tasks)")
        return 0

    # Prepare output directory
    output_dir: Path | None = None
    if args.output:
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)

    start = time.time()

    if args.ablation:
        # Ablation study
        logger.info("Starting ablation study on suite '%s'...", args.suite)
        ablation = AblationRunner(config=config, dry_run=args.dry_run)
        results = await ablation.run_ablation(
            suite=args.suite, runs_per_config=args.runs_per_config
        )
        contributions = ablation.analyze_contributions(results)

        # Print results
        print("\n" + "=" * 60)
        print("ABLATION STUDY RESULTS")
        print("=" * 60)
        print(f"\n{'Config':<20} {'Success%':>10} {'Avg Steps':>10} {'Avg Time':>10}")
        print("-" * 50)
        for name, res in sorted(results.items()):
            print(
                f"{name:<20} {res.success_rate:>9.1f}% "
                f"{res.avg_steps:>10.1f} {res.avg_time:>9.1f}s"
            )

        print(f"\n{'Module':<20} {'Solo Delta':>10} {'Drop':>10} {'Critical':>10}")
        print("-" * 50)
        for mod, info in contributions.items():
            crit = "YES" if info["is_critical"] else "no"
            print(
                f"{mod:<20} {info['solo_contribution']:>+9.1f}% "
                f"{info['drop_when_removed']:>+9.1f}% {crit:>10}"
            )

        # Save results
        if output_dir:
            ablation_path = output_dir / "ablation_results.json"
            data = {
                name: {
                    "config_name": r.config_name,
                    "modules_enabled": r.modules_enabled,
                    "success_rate": r.success_rate,
                    "avg_steps": r.avg_steps,
                    "avg_tokens": r.avg_tokens,
                    "avg_time": r.avg_time,
                }
                for name, r in results.items()
            }
            with open(ablation_path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"\nResults saved to {ablation_path}")

    else:
        # Standard benchmark
        mode_label = "DRY RUN" if args.dry_run else "LIVE"
        logger.info(
            "Starting benchmark [%s] suite='%s'...", mode_label, args.suite
        )
        runner = BenchmarkRunner(config=config, dry_run=args.dry_run)
        result = await runner.run_suite(
            suite=args.suite, max_tasks=args.max_tasks
        )

        # Print results
        collector = MetricsCollector()
        report = collector.to_markdown(result)
        print("\n" + report)

        # Failure analysis
        if result.total_tasks > 0 and result.successful_tasks < result.total_tasks:
            analyzer = FailureAnalyzer()
            analysis = analyzer.analyze(result)
            print("\n## Failure Analysis")
            if analysis["recommendations"]:
                for rec in analysis["recommendations"]:
                    print(f"  - {rec}")

        # Save results
        if output_dir:
            timestamp = int(time.time())
            json_path = output_dir / f"benchmark_{args.suite}_{timestamp}.json"
            md_path = output_dir / f"benchmark_{args.suite}_{timestamp}.md"
            collector.to_json(result, str(json_path))
            with open(md_path, "w") as f:
                f.write(report)
            print(f"\nResults saved to {json_path}")

    elapsed = time.time() - start
    print(f"\nTotal time: {elapsed:.1f}s")
    return 0


def main() -> None:
    # Ensure UTF-8 output on Windows (cp949 can't encode some chars)
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    sys.exit(asyncio.run(run_benchmark(args)))


if __name__ == "__main__":
    main()
