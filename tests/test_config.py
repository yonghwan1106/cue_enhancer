"""Tests for CUE configuration."""

import tempfile
from pathlib import Path

from cue.config import (
    AgentConfig,
    CUEConfig,
    EnhancerLevel,
    ExecutionConfig,
    GroundingConfig,
    SafetyConfig,
    VerificationConfig,
)


class TestEnhancerLevel:
    def test_values(self):
        assert EnhancerLevel.OFF == "off"
        assert EnhancerLevel.BASIC == "basic"
        assert EnhancerLevel.FULL == "full"


class TestGroundingConfig:
    def test_defaults(self):
        cfg = GroundingConfig()
        assert cfg.level == EnhancerLevel.FULL
        assert cfg.visual_backend == "opencv"
        assert cfg.ocr_engine == "tesseract"
        assert cfg.confidence_threshold == 0.6
        assert cfg.cache_ttl_seconds == 5
        assert cfg.nms_iou_threshold == 0.5

    def test_custom(self):
        cfg = GroundingConfig(
            level=EnhancerLevel.OFF,
            visual_backend="omniparser",
            ocr_languages=["eng", "kor"],
        )
        assert cfg.level == EnhancerLevel.OFF
        assert cfg.visual_backend == "omniparser"
        assert "kor" in cfg.ocr_languages


class TestExecutionConfig:
    def test_defaults(self):
        cfg = ExecutionConfig()
        assert cfg.coordinate_snap_radius == 10
        assert cfg.enable_pre_validation is True
        assert cfg.enable_fallback_chain is True
        assert cfg.stability_timeout_ms == 1500


class TestVerificationConfig:
    def test_defaults(self):
        cfg = VerificationConfig()
        assert cfg.tier1_ssim_threshold == 0.005
        assert cfg.tier3_enabled is False
        assert cfg.tier3_max_calls_per_episode == 3


class TestSafetyConfig:
    def test_blocked_commands(self):
        cfg = SafetyConfig()
        assert "rm -rf" in cfg.blocked_commands
        assert "DROP TABLE" in cfg.blocked_commands

    def test_confirmation_patterns(self):
        cfg = SafetyConfig()
        assert "send" in cfg.confirmation_patterns
        assert "delete" in cfg.confirmation_patterns


class TestAgentConfig:
    def test_defaults(self):
        cfg = AgentConfig()
        assert cfg.max_steps == 50
        assert cfg.timeout_seconds == 600
        assert cfg.screenshot_width == 1024
        assert cfg.screenshot_height == 768
        assert "computer-use-2025-11-24" in cfg.api_betas


class TestCUEConfig:
    def test_defaults(self):
        cfg = CUEConfig()
        assert cfg.grounding.level == EnhancerLevel.FULL
        assert cfg.execution.level == EnhancerLevel.FULL
        assert cfg.verification.level == EnhancerLevel.FULL
        assert cfg.safety.level == EnhancerLevel.FULL
        assert cfg.agent.max_steps == 50

    def test_is_module_enabled(self):
        cfg = CUEConfig()
        assert cfg.is_module_enabled("grounding") is True
        assert cfg.is_module_enabled("execution") is True
        assert cfg.is_module_enabled("nonexistent") is True

    def test_is_module_disabled(self):
        cfg = CUEConfig(grounding=GroundingConfig(level=EnhancerLevel.OFF))
        assert cfg.is_module_enabled("grounding") is False
        assert cfg.is_module_enabled("execution") is True

    def test_yaml_roundtrip(self):
        cfg = CUEConfig(
            grounding=GroundingConfig(visual_backend="omniparser"),
            agent=AgentConfig(max_steps=100),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.yaml"
            cfg.to_yaml(path)
            assert path.exists()

            loaded = CUEConfig.from_yaml(path)
            assert loaded.grounding.visual_backend == "omniparser"
            assert loaded.agent.max_steps == 100

    def test_from_yaml_missing(self):
        cfg = CUEConfig.from_yaml("/nonexistent/path/config.yaml")
        assert cfg.agent.max_steps == 50  # defaults

    def test_load_defaults(self):
        cfg = CUEConfig.load(config_path="/nonexistent/path.yaml")
        assert cfg.grounding.level == EnhancerLevel.FULL
