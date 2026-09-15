# Project: Episodic Content Directing and Production Engine

## Architecture
The system is structured into four decoupled, modular subsystems:
1. **Directing & Architecture Subsystem (`docs/`, `src/director/`)**: Comprehensive open-source ecosystem survey (10 repos), S2P prompt decoupling architecture, persistent character profiles, 5-phase retention mechanics, 140–160 WPM pacing budgeter, and 3-part continuous episodic arc generator.
2. **FlowKit Integration Subsystem (`src/flowkit/`)**: Strict Pydantic schemas mirroring FlowKit API, asynchronous HTTP/REST client for `http://127.0.0.1:8100/api`, payload adapter, multi-phase generation orchestrator (Entities -> Stills -> Clips -> TTS -> Concat), and pre-flight schema validation script.
3. **Continuity & Automation Subsystem (`src/storage/`, `src/cli.py`, `README.md`)**: SQLite WAL-mode continuity database tracking series, character states, and episode arcs across runs, coupled with a production CLI for single and batch episode generation.
4. **E2E Testing & Hardening Subsystem (`tests/e2e/`)**: 4-Tier requirement-driven opaque-box test suite (≥150 tests) and Tier 5 white-box adversarial stress test coverage.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---|---|---|---|
| F1 | Ecosystem Survey Report | Structured evaluation of 10 video automation repos (MPT, ShortGPT, StoryDiffusion, etc.) | M1 | ORIGINAL_REQUEST §R1 |
| F2 | Architectural Continuity Patterns | Documentation of S2P prompt decoupling, entity reference models, and character persistence | M1 | ORIGINAL_REQUEST §R1 |
| F3 | Short-Form Engagement Arc & Timing | 5-phase retention arc definition and 140–160 WPM mathematical timing budget rules | M1 | ORIGINAL_REQUEST §R1 |
| F4 | Persistent Character Profile Registry | Data models and registry for recurring characters (visual traits, voice, seed, personality) | M1 | ORIGINAL_REQUEST §R2 |
| F5 | Episodic Story Director Engine | Core narrative directing engine generating structured multi-scene episodes (30–60s) | M1 | ORIGINAL_REQUEST §R2 |
| F6 | Decoupled Prompt & Scene Action Formatter | Isolates character appearance from scene actions, generating sub-clip timed prompts | M1 | ORIGINAL_REQUEST §R2 |
| F7 | 3-Part Continuous Episodic Arc | Programmatic generator for 3-part continuous arc demonstrating continuity across episodes | M1 | ORIGINAL_REQUEST §AC2 |
| F8 | FlowKit Pydantic Schemas & Client | Strict Pydantic models and asynchronous API client for http://127.0.0.1:8100/api | M2 | ORIGINAL_REQUEST §R3 |
| F9 | FlowKit Payload Validation Script | Automated validation script verifying payloads pass FlowKit validation without errors | M2 | ORIGINAL_REQUEST §AC3 |
| F10 | FlowKit End-to-End Orchestrator | Complete pipeline: entity registration, scene stills, video clips, TTS, and video assembly | M2 | ORIGINAL_REQUEST §R3 |
| F11 | Episodic SQLite Continuity Ledger | SQLite WAL ledger storing series history, character states, cliffhangers, and outputs | M3 | ORIGINAL_REQUEST §R4 |
| F12 | Daily Batch Automation CLI | Command-line interface for generating single and $N$ daily episodes in batch mode | M3 | ORIGINAL_REQUEST §R4 |
| F13 | User Documentation & CLI Guide | README.md documenting architecture, CLI commands, single/batch modes, and FlowKit integration | M3 | ORIGINAL_REQUEST §AC3 |
| F14 | Comprehensive E2E Test Suite | Opaque-box tests across Tiers 1-4 covering all features, boundaries, and scenarios | M4 | Acceptance Criteria |
| F15 | Adversarial Coverage Hardening | White-box stress tests, edge case verification, and resilience audit | M4 | Project Pattern Tier 5 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|---|---|---|---|
| M1 | Episodic Directing Engine & Ecosystem Analysis | `docs/ECOSYSTEM_SURVEY.md`, `src/models.py`, `src/director/` (`character.py`, `director.py`, `pacing.py`, `compiler.py`), `scripts/demo_3part_arc.py`, `tests/unit/test_director.py` | Survey complete | IN_PROGRESS |
| M2 | FlowKit & Video Generation Integration | `src/flowkit/` (`models.py`, `client.py`, `adapter.py`, `orchestrator.py`), `scripts/validate_flowkit_payloads.py`, `tests/unit/test_flowkit.py` | M1 interfaces | PLANNED |
| M3 | Daily Batch Automation CLI & Continuity Ledger | `src/storage/ledger.py`, `src/cli.py`, `README.md`, `tests/unit/test_ledger.py`, `tests/unit/test_cli.py` | M1, M2 | PLANNED |
| M4 | Final E2E Test Suite & Adversarial Hardening | `tests/e2e/` (Tiers 1-4), Tier 5 adversarial hardening, `TEST_READY.md` | M1-M3 | PLANNED |

## Interface Contracts

### 1. Director ↔ FlowKit Adapter
```python
class SceneBeat(BaseModel):
    scene_index: int
    time_start: float
    time_end: float
    narration: str
    action_prompt: str
    video_prompt: str
    bound_characters: list[str]

class EpisodeManifest(BaseModel):
    series_id: str
    episode_num: int
    title: str
    target_duration: float  # 30.0 - 60.0s
    scenes: list[SceneBeat]
    character_profiles: list[CharacterProfile]
    cliffhanger: str
    next_episode_hook: str
```

### 2. FlowKit Adapter ↔ FlowKit API
```python
# ProjectCreate: name, material, language, characters: list[CharacterInput]
# CharacterCreate: name, entity_type, description, voice_description, image_prompt
# VideoCreate: project_id, title, orientation="VERTICAL"
# SceneCreate: video_id, display_order, prompt, video_prompt, character_names
# SceneUpdate: narrator_text (via PATCH /api/scenes/{id})
# RequestCreate: type, orientation, scene_id, project_id, video_id
# NarrateVideoRequest: project_id, orientation="VERTICAL", mix=True, sfx_volume=0.4
```

### 3. CLI / Ledger ↔ Director
```python
class SeriesState(BaseModel):
    series_id: str
    title: str
    genre: str
    current_season: int
    current_episode: int
    characters: dict[str, Any]
    last_cliffhanger: Optional[str]
    unresolved_threads: list[str]
```

## Code Layout
```
shorts_content_engine/
├── docs/
│   └── ECOSYSTEM_SURVEY.md          # M1: 10-repo deep analysis & directing patterns
├── src/
│   ├── __init__.py
│   ├── models.py                    # Shared domain models (Series, Episode, Scene, Character)
│   ├── director/
│   │   ├── __init__.py
│   │   ├── character.py             # Character profile registry & attributes
│   │   ├── director.py              # 5-phase episodic story director & arc generator
│   │   ├── pacing.py                # Mathematical WPM budgeting & validator
│   │   └── compiler.py              # Prompt decoupling & FlowKit entity compiler
│   ├── flowkit/
│   │   ├── __init__.py
│   │   ├── models.py                # FlowKit Pydantic schemas (Project, Character, Scene, Request)
│   │   ├── client.py                # Asynchronous API client for http://127.0.0.1:8100/api
│   │   ├── adapter.py               # Adapts EpisodeManifest -> FlowKit payloads
│   │   └── orchestrator.py          # Multi-stage generation runner (Refs -> Stills -> Clips -> Audio -> Concat)
│   ├── storage/
│   │   ├── __init__.py
│   │   └── ledger.py                # SQLite WAL episodic continuity ledger
│   └── cli.py                       # Daily batch automation CLI
├── scripts/
│   ├── validate_flowkit_payloads.py # Pre-flight automated validation script
│   └── demo_3part_arc.py            # Generates 3-part continuous episodic arc
├── tests/
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_director.py         # Unit tests for story directing & character persistence
│   │   ├── test_flowkit.py          # Unit tests for FlowKit payload validation
│   │   ├── test_ledger.py           # Unit tests for SQLite continuity ledger
│   │   └── test_cli.py              # Unit tests for CLI batch generation
│   └── e2e/
│       ├── test_tier1_features.py   # Tier 1: Feature coverage (>=5 per feature)
│       ├── test_tier2_boundaries.py # Tier 2: Boundary & corner cases (>=5 per feature)
│       ├── test_tier3_pairwise.py   # Tier 3: Cross-feature combinations
│       └── test_tier4_scenarios.py  # Tier 4: Real-world application scenarios
├── pyproject.toml                   # Project dependencies & package configuration
└── README.md                        # Architectural documentation & CLI guide
```
