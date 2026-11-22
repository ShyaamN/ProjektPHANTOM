"""Hierarchical states. Transitions read measured features, not a scripted route."""
from __future__ import annotations

SURVIVE = "SURVIVE"
ROTATE = "ROTATE"
LOOT = "LOOT"
REPOSITION = "REPOSITION"
ESCAPE = "ESCAPE"
ENGAGE = "ENGAGE"
RECOVER = "RECOVER"
ENDGAME = "ENDGAME"

ALL = (SURVIVE, ROTATE, LOOT, REPOSITION, ESCAPE, ENGAGE, RECOVER, ENDGAME)


def decide_state(f: dict) -> str:
    """Priority: get inside the zone, escape a bad fight, heal, take a fair fight, loot, hide."""
    if f.get("outside") or f.get("must_rotate"):
        return ROTATE
    if f.get("panic"):
        return ESCAPE
    if f.get("should_recover"):
        return RECOVER
    if f.get("can_engage"):
        return ENGAGE
    if f.get("endgame"):
        return ENDGAME
    if f.get("loot_worth"):
        return LOOT
    if f.get("threat_near"):
        return REPOSITION
    return SURVIVE


# Below this fraction, keep running. At or above it, an isolated attacker in gun range gets a reply.
RETURN_FIRE_HP = 0.35


def allow_return_fire(
    nearest: float,
    isolated: bool,
    hp_frac: float,
    gun_range: float,
    aim_aligned: bool,
    los: bool,
) -> bool:
    """Gun only. Does not start a laser, a mortar, or a chase.

    The shot still has to pass the weapon gate (ammo, cooldown, aim error). This
    only decides that a hurt bot is allowed to answer an isolated attacker.
    """
    if not isolated or not aim_aligned or not los or gun_range <= 0.0:
        return False
    if hp_frac < RETURN_FIRE_HP:
        return False
    return 0.0 <= nearest < gun_range


def wants_for(
    state: str,
    nearest: float,
    isolated: bool,
    hp_frac: float,
    gun_range: float = 0.0,
    aim_aligned: bool = False,
    los: bool = False,
) -> dict:
    """Which weapons are allowed to fire. Silence is the default: shots reset regen and travel far."""
    none = {"gun": False, "laser": False, "mortar": False, "lightning": False}
    if state == RECOVER:
        wants = dict(none)
    elif state == ENGAGE:
        wants = {"gun": True, "laser": True, "mortar": True, "lightning": True}
    elif state == ENDGAME:
        if isolated and nearest < 110.0:
            wants = {"gun": True, "laser": True, "mortar": True, "lightning": True}
        else:
            wants = {"gun": nearest < 36.0, "laser": False, "mortar": False, "lightning": nearest < 24.0}
    elif state == ESCAPE:
        wants = {"gun": nearest < 26.0, "laser": False, "mortar": False, "lightning": nearest < 18.0}
    elif state == REPOSITION:
        wants = {
            "gun": isolated and nearest < 42.0 and hp_frac > 0.48,
            "laser": False,
            "mortar": False,
            "lightning": nearest < 22.0,
        }
    else:
        wants = {"gun": nearest < 20.0, "laser": False, "mortar": False, "lightning": nearest < 16.0}
    if allow_return_fire(nearest, isolated, hp_frac, gun_range, aim_aligned, los):
        wants["gun"] = True
    return wants
