"""Unit tests for the deterministic object runtime (Task 2)."""

import numpy as np

from src.objects import evaluate_objects, GROUND_Y


def _joints(t=48, n=1):
    # Actors stand at x = -0.3 + 0.6*a; chest (joint 2) tracks x.
    j = np.zeros((t, n, 15, 2))
    for a in range(n):
        j[:, a, :, 0] = -0.3 + 0.6 * a
    return j


def test_1_static_window():
    objs = [{"kind": "ball", "at": [0.1, 0.0], "scale": 1.0,
             "spawn_frame": 5, "despawn_frame": 20}]
    tracks, impacts = evaluate_objects(objs, _joints(), T=48)
    assert impacts == []
    for t in range(48):
        if 5 <= t < 20:
            assert len(tracks[t]) == 1
            p = tracks[t][0]
            assert (p["kind"], p["x"], p["y"]) == ("ball", 0.1, 0.0)
        else:
            assert tracks[t] == []


def test_2_attach_joint_locked():
    objs = [{"kind": "sword", "scale": 1.0,
             "attach": {"actor": "a", "joint": 8, "from_frame": 10, "to_frame": 30}}]
    tracks, _ = evaluate_objects(objs, _joints(n=2), T=48)
    for t in range(10, 30):
        assert len(tracks[t]) == 1
        p = tracks[t][0]
        assert p["anchor_puppet"] == 0 and p["joint"] == 8
        assert "x" not in p
    assert tracks[9] == []  # outside window, no `at` -> absent


def test_3_throw_arc_deterministic():
    objs = [{"kind": "ball", "at": [0.0, 0.3], "scale": 1.0,
             "throw": {"frame": 4, "vx": 1.0, "vy": 1.2, "gravity": 2.0}}]
    j = _joints()
    # Move chests far away so no collision perturbs the arc.
    j[:, :, 2, 0] = 5.0
    t1, _ = evaluate_objects(objs, j, T=48)
    t2, _ = evaluate_objects(objs, j, T=48)
    y = [t1[t][0]["y"] for t in range(4, 40)]
    assert y[1] > y[0]  # rises first
    assert y[-1] < max(y)  # then falls
    assert t1 == t2  # deterministic


def test_4_bounce_impact_and_floor():
    objs = [{"kind": "ball", "at": [0.0, 0.5], "scale": 1.0, "bounce": True,
             "throw": {"frame": 0, "vx": 0.2, "vy": 0.0, "gravity": 3.0}}]
    j = _joints(t=96)
    j[:, :, 2, 0] = 5.0
    tracks, impacts = evaluate_objects(objs, j, T=96)
    bursts = [i for i in impacts if i["kind"] == "impact_burst"]
    assert len(bursts) >= 1
    ys = [tracks[t][0]["y"] for t in range(96)]
    assert min(ys) >= GROUND_Y - 1e-9


def test_5_pickup_flips_to_anchored():
    objs = [{"kind": "sword", "at": [0.2, -0.4], "scale": 1.0,
             "pickup": {"actor": "b", "joint": 6, "frame": 12}}]
    tracks, _ = evaluate_objects(objs, _joints(n=2), T=48)
    before = tracks[11][0]
    assert (before["x"], before["y"]) == (0.2, -0.4)
    after = tracks[12][0]
    assert after["anchor_puppet"] == 1 and after["joint"] == 6


def test_6_malformed_skipped():
    objs = [{"frobnicate": True}, "not-a-dict",
            {"kind": "ball", "at": [0.0, 0.0]}]
    tracks, impacts = evaluate_objects(objs, _joints(), T=12)
    assert all(len(tracks[t]) == 1 for t in range(12))
    assert impacts == []
    # Whole-batch garbage never raises either.
    evaluate_objects(None, _joints(), T=8)
    evaluate_objects([{"kind": "ball"}], "garbage", T=8)


def test_7_bounce_settles_no_energy_pump():
    """A bouncing ball must come to rest: bounded impacts, no perpetual rebound.

    Regression for a bug where re-entering an actor's collision window injected
    +0.2 upward velocity every frame, so the ball never settled (176 impacts in
    a 30s scene). Impacts must stay small and the object must stop moving.
    """
    objs = [{"kind": "ball", "at": [0.0, 0.4], "scale": 1.0, "bounce": True,
             "throw": {"frame": 0, "vx": 0.9, "vy": 0.8, "gravity": 1.8}}]
    j = _joints(t=240)
    j[:, :, 2, 0] = 0.0  # chest exactly on the flight path -> forces collisions
    tracks, impacts = evaluate_objects(objs, j, T=240)
    assert len(impacts) <= 16  # bounded, not one per frame
    # After settling, the object's position is essentially constant.
    tail = [(tracks[t][0]["x"], tracks[t][0]["y"]) for t in range(150, 240)]
    assert max(p[1] for p in tail) - min(p[1] for p in tail) < 1e-3
    assert max(p[0] for p in tail) - min(p[0] for p in tail) < 1e-3

