"""Tests for src/camera.py camera computation and staging modes."""

import numpy as np
import pytest

from src.camera import compute_camera


@pytest.fixture
def sample_joints():
    """Generates synthetic moving joints: (T=72, N=2, 15 joints, 2D coords).

    Actor 0 moves smoothly from x = -0.5 to x = 1.5.
    Actor 1 moves smoothly from x = 0.5 to x = 2.5.
    """
    T, N, J = 72, 2, 15
    joints = np.zeros((T, N, J, 2), dtype=np.float32)

    # Time ramp
    t_ramp = np.linspace(0.0, 1.0, T, dtype=np.float32)

    # Actor 0 root motion
    actor0_x = -0.5 + 2.0 * t_ramp
    # Actor 1 root motion
    actor1_x = 0.5 + 2.0 * t_ramp

    # Assign roots and offset joints
    for j in range(J):
        joints[:, 0, j, 0] = actor0_x + 0.02 * (j - 7)
        joints[:, 0, j, 1] = -0.42 + 0.05 * j

        joints[:, 1, j, 0] = actor1_x + 0.02 * (j - 7)
        joints[:, 1, j, 1] = -0.42 + 0.05 * j

    return joints


def test_camera_static(sample_joints):
    """Test 1: static mode produces all zeros for camera_x."""
    T = sample_joints.shape[0]
    res = compute_camera(sample_joints, {"mode": "static"})

    assert isinstance(res, dict)
    assert res["mode"] == "static"
    assert res["zoom"] == 1.0
    assert res["camera_x"].shape == (T,)
    assert res["camera_x"].dtype == np.float32
    assert np.all(res["camera_x"] == 0.0)
    assert not np.any(np.isnan(res["camera_x"]))

    # Test custom zoom in static mode
    res_zoom = compute_camera(sample_joints, {"mode": "static", "zoom": 2.5})
    assert res_zoom["zoom"] == 2.5
    assert np.all(res_zoom["camera_x"] == 0.0)


def test_camera_auto_tracks_midpoint(sample_joints):
    """Test 2: auto mode is finite and tracks horizontal midpoint (corr > 0.9)."""
    res = compute_camera(sample_joints, {"mode": "auto"})

    cam_x = res["camera_x"]
    assert res["mode"] == "auto"
    assert res["zoom"] == 1.0
    assert np.all(np.isfinite(cam_x))
    assert not np.any(np.isnan(cam_x))

    # Calculate ground-truth per-frame horizontal midpoint
    min_x = np.min(sample_joints[:, :, :, 0], axis=(1, 2))
    max_x = np.max(sample_joints[:, :, :, 0], axis=(1, 2))
    midpoint = 0.5 * (min_x + max_x)

    # Verify correlation > 0.9
    corr = np.corrcoef(cam_x, midpoint)[0, 1]
    assert corr > 0.9, f"Expected correlation > 0.9, got {corr:.4f}"


def test_camera_close_wide_zoom_bounds(sample_joints):
    """Test 3: close (x1.6) and wide (x0.7) zoom calculation and bounds (0.25 - 4.0)."""
    # Close default
    res_close = compute_camera(sample_joints, {"mode": "close"})
    assert res_close["mode"] == "close"
    assert abs(res_close["zoom"] - 1.6) < 1e-5

    # Wide default
    res_wide = compute_camera(sample_joints, {"mode": "wide"})
    assert res_wide["mode"] == "wide"
    assert abs(res_wide["zoom"] - 0.7) < 1e-5

    # Upper clamp test: 3.0 * 1.6 = 4.8 -> clamp to 4.0
    res_close_clamped = compute_camera(sample_joints, {"mode": "close", "zoom": 3.0})
    assert res_close_clamped["zoom"] == 4.0

    # Lower clamp test: 0.25 * 0.7 = 0.175 -> clamp to 0.25
    res_wide_clamped = compute_camera(sample_joints, {"mode": "wide", "zoom": 0.25})
    assert res_wide_clamped["zoom"] == 0.25

    # Sweep across various base zoom values
    for z in [0.1, 0.25, 0.5, 1.0, 2.0, 3.5, 5.0]:
        z_close = compute_camera(sample_joints, {"mode": "close", "zoom": z})["zoom"]
        z_wide = compute_camera(sample_joints, {"mode": "wide", "zoom": z})["zoom"]
        assert 0.25 <= z_close <= 4.0
        assert 0.25 <= z_wide <= 4.0


def test_camera_pan_start_ne_end_and_monotone(sample_joints):
    """Test 4: pan mode has start != end and monotone direction."""
    res_pan = compute_camera(sample_joints, {"mode": "pan"})
    cam_x = res_pan["camera_x"]

    assert res_pan["mode"] == "pan"
    assert len(cam_x) == sample_joints.shape[0]
    assert cam_x[0] != cam_x[-1], "Pan start and end must not be equal"

    diffs = np.diff(cam_x)
    is_monotone_increasing = np.all(diffs >= -1e-6)
    is_monotone_decreasing = np.all(diffs <= 1e-6)
    assert is_monotone_increasing or is_monotone_decreasing, "Pan track must be monotone"

    # Also test completely stationary actors (all coords identical)
    static_joints = np.zeros_like(sample_joints)
    res_static_pan = compute_camera(static_joints, {"mode": "pan"})
    cam_x_static = res_static_pan["camera_x"]
    assert cam_x_static[0] != cam_x_static[-1], "Pan on stationary scene must still have start != end"
    diffs_static = np.diff(cam_x_static)
    assert np.all(diffs_static >= -1e-6) or np.all(diffs_static <= 1e-6)


def test_camera_determinism(sample_joints):
    """Test 5: two calls with identical inputs return identical byte-for-byte outputs."""
    modes = ["static", "auto", "follow", "close", "wide", "pan"]
    for m in modes:
        spec = {
            "mode": m,
            "zoom": 1.5,
            "focus": "fighter_b",
            "actors": ["fighter_a", "fighter_b"],
        }
        res1 = compute_camera(sample_joints, spec)
        res2 = compute_camera(sample_joints, spec)

        assert np.array_equal(res1["camera_x"], res2["camera_x"]), f"Non-deterministic camera_x in {m}"
        assert res1["camera_x"].tobytes() == res2["camera_x"].tobytes(), f"Byte diff in {m}"
        assert res1["zoom"] == res2["zoom"]
        assert res1["mode"] == res2["mode"]


def test_camera_follow_actor_focus(sample_joints):
    """Extra verification: follow mode tracks specific actor's root."""
    spec_a = {"mode": "follow", "focus": "actor_0", "actors": ["actor_0", "actor_1"]}
    spec_b = {"mode": "follow", "focus": "actor_1", "actors": ["actor_0", "actor_1"]}

    res_a = compute_camera(sample_joints, spec_a)
    res_b = compute_camera(sample_joints, spec_b)

    # Actor 1 is offset to the right of Actor 0, so camera_x for b must be greater than for a
    assert np.mean(res_b["camera_x"]) > np.mean(res_a["camera_x"])


def test_camera_single_actor_and_empty():
    """Extra verification: handle (T, 15, 2) single actor shape and empty input gracefully."""
    T = 30
    single_joints = np.zeros((T, 15, 2), dtype=np.float32)
    single_joints[:, :, 0] = np.linspace(0.0, 1.0, T)[:, None]

    res = compute_camera(single_joints, {"mode": "auto"})
    assert res["camera_x"].shape == (T,)
    assert not np.any(np.isnan(res["camera_x"]))

    # Empty
    empty_joints = np.zeros((0, 1, 15, 2), dtype=np.float32)
    res_empty = compute_camera(empty_joints, {"mode": "auto"})
    assert len(res_empty["camera_x"]) == 0
