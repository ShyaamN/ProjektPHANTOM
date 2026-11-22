"""Combat pilot: lead the shot, take the winning fight, leave the losing one.

Placement is the score (16 - finish). Kills matter because cubes scale damage
and HP, and because the last mech alive wins. They do not matter more than
being alive. Every visible mech is treated as a free-for-all opponent,
including ones that are not shooting yet: torsos turn at several radians
per second, so a passive-looking gun is still a gun.
"""
from __future__ import annotations

import math
import random

import mechfight as mf

from combat.aim import (
    beam_dodge,
    gun_hit_probability,
    gun_solution,
    laser_aim,
    laser_charge_fraction,
    laser_hit_probability,
    lightning_pick,
    mortar_expected_damage,
    mortar_solution,
    simulate_ballistic,
)
from combat.engage import (
    FightState,
    chase_allowed,
    cube_damage_scale,
    desired_weapon,
    exchange_losing,
    fight_decision,
    inside_circle,
    pick_upgrade,
    preferred_range,
    press_from_range,
    sustained_gun_dps,
    swap_worth,
    zone_circle,
)
from combat.mathutil import angle_between_yaw, clamp, dist2, dist3, finite, normalize2, wrap_angle
from combat.world import MapWorld

_HOSTILE_SOUNDS = {
    "gun", "mortar", "explosion", "laser", "laser_charge", "lightning",
    "step", "boost", "reload", "jet",
}
_DIST_RANK = {"near": 3.0, "mid": 2.0, "far": 1.0}


class CombatBot:
    name = "phantom-duelist"

    def __init__(self, hello):
        cfg = hello["config"]
        self.cfg = cfg
        self.mech = cfg["mech"]
        self.wcfg = cfg["weapons"]
        self.loot = cfg["loot"]
        self.cubes_cfg = cfg["cubes"]
        self.npc = cfg["npc"]
        self.slot = hello["slot"]
        match = cfg["match"]
        self.dt = match["decide_every"] / match["tick_hz"]
        self.rng = random.Random(int(hello["seed"]))
        self.world = MapWorld.load((hello.get("map") or {}).get("dir"))
        self.tracks = {}
        self.dealt = {}
        self.taken = {}
        self.strafe = 1.0 if self.rng.random() < 0.5 else -1.0
        self.strafe_until = 0.0
        self.scan = self.rng.random() * math.tau
        self.hear_bearing = None
        self.hear_t = -99.0
        self.jump_at = 0.0
        self.last_plan = {"mode": "boot", "decision": "none", "weapon": None, "target": None}

    def act(self, obs):
        action = self._plan(obs)
        self._draw(obs, action)
        return action

    # ---------------------------------------------------------------- world reads

    def _s(self, me, key):
        if key in me["stats"]:
            return me["stats"][key]
        return self.mech.get(key, 0.0)

    def _muzzle(self, me):
        return (me["pos"][0], me["pos"][1], me["pos"][2] + self._s(me, "muzzle_height"))

    def _eye(self, me):
        return (me["pos"][0], me["pos"][1], me["pos"][2] + self._s(me, "eye_height"))

    def _tube(self, me):
        return (me["pos"][0], me["pos"][1], me["pos"][2] + self._s(me, "height") + 0.5)

    def _standoff(self, me):
        return self._s(me, "radius") + 0.5

    def _body_radius(self, actor):
        per = self.cubes_cfg["size_per_cube"]
        if actor.get("kind") == "npc":
            return self.npc["radius"]
        return self.mech["radius"] * (1.0 + per * (actor.get("cubes") or 0))

    def _chest(self, actor):
        per = self.cubes_cfg["size_per_cube"]
        if actor.get("kind") == "npc":
            h = self.npc["height"] * 0.5
        else:
            h = self.mech["height"] * (1.0 + per * (actor.get("cubes") or 0)) * 0.5
        p = actor["pos"]
        return (p[0], p[1], p[2] + h)

    def _held(self, me):
        out = {}
        for i, weapon in enumerate(me["weapons"]):
            if weapon:
                out[weapon["kind"]] = (i, weapon)
        return out

    def _scale(self, cubes):
        return cube_damage_scale(cubes, self.cubes_cfg["damage_per_cube"], self.cubes_cfg["stat_cap"])

    def _pitch_limits(self, me):
        return (
            me["stats"].get("min_pitch", self.mech.get("min_pitch", -0.7)),
            me["stats"].get("max_pitch", self.mech.get("max_pitch", 1.3)),
        )

    # ---------------------------------------------------------------- memory

    def _note(self, book, key, t, amount):
        rows = book.setdefault(key, [])
        rows.append((t, amount))
        if len(rows) > 24:
            del rows[:-24]

    def _recent(self, book, key, t, window=6.0):
        rows = [row for row in book.get(key, ()) if t - row[0] <= window]
        book[key] = rows
        return sum(amount for _, amount in rows)

    def _remember(self, obs):
        t = obs["t"]
        me = obs["self"]
        seen = set()
        for actor in obs["mechs"]:
            seen.add(actor["id"])
            self.tracks[actor["id"]] = {
                "id": actor["id"],
                "kind": actor["kind"],
                "pos": actor["pos"],
                "vel": actor["vel"],
                "hp": actor.get("hp", 0.0),
                "weapons": list(actor.get("weapons") or []),
                "aim": actor["aim"],
                "charging": bool(actor.get("charging")),
                "cubes": actor.get("cubes") or 0,
                "t": t,
            }
        for event in obs.get("events") or []:
            kind = event.get("type")
            if kind == "damaged" and event.get("by") is not None:
                self._note(self.taken, event["by"], t, event.get("amount") or 0.0)
                if event.get("bearing") is not None:
                    self.hear_bearing = event["bearing"]
                    self.hear_t = t
            elif kind == "hit" and event.get("target") is not None:
                self._note(self.dealt, event["target"], t, event.get("amount") or 0.0)
        best = None
        for sound in obs.get("sounds") or []:
            if sound.get("kind") not in _HOSTILE_SOUNDS:
                continue
            score = _DIST_RANK.get(sound.get("dist"), 0.0) - (sound.get("age") or 0.0)
            if best is None or score > best[0]:
                best = (score, sound.get("bearing"))
        if best is not None and (self.hear_bearing is None or t - self.hear_t > 0.4):
            self.hear_bearing = best[1]
            self.hear_t = t
        # Drop tracks that vision memory would have forgotten, plus a little slack.
        memory = self.cfg["vision"].get("memory_s", 5.0) + 8.0
        for ident in list(self.tracks):
            if ident not in seen and t - self.tracks[ident]["t"] > memory:
                del self.tracks[ident]
        if t >= self.strafe_until:
            self.strafe = -self.strafe
            self.strafe_until = t + 0.65 + self.rng.random() * 0.35
        return me

    def _seen_counts(self, t):
        counts = {}
        for track in self.tracks.values():
            if track["kind"] != "mech" or t - track["t"] > 20.0:
                continue
            for kind in track["weapons"]:
                counts[kind] = counts.get(kind, 0) + 1
        return counts

    # ---------------------------------------------------------------- gunnery

    def _rear_bonus(self, me, actor):
        """True when a shot from us lands outside their front arc."""
        half = math.radians(self.mech.get("front_arc_deg", 180.0) * 0.5)
        incoming = math.atan2(me["pos"][1] - actor["pos"][1], me["pos"][0] - actor["pos"][0])
        if angle_between_yaw(actor["aim"][0], incoming) > half:
            return self.mech.get("rear_mult", 1.5)
        return 1.0

    def _they_aim_at_us(self, me, actor):
        yaw = math.atan2(me["pos"][1] - actor["pos"][1], me["pos"][0] - actor["pos"][0])
        return angle_between_yaw(actor["aim"][0], yaw) <= math.radians(22.0)

    def _incoming_dps(self, me, actor, dist):
        """Damage per second they can put on us if they choose to."""
        armor = clamp(self._s(me, "armor"), 0.0, 0.75)
        mit = 1.0 - armor
        half = math.radians(self._s(me, "front_arc_deg") * 0.5)
        bearing = math.atan2(actor["pos"][1] - me["pos"][1], actor["pos"][0] - me["pos"][0])
        rear = self._s(me, "rear_mult") if angle_between_yaw(me["aim"][0], bearing) > half else 1.0
        scale = self._scale(actor.get("cubes") or 0)
        aiming = self._they_aim_at_us(me, actor)
        face = 1.0 if aiming else 0.38
        our_speed = math.hypot(me["vel"][0], me["vel"][1])
        our_radius = self._s(me, "radius")
        if actor.get("kind") == "npc":
            if dist > self.npc["deaggro_range"]:
                return 0.0
            p = gun_hit_probability(
                dist, dist / max(self.npc["projectile_speed"], 1.0),
                self.npc["spread_deg"], our_radius, our_speed, self.npc["aggro_range"],
            )
            return self.npc["damage"] / max(self.npc["cooldown"], 0.1) * p * mit
        total = 0.0
        for kind in actor.get("weapons") or []:
            spec = self.wcfg.get(kind)
            if not spec:
                continue
            if kind == "gun":
                flight = dist / max(spec["speed"], 1.0)
                p = gun_hit_probability(dist, flight, spec["spread_deg"], our_radius, our_speed, spec["range"])
                total += sustained_gun_dps(spec["damage"] * scale, spec["cooldown"], spec["mag"], spec["reload"], p)
            elif kind == "laser" and dist <= spec["range"]:
                cycle = spec["charge"] + spec["cooldown"]
                total += spec["damage"] * scale * 0.55 / max(cycle, 0.1)
                if actor.get("charging"):
                    total += spec["damage"] * scale * 0.35
            elif kind == "lightning" and dist <= spec["range"] + 2.0:
                total += spec["damage"] * scale / max(spec["cooldown"], 0.05) * 0.8
            elif kind == "mortar":
                total += 55.0 * scale / max(spec["cooldown"], 0.1)
        return total * face * mit * rear

    def _our_weapons(self, me, actor, los):
        """Per-kind aim, hit probability, and a short-horizon damage value."""
        muzzle = self._muzzle(me)
        chest = self._chest(actor)
        feet = (actor["pos"][0], actor["pos"][1], actor["pos"][2] + 0.5)
        vel = actor["vel"]
        speed = math.hypot(vel[0], vel[1], vel[2])
        radius = self._body_radius(actor)
        scale = self._scale(me["cubes"]) * self._rear_bonus(me, actor)
        dist = dist3(muzzle, chest)
        held = self._held(me)
        lo, hi = self._pitch_limits(me)
        out = {"dist": dist, "los": los, "aims": {}, "hit": {}, "value": {}, "dps": 0.0, "primary": None}
        cover = 1.0 if los else 0.5

        if "gun" in held:
            _i, weapon = held["gun"]
            stats = weapon["stats"]
            sol = gun_solution(muzzle, chest, vel, stats["speed"], self._standoff(me), stats["range"])
            # Geometric distance includes the standoff, so the range check is
            # the bullet's flight, not the longer center-to-target segment.
            raw = gun_hit_probability(
                sol["dist"], sol["t"], stats["spread_deg"], radius, speed,
                stats["range"] + self._standoff(me),
            )
            if not sol["reachable"] or not (lo <= sol["pitch"] <= hi):
                raw = 0.0
            now = raw * (1.0 if los else 0.0)
            ammo = weapon.get("ammo", stats.get("mag", 0))
            reloading = (weapon.get("reload") or 0.0) > 0.05
            dps = sustained_gun_dps(stats["damage"] * scale, stats["cooldown"], stats["mag"], stats["reload"], raw * cover)
            value = 0.0 if reloading or ammo <= 0 else dps * 2.0 * (1.0 if los else 0.45)
            out["aims"]["gun"] = sol
            out["hit"]["gun"] = now
            out["value"]["gun"] = value
            out["dps"] = max(out["dps"], dps)

        if "laser" in held:
            _i, weapon = held["laser"]
            stats = weapon["stats"]
            charged = weapon.get("charge") or 0.0
            remaining = max(0.0, stats["charge"] - charged)
            # A full charge is the default; a close fast target gets a short one.
            if speed > 8.0 and dist < 55.0:
                remaining = max(0.0, stats["min_charge"] - charged)
            yaw, pitch, _point, ldist = laser_aim(muzzle, chest, vel, remaining)
            raw = laser_hit_probability(ldist, remaining, speed, radius, stats["range"])
            if not (lo <= pitch <= hi):
                raw = 0.0
            now = raw * (1.0 if los else 0.0)
            frac = max(laser_charge_fraction(max(charged, stats["min_charge"]), stats["charge"], stats["min_frac"]), 0.7)
            cook = stats.get("cookoff", self.wcfg["laser"].get("cookoff", 0.0))
            if "mortar" in (actor.get("weapons") or []):
                frac_damage = stats["damage"] * frac * (1.0 + cook)
            else:
                frac_damage = stats["damage"] * frac
            cycle = stats["charge"] + stats["cooldown"]
            dps = frac_damage * scale * raw * cover / max(cycle, 0.1)
            ready = (weapon.get("cooldown") or 0.0) <= 0.05 or charged > 0.02
            out["aims"]["laser"] = {"yaw": yaw, "pitch": pitch, "t": remaining, "point": _point, "dist": ldist}
            out["hit"]["laser"] = now
            out["value"]["laser"] = (frac_damage * scale * now) if ready else 0.0
            if ready:
                out["dps"] = max(out["dps"], dps)

        if "lightning" in held:
            _i, weapon = held["lightning"]
            stats = weapon["stats"]
            yaw = math.atan2(chest[1] - muzzle[1], chest[0] - muzzle[0])
            raw = 0.9 if dist <= stats["range"] and los else 0.0
            others = 0
            # Chain value is applied by the caller via `chains` if it bothers;
            # a flat bonus for a second body is enough to prefer the shot.
            dps = stats["damage"] * scale * raw / max(stats["cooldown"], 0.05)
            cost = stats.get("energy", self.wcfg["lightning"]["energy"])
            value = dps * 1.5 if me["energy"] >= cost else 0.0
            out["aims"]["lightning"] = {"yaw": yaw, "pitch": 0.0, "t": 0.0, "point": chest, "dist": dist}
            out["hit"]["lightning"] = raw
            out["value"]["lightning"] = value
            out["dps"] = max(out["dps"], dps * (1.0 if los else 0.0))
            out["lightning_cost"] = cost
            out["chains"] = others

        if "mortar" in held:
            _i, weapon = held["mortar"]
            stats = weapon["stats"]
            tube = self._tube(me)
            sol = mortar_solution(
                tube, feet, vel, stats["speed"], stats["gravity"], lo, hi, stats.get("ttl", 7.0), False,
            )
            raw_expected = 0.0
            if sol is not None:
                raw_expected = mortar_expected_damage(
                    sol["t"], speed, radius, stats["splash_radius"],
                    stats["damage"], stats["splash"], stats.get("splash_edge", 0.3),
                )
                if self._shell_blocked(tube, sol, stats) or self._splash_on_self(me, sol["point"], stats):
                    raw_expected = 0.0
                    sol = None
            dps = raw_expected * scale / max(stats["cooldown"], 0.1)
            ready = (weapon.get("cooldown") or 0.0) <= 0.05
            out["aims"]["mortar"] = sol
            out["hit"]["mortar"] = (raw_expected / max(stats["damage"], 1.0)) if sol else 0.0
            out["value"]["mortar"] = raw_expected * scale if ready and sol else 0.0
            out["dps"] = max(out["dps"], dps if ready else 0.0)

        best_kind = None
        best_value = 0.0
        for kind, value in out["value"].items():
            if value > best_value:
                best_value = value
                best_kind = kind
        out["primary"] = best_kind
        return out

    def _shell_blocked(self, tube, sol, stats) -> bool:
        if not self.world.ok or sol is None:
            return False
        prev = tube
        steps = 6
        for i in range(1, steps + 1):
            t = sol["t"] * i / steps
            point = simulate_ballistic(tube, sol["yaw"], sol["pitch"], stats["speed"], stats["gravity"], t)
            if self.world.blocked(prev, point):
                return True
            prev = point
        return False

    def _splash_on_self(self, me, point, stats) -> bool:
        if point is None:
            return True
        return dist2(me["pos"][0], me["pos"][1], point[0], point[1]) < stats["splash_radius"] + 2.0

    def _aligned(self, me, yaw, pitch, slop_yaw, slop_pitch):
        dy = angle_between_yaw(me["aim"][0], yaw)
        dp = abs(pitch - me["aim"][1])
        turn = max(self._s(me, "turn_rate"), 0.2)
        rate = max(self._s(me, "pitch_rate"), 0.2)
        slew = max(dy / turn, dp / rate)
        return dy <= slop_yaw and dp <= slop_pitch, slew, dy, dp

    # ---------------------------------------------------------------- decisions

    def _plan(self, obs):
        me = self._remember(obs)
        held = self._held(me)
        t = obs["t"]
        hp_frac = me["hp"] / me["max_hp"] if me["max_hp"] else 0.0
        eye = self._eye(me)
        actors = list(obs.get("mechs") or [])
        evaluations = []
        on_me = 0
        threat_dps = 0.0
        for actor in actors:
            if actor["id"] == me["id"]:
                continue
            chest = self._chest(actor)
            los = not self.world.blocked(eye, chest)
            info = self._our_weapons(me, actor, los)
            incoming = self._incoming_dps(me, actor, info["dist"])
            aiming = actor.get("kind") == "mech" and self._they_aim_at_us(me, actor)
            reaches = incoming > 8.0 or info["dist"] < 70.0
            if aiming and reaches and actor.get("kind") == "mech":
                on_me += 1
                threat_dps += incoming
            evaluations.append((actor, info, incoming, aiming))

        target = None
        info = None
        incoming = 0.0
        best_score = -1e18
        for actor, ev, inc, aiming in evaluations:
            if ev["dist"] > 260.0:
                continue
            score = ev["dps"] * 1.4 - inc * 0.35 - ev["dist"] * 0.12
            if actor.get("kind") == "mech":
                score += 180.0
            else:
                score += 25.0
            if aiming:
                score += 35.0
            hp = actor.get("hp")
            if hp is not None and hp < 350:
                score += 45.0
            if not ev["los"] and "mortar" not in held:
                score -= 25.0
            if score > best_score:
                best_score = score
                target = actor
                info = ev
                incoming = inc

        decision = "none"
        if target is not None:
            dealt = self._recent(self.dealt, target["id"], t)
            taken = self._recent(self.taken, target["id"], t)
            losing = exchange_losing(dealt, taken, hp_frac)
            enemy_dps = max(incoming, threat_dps if on_me else incoming)
            state = FightState(
                my_hp=me["hp"],
                my_max=me["max_hp"],
                enemy_hp=_actor_hp(target),
                my_dps=max(info["dps"], 0.0),
                enemy_dps=enemy_dps,
                enemies_on_me=on_me,
                in_zone=bool(me["in_zone"]),
                zone_dps=obs["zone"]["dps"] if me["in_zone"] else obs["zone"]["dps"],
                alive=obs["alive"],
                exchange_losing=losing,
            )
            # Zone damage is already in `in_zone`. Pass the live dps either way
            # so an out-of-zone fight can see the clock.
            state.in_zone = bool(me["in_zone"])
            state.zone_dps = obs["zone"]["dps"]
            decision = fight_decision(state)
            if decision == "trade" and hp_frac < 0.4 and obs["alive"] > 2:
                decision = "disengage"
            decision = press_from_range(
                decision,
                info["dist"],
                preferred_range(list(held), target.get("weapons") or []),
                me["hp"],
                info["dps"],
                enemy_dps,
                hp_frac,
                on_me,
                bool(me["in_zone"]),
            )
        else:
            state = None

        cx, cy, radius = zone_circle(obs["zone"], t, ahead=6.0)
        px, py = me["pos"][0], me["pos"][1]
        in_future = inside_circle(px, py, cx, cy, radius, 16.0)
        their_ttk = math.inf
        if target is not None and info is not None and info["dps"] > 1.0:
            their_ttk = _actor_hp(target) / info["dps"]
        urgent = not in_future
        quick = (
            target is not None
            and decision == "commit"
            and their_ttk < 1.6
            and me["in_zone"]
        )
        shoot = False
        mode = "zone"
        goal = (cx, cy)

        drop_goal = self._capture_goal(obs, me, on_me, decision)
        loot_goal = None if drop_goal else self._loot_goal(obs, me, held, in_future, cx, cy, radius)

        if drop_goal is not None and drop_goal[0] == "stay":
            mode = "capture"
            goal = drop_goal[1]
        elif urgent and not quick:
            mode = "zone"
            goal = (cx, cy)
            shoot = target is not None and decision != "disengage"
        elif decision == "disengage" and target is not None:
            mode = "leave"
            goal = (cx, cy)
            shoot = True
        elif target is not None and decision in ("commit", "trade"):
            allowed = chase_allowed(info["dist"], in_future, me["hp"], obs["zone"]["dps"], their_ttk)
            if allowed or decision == "trade":
                mode = "fight"
                shoot = True
            else:
                mode = "zone"
                shoot = True
        elif drop_goal is not None:
            mode = "capture"
            goal = drop_goal[1]
        elif hp_frac < 0.62 and on_me == 0 and target is None:
            mode = "zone"
            shoot = False
        elif loot_goal is not None:
            mode = "loot"
            goal = loot_goal
            shoot = False
        else:
            mode = "zone"
            shoot = False

        primary = info["primary"] if info else None
        # A laser that is already charging owns the aim until it releases.
        laser_slot = held.get("laser")
        charging = bool(laser_slot and (laser_slot[1].get("charge") or 0.0) > 0.02)
        if charging and info and "laser" in info["aims"]:
            primary = "laser"

        yaw, pitch = self._command_aim(me, obs, target, info, primary, mode)
        fire = [False, False]
        reload = False
        if shoot and target is not None and info is not None:
            fire, reload, primary = self._triggers(
                me, obs, target, info, primary, decision, hp_frac, charging, actors,
            )
        elif not shoot:
            # Release a charge if we are done fighting so movement is full speed.
            if charging and laser_slot is not None:
                fire[laser_slot[0]] = False
            reload = self._should_reload(held, shoot=False, need=0.0)

        move, boost, jump = self._move(obs, me, mode, goal, target, info, decision, fire, held)

        action = {
            "tick": obs["tick"],
            "move": move,
            "aim": [yaw, pitch],
            "boost": boost,
            "jump": jump,
            "fire": fire,
        }
        if reload:
            action["reload"] = True
        take = self._take(me, obs, held, charging, decision)
        if take is not None:
            action["take"] = take["id"]
            if take.get("drop") is not None:
                action["drop"] = take["drop"]
        if obs.get("offer"):
            action["pick"] = pick_upgrade(obs["offer"]["choices"])

        action = self._sanitize(me, action)
        hit = 0.0
        if info and primary:
            hit = info["hit"].get(primary, 0.0)
        self.last_plan = {
            "mode": mode,
            "decision": decision,
            "weapon": primary,
            "target": None if target is None else target["id"],
            "hit": hit,
            "on_me": on_me,
        }
        return action

    def _command_aim(self, me, obs, target, info, primary, mode):
        lo, hi = self._pitch_limits(me)
        if target is not None and info is not None and primary and info["aims"].get(primary):
            sol = info["aims"][primary]
            if sol:
                return wrap_angle(sol["yaw"]), clamp(sol["pitch"], lo, hi)
        if target is not None:
            yaw, pitch, _h, _z = _bare_aim(self._muzzle(me), self._chest(target))
            return wrap_angle(yaw), clamp(pitch, lo, hi)
        if self.hear_bearing is not None and obs["t"] - self.hear_t < 2.5:
            return wrap_angle(self.hear_bearing), 0.0
        self.scan = wrap_angle(self.scan + 2.4 * self.dt)
        return self.scan, 0.04

    def _triggers(self, me, obs, target, info, primary, decision, hp_frac, charging, actors):
        held = self._held(me)
        fire = [False, False]
        muzzle = self._muzzle(me)
        lo, hi = self._pitch_limits(me)
        # Gun. Only along the actual aim: the server does not fire the command.
        if "gun" in held and info["aims"].get("gun"):
            sol = info["aims"]["gun"]
            _i, weapon = held["gun"]
            stats = weapon["stats"]
            ammo = weapon.get("ammo", 0)
            reloading = (weapon.get("reload") or 0) > 0.05
            aligned, slew, dy, _dp = self._aligned(me, sol["yaw"], sol["pitch"], 0.06, 0.08)
            ang = math.atan2(self._body_radius(target), max(info["dist"], 1.0))
            close_enough = dy <= max(0.045, ang * 1.15) and slew < 0.12
            execute = _actor_hp(target, 9999.0) < stats["damage"] * self._scale(me["cubes"]) * 1.3
            if (
                info["hit"]["gun"] >= (0.08 if execute else 0.14)
                and info["los"]
                and sol["reachable"]
                and ammo > 0
                and not reloading
                and close_enough
                and lo <= sol["pitch"] <= hi
            ):
                # Don't spend the last bullets on a bad angle while leaving.
                if not (decision == "disengage" and ammo <= 3 and info["hit"]["gun"] < 0.35):
                    fire[_i] = True

        # Lightning is instant and yaw-only. Fire on the current torso yaw.
        if "lightning" in held:
            _i, weapon = held["lightning"]
            stats = weapon["stats"]
            cost = stats.get("energy", self.wcfg["lightning"]["energy"])
            reserve = 18.0 if decision == "disengage" else 6.0
            if me["energy"] >= cost + reserve or _actor_hp(target, 9999.0) < stats["damage"] * 1.4:
                picked = self._lightning_target(me, actors, obs, stats)
                want_id = target["id"]
                if picked is not None and picked["id"] == want_id and info["los"]:
                    err = angle_between_yaw(me["aim"][0], picked["yaw"])
                    # Tight on purpose: cone_deg is "within N degrees", and a
                    # miss inside a misread cone still costs energy.
                    if err <= math.radians(min(stats["cone_deg"], 12.0)) and picked["dist"] <= stats["range"]:
                        fire[_i] = True

        # Mortar only when it is the chosen arc. Pitch is the whole weapon.
        if primary == "mortar" and "mortar" in held and info["aims"].get("mortar"):
            sol = info["aims"]["mortar"]
            _i, weapon = held["mortar"]
            if sol and (weapon.get("cooldown") or 0) <= 0.05 and info["value"]["mortar"] >= 40.0:
                aligned, _slew, _dy, _dp = self._aligned(me, sol["yaw"], sol["pitch"], 0.04, 0.04)
                if aligned:
                    fire[_i] = True

        # Laser: hold to charge, release to fire. Charging halves move speed,
        # so a losing fight releases immediately.
        if "laser" in held:
            _i, weapon = held["laser"]
            stats = weapon["stats"]
            charged = weapon.get("charge") or 0.0
            cooldown = weapon.get("cooldown") or 0.0
            want = primary == "laser" and info["los"] and info["dist"] <= stats["range"]
            if decision == "disengage" and hp_frac < 0.5:
                want = False
            lightning_near = self._lightning_threat(me, actors)
            if not charging and lightning_near and "lightning" not in held:
                want = False
            if charging and decision == "disengage" and hp_frac < 0.45:
                fire[_i] = False  # release, regain speed, the beam still leaves
            elif cooldown > 0.08 and charged <= 0.02:
                fire[_i] = False
            elif want or charging:
                sol = info["aims"].get("laser")
                release_at = stats["charge"]
                if hp_frac < 0.45 or info["dist"] < 40.0:
                    release_at = stats["min_charge"]
                elif _actor_hp(target, 9999.0) <= stats["damage"] * stats["min_frac"] * self._scale(me["cubes"]) * 1.15:
                    release_at = stats["min_charge"]
                ready = charged + 1e-6 >= max(release_at, stats["min_charge"]) * 0.96
                if charged >= stats["charge"] + stats.get("hold_s", 2.0) - 0.12:
                    ready = True
                aligned = False
                if sol:
                    aligned, _s, _dy, _dp = self._aligned(me, sol["yaw"], sol["pitch"], 0.045, 0.06)
                if ready and aligned:
                    fire[_i] = False
                elif ready and not aligned and charged >= stats["charge"]:
                    fire[_i] = True  # keep turning through the hold window
                else:
                    fire[_i] = True
            else:
                fire[_i] = False

        need = _actor_hp(target, 0.0)
        reload = self._should_reload(held, shoot=fire[held["gun"][0]] if "gun" in held else False, need=need)
        if "gun" in held and fire[held["gun"][0]]:
            reload = False
        return fire, reload, primary

    def _should_reload(self, held, shoot, need):
        if "gun" not in held:
            return False
        _i, weapon = held["gun"]
        stats = weapon["stats"]
        ammo = weapon.get("ammo", 0)
        if (weapon.get("reload") or 0) > 0:
            return False
        if ammo <= 0:
            return True
        if shoot and need > 0 and ammo * stats["damage"] >= need:
            return False
        if ammo <= max(2, stats["mag"] * 0.2) and not shoot:
            return True
        return False

    def _lightning_target(self, me, actors, obs, stats):
        muzzle = self._muzzle(me)
        items = []
        for actor in actors:
            chest = self._chest(actor)
            dist = dist3(muzzle, chest)
            items.append({
                "id": actor["id"],
                "x": chest[0],
                "y": chest[1],
                "dist": dist,
                "yaw": math.atan2(chest[1] - muzzle[1], chest[0] - muzzle[0]),
            })
        for crate in obs.get("crates") or []:
            pos = crate["pos"]
            dist = dist3(muzzle, (pos[0], pos[1], pos[2] + 1.0))
            items.append({
                "id": crate["id"],
                "x": pos[0],
                "y": pos[1],
                "dist": dist,
                "yaw": math.atan2(pos[1] - muzzle[1], pos[0] - muzzle[0]),
            })
        return lightning_pick(me["aim"][0], (muzzle[0], muzzle[1]), items, stats["range"], stats["cone_deg"])

    def _lightning_threat(self, me, actors):
        spec = self.wcfg["lightning"]
        for actor in actors:
            if actor.get("kind") != "mech":
                continue
            if "lightning" not in (actor.get("weapons") or []):
                continue
            d = dist2(me["pos"][0], me["pos"][1], actor["pos"][0], actor["pos"][1])
            if d <= spec["range"] + 6.0 and self._they_aim_at_us(me, actor):
                return True
        return False

    def _capture_goal(self, obs, me, on_me, decision):
        best = None
        best_d = 1e18
        px, py = me["pos"][0], me["pos"][1]
        for drop in obs.get("drops") or []:
            if drop.get("holder") == me["id"] and (drop.get("lands_in") or 0) <= 0:
                if on_me >= 2 or (decision == "disengage" and me["hp"] < me["max_hp"] * 0.35):
                    continue
                return ("stay", (drop["pos"][0], drop["pos"][1]))
            if (drop.get("lands_in") or 0) > 12.0:
                continue
            d = dist2(px, py, drop["pos"][0], drop["pos"][1])
            if d < best_d and d < 140.0 and on_me == 0 and decision != "commit":
                best = (drop["pos"][0], drop["pos"][1])
                best_d = d
        if best is None:
            return None
        return ("go", best)

    def _loot_goal(self, obs, me, held, in_future, cx, cy, radius):
        have = set(held)
        empty = any(weapon is None for weapon in me["weapons"])
        counts = self._seen_counts(obs["t"])
        want = desired_weapon(have, counts)
        px, py, pz = me["pos"]
        best = None
        best_score = -1e18
        reach = 100.0 if empty else 32.0
        for pickup in obs.get("pickups") or []:
            kind = pickup["kind"]
            if kind in have or kind == "gun":
                continue
            if not empty and not swap_worth(have, counts, kind):
                continue
            if abs(pickup["pos"][2] - pz) > 8.0:
                continue
            d = dist2(px, py, pickup["pos"][0], pickup["pos"][1])
            if d > reach:
                continue
            if not inside_circle(pickup["pos"][0], pickup["pos"][1], cx, cy, radius, 0.0) and d > 25.0:
                continue
            score = 80.0 - d
            if kind == want:
                score += 50.0
            if empty:
                score += 30.0
            if score > best_score:
                best_score = score
                best = (pickup["pos"][0], pickup["pos"][1])
        if best is not None:
            return best
        if me["hp"] > me["max_hp"] * 0.8:
            for cube in obs.get("cubes") or []:
                if abs(cube["pos"][2] - pz) > 6.0:
                    continue
                d = dist2(px, py, cube["pos"][0], cube["pos"][1])
                if d <= 26.0 and (in_future or d < 12.0):
                    return (cube["pos"][0], cube["pos"][1])
        return None

    def _take(self, me, obs, held, charging, decision):
        if charging:
            return None
        have = set(held)
        empty_index = next((i for i, weapon in enumerate(me["weapons"]) if weapon is None), None)
        # A committed duel does not stop to swap. An empty slot is still a
        # one-line take, because it does not drop the weapon we are firing.
        if decision == "commit" and empty_index is None:
            return None
        px, py, pz = me["pos"]
        radius = self.loot["pickup_radius"]
        counts = self._seen_counts(obs["t"])
        want = desired_weapon(have, counts)
        best = None
        best_score = -1e18
        for pickup in obs.get("pickups") or []:
            kind = pickup["kind"]
            if kind in have:
                continue
            if dist2(px, py, pickup["pos"][0], pickup["pos"][1]) > radius:
                continue
            if abs(pickup["pos"][2] - pz) > 4.0:
                continue
            score = 10.0 if kind == want else 0.0
            score += {"laser": 3, "lightning": 2, "mortar": 1}.get(kind, 0)
            if score > best_score:
                best_score = score
                best = pickup
        if best is None:
            return None
        if empty_index is not None:
            return {"id": best["id"]}
        if not swap_worth(have, counts, best["kind"]):
            return None
        # Swap the non-gun slot. A charging laser never reaches here.
        drop = None
        for kind, (index, _weapon) in held.items():
            if kind != "gun":
                drop = index
                break
        if drop is None:
            return None
        return {"id": best["id"], "drop": drop}

    def _move(self, obs, me, mode, goal, target, info, decision, fire, held):
        px, py = me["pos"][0], me["pos"][1]
        dodge = self._dodge(me, obs.get("projectiles") or [])
        beamed = beam_dodge(px, py, obs.get("beams") or [])
        if beamed is not None:
            if dodge is None:
                dodge = beamed
            else:
                dodge = normalize2(dodge[0] + beamed[0], dodge[1] + beamed[1])
        boost = False
        jump = False
        energy = me["energy"]
        if mode == "fight" and target is not None and info is not None:
            dx, dy = normalize2(target["pos"][0] - px, target["pos"][1] - py)
            sx, sy = -dy * self.strafe, dx * self.strafe
            have = list(held)
            enemy_weapons = target.get("weapons") or []
            pref = preferred_range(have, enemy_weapons)
            toward = clamp((info["dist"] - pref) / 28.0, -1.0, 1.0)
            if not info["los"]:
                toward = clamp(toward, -0.15, 0.3)
            mx = sx * 0.95 + dx * toward * 0.75
            my = sy * 0.95 + dy * toward * 0.75
            if energy > 58.0 and "lightning" not in held and decision == "commit":
                boost = True
        elif mode == "leave" and target is not None:
            ax, ay = normalize2(px - target["pos"][0], py - target["pos"][1])
            zx, zy = normalize2(goal[0] - px, goal[1] - py)
            mx, my = ax * 0.85 + zx * 0.7, ay * 0.85 + zy * 0.7
            if energy > 20.0:
                boost = True
        elif mode == "capture":
            d = dist2(px, py, goal[0], goal[1])
            if d < 3.5:
                mx, my = 0.0, 0.0
            else:
                mx, my = normalize2(goal[0] - px, goal[1] - py)
            if d > 12.0 and energy > 30.0:
                boost = True
        else:
            mx, my = normalize2(goal[0] - px, goal[1] - py)
            outside = not me["in_zone"]
            if (outside or mode == "zone") and energy > 24.0 and dist2(px, py, goal[0], goal[1]) > 18.0:
                # Boost only when the circle is actually a problem or the walk is long.
                cx, cy, radius = zone_circle(obs["zone"], obs["t"], 0.0)
                if outside or dist2(px, py, cx, cy) > max(0.0, radius - 30.0):
                    boost = True
        if dodge is not None:
            mx += dodge[0] * 1.15
            my += dodge[1] * 1.15
            if energy > 28.0:
                boost = True
            if me["grounded"] and obs["t"] >= self.jump_at:
                jump = True
                self.jump_at = obs["t"] + 0.8
        elif (
            target is not None
            and target.get("charging")
            and info is not None
            and info["dist"] < 90.0
            and me["grounded"]
            and obs["t"] >= self.jump_at
        ):
            jump = True
            self.jump_at = obs["t"] + 1.0
        # Lightning spends energy. Don't boost it away while the trigger is down
        # unless a projectile is already on us (handled above).
        if "lightning" in held and any(fire) and dodge is None and mode == "fight":
            boost = False
        n = math.hypot(mx, my)
        if n > 1.0:
            mx, my = mx / n, my / n
        elif n < 1e-8:
            mx, my = 0.0, 0.0
        return [mx, my], boost, jump

    def _dodge(self, me, projectiles):
        if not projectiles:
            return None
        px, py = me["pos"][0], me["pos"][1]
        pz = me["pos"][2] + self._s(me, "height") * 0.5
        radius = self._s(me, "radius") + 1.4
        gravity = self.wcfg["mortar"]["gravity"]
        best = None
        best_t = 99.0
        for shot in projectiles:
            pos = shot["pos"]
            vel = shot["vel"]
            if shot["kind"] == "mortar":
                for step in range(1, 14):
                    t = step * 0.1
                    x = pos[0] + vel[0] * t
                    y = pos[1] + vel[1] * t
                    z = pos[2] + vel[2] * t - 0.5 * gravity * t * t
                    if math.hypot(x - px, y - py) < radius + self.wcfg["mortar"]["splash_radius"] and abs(z - me["pos"][2]) < 6.0:
                        if t < best_t:
                            best_t = t
                            best = normalize2(px - x, py - y)
                        break
                continue
            rx, ry, rz = pos[0] - px, pos[1] - py, pos[2] - pz
            vx = vel[0] - me["vel"][0]
            vy = vel[1] - me["vel"][1]
            vz = vel[2]
            vv = vx * vx + vy * vy + vz * vz
            if vv < 1.0:
                continue
            t = -(rx * vx + ry * vy + rz * vz) / vv
            if t < 0.0 or t > 0.5:
                continue
            cx, cy, cz = rx + vx * t, ry + vy * t, rz + vz * t
            if math.sqrt(cx * cx + cy * cy + cz * cz) <= radius and t < best_t:
                best_t = t
                best = normalize2(-vy, vx)
        return best

    def _sanitize(self, me, action):
        mx, my = action["move"]
        n = math.hypot(mx, my)
        if n > 1.0:
            mx, my = mx / n, my / n
        action["move"] = [finite(mx), finite(my)]
        lo, hi = self._pitch_limits(me)
        yaw = finite(action["aim"][0], me["aim"][0])
        pitch = finite(action["aim"][1], me["aim"][1])
        action["aim"] = [wrap_angle(yaw), clamp(pitch, lo, hi)]
        fire = action["fire"]
        action["fire"] = [bool(fire[0]), bool(fire[1])]
        action["boost"] = bool(action["boost"])
        action["jump"] = bool(action["jump"])
        return action

    def _draw(self, obs, action):
        me = obs["self"]
        plan = self.last_plan
        weapon = plan.get("weapon") or "-"
        mode = plan.get("mode") or "-"
        hit = plan.get("hit") or 0.0
        mf.draw.label(f"{mode} {weapon} p{hit:.2f} hp{me['hp']:.0f}")
        target_id = plan.get("target")
        if target_id is None:
            return
        for actor in obs.get("mechs") or []:
            if actor["id"] == target_id:
                muzzle = self._muzzle(me)
                chest = self._chest(actor)
                mf.draw.line(list(muzzle), list(chest), "#ff5040")
                break


def _bare_aim(src, dst):
    from combat.mathutil import yaw_pitch_toward
    return yaw_pitch_toward(src, dst)


def _actor_hp(actor, default=1.0):
    hp = actor.get("hp")
    if hp is None:
        hp = actor.get("max_hp")
    if hp is None:
        return default
    return hp
