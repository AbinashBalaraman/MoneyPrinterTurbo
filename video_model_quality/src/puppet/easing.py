"""Animation Easing & Timing Engine for Smooth Stop-Motion Puppetry.

Replaces continuous trigonometric high-frequency oscillations with
disciplined pose-to-pose easing curves, moving holds, and spring-damped snaps.
"""

import math
from typing import Callable, Dict, Union
import numpy as np


def linear(t: float) -> float:
    """Linear interpolation."""
    return float(np.clip(t, 0.0, 1.0))


def ease_in_quad(t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    return t * t


def ease_out_quad(t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    return 1.0 - (1.0 - t) * (1.0 - t)


def ease_in_out_quad(t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    if t < 0.5:
        return 2.0 * t * t
    return 1.0 - math.pow(-2.0 * t + 2.0, 2) / 2.0


def ease_in_cubic(t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    return t * t * t


def ease_out_cubic(t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    return 1.0 - math.pow(1.0 - t, 3)


def ease_in_out_cubic(t: float) -> float:
    t = float(np.clip(t, 0.0, 1.0))
    if t < 0.5:
        return 4.0 * t * t * t
    return 1.0 - math.pow(-2.0 * t + 2.0, 3) / 2.0


def ease_out_back(t: float, overshoot: float = 1.4) -> float:
    """Overshoots the target pose slightly and cushions back into place."""
    t = float(np.clip(t, 0.0, 1.0)) - 1.0
    return float(t * t * ((overshoot + 1.0) * t + overshoot) + 1.0)


def snap_and_settle(t: float, overshoot: float = 0.15, duration_settle: float = 1.0) -> float:
    """Fast dynamic attack with damped physical settling.
    
    Models the exact step response of an underdamped 2nd-order physical system:
    Starts smoothly at 0.0 with zero velocity, reaches target rapidly,
    overshoots cleanly by ~15%, and smoothly settles to 1.0 at the end.
    """
    t = float(np.clip(t, 0.0, 1.0))
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    # Damping ratio derived directly from overshoot percentage
    ln_os = math.log(max(1e-4, overshoot))
    zeta = -ln_os / math.sqrt(math.pi * math.pi + ln_os * ln_os)
    wn = 3.0 / (zeta * duration_settle)
    wd = wn * math.sqrt(max(1e-4, 1.0 - zeta * zeta))
    decay = math.exp(-zeta * wn * t)
    term = math.cos(wd * t) + (zeta / math.sqrt(max(1e-4, 1.0 - zeta * zeta))) * math.sin(wd * t)
    val = 1.0 - decay * term
    # Boundary normalization
    decay_end = math.exp(-zeta * wn)
    term_end = math.cos(wd) + (zeta / math.sqrt(max(1e-4, 1.0 - zeta * zeta))) * math.sin(wd)
    end_val = max(1e-4, 1.0 - decay_end * term_end)
    return float(val / end_val)



def moving_hold(t: float, amplitude: float = 0.02) -> float:
    """Subtle organic breathing drift during pauses to keep puppets alive without shaking."""
    t = float(np.clip(t, 0.0, 1.0))
    # Smooth half-sine swell and return
    return float(math.sin(t * math.pi) * amplitude)


def hold_breath(t_sec: float, amplitude: float = 0.035, hz: float = 1.2) -> float:
    """Continuous breathing oscillation for holds, in radians.

    Unlike ``moving_hold`` (a half-sine normalized over the whole hold, which
    becomes near-static for long holds and trips the dead-hold auditor), this
    keeps a fixed ~1.2 Hz cadence at a small amplitude so a held pose reads as
    alive. Amplitude ramps in over the first ~0.15 s (smoothstep) so the offset
    starts at 0.0 and stays continuous with the preceding transition.
    """
    if t_sec <= 0.0:
        return 0.0
    ramp_t = min(1.0, t_sec / 0.15)
    ramp = ramp_t * ramp_t * (3.0 - 2.0 * ramp_t)
    return float(amplitude * ramp * math.sin(2.0 * math.pi * hz * t_sec))


EASING_MAP: Dict[str, Callable[[float], float]] = {
    "linear": linear,
    "ease_in": ease_in_cubic,
    "ease_out": ease_out_cubic,
    "ease_in_out": ease_in_out_cubic,
    "ease_in_quad": ease_in_quad,
    "ease_out_quad": ease_out_quad,
    "ease_in_out_quad": ease_in_out_quad,
    "ease_out_back": ease_out_back,
    "snap_and_settle": snap_and_settle,
    "moving_hold": moving_hold,
}


def get_easing_function(name: Union[str, Callable[[float], float]]) -> Callable[[float], float]:
    """Resolves an easing function by name or returns the callable directly."""
    if callable(name):
        return name
    clean_name = str(name).strip().lower()
    return EASING_MAP.get(clean_name, ease_in_out_cubic)
