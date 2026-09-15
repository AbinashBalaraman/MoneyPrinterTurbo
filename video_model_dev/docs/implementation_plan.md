# Goal Video Quality & Puppet Stage Platform Implementation Plan

## Executive Summary
The goal is to elevate our stickman engine from a simple 512x512 plain-background prototype to a full **Puppet Stage Platform** capable of producing the cinematic quality, perspective, and detailed narrative scenes seen in `goal_videos/` (`dark-theme-demo.mp4` and `light-theme-demo.mp4`).

---

## Detailed Inspection Findings of `goal_videos/`

We extracted and analyzed frame-by-frame captures across both 10-second reference clips (`dark-theme-demo.mp4` and `light-theme-demo.mp4`):

### 1. Video Specifications
- **Resolution**: 1280x720 (16:9 widescreen HD).
- **Framerate**: 24.0 fps progressive.
- **Duration**: 10.0 seconds (240 frames each).

### 2. Visual Themes & Color Palettes
- **Light Theme**:
  - Background: Off-white parchment/subtle textured cream (`#F4F4F2`).
  - Stickmen: Ink-black (`#111111`) with rounded joint caps and soft ground contact drop shadows.
  - Accent Color: Vibrant vermillion red (`#E53935`) used for narrative emphasis (speech bubbles, falling gavel, fluid ribbon splash).
  - Perspective Grid: Clean 1-point linear perspective floorboards and ceiling vanishing lines.
- **Dark Theme**:
  - Background: Pure deep cosmic black (`#0A0A0E`).
  - Stickmen: Solid white bodies (`#FFFFFF`) with expressive facial features (eyes, angry eyebrows, gasping mouths).
  - Accents: Glowing lavender/purple organic splines (`#8B72D6`), vibrant red cages (`#D32F2F`), red stamps with big 'X' brush strokes.

### 3. Key Scene Archetypes Identified
1. **The Hand-Held Prop Scene** (`light_1s.png`): Character holds a rounded red speech bubble in two hands, while a companion character reaches forward.
2. **The 1-Point Perspective Hall** (`light_5s.png`): 3 pairs of receding black classical pillars with capital moldings, ornate baroque mirror frame in center, floorboard lines radiating from vanishing point.
3. **The Gavel Smash & Destruction** (`light_7s.png`, `light_8s.png`): A giant red gavel slams down; pillars crumble into polygonal rubble; ground and ceiling fracture with crack splinters; kinetic text "NOT A VERDICT" appears.
4. **The Accusatory Split-Screen** (`dark_5s.png`): 3-panel vertical layout; left panel shows a crowd of grey stickmen pointing fingers at a central defiant white stickman; middle shows a letter with a red X; right shows a document being stamped by a giant red hand.
5. **The Prison Cage in Agony** (`dark_8s.png`): 3D perspective red cage bars with keyhole padlock; white stickman kneeling inside holding his head in distress.
6. **The Neural Void / Thought Bubble** (`dark_1s.png`, `dark_3s.png`): Dynamic curving purple splines; glowing white thought bubble showing a stickman crawling on fractured ground.

---

## The Core Concept: A Solid Platform for Puppets

As suggested by the user, the core strategy is to treat the 2D video world like a **rich symbolic puppet platform** (analogous to a high-dimensional terminal/ASCII animation system with symbol layers and bone puppets):
- The puppets are actors with controllable joints, grip sockets, and expressive faces.
- The stage consists of modular, code-drawn 2.5D visual components: perspective floorboards, architectural pillars, fracture cracks, cages, prop kits, and panel dividers.
- External models or directors can compose complex story scenes by declaring stage layouts, props, and puppet actions.

---

## User Review Required

> [!IMPORTANT]
> **Resolution & Aspect Ratio Upgrade**: We propose upgrading the default renderer output from 512x512 square to **1280x720 widescreen (16:9)** to match the goal videos exactly, while maintaining 512x512 backward compatibility for tiny-footprint inference.

> [!TIP]
> **Modular 2.5D Vector Scenery**: Rather than hardcoding single scenes, we will implement modular, parameterized drawing components (`PerspectiveHall`, `PrisonCage`, `SplitScreenPanels`, `ShatterRubble`, `ThoughtBubble`, `HandHeldProps`) that can be combined declaratively.

---

## Proposed Architectural Changes

```
src/
├── rig.py                  # Existing FK + kinematics (preserved)
├── data_gen.py             # Existing procedural motions (preserved)
├── catalog.py              # Extended with expressive actions (kneel, crawl, point, hold_prop)
├── parser.py               # Extended with scenic and prop keywords
├── sequencer.py            # Compositional multi-actor sequencer (preserved)
├── mcp_server.py           # Extended with scene building tools
├── stage/                  # [NEW] Puppet Stage & Scenery Platform
│   ├── __init__.py
│   ├── theme.py            # Light & Dark theme definitions (colors, paper texture, glow)
│   ├── perspective.py      # 1-point perspective camera, floorboards, vanishing lines
│   ├── props.py            # Speech bubble, gavel, ornate frame, cage, pillars, rubble, stamps
│   ├── effects.py          # Ground cracks, fluid splashes, glowing spline web, drop shadows
│   ├── panels.py           # Split-screen comic panels & thought bubbles
│   └── text_overlay.py     # Kinetic typography ("NOT A VERDICT", etc.)
└── stage_renderer.py       # [NEW] 1280x720 HD Layered Renderer composing stage + puppets
```

---

## Verification & Demonstration Plan

### Automated Verification
- Unit tests verifying the 1280x720 stage renderer, perspective projection math, prop attachment to puppet wrists, and panel division.
- Benchmarking render latency per 720p frame.

### Visual Demonstration
- Generate two reproduction demo videos matching the goal videos:
  1. `output_goal_light_demo.mp4`: Light theme with perspective pillars, ornate frame, speech bubble handoff, gavel strike, pillar crumbling, and "NOT A VERDICT" typography.
  2. `output_goal_dark_demo.mp4`: Dark theme with split-screen pointing crowd, stamped envelope, red cage with kneeling prisoner, and glowing thought bubble.
- Verify visual fidelity against `goal_videos/`.
