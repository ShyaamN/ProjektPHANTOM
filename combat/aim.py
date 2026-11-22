"""Weapon aim solutions.

Gun and mortar are moving projectiles: the aim point is where the target will
be when the shot arrives, not where it is now. Laser is hitscan at the moment
of release, so the lead is only the target's motion during the remaining
charge. Lightning is instant and yaw-gated: point the torso at the target.

Bullet speed is world-frame speed along the aim. A recorded gun projectile in
the protocol has speed equal to weapons.gun.speed, so shooter velocity is not
added.

The gun equation includes the shot standoff. The projectile leaves
``radius + 0.5`` meters out along the aim, so

    |target + vel * t - muzzle| = standoff + speed * t
"""
from __future__ import annotations

import math

from combat.mathutil import clamp, dist3, normalize2, wrap_angle, yaw_pitch_toward


def intercept_time(src, pos, vel, speed: float, standoff: float = 0.0):
    """Smallest t >= 0 at which a shot from src reaches pos + vel*t.

    Returns None when the target is inside the standoff or faster than the
    projectile along every future ray.
    """
    if speed <= 1e-6:
        return None
    rx = pos[0] - src[0]
    ry = pos[1] - src[1]
    rz = pos[2] - src[2]
    vx, vy, vz = vel[0], vel[1], vel[2]
    a = vx * vx + vy * vy + vz * vz - speed * speed
    b = 2.0 * (rx * vx + ry * vy + rz * vz) - 2.0 * standoff * speed
    c = rx * rx + ry * ry + rz * rz - standoff * standoff
    cands = []
    if abs(a) < 1e-8:
        if abs(b) > 1e-8:
            cands.append(-c / b)
    else:
        disc = b * b - 4.0 * a * c
        if disc >= 0.0:
            s = math.sqrt(disc)
            cands.append((-b - s) / (2.0 * a))
            cands.append((-b + s) / (2.0 * a))
    best = None
    for t in cands:
        if t < -1e-3:
            continue
        t = 0.0 if t < 0.0 else t
        px = rx + vx * t
        py = ry + vy * t
        pz = rz + vz * t
        dist = math.sqrt(px * px + py * py + pz * pz)
        if abs(dist - (standoff + speed * t)) <= 1e-2 + 1e-3 * t:
            if best is None or t < best:
                best = t
    return best


def _point_at(pos, vel, t: float):
    return (
        pos[0] + vel[0] * t,
        pos[1] + vel[1] * t,
        pos[2] + vel[2] * t,
    )


def gun_solution(muzzle, target_pos, target_vel, speed: float, standoff: float = 0.0, range_m: float = 1e9):
    """Lead a gun (or any straight projectile) onto a constant-velocity target."""
    t = intercept_time(muzzle, target_pos, target_vel, speed, standoff)
    if t is None:
        point = (target_pos[0], target_pos[1], target_pos[2])
        yaw, pitch, horiz, dz = yaw_pitch_toward(muzzle, point)
        return {
            "yaw": yaw,
            "pitch": pitch,
            "t": 0.0,
            "point": point,
            "reachable": False,
            "dist": math.hypot(horiz, dz),
        }
    point = _point_at(target_pos, target_vel, t)
    yaw, pitch, horiz, dz = yaw_pitch_toward(muzzle, point)
    dist = math.hypot(horiz, dz)
    reachable = speed * t <= range_m + 1e-6
    return {
        "yaw": yaw,
        "pitch": pitch,
        "t": t,
        "point": point,
        "reachable": reachable,
        "dist": dist,
    }


def gun_hit_probability(
    dist: float,
    t: float,
    spread_deg: float,
    target_radius: float,
    target_speed: float,
    range_m: float,
) -> float:
    """Chance a Gaussian-spread shot, plus unknown dodge, still meets the body.

    ``spread_deg`` is treated as the standard deviation of the aim error, in
    degrees, matching the protocol's "small Gaussian spread". Dodge error grows
    with flight time because the target's velocity is not a promise.
    """
    if dist > range_m or dist < 0.0 or not math.isfinite(dist):
        return 0.0
    spread_m = math.tan(math.radians(max(spread_deg, 0.0))) * max(dist, 1.0)
    dodge_m = 0.45 * max(target_speed, 0.0) * max(t, 0.0) + 0.35
    sigma = math.hypot(spread_m, dodge_m)
    if sigma < 1e-6:
        return 0.97
    r = max(target_radius, 0.2)
    p = 1.0 - math.exp(-(r * r) / (2.0 * sigma * sigma))
    return clamp(p, 0.0, 0.97)


def laser_aim(muzzle, pos, vel, t_release: float):
    """Hitscan aim at where the target will be when the beam is released."""
    t = max(0.0, t_release)
    point = _point_at(pos, vel, t)
    yaw, pitch, horiz, dz = yaw_pitch_toward(muzzle, point)
    return yaw, pitch, point, math.hypot(horiz, dz)


def laser_charge_fraction(charged: float, charge_time: float, min_frac: float) -> float:
    """Damage fraction from min_frac at zero charge to 1 at a full charge."""
    if charge_time <= 1e-6:
        return 1.0
    u = clamp(charged / charge_time, 0.0, 1.0)
    return min_frac + (1.0 - min_frac) * u


def laser_hit_probability(
    dist: float,
    t_release: float,
    target_speed: float,
    target_radius: float,
    range_m: float,
) -> float:
    """Hitscan, so spread is zero. Miss comes from dodge during the telegraph."""
    if dist > range_m or dist < 0.0:
        return 0.0
    dodge = max(target_speed, 0.0) * max(t_release, 0.0) * 0.65 + 0.4
    sigma = max(dodge, 0.2)
    r = max(target_radius, 0.2)
    p = 1.0 - math.exp(-(r * r) / (2.0 * sigma * sigma))
    return clamp(p, 0.0, 0.95)


def mortar_angles(range_h: float, height: float, speed: float, gravity: float):
    """Closed-form pitches that land a shell at horizontal range ``range_h``.

    ``height`` is target_z - muzzle_z. Returns ``(pitch, time_of_flight)`` for
    the low arc, then the high arc. Empty when the target is out of range.
    """
    if speed <= 1e-6 or gravity <= 1e-6:
        return []
    R = range_h
    if R < 1e-3:
        return []
    h = height
    k = gravity * R * R / (2.0 * speed * speed)
    if k <= 1e-9:
        return []
    disc = R * R - 4.0 * k * (h + k)
    if disc < 0.0:
        return []
    root = math.sqrt(disc)
    out = []
    for sign in (-1.0, 1.0):
        u = (R + sign * root) / (2.0 * k)
        pitch = math.atan(u)
        cos = math.cos(pitch)
        if cos < 1e-4:
            continue
        tof = R / (speed * cos)
        if tof > 0.0:
            out.append((pitch, tof))
    return out


def mortar_solution(
    muzzle,
    pos,
    vel,
    speed: float,
    gravity: float,
    min_pitch: float,
    max_pitch: float,
    ttl: float,
    prefer_high: bool = False,
):
    """Iterative lead: solve the arc, fly the target forward, repeat.

    Aims at the target's feet-height point passed in ``pos``. Constant
    velocity, no drag, gravity on z only, matching weapons.mortar.
    """
    guess = (pos[0], pos[1], pos[2])
    chosen = None
    for _ in range(5):
        dx = guess[0] - muzzle[0]
        dy = guess[1] - muzzle[1]
        R = math.hypot(dx, dy)
        h = guess[2] - muzzle[2]
        angles = mortar_angles(R, h, speed, gravity)
        usable = []
        for pitch, tof in angles:
            if tof > ttl or tof < 0.0:
                continue
            if pitch < min_pitch - 1e-3 or pitch > max_pitch + 1e-3:
                continue
            usable.append((pitch, tof))
        if not usable:
            return chosen
        pitch, tof = usable[-1] if prefer_high and len(usable) > 1 else usable[0]
        pred = _point_at(pos, vel, tof)
        yaw = math.atan2(pred[1] - muzzle[1], pred[0] - muzzle[0])
        chosen = {
            "yaw": yaw,
            "pitch": pitch,
            "t": tof,
            "point": pred,
            "high": prefer_high,
        }
        guess = pred
    return chosen


def simulate_ballistic(muzzle, yaw: float, pitch: float, speed: float, gravity: float, t: float):
    """Forward integration used by tests and splash checks. Gravity pulls -z."""
    cosp = math.cos(pitch)
    vx = speed * cosp * math.cos(yaw)
    vy = speed * cosp * math.sin(yaw)
    vz = speed * math.sin(pitch)
    return (
        muzzle[0] + vx * t,
        muzzle[1] + vy * t,
        muzzle[2] + vz * t - 0.5 * gravity * t * t,
    )


def mortar_expected_damage(
    tof: float,
    target_speed: float,
    target_radius: float,
    splash_radius: float,
    direct: float,
    splash: float,
    splash_edge: float,
) -> float:
    """Direct-hit chance plus splash if the miss lands inside the blast.

    A direct hit is modeled as also taking the full splash (the shell's
    impact damage plus the blast). Misses use a linear falloff to
    ``splash_edge`` at ``splash_radius``.
    """
    sigma = 0.55 * max(target_speed, 0.0) * max(tof, 0.0) + 0.8
    sigma = max(sigma, 0.2)
    r = max(target_radius, 0.2)
    p_direct = 1.0 - math.exp(-(r * r) / (2.0 * sigma * sigma))
    p_direct = clamp(p_direct, 0.0, 0.95)
    mean_miss = sigma * math.sqrt(math.pi / 2.0)
    if splash_radius <= 0.0 or mean_miss >= splash_radius:
        splash_d = 0.0
    else:
        u = mean_miss / splash_radius
        fall = 1.0 + (splash_edge - 1.0) * u
        splash_d = splash * fall
    return p_direct * (direct + splash) + (1.0 - p_direct) * splash_d


def lightning_yaw(src_xy, dst_xy) -> float:
    return math.atan2(dst_xy[1] - src_xy[1], dst_xy[0] - src_xy[0])


def yaw_in_cone(aim_yaw: float, target_yaw: float, cone_deg: float) -> bool:
    """Protocol: within ``cone_deg`` of aim yaw means |Δyaw| <= cone_deg."""
    return abs(wrap_angle(target_yaw - aim_yaw)) <= math.radians(cone_deg) + 1e-9


def lightning_pick(aim_yaw: float, origin_xy, targets, range_m: float, cone_deg: float):
    """Nearest target inside range and the yaw cone.

    ``targets`` items need ``id``, ``x``, ``y``, and ``dist`` (3D, already
    computed by the caller) or the horizontal distance is used when ``dist``
    is absent.
    """
    best = None
    best_d = 1e18
    ox, oy = origin_xy
    for t in targets:
        d = t["dist"] if "dist" in t else math.hypot(t["x"] - ox, t["y"] - oy)
        if d > range_m or d >= best_d:
            continue
        yaw = math.atan2(t["y"] - oy, t["x"] - ox)
        if yaw_in_cone(aim_yaw, yaw, cone_deg):
            best = t
            best_d = d
    return best


def point_segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float):
    """Distance from a point to a segment, and which side of AB the point is on."""
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-9:
        return math.hypot(px - ax, py - ay), 1.0
    t = clamp(((px - ax) * dx + (py - ay) * dy) / len2, 0.0, 1.0)
    cx, cy = ax + dx * t, ay + dy * t
    cross = dx * (py - ay) - dy * (px - ax)
    side = 1.0 if cross >= 0.0 else -1.0
    return math.hypot(px - cx, py - cy), side


def beam_dodge(px: float, py: float, beams, radius: float = 7.0):
    """Unit vector away from the closest recent beam, or None.

    Laser and lightning are instant, so this only dodges the next one: a beam
    that just passed nearby means the shooter has the angle and will fire again.
    """
    best = None
    best_d = radius
    for beam in beams:
        if (beam.get("age") or 0.0) > 0.5:
            continue
        path = beam.get("path") or []
        for a, b in zip(path, path[1:]):
            dist, side = point_segment_distance(px, py, a[0], a[1], b[0], b[1])
            if dist < best_d:
                best_d = dist
                dx, dy = b[0] - a[0], b[1] - a[1]
                nx, ny = normalize2(-dy, dx)
                if side < 0.0:
                    nx, ny = -nx, -ny
                best = (nx, ny)
    return best


def opening_speed(src, pos, vel) -> float:
    """Positive when the target is moving away from src."""
    dx = pos[0] - src[0]
    dy = pos[1] - src[1]
    dz = pos[2] - src[2]
    n = dist3((0.0, 0.0, 0.0), (dx, dy, dz))
    if n < 1e-6:
        return 0.0
    return (dx * vel[0] + dy * vel[1] + dz * vel[2]) / n
