"""Keyframe Pose Library for Smooth Stop-Motion Puppetry.

Defines anatomically solid, expressive key poses as frozen relative angle vectors
for the 14 bones, along with natural root height and stance-foot anchors.
"""

from dataclasses import dataclass
from typing import Dict, Optional
import numpy as np

from src.rig import REST_ANGLES, N_BONES


@dataclass(frozen=True)
class Pose:
    """Immutable definition of a puppet keyframe pose."""
    name: str
    angles: np.ndarray        # Shape (14,), radians
    root_y: float = 0.0       # Pelvis vertical offset from ground
    stance_anchor: Optional[str] = None  # "left_foot", "right_foot", "both_feet", or None
    description: str = ""


def _deg(degrees_list: list[float]) -> np.ndarray:
    """Converts a list of 14 angles in degrees to radians float32 array."""
    assert len(degrees_list) == 14, f"Expected 14 angles, got {len(degrees_list)}"
    return np.radians(np.array(degrees_list, dtype=np.float32))


# Curated, anatomically balanced keyframe poses
# Bone order:
# 0:spine, 1:chest, 2:neck, 3:head,
# 4:upperArmL, 5:lowerArmL, 6:upperArmR, 7:lowerArmR,
# 8:upperLegL, 9:lowerLegL, 10:footL,
# 11:upperLegR, 12:lowerLegR, 13:footR

_RAW_POSES = {
    # 1. Neutral & Stance
    "stand_relaxed": Pose(
        name="stand_relaxed",
        angles=_deg([
            0, 0, 0, 0,           # Spine & Head upright
            10, -15, -10, -15,    # Arms relaxed naturally at sides
            2, -4, 92,            # Left leg straight under body, foot flat
            2, -4, 92             # Right leg straight under body, foot flat
        ]),
        root_y=0.0,
        stance_anchor="both_feet",
        description="Relaxed resting standing posture."
    ),

    "squat_deep": Pose(
        name="squat_deep",
        angles=_deg([
            25, 12, -5, -5,       # Torso forward lean balancing CoM over feet
            40, -20, 36, -18,     # Arms forward counterbalance
            40, -99.5, 149.5,     # Left leg deep natural bend, foot flat on floor
            40, -99.5, 149.5      # Right leg deep natural bend, foot flat on floor
        ]),
        root_y=-0.15,
        stance_anchor="both_feet",
        description="Deep balanced squat with feet flat on ground and torso counterbalance."
    ),

    "stand_alert": Pose(
        name="stand_alert",
        angles=_deg([
            5, 5, 0, -5,          # Chest puffed, chin tucked
            45, -70, -45, 70,     # Fists raised near chest
            12, -10, 78,          # Left leg slightly forward
            -12, -10, 78          # Right leg back
        ]),
        root_y=0.0,
        stance_anchor="both_feet",
        description="Alert combat or attention stance."
    ),

    # 2. Locomotion Keyframes (Pose-to-Pose Walk/Run)
    "stride_contact_L": Pose(
        name="stride_contact_L",
        angles=_deg([
            6, 4, -2, -4,         # Forward torso lean
            -30, -15, 30, -20,    # Arms swinging in opposition
            22, -8, 95,           # Left leg heel strike forward (+X)
            -18, -12, 88          # Right leg pushing off behind (-X, toe grounded at -0.42)
        ]),
        root_y=0.0,               # Pelvis stays level with plant foot flat
        stance_anchor="left_foot",
        description="Walk keyframe: Left foot forward heel-strike."
    ),

    "stride_pass_L": Pose(
        name="stride_pass_L",
        angles=_deg([
            3, 2, 0, -3,          # Upright torso
            -8, -10, 8, -10,      # Arms passing neutral
            2, -4, 92,            # Left leg planted straight under body
            20, -45, 92           # Right leg bending and swinging through (dorsiflexed toe clearing floor)
        ]),
        root_y=0.0,               # Pelvis stays level with plant foot flat
        stance_anchor="left_foot",
        description="Walk keyframe: Left leg weight-bearing, right passing."
    ),

    "stride_contact_R": Pose(
        name="stride_contact_R",
        angles=_deg([
            6, 4, -2, -4,         # Forward torso lean
            30, -20, -30, -15,    # Arms swinging in opposition
            -18, -12, 88,         # Left leg pushing off behind (-X, toe grounded at -0.42)
            22, -8, 95            # Right leg heel strike forward (+X)
        ]),
        root_y=0.0,
        stance_anchor="right_foot",
        description="Walk keyframe: Right foot forward heel-strike."
    ),

    "stride_pass_R": Pose(
        name="stride_pass_R",
        angles=_deg([
            3, 2, 0, -3,          # Upright torso
            8, -10, -8, -10,      # Arms passing neutral
            20, -45, 92,          # Left leg bending and swinging through (dorsiflexed toe clearing floor)
            2, -4, 92             # Right leg planted straight under body
        ]),
        root_y=0.0,
        stance_anchor="right_foot",
        description="Walk keyframe: Right leg weight-bearing, left passing."
    ),

    # 2b. Backward Locomotion Keyframes (retreat facing forward, toe-first rear reach -X)
    "walkback_contact_L": Pose(
        name="walkback_contact_L",
        angles=_deg([
            -5, -3, 2, 3,         # Slight rearward lean (facing forward, stepping back)
            28, -15, -28, -20,    # Arms in opposition (left forward)
            -22, -8, 72,          # Left leg reaching back, toe-first strike
            16, -12, 92           # Right leg forward support, foot flat
        ]),
        root_y=-0.02,             # Pelvis dips to cushion toe strike
        stance_anchor="left_foot",
        description="Backward-walk keyframe: Left toe strikes behind (-X), facing forward."
    ),

    "walkback_pass_L": Pose(
        name="walkback_pass_L",
        angles=_deg([
            -2, -1, 0, 2,         # Near-upright torso
            10, -10, -10, -10,    # Arms passing neutral
            -3, -5, 90,           # Left leg weight-bearing under body
            -20, -45, 68          # Right leg swinging back through, toe down
        ]),
        root_y=-0.005,
        stance_anchor="left_foot",
        description="Backward-walk keyframe: weight over left, right swinging back."
    ),

    "walkback_contact_R": Pose(
        name="walkback_contact_R",
        angles=_deg([
            -5, -3, 2, 3,         # Slight rearward lean
            -28, -20, 28, -15,    # Arms in opposition (right forward)
            16, -12, 92,          # Left leg forward support, foot flat
            -22, -8, 72           # Right leg reaching back, toe-first strike
        ]),
        root_y=-0.02,
        stance_anchor="right_foot",
        description="Backward-walk keyframe: Right toe strikes behind (-X), facing forward."
    ),

    "walkback_pass_R": Pose(
        name="walkback_pass_R",
        angles=_deg([
            -2, -1, 0, 2,         # Near-upright torso
            -10, -10, 10, -10,    # Arms passing neutral
            -20, -45, 68,         # Left leg swinging back through, toe down
            -3, -5, 90            # Right leg weight-bearing under body
        ]),
        root_y=-0.005,
        stance_anchor="right_foot",
        description="Backward-walk keyframe: weight over right, left swinging back."
    ),

    # 3. Jump & Acrobatics
    "crouch_anticipate": Pose(
        name="crouch_anticipate",
        angles=_deg([
            25, 12, -5, -5,       # Deep forward torso tuck
            -35, -15, -35, -15,   # Arms cocked back for upward swing
            40, -99.5, 149.5,     # Left knee bent deep, foot flat
            40, -99.5, 149.5      # Right knee bent deep, foot flat
        ]),
        root_y=-0.15,             # Pelvis compresses low
        stance_anchor="both_feet",
        description="Deep crouch anticipation before jumping or lunging."
    ),

    "jump_takeoff": Pose(
        name="jump_takeoff",
        angles=_deg([
            -4, -2, 4, 2,         # Torso extended straight
            160, 15, 160, 15,     # Arms reaching upward towards sky
            10, -5, 75,           # Left leg extending through toes
            10, -5, 75            # Right leg extending through toes
        ]),
        root_y=0.08,              # Pelvis lifting off ground
        stance_anchor=None,
        description="Explosive vertical push-off."
    ),

    "jump_apex": Pose(
        name="jump_apex",
        angles=_deg([
            8, 5, -4, -6,         # Slight forward tilt at peak
            65, -35, 65, -35,     # Arms spread for flight balance
            20, -45, 65,          # Legs loosely tucked
            15, -40, 65
        ]),
        root_y=0.35,              # Maximum airborne altitude
        stance_anchor=None,
        description="Airborne apex at the top of a jump arc."
    ),

    "jump_land_absorb": Pose(
        name="jump_land_absorb",
        angles=_deg([
            15, 10, -5, -8,       # Torso absorbing impact
            30, -45, 30, -45,     # Arms forward for counterbalance
            30, -60, 50,          # Deep knee cushion
            30, -60, 50
        ]),
        root_y=-0.12,             # Pelvis dropped to cushion force
        stance_anchor="both_feet",
        description="Landing cushion absorbing shock with bent knees."
    ),

    # 4. Martial Arts & Action
    "guard_high": Pose(
        name="guard_high",
        angles=_deg([
            5, 8, -4, -6,         # Tight combat crouch
            65, -105, -60, 95,    # Gloves protecting chin and temples
            15, -10, 75,          # Left lead leg
            -15, -10, 75          # Right anchor leg
        ]),
        root_y=-0.02,
        stance_anchor="both_feet",
        description="Defensive boxing / martial arts high guard."
    ),

    "punch_windup": Pose(
        name="punch_windup",
        angles=_deg([
            -10, -12, 6, 8,       # Torso coiled back
            45, -90, -75, 115,    # Right fist cocked deep near ribs, left extended
            20, -15, 75,          # Weight shifted to rear right leg
            -20, -15, 75
        ]),
        root_y=-0.02,
        stance_anchor="both_feet",
        description="Anticipation coil loading kinetic energy for a punch."
    ),

    "punch_extend": Pose(
        name="punch_extend",
        angles=_deg([
            6, 4, -2, -4,         # Torso driving forward through neutral
            10, -85, 15, 45,      # Right arm extending forward halfway, left guard
            -5, -5, 75,
            5, -5, 75
        ]),
        root_y=-0.01,
        stance_anchor="left_foot",
        description="Intermediate breakdown pose for punch strike."
    ),

    "punch_impact": Pose(
        name="punch_impact",
        angles=_deg([
            18, 14, -8, -12,      # Torso lunging forward with full hip drive
            -20, -85, 95, 5,      # Right fist snapped fully straight forward, left guard
            -25, -20, 75,         # Front left leg braced forward
            25, -15, 75           # Rear right leg driving from ball of foot
        ]),
        root_y=-0.01,
        stance_anchor="left_foot",
        description="Crisp punch impact extension with full follow-through."
    ),

    "kick_chamber": Pose(
        name="kick_chamber",
        angles=_deg([
            -5, -8, 4, 6,         # Torso balanced back
            35, -75, -45, 65,     # Guard raised for balance
            55, -110, 45,         # Left knee chambered tight to chest (thigh +55, knee -110)
            4, -4, 80             # Right leg planted rigid
        ]),
        root_y=0.01,
        stance_anchor="right_foot",
        description="Chambered knee preparing for a front kick."
    ),

    "kick_extend_mid": Pose(
        name="kick_extend_mid",
        angles=_deg([
            -12, -10, 6, 8,       # Torso leaning back in transition
            25, -60, -50, 65,
            20, -45, 65,          # Knee uncoiling forward
            6, -5, 80
        ]),
        root_y=0.0,
        stance_anchor="right_foot",
        description="Intermediate breakdown pose for kick strike."
    ),

    "kick_extend": Pose(
        name="kick_extend",
        angles=_deg([
            -18, -12, 10, 12,     # Torso leaned back to counterbalance kick
            20, -50, -55, 70,     # Arm counterbalance
            90, -10, 85,          # Left leg snapped fully horizontal (+X)
            8, -6, 80             # Right standing leg firmly planted
        ]),
        root_y=0.0,
        stance_anchor="right_foot",
        description="Full horizontal kick extension."
    ),

    # 5. Reactions & Knockdowns
    "hit_recoil": Pose(
        name="hit_recoil",
        angles=_deg([
            -14, -28, 18, 22,     # Spine crunch differential + head snapped back (2D snap)
            -55, -30, -25, 55,    # Arms flailing out of control
            -25, -40, 60,         # Legs buckling under impact
            -20, -45, 60
        ]),
        root_y=-0.07,
        stance_anchor=None,
        description="Violent impact reaction recoiling backward."
    ),

    "knockdown_fall": Pose(
        name="knockdown_fall",
        angles=_deg([
            -60, -25, 20, 15,     # Torso tipped heavily backward towards floor
            -70, -20, -60, 25,    # Arms splayed
            -25, -40, 60,
            15, -30, 60
        ]),
        root_y=-0.25,
        stance_anchor=None,
        description="Falling backward through the air towards ground."
    ),

    "ground_prone": Pose(
        name="ground_prone",
        angles=_deg([
            -88, -2, 2, 0,        # Torso completely flat on ground
            -85, 10, -85, 10,     # Arms limp beside body
            -5, -5, 80,           # Legs flat
            -5, -5, 80
        ]),
        root_y=-0.45,             # Pelvis on the ground plane (-0.50)
        stance_anchor=None,
        description="Flat on back on the ground floor."
    ),

    # 6. Expressive & Gestural
    "wave_tilt": Pose(
        name="wave_tilt",
        angles=_deg([
            -4, -6, 6, 8,         # Charming slight body tilt
            155, -45, -25, 20,    # Left hand held high waving, right relaxed
            5, -4, 80,
            -5, -4, 80
        ]),
        root_y=0.0,
        stance_anchor="both_feet",
        description="Friendly high hand wave with body tilt."
    ),

    "celebrate_cheer": Pose(
        name="celebrate_cheer",
        angles=_deg([
            -8, -6, 6, 8,         # Chest raised triumphantly
            155, 20, 150, 20,     # Both fists pumped high in the air
            12, -8, 80,           # Wide power stance
            -12, -8, 80
        ]),
        root_y=0.02,
        stance_anchor="both_feet",
        description="Triumphant celebration with both arms raised."
    ),

    "distress_head_clasp": Pose(
        name="distress_head_clasp",
        angles=_deg([
            25, 18, -12, -15,     # Hunched shoulders and bowed head
            85, -125, -85, 125,   # Both hands clasping head in desperation
            25, -50, 55,          # Trembling bent knees
            20, -45, 55
        ]),
        root_y=-0.10,
        stance_anchor="both_feet",
        description="Distress pose with hands clutching head."
    ),

    # 7. Office, Props & Infiltration
    "sit_desk": Pose(
        name="sit_desk",
        angles=_deg([
            12, 8, -4, -6,        # Upright torso with slight desk posture
            45, -65, 45, -65,     # Arms forward resting on table surface
            85, -85, 90,          # Thighs horizontal, knees bent 90 deg down
            85, -85, 90
        ]),
        root_y=-0.18,
        stance_anchor="both_feet",
        description="Seated posture at desk with hands on surface."
    ),

    "type_laptop": Pose(
        name="type_laptop",
        angles=_deg([
            15, 10, -6, -8,       # Focused forward lean over keyboard
            48, -82, 42, -78,     # Hands positioned actively typing on laptop keyboard
            85, -85, 90,          # Legs seated squarely under desk
            85, -85, 90
        ]),
        root_y=-0.18,
        stance_anchor="both_feet",
        description="Focused typing posture at laptop."
    ),

    "sword_ready": Pose(
        name="sword_ready",
        angles=_deg([
            5, 5, 0, -5,          # Combat ready torso
            50, -65, 35, -75,     # Two-handed katana grip in front
            18, -20, 88,          # Lead leg braced forward
            -14, -15, 82          # Rear leg anchored
        ]),
        root_y=0.0107,
        stance_anchor="both_feet",
        description="Two-handed katana combat stance."
    ),

    "sword_slash": Pose(
        name="sword_slash",
        angles=_deg([
            22, 18, -10, -12,     # Full upper body diagonal slash drive
            20, -40, 85, 15,      # Katana slashed downward across body
            -20, -15, 80,         # Braced lunge stance
            25, -25, 85
        ]),
        root_y=0.0003,
        stance_anchor="left_foot",
        description="Dynamic diagonal blade slash follow-through."
    ),

    "sword_parry": Pose(
        name="sword_parry",
        angles=_deg([
            -8, -6, 4, 6,         # Recoiling defensive tuck
            65, -95, 70, -85,     # Blade raised diagonally to intercept strike
            15, -15, 82,          # Braced defensive stance
            -15, -15, 82
        ]),
        root_y=0.0090,
        stance_anchor="both_feet",
        description="Defensive blade parry deflecting incoming attack."
    ),

    "dash_forward": Pose(
        name="dash_forward",
        angles=_deg([
            35, 20, -10, -15,     # Low sprint forward
            -45, -25, 55, -30,    # Arms pumping in sprint
            35, -50, 75,          # Explosive forward stride
            -30, -15, 80
        ]),
        root_y=-0.0114,
        stance_anchor="left_foot",
        description="Low aerodynamic forward sprint dash."
    ),

    "dash_backward": Pose(
        name="dash_backward",
        angles=_deg([
            -15, -10, 5, 10,      # Evasive back lean
            30, -30, -30, -30,    # Arms counter-balancing
            -25, -20, 75,         # Rearward evasive push
            20, -30, 75
        ]),
        root_y=0.0135,
        stance_anchor=None,
        description="Evasive backward retreat dash."
    ),

    "getup_roll": Pose(
        name="getup_roll",
        angles=_deg([
            40, 25, -15, -20,     # Rising torso drive
            60, -80, -20, -40,    # Hands pushing off floor
            50, -85, 70,          # Knee tucking under body
            -10, -40, 80
        ]),
        root_y=-0.0140,
        stance_anchor="both_feet",
        description="Kinetic rising recovery from ground."
    ),
}

# Aliases required by src/puppet/choreography.py:build_combat_pair
# (previously missing -> silent stand_relaxed fallback). Values mirror
# the closest canonical poses so strikes connect instead of idling.
_RAW_POSES["strike_anticipate"] = Pose(
    name="strike_anticipate",
    angles=_RAW_POSES["punch_windup"].angles.copy(),
    root_y=_RAW_POSES["punch_windup"].root_y,
    stance_anchor=_RAW_POSES["punch_windup"].stance_anchor,
    description="Alias of punch_windup for combat pairing."
)
_RAW_POSES["kick_anticipate"] = Pose(
    name="kick_anticipate",
    angles=_RAW_POSES["kick_chamber"].angles.copy(),
    root_y=_RAW_POSES["kick_chamber"].root_y,
    stance_anchor=_RAW_POSES["kick_chamber"].stance_anchor,
    description="Alias of kick_chamber for combat pairing."
)
_RAW_POSES["kick_impact"] = Pose(
    name="kick_impact",
    angles=_RAW_POSES["kick_extend"].angles.copy(),
    root_y=_RAW_POSES["kick_extend"].root_y,
    stance_anchor=_RAW_POSES["kick_extend"].stance_anchor,
    description="Alias of kick_extend for combat pairing."
)

POSES: Dict[str, Pose] = _RAW_POSES
# Lowercase index for case-insensitive lookup (keys like stride_contact_L vs stride_contact_l)
_POSE_MAP: Dict[str, Pose] = {k.lower(): v for k, v in _RAW_POSES.items()}


def get_pose_angles(name: str) -> np.ndarray:
    """Returns the (14,) float32 angle vector for a pose name, raising on unknown."""
    key = name.strip().lower()
    p = _POSE_MAP.get(key)
    if p is None:
        raise KeyError(f"Unknown pose '{name}'. Available: {sorted(POSES.keys())}")
    return p.angles.copy()


def get_pose_root_y(name: str) -> float:
    """Returns the root_y vertical offset for a pose name, raising on unknown."""
    key = name.strip().lower()
    p = _POSE_MAP.get(key)
    if p is None:
        raise KeyError(f"Unknown pose '{name}'. Available: {sorted(POSES.keys())}")
    return p.root_y
