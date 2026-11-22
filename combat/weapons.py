"""When to pull a trigger. Stats come from the observation, not hard-coded balance."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

from combat.aim import (
    angle_error,
    clamp,
    direct_aim,
    gun_lead,
    mortar_solution,
    wrap_angle,
    yaw_error,
    yaw_pitch,
)


def aim_gate(dist: float) -> float:
    """How far the torso can be from the shot and still be on a mech-sized target."""
    return max(0.04, math.atan2(2.8, max(dist, 1.0)) + 0.025)


def gun_should_fire(ammo: float, reloading: bool, dist: float, gun_range: float, aim_err: float, los: bool, want: bool) -> bool:
    if not want or not los or reloading or ammo <= 0.0 or dist > gun_range - 1.0:
        return False
    return aim_err <= aim_gate(dist)


def should_reload(ammo: float, mag: float, reloading: bool, want_gun: bool) -> bool:
    if reloading or ammo >= mag:
        return False
    if ammo <= 0.0:
        return True
    return (not want_gun) and ammo <= max(3.0, mag * 0.25)


def lightning_should_fire(
    dist: float, yaw_err: float, cone_deg: float, rng: float, energy: float, cost: float, reserve: float, los: bool, want: bool
) -> bool:
    if not want or not los or dist > rng or energy < cost + reserve:
        return False
    half = math.radians(cone_deg) * 0.5 * 0.9
    return yaw_err <= half


def mortar_should_fire(dist: float, splash: float, los: bool, want: bool, solved: bool, self_dist: float) -> bool:
    if not want or not solved:
        return False
    if dist < max(20.0, splash + 8.0):
        return False
    if self_dist < splash + 6.0:
        return False
    # The gun is the better direct weapon. Lob the mortar over cover or at range.
    if los and dist < 80.0:
        return False
    return True


def laser_hold(charge: float, full: float, min_charge: float, cooldown: float, aim_err: float, want: bool) -> bool:
    """True holds the trigger (charge). False releases, which fires once min_charge is in."""
    charging = charge > 0.02
    if charging:
        if not want:
            return False
        if charge >= full - 0.03:
            return False
        if aim_err < 0.09 and charge >= max(min_charge, full * 0.62):
            return False
        return True
    if not want or cooldown > 0.08 or aim_err > 0.32:
        return False
    return True


def _slot(weapons: Sequence[Optional[dict]], kind: str) -> Optional[Tuple[int, dict]]:
    for i, weapon in enumerate(weapons):
        if weapon and weapon.get("kind") == kind:
            return i, weapon
    return None


def _stat(weapon: dict, key: str, default: float) -> float:
    stats = weapon.get("stats") or {}
    try:
        return float(stats.get(key, default))
    except (TypeError, ValueError):
        return default


def decide(ctx: dict) -> Tuple[List[float], List[bool], bool]:
    """Return aim [yaw, pitch], fire [slot0, slot1], reload."""
    weapons: Sequence[Optional[dict]] = ctx.get("weapons") or [None, None]
    fire = [False, False]
    look = ctx.get("look") or [0.0, 0.0]
    min_pitch = float(ctx.get("min_pitch", -0.7))
    max_pitch = float(ctx.get("max_pitch", 1.3))
    actual = ctx.get("actual_aim") or [0.0, 0.0]
    target = ctx.get("target")
    wants: Dict[str, bool] = ctx.get("wants") or {}

    def finish(yaw: float, pitch: float, reload: bool) -> Tuple[List[float], List[bool], bool]:
        return [yaw, clamp(pitch, min_pitch, max_pitch)], fire, reload

    gun = _slot(weapons, "gun")
    if target is None:
        reload = False
        if gun is not None:
            _, weapon = gun
            reload = should_reload(
                float(weapon.get("ammo") or 0.0),
                _stat(weapon, "mag", 12.0),
                float(weapon.get("reload") or 0.0) > 0.05,
                False,
            )
        return finish(float(look[0]), float(look[1]), reload)

    pos = target.get("pos") or [0.0, 0.0, 0.0]
    vel = target.get("vel") or [0.0, 0.0, 0.0]
    if len(pos) < 3:
        pos = [0.0, 0.0, 0.0]
    if len(vel) < 3:
        vel = [0.0, 0.0, 0.0]
    com = float(target.get("com_z", pos[2]))
    aim_at = [pos[0], pos[1], com]
    muzzle = ctx.get("muzzle") or pos
    tube = ctx.get("tube") or muzzle
    dist = float(ctx.get("dist") or math.dist(muzzle, aim_at))
    los = bool(ctx.get("los", False))
    turn_rate = max(float(ctx.get("turn_rate") or 4.0), 0.2)

    bearing = yaw_pitch(muzzle, aim_at)
    rough_err = yaw_error(actual[0], bearing[0])
    slew_t = rough_err / turn_rate

    yaw, pitch = direct_aim(muzzle, aim_at, vel, slew_t)
    gun_aim = None
    if gun is not None:
        _, weapon = gun
        gun_aim = gun_lead(muzzle, aim_at, vel, _stat(weapon, "speed", 252.0), extra_t=slew_t * 0.5)
        yaw, pitch = gun_aim[0]

    mortar = _slot(weapons, "mortar")
    mortar_sol = None
    if mortar is not None and wants.get("mortar"):
        _, weapon = mortar
        speed = _stat(weapon, "speed", 72.0)
        gravity = float(ctx.get("mortar_gravity") or 22.0)
        prefer_high = not los
        mortar_sol = mortar_solution(tube, [pos[0], pos[1], pos[2]], vel, speed, gravity, min_pitch, max_pitch, prefer_high)
        if mortar_sol is not None and mortar_should_fire(
            dist,
            _stat(weapon, "splash_radius", 7.0),
            los,
            True,
            True,
            math.dist(ctx.get("feet") or muzzle, mortar_sol[2]),
        ):
            yaw, pitch = mortar_sol[0], mortar_sol[1]
            idx, _ = mortar
            if idx < 2 and float(weapon.get("cooldown") or 0.0) <= 0.05:
                fire[idx] = True

    laser = _slot(weapons, "laser")
    laser_charging = False
    if laser is not None:
        idx, weapon = laser
        charge = float(weapon.get("charge") or 0.0)
        laser_charging = charge > 0.02
        hold = laser_hold(
            charge,
            _stat(weapon, "charge", 0.75),
            _stat(weapon, "min_charge", 0.15),
            float(weapon.get("cooldown") or 0.0),
            angle_error(actual, (yaw, pitch)) if not laser_charging else angle_error(actual, direct_aim(muzzle, aim_at, vel, slew_t)),
            bool(wants.get("laser")) and los and dist <= _stat(weapon, "range", 280.0) and dist > 12.0,
        )
        if hold or laser_charging:
            # Hitscan: track the body, don't use the ballistic pitch.
            yaw, pitch = direct_aim(muzzle, aim_at, vel, slew_t)
        if idx < 2:
            fire[idx] = hold
            if hold and mortar is not None and mortar[0] < 2:
                fire[mortar[0]] = False

    mortaring = mortar is not None and mortar[0] < 2 and fire[mortar[0]]
    laser_holding = laser is not None and laser[0] < 2 and fire[laser[0]]
    if gun is not None and not laser_charging and not mortaring and not laser_holding:
        idx, weapon = gun
        aimed = gun_aim[0] if gun_aim is not None else (yaw, pitch)
        yaw, pitch = aimed
        if idx < 2:
            reloading = float(weapon.get("reload") or 0.0) > 0.05
            fire[idx] = gun_should_fire(
                float(weapon.get("ammo") or 0.0),
                reloading,
                dist,
                _stat(weapon, "range", 230.0),
                angle_error(actual, aimed),
                los,
                bool(wants.get("gun")),
            )

    lightning = _slot(weapons, "lightning")
    if lightning is not None:
        idx, weapon = lightning
        cost = _stat(weapon, "energy", 3.0)
        if idx < 2 and lightning_should_fire(
            dist,
            yaw_error(actual[0], bearing[0]),
            _stat(weapon, "cone_deg", 30.0),
            _stat(weapon, "range", 45.0),
            float(ctx.get("energy") or 0.0),
            cost,
            float(ctx.get("lightning_reserve") or 25.0),
            los,
            bool(wants.get("lightning")),
        ):
            fire[idx] = True
            if not any(fire[i] for i in range(2) if i != idx):
                yaw, pitch = bearing

    reload = False
    if gun is not None:
        _, weapon = gun
        reload = should_reload(
            float(weapon.get("ammo") or 0.0),
            _stat(weapon, "mag", 12.0),
            float(weapon.get("reload") or 0.0) > 0.05,
            bool(wants.get("gun")) and bool(target),
        )
    # A reload request cancels nothing else; the server starts it when the gun is idle.
    return finish(yaw, pitch, reload)
