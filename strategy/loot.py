"""Pickup choice and upgrade utility. Weapon upgrades persist on the mech (protocol section 10)."""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

PRIO = {"laser": 3, "mortar": 2, "lightning": 1, "gun": 0}

# Survival stats outrank damage. Placement is the score; cubes already scale damage.
UPGRADE_WEIGHT = {
    "armor": 100,
    "plating": 96,
    "nanites": 90,
    "servos": 72,
    "jets": 68,
    "reactor": 56,
    "sensors": 52,
    "gyros": 46,
    "capacitor": 32,
    "gun_mag": 42,
    "gun_velocity": 36,
    "gun_rate": 28,
    "gun_damage": 26,
    "laser_damage": 44,
    "laser_charge": 40,
    "laser_pierce": 22,
    "mortar_velocity": 34,
    "mortar_reload": 28,
    "mortar_splash": 22,
    "lightning_efficiency": 30,
    "lightning_range": 24,
    "lightning_chain": 18,
}


def held_kinds(weapons: Sequence[Optional[dict]]) -> List[str]:
    kinds = []
    for weapon in weapons or []:
        if weapon and weapon.get("kind"):
            kinds.append(weapon["kind"])
    return kinds


def choose_take(pos: Sequence[float], weapons: Sequence[Optional[dict]], pickups: Sequence[dict], radius: float) -> Optional[dict]:
    """Take the best weapon already in reach. Swap slot 1 only for a higher priority kind."""
    if not pickups or len(pos) < 3:
        return None
    have = set(held_kinds(weapons))
    best = None
    best_key = None
    px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
    for pickup in pickups:
        kind = pickup.get("kind")
        if kind not in PRIO or kind in have or PRIO[kind] <= 0:
            continue
        pp = pickup.get("pos") or (0.0, 0.0, 0.0)
        if len(pp) < 3:
            continue
        dist = math.hypot(pp[0] - px, pp[1] - py)
        if dist > radius or abs(pp[2] - pz) > 4.0:
            continue
        key = (-PRIO[kind], dist)
        if best_key is None or key < best_key:
            best_key = key
            best = pickup
    if best is None:
        return None
    slot1 = weapons[1] if len(weapons) > 1 else None
    if slot1 is None:
        return {"take": best["id"]}
    current = slot1.get("kind")
    if PRIO.get(best.get("kind"), 0) <= PRIO.get(current, 0):
        return None
    if current == "laser" and float(slot1.get("charge") or 0.0) > 0.0:
        return None
    return {"take": best["id"], "drop": 1}


def pick_upgrade(choices: Sequence[dict], have: Sequence[str], hp_frac: float) -> int:
    best_i = 0
    best_s = -1e9
    owned = set(have)
    for i, choice in enumerate(choices):
        cid = choice.get("id") if isinstance(choice, dict) else str(choice)
        score = float(UPGRADE_WEIGHT.get(cid, 10))
        if hp_frac < 0.55 and cid in ("armor", "plating", "nanites"):
            score += 28.0
        family = cid.split("_", 1)[0] if cid else ""
        if family in ("laser", "mortar", "lightning", "gun") and family not in owned and not cid.startswith("gun"):
            score -= 40.0
        if score > best_s:
            best_s = score
            best_i = i
    return best_i


def loot_destination(
    pos: Sequence[float],
    me_id: float,
    pickups: Sequence[dict],
    cubes: Sequence[dict],
    drops: Sequence[dict],
    weapons: Sequence[Optional[dict]],
    enemy_positions: Sequence[Sequence[float]],
    next_center: Sequence[float],
    next_radius: float,
) -> Optional[dict]:
    """A nearby cube, weapon, or uncontested supply drop. None if nothing is worth the detour."""
    px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
    have = set(held_kinds(weapons))

    def near_enemy(x: float, y: float, limit: float) -> bool:
        for ep in enemy_positions:
            if math.hypot(ep[0] - x, ep[1] - y) < limit:
                return True
        return False

    best_drop = None
    best_drop_d = 1e9
    for drop in drops or []:
        dp = drop.get("pos") or None
        if not dp or len(dp) < 2:
            continue
        if drop.get("holder") not in (None, me_id):
            continue
        lands = float(drop.get("lands_in") or 0.0)
        if math.hypot(dp[0] - next_center[0], dp[1] - next_center[1]) > max(8.0, next_radius):
            continue
        dist = math.hypot(dp[0] - px, dp[1] - py)
        window = 25.0 if lands <= 0.0 else 70.0
        if dist > window or dist >= best_drop_d:
            continue
        if near_enemy(dp[0], dp[1], 40.0 if lands <= 0.0 else 55.0):
            continue
        if lands > 20.0:
            continue
        best_drop = {"pos": dp, "kind": "drop", "id": drop.get("id"), "dist": dist}
        best_drop_d = dist
    if best_drop is not None and (float(drops[0].get("lands_in") or 0.0) <= 0.0 or best_drop_d < 50.0):
        # Prefer a drop that is already down, otherwise only if it is the closest good loot.
        if any(float(d.get("lands_in") or 0.0) <= 0.0 and d.get("id") == best_drop["id"] for d in drops):
            return best_drop

    best_cube = None
    best_cube_d = 1e9
    for cube in cubes or []:
        cp = cube.get("pos") or None
        if not cp or len(cp) < 2:
            continue
        dist = math.hypot(cp[0] - px, cp[1] - py)
        if dist < 22.0 and dist < best_cube_d and abs((cp[2] if len(cp) > 2 else pz) - pz) < 4.0:
            best_cube = {"pos": cp, "kind": "cube", "id": cube.get("id"), "dist": dist}
            best_cube_d = dist
    if best_cube is not None:
        return best_cube

    best_pick = None
    best_key = None
    for pickup in pickups or []:
        kind = pickup.get("kind")
        if kind not in PRIO or kind in have or PRIO[kind] <= 0:
            continue
        pp = pickup.get("pos") or None
        if not pp or len(pp) < 2:
            continue
        dist = math.hypot(pp[0] - px, pp[1] - py)
        if dist > 32.0:
            continue
        key = (-PRIO[kind], dist)
        if best_key is None or key < best_key:
            best_key = key
            best_pick = {"pos": pp, "kind": kind, "id": pickup.get("id"), "dist": dist}
    if best_pick is not None and not near_enemy(best_pick["pos"][0], best_pick["pos"][1], 30.0):
        return best_pick
    if best_drop is not None:
        return best_drop
    return None
