"""Zone geometry. The next circle is always inside the current one (protocol section 9)."""
from __future__ import annotations

import math
from typing import Sequence, Tuple


def zone_margin(radius: float) -> float:
    if radius <= 30.0:
        return max(2.0, radius * 0.15)
    return min(18.0, max(8.0, radius * 0.04))


def inside_circle(x: float, y: float, center: Sequence[float], radius: float, margin: float = 0.0) -> bool:
    limit = max(0.0, radius - margin)
    return math.hypot(x - center[0], y - center[1]) <= limit


def distance_outside(x: float, y: float, center: Sequence[float], radius: float) -> float:
    """Positive when (x, y) is outside the circle."""
    return math.hypot(x - center[0], y - center[1]) - radius


def clamp_inside(x: float, y: float, center: Sequence[float], radius: float, margin: float = 0.0) -> Tuple[float, float]:
    limit = max(0.0, radius - margin)
    dx = x - center[0]
    dy = y - center[1]
    dist = math.hypot(dx, dy)
    if limit <= 0.0:
        return float(center[0]), float(center[1])
    if dist <= limit or dist < 1e-8:
        return float(x), float(y)
    scale = limit / dist
    return center[0] + dx * scale, center[1] + dy * scale


def must_rotate(t: float, zone: dict, x: float, y: float) -> bool:
    """True when we should already be walking into the next circle."""
    margin = zone_margin(float(zone.get("next_radius") or 0.0))
    outside_next = distance_outside(x, y, zone.get("next_center") or (0.0, 0.0), float(zone.get("next_radius") or 0.0))
    if outside_next <= max(6.0, margin):
        return False
    shrink_start = float(zone.get("shrink_start") or 0.0)
    if t >= shrink_start:
        return True
    # Start walking in well before the shrink. An 18 s lead is enough at boost
    # speed, but a hurt mech is walking, and the recorded trace stayed outside
    # the next circle while it tried to heal.
    return shrink_start - t < 35.0
