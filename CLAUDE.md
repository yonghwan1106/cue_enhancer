# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CUE (Computer Use Enhancement) is an augmentation middleware for Anthropic's Claude Computer Use API. It wraps Claude's raw computer-use calls with grounding, verification, memory, and safety modules to improve action accuracy and reliability. Python 3.11+, async-first.

## Commands

```bash
# Run all tests (169 tests, ~3s)
python -m pytest tests/ -q

# Run a single test file
python -m pytest tests/test_config.py -v

# Run a single test
python -m pytest tests/test_grounding.py::TestSourceMerger::test_iou_overlap -v

# Lint
ruff check cue/ tests/

# Format
ruff format cue/ tests/

# CLI usage
cue run "task description" --max-steps 10 --timeout 60

# Import check
python -c "from cue import CUEAgent, CUEConfig"
```

## Architecture

### Agent Loop (cue/agent.py)

`CUEAgent.run(task)` executes a 10-step loop per action cycle:

1. **Screenshot** → platform adapter captures screen
2. **Efficiency** → cache check, skip grounding if hit
3. **Grounding** → 3-expert merge (OpenCV + Tesseract + AT-SPI2)
4. **Safety(screen)** → check screen for injection attacks
5. **Planning** → subtask decomposition + app knowledge + lessons
6. **Claude API** → `client.beta.messages.create()` with `computer_20251124` tool
7. **Safety(action)** → validate proposed action before execution
8. **Execution** → coordinate refinement → timing wait → execute → fallback chain
9. **Verification** → 3-tier (SSIM diff → rule-based → Claude visual) + reflection
10. **Memory** → update working/episodic/semantic layers

### Module Structure

Each module under `cue/` follows the pattern: individual components + an `enhancer.py` orchestrator.

| Module | Purpose | Key Classes |
|--------|---------|-------------|
| `grounding/` | UI element detection | `GroundingEnhancer`, `OpenCVGrounder`, `TextGrounder`, `SourceMerger` |
| `execution/` | Action execution pipeline | `ExecutionEnhancer`, `CoordinateRefiner`, `TimingController`, `FallbackChain` |
| `verification/` | Result verification | `VerificationOrchestrator`, `Tier1Verifier`, `Tier2Verifier`, `ReflectionEngine` |
| `planning/` | Task decomposition | `PlanningEnhancer`, `AppKnowledgeBase` |
| `memory/` | Learning across episodes | `ThreeLayerMemory`, `WorkingMemory`, `EpisodicMemory`, `SemanticMemory` |
| `safety/` | Action filtering | `SafetyGate` |
| `efficiency/` | Performance optimization | `EfficiencyEngine`, `StepOptimizer`, `ContextManager` |
| `platform/` | OS abstraction | `EnvironmentAbstraction` (ABC), `LinuxEnvironment`, `WindowsEnvironment` |

### Key Types (cue/types.py)

All inter-module data flows through dataclasses defined in `types.py`. Key types:
- `Action` / `ActionResult` — execution units with type, coordinate, text
- `UIElement` / `ElementMap` — detected UI elements with bbox and confidence
- `EnhancedContext` — grounding output passed to Claude API
- `StepRecord` / `Episode` / `TaskResult` — execution history
- `VerificationResult` — tier number, success, confidence, reason

### Configuration (cue/config.py)

Pydantic `BaseModel` nested config. Each module has its own config class with an `EnhancerLevel` (OFF/BASIC/FULL) to enable/disable it. Load from YAML: `CUEConfig.load("cue.yaml")`.

### Knowledge Base (cue/knowledge/)

24 YAML files with app-specific shortcuts, menus, workflows, and pitfalls (Chrome, VSCode, Excel, etc.). Consumed by `AppKnowledgeBase` in the planning module.

## Conventions

- **Async everywhere**: all agent loop methods, platform calls, and memory operations are `async def`
- **pytest-asyncio**: tests use `asyncio_mode = "auto"` — just write `async def test_*`
- **Claude API**: use `client.beta.messages.create()` with `betas=["computer-use-2025-11-24"]` and tool type `computer_20251124`
- **Model ID**: `claude-sonnet-4-6` (not the dated variant)
- **Line length**: 100 chars (ruff config)
- **PIL/numpy**: screenshot functions return `PIL.Image`; conversion to numpy happens at consumption site with `np.array(img) if not isinstance(img, np.ndarray) else img`

## VPS Testing

Live testing on Vultr VPS (158.247.210.200) with Xvfb + xterm:
- Code at `/opt/cue_enhancer/`, venv at `venv/`
- `DISPLAY=:99`, API key in `.env` (format: `export ANTHROPIC_API_KEY=...`)
- Use `source venv/bin/activate && source .env` before running
- VPS is Python 3.10 (pyproject says 3.11+ but works via manual pip install)
