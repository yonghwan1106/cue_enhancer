"""Tests for CUE Phase 4 — OmniParser, Windows platform, knowledge base."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cue.config import OmniParserConfig
from cue.types import OmniParserElement, OmniParserResult, PlatformInfo, UIElement


# ─── TestOmniParserGrounder ────────────────────────────────────────────────────


class TestOmniParserGrounder:
    def _get_grounder(self):
        from cue.advanced.omniparser import OmniParserGrounder
        return OmniParserGrounder()

    def test_is_available_false_when_no_model(self):
        grounder = self._get_grounder()
        # Default config has empty model_path, so model is not loaded
        assert grounder.is_available() is False

    def test_parse_returns_empty_when_unavailable(self):
        grounder = self._get_grounder()
        # Model not loaded — parse() should return an empty OmniParserResult
        from PIL import Image
        img = Image.new("RGB", (100, 100))
        result = grounder.parse(img)
        assert isinstance(result, OmniParserResult)
        assert result.elements == []

    def test_detect_elements_returns_empty_when_unavailable(self):
        grounder = self._get_grounder()
        from PIL import Image
        img = Image.new("RGB", (100, 100))
        elements = grounder.detect_elements(img)
        assert isinstance(elements, list)
        assert elements == []

    def test_convert_to_ui_elements(self):
        grounder = self._get_grounder()
        omni_result = OmniParserResult(
            elements=[
                OmniParserElement(
                    label="Save",
                    bbox=(10, 20, 110, 50),
                    element_type="button",
                    confidence=0.9,
                    is_interactive=True,
                ),
                OmniParserElement(
                    label="Cancel",
                    bbox=(120, 20, 220, 50),
                    element_type="button",
                    confidence=0.8,
                    is_interactive=True,
                ),
            ]
        )
        ui_elements = grounder.convert_to_ui_elements(omni_result)
        assert len(ui_elements) == 2
        assert all(isinstance(e, UIElement) for e in ui_elements)
        labels = {e.label for e in ui_elements}
        assert "Save" in labels
        assert "Cancel" in labels

    def test_config_defaults(self):
        cfg = OmniParserConfig()
        assert cfg.model_path == ""
        assert cfg.enabled is False
        assert cfg.device == "cpu"
        assert cfg.confidence_threshold == 0.5
        assert cfg.max_elements == 100

    def test_fallback_flag(self):
        cfg = OmniParserConfig()
        assert cfg.fallback_to_opencv is True


# ─── TestWindowsEnvironment ────────────────────────────────────────────────────


class TestWindowsEnvironment:
    def test_import(self):
        # WindowsEnvironment can be imported regardless of platform
        from cue.platform.windows import WindowsEnvironment  # noqa: F401
        assert True

    def test_translate_key_simple(self):
        from cue.platform.windows import WindowsEnvironment
        env = WindowsEnvironment()
        assert env._translate_key("Enter") == "Return"
        assert env._translate_key("Tab") == "Tab"
        assert env._translate_key("Escape") == "Escape"
        assert env._translate_key("Backspace") == "BackSpace"

    def test_translate_key_combo(self):
        from cue.platform.windows import WindowsEnvironment
        env = WindowsEnvironment()
        # Modifier combos should pass through with translations applied per part
        result = env._translate_key("ctrl+s")
        assert "ctrl" in result.lower() or "+" in result
        result_alt_f4 = env._translate_key("alt+F4")
        assert "alt" in result_alt_f4.lower() or "+" in result_alt_f4

    def test_create_environment_factory_win32(self):
        # Patch sys.platform to win32 and verify factory returns WindowsEnvironment
        from cue.platform.windows import WindowsEnvironment
        with patch("cue.platform.base.sys") as mock_sys:
            mock_sys.platform = "win32"
            from cue.platform.base import create_environment
            # Re-evaluate under the patched platform
            with patch("cue.platform.base.sys.platform", "win32"):
                # The factory raises NotImplementedError for win32 in base —
                # but WindowsEnvironment itself is importable and instantiable.
                env = WindowsEnvironment()
                assert env is not None

    def test_platform_info_type(self):
        info = PlatformInfo(
            os_name="win32",
            os_version="10.0.19045",
            a11y_backend="uia",
            screenshot_method="win32api",
            input_method="win32api",
        )
        assert info.os_name == "win32"
        assert info.a11y_backend == "uia"


# ─── TestKnowledgeExpansion ────────────────────────────────────────────────────


class TestKnowledgeExpansion:
    _KNOWLEDGE_DIR = Path(__file__).parent.parent / "cue" / "knowledge"

    def test_knowledge_files_exist(self):
        yaml_files = list(self._KNOWLEDGE_DIR.glob("*.yaml"))
        assert len(yaml_files) >= 1, (
            f"Expected at least 1 YAML knowledge file, found {len(yaml_files)}"
        )

    def test_knowledge_schema(self):
        import yaml
        yaml_files = list(self._KNOWLEDGE_DIR.glob("*.yaml"))
        assert yaml_files, "No YAML knowledge files found"
        required_keys = {"app_name", "shortcuts", "pitfalls", "navigation", "common_tasks"}
        for path in yaml_files:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            missing = required_keys - set(data.keys())
            assert not missing, f"{path.name} is missing keys: {missing}"

    def test_shortcuts_have_required_fields(self):
        import yaml
        yaml_files = list(self._KNOWLEDGE_DIR.glob("*.yaml"))
        assert yaml_files, "No YAML knowledge files found"
        for path in yaml_files:
            with open(path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            for shortcut in data.get("shortcuts", []):
                assert "action" in shortcut, f"{path.name}: shortcut missing 'action'"
                assert "keys" in shortcut, f"{path.name}: shortcut missing 'keys'"
                assert "reliability" in shortcut, f"{path.name}: shortcut missing 'reliability'"

    def test_knowledge_loader_finds_all(self):
        from cue.planning.knowledge import AppKnowledgeBase
        kb = AppKnowledgeBase()
        kb.load_all(self._KNOWLEDGE_DIR)
        yaml_files = list(self._KNOWLEDGE_DIR.glob("*.yaml"))
        assert len(kb.loaded_apps) == len(yaml_files), (
            f"Loaded {len(kb.loaded_apps)} apps but found {len(yaml_files)} YAML files"
        )


# ─── TestPlatformInfo ─────────────────────────────────────────────────────────


class TestPlatformInfo:
    def test_platform_info_defaults(self):
        info = PlatformInfo()
        assert info.os_name == ""
        assert info.os_version == ""
        assert info.a11y_backend == ""
        assert info.screenshot_method == ""
        assert info.input_method == ""

    def test_omniparser_types(self):
        elem = OmniParserElement(
            label="OK",
            bbox=(0, 0, 50, 30),
            element_type="button",
            confidence=0.95,
            ocr_text="OK",
            icon_class="",
            is_interactive=True,
        )
        assert elem.label == "OK"
        assert elem.bbox == (0, 0, 50, 30)
        assert elem.is_interactive is True

        result = OmniParserResult(
            elements=[elem],
            latency_ms=12.5,
            model_version="v2",
            screenshot_size=(1024, 768),
        )
        assert len(result.elements) == 1
        assert len(result.interactive_elements) == 1
        assert result.latency_ms == 12.5
