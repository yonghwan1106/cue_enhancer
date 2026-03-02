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
    coordinate_snap_radius: int = 20
    enable_pre_validation: bool = True
    enable_timing_control: bool = True
    enable_fallback_chain: bool = True
    stability_threshold: float = 0.005
    stability_timeout_ms: int = 3000
    stability_poll_interval_ms: int = 100
    max_fallback_stages: int = 6


class VerificationConfig(BaseModel):
    """Verification Loop configuration."""

    level: EnhancerLevel = EnhancerLevel.FULL
    tier1_ssim_threshold: float = 0.01
    tier1_minor_threshold: float = 0.002
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


class AgentConfig(BaseModel):
    """Main agent loop configuration."""

    max_steps: int = 50
    timeout_seconds: int = 600
    screenshot_width: int = 1024
    screenshot_height: int = 768
    model: str = "claude-sonnet-4-6-20250514"
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
        }
        mod = config_map.get(module)
        if mod and hasattr(mod, "level"):
            return mod.level != EnhancerLevel.OFF
        return True
