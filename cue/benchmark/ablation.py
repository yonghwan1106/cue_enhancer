"""Ablation study runner — measures per-module contribution to CUE performance."""

from __future__ import annotations

import logging
from typing import Any

from cue.config import CUEConfig, EnhancerLevel
from cue.types import AblationResult, BenchmarkResult

logger = logging.getLogger(__name__)

_MODULES = [
    "grounding", "planning", "execution", "verification", "memory", "efficiency", "safety",
]


def _build_configs() -> dict[str, dict[str, bool]]:
    configs: dict[str, dict[str, bool]] = {
        "baseline": {m: False for m in _MODULES},
        "full_cue": {m: True for m in _MODULES},
    }
    for m in _MODULES:
        configs[f"+{m}"] = {mod: (mod == m) for mod in _MODULES}
        configs[f"cue-{m}"] = {mod: (mod != m) for mod in _MODULES}
    return configs


class AblationRunner:
    """Run ablation study configurations to measure module contributions.

    14 configurations:
    - baseline (no CUE modules)
    - full_cue (all modules)
    - +grounding, +planning, +execution, +verification, +memory, +efficiency (solo add)
    - cue-grounding, ..., cue-safety (leave one out)
    """

    MODULES = _MODULES
    CONFIGS: dict[str, dict[str, bool]] = _build_configs()

    def __init__(self, config: CUEConfig | None = None, dry_run: bool = False) -> None:
        self._config = config or CUEConfig()
        self._dry_run = dry_run

    async def run_ablation(
        self,
        suite: str = "mini",
        runs_per_config: int = 3,
    ) -> dict[str, AblationResult]:
        """Run all 14 ablation configurations and return per-config results."""
        results: dict[str, AblationResult] = {}
        for config_name, modules in self.CONFIGS.items():
            result = await self._run_config(config_name, modules, suite, runs_per_config)
            results[config_name] = result
        return results

    async def _run_config(
        self,
        config_name: str,
        modules: dict[str, bool],
        suite: str,
        runs: int,
    ) -> AblationResult:
        """Run a single ablation configuration with real CUEAgent."""
        from cue.benchmark.runner import BenchmarkRunner

        # Build a config with specific modules toggled
        config = self._build_ablation_config(modules)
        runner = BenchmarkRunner(config=config, dry_run=self._dry_run)

        run_results: list[BenchmarkResult] = []
        all_success_rates: list[float] = []
        all_steps: list[float] = []
        all_tokens: list[int] = []
        all_times: list[float] = []

        for run_idx in range(runs):
            logger.info(
                "Ablation %s — run %d/%d", config_name, run_idx + 1, runs
            )
            result = await runner.run_suite(suite)
            run_results.append(result)
            all_success_rates.append(result.success_rate)
            all_steps.append(result.avg_steps)
            all_tokens.append(result.avg_tokens)
            all_times.append(result.avg_time)

        return AblationResult(
            config_name=config_name,
            modules_enabled=modules,
            success_rate=sum(all_success_rates) / len(all_success_rates) if all_success_rates else 0.0,
            avg_steps=sum(all_steps) / len(all_steps) if all_steps else 0.0,
            avg_tokens=int(sum(all_tokens) / len(all_tokens)) if all_tokens else 0,
            avg_time=sum(all_times) / len(all_times) if all_times else 0.0,
            runs=run_results,
        )

    def _build_ablation_config(self, modules: dict[str, bool]) -> CUEConfig:
        """Build a CUEConfig with specific modules enabled/disabled."""
        config = CUEConfig()
        level_map = {True: EnhancerLevel.FULL, False: EnhancerLevel.OFF}

        if "grounding" in modules:
            config.grounding.level = level_map[modules["grounding"]]
        if "execution" in modules:
            config.execution.level = level_map[modules["execution"]]
        if "verification" in modules:
            config.verification.level = level_map[modules["verification"]]
        if "planning" in modules:
            config.planning.level = level_map[modules["planning"]]
        if "memory" in modules:
            config.memory.level = level_map[modules["memory"]]
        if "safety" in modules:
            config.safety.level = level_map[modules["safety"]]
        if "efficiency" in modules:
            config.efficiency.level = level_map[modules["efficiency"]]

        return config

    def analyze_contributions(
        self, results: dict[str, AblationResult]
    ) -> dict[str, dict[str, Any]]:
        """Analyze per-module contributions from ablation results."""
        baseline_rate = results["baseline"].success_rate if "baseline" in results else 0.0
        full_rate = results["full_cue"].success_rate if "full_cue" in results else 0.0

        contributions: dict[str, dict[str, Any]] = {}
        for module in self.MODULES:
            solo_key = f"+{module}"
            ablated_key = f"cue-{module}"

            solo_rate = results[solo_key].success_rate if solo_key in results else baseline_rate
            ablated_rate = results[ablated_key].success_rate if ablated_key in results else full_rate

            solo_contribution = solo_rate - baseline_rate
            interaction_effect = (full_rate - ablated_rate) - solo_contribution
            drop_when_removed = full_rate - ablated_rate
            is_critical = drop_when_removed > 10.0

            contributions[module] = {
                "solo_contribution": round(solo_contribution, 2),
                "interaction_effect": round(interaction_effect, 2),
                "is_critical": is_critical,
                "drop_when_removed": round(drop_when_removed, 2),
            }

        return contributions
