"""Tracks hurt timers, remembered mechs, and a circular-mean sound bearing."""
from __future__ import annotations

import math
from typing import Optional

_DIST_W = {"near": 3.0, "mid": 1.2, "far": 0.35}
_KIND_W = {
    "gun": 1.3,
    "laser": 1.4,
    "lightning": 1.5,
    "mortar": 1.2,
    "explosion": 1.4,
    "laser_charge": 1.6,
    "step": 0.4,
    "boost": 0.7,
    "jet": 0.5,
    "npc_gun": 0.5,
    "reload": 0.3,
    "death": 0.2,
    "crate": 0.2,
    "drop": 0.1,
}


def sound_bearing(sounds) -> Optional[float]:
    acc_s = acc_c = weight = 0.0
    for sound in sounds or []:
        kind_w = _KIND_W.get(sound.get("kind") or "", 0.0)
        if kind_w <= 0.0 or sound.get("bearing") is None:
            continue
        w = kind_w * _DIST_W.get(sound.get("dist"), 0.4) * math.exp(-float(sound.get("age") or 0.0) / 1.5)
        bearing = float(sound["bearing"])
        acc_s += math.sin(bearing) * w
        acc_c += math.cos(bearing) * w
        weight += w
    if weight < 0.25:
        return None
    return math.atan2(acc_s, acc_c)


class ThreatBoard:
    def __init__(self) -> None:
        self.last_hurt = -1e9
        self.last_dealt = -1e9
        self.hurt_bearing: Optional[float] = None
        self.sound: Optional[float] = None

    def update(self, obs: dict) -> None:
        t = float(obs.get("t") or 0.0)
        self.sound = sound_bearing(obs.get("sounds"))
        for event in obs.get("events") or []:
            kind = event.get("type")
            if kind == "damaged":
                self.last_hurt = t
                if event.get("weapon") != "zone" and event.get("bearing") is not None:
                    self.hurt_bearing = float(event["bearing"])
            elif kind == "hit":
                self.last_dealt = t

    def combat_idle(self, t: float) -> float:
        return t - max(self.last_hurt, self.last_dealt)
