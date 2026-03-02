# CUE — Computer Use Enhancer

**모델을 바꾸지 않고, 모델이 더 잘 보고 · 판단하고 · 행동하도록 돕는 증강 레이어**
*An augmentation layer that helps Claude see better, plan better, and act better — without changing the model.*

[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![Claude API](https://img.shields.io/badge/Claude-Computer%20Use%20API-d97706.svg)](https://docs.anthropic.com/en/docs/computer-use)

---

## 🎯 What is CUE?

CUE (Computer Use Enhancer) is an open-source augmentation middleware that sits on top of the Claude Computer Use API. It does not replace or retrain Claude — it makes Claude significantly better at interacting with desktop environments by addressing the systematic failure patterns that cause AI agents to fail roughly 27.5% of the time.

CUE wraps Claude's `computer_20251124` tool with six enhancement modules: improved visual grounding, hierarchical planning, precise execution, multi-tier verification, persistent experience memory, and token/step efficiency optimization. Each module is independently togglable, measurable, and designed to contribute 2–5 percentage points of improvement to task success rates.

The key insight: Claude Sonnet 4.6 already achieves human-level accuracy on OSWorld (72.5%). CUE targets the remaining gap — the systematic failures in grounding, planning, and execution — to push that number to 85% and beyond.

---

## 🔍 The Problem

Current AI computer use agents, including the best available models, fail on roughly 27.5% of desktop tasks. Analysis of failure patterns reveals five root causes:

```
GUI Grounding failures   ████████████████████████████████████  35%
Planning failures        ████████████████████████████          28%
Execution failures       ████████████████████                  20%
Navigation failures      ██████████                            10%
Impossible tasks         ███████                                7%
                         ├────┬────┬────┬────┬────┬────┬────┤
                         0%   5%  10%  15%  20%  25%  30%  35%
```

Beyond accuracy, there is a severe **efficiency gap**. The same tasks that humans complete in ~2 minutes with ~8 steps take AI agents ~20 minutes and ~18 steps — a 10x time overhead and 2.25x step overhead. Token costs run to ~60,000 tokens per task at current rates.

CUE addresses all five failure categories and the efficiency gap through targeted augmentation modules.

---

## 🧩 How CUE Solves It

CUE inserts an augmentation layer between the user's task and the Claude API:

```
                         ┌──────────────────────┐
                         │     User Task        │
                         └──────────┬───────────┘
                                    │
                                    ▼
                      ┌─────────────────────────┐
                      │   CUE Orchestrator      │
                      │ (Task Lifecycle Mgr)    │
                      └──────────┬──────────────┘
                                 │
             ┌───────────────────┼───────────────────┐
             │                   │                   │
    ┌────────▼──────────┐ ┌──────▼──────┐ ┌─────────▼──────────┐
    │ Grounding Enhancer│ │   Planning  │ │ Execution Enhancer │
    │  (see better)     │ │  Enhancer   │ │  (act better)      │
    └────────────────────┘ │(plan better)│ └────────────────────┘
                           └─────────────┘
             ┌───────────────────┼───────────────────┐
             │                   │                   │
    ┌────────▼──────────┐ ┌──────▼──────┐ ┌─────────▼──────────┐
    │ Verification Loop │ │  Experience │ │ Efficiency Engine  │
    │ (verify better)   │ │   Memory    │ │ (do it faster)     │
    └────────────────────┘ │(learn from  │ └────────────────────┘
                           │ mistakes)   │
                           └─────────────┘
                                  │
                                  ▼
                      ┌─────────────────────────┐
                      │   Claude API Call       │
                      │ (computer_20251124)     │
                      └──────────┬──────────────┘
                                 │
                                 ▼
                      ┌─────────────────────────┐
                      │ Desktop Environment     │
                      │(Docker+Xvfb / Local)    │
                      └─────────────────────────┘
```

**Grounding Enhancer** — Addresses the largest failure category (35%). Uses a Mixture-of-Grounding (MoG) architecture with three expert sources (visual/OpenCV, textual/OCR, structural/AT-SPI2) that vote on UI element locations. Detects text, buttons, icons, and interactive elements with sub-pixel precision.

**Planning Enhancer** — Addresses 28% of failures. Applies two-level hierarchical planning (goal decomposition → step sequencing) enriched by a community-maintained YAML knowledge base of app-specific menus, shortcuts, and workflows. Includes Reflexion-style lesson extraction from failed attempts.

**Execution Enhancer** — Addresses 20% of failures. Applies coordinate refinement (sub-pixel correction before click delivery), timing control for UI state transitions, and a fallback strategy chain (primary action → alternative interaction → keyboard shortcut → menu navigation) when actions do not produce expected state changes.

**Verification Loop** — Improves overall success rates across all failure types. Three-tier verification: semantic intent check (did the action make sense?), visual state diff (did the screen change as expected?), and functional outcome check (is the task goal achieved?). Catches silent failures before they compound.

**Experience Memory** — Provides long-term performance improvement. Persists task outcomes, failure patterns, and extracted lessons using context compression (26–54% token reduction). Subsequent runs on similar tasks benefit from accumulated knowledge without re-learning from scratch.

**Efficiency Engine** — Targets the step and time overhead gap. Applies keyboard shortcut prioritization, batch operation detection, and context window pruning to reduce average steps from 2.7x human to 1.5x human, and task time from ~20 minutes to ~5 minutes.

---

## 📊 Key Metrics & Targets

| Metric | Baseline | Target | Improvement |
|---|---|---|---|
| OSWorld accuracy | 72.5% | 85%+ | +12.5%p |
| Grounding precision (ScreenSpot) | ~18% | 35%+ | +17%p |
| Step efficiency | 2.7x human | 1.5x human | -44% |
| Task completion time | ~20 min | ~5 min | -75% |
| Token usage per task | ~60k | ~30k | -50% |

Each module contributes independently. Ablation studies are a first-class deliverable.

---

## 🏗️ Architecture & Design

CUE is structured in five layers with clear responsibility boundaries:

```
┌───────────────────────────────────────────────────────────────┐
│  Layer 1: User Interface                                      │
│  [ CLI (typer) ] [ Python API ] [ Dashboard ]                 │
├───────────────────────────────────────────────────────────────┤
│  Layer 2: Orchestrator                                        │
│  [ Task Lifecycle ] [ Module Router ] [ Safety Gate ]         │
├───────────────────────────────────────────────────────────────┤
│  Layer 3: Enhancement Modules (6x, independently togglable)   │
│  [ Grounding ] [ Planning ] [ Execution ]                     │
│  [ Verification ] [ Memory ] [ Efficiency ]                   │
├───────────────────────────────────────────────────────────────┤
│  Layer 4: Claude API Adapter                                  │
│  [ computer_20251124 tool ] [ Token budget manager ]          │
├───────────────────────────────────────────────────────────────┤
│  Layer 5: Environment Interface                               │
│  [ Docker+Xvfb ] [ Local desktop ] [ AT-SPI2 ]               │
└───────────────────────────────────────────────────────────────┘
```

### 10-Step Agent Loop

CUE orchestrates the agent through a deterministic 10-step loop:

1. **Screenshot capture** — Acquire current desktop state
2. **Efficiency check** — Cache hit? Skip grounding
3. **Grounding enhancement** — Parallel 3-expert (visual, text, structural)
4. **Safety gate** — Screen content injection check
5. **Planning enhancement** — Subtask decomposition + app knowledge + lessons
6. **Claude API call** — Enhanced context to language model
7. **Safety gate** — Proposed action validation
8. **Execution enhancement** — Coordinate refinement + timing control + fallback chain
9. **Verification** — 3-tier checks + reflection
10. **Memory update** — Working + episodic + reflexion layers

---

## 📦 Installation

### Prerequisites

- Python 3.11+
- Anthropic API key
- System dependencies (Linux/macOS):
  ```bash
  # Debian/Ubuntu
  sudo apt-get install tesseract-ocr xdotool xsel scrot

  # macOS
  brew install tesseract
  ```

### Install CUE

```bash
# Basic install
pip install -e .

# With development dependencies
pip install -e ".[dev]"

# With EasyOCR support
pip install -e ".[easyocr]"
```

### Set API Key

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## 🚀 Quick Start

### Python API

```python
from cue import CUEAgent

# Create agent with default config
agent = CUEAgent()

# Run a task
result = await agent.run("Sort column A in descending order in LibreOffice Calc")

# Access results
print(f"Success: {result.success}")
print(f"Steps taken: {len(result.steps)}")
print(f"Total tokens: {result.tokens_used}")
```

### Command Line

```bash
# Run a task
cue run "Take a screenshot and describe what you see"

# With custom config
cue run "Open Firefox" --config ./cue.yaml --max-steps 100

# Specify model
cue run "Navigate to google.com" --model claude-opus-4-6
```

### Configuration

Create a `cue.yaml` in your project directory:

```yaml
agent:
  model: "claude-sonnet-4-6"
  max_steps: 50
  timeout_seconds: 600

grounding:
  level: "full"
  visual_backend: "opencv"
  ocr_engine: "tesseract"
  confidence_threshold: 0.6

execution:
  level: "full"
  coordinate_snap_radius: 10
  enable_fallback_chain: true
  max_fallback_stages: 6

verification:
  level: "full"
  tier1_enabled: true
  tier2_enabled: true
  tier3_enabled: false  # Requires additional Claude API calls

memory:
  level: "full"
  persistence_dir: "./memory"

efficiency:
  level: "full"
  screenshot_cache_ttl: 5
```

---

## 📂 Module Reference

### `cue/platform/`
**OS abstraction layer** for Linux, Windows, and macOS. Provides unified interface for:
- Screenshot capture (xwd, ImageGrab, scrot)
- Input simulation (xdotool, xautomation, PyAutoGUI)
- System accessibility (AT-SPI2, UIAutomator, AppleScript)
- File system operations

**Key files:**
- `base.py` — Abstract base class for platform operations
- `linux.py` — Linux-specific implementation (Xvfb)
- `windows.py` — Windows-specific implementation

### `cue/grounding/`
**Visual, textual, and structural grounding** with 3-expert voting architecture.
- `visual.py` — OpenCV-based object detection, edge detection, corner finding
- `textual.py` — Tesseract/EasyOCR for OCR with bounding box generation
- `structural.py` — AT-SPI2 accessibility tree parsing for UI hierarchy
- `merger.py` — Mixture-of-Grounding voting and consensus algorithm
- `enhancer.py` — Orchestration and caching

**Confidence thresholds:** Visual ≥0.6, OCR ≥0.6, Structural ≥0.7 → consensus ≥2/3

### `cue/execution/`
**Execution enhancement** with coordinate refinement, timing, and fallback chains.
- `coordinator.py` — Coordinate snapping and sub-pixel refinement
- `timing.py` — Stability checks and UI state transition detection
- `fallback.py` — 6-stage fallback chain (click → right-click → keyboard → menu → ...)
- `validator.py` — Pre-execution validation (bounds checking, clickability)
- `enhancer.py` — Orchestration

**Fallback stages:**
1. Primary action with refined coordinates
2. Alternative interaction (right-click, double-click)
3. Keyboard navigation (Tab, arrow keys)
4. Keyboard shortcut (Ctrl+S, Alt+F4)
5. Menu navigation (Alt+F → File menu)
6. Text input as last resort

### `cue/verification/`
**Three-tier verification** with reflection and checkpoints.
- `tier1.py` — Semantic intent check (action validity)
- `tier2.py` — Visual state diff (SSIM-based screen change detection)
- `tier3.py` — Claude visual verification (functional outcome check)
- `reflection.py` — Failure analysis and lesson extraction
- `checkpoint.py` — State snapshots for rollback
- `orchestrator.py` — Tier coordination

**SSIM diff threshold:** 0.005 (screen changed) vs 0.001 (minor/no change detected)

### `cue/planning/`
**Hierarchical planning** with app knowledge base.
- `planner.py` — Goal decomposition and step sequencing
- `knowledge.py` — YAML-based app knowledge: menus, shortcuts, workflows, pitfalls
- `enhancer.py` — Planning orchestration with Reflexion

**Knowledge base includes 24+ applications:**
Firefox, Chrome, LibreOffice Calc, Writer, Outlook, Gmail, VS Code, Vim, Bash, PowerShell, Terminal, Finder, Windows Explorer, System Settings, Calendar, Maps, and more.

### `cue/memory/`
**Three-layer memory** with compression and reflexion.
- `working.py` — Current task context (active window, recent actions)
- `episodic.py` — Historical task outcomes and failure logs
- `semantic.py` — Generalized patterns and task templates
- `manager.py` — Memory coordination and pruning
- `compression.py` — ACON-style context compression (26–54% reduction)
- `reflexion.py` — Automatic lesson extraction from failures

**Compression:** Reduces verbose context to essential facts; token savings compound across tasks.

### `cue/safety/`
**Action safety gate** with three-level classification.
- `gate.py` — Classifies actions as safe (allowed), confirm (needs approval), blocked (dangerous)

**Safety rules:**
- Blocked: `rm -rf /`, `dd if=/dev/zero`, password resets without verification
- Confirm: File deletion, system shutdown, credential entry
- Safe: UI navigation, text entry, standard app operations

### `cue/efficiency/`
**Efficiency engine** for step and token optimization.
- `step_optimizer.py` — Shortcut prioritization and batch operation detection
- `context.py` — Working memory window pruning and summarization
- `latency.py` — Timing predictions for UI transitions
- `enhancer.py` — Orchestration

**Optimizations:**
- Detect batch operations (multi-file selection before delete)
- Prioritize keyboard shortcuts over mouse navigation
- Cache repeated screenshots (5s TTL default)
- Compress task context with sliding window

### `cue/benchmark/`
**OSWorld-compatible benchmark framework** for evaluation and ablation studies.
- `runner.py` — Task execution harness
- `metrics.py` — Success rate, step count, token usage, time
- `checkers.py` — Outcome verification (screenshot matching, OCR verification)
- `ablation.py` — Per-module contribution analysis
- `analysis.py` — Statistical aggregation and reporting
- `task_loader.py` — OSWorld dataset integration

---

## 🛠️ VPS Setup (Ubuntu)

### Install System Dependencies

```bash
# Update and install base tools
sudo apt-get update && sudo apt-get install -y \
  python3.11 python3.11-venv python3-pip \
  tesseract-ocr xdotool xsel scrot \
  xvfb wmctrl xclip

# Create virtual environment
python3.11 -m venv venv
source venv/bin/activate
```

### Install CUE

```bash
git clone https://github.com/yonghwan1106/cue_enhancer.git
cd cue_enhancer
pip install -e .
```

### Run with Xvfb (Headless)

```bash
# Start Xvfb display server
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99

# Run agent
export ANTHROPIC_API_KEY="sk-ant-..."
cue run "Navigate to google.com and search for Python"
```

### Systemd Service (Optional)

Create `/etc/systemd/system/cue-agent.service`:

```ini
[Unit]
Description=CUE Agent Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/cue_enhancer
Environment="DISPLAY=:99"
Environment="ANTHROPIC_API_KEY=sk-ant-..."
ExecStart=/home/ubuntu/cue_enhancer/venv/bin/cue run
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable with: `sudo systemctl enable cue-agent && sudo systemctl start cue-agent`

---

## 📁 Project Structure

```
cue_enhancer/
├── cue/
│   ├── __init__.py                    # Main exports: CUEAgent, CUEConfig
│   ├── agent.py                       # 10-step orchestrator loop
│   ├── config.py                      # Pydantic configuration
│   ├── cli.py                         # Typer command-line interface
│   ├── types.py                       # Shared type definitions
│   │
│   ├── platform/                      # OS abstraction (Linux, Windows, macOS)
│   │   ├── base.py
│   │   ├── linux.py
│   │   └── windows.py
│   │
│   ├── grounding/                     # 3-expert visual grounding
│   │   ├── visual.py                  # OpenCV detector
│   │   ├── textual.py                 # OCR (Tesseract/EasyOCR)
│   │   ├── structural.py              # AT-SPI2 accessibility
│   │   ├── merger.py                  # Voting consensus
│   │   └── enhancer.py                # Orchestration
│   │
│   ├── execution/                     # Coordinate refinement + fallback
│   │   ├── coordinator.py             # Sub-pixel snapping
│   │   ├── timing.py                  # Stability detection
│   │   ├── fallback.py                # 6-stage chains
│   │   ├── validator.py               # Pre-execution checks
│   │   └── enhancer.py                # Orchestration
│   │
│   ├── verification/                  # 3-tier verification
│   │   ├── tier1.py                   # Semantic check
│   │   ├── tier2.py                   # Visual diff (SSIM)
│   │   ├── tier3.py                   # Claude verification
│   │   ├── reflection.py              # Lesson extraction
│   │   ├── checkpoint.py              # State snapshots
│   │   └── orchestrator.py            # Tier coordination
│   │
│   ├── planning/                      # Hierarchical planning + KB
│   │   ├── planner.py                 # Goal decomposition
│   │   ├── knowledge.py               # App knowledge base
│   │   └── enhancer.py                # Orchestration
│   │
│   ├── memory/                        # 3-layer memory system
│   │   ├── working.py                 # Current task context
│   │   ├── episodic.py                # Historical outcomes
│   │   ├── semantic.py                # Generalized patterns
│   │   ├── manager.py                 # Coordination
│   │   ├── compression.py             # Token reduction
│   │   └── reflexion.py               # Lesson extraction
│   │
│   ├── safety/                        # Action safety gate
│   │   └── gate.py                    # safe/confirm/blocked classifier
│   │
│   ├── efficiency/                    # Step/token optimization
│   │   ├── step_optimizer.py          # Shortcut prioritization
│   │   ├── context.py                 # Memory pruning
│   │   ├── latency.py                 # Timing predictions
│   │   └── enhancer.py                # Orchestration
│   │
│   ├── knowledge/                     # App knowledge YAML files
│   │   ├── firefox.yaml
│   │   ├── libreoffice.yaml
│   │   ├── vs_code.yaml
│   │   └── ... (24+ apps)
│   │
│   ├── advanced/                      # OmniParser, GUI-Actor integrations
│   │   └── omniparser.py
│   │
│   └── benchmark/                     # OSWorld evaluation
│       ├── runner.py
│       ├── metrics.py
│       ├── checkers.py
│       ├── ablation.py
│       ├── analysis.py
│       └── task_loader.py
│
├── tests/                             # Unit and integration tests
│   ├── test_grounding.py
│   ├── test_execution.py
│   ├── test_verification.py
│   └── ...
│
├── pyproject.toml                     # Build config and dependencies
├── cue.yaml.example                   # Configuration template
├── README.md                          # This file
└── LICENSE                            # MIT license
```

---

## 🧪 Testing & Development

### Run Tests

```bash
# All tests
pytest

# With coverage
pytest --cov=cue --cov-report=html

# Specific module
pytest tests/test_grounding.py -v
```

### Type Checking

```bash
mypy cue/
```

### Code Formatting

```bash
ruff check cue/
ruff format cue/
```

### Benchmark Evaluation

```bash
# Run OSWorld benchmark (100 tasks)
python -m cue.benchmark.runner --dataset osworld --num-tasks 100

# Ablation study (per-module contribution)
python -m cue.benchmark.ablation --module grounding --num-tasks 50
```

---

## 📖 Documentation

- **[Architecture Design](cue-enhancer-design.md)** — Deep dive into each module
- **[API Reference](docs/api.md)** — Complete function signatures
- **[App Knowledge Base](cue/knowledge/)** — Keyboard shortcuts, menus, workflows
- **[Configuration Guide](docs/configuration.md)** — All config options explained

---

## 🤝 Contributing

Contributions are welcome! Areas of impact:

1. **App Knowledge Base** — Add YAML files for new applications (shortcuts, menus, workflows)
2. **Platform Support** — Extend platform abstraction for macOS improvements
3. **Grounding Models** — Integrate OmniParser V2 or GUI-Actor-7B
4. **Safety Rules** — Expand dangerous action detection
5. **Benchmarks** — Add OSWorld tasks and evaluation metrics

See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

---

## 📜 License

MIT License — see [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- Built on Claude's Computer Use API by Anthropic
- OSWorld benchmark from arXiv:2404.08606
- Accessibility via AT-SPI2, UIAutomation, AppleScript
- OCR via Tesseract and EasyOCR communities

---

## 📞 Support

- **Issues** — Report bugs on GitHub Issues
- **Discussions** — Ask questions on GitHub Discussions
- **Email** — Contact the team at cue-project@anthropic.com

---

**Status:** CUE is in active development. Phase 1 (core modules) is feature-complete. Phase 2 (Tier 3 verification, advanced grounding) is in progress. Phase 3 (professional software support) is planned for Q2 2026.

Last updated: 2026-03-02
