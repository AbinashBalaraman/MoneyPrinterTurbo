"""Agentic Story Director generating structured 5-phase episodic short-form scripts with narrative continuity."""

from __future__ import annotations

from typing import Any, Optional

from src.director.character import CharacterRegistry
from src.director.compiler import PromptCompiler
from src.director.pacing import PacingBudgeter, PacingRhythm
from src.models import (
    CharacterProfile,
    DialogueLine,
    EngagementPhase,
    EpisodeManifest,
    SceneBeat,
    SeriesState,
)


class StoryDirector:
    """Narrative director producing structured 30-60s multi-scene episodic scripts.
    
    Enforces the 5-phase retention arc, 140-160 WPM pacing budget, character reference
    binding, and narrative continuity across multi-episode story arcs.
    """

    def __init__(
        self,
        character_registry: Optional[CharacterRegistry] = None,
        pacing_budgeter: Optional[type[PacingBudgeter]] = None,
        compiler: Optional[type[PromptCompiler]] = None,
    ) -> None:
        self.registry = character_registry or CharacterRegistry()
        self.budgeter = pacing_budgeter or PacingBudgeter
        self.compiler = compiler or PromptCompiler

    def direct_episode(
        self,
        series_state: SeriesState,
        episode_num: int,
        target_duration: float = 45.0,
        custom_plot: Optional[dict[str, Any]] = None,
        rhythm: PacingRhythm = PacingRhythm.PULSE_ACTION,
    ) -> EpisodeManifest:
        """Directs and compiles an episodic Short conforming to the 5-phase retention arc."""
        if not (self.budgeter.MIN_DURATION <= target_duration <= self.budgeter.MAX_DURATION):
            raise ValueError(f"Target duration {target_duration}s must be within [{self.budgeter.MIN_DURATION}, {self.budgeter.MAX_DURATION}]s")

        # Sync characters from series_state into registry if present
        if series_state.characters:
            for char_id, char_data in series_state.characters.items():
                if isinstance(char_data, CharacterProfile):
                    self.registry.register_character(char_data)
                elif isinstance(char_data, dict):
                    self.registry.register_character(CharacterProfile.model_validate(char_data))

        # Generate scene timeline with precise time cuts and non-linear duration curves
        timeline = self.budgeter.generate_scene_timeline(target_duration, rhythm=rhythm)

        # Build episodic narrative content
        plot_data = custom_plot or self._generate_episodic_narrative(
            series_state=series_state,
            episode_num=episode_num,
            target_duration=target_duration,
        )

        title = plot_data.get("title", f"{series_state.title} - Episode {episode_num}")
        premise = plot_data.get("premise", series_state.premise)
        cliffhanger = plot_data.get("cliffhanger", "The screen cuts to black as footsteps echo closer.")
        next_hook = plot_data.get("next_episode_hook", "Will the truth be uncovered in time?")
        micro_loop = plot_data.get("micro_loop")
        loop_phrase = plot_data.get("loop_phrase")
        scene_narratives = plot_data.get("scenes", [])

        # Compile SceneBeat objects
        scenes: list[SceneBeat] = []
        for idx, t_spec in enumerate(timeline):
            n_data = scene_narratives[idx] if idx < len(scene_narratives) else self._default_scene_narrative(t_spec, plot_data)

            phase = t_spec["phase"]
            t_start = t_spec["time_start"]
            t_end = t_spec["time_end"]
            dur = t_spec["duration"]
            target_words = t_spec["target_words"]

            narration = n_data.get("narration", "")
            dialogue_raw = n_data.get("dialogue")
            dialogue: Optional[DialogueLine] = None
            if isinstance(dialogue_raw, dict):
                dialogue = DialogueLine.model_validate(dialogue_raw)
            elif isinstance(dialogue_raw, DialogueLine):
                dialogue = dialogue_raw

            action_desc = n_data.get("action_desc", "")
            camera_dir = n_data.get("camera_directive", "Low angle dynamic tracking shot")
            bound_chars = n_data.get("bound_characters", [])
            env = n_data.get("environment", "Dimly lit gritty urban corridor with neon reflections")

            # Ensure narration fits pacing without dumb truncation or canned fillers
            narration = self._align_narration_to_budget(narration, dur, target_words)

            # Compile decoupled prompts
            action_prompt, video_prompt = self.compiler.compile_scene_prompts(
                situational_action=action_desc,
                duration=dur,
                bound_characters=bound_chars,
                camera_directive=camera_dir,
                environment=env,
                dialogue=dialogue,
            )

            beat = SceneBeat(
                scene_index=idx,
                time_start=t_start,
                time_end=t_end,
                narration=narration,
                dialogue=dialogue,
                action_prompt=action_prompt,
                video_prompt=video_prompt,
                bound_characters=bound_chars,
                phase=phase,
                camera_directive=camera_dir,
            )
            scenes.append(beat)

        # Get active character profiles
        all_bound = {c for s in scenes for c in s.bound_characters}
        char_profiles: list[CharacterProfile] = []
        for name in all_bound:
            char = self.registry.get_character(name)
            if char:
                char_profiles.append(char)

        manifest = EpisodeManifest(
            series_id=series_state.series_id,
            season_num=series_state.current_season,
            episode_num=episode_num,
            title=title,
            premise=premise,
            target_duration=target_duration,
            scenes=scenes,
            character_profiles=char_profiles,
            cliffhanger=cliffhanger,
            next_episode_hook=next_hook,
            micro_loop=micro_loop,
            loop_phrase=loop_phrase,
        )

        # Advance series state
        series_state.advance_episode(manifest)

        return manifest

    def _align_narration_to_budget(self, text: str, duration: float, target_words: int) -> str:
        """Calibrates narration text so that its word count satisfies 140-160 WPM syntactically."""
        return self.budgeter.adjust_narration_syntactically(text, duration)

    def _generate_episodic_narrative(
        self, series_state: SeriesState, episode_num: int, target_duration: float
    ) -> dict[str, Any]:
        """Generates continuous dramatic episodic plot data linking across episodes 1, 2, 3+."""
        characters = self.registry.list_characters()
        main_char = characters[0].name if characters else "Detective Rex Vance"
        second_char = characters[1].name if len(characters) > 1 else "Dr. Aris Thorne"
        ally_char = characters[2].name if len(characters) > 2 else "Maya Lin"

        # Arc configuration based on episode index
        if episode_num == 1:
            return self._arc_part1(main_char, second_char, ally_char, series_state)
        elif episode_num == 2:
            return self._arc_part2(main_char, second_char, ally_char, series_state)
        elif episode_num == 3:
            return self._arc_part3(main_char, second_char, ally_char, series_state)
        else:
            return self._arc_generic(main_char, second_char, ally_char, episode_num, series_state)

    def _arc_part1(self, p1: str, p2: str, p3: str, state: SeriesState) -> dict[str, Any]:
        """Part 1: The Inciting Anomaly & The Perimeter Breach."""
        return {
            "title": "The Cipher Protocol",
            "premise": "A temporal chronometer ticks backwards at a locked vault crime scene.",
            "cliffhanger": f"Laser sights lock onto [{p1}]'s chest as the heavy blast doors slam shut.",
            "next_episode_hook": f"Can [{p1}] survive the execution squad trapped inside the subterranean vault?",
            "micro_loop": "Nobody could explain how the breach began, except...",
            "loop_phrase": "Because when the pocket watch ticks backwards, the cycle begins anew.",
            "scenes": [
                # Phase 1: Hook (0-3s)
                {
                    "narration": f"The brass pocket watch was ticking backwards inside the vault.",
                    "action_desc": f"[{p1}] crouches over a cracked vault floor, holding a glowing brass pocket watch whose hands spin counter-clockwise.",
                    "camera_directive": "Extreme close-up snap zoom onto frantic character expression",
                    "bound_characters": [p1],
                    "environment": "Cold subterranean bank vault with shattered concrete",
                },
                # Phase 2: Rising Tension (3-13s, 2 scenes)
                {
                    "narration": f"Security feeds showed no one entered, yet the reinforced vault door stood open.",
                    "action_desc": f"[{p1}] glances up at broken security monitors sparking on the wall.",
                    "camera_directive": "Low angle Dutch tilt tracking shot",
                    "bound_characters": [p1],
                    "environment": "Sparks falling from dangling electrical conduits",
                },
                {
                    "narration": f"[{p3}] transmitted a warning from dispatch that the building was surrounded.",
                    "action_desc": f"[{p3}] furiously taps tactical console screens inside a mobile surveillance vehicle.",
                    "camera_directive": "Medium close-up over-the-shoulder shot",
                    "bound_characters": [p3],
                    "environment": "High-tech surveillance van with neon blue readouts",
                },
                # Phase 3: Complication (13-32s, 3 scenes)
                {
                    "narration": f"[{p1}] discovered the chronometer was counting down to an imminent temporal detonation.",
                    "action_desc": f"[{p1}] uses a tactical spectrometer to inspect the humming chronometer mechanism.",
                    "camera_directive": "Close-up macro lens on whirring gear wheels",
                    "bound_characters": [p1],
                    "environment": "Dim concrete room illuminated by amber warning flashes",
                },
                {
                    "narration": f"The signature carved into the titanium housing belonged to [{p2}].",
                    "action_desc": f"[{p1}] reveals the engraved initial logo of [{p2}] on the device chassis.",
                    "camera_directive": "Slow dramatic dolly push-in",
                    "bound_characters": [p1],
                    "environment": "Vault interior filling with dense cold condensation vapor",
                },
                {
                    # Environmental cutaway: pure atmospheric establishing beat without characters
                    "narration": "The emergency power grid severed, plunging the corridor into flashing red strobe lights.",
                    "action_desc": "Flashing red emergency strobe lights cast jagged shadows across the empty industrial corridor as steam hisses from overhead pipes.",
                    "camera_directive": "Rapid whip pan across the darkening chamber",
                    "bound_characters": [],
                    "environment": "Flashing red strobe lights painting industrial shadows",
                },
                # Phase 4: Climax / Twist (32-41s, 2 scenes)
                {
                    "narration": f"A hologram materialized in the dark, revealing [{p2}] watching in silence.",
                    "action_desc": f"A shimmering blue volumetric hologram of [{p2}] appears above the vault pedestal as [{p1}] watches intently.",
                    "camera_directive": "Two-shot perspective aligning hero and hologram",
                    "bound_characters": [p1, p2],
                    "environment": "Luminescent holographic projection piercing shadows",
                },
                {
                    # Mixed-mode direct dialogue beat
                    "narration": f"[{p2}] smiled coldly.",
                    "dialogue": DialogueLine(
                        speaker=p2,
                        text="The target was never the vault, Detective.",
                        emotion="cold sneer",
                    ),
                    "action_desc": f"The holographic projection of [{p2}] gestures toward the blast doors as [{p1}] draws his sidearm.",
                    "camera_directive": "High-speed tracking arc shot circling the two entities",
                    "bound_characters": [p1, p2],
                    "environment": "Sparks blasting from hydraulic door clamps",
                },
                # Phase 5: Cliffhanger / Loop (41-45s, 1 scene)
                {
                    "narration": f"Armed lasers locked onto [{p1}] as the heavy blast doors sealed shut.",
                    "action_desc": f"Red targeting lasers pierce the smoke, pinning [{p1}] against the sealed blast doors.",
                    "camera_directive": "Rapid pull-back crane shot through closing hydraulic teeth",
                    "bound_characters": [p1],
                    "environment": "Heavy reinforced steel doors grinding shut with intense smoke",
                },
            ],
        }

    def _arc_part2(self, p1: str, p2: str, p3: str, state: SeriesState) -> dict[str, Any]:
        """Part 2: The Reverse Pulse & Substation Infiltration (resolves Part 1 cliffhanger)."""
        return {
            "title": "The Zero Pulse",
            "premise": "Trapped in the vault, Rex triggers a temporal pulse to breach the blockade.",
            "cliffhanger": f"The substation core breaches, threatening to engulf the entire city sector in chronal fire.",
            "next_episode_hook": f"Can [{p1}] and [{p3}] stabilize the core before time itself collapses?",
            "micro_loop": "And through the blinding chronal fire, the only way forward was when...",
            "loop_phrase": "And through the smoke, the anomaly continues to pulse without end.",
            "scenes": [
                # Phase 1: Hook (0-3s, resolves Part 1 cliffhanger)
                {
                    "narration": f"[{p1}] detonated the chronometer's reverse pulse, freezing incoming bullets.",
                    "action_desc": f"[{p1}] slams the brass chronometer into the floor, generating a shimmering temporal shockwave that freezes tracer rounds in mid-air.",
                    "camera_directive": "360-degree bullet-time orbital camera sweep",
                    "bound_characters": [p1],
                    "environment": "Vault entrance suspended in crystalline zero-time distortion",
                },
                # Phase 2: Rising Tension (3-13s, 2 scenes)
                {
                    "narration": f"With time frozen, [{p1}] slipped through the armed security line.",
                    "action_desc": f"[{p1}] dashes past the frozen armed operatives and breaches the outer ventilation shaft.",
                    "camera_directive": "Handheld sprint POV tracking protagonist",
                    "bound_characters": [p1],
                    "environment": "Steamy industrial exhaust corridor with yellow sodium lamps",
                },
                {
                    "narration": f"[{p3}] hacked the city grid, locating [{p2}]'s secret broadcast hub.",
                    "action_desc": f"[{p3}] reroutes power conduits on the digital 3D holographic city grid map.",
                    "camera_directive": "Rapid cinematic dolly in toward holographic neon wireframe",
                    "bound_characters": [p3],
                    "environment": "Mobile command desk packed with glowing fiber optic cables",
                },
                # Phase 3: Complication (13-32s, 3 scenes)
                {
                    "narration": f"[{p1}] reached the electrical substation just as coolant lines were severed.",
                    "action_desc": f"[{p1}] kicks open the heavy substation grate into a cavern of roaring electrical generators.",
                    "camera_directive": "Low angle wide shot revealing massive generator columns",
                    "bound_characters": [p1],
                    "environment": "Vast electrical turbine hall filled with arcing blue electricity",
                },
                {
                    # Mixed-mode direct dialogue beat
                    "narration": f"[{p3}] patched through as reactor warning sirens screamed.",
                    "dialogue": DialogueLine(
                        speaker=p3,
                        text="Rex, the core is overloading! You have thirty seconds!",
                        emotion="panicked shout",
                    ),
                    "action_desc": f"[{p3}] reroutes glowing optical lines on her console as warning sirens flash.",
                    "camera_directive": "High angle bird's-eye tracking crane shot",
                    "bound_characters": [p3],
                    "environment": "Vibrating steel catwalk above glowing turbine pits",
                },
                {
                    "narration": f"Automated turrets deployed from the ceiling, tracking [{p1}] across the catwalk.",
                    "action_desc": f"Mechanical automated turrets deploy from the ceiling, tracking [{p1}] with red sensory beacons.",
                    "camera_directive": "Rapid snap zoom on deploying gun barrels",
                    "bound_characters": [p1],
                    "environment": "Steam vents hissing high pressure vapor across the catwalk",
                },
                # Phase 4: Climax / Twist (32-41s, 2 scenes)
                {
                    "narration": f"[{p1}] severed the primary conduit, cutting electrical power across five districts.",
                    "action_desc": f"[{p1}] drives an insulated crowbar into the master breaker, unleashing a blinding arc flash.",
                    "camera_directive": "Dramatic slow-motion explosion of sparks framing the hero",
                    "bound_characters": [p1],
                    "environment": "Cascading blue electrical arcs shattering glass control panels",
                },
                {
                    # Environmental cutaway: ancient secret chamber
                    "narration": "Behind the shattered breaker lay a secret chamber predating the modern grid.",
                    "action_desc": "The collapsed circuit panel exposes a hidden reinforced vault doorway inscribed with ancient glowing temporal runes.",
                    "camera_directive": "Slow cinematic push-in toward the illuminated portal",
                    "bound_characters": [],
                    "environment": "Dark subterranean chamber glowing with warm amber ancient runes",
                },
                # Phase 5: Cliffhanger / Loop (41-45s, 1 scene)
                {
                    "narration": f"The core breached, plunging the subterranean chamber into blinding chronal fire.",
                    "action_desc": f"A swirling vortex of white chronal energy ruptures from the portal floor beneath [{p1}].",
                    "camera_directive": "Rapid tilt up into the blinding vortex",
                    "bound_characters": [p1],
                    "environment": "Swirling white portal of raw temporal singularity",
                },
            ],
        }

    def _arc_part3(self, p1: str, p2: str, p3: str, state: SeriesState) -> dict[str, Any]:
        """Part 3: The Temporal Truth & The Infinite Loop (resolves Part 2 cliffhanger)."""
        return {
            "title": "The Infinite Loop",
            "premise": "Rex confronts Thorne inside the origin facility, discovering the shocking paradox.",
            "cliffhanger": f"As the machine activates, [{p1}] realizes he was the one who built it all along.",
            "next_episode_hook": f"Season 2: Can the paradox be broken, or is time doomed to repeat?",
            "micro_loop": "And every time the machinery resets into blinding white light...",
            "loop_phrase": "Because when the pocket watch ticks backwards, the cycle begins anew.",
            "scenes": [
                # Phase 1: Hook (0-3s, resolves Part 2 cliffhanger)
                {
                    "narration": f"[{p1}] caught the rusted beam as the floor gave way.",
                    "action_desc": f"[{p1}] catches an iron structural girder with one hand as white lightning erupts below.",
                    "camera_directive": "Dramatic low angle shot looking up at heroic grip",
                    "bound_characters": [p1],
                    "environment": "Deep chasm with swirling chronal light and falling debris",
                },
                # Phase 2: Rising Tension (3-13s, 2 scenes)
                {
                    "narration": f"Pulling himself up, [{p1}] stood inside the 1984 prototype laboratory.",
                    "action_desc": f"[{p1}] hoists himself onto the ancient marble floor of a preserved vintage laboratory.",
                    "camera_directive": "Wide pan across retro computer banks and analog oscilloscopes",
                    "bound_characters": [p1],
                    "environment": "Dusty retro-futuristic research lab with amber phosphor screens",
                },
                {
                    "narration": f"[{p3}] confirmed the laboratory did not exist on any blueprint.",
                    "action_desc": f"[{p3}] stares in disbelief at satellite scans showing an empty void where the lab sits.",
                    "camera_directive": "Medium close-up shot of bewildered technician",
                    "bound_characters": [p3],
                    "environment": "Mobile surveillance vehicle bathed in emergency green monitor glow",
                },
                # Phase 3: Complication (13-32s, 3 scenes)
                {
                    "narration": f"[{p2}] emerged from shadows holding the master chronal core.",
                    "action_desc": f"[{p2}] steps forward from behind glass containment cylinders, holding a glowing crystal orb.",
                    "camera_directive": "Slow tracked walking shot revealing antagonist",
                    "bound_characters": [p2],
                    "environment": "Glass containment cylinders bubbling with luminous green liquid",
                },
                {
                    # Mixed-mode direct dialogue beat
                    "narration": f"[{p2}] revealed the secret behind the fracture.",
                    "dialogue": DialogueLine(
                        speaker=p2,
                        text="Time isn't breaking, Rex. It's trying to heal.",
                        emotion="intellectual calm",
                    ),
                    "action_desc": f"[{p2}] activates the central console, projecting architectural diagrams across the room towards [{p1}] as [{p1}] steps forward in disbelief.",
                    "camera_directive": "Floating orbital tracking shot through projected blueprints",
                    "bound_characters": [p1, p2],
                    "environment": "Volumetric golden wireframe schematics filling the air",
                },
                {
                    "narration": f"The blueprints displayed [{p1}]'s signature dated forty years forward.",
                    "action_desc": f"[{p1}] recoils in shock, recognizing his own handwriting on the ancient parchment.",
                    "camera_directive": "Extreme close-up macro focus on handwriting signature",
                    "bound_characters": [p1],
                    "environment": "Flickering golden light illuminating horrified expression",
                },
                # Phase 4: Climax / Twist (32-41s, 2 scenes)
                {
                    # Mixed-mode direct dialogue beat
                    "narration": f"[{p2}] worked to preserve the temporal loop.",
                    "dialogue": DialogueLine(
                        speaker=p1,
                        text="Step away from that core, Thorne!",
                        emotion="defiant snarl",
                    ),
                    "action_desc": f"[{p2}] inserts the crystal core into the main engine housing while [{p1}] lunges forward to stop the activation.",
                    "camera_directive": "Dramatic counter-rotating camera move framing both characters",
                    "bound_characters": [p1, p2],
                    "environment": "Vast brass temporal engine spinning into hyper-velocity",
                },
                {
                    "narration": f"To stop disaster, [{p1}] had to reset the machine.",
                    "action_desc": f"[{p1}] steps toward the central chronometer console, reaching for the master activation switch.",
                    "camera_directive": "Low angle heroic push-in shot",
                    "bound_characters": [p1],
                    "environment": "Blinding golden resonance radiating from the machine core",
                },
                # Phase 5: Cliffhanger / Loop (41-45s, 1 scene)
                {
                    "narration": f"Because when the pocket watch ticks backwards, the cycle begins anew.",
                    "action_desc": f"[{p1}] presses the brass watch into the engine slot as time resets with a brilliant flash.",
                    "camera_directive": "Rapid whiteout zoom transitioning into opening frame",
                    "bound_characters": [p1],
                    "environment": "Brilliant lens flare whiteout swallowing the frame",
                },
            ],
        }

    def _arc_generic(self, p1: str, p2: str, p3: str, ep: int, state: SeriesState) -> dict[str, Any]:
        """Fallback generator for arbitrary episode index N."""
        return {
            "title": f"The Chrono Fracture Part {ep}",
            "premise": f"The investigation deepens as anomaly {ep} threatens the timeline.",
            "cliffhanger": f"The chronal shockwave expands, leaving [{p1}] trapped in a diverging reality.",
            "next_episode_hook": f"Can the diverging realities be merged in Episode {ep + 1}?",
            "micro_loop": f"And through the fracture in reality, the story begins again with...",
            "loop_phrase": "And the clock continues to count down.",
            "scenes": [
                {
                    "narration": f"The temporal rift expanded, threatening everything [{p1}] fought for.",
                    "action_desc": f"[{p1}] stares into the growing rift with determined posture.",
                    "camera_directive": "Wide low angle tracking shot",
                    "bound_characters": [p1],
                    "environment": "Fractured city street with floating debris",
                },
                {
                    "narration": f"[{p3}] reported anomalies rapidly multiplying across all five city sectors.",
                    "action_desc": f"[{p3}] analyzes cascading sensor warnings.",
                    "camera_directive": "Close-up on tactical screens",
                    "bound_characters": [p3],
                    "environment": "High-tech surveillance van",
                },
                {
                    "narration": f"[{p1}] knew that stopping the collapse required finding and confronting [{p2}].",
                    "action_desc": f"[{p1}] draws weapon and advances through the haze.",
                    "camera_directive": "Medium tracking shot",
                    "bound_characters": [p1],
                    "environment": "Smoky neon alleyway",
                },
                {
                    "narration": f"The device was counting down to an irreversible and catastrophic collapse.",
                    "action_desc": f"[{p1}] examines the ticking counter mechanism.",
                    "camera_directive": "Macro close-up",
                    "bound_characters": [p1],
                    "environment": "Flickering amber control room",
                },
                {
                    "narration": f"Without warning, [{p2}] stepped forward through the heavy veil of steam.",
                    "action_desc": f"[{p2}] emerges through a veil of steam.",
                    "camera_directive": "Dramatic reveal shot",
                    "bound_characters": [p2],
                    "environment": "Industrial steam pipe junction",
                },
                {
                    "narration": f"Neither spoke a word, but both understood the terrible cost of failure.",
                    "action_desc": f"[{p1}] and [{p2}] face each other across the gap.",
                    "camera_directive": "Two-shot Dutch angle",
                    "bound_characters": [p1, p2],
                    "environment": "Shattered glass bridge",
                },
                {
                    "narration": f"[{p1}] activated the counter-resonance charge to contain the breach.",
                    "action_desc": f"[{p1}] depresses the charge trigger.",
                    "camera_directive": "Rapid push-in",
                    "bound_characters": [p1],
                    "environment": "Blinding pulse of blue energy",
                },
                {
                    "narration": f"The anomaly imploded into a blinding vortex of raw light.",
                    "action_desc": f"The anomaly implodes into a singularity as [{p1}] and [{p2}] shield their eyes.",
                    "camera_directive": "Dynamic whip pan",
                    "bound_characters": [p1, p2],
                    "environment": "Singularity vortex",
                },
                {
                    "narration": f"And the brass chronometer continues to count down in the silence.",
                    "action_desc": f"[{p1}] stands silently in the ruined street as the device ticks in the rubble.",
                    "camera_directive": "Slow pull-back crane shot",
                    "bound_characters": [p1],
                    "environment": "Silent ruined street",
                },
            ],
        }

    def _default_scene_narrative(self, t_spec: dict[str, Any], plot_data: dict[str, Any]) -> dict[str, Any]:
        """Provides default scene narrative elements if timeline has more scenes than plot beats."""
        phase = t_spec["phase"]
        characters = self.registry.list_characters()
        main_char = characters[0].name if characters else "Subject"
        return {
            "narration": f"The tension mounted steadily as [{main_char}] observed the treacherous corridor.",
            "action_desc": f"[{main_char}] moves cautiously through the shadowy corridor, assessing potential hazards.",
            "camera_directive": "Smooth steadycam tracking shot",
            "bound_characters": [main_char],
            "environment": "Darkened urban corridor with moody ambient lighting",
        }
