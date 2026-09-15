# Original User Request

## Initial Request — 2026-09-12T20:04:55Z

Build an automated episodic content directing and production engine for daily 30–60s Shorts featuring persistent recurring characters, intelligent script directing for smooth narrative flow, and integration with Google Flow (via local FlowKit API) for video generation.

Working directory: C:/Users/SATHYA TRADERS/Documents/Abi/Projects/shorts_content_engine
Integrity mode: development

## Requirements

### R1. Deep GitHub Ecosystem Survey & Directing Analysis
Research and analyze open-source GitHub projects in the video automation and agentic storytelling space (e.g., MoneyPrinterTurbo, ShortGPT, StoryDiffusion, AutoShorts, Remotion workflows, AI narrative directors). Document how leading repositories handle:
- Automated script generation with strong retention hooks and pacing.
- Multi-scene directing with visual scene descriptions decoupled from character appearance.
- Persistent character identity across multiple episodes.

### R2. Episodic Script & Content Directing Engine
Implement an agentic story director that produces daily episodic scripts (30s–60s) with neat narrative flow. The director must:
- Maintain persistent character profiles (visual appearance, personality, voice attributes, relationships).
- Generate structured multi-scene episodes following short-form engagement mechanics (hook, rising tension, climax/twist, call-to-action/cliffhanger).
- Output scene-by-scene visual action prompts, narrator/dialogue scripts, and character reference bindings.

### R3. FlowKit & Video Generation Integration
Integrate the directing engine with the running FlowKit local service (`http://127.0.0.1:8100/api`):
- Automatically format and register character and location reference entities with FlowKit.
- Convert director scene output into FlowKit project and scene specifications.
- Support end-to-end orchestration: reference generation, scene stills, video clips (Google Flow / Veo), narrator TTS synthesis, and video concatenation.

### R4. Daily Batch Automation CLI & Scheduling
Provide an automated CLI runner capable of generating $N$ daily episodes in batch mode, tracking episode continuity in a local database or state file, and packaging finished videos ready for publishing.

## Acceptance Criteria

### Comprehensive Research & Architecture Matrix
- [ ] Deliver a structured markdown report evaluating at least 8 relevant GitHub repositories with strengths, directing logic, and applicability to daily shorts.
- [ ] Include concrete architectural patterns for character continuity and visual coherence across recurring episodes.

### Script & Directing Engine Quality
- [ ] Programmatic generation of a 3-part continuous episodic arc showcasing character continuity across episodes.
- [ ] Generated scripts strictly adhere to 30–60 second timing budgets with explicit scene timestamps and shot descriptions.
- [ ] Character appearance descriptions are properly isolated from scene action descriptions (conforming to the reference-based prompt model).

### Integration & Execution Verification
- [ ] Automated validation script verifying that all generated project, character, and scene payloads pass FlowKit API validation without schema errors.
- [ ] End-to-end execution of a sample episode pipeline with testable outputs (scripts, storyboard frames, and assembled video project).
- [ ] Clear CLI commands documented in README.md for generating single episodes, batch episodes, and monitoring status.

## Follow-up — 2026-09-12T20:21:17Z

USER DIRECTIVE:
The user explicitly requests to establish a Debating / Adversarial Review Team on our current progress:
"tell the orchestrator to create a debating team on our progress make ateam mates analys and argue with each other to deside what is good and flwas how to improve and based on the debate result improve the product"

Please ensure the orchestrator immediately coordinates an adversarial debate/critique session among specialized personas (e.g., Creative Director vs. Pipeline Architect vs. Consistency/Fidelity Auditor):
1. Analyze current deliverables, architecture, and code.
2. Rigorously argue the pros and cons, identify flaws, edge cases, pacing issues, character prompt leakage, and integration weaknesses.
3. Formulate consensus recommendations on how to improve the product.
4. Execute concrete engineering and prompt improvements based directly on the debate results.

