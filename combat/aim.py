"""Aiming math. Distances are meters, angles radians, speeds meters/second.

Gun bullets fly straight at `speed` (protocol: no drop). Mortar shells are
ballistic with the configured gravity. Laser and lightning are hitscan, so
they only lead by the time the torso still needs to slew.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple


def wrap_angle(a: float) -> float:
    while a > math.pi:
        a -= math.tau
    while a < -math.pi:
        a += math.tau
    return a


def clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def norm(x: float, y: float) -> List[float]:
    mag = math.hypot(x, y)
    if mag < 1e-8:
        return [0.0, 0.0]
    return [x / mag, y / mag]


def yaw_pitch(src: Sequence[float], dst: Sequence[float]) -> Tuple[float, float]:
    dx = dst[0] - src[0]
    dy = dst[1] - src[1]
    dz = dst[2] - src[2]
    return math.atan2(dy, dx), math.atan2(dz, math.hypot(dx, dy))


def angle_error(actual: Sequence[float], desired: Sequence[float]) -> float:
    return math.hypot(wrap_angle(desired[0] - actual[0]), desired[1] - actual[1])


def yaw_error(actual_yaw: float, desired_yaw: float) -> float:
    return abs(wrap_angle(desired_yaw - actual_yaw))


def gun_lead(
    muzzle: Sequence[float],
    pos: Sequence[float],
    vel: Sequence[float],
    speed: float,
    extra_t: float = 0.0,
) -> Tuple[Tuple[float, float], List[float], float]:
    """Iterative intercept. Returns (yaw, pitch), aim point, time of flight."""
    speed = max(float(speed), 1.0)
    aim = [float(pos[0]), float(pos[1]), float(pos[2])]
    tof = 0.0
    for _ in range(3):
        tof = math.dist(muzzle, aim) / speed + extra_t
        aim = [pos[0] + vel[0] * tof, pos[1] + vel[1] * tof, pos[2] + vel[2] * tof]
    return yaw_pitch(muzzle, aim), aim, tof


def direct_aim(muzzle: Sequence[float], pos: Sequence[float], vel: Sequence[float], slew_t: float) -> Tuple[float, float]:
    """Hitscan aim, leading only for torso slew and a short reaction."""
    aim = [pos[0] + vel[0] * slew_t, pos[1] + vel[1] * slew_t, pos[2] + vel[2] * slew_t]
    return yaw_pitch(muzzle, aim)


def mortar_pitches(distance: float, dz: float, speed: float, gravity: float) -> List[float]:
    """Pitch solutions (low, then high) for a shell that lands `dz` above the tube.

    From z = d tan(pitch) - (g d^2 / (2 v^2)) (1 + tan^2(pitch)).
    """
    if distance < 1.0 or speed <= 1.0 or gravity <= 0.0:
        return []
    a = gravity * distance * distance / (2.0 * speed * speed)
    if a <= 1e-8:
        return []
    disc = distance * distance - 4.0 * a * (a + dz)
    if disc < 0.0:
        return []
    root = math.sqrt(disc)
    pitches = []
    for numer in (distance - root, distance + root):
        pitches.append(math.atan(numer / (2.0 * a)))
    pitches.sort()
    return pitches


def mortar_solution(
    tube: Sequence[float],
    pos: Sequence[float],
    vel: Sequence[float],
    speed: float,
    gravity: float,
    min_pitch: float,
    max_pitch: float,
    prefer_high: bool,
) -> Optional[Tuple[float, float, List[float], float]]:
    """Lead a moving target. Returns yaw, pitch, impact point, time of flight."""
    impact = [float(pos[0]), float(pos[1]), float(pos[2])]
    solved = None
    for _ in range(3):
        dx = impact[0] - tube[0]
        dy = impact[1] - tube[1]
        dist = math.hypot(dx, dy)
        dz = impact[2] - tube[2]
        pitches = [p for p in mortar_pitches(dist, dz, speed, gravity) if min_pitch <= p <= max_pitch]
        if not pitches:
            return None
        pitch = pitches[-1] if prefer_high and len(pitches) > 1 else pitches[0]
        tof = dist / max(speed * math.cos(pitch), 1e-3)
        if tof > 7.0:
            return None
        impact = [pos[0] + vel[0] * tof, pos[1] + vel[1] * tof, pos[2] + vel[2] * tof]
        yaw = math.atan2(impact[1] - tube[1], impact[0] - tube[0])
        solved = (yaw, pitch, impact, tof)
    return solved


def mortar_impact(
    pos: Sequence[float], vel: Sequence[float], gravity: float, ground_z: float
) -> Optional[Tuple[Tuple[float, float, float], float]]:
    """Time for a falling shell to reach ground_z. None if it never does."""
    if gravity <= 0.0:
        return None
    z0 = float(pos[2])
    vz = float(vel[2])
    disc = vz * vz - 2.0 * gravity * (ground_z - z0)
    if disc < 0.0:
        return None
    root = math.sqrt(disc)
    times = []
    for sign in (1.0, -1.0):
        t = (vz + sign * root) / gravity
        if t > 0.05:
            times.append(t)
    if not times:
        return None
    t = min(times)
    return (pos[0] + vel[0] * t, pos[1] + vel[1] * t, ground_z), t


def projectile_dodge(
    pos: Sequence[float],
    projectiles: Sequence[dict],
    gravity: float,
    splash_radius: float,
) -> Optional[Tuple[float, float]]:
    """Unit dodge direction when a bullet or shell will pass close. None if clear."""
    px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
    ax = ay = 0.0
    danger = False
    for proj in list(projectiles)[:24]:
        pp = proj.get("pos") or (0.0, 0.0, 0.0)
        vv = proj.get("vel") or (0.0, 0.0, 0.0)
        if len(pp) < 3 or len(vv) < 3:
            continue
        if proj.get("kind") == "mortar":
            hit = mortar_impact(pp, vv, gravity, pz)
            if hit is None:
                continue
            impact, tof = hit
            if tof > 3.0:
                continue
            d = math.hypot(impact[0] - px, impact[1] - py)
            if d < splash_radius + 5.0:
                danger = True
                if d < 0.6:
                    ax += -vv[1]
                    ay += vv[0]
                else:
                    ax += (px - impact[0]) / d
                    ay += (py - impact[1]) / d
            continue
        rx, ry, rz = px - pp[0], py - pp[1], pz - pp[2]
        vv2 = vv[0] * vv[0] + vv[1] * vv[1] + vv[2] * vv[2]
        if vv2 < 100.0:
            continue
        tca = (rx * vv[0] + ry * vv[1] + rz * vv[2]) / vv2
        if tca < 0.0 or tca > 0.9:
            continue
        cx = pp[0] + vv[0] * tca
        cy = pp[1] + vv[1] * tca
        cz = pp[2] + vv[2] * tca
        d = math.sqrt((cx - px) ** 2 + (cy - py) ** 2 + (cz - pz) ** 2)
        if d < 6.5:
            danger = True
            ox, oy = px - cx, py - cy
            h = math.hypot(ox, oy)
            if h < 0.4:
                ox, oy = -vv[1], vv[0]
                h = math.hypot(ox, oy) or 1.0
            ax += ox / h
            ay += oy / h
    if not danger:
        return None
    return tuple(norm(ax, ay))  # type: ignore[return-value]
