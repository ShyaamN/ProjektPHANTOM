"""Small vector and angle helpers. World axes: x east, y north, z up."""
from __future__ import annotations

import math


def clamp(v: float, lo: float, hi: float) -> float:
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def wrap_angle(a: float) -> float:
    return (a + math.pi) % (2.0 * math.pi) - math.pi


def finite(v: float, default: float = 0.0) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    if not math.isfinite(v):
        return default
    return float(v)


def hypot3(dx: float, dy: float, dz: float) -> float:
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def dist3(a, b) -> float:
    return hypot3(a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dist2(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def normalize2(x: float, y: float):
    n = math.hypot(x, y)
    if n < 1e-9:
        return 0.0, 0.0
    return x / n, y / n


def yaw_pitch_toward(src, dst):
    """Yaw (from +x, CCW) and pitch (up-positive) from src to dst, plus horiz and dz."""
    dx = dst[0] - src[0]
    dy = dst[1] - src[1]
    dz = dst[2] - src[2]
    horiz = math.hypot(dx, dy)
    yaw = math.atan2(dy, dx)
    pitch = math.atan2(dz, horiz)
    return yaw, pitch, horiz, dz


def clamp_aim(yaw: float, pitch: float, min_pitch: float, max_pitch: float):
    return wrap_angle(yaw), clamp(pitch, min_pitch, max_pitch)


def angle_between_yaw(a: float, b: float) -> float:
    return abs(wrap_angle(a - b))
