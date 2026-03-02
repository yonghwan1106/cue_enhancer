# CUE — Computer Use Enhancer

**모델을 바꾸지 않고, 모델이 더 잘 보고 · 판단하고 · 행동하도록 돕는 증강 레이어**
*An augmentation layer that helps Claude see better, plan better, and act better — without changing the model.*

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![Claude API](https://img.shields.io/badge/Claude-Computer%20Use%20API-d97706.svg)](https://docs.anthropic.com/en/docs/computer-use)
[![OSWorld](https://img.shields.io/badge/OSWorld-72.5%25%20→%2085%25%2B-22c55e.svg)](https://os-world.github.io/)

---

## 🎯 What is CUE?

CUE (Computer Use Enhancer) is an open-source augmentation middleware that sits on top of the Claude Computer Use API. It does not replace or retrain Claude — it makes Claude significantly better at interacting with desktop environments by addressing the systematic failure patterns that cause AI agents to fail roughly 27.5% of the time.

CUE wraps Claude's `computer_20251124` tool with six enhancement modules: improved visual grounding, hierarchical planning, precise execution, multi-tier verification, persistent experience memory, and token/step efficiency optimization. Each module is independently togglable, measurable, and designed to contribute 2–5 percentage points of improvement to task success rates.

The key insight: Claude Sonnet 4.6 already achieves human-level accuracy on OSWorld (72.5%). CUE targets the remaining gap — the systematic failures in grounding, planning, and execution — to push that number to 85% and beyond.

---

## 🔍 The Problem

Current AI computer use agents, including the best available models, fail on roughly 27.5% of desktop tasks. Analysis of failure patterns (Agent S2, arXiv:2504.00906) reveals five root causes:

```
GUI Grounding failures   ████████████████████████████████████  35%
Planning failures        ████████████████████████████          28%
Execution failures       ████████████████████                  20%
Navigation failures      ██████████                            10%
Impossible tasks         ███████                                7%
                         ├────┬────┬────┬────┬────┬────┬────┤
                         0%   5%  10%  15%  20%  25%  30%  35%
```

Beyond accuracy, there is a severe **efficiency gap**. The same tasks that humans complete in ~2 minutes with ~8 steps take AI agents ~20 minutes and ~18 steps — a 10x time overhead and 2.25x step overhead (OSWorld-Human, arXiv:2506.16042). Token costs run to ~60,000 tokens per task at current rates.

CUE addresses all five failure categories and the efficiency gap through targeted augmentation modules.

---

## 🧩 How CUE Solves It

CUE inserts an augmentation layer between the user's task and the Claude API:

```
                         ┌─────────────────┐
                         │    User Task    │
                         └────────┬────────┘
                                  │
                                  ▼
                      ┌───────────────────────┐
                      │     CUE Orchestrator  │
                      │  (Task Lifecycle Mgr) │
                      └───────────┬───────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
    ┌─────────▼─────────┐ ┌──────▼──────┐ ┌──────────▼──────────┐
    │ Grounding Enhancer│ │  Planning   │ │ Execution Enhancer  │
    │  (see better)     │ │  Enhancer   │ │  (act better)       │
    └───────────────────┘ │(plan better)│ └─────────────────────┘
                          └─────────────┘
              ┌───────────────────┼───────────────────┐
              │                   │                   │
    ┌─────────▼─────────┐ ┌──────▼──────┐ ┌──────────▼──────────┐
    │ Verification Loop │ │ Experience  │ │ Efficiency Engine   │
    │ (verify everything│ │   Memory    │ │ (do it faster)      │
    └───────────────────┘ │(learn from  │ └─────────────────────┘
                          │  mistakes)  │
                          └──────┬──────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │      Claude API       │
                     │  (computer_20251124)  │
                     └───────────┬───────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │  Desktop Environment  │
                     │ (Docker+Xvfb / Local) │
                     └───────────────────────┘
```

**Grounding Enhancer** — Addresses the largest failure category (35%). Uses a Mixture-of-Grounding (MoG) architecture with three expert sources (visual/OpenCV, textual/OCR, structural/AT-SPI2) that vote on UI element locations. Phase 2 integrates OmniParser V2; Phase 3 integrates GUI-Actor-7B for professional software environments.

**Planning Enhancer** — Addresses 28% of failures. Applies two-level hierarchical planning (goal decomposition → step sequencing) enriched by a community-maintained YAML knowledge base of app-specific menus, shortcuts, and workflows. Includes Reflexion-style lesson extraction from failed attempts.

**Execution Enhancer** — Addresses 20% of failures. Applies coordinate refinement (sub-pixel correction before click delivery), timing control for UI state transitions, and a fallback strategy chain (primary action → alternative interaction → keyboard shortcut → menu navigation) when actions do not produce expected state changes.

**Verification Loop** — Improves overall success rates across all failure types. Three-tier verification: semantic intent check (did the action make sense?), visual state diff (did the screen change as expected?), and functional outcome check (is the task goal achieved?). Catches silent failures before they compound.

**Experience Memory** — Provides long-term performance improvement. Persists task outcomes, failure patterns, and extracted lessons using ACON-style context compression (26–54% token reduction). Subsequent runs on similar tasks benefit from accumulated knowledge without re-learning from scratch.

**Efficiency Engine** — Targets the step and time overhead gap. Applies keyboard shortcut prioritization, batch operation detection, and context window pruning to reduce average steps from 2.7x human to 1.5x human, and task time from ~20 minutes to ~5 minutes.

---

## 📊 Key Metrics Targets

| Metric | Current (Baseline) | Target | Improvement |
|---|---|---|---|
| OSWorld accuracy | 72.5% | 85%+ | +12.5%p |
| ScreenSpot-Pro grounding | ~18% | 35%+ | +17%p |
| Step efficiency | 2.7x human | 1.5x human | -44% |
| Task completion time | ~20 min | ~5 min | -75% |
| Token usage per task | ~60k | ~30k | -50% |

Each module contributes independently. Ablation studies are a first-class deliverable: Phase 3 includes a full per-module contribution report.

---

## 🗺️ Architecture

CUE is structured in five layers with clear responsibility boundaries:

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: User Interface                                    │
│  [ CLI (typer) ]  [ Python API (cue.run()) ]  [ Dashboard ] │
├─────────────────────────────────────────────────────────────┤
│  Layer 2: Orchestrator                                      │
│  [ Task Lifecycle ]  [ Module Router ]  [ Safety Gate ]     │
├─────────────────────────────────────────────────────────────┤
│  Layer 3: Enhancement Modules (6x, independently togglable) │
│  [ Grounding ] [ Planning ] [ Execution ]                   │
│  [ Verification ] [ Memory ] [ Efficiency ]                 │
├─────────────────────────────────────────────────────────────┤
│  Layer 4: Claude API Adapter                                │
│  [ computer_20251124 tool ]  [ Token budget manager ]       │
├─────────────────────────────────────────────────────────────┤
│  Layer 5: Environment Interface                             │
│  [ Docker+Xvfb sandbox ]  [ Local desktop ]  [ AT-SPI2 ]   │
└─────────────────────────────────────────────────────────────┘
```

---

## Quick Start

> Note: CUE is currently in active design and early implementation (Phase 1). The API below reflects the planned public interface from the technical specification. Implementation begins Month 1.

```python
from cue import CUEAgent

agent = CUEAgent(model="claude-sonnet-4-6")
result = await agent.run("Sort column A in descending order in LibreOffice Calc")
print(f"Success: {result.success}, Steps: {len(result.steps)}")
```

With module configuration:

```python
from cue import CUEAgent, CUEConfig

config = CUEConfig(
    grounding_expert="opencv",      # Phase 1: lightweight
    # grounding_expert="omniparser", # Phase 2: precise
    # grounding_expert="gui-actor",  # Phase 3: advanced
    planning_enabled=True,
    verification_tiers=3,
    memory_enabled=True,
    efficiency_mode="balanced",
)

agent = CUEAgent(model="claude-sonnet-4-6", config=config)
result = await agent.run("Merge cells A1:C1 and center the heading")
```

---

## Research Foundation

CUE is grounded in 18 peer-reviewed papers. The ten most directly relevant:

| # | Paper | arXiv | CUE Relevance |
|---|---|---|---|
| 1 | Agent S2: Compositional Generalist-Specialist Framework | [2504.00906](https://arxiv.org/abs/2504.00906) | Mixture-of-Grounding architecture; proven +6.5%p augmentation |
| 2 | GUI-Actor: Coordinate-Free Visual Grounding | NeurIPS 2025 | Phase 3 grounding backend; 7B model beats 72B baselines |
| 3 | OmniParser V2: Screen Parsing for GUI Agents | Microsoft 2025 | Phase 2 grounding; 60% latency reduction |
| 4 | OSWorld-Human: Human-Level Efficiency Benchmark | [2506.16042](https://arxiv.org/abs/2506.16042) | Quantifies 1.4–2.7x step overhead; Efficiency Engine target |
| 5 | PC-Agent: Hierarchical Multi-Agent Framework | [2502.14282](https://arxiv.org/abs/2502.14282) | 3-tier planning architecture reference |
| 6 | VeriSafe: Formal Logic-Based Pre-Verification | [2503.18492](https://arxiv.org/abs/2503.18492) | Safety Gate design; 98.33% pre-action accuracy |
| 7 | ACON: Adaptive Context Optimization | [2510.00615](https://arxiv.org/abs/2510.00615) | 26–54% token reduction with no performance loss |
| 8 | MGA: Memory-Based GUI Agent | [2510.24168](https://arxiv.org/abs/2510.24168) | Experience Memory module architecture |
| 9 | Reflexion: Language Agents with Verbal RL | [2303.11366](https://arxiv.org/abs/2303.11366) | Lesson extraction from failures; Planning Enhancer |
| 10 | Trustworthy GUI Agents Survey | [2503.23434](https://arxiv.org/abs/2503.23434) | Security threat taxonomy; CUE safety architecture |

Full reference list with contribution notes: [Appendix C of the design document](./cue-enhancer-design.md#appendix-c-full-reference-list).

---

## Roadmap

| Phase | Timeline | Focus | Target |
|---|---|---|---|
| **Phase 1: Foundation** | Month 1–2 | Docker sandbox, basic agent loop, OpenCV grounding, Execution Enhancer v1, Safety Gate v1 | Mini-benchmark baseline +5%p |
| **Phase 2: Core Modules** | Month 3–4 | AT-SPI2 structural grounding, Planning Enhancer + app knowledge (5 apps), 3-tier Verification, Experience Memory + ACON compression | +15%p over baseline, -30% tokens |
| **Phase 3: OSWorld Challenge** | Month 5–6 | Full OSWorld benchmark integration, Efficiency Engine, failure analysis, ablation study, paper draft | OSWorld > 78%, steps < 2x human |
| **Phase 4: Scale and Polish** | Month 7–12 | OmniParser V2 integration (optional), Windows platform support, community launch, 20+ app knowledge YAMLs | OSWorld > 85%, macOS support |

```
Month:  1     2     3     4     5     6     7     8     9    10    11    12
        ├─────┼─────┼─────┼─────┼─────┼─────┼─────┼─────┼─────┼─────┼─────┤
Phase 1 │█████████████                                                      │
Phase 2 │              ████████████████                                     │
Phase 3 │                              █████████████████                    │
Phase 4 │                                                ██████████████████ │
        └───────────────────────────────────────────────────────────────────┘
```

---

## Contributing

CUE is an open-source project and welcomes contributions at every level.

**Highest-value contribution: App knowledge YAML files.** The Planning Enhancer learns app-specific menu structures, keyboard shortcuts, and common workflows from community-maintained YAML files. If you know LibreOffice, GIMP, VS Code, or any other desktop application well, your knowledge YAML can directly improve task success rates for that application. See [Appendix B of the design document](./cue-enhancer-design.md#appendix-b-app-knowledge-yaml-schema) for the schema.

Other ways to contribute:
- Bug reports and test case submissions against the OSWorld benchmark suite
- Grounding expert implementations (new visual, textual, or structural backends)
- Platform support (Windows UIA integration, macOS AX API)
- Documentation, translations, and usage examples

Please open an issue before starting significant implementation work so we can coordinate.

**Repository**: [github.com/yonghwan1106/cue_enhancer](https://github.com/yonghwan1106/cue_enhancer)

---

## Design Document

The full technical specification is available at [`cue-enhancer-design.md`](./cue-enhancer-design.md) (7,979 lines). It covers:

- Chapter 0: Executive Summary and key metrics
- Chapters 3–8: Per-module architecture, algorithms, and pseudocode
- Chapter 9: Security and safety design (VeriSafe integration, prompt injection defense)
- Chapter 10: Cross-platform strategy (Linux → Windows → macOS)
- Chapter 11: Benchmarking strategy (OSWorld, ScreenSpot-Pro, OSWorld-Human)
- Chapter 12: Implementation plan and 4-phase roadmap with weekly milestones
- Appendix A: Public API reference
- Appendix B: App knowledge YAML schema and examples
- Appendix C: Full 18-paper reference list with contribution notes

---

## License

Apache License 2.0. See [LICENSE](./LICENSE) for details.

You are free to use, modify, and distribute CUE in commercial and non-commercial projects. Contributions are accepted under the same license.

---

*CUE: Bridging the gap between AI and human-level computer use.*
