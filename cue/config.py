"""CUE configuration management with Pydantic BaseSettings."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class EnhancerLevel(str, Enum):
    """Enhancement level for each module."""

    OFF = "off"
    BASIC = "basic"
    FULL = "full"


class GroundingConfig(BaseModel):
    """Grounding Enhancer configuration."""

    level: EnhancerLevel = EnhancerLevel.FULL
    visual_backend: str = "opencv"  # opencv | omniparser | gui-actor
    ocr_engine: str = "tesseract"  # tesseract | easyocr
    ocr_languages: list[str] = Field(default_factory=lambda: ["eng"])
    confidence_threshold: float = 0.6
    cache_ttl_seconds: int = 5
    nms_iou_threshold: float = 0.5


class ExecutionConfig(BaseModel):
    """Execution Enhancer configuration."""

    level: EnhancerLevel = EnhancerLevel.FULL
    coordinate_snap_radius: int = 10
    enable_pre_validation: bool = True
    enable_timing_control: bool = True
    enable_fallback_chain: bool = True
    stability_threshold: float = 0.005
    stability_timeout_ms: int = 1500
    stability_poll_interval_ms: int = 100
    post_action_delay_ms: int = 50
    max_fallback_stages: int = 6


class VerificationConfig(BaseModel):
    """Verification Loop configuration."""

    level: EnhancerLevel = EnhancerLevel.FULL
    tier1_ssim_threshold: float = 0.005
    tier1_minor_threshold: float = 0.001
    tier2_pass_score: float = 0.6
    tier2_fail_score: float = 0.2
    tier3_enabled: bool = False  # Phase 2
    tier3_max_calls_per_episode: int = 3


class SafetyConfig(BaseModel):
    """Safety Gate configuration."""

    level: EnhancerLevel = EnhancerLevel.FULL
    blocked_commands: list[str] = Field(
        default_factory=lambda: [
            "rm -rf",
            "sudo rm",
            "mkfs",
            "dd if=",
            "DROP TABLE",
            "DROP DATABASE",
            "DELETE FROM",
            "TRUNCATE",
            "shutdown",
            "reboot",
            "init 0",
            "init 6",
        ]
    )
    confirmation_patterns: list[str] = Field(
        default_factory=lambda: [
            "send",
            "submit",
            "publish",
            "delete",
            "remove",
            "post",
            "tweet",
            "email",
        ]
    )
    permission_level: int = 2  # 0=Observe, 1=Confirm, 2=Auto-Safe, 3=Full Auto
    max_repeated_actions: int = 5  # Emergency stop: consecutive same-action limit
    sensitive_paths: list[str] = Field(
        default_factory=lambda: [
            "/etc/",
            "/boot/",
            "/sys/",
            "~/.ssh/",
            "~/.gnupg/",
            "/root/",
        ]
    )


class PlanningConfig(BaseModel):
    """Planning Enhancer configuration."""

    level: EnhancerLevel = EnhancerLevel.FULL
    step_limit: int = 7  # Miller's Law: max subtasks
    keyboard_first: bool = True
    enable_app_knowledge: bool = True
    enable_reflexion: bool = True
    knowledge_dir: str = ""  # defaults to package bundled knowledge


class MemoryConfig(BaseModel):
    """Experience Memory configuration."""

    level: EnhancerLevel = EnhancerLevel.FULL
    db_dir: str = "~/.cue"
    working_memory_steps: int = 10
    episodic_ttl_days: int = 90
    max_lessons_per_query: int = 5
    max_episodes_per_query: int = 3
    memory_token_budget: int = 500
    acon_recent_window: int = 5
    acon_mid_window: int = 5
    acon_max_tokens: int = 2000


class EfficiencyConfig(BaseModel):
    """Efficiency Engine configuration."""

    level: EnhancerLevel = EnhancerLevel.FULL
    enable_step_optimizer: bool = True
    enable_latency_optimizer: bool = True
    enable_context_manager: bool = True
    cache_ttl_seconds: float = 2.0
    token_budget_per_step: int = 2000
    enable_selective_screenshots: bool = True
    enable_prefetch: bool = True


class BenchmarkConfig(BaseModel):
    """Benchmark and ablation study configuration."""

    suite: str = "mini"  # mini | osworld | custom
    tasks_dir: str = ""  # defaults to bundled tasks
    runs_per_config: int = 3  # for statistical significance
    output_dir: str = ".cue/benchmark_results"
    timeout_per_task: int = 120
    parallel_tasks: int = 1  # sequential by default
    save_screenshots: bool = False
    save_traces: bool = True


class OmniParserConfig(BaseModel):
    """OmniParser V2 integration configuration."""

    enabled: bool = False  # opt-in; requires model weights
    model_path: str = ""  # path to OmniParser V2 weights
    device: str = "cpu"  # cpu | cuda | mps
    confidence_threshold: float = 0.5
    max_elements: int = 100
    batch_size: int = 1
    cache_ttl_seconds: int = 5
    fallback_to_opencv: bool = True  # use OpenCV if OmniParser unavailable


class AgentConfig(BaseModel):
    """Main agent loop configuration."""

    max_steps: int = 50
    timeout_seconds: int = 600
    screenshot_width: int = 1024
    screenshot_height: int = 768
    model: str = "claude-sonnet-4-6"
    api_betas: list[str] = Field(
        default_factory=lambda: ["computer-use-2025-11-24"]
    )


class CUEConfig(BaseSettings):
    """Root configuration for CUE.

    Priority: env vars > YAML config > code defaults.
    Env vars use CUE_ prefix (e.g., CUE_AGENT__MAX_STEPS=100).
    """

    model_config = {"env_prefix": "CUE_", "env_nested_delimiter": "__"}

    grounding: GroundingConfig = Field(default_factory=GroundingConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    planning: PlanningConfig = Field(default_factory=PlanningConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    efficiency: EfficiencyConfig = Field(default_factory=EfficiencyConfig)
    benchmark: BenchmarkConfig = Field(default_factory=BenchmarkConfig)
    omniparser: OmniParserConfig = Field(default_factory=OmniParserConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)

    @classmethod
    def from_yaml(cls, path: str | Path) -> CUEConfig:
        """Load configuration from a YAML file, merged with defaults."""
        path = Path(path)
        if not path.exists():
            return cls()
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        return cls(**data)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> CUEConfig:
        """Load config with priority: env vars > YAML > defaults.

        Searches for config in order:
        1. Explicit path
        2. .cue/config.yaml in CWD
        3. ~/.cue/config.yaml
        4. Defaults
        """
        search_paths: list[Path] = []
        if config_path:
            search_paths.append(Path(config_path))
        search_paths.append(Path.cwd() / ".cue" / "config.yaml")
        search_paths.append(Path.home() / ".cue" / "config.yaml")

        for p in search_paths:
            if p.exists():
                return cls.from_yaml(p)

        return cls()

    def to_yaml(self, path: str | Path) -> None:
        """Save current config to a YAML file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = self.model_dump(mode="json")
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def is_module_enabled(self, module: str) -> bool:
        """Check if a module is enabled (not off)."""
        config_map: dict[str, Any] = {
            "grounding": self.grounding,
            "execution": self.execution,
            "verification": self.verification,
            "safety": self.safety,
            "planning": self.planning,
            "memory": self.memory,
            "efficiency": self.efficiency,
        }
        mod = config_map.get(module)
        if mod and hasattr(mod, "level"):
            return mod.level != EnhancerLevel.OFF
        return True
