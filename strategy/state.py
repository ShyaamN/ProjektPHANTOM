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


def wants_for(state: str, nearest: float, isolated: bool, hp_frac: float) -> dict:
    """Which weapons are allowed to fire. Silence is the default: shots reset regen and travel far."""
    none = {"gun": False, "laser": False, "mortar": False, "lightning": False}
    if state == RECOVER:
        return none
    if state == ENGAGE:
        return {"gun": True, "laser": True, "mortar": True, "lightning": True}
    if state == ENDGAME:
        if isolated and nearest < 110.0:
            return {"gun": True, "laser": True, "mortar": True, "lightning": True}
        return {"gun": nearest < 36.0, "laser": False, "mortar": False, "lightning": nearest < 24.0}
    if state == ESCAPE:
        return {"gun": nearest < 26.0, "laser": False, "mortar": False, "lightning": nearest < 18.0}
    if state == REPOSITION:
        return {
            "gun": isolated and nearest < 42.0 and hp_frac > 0.48,
            "laser": False,
            "mortar": False,
            "lightning": nearest < 22.0,
        }
    return {"gun": nearest < 20.0, "laser": False, "mortar": False, "lightning": nearest < 16.0}
