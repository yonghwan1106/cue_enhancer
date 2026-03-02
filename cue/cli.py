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
    suite: str = typer.Argument("mini", help="Benchmark suite: mini, full"),
) -> None:
    """Run benchmark tests (placeholder for Phase 1)."""
    console.print(Panel(
        "[yellow]Benchmark runner is a placeholder in Phase 1.[/yellow]\n"
        "Full benchmark integration planned for Phase 2.",
        title="CUE Benchmark",
    ))


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

    # Agent
    a = cfg.agent
    table.add_row("Agent", "model", a.model)
    table.add_row("", "max_steps", str(a.max_steps))
    table.add_row("", "timeout_seconds", str(a.timeout_seconds))
    table.add_row("", "resolution", f"{a.screenshot_width}x{a.screenshot_height}")

    console.print(table)


if __name__ == "__main__":
    app()
