"""Survival-first pilot.

Practice matches are a cooperating squad. Finals are a free-for-all. Both reward
placement, so the bot stays quiet, stays in the next circle, and only takes a
fight it can leave. Nothing here assumes house bots will refuse to shoot each other.
"""
from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import mechfight as mf

from combat.aim import angle_error, norm, projectile_dodge, wrap_angle, yaw_pitch
from combat.weapons import aim_gate
from combat.weapons import decide as decide_weapons
from navigation.grid import NavGrid, build_grid
from navigation.map import Solids
from navigation.path import Pilot
from strategy.loot import choose_take, held_kinds, loot_destination, pick_upgrade
from strategy.state import ENDGAME, ENGAGE, ESCAPE, LOOT, RECOVER, REPOSITION, ROTATE, SURVIVE, decide_state, wants_for
from strategy.threat import ThreatBoard
from strategy.zone import clamp_inside, distance_outside, inside_circle, must_rotate, zone_margin

_NAV: dict = {}


def _world(arena_dir: str):
    if arena_dir not in _NAV:
        grid, solids, info = build_grid(arena_dir)
        _NAV[arena_dir] = (grid, solids, info)
        mf.log(f"nav {info['w']}x{info['h']} blocked {info['blocked']}/{info['cells']} in {info['ms']:.0f} ms")
    return _NAV[arena_dir]


class Brain:
    name = "phantom"

    def __init__(self, hello: dict) -> None:
        self.hello = hello
        self.cfg = hello.get("config") or {}
        self.seed = int(hello.get("seed") or 1)
        self.board = ThreatBoard()
        self.pilot = Pilot()
        self.grid: Optional[NavGrid] = None
        self.solids: Optional[Solids] = None
        mech = self.cfg.get("mech") or {}
        self.step_up = float(mech.get("step_up") or 1.2)
        try:
            arena = (hello.get("map") or {}).get("dir") or ""
            self.grid, self.solids, _info = _world(arena)
        except Exception as exc:  # missing map in a unit test, or a short hello
            mf.log(f"nav unavailable: {exc}")
            self.grid = None
            self.solids = None

    def act(self, obs: dict) -> dict:
        self.board.update(obs)
        me = obs.get("self") or {}
        pos = me.get("pos") or [0.0, 0.0, 0.0]
        x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
        t = float(obs.get("t") or 0.0)
        zone = obs.get("zone") or {}
        features, mechs, npcs, loot = self._features(obs, me, x, y, z, t, zone)
        state = decide_state(features)
        action: dict = {"tick": obs.get("tick", 0)}

        offer = obs.get("offer")
        if offer and offer.get("choices"):
            action["pick"] = pick_upgrade(offer["choices"], held_kinds(me.get("weapons") or []), features["hp_frac"])

        weapons = me.get("weapons") or [None, None]
        radius = float((self.cfg.get("loot") or {}).get("pickup_radius") or 4.0)
        take = choose_take(pos, weapons, obs.get("pickups") or [], radius)
        if take and state not in (ENGAGE, ESCAPE) and features["nearest"] > 28.0:
            action.update(take)

        move, boost, jump, goal = self._move(obs, me, state, features, mechs, loot, x, y, z, t, zone)
        aim, fire, reload = self._combat(obs, me, state, features, mechs, npcs, move, x, y, z)
        action["move"] = move
        action["boost"] = boost
        action["jump"] = jump
        action["aim"] = aim
        action["fire"] = fire
        if reload:
            action["reload"] = True
        mf.draw.label(f"{state} hp{int(me.get('hp') or 0)} n{len(mechs)}")
        if goal is not None and self._finite(goal[0]) and self._finite(goal[1]):
            mf.draw.line([x, y, z + 2.0], [goal[0], goal[1], z], "#40c0ff")
        return action

    def _features(self, obs, me, x, y, z, t, zone) -> tuple:
        max_hp = float(me.get("max_hp") or 1.0) or 1.0
        hp_frac = float(me.get("hp") or 0.0) / max_hp
        mechs: List[tuple] = []
        npcs: List[tuple] = []
        for actor in obs.get("mechs") or []:
            apos = actor.get("pos")
            if not apos or len(apos) < 2:
                continue
            dist = math.hypot(float(apos[0]) - x, float(apos[1]) - y)
            if actor.get("kind") == "npc":
                npcs.append((dist, actor))
            else:
                mechs.append((dist, actor))
        mechs.sort(key=lambda item: item[0])
        npcs.sort(key=lambda item: item[0])
        nearest = mechs[0][0] if mechs else 1e9
        second = mechs[1][0] if len(mechs) > 1 else 1e9
        close = sum(1 for dist, _ in mechs if dist < 42.0)
        isolated = bool(mechs) and (len(mechs) == 1 or second > nearest + 38.0)
        in_zone = bool(me.get("in_zone", True))
        outside = not in_zone
        rotating = (not outside) and _zone_ready(zone) and must_rotate(t, zone, x, y)
        laser_on_us = False
        for dist, actor in mechs:
            if dist < 170.0 and _laser_aimed(actor, (x, y)):
                laser_on_us = True
                break
        dodge = projectile_dodge(
            (x, y, z + 4.5),
            obs.get("projectiles") or [],
            float(((self.cfg.get("weapons") or {}).get("mortar") or {}).get("gravity") or 22.0),
            float(((self.cfg.get("weapons") or {}).get("mortar") or {}).get("splash_radius") or 7.0),
        )
        idle = self.board.combat_idle(t)
        panic = bool(
            dodge is not None
            or (close >= 2 and nearest < 42.0)
            or (hp_frac < 0.32 and nearest < 70.0)
            or (idle < 0.8 and hp_frac < 0.45 and nearest < 50.0 and close >= 1)
            or laser_on_us
        )
        los = False
        target = mechs[0][1] if mechs else None
        if target is not None and self.solids is not None:
            los = not self.solids.blocks_segment(self._muzzle(me, x, y, z), _body(target), 6.0)
        elif target is not None:
            los = nearest < 45.0
        have_mortar = "mortar" in held_kinds(me.get("weapons") or [])
        heal_block = hp_frac < 0.72 and idle > 3.0 and nearest > 48.0
        can_engage = bool(
            mechs
            and not panic
            and not outside
            and not rotating
            and nearest < (70.0 if hp_frac < 0.6 else 125.0)
            and isolated
            and hp_frac > 0.42
            and not laser_on_us
            and (los or (have_mortar and nearest > 30.0))
            and not heal_block
        )
        enemies = [actor.get("pos") for _, actor in mechs if actor.get("pos")]
        loot = loot_destination(
            (x, y, z),
            float(me.get("id") or 0.0),
            obs.get("pickups") or [],
            obs.get("cubes") or [],
            obs.get("drops") or [],
            me.get("weapons") or [],
            enemies,
            zone.get("next_center") or (x, y),
            float(zone.get("next_radius") or 0.0),
        )
        loot_dist = float(loot["dist"]) if loot else 1e9
        alive = float(obs.get("alive") or 16)
        radius = float(zone.get("radius") or 999.0)
        endgame = alive <= 4 or radius < 110.0 or t >= 300.0
        should_recover = bool(
            not panic
            and not outside
            and not rotating
            and hp_frac < 0.84
            and nearest > 58.0
            and idle >= 0.25
            and (hp_frac < 0.56 or idle >= 4.2)
        )
        loot_worth = bool(loot is not None and loot_dist < 34.0 and nearest > 60.0 and hp_frac > 0.62 and not outside)
        threat_near = nearest < 78.0
        npc_close = npcs[0][0] if npcs else 1e9
        features = {
            "hp_frac": hp_frac,
            "outside": outside,
            "must_rotate": rotating,
            "panic": panic,
            "should_recover": should_recover,
            "can_engage": can_engage,
            "endgame": endgame,
            "loot_worth": loot_worth,
            "threat_near": threat_near,
            "nearest": nearest,
            "second": second,
            "isolated": isolated,
            "los": los,
            "dodge": dodge,
            "idle": idle,
            "laser_on_us": laser_on_us,
            "npc_close": npc_close,
            "in_zone": in_zone,
        }
        return features, mechs, npcs, loot

    def _move(self, obs, me, state, features, mechs, loot, x, y, z, t, zone):
        goal = self._goal(state, features, mechs, loot, x, y, t, zone)
        quantize = state not in (LOOT, ENGAGE)
        stored = self.pilot.set_goal(goal, state, t, quantize=quantize)
        commanded = True
        self.pilot.note_motion(x, y, t, commanded)
        if self.grid is not None and state not in (ENGAGE, ESCAPE) and self.pilot.should_replan(t):
            self.pilot.path = self.grid.astar((x, y), stored, limit=700)
            self.pilot.last_plan_t = t
            self.pilot.dirty = False
        if state == ENGAGE and mechs:
            sign = 1 if ((self.seed // 7) ^ int(t / 2.4)) & 1 == 0 else -1
            actor = mechs[0][1]
            apos = actor.get("pos") or (x, y, z)
            pref = 60.0 if _has_weapon(actor, "lightning") else 45.0
            move = _strafe(x, y, float(apos[0]), float(apos[1]), pref, sign)
        elif state == ESCAPE:
            move = self._flee(features, mechs, x, y, zone)
        else:
            move = self.pilot.steer(self.grid, x, y, stored)
        if self.pilot.unsticking(t) and state != ENGAGE:
            move = norm(-move[1] * self.pilot.unstick_sign, move[0] * self.pilot.unstick_sign)
        if features["dodge"] is not None and state != RECOVER:
            dx, dy = features["dodge"]
            move = norm(move[0] * 0.25 + dx, move[1] * 0.25 + dy)
        elif state in (SURVIVE, REPOSITION, ROTATE, ENDGAME) and mechs:
            ax, ay = _repulse(x, y, mechs, 80.0)
            weight = 1.1 if state == REPOSITION else 0.45
            move = norm(move[0] + ax * weight, move[1] + ay * weight)
        if zone:
            move = _restrain(x, y, move, zone, bool(me.get("in_zone", True)))
        if state == LOOT and loot is not None and loot["dist"] < 3.5:
            move = [move[0] * 0.35, move[1] * 0.35]
        boost = self._boost(me, state, math.hypot(stored[0] - x, stored[1] - y), not me.get("in_zone", True))
        jump = self.pilot.should_jump(t)
        return _unit_or_slow(move), boost, jump, stored

    def _flee(self, features, mechs, x, y, zone) -> List[float]:
        fx = fy = 0.0
        if mechs:
            apos = mechs[0][1].get("pos") or (x, y)
            dist = max(features["nearest"], 1.0)
            fx += (x - float(apos[0])) / dist
            fy += (y - float(apos[1])) / dist
        elif self.board.hurt_bearing is not None:
            fx += -math.cos(self.board.hurt_bearing)
            fy += -math.sin(self.board.hurt_bearing)
        elif self.board.sound is not None:
            fx += -math.cos(self.board.sound)
            fy += -math.sin(self.board.sound)
        if zone and zone.get("center"):
            margin = zone_margin(float(zone.get("radius") or 0.0))
            if distance_outside(x, y, zone["center"], float(zone.get("radius") or 0.0)) > -margin:
                inward = norm(zone["center"][0] - x, zone["center"][1] - y)
                fx += inward[0] * 1.4
                fy += inward[1] * 1.4
        if self.grid is not None:
            return self.grid.slide(x, y, fx, fy)
        return norm(fx, fy)

    def _goal(self, state, features, mechs, loot, x, y, t, zone) -> Tuple[float, float]:
        center = zone.get("center") or (x, y)
        radius = float(zone.get("radius") or 0.0)
        nxt = zone.get("next_center") or center
        nr = float(zone.get("next_radius") or 0.0)
        margin = zone_margin(radius)
        if features["outside"]:
            return clamp_inside(x, y, center, radius, min(margin, max(4.0, radius * 0.02)))
        if state == LOOT and loot is not None:
            lp = loot["pos"]
            return clamp_inside(float(lp[0]), float(lp[1]), center, radius, min(6.0, margin))
        if state in (REPOSITION, RECOVER) and mechs and self.grid is not None:
            cover = self._cover(x, y, mechs[0][1].get("pos"), zone)
            if cover is not None and inside_circle(cover[0], cover[1], nxt, nr, min(8.0, zone_margin(nr))):
                return cover
        anchor = self._hold_point(x, y, mechs, nxt, nr, t, endgame=state == ENDGAME or features["endgame"])
        return clamp_inside(anchor[0], anchor[1], center, radius, margin)

    def _hold_point(self, x, y, mechs, nxt, nr, t, endgame: bool) -> Tuple[float, float]:
        if nr <= 8.0:
            return float(nxt[0]), float(nxt[1])
        away = self._threat_yaw(x, y, mechs)
        if away is None:
            away = ((self.seed % 628) / 100.0)
        else:
            away = away + math.pi
        frac = 0.22 if endgame or nr < 110.0 else 0.50
        dist = nr * frac
        return nxt[0] + math.cos(away) * dist, nxt[1] + math.sin(away) * dist

    def _threat_yaw(self, x, y, mechs) -> Optional[float]:
        if mechs:
            apos = mechs[0][1].get("pos")
            if apos:
                return math.atan2(float(apos[1]) - y, float(apos[0]) - x)
        if self.board.hurt_bearing is not None:
            return self.board.hurt_bearing
        return self.board.sound

    def _cover(self, x, y, enemy_pos, zone) -> Optional[Tuple[float, float]]:
        if enemy_pos is None or self.grid is None or len(enemy_pos) < 2:
            return None
        best = None
        best_s = -1e9
        radius = float(zone.get("radius") or 0.0)
        margin = zone_margin(radius)
        center = zone.get("center") or (x, y)
        ex, ey = float(enemy_pos[0]), float(enemy_pos[1])
        for k in range(12):
            ang = k * (math.tau / 12.0)
            for reach in (16.0, 28.0):
                cx = x + math.cos(ang) * reach
                cy = y + math.sin(ang) * reach
                if not self.grid.walkable(cx, cy):
                    continue
                if not inside_circle(cx, cy, center, radius, margin):
                    continue
                blocked = self.grid.segment_hits_block(cx, cy, ex, ey)
                dist_e = math.hypot(cx - ex, cy - ey)
                score = (50.0 if blocked else 0.0) + dist_e * 0.25 - reach * 0.05
                if score > best_s:
                    best_s = score
                    best = (cx, cy)
        return best

    def _boost(self, me, state, dist_goal: float, outside: bool) -> bool:
        energy = float(me.get("energy") or 0.0)
        weapons = me.get("weapons") or []
        for weapon in weapons:
            if weapon and weapon.get("kind") == "laser" and float(weapon.get("charge") or 0.0) > 0.02:
                return False
        if outside and energy > 8.0:
            return True
        if state == ESCAPE and energy > 16.0:
            return True
        if state in (ROTATE, ENDGAME) and dist_goal > 24.0 and energy > 44.0:
            return True
        if state not in (ENGAGE, RECOVER) and dist_goal > 55.0 and energy > 78.0:
            return True
        return False

    def _combat(self, obs, me, state, features, mechs, npcs, move, x, y, z):
        weapons = list(me.get("weapons") or [None, None])
        while len(weapons) < 2:
            weapons.append(None)
        target = mechs[0][1] if mechs else None
        nearest = features["nearest"]
        stats = me.get("stats") or {}
        muzzle_h = float(stats.get("muzzle_height") or (self.cfg.get("mech") or {}).get("muzzle_height") or 7.0)
        height = float(stats.get("height") or (self.cfg.get("mech") or {}).get("height") or 9.0)
        muzzle = (x, y, z + muzzle_h)
        los = features["los"] if target is not None and mechs and target is mechs[0][1] else False
        com = (target.get("pos") or [x, y, z])[2] + (1.6 if target and target.get("kind") == "npc" else 4.5) if target else z
        aim_aligned = False
        if target is not None and nearest < 1e8:
            apos = target.get("pos") or (x, y, z)
            desired = yaw_pitch(muzzle, (float(apos[0]), float(apos[1]), float(com)))
            aim_aligned = angle_error(me.get("aim") or [0.0, 0.0], desired) <= aim_gate(nearest)
        wants = wants_for(
            state,
            nearest if target else 1e9,
            features["isolated"],
            features["hp_frac"],
            gun_range=_gun_range(weapons, self.cfg),
            aim_aligned=aim_aligned,
            los=bool(los),
        )
        if target is None and npcs and features["npc_close"] < 22.0 and nearest > 60.0:
            target = npcs[0][1]
            nearest = features["npc_close"]
            wants = {"gun": True, "laser": False, "mortar": False, "lightning": features["npc_close"] < 16.0}
        look_yaw = self._look_yaw(state, features, mechs, move, x, y, me)
        tube = (x, y, z + height + 0.5)
        if target is not None and not mechs:
            if self.solids is not None:
                los = not self.solids.blocks_segment(muzzle, _body(target), 6.0)
            else:
                los = features["npc_close"] < 30.0
        com = (target.get("pos") or [x, y, z])[2] + (1.6 if target and target.get("kind") == "npc" else 4.5) if target else z
        ctx = {
            "weapons": weapons,
            "look": [look_yaw, 0.0],
            "actual_aim": me.get("aim") or [0.0, 0.0],
            "target": None
            if target is None
            else {**target, "com_z": com},
            "muzzle": muzzle,
            "tube": tube,
            "feet": (x, y, z),
            "dist": nearest if target is not None else 0.0,
            "los": los if target is not None else False,
            "wants": wants,
            "turn_rate": float(stats.get("turn_rate") or (self.cfg.get("mech") or {}).get("turn_rate") or 4.0),
            "min_pitch": float(stats.get("min_pitch") or (self.cfg.get("mech") or {}).get("min_pitch") or -0.7),
            "max_pitch": float(stats.get("max_pitch") or (self.cfg.get("mech") or {}).get("max_pitch") or 1.3),
            "energy": float(me.get("energy") or 0.0),
            "lightning_reserve": 25.0,
            "mortar_gravity": float(((self.cfg.get("weapons") or {}).get("mortar") or {}).get("gravity") or 22.0),
        }
        # Facing the shooter keeps the front arc (180 deg) on the threat. Rear hits are 1.5x.
        if target is not None and state in (ESCAPE, RECOVER, REPOSITION) and not wants["gun"] and not wants["lightning"]:
            apos = target.get("pos") or (x, y, z)
            yaw, pitch = yaw_pitch(muzzle, (apos[0], apos[1], com))
            ctx["look"] = [yaw, pitch]
            ctx["target"] = None
            wants = {k: False for k in wants}
            ctx["wants"] = wants
        return decide_weapons(ctx)

    def _look_yaw(self, state, features, mechs, move, x, y, me) -> float:
        if mechs and state != LOOT:
            apos = mechs[0][1].get("pos")
            if apos:
                return math.atan2(float(apos[1]) - y, float(apos[0]) - x)
        if self.board.hurt_bearing is not None and state in (ESCAPE, RECOVER, REPOSITION):
            return self.board.hurt_bearing
        if self.board.sound is not None and state in (SURVIVE, ROTATE, RECOVER, ENDGAME):
            return self.board.sound
        if abs(move[0]) + abs(move[1]) > 0.2:
            return math.atan2(move[1], move[0])
        aim = me.get("aim") or [0.0, 0.0]
        return float(aim[0]) + 0.35 * math.sin(float(features.get("idle") or 0.0) * 0.6)

    @staticmethod
    def _muzzle(me, x, y, z) -> Tuple[float, float, float]:
        stats = me.get("stats") or {}
        return (x, y, z + float(stats.get("muzzle_height") or 7.0))

    @staticmethod
    def _finite(v: float) -> bool:
        return v == v and abs(v) < 1e7


def _gun_range(weapons, cfg) -> float:
    for weapon in weapons or []:
        if not weapon or weapon.get("kind") != "gun":
            continue
        stats = weapon.get("stats") or {}
        if stats.get("range") is None:
            break
        try:
            return float(stats["range"])
        except (TypeError, ValueError):
            break
    try:
        return float(((cfg.get("weapons") or {}).get("gun") or {}).get("range") or 230.0)
    except (TypeError, ValueError):
        return 230.0


def _zone_ready(zone: dict) -> bool:
    return bool(zone) and zone.get("center") is not None and zone.get("next_center") is not None


def _laser_aimed(actor: dict, me_xy: Tuple[float, float]) -> bool:
    if not actor.get("charging"):
        return False
    pos = actor.get("pos")
    aim = actor.get("aim") or [0.0, 0.0]
    if not pos:
        return False
    bearing = math.atan2(me_xy[1] - float(pos[1]), me_xy[0] - float(pos[0]))
    return abs(wrap_angle(float(aim[0]) - bearing)) < 0.34


def _has_weapon(actor: dict, kind: str) -> bool:
    return kind in (actor.get("weapons") or [])


def _body(actor: dict) -> Tuple[float, float, float]:
    pos = actor.get("pos") or [0.0, 0.0, 0.0]
    extra = 1.6 if actor.get("kind") == "npc" else 4.5
    return (float(pos[0]), float(pos[1]), float(pos[2]) + extra)


def _strafe(x: float, y: float, tx: float, ty: float, pref: float, sign: int) -> List[float]:
    dx, dy = tx - x, ty - y
    dist = math.hypot(dx, dy) or 1.0
    ux, uy = dx / dist, dy / dist
    px, py = -uy * sign, ux * sign
    if dist > pref + 10.0:
        rx, ry = ux, uy
    elif dist < pref - 8.0:
        rx, ry = -ux, -uy
    else:
        rx, ry = 0.0, 0.0
    return norm(px + rx * 0.85, py + ry * 0.85)


def _repulse(x: float, y: float, mechs, reach: float) -> Tuple[float, float]:
    ax = ay = 0.0
    for dist, actor in mechs:
        if dist > reach or dist < 0.5:
            continue
        pos = actor.get("pos") or (x, y)
        w = ((reach - dist) / reach) ** 2
        ax += (x - float(pos[0])) / dist * w
        ay += (y - float(pos[1])) / dist * w
    return ax, ay


def _restrain(x: float, y: float, move: Sequence[float], zone: dict, in_zone: bool) -> List[float]:
    center = zone.get("center")
    if not center:
        return [float(move[0]), float(move[1])]
    radius = float(zone.get("radius") or 0.0)
    margin = zone_margin(radius)
    nx = x + float(move[0]) * 12.0
    ny = y + float(move[1]) * 12.0
    if inside_circle(nx, ny, center, radius, margin if in_zone else 0.0):
        return [float(move[0]), float(move[1])]
    inward = norm(center[0] - x, center[1] - y)
    if not in_zone:
        return norm(float(move[0]) + inward[0] * 1.6, float(move[1]) + inward[1] * 1.6)
    return norm(float(move[0]) * 0.3 + inward[0], float(move[1]) * 0.3 + inward[1])


def _unit_or_slow(move: Sequence[float]) -> List[float]:
    x, y = float(move[0]), float(move[1])
    if x != x or y != y:
        return [0.0, 0.0]
    mag = math.hypot(x, y)
    if mag > 1.0:
        return [x / mag, y / mag]
    return [x, y]
