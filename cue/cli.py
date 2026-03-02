"""CUE CLI — Command-line interface for the Computer Use Enhancer."""

from __future__ import annotations

import asyncio
import sys

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cue.config import CUEConfig

app = typer.Typer(
    name="cue",
    help="CUE — Computer Use Enhancer: Augmentation layer for Claude Computer Use",
    no_args_is_help=True,
)
console = Console()


@app.command()
def run(
    task: str = typer.Argument(..., help="Task description to execute"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config YAML"),
    max_steps: int = typer.Option(50, "--max-steps", "-s", help="Maximum steps"),
    timeout: int = typer.Option(600, "--timeout", "-t", help="Timeout in seconds"),
    model: str | None = typer.Option(None, "--model", "-m", help="Claude model to use"),
) -> None:
    """Run a task with the CUE agent."""
    cfg = CUEConfig.load(config)

    if max_steps != 50:
        cfg.agent.max_steps = max_steps
    if timeout != 600:
        cfg.agent.timeout_seconds = timeout
    if model:
        cfg.agent.model = model

    console.print(Panel(f"[bold]Task:[/bold] {task}", title="CUE Agent", border_style="blue"))
    console.print(f"Model: {cfg.agent.model}")
    console.print(f"Max steps: {cfg.agent.max_steps} | Timeout: {cfg.agent.timeout_seconds}s")
    console.print()

    from cue.agent import CUEAgent

    agent = CUEAgent(config=cfg)

    try:
        result = asyncio.run(agent.run(task))
    except KeyboardInterrupt:
        console.print("\n[yellow]Task interrupted by user.[/yellow]")
        raise typer.Exit(1)

    if result.success:
        console.print(Panel(
            f"[green]Task completed successfully![/green]\n"
            f"Steps: {result.steps_taken} | Time: {result.total_time_seconds:.1f}s",
            border_style="green",
        ))
    else:
        console.print(Panel(
            f"[red]Task failed:[/red] {result.error}\n"
            f"Steps: {result.steps_taken} | Time: {result.total_time_seconds:.1f}s",
            border_style="red",
        ))
        raise typer.Exit(1)


@app.command("config")
def config_cmd(
    action: str = typer.Argument("show", help="Action: show, init, path"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to config YAML"),
) -> None:
    """Show or initialize CUE configuration."""
    if action == "show":
        cfg = CUEConfig.load(config)
        _display_config(cfg)
    elif action == "init":
        cfg = CUEConfig()
        out_path = config or ".cue/config.yaml"
        cfg.to_yaml(out_path)
        console.print(f"[green]Config initialized at: {out_path}[/green]")
    elif action == "path":
        from pathlib import Path

        search = [
            Path.cwd() / ".cue" / "config.yaml",
            Path.home() / ".cue" / "config.yaml",
        ]
        for p in search:
            if p.exists():
                console.print(f"[green]Active config:[/green] {p}")
                return
        console.print("[yellow]No config file found. Using defaults.[/yellow]")
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        raise typer.Exit(1)


@app.command("benchmark")
def benchmark(
    suite: str = typer.Argument("mini", help="Benchmark suite: mini, osworld"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output directory"),
    runs: int = typer.Option(1, "--runs", "-r", help="Number of runs"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
) -> None:
    """Run benchmark suite and display results."""
    cfg = CUEConfig.load(config)
    if output:
        cfg.benchmark.output_dir = output
    cfg.benchmark.runs_per_config = runs

    console.print(Panel(
        f"[bold]Suite:[/bold] {suite}\n"
        f"[bold]Runs:[/bold] {runs}",
        title="CUE Benchmark",
        border_style="blue",
    ))

    from cue.benchmark import BenchmarkRunner
    runner = BenchmarkRunner(config=cfg)

    try:
        result = asyncio.run(runner.run_suite(suite))
    except KeyboardInterrupt:
        console.print("\n[yellow]Benchmark interrupted.[/yellow]")
        raise typer.Exit(1)

    _display_benchmark_result(result, verbose)


@app.command("ablation")
def ablation(
    suite: str = typer.Argument("mini", help="Benchmark suite"),
    config: str | None = typer.Option(None, "--config", "-c", help="Config YAML path"),
    runs: int = typer.Option(3, "--runs", "-r", help="Runs per configuration"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output directory"),
) -> None:
    """Run ablation study to measure module contributions."""
    cfg = CUEConfig.load(config)
    if output:
        cfg.benchmark.output_dir = output
    cfg.benchmark.runs_per_config = runs

    console.print(Panel(
        f"[bold]Suite:[/bold] {suite}\n"
        f"[bold]Runs per config:[/bold] {runs}\n"
        f"[bold]Total configs:[/bold] 14",
        title="CUE Ablation Study",
        border_style="magenta",
    ))

    from cue.benchmark import AblationRunner
    abl = AblationRunner(config=cfg)

    try:
        results = asyncio.run(abl.run_ablation(suite=suite, runs_per_config=runs))
    except KeyboardInterrupt:
        console.print("\n[yellow]Ablation interrupted.[/yellow]")
        raise typer.Exit(1)

    contributions = abl.analyze_contributions(results)
    _display_ablation_results(results, contributions)


@app.command("analyze")
def analyze_cmd(
    results_path: str = typer.Argument(..., help="Path to benchmark results JSON"),
) -> None:
    """Analyze benchmark failures."""
    import json
    from pathlib import Path

    path = Path(results_path)
    if not path.exists():
        console.print(f"[red]File not found: {results_path}[/red]")
        raise typer.Exit(1)

    from cue.benchmark import FailureAnalyzer

    with open(path) as f:
        data = json.load(f)

    console.print(Panel(
        f"[bold]Analyzing:[/bold] {results_path}",
        title="Failure Analysis",
        border_style="yellow",
    ))

    analyzer = FailureAnalyzer()
    report = analyzer.generate_report_from_json(data)
    console.print(report)


@app.command("version")
def version() -> None:
    """Show CUE version information."""
    from cue import __version__

    table = Table(show_header=False, box=None)
    table.add_row("CUE version", __version__)
    table.add_row("Python", sys.version.split()[0])
    try:
        import anthropic
        table.add_row("anthropic SDK", anthropic.__version__)
    except ImportError:
        table.add_row("anthropic SDK", "[red]not installed[/red]")
    console.print(table)


def _display_benchmark_result(result: "BenchmarkResult", verbose: bool = False) -> None:
    """Display benchmark results in a rich table."""
    from cue.types import BenchmarkResult

    table = Table(title="Benchmark Results", show_lines=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Success Rate", f"{result.success_rate:.1f}%")
    table.add_row("Tasks", f"{result.successful_tasks}/{result.total_tasks}")
    table.add_row("Avg Steps", f"{result.avg_steps:.1f}")
    table.add_row("Avg Time", f"{result.avg_time:.1f}s")
    table.add_row("Avg Tokens", str(result.avg_tokens))

    console.print(table)

    # By difficulty
    if result.by_difficulty:
        diff_table = Table(title="By Difficulty")
        diff_table.add_column("Difficulty")
        diff_table.add_column("Success Rate")
        for diff, rate in result.by_difficulty.items():
            diff_table.add_row(diff, f"{rate:.1f}%")
        console.print(diff_table)

    # By app
    if result.by_app:
        app_table = Table(title="By Application")
        app_table.add_column("App")
        app_table.add_column("Success Rate")
        for app_name, rate in result.by_app.items():
            app_table.add_row(app_name, f"{rate:.1f}%")
        console.print(app_table)

    # Failure breakdown
    if result.by_failure_type:
        fail_table = Table(title="Failure Types")
        fail_table.add_column("Category")
        fail_table.add_column("Count")
        for cat, count in sorted(result.by_failure_type.items(), key=lambda x: -x[1]):
            fail_table.add_row(cat, str(count))
        console.print(fail_table)


def _display_ablation_results(
    results: dict, contributions: dict
) -> None:
    """Display ablation study results."""
    # Results table
    table = Table(title="Ablation Study Results", show_lines=True)
    table.add_column("Config", style="cyan")
    table.add_column("Success %", style="green")
    table.add_column("Avg Steps", style="white")
    table.add_column("Avg Tokens", style="white")

    for name, result in results.items():
        table.add_row(name, f"{result.success_rate:.1f}%", f"{result.avg_steps:.1f}", str(result.avg_tokens))
    console.print(table)

    # Contributions table
    contrib_table = Table(title="Module Contributions", show_lines=True)
    contrib_table.add_column("Module", style="cyan")
    contrib_table.add_column("Solo +%", style="green")
    contrib_table.add_column("Interaction +%", style="yellow")
    contrib_table.add_column("Critical?", style="red")

    for module, data in contributions.items():
        critical = "YES" if data.get("is_critical") else "no"
        contrib_table.add_row(
            module,
            f"{data['solo_contribution']:.1f}%",
            f"{data['interaction_effect']:.1f}%",
            critical,
        )
    console.print(contrib_table)


@app.command("platform-info")
def platform_info() -> None:
    """Show detected platform and capabilities."""
    import platform

    from cue.config import OmniParserConfig
    from cue.types import PlatformInfo

    os_name = sys.platform
    os_ver = platform.version()

    # Detect accessibility backend
    if os_name == "linux":
        a11y = "atspi"
    elif os_name == "darwin":
        a11y = "ax"
    elif os_name == "win32":
        a11y = "uia"
    else:
        a11y = "unknown"

    # Check OmniParser configuration
    cfg = CUEConfig.load()
    omni_cfg: OmniParserConfig = cfg.omniparser
    omni_status = (
        f"[green]configured[/green] ({omni_cfg.model_path})"
        if omni_cfg.enabled and omni_cfg.model_path
        else "[yellow]not configured[/yellow]"
    )

    info = PlatformInfo(
        os_name=os_name,
        os_version=os_ver,
        a11y_backend=a11y,
    )

    table = Table(title="Platform Info", show_lines=True)
    table.add_column("Property", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("OS", info.os_name)
    table.add_row("Version", info.os_version)
    table.add_row("A11y Backend", info.a11y_backend)
    table.add_row("OmniParser", omni_status)
    console.print(table)


@app.command("knowledge")
def knowledge(
    app_name: str = typer.Argument("", help="App name to show details for (leave empty to list all)"),
) -> None:
    """List available app knowledge or show details for a specific app."""
    from pathlib import Path

    from cue.planning.knowledge import AppKnowledgeBase

    knowledge_dir = Path(__file__).parent / "knowledge"

    if not app_name:
        # List all available YAML files
        yaml_files = sorted(knowledge_dir.glob("*.yaml"))
        if not yaml_files:
            console.print("[yellow]No knowledge files found.[/yellow]")
            return
        table = Table(title="Available App Knowledge", show_lines=True)
        table.add_column("File", style="cyan")
        table.add_column("App Name", style="green")
        import yaml
        for path in yaml_files:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            table.add_row(path.name, data.get("app_name", path.stem))
        console.print(table)
        return

    # Show details for the requested app
    kb = AppKnowledgeBase()
    kb.load_all(knowledge_dir)
    app_knowledge = kb.get_knowledge(app_name)

    if app_knowledge is None:
        console.print(f"[red]No knowledge found for: {app_name}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold]App:[/bold] {app_knowledge.app_name}",
        title="App Knowledge",
        border_style="blue",
    ))

    # Shortcuts
    if app_knowledge.shortcuts:
        sc_table = Table(title="Shortcuts", show_lines=True)
        sc_table.add_column("Action", style="cyan")
        sc_table.add_column("Keys", style="green")
        sc_table.add_column("Reliability", style="white")
        for sc in app_knowledge.shortcuts:
            sc_table.add_row(sc.action, sc.keys, f"{sc.reliability:.0%}")
        console.print(sc_table)

    # Pitfalls
    if app_knowledge.pitfalls:
        pt_table = Table(title="Pitfalls", show_lines=True)
        pt_table.add_column("Situation", style="cyan")
        pt_table.add_column("Avoid", style="red")
        pt_table.add_column("Instead", style="green")
        for pt in app_knowledge.pitfalls:
            pt_table.add_row(pt.situation, pt.avoid, pt.instead)
        console.print(pt_table)

    # Navigation
    if app_knowledge.navigation:
        nav_table = Table(title="Direct Navigation", show_lines=True)
        nav_table.add_column("Target", style="cyan")
        nav_table.add_column("Method", style="green")
        nav_table.add_column("Notes", style="white")
        for nav in app_knowledge.navigation:
            nav_table.add_row(nav.target, nav.method, nav.notes)
        console.print(nav_table)

    # Common tasks
    if app_knowledge.common_tasks:
        ct_table = Table(title="Common Tasks", show_lines=True)
        ct_table.add_column("Task", style="cyan")
        ct_table.add_column("Steps", style="green")
        for task in app_knowledge.common_tasks:
            steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(task.get("steps", [])))
            ct_table.add_row(task.get("name", ""), steps)
        console.print(ct_table)


def _display_config(cfg: CUEConfig) -> None:
    """Display configuration in a rich table."""
    table = Table(title="CUE Configuration", show_lines=True)
    table.add_column("Module", style="cyan")
    table.add_column("Setting", style="white")
    table.add_column("Value", style="green")

    # Grounding
    g = cfg.grounding
    table.add_row("Grounding", "level", g.level.value)
    table.add_row("", "visual_backend", g.visual_backend)
    table.add_row("", "ocr_engine", g.ocr_engine)
    table.add_row("", "confidence_threshold", str(g.confidence_threshold))

    # Execution
    e = cfg.execution
    table.add_row("Execution", "level", e.level.value)
    table.add_row("", "coordinate_snap_radius", str(e.coordinate_snap_radius))
    table.add_row("", "pre_validation", str(e.enable_pre_validation))
    table.add_row("", "timing_control", str(e.enable_timing_control))
    table.add_row("", "fallback_chain", str(e.enable_fallback_chain))

    # Verification
    v = cfg.verification
    table.add_row("Verification", "level", v.level.value)
    table.add_row("", "tier3_enabled", str(v.tier3_enabled))

    # Safety
    s = cfg.safety
    table.add_row("Safety", "level", s.level.value)
    table.add_row("", "blocked_commands", str(len(s.blocked_commands)))
    table.add_row("", "confirmation_patterns", str(len(s.confirmation_patterns)))

    # Benchmark
    b = cfg.benchmark
    table.add_row("Benchmark", "suite", b.suite)
    table.add_row("", "runs_per_config", str(b.runs_per_config))
    table.add_row("", "output_dir", b.output_dir)
    table.add_row("", "timeout_per_task", str(b.timeout_per_task))

    # Agent
    a = cfg.agent
    table.add_row("Agent", "model", a.model)
    table.add_row("", "max_steps", str(a.max_steps))
    table.add_row("", "timeout_seconds", str(a.timeout_seconds))
    table.add_row("", "resolution", f"{a.screenshot_width}x{a.screenshot_height}")

    console.print(table)


if __name__ == "__main__":
    app()
