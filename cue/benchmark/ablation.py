"""Ablation study runner — measures per-module contribution to CUE performance."""

from __future__ import annotations

from typing import Any

from cue.config import CUEConfig
from cue.types import AblationResult, BenchmarkResult


_MODULES = ["grounding", "planning", "execution", "verification", "memory", "efficiency"]


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
    - cue-grounding, cue-planning, cue-execution, cue-verification, cue-memory, cue-efficiency (leave one out)
    """

    MODULES = _MODULES
    CONFIGS: dict[str, dict[str, bool]] = _build_configs()

    def __init__(self, config: CUEConfig | None = None) -> None:
        self._config = config or CUEConfig()

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
        """Run a single ablation configuration (mock implementation)."""
        if config_name == "baseline":
            success_rate = 50.0
        elif config_name == "full_cue":
            success_rate = 80.0
        elif config_name.startswith("+"):
            success_rate = 55.0
        else:  # cue-X
            success_rate = 75.0

        return AblationResult(
            config_name=config_name,
            modules_enabled=modules,
            success_rate=success_rate,
            avg_steps=5.0,
            avg_tokens=1000,
            avg_time=10.0,
            runs=[],
        )

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
