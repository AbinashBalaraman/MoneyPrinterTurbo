"""Smooth Stop-Motion Puppet Platform package."""

from src.puppet.easing import (
    linear,
    ease_in_cubic,
    ease_out_cubic,
    ease_in_out_cubic,
    ease_in_quad,
    ease_out_quad,
    ease_in_out_quad,
    snap_and_settle,
    moving_hold,
    get_easing_function,
)
from src.puppet.pose import (
    POSES,
    get_pose_angles,
    get_pose_root_y,
)
from src.puppet.armature import (
    Keyframe,
    ArmatureTimeline,
    interpolate_keyframes,
)
from src.puppet.choreography import (
    PuppetChoreographer,
    create_walk_sequence,
    create_combat_sequence,
    create_jump_sequence,
    create_expressive_sequence,
)

__all__ = [
    "linear",
    "ease_in_cubic",
    "ease_out_cubic",
    "ease_in_out_cubic",
    "ease_in_quad",
    "ease_out_quad",
    "ease_in_out_quad",
    "snap_and_settle",
    "moving_hold",
    "get_easing_function",
    "POSES",
    "get_pose_angles",
    "get_pose_root_y",
    "Keyframe",
    "ArmatureTimeline",
    "interpolate_keyframes",
    "PuppetChoreographer",
    "create_walk_sequence",
    "create_combat_sequence",
    "create_jump_sequence",
    "create_expressive_sequence",
]
