"""Fight selection. Placement is the score, so a lost trade is a bad kill.

Score per match is ``16 - place``. Dying first is zero. This module decides
whether the current exchange is worth staying in. It does not assume the
other mech will refuse to shoot: a target that is not yet aiming still has
most of its weapon's damage, because torsos turn quickly.
"""
from __future__ import annotations

import math


class FightState:
    def __init__(
        self,
        my_hp: float,
        my_max: float,
        enemy_hp: float,
        my_dps: float,
        enemy_dps: float,
        enemies_on_me: int,
        in_zone: bool,
        zone_dps: float,
        alive: int,
        exchange_losing: bool = False,
    ):
        self.my_hp = my_hp
        self.my_max = my_max
        self.enemy_hp = enemy_hp
        self.my_dps = my_dps
        self.enemy_dps = enemy_dps
        self.enemies_on_me = enemies_on_me
        self.in_zone = in_zone
        self.zone_dps = zone_dps
        self.alive = alive
        self.exchange_losing = exchange_losing


def _deaths(state: FightState):
    my_death = state.my_hp / state.enemy_dps if state.enemy_dps > 1e-6 else math.inf
    their_death = state.enemy_hp / state.my_dps if state.my_dps > 1e-6 else math.inf
    return my_death, their_death


def fight_decision(state: FightState) -> str:
    """``commit`` press, ``trade`` strafe and shoot, ``disengage`` leave.

    A commit is a favorable time-to-kill or a target that cannot answer.
    A trade is an even fight: shoot, do not chase, keep the front arc on them.
    Disengage when the race is losing, the recent damage exchange is losing,
    several mechs are on us, or the zone will kill us during a long fight.
    The last duel is special: if we win the race we stay, because running
    only delays second place.
    """
    hp_frac = state.my_hp / state.my_max if state.my_max > 0 else 0.0
    my_death, their_death = _deaths(state)

    # Two mechs already aiming at us is how a combat bot dies first.
    # Stay only long enough to delete a mech that is about to fall, and only
    # when that kill lands before their focus fire does.
    if state.enemies_on_me >= 2:
        if their_death < 0.8 and my_death > their_death + 0.3:
            return "commit"
        return "disengage"

    if not state.in_zone and state.zone_dps > 0:
        zone_death = state.my_hp / state.zone_dps if state.zone_dps > 0 else math.inf
        if their_death > min(zone_death * 0.5, 3.0):
            return "disengage"

    if state.alive <= 2 and state.my_dps > 0:
        if their_death <= my_death:
            return "commit"
        if my_death < their_death * 0.75 and hp_frac < 0.5:
            return "disengage"
        return "trade"

    if state.exchange_losing and not (their_death < my_death and their_death < 1.2):
        return "disengage"

    if state.enemy_dps > 1.0 and my_death + 0.5 < their_death and hp_frac < 0.8:
        return "disengage"

    if hp_frac < 0.25 and their_death > 1.5:
        return "disengage"

    if state.enemy_dps <= 0.5 and state.my_dps > 0 and state.in_zone:
        return "commit"

    if their_death < my_death * 0.9:
        return "commit"
    return "trade"


def should_disengage(state: FightState) -> bool:
    return fight_decision(state) == "disengage"


def press_from_range(
    decision: str,
    dist: float,
    preferred: float,
    hp: float,
    my_dps: float,
    enemy_dps: float,
    hp_frac: float,
    enemies_on_me: int,
    in_zone: bool,
) -> str:
    """Close a long gun fight instead of treating low hit chance as a loss.

    At 150 m a gun's hit probability is small, so the time-to-kill says we
    lose even when we would win the same fight at 50 m. If we are healthy,
    inside the zone, and not already under focus fire that kills us in five
    seconds, turn that disengage into a trade and close. A fight that is
    already at the preferred range stays a disengage: the bad numbers are real.
    """
    if decision != "disengage":
        return decision
    if not in_zone or enemies_on_me >= 2 or hp_frac < 0.65:
        return decision
    if dist < preferred + 18.0:
        return decision
    if enemy_dps > 1.0 and hp / enemy_dps < 5.0:
        return decision
    if my_dps < 40.0:
        return "trade"
    return decision


def exchange_losing(dealt: float, taken: float, hp_frac: float) -> bool:
    """Recent damage taken has outrun damage dealt, and we are not comfortable.

    Even trades stay. A few points of chip do not count. A large deficit
    while under about 80% HP is a lost exchange.
    """
    if taken < 80.0:
        return False
    if taken > dealt * 1.2 and hp_frac < 0.8:
        return True
    if taken > dealt + 250.0 and hp_frac < 0.9:
        return True
    return False


def chase_allowed(dist: float, in_future_zone: bool, my_hp: float, zone_dps: float, their_ttk: float) -> bool:
    """Do not run out of the next circle for a slow kill."""
    if in_future_zone:
        return their_ttk < 12.0 or dist < 80.0
    if zone_dps <= 0.0:
        return True
    survive = my_hp / zone_dps if zone_dps > 0 else math.inf
    return their_ttk < survive * 0.45 and dist < 50.0


def preferred_range(my_weapons, enemy_weapons) -> float:
    """Meters. Lightning is a 45 m problem; everything else wants more air."""
    mine = set(my_weapons)
    theirs = set(enemy_weapons)
    if "lightning" in mine and "lightning" not in theirs:
        base = 32.0
    elif "laser" in mine:
        base = 90.0
    elif "mortar" in mine:
        base = 85.0
    else:
        base = 55.0
    if "lightning" in theirs and "lightning" not in mine:
        base = max(base, 62.0)
    return base


def weapon_scores(seen_counts) -> dict:
    mortar_n = float(seen_counts.get("mortar", 0))
    laser_n = float(seen_counts.get("laser", 0))
    light_n = float(seen_counts.get("lightning", 0))
    return {
        "laser": 3.0 + 1.5 * mortar_n,
        "lightning": 2.6 + 1.6 * laser_n,
        "mortar": 2.4 + 1.6 * light_n,
    }


def swap_worth(have, seen_counts, pickup_kind: str) -> bool:
    """True when a ground weapon should replace the special we already hold.

    An empty special slot is not a swap. With no scouting, a laser stays: it
    is the default duel weapon, and walking onto lightning must not drop it.
    A swap happens when the pickup counters what enemies are actually carrying.
    """
    if pickup_kind in have or pickup_kind == "gun":
        return False
    scores = weapon_scores(seen_counts)
    specials = [kind for kind in have if kind != "gun" and kind in scores]
    if not specials:
        return False
    current = max(scores[kind] for kind in specials)
    return scores.get(pickup_kind, 0.0) >= current + 0.5


def desired_weapon(have, seen_counts) -> str | None:
    """Weapon triangle: laser cooks mortar, mortar concusses lightning, lightning shorts laser.

    With no information, take a laser. It is the longest duel weapon.
    ``have`` is the set of kinds already held. ``seen_counts`` counts enemy
    weapons observed recently.
    """
    scores = weapon_scores(seen_counts)
    for kind in have:
        scores.pop(kind, None)
    if not scores:
        return None
    return max(scores, key=scores.get)


def sustained_gun_dps(damage: float, cooldown: float, mag: float, reload: float, hit_p: float) -> float:
    if cooldown <= 1e-6 or mag <= 0 or hit_p <= 0:
        return 0.0
    cycle = mag * cooldown + max(reload, 0.0)
    if cycle <= 0:
        return 0.0
    return (damage / cooldown) * ((mag * cooldown) / cycle) * hit_p


def cube_damage_scale(cubes: float, per: float, cap: float) -> float:
    return 1.0 + per * min(max(cubes, 0.0), cap)


# Combat value of an upgrade id. Weapon upgrades only appear in an offer when
# that weapon is held, so a high weapon score is safe to prefer.
_UPGRADE_VALUE = {
    "armor": 92,
    "plating": 84,
    "laser_damage": 88,
    "laser_charge": 80,
    "gun_damage": 78,
    "gun_rate": 76,
    "lightning_range": 74,
    "lightning_efficiency": 72,
    "gyros": 70,
    "mortar_splash": 66,
    "mortar_reload": 64,
    "nanites": 62,
    "sensors": 58,
    "gun_velocity": 54,
    "lightning_chain": 52,
    "mortar_velocity": 50,
    "gun_mag": 48,
    "servos": 40,
    "laser_pierce": 36,
    "capacitor": 34,
    "reactor": 30,
    "jets": 24,
}


def pick_upgrade(choices) -> int:
    """Index of the most combat-useful offer choice. Defaults to 0."""
    best_i = 0
    best_v = -1
    for i, choice in enumerate(choices):
        v = _UPGRADE_VALUE.get(choice.get("id", ""), 10)
        if v > best_v:
            best_v = v
            best_i = i
    return best_i


def zone_circle(zone, t: float, ahead: float = 0.0):
    """Circle the zone will have at ``t + ahead``, from the live observation.

    The observation already names the current circle and the next one. Past
    ``shrink_end`` this returns the next circle; it does not know the phase
    after that.
    """
    t2 = t + ahead
    ss = zone["shrink_start"]
    se = zone["shrink_end"]
    if se <= ss or t2 <= ss:
        u = 0.0
    elif t2 >= se:
        u = 1.0
    else:
        u = (t2 - ss) / (se - ss)
    cx = zone["center"][0] + (zone["next_center"][0] - zone["center"][0]) * u
    cy = zone["center"][1] + (zone["next_center"][1] - zone["center"][1]) * u
    radius = zone["radius"] + (zone["next_radius"] - zone["radius"]) * u
    return cx, cy, radius


def inside_circle(x: float, y: float, cx: float, cy: float, radius: float, margin: float) -> bool:
    return math.hypot(x - cx, y - cy) <= max(0.0, radius - margin)
