"""Camera tracking & staging module.

Computes deterministic camera horizontal tracking and zoom from validated
scene camera specifications.
"""

from typing import Any, Dict, List, Optional
import numpy as np


def _smooth_track(target_x: np.ndarray, alpha: float = 0.10) -> np.ndarray:
    """Computes smooth damped horizontal tracking array (T,) from per-frame targets."""
    T = len(target_x)
    if T == 0:
        return np.zeros(0, dtype=np.float32)

    cam_x = np.zeros(T, dtype=np.float32)
    curr = float(target_x[0])
    for t in range(T):
        curr = (1.0 - alpha) * curr + alpha * float(target_x[t])
        cam_x[t] = curr
    return cam_x


def compute_camera(
    joints: Any,
    spec: Optional[Dict[str, Any]] = None,
    fps: int = 24,
) -> Dict[str, Any]:
    """Compute camera track and zoom for a scene.

    Parameters
    ----------
    joints : np.ndarray
        Array of shape (T, N, 15, 2) in world coordinates. Also accepts
        (T, 15, 2) for a single actor or (15, 2) for a single frame.
    spec : dict, optional
        Validated camera specification dictionary from contract.validate_scene:
        {"mode": "auto|static|follow|close|wide|pan", "zoom": float,
         "focus": "mid"|actor_id, "follow": bool, "actors": [ids]}
    fps : int
        Frames per second (default 24).

    Returns
    -------
    dict
        {"camera_x": np.ndarray(T,), "zoom": float, "mode": str}
        where camera_x is a 1D float32 array with no NaNs.
    """
    if spec is None:
        spec = {}

    mode = str(spec.get("mode", "auto")).strip().lower()
    if mode not in ("auto", "static", "follow", "close", "wide", "pan"):
        mode = "auto"

    base_zoom = float(spec.get("zoom", 1.0))
    focus = spec.get("focus", "mid")
    follow_flag = bool(spec.get("follow", False))
    actors = spec.get("actors", [])
    if not isinstance(actors, (list, tuple)):
        actors = []

    # Normalise joints array
    joints_arr = np.asarray(joints, dtype=np.float32)
    if joints_arr.ndim == 2:
        # (15, 2) -> (1, 1, 15, 2)
        joints_arr = joints_arr[np.newaxis, np.newaxis, :, :]
    elif joints_arr.ndim == 3:
        # (T, 15, 2) -> (T, 1, 15, 2)
        joints_arr = joints_arr[:, np.newaxis, :, :]

    if joints_arr.ndim != 4:
        raise ValueError(f"Expected joints array with 2, 3, or 4 dimensions, got {joints_arr.ndim}")

    T, N = joints_arr.shape[0], joints_arr.shape[1]

    # Calculate zoom based on mode
    if mode == "close":
        zoom = float(np.clip(base_zoom * 1.6, 0.25, 4.0))
    elif mode == "wide":
        zoom = float(np.clip(base_zoom * 0.7, 0.25, 4.0))
    elif mode == "auto":
        zoom = float(np.clip(base_zoom, 0.25, 4.0))
    else:
        zoom = float(np.clip(base_zoom, 0.25, 4.0))

    if spec.get("zoom") is None and mode in ("auto", "wide") and N > 1 and T > 0:
        per_frame_span = np.max(joints_arr[..., 0], axis=(1, 2)) - np.min(joints_arr[..., 0], axis=(1, 2))
        max_frame_span = float(np.max(per_frame_span))
        if max_frame_span > 2.0:
            zoom = float(np.clip(2.5 / (max_frame_span + 0.5), 0.25, zoom))

    if T == 0:
        return {
            "camera_x": np.zeros(0, dtype=np.float32),
            "zoom": zoom,
            "mode": mode,
        }

    # Clean NaNs/Infs in input coordinates if any
    if not np.all(np.isfinite(joints_arr)):
        joints_arr = np.nan_to_num(joints_arr, nan=0.0, posinf=0.0, neginf=0.0)

    # Compute camera_x track
    if mode == "static":
        camera_x = np.zeros(T, dtype=np.float32)

    elif mode == "follow" or (mode == "auto" and follow_flag and focus != "mid"):
        # Track focus actor's root x (joint 0)
        actor_idx = 0
        if isinstance(focus, int):
            actor_idx = focus
        elif isinstance(focus, str):
            if focus in actors:
                actor_idx = actors.index(focus)
            else:
                try:
                    actor_idx = int(focus)
                except ValueError:
                    actor_idx = 0

        actor_idx = max(0, min(N - 1, actor_idx)) if N > 0 else 0
        if N > 0:
            target_x = joints_arr[:, actor_idx, 0, 0]
        else:
            target_x = np.zeros(T, dtype=np.float32)

        camera_x = _smooth_track(target_x, alpha=0.10)

    elif mode in ("auto", "close", "wide"):
        # Auto framing: smooth follow of the actors' horizontal midpoint
        if N > 0:
            min_x = np.min(joints_arr[:, :, :, 0], axis=(1, 2))
            max_x = np.max(joints_arr[:, :, :, 0], axis=(1, 2))
            target_x = 0.5 * (min_x + max_x)
        else:
            target_x = np.zeros(T, dtype=np.float32)

        camera_x = _smooth_track(target_x, alpha=0.10)

    elif mode == "pan":
        # Slow linear traverse across actors' full x-range over T
        if N > 0:
            x_min = float(np.min(joints_arr[..., 0]))
            x_max = float(np.max(joints_arr[..., 0]))
        else:
            x_min, x_max = -0.5, 0.5

        # If x-range is too small (e.g. stationary actor), expand to guarantee start != end
        if abs(x_max - x_min) < 0.2:
            mid = 0.5 * (x_min + x_max)
            x_min = mid - 0.5
            x_max = mid + 0.5

        camera_x = np.linspace(x_min, x_max, T, dtype=np.float32)

    else:
        camera_x = np.zeros(T, dtype=np.float32)

    # Ensure float32, 1D (T,), and finite (no NaN)
    camera_x = np.nan_to_num(camera_x, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    return {
        "camera_x": camera_x,
        "zoom": zoom,
        "mode": mode,
    }
