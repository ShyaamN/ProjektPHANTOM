"""Deterministic checks for protocol shape, tactics, and decision latency.

A passing test is not a match score. The kit has no simulator.
"""
from __future__ import annotations

import copy
import gzip
import json
import math
import os
import subprocess
import sys
import time
import unittest
from array import array

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from combat.aim import gun_lead, mortar_impact, mortar_pitches, projectile_dodge, yaw_pitch  # noqa: E402
from combat.weapons import decide, gun_should_fire, laser_hold, lightning_should_fire, mortar_should_fire  # noqa: E402
from navigation.grid import NavGrid  # noqa: E402
from navigation.path import Pilot  # noqa: E402
from strategy.brain import Brain  # noqa: E402
from strategy.loot import choose_take, pick_upgrade  # noqa: E402
from strategy.state import (  # noqa: E402
    ENDGAME,
    ENGAGE,
    ESCAPE,
    LOOT,
    RECOVER,
    REPOSITION,
    ROTATE,
    SURVIVE,
    allow_return_fire,
    decide_state,
    wants_for,
)
from strategy.zone import clamp_inside, inside_circle, must_rotate, zone_margin  # noqa: E402


def _stream():
    path = os.path.join(ROOT, "check", "stream.jsonl.gz")
    with gzip.open(path, "rt") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class TacticsTest(unittest.TestCase):
    def test_gun_lead_stationary_is_direct(self):
        muzzle = (0.0, 0.0, 0.0)
        pos = (100.0, 0.0, 0.0)
        aim, point, tof = gun_lead(muzzle, pos, (0.0, 0.0, 0.0), 252.0)
        self.assertAlmostEqual(aim[0], 0.0, places=5)
        self.assertAlmostEqual(point[0], 100.0, places=3)
        self.assertAlmostEqual(tof, 100.0 / 252.0, places=3)

    def test_gun_lead_beats_direct_on_crossing_target(self):
        muzzle = (0.0, 0.0, 0.0)
        pos = (80.0, 0.0, 0.0)
        vel = (0.0, 20.0, 0.0)
        speed = 252.0
        aim, _point, tof = gun_lead(muzzle, pos, vel, speed)
        lead_err = _miss(muzzle, aim, speed, tof, pos, vel)
        direct = yaw_pitch(muzzle, pos)
        t_direct = math.dist(muzzle, pos) / speed
        direct_err = _miss(muzzle, direct, speed, t_direct, pos, vel)
        self.assertLess(lead_err, 1.0)
        self.assertLess(lead_err, direct_err * 0.25)

    def test_mortar_pitch_roundtrip(self):
        speed, gravity = 72.0, 22.0
        pitch = math.radians(30.0)
        t = 2.0
        distance = speed * math.cos(pitch) * t
        dz = speed * math.sin(pitch) * t - 0.5 * gravity * t * t
        pitches = mortar_pitches(distance, dz, speed, gravity)
        self.assertTrue(any(abs(p - pitch) < 0.02 for p in pitches))
        self.assertLess(pitches[0], pitches[-1])

    def test_mortar_flat_ground_has_a_low_arc(self):
        pitches = mortar_pitches(100.0, 0.0, 72.0, 22.0)
        self.assertGreaterEqual(len(pitches), 2)
        self.assertLess(pitches[0], math.radians(45.0))
        self.assertGreater(pitches[-1], math.radians(45.0))

    def test_mortar_impact_falls_to_ground(self):
        hit = mortar_impact((0.0, 0.0, 10.0), (5.0, 0.0, 0.0), 22.0, 0.0)
        self.assertIsNotNone(hit)
        impact, tof = hit
        self.assertAlmostEqual(tof, math.sqrt(2.0 * 10.0 / 22.0), places=2)
        self.assertAlmostEqual(impact[2], 0.0, places=5)

    def test_projectile_dodge_on_headon_bullet(self):
        dodge = projectile_dodge((0.0, 0.0, 0.0), [{"kind": "gun", "pos": [-30.0, 0.0, 0.0], "vel": [100.0, 0.0, 0.0]}], 22.0, 7.0)
        self.assertIsNotNone(dodge)
        self.assertAlmostEqual(math.hypot(*dodge), 1.0, places=3)

    def test_projectile_dodge_ignores_distant_bullet(self):
        dodge = projectile_dodge((0.0, 0.0, 0.0), [{"kind": "gun", "pos": [-30.0, 40.0, 0.0], "vel": [100.0, 0.0, 0.0]}], 22.0, 7.0)
        self.assertIsNone(dodge)

    def test_state_priority(self):
        self.assertEqual(decide_state({"outside": True, "panic": True, "can_engage": True}), ROTATE)
        self.assertEqual(decide_state({"must_rotate": True, "loot_worth": True}), ROTATE)
        self.assertEqual(decide_state({"panic": True, "can_engage": True}), ESCAPE)
        self.assertEqual(decide_state({"should_recover": True, "can_engage": True}), RECOVER)
        self.assertEqual(decide_state({"can_engage": True, "loot_worth": True}), ENGAGE)
        self.assertEqual(decide_state({"endgame": True, "loot_worth": True}), ENDGAME)
        self.assertEqual(decide_state({"loot_worth": True, "threat_near": True}), LOOT)
        self.assertEqual(decide_state({"threat_near": True}), REPOSITION)
        self.assertEqual(decide_state({}), SURVIVE)

    def test_zone_clamp_and_rotate_window(self):
        self.assertTrue(inside_circle(0.0, 0.0, (0.0, 0.0), 10.0, 0.0))
        self.assertFalse(inside_circle(9.0, 0.0, (0.0, 0.0), 10.0, 2.0))
        x, y = clamp_inside(50.0, 0.0, (0.0, 0.0), 10.0, 2.0)
        self.assertAlmostEqual(math.hypot(x, y), 8.0, places=4)
        zone = {"center": [0, 0], "radius": 100, "next_center": [0, 0], "next_radius": 20, "shrink_start": 60, "shrink_end": 110}
        self.assertFalse(must_rotate(0.0, zone, 40.0, 0.0))
        self.assertFalse(must_rotate(20.0, zone, 40.0, 0.0))
        self.assertTrue(must_rotate(30.0, zone, 40.0, 0.0))
        self.assertTrue(must_rotate(50.0, zone, 40.0, 0.0))
        self.assertGreater(zone_margin(560.0), zone_margin(20.0))

    def test_upgrade_prefers_armor_when_hurt(self):
        choices = [{"id": "gun_damage"}, {"id": "sensors"}, {"id": "armor"}]
        self.assertEqual(pick_upgrade(choices, ["gun"], 0.4), 2)

    def test_choose_take_laser_into_empty_slot(self):
        gun = {"kind": "gun", "cooldown": 0, "ammo": 12, "reload": 0, "stats": {}}
        weapons = [gun, None]
        action = choose_take((0, 0, 0), weapons, [{"id": 8010, "kind": "laser", "pos": [3.0, 0.0, 0.2]}], 4.0)
        self.assertEqual(action, {"take": 8010})
        self.assertIsNone(choose_take((0, 0, 0), weapons, [{"id": 1, "kind": "laser", "pos": [3.0, 0.0, 6.0]}], 4.0))
        self.assertIsNone(choose_take((0, 0, 0), weapons, [{"id": 2, "kind": "gun", "pos": [1.0, 0.0, 0.0]}], 4.0))

    def test_choose_take_swaps_lightning_for_laser(self):
        weapons = [
            {"kind": "gun", "ammo": 12, "reload": 0, "stats": {}},
            {"kind": "lightning", "cooldown": 0, "charge": 0, "stats": {}},
        ]
        action = choose_take((0, 0, 0), weapons, [{"id": 9, "kind": "laser", "pos": [1.0, 1.0, 0.0]}], 4.0)
        self.assertEqual(action, {"take": 9, "drop": 1})

    def test_weapon_gates(self):
        self.assertTrue(gun_should_fire(12, False, 40.0, 230.0, 0.02, True, True))
        self.assertFalse(gun_should_fire(12, False, 40.0, 230.0, 0.02, False, True))
        self.assertFalse(gun_should_fire(0, False, 40.0, 230.0, 0.02, True, True))
        self.assertFalse(gun_should_fire(12, False, 40.0, 230.0, 0.02, True, False))
        self.assertTrue(lightning_should_fire(20, 0.05, 30, 45, 50, 3, 25, True, True))
        self.assertFalse(lightning_should_fire(20, 0.05, 30, 45, 10, 3, 25, True, True))
        self.assertFalse(mortar_should_fire(12, 7, False, True, True, 12))
        self.assertTrue(mortar_should_fire(120, 7, False, True, True, 120))
        self.assertTrue(laser_hold(0.0, 0.75, 0.15, 0.0, 0.1, True))
        self.assertFalse(laser_hold(0.7, 0.75, 0.15, 0.0, 0.02, True))

    def test_decide_fires_aligned_gun_and_holds_recover(self):
        muzzle = (0.0, 0.0, 7.0)
        pos = [40.0, 0.0, 0.0]
        com = 4.5
        aim = yaw_pitch(muzzle, (pos[0], pos[1], com))
        weapon = {"kind": "gun", "cooldown": 0.0, "ammo": 12, "reload": 0.0, "stats": {"damage": 45, "speed": 252, "range": 230, "mag": 12}}
        ctx = {
            "weapons": [weapon, None],
            "look": [0.0, 0.0],
            "actual_aim": aim,
            "target": {"pos": pos, "vel": [0, 0, 0], "com_z": com, "kind": "mech"},
            "muzzle": muzzle,
            "tube": (0.0, 0.0, 9.5),
            "feet": (0.0, 0.0, 0.0),
            "dist": 40.0,
            "los": True,
            "wants": {"gun": True, "laser": False, "mortar": False, "lightning": False},
            "turn_rate": 4.0,
            "min_pitch": -0.7,
            "max_pitch": 1.3,
            "energy": 100.0,
            "lightning_reserve": 25.0,
            "mortar_gravity": 22.0,
        }
        _aim, fire, _reload = decide(ctx)
        self.assertEqual(fire, [True, False])
        ctx["wants"] = {"gun": False, "laser": False, "mortar": False, "lightning": False}
        _aim, fire, reload = decide(ctx)
        self.assertEqual(fire, [False, False])
        self.assertFalse(reload)

    def test_astar_routes_around_a_wall(self):
        w = h = 12
        block = bytearray(w * h)
        for j in range(2, 10):
            block[j * w + 5] = 1
        grid = NavGrid(0.0, 0.0, w, h, 8.0, block, array("f", [0.0]) * (w * h))
        path = grid.astar((8.0, 44.0), (84.0, 44.0), limit=400)
        self.assertGreater(len(path), 2)
        self.assertGreater(path[-1][0], 70.0)
        self.assertTrue(min(p[1] for p in path) < 20.0 or max(p[1] for p in path) > 75.0)

    def test_slide_turns_off_a_blocked_cell(self):
        block = bytearray(9)
        block[1] = 1  # cell (1, 0), the cell to the east
        grid = NavGrid(0.0, 0.0, 3, 3, 8.0, block, array("f", [0.0]) * 9)
        move = grid.slide(4.0, 4.0, 10.0, 0.0)
        self.assertGreater(move[1], 0.3)

    def test_return_fire_policy(self):
        self.assertTrue(allow_return_fire(100.0, True, 0.35, 230.0, True, True))
        self.assertTrue(allow_return_fire(100.0, True, 0.36, 230.0, True, True))
        self.assertFalse(allow_return_fire(100.0, True, 0.34, 230.0, True, True))
        self.assertFalse(allow_return_fire(100.0, False, 0.8, 230.0, True, True))
        self.assertFalse(allow_return_fire(100.0, True, 0.8, 230.0, False, True))
        self.assertFalse(allow_return_fire(100.0, True, 0.8, 230.0, True, False))
        self.assertFalse(allow_return_fire(230.0, True, 0.8, 230.0, True, True))
        self.assertTrue(allow_return_fire(229.0, True, 0.8, 230.0, True, True))
        quiet = wants_for(RECOVER, 100.0, True, 0.36)
        self.assertFalse(quiet["gun"])
        answered = wants_for(RECOVER, 100.0, True, 0.36, gun_range=230.0, aim_aligned=True, los=True)
        self.assertTrue(answered["gun"])
        self.assertFalse(answered["laser"])
        self.assertFalse(answered["mortar"])
        self.assertFalse(answered["lightning"])

    def test_return_fire_while_hurt(self):
        """An isolated mech inside gun range is answered at HP 0.36, and not at 0.34.

        The state stays RECOVER. This is not a chase and not a match.
        """
        fired, label = _hurt_reply(0.36, (100.0, 0.0, 0.0), aim_on=True)
        self.assertTrue(label.startswith("RECOVER"), label)
        self.assertTrue(fired[0])
        self.assertFalse(fired[1])
        quiet, low_label = _hurt_reply(0.34, (100.0, 0.0, 0.0), aim_on=True)
        self.assertTrue(low_label.startswith("RECOVER"), low_label)
        self.assertFalse(quiet[0])
        off_aim, _label = _hurt_reply(0.36, (100.0, 0.0, 0.0), aim_on=False)
        self.assertFalse(off_aim[0])
        too_far, _label = _hurt_reply(0.50, (250.0, 0.0, 0.0), aim_on=True)
        self.assertFalse(too_far[0])
        crowded, _label = _hurt_reply(0.50, (100.0, 0.0, 0.0), aim_on=True, extra=(120.0, 25.0, 0.0))
        self.assertFalse(crowded[0])

    def test_isolated_mech_in_range_is_a_fight(self):
        """A healthy bot inside the next circle takes an isolated fight. It does not need the squad to ignore each other."""
        msgs = _stream()
        hello = msgs[0]
        hello["map"]["dir"] = os.path.join(ROOT, "arena")
        brain = Brain(hello)
        brain.solids = None
        brain.grid = None
        obs = copy.deepcopy(next(m for m in msgs if m.get("type") == "obs"))
        obs["t"] = 0.0
        me = obs["self"]
        me["pos"] = [0.0, 0.0, 0.0]
        me["vel"] = [0.0, 0.0, 0.0]
        me["hp"] = me["max_hp"] = 1400
        me["energy"] = 100
        me["in_zone"] = True
        me["aim"] = [0.0, 0.0]
        obs["mechs"] = [{
            "id": 4, "kind": "mech", "pos": [30.0, 0.0, 0.0], "vel": [0.0, 0.0, 0.0],
            "aim": [math.pi, 0.0], "hp": 1400, "max_hp": 1400, "weapons": ["gun"], "charging": False,
        }]
        for key in ("projectiles", "sounds", "events", "beams", "pickups", "cubes", "crates", "drops"):
            obs[key] = []
        obs["offer"] = None
        obs["zone"] = {
            "center": [0.0, 0.0], "radius": 500.0, "next_center": [0.0, 0.0], "next_radius": 400.0,
            "shrink_start": 200.0, "shrink_end": 250.0, "dps": 20.0,
        }
        import mechfight as mf
        mf.draw.clear()
        action = brain.act(obs)
        self.assertTrue(mf.draw._d.get("label", "").startswith("ENGAGE"), mf.draw._d.get("label"))
        self.assertAlmostEqual(action["aim"][0], 0.0, places=2)
        self.assertLessEqual(math.hypot(*action["move"]), 1.0)

    def test_stuck_recovery_triggers_jump_and_replan(self):
        pilot = Pilot()
        pilot.note_motion(0.0, 0.0, 0.0, True)
        pilot.note_motion(0.4, 0.0, 1.1, True)
        self.assertTrue(pilot.stuck)
        self.assertTrue(pilot.should_jump(1.15))
        self.assertTrue(pilot.dirty)
        self.assertTrue(pilot.unsticking(1.5))
        self.assertFalse(pilot.unsticking(3.0))


class ProtocolTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        msgs = _stream()
        cls.hello = msgs[0]
        cls.obs = [m for m in msgs if m.get("type") == "obs"]
        cls.hello["map"]["dir"] = os.path.join(ROOT, "arena")
        cls.brain = Brain(cls.hello)

    def test_action_is_valid_json_and_echoes_tick(self):
        for obs in (self.obs[0], self.obs[len(self.obs) // 2], self.obs[-1]):
            action = self.brain.act(copy.deepcopy(obs))
            raw = json.dumps(action)
            parsed = json.loads(raw)
            self.assertEqual(parsed["tick"], obs["tick"])
            self.assertEqual(len(parsed["move"]), 2)
            self.assertLessEqual(math.hypot(*parsed["move"]), 1.0001)
            self.assertEqual(len(parsed["fire"]), 2)
            self.assertTrue(all(isinstance(flag, bool) for flag in parsed["fire"]))
            self.assertEqual(len(parsed["aim"]), 2)
            self.assertTrue(all(math.isfinite(v) for v in parsed["aim"]))

    def test_missing_optional_fields(self):
        obs = copy.deepcopy(self.obs[10])
        for key in ("drops", "beams", "offer", "sounds", "events", "projectiles", "crates", "cubes", "pickups"):
            obs.pop(key, None)
        obs["offer"] = None
        for actor in obs.get("mechs") or []:
            for key in ("hp", "max_hp", "cubes", "weapons", "charging"):
                actor.pop(key, None)
        me = obs["self"]
        me.pop("stats", None)
        me.pop("upgrades", None)
        me.pop("grounded", None)
        if me.get("weapons"):
            me["weapons"][0].pop("stats", None)
            me["weapons"][0].pop("ammo", None)
        action = self.brain.act(obs)
        self.assertEqual(action["tick"], obs["tick"])
        json.dumps(action)

    def test_decision_latency(self):
        # Warm the caches, then time decisions. Replans are included; they must stay inside the budget.
        self.brain.act(copy.deepcopy(self.obs[0]))
        samples = []
        for obs in self.obs[1:61]:
            t0 = time.perf_counter()
            action = self.brain.act(copy.deepcopy(obs))
            samples.append((time.perf_counter() - t0) * 1000.0)
            self.assertEqual(action["tick"], obs["tick"])
        samples.sort()
        p50 = samples[len(samples) // 2]
        p99 = samples[min(len(samples) - 1, int(len(samples) * 0.99))]
        print(f"\nlatency ms p50 {p50:.2f} p99 {p99:.2f} max {samples[-1]:.2f}")
        self.assertLess(p99, 30.0)
        self.assertLess(samples[-1], 45.0)

    def test_startup_and_shutdown(self):
        # The official wrapper returns as soon as it sees `end`, so the messages
        # have to arrive as a match does: hello, then obs, then end.
        hello = copy.deepcopy(self.hello)
        hello["map"]["dir"] = os.path.join(ROOT, "arena")
        obs = copy.deepcopy(self.obs[0])
        proc = subprocess.Popen(
            [sys.executable, "-u", os.path.join(ROOT, "bot.py")],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ROOT,
        )
        try:
            ready = _exchange(proc, hello, 10.0)
            action = _exchange(proc, obs, 5.0)
            proc.stdin.write((json.dumps({"type": "end", "place": 8, "kills": 0}) + "\n").encode())
            proc.stdin.close()
            code = proc.wait(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
        err = proc.stderr.read().decode()
        self.assertEqual(code, 0, err[-500:])
        self.assertEqual(ready.get("type"), "ready")
        self.assertEqual(ready.get("name"), "phantom")
        self.assertEqual(action.get("tick"), obs["tick"])
        self.assertNotIn("\n", json.dumps(ready))


class _OpenSight:
    def blocks_segment(self, *_args, **_kwargs):
        return False


def _hurt_reply(hp_frac: float, enemy_xy, aim_on: bool, extra=None):
    """One decision against a stationary mech. Sight is forced clear so the map cannot hide them."""
    import mechfight as mf
    from combat.aim import yaw_pitch

    msgs = _stream()
    hello = msgs[0]
    hello["map"]["dir"] = os.path.join(ROOT, "arena")
    brain = Brain(hello)
    brain.grid = None
    brain.solids = _OpenSight()
    obs = copy.deepcopy(next(m for m in msgs if m.get("type") == "obs"))
    obs["t"] = 1.0
    me = obs["self"]
    me["pos"] = [0.0, 0.0, 0.0]
    me["vel"] = [0.0, 0.0, 0.0]
    me["max_hp"] = 1400.0
    me["hp"] = 1400.0 * hp_frac
    me["energy"] = 80.0
    me["in_zone"] = True
    me["stats"] = {"muzzle_height": 7.0, "height": 9.0, "turn_rate": 4.0, "min_pitch": -0.7, "max_pitch": 1.3}
    me["weapons"] = [{
        "kind": "gun",
        "cooldown": 0.0,
        "ammo": 12,
        "reload": 0.0,
        "stats": {"damage": 45, "cooldown": 0.24, "speed": 252, "range": 230, "mag": 12, "reload": 2.4},
    }, None]
    aimed = yaw_pitch((0.0, 0.0, 7.0), (enemy_xy[0], enemy_xy[1], 4.5))
    me["aim"] = list(aimed) if aim_on else [math.pi, 0.0]
    obs["mechs"] = [{
        "id": 4, "kind": "mech", "pos": [enemy_xy[0], enemy_xy[1], 0.0], "vel": [0.0, 0.0, 0.0],
        "aim": [math.pi, 0.0], "hp": 1400, "max_hp": 1400, "weapons": ["gun"], "charging": False,
    }]
    if extra is not None:
        obs["mechs"].append({
            "id": 5, "kind": "mech", "pos": [extra[0], extra[1], extra[2]], "vel": [0.0, 0.0, 0.0],
            "aim": [0.0, 0.0], "hp": 1400, "max_hp": 1400, "weapons": ["gun"], "charging": False,
        })
    for key in ("projectiles", "sounds", "events", "beams", "pickups", "cubes", "crates", "drops"):
        obs[key] = []
    obs["offer"] = None
    obs["alive"] = 16
    obs["zone"] = {
        "center": [0.0, 0.0], "radius": 500.0, "next_center": [0.0, 0.0], "next_radius": 400.0,
        "shrink_start": 200.0, "shrink_end": 250.0, "dps": 20.0,
    }
    mf.draw.clear()
    action = brain.act(obs)
    return action["fire"], mf.draw._d.get("label", "")


def _exchange(proc: subprocess.Popen, msg: dict, timeout: float) -> dict:
    proc.stdin.write((json.dumps(msg) + "\n").encode())
    proc.stdin.flush()
    fd = proc.stdout.fileno()
    os.set_blocking(fd, False)
    data = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            time.sleep(0.01)
            continue
        if chunk == b"":
            break
        data += chunk
        if b"\n" in data:
            line, _rest = data.split(b"\n", 1)
            return json.loads(line)
    err = proc.stderr.read().decode() if proc.stderr else ""
    raise AssertionError(f"no reply for {msg.get('type')} ({data!r}) stderr {err[-400:]}")


def _miss(muzzle, aim, speed, tof, pos, vel):
    yaw, pitch = aim
    bullet = (
        muzzle[0] + math.cos(pitch) * math.cos(yaw) * speed * tof,
        muzzle[1] + math.cos(pitch) * math.sin(yaw) * speed * tof,
        muzzle[2] + math.sin(pitch) * speed * tof,
    )
    actual = (pos[0] + vel[0] * tof, pos[1] + vel[1] * tof, pos[2] + vel[2] * tof)
    return math.dist(bullet, actual)


if __name__ == "__main__":
    unittest.main()
