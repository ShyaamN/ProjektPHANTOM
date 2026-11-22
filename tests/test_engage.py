"""Disengage when the exchange is losing. Stay when the race is ours."""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from combat.engage import (
    FightState,
    chase_allowed,
    desired_weapon,
    exchange_losing,
    fight_decision,
    pick_upgrade,
    press_from_range,
    should_disengage,
    sustained_gun_dps,
    swap_worth,
)
from combat.pilot import CombatBot
from tests.support import fresh_obs, hello_without_map, load_stream


def state(**overrides):
    base = dict(
        my_hp=1000.0,
        my_max=1400.0,
        enemy_hp=1000.0,
        my_dps=80.0,
        enemy_dps=40.0,
        enemies_on_me=1,
        in_zone=True,
        zone_dps=20.0,
        alive=10,
        exchange_losing=False,
    )
    base.update(overrides)
    return FightState(**base)


class DecisionTest(unittest.TestCase):
    def test_favorable_race_commits(self):
        # We die in 10s, they die in 3s.
        got = fight_decision(state(my_hp=1000, enemy_hp=300, my_dps=100, enemy_dps=100))
        self.assertEqual(got, "commit")
        self.assertFalse(should_disengage(state(my_hp=1000, enemy_hp=300, my_dps=100, enemy_dps=100)))

    def test_losing_race_while_hurt_disengages(self):
        # We die in 3s, they die in 10s, and we are already at half.
        got = fight_decision(state(my_hp=700, my_max=1400, enemy_hp=1000, my_dps=100, enemy_dps=233))
        self.assertEqual(got, "disengage")

    def test_two_mechs_aiming_at_us_is_a_leave(self):
        got = fight_decision(state(enemies_on_me=2, my_hp=1400, enemy_hp=1400, my_dps=80, enemy_dps=160))
        self.assertEqual(got, "disengage")

    def test_two_mechs_but_one_is_about_to_fall(self):
        # Their focus fire kills us in 2s. The weak mech dies in 0.4s.
        got = fight_decision(state(enemies_on_me=2, my_hp=800, enemy_hp=40, my_dps=100, enemy_dps=400))
        self.assertEqual(got, "commit")

    def test_final_duel_we_win_stays(self):
        got = fight_decision(state(alive=2, my_hp=600, enemy_hp=400, my_dps=80, enemy_dps=75))
        self.assertEqual(got, "commit")

    def test_final_duel_we_lose_and_are_low_leaves_to_regen(self):
        got = fight_decision(state(alive=2, my_hp=400, my_max=1400, enemy_hp=1200, my_dps=100, enemy_dps=133))
        self.assertEqual(got, "disengage")

    def test_free_shot_commits(self):
        got = fight_decision(state(enemy_dps=0.0, my_dps=50, in_zone=True, enemies_on_me=0))
        self.assertEqual(got, "commit")

    def test_long_fight_outside_the_zone_leaves(self):
        got = fight_decision(state(in_zone=False, zone_dps=100, my_hp=400, enemy_hp=800, my_dps=50, enemy_dps=20))
        self.assertEqual(got, "disengage")

    def test_short_fight_outside_the_zone_can_finish(self):
        got = fight_decision(state(in_zone=False, zone_dps=20, my_hp=1400, enemy_hp=100, my_dps=100, enemy_dps=20))
        self.assertEqual(got, "commit")

    def test_exchange_losing_overrides_an_even_model(self):
        self.assertTrue(exchange_losing(dealt=0, taken=200, hp_frac=0.5))
        self.assertFalse(exchange_losing(dealt=200, taken=100, hp_frac=0.5))
        self.assertFalse(exchange_losing(dealt=0, taken=30, hp_frac=0.2))
        got = fight_decision(state(
            my_hp=700, enemy_hp=700, my_dps=100, enemy_dps=100, exchange_losing=True,
        ))
        self.assertEqual(got, "disengage")

    def test_exchange_losing_still_finishes_a_one_second_kill(self):
        got = fight_decision(state(
            my_hp=900, enemy_hp=50, my_dps=100, enemy_dps=100, exchange_losing=True,
        ))
        self.assertEqual(got, "commit")

    def test_do_not_chase_a_slow_kill_out_of_the_next_circle(self):
        self.assertFalse(chase_allowed(90.0, False, 400.0, 80.0, 8.0))
        self.assertTrue(chase_allowed(30.0, False, 1400.0, 20.0, 1.0))
        self.assertTrue(chase_allowed(40.0, True, 1400.0, 20.0, 4.0))

    def test_weapon_triangle_and_upgrade_pick(self):
        self.assertEqual(desired_weapon({"gun"}, {}), "laser")
        self.assertEqual(desired_weapon({"gun"}, {"laser": 3}), "lightning")
        self.assertEqual(desired_weapon({"gun"}, {"lightning": 3}), "mortar")
        self.assertEqual(desired_weapon({"gun"}, {"mortar": 3}), "laser")
        self.assertFalse(swap_worth({"gun", "laser"}, {}, "lightning"))
        # Mortar is the counter to lightning, so two lightning mechs are not a reason to drop it.
        self.assertFalse(swap_worth({"gun", "mortar"}, {"lightning": 2}, "laser"))
        # Laser cooks mortar. Drop lightning for it when mortars are what we see.
        self.assertTrue(swap_worth({"gun", "lightning"}, {"mortar": 2}, "laser"))
        index = pick_upgrade([
            {"id": "jets"},
            {"id": "armor"},
            {"id": "reactor"},
        ])
        self.assertEqual(index, 1)

    def test_long_range_chip_is_a_close_not_a_flee(self):
        # Healthy, far, our gun barely connects, their damage is not lethal yet.
        got = press_from_range("disengage", 150.0, 55.0, 1200.0, 12.0, 40.0, 0.85, 1, True)
        self.assertEqual(got, "trade")
        # Already at the range we wanted, and still losing: leave.
        stay = press_from_range("disengage", 50.0, 55.0, 1200.0, 12.0, 40.0, 0.85, 1, True)
        self.assertEqual(stay, "disengage")
        # They kill us before we can walk in.
        doomed = press_from_range("disengage", 150.0, 55.0, 200.0, 12.0, 80.0, 0.7, 1, True)
        self.assertEqual(doomed, "disengage")
        # A commit is not rewritten.
        self.assertEqual(press_from_range("commit", 150.0, 55.0, 1400.0, 10.0, 10.0, 1.0, 0, True), "commit")

    def test_sustained_gun_dps_matches_the_magazine_cycle(self):
        # 45 dmg, 0.24s, 12 rounds, 2.4s reload, perfect accuracy.
        # cycle = 12*0.24+2.4 = 5.28s, shots per cycle = 12, dps = 12*45/5.28.
        got = sustained_gun_dps(45.0, 0.24, 12.0, 2.4, 1.0)
        self.assertAlmostEqual(got, 12.0 * 45.0 / 5.28, places=4)


class PilotDisengageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stream = load_stream()
        cls.hello = hello_without_map(cls.stream)

    def _bot(self):
        return CombatBot(self.hello)

    def _losing_obs(self):
        obs = fresh_obs(self.stream)
        me = obs["self"]
        me["pos"] = [0.0, 0.0, 0.0]
        me["vel"] = [0.0, 0.0, 0.0]
        me["aim"] = [0.0, 0.0]
        me["hp"] = 200.0
        me["max_hp"] = 1400.0
        me["energy"] = 80.0
        me["in_zone"] = True
        me["grounded"] = True
        me["cubes"] = 0
        gun = me["weapons"][0]
        me["weapons"] = [gun, None]
        obs["mechs"] = [{
            "id": 10,
            "kind": "mech",
            "pos": [24.0, 0.0, 0.0],
            "vel": [0.0, 0.0, 0.0],
            "aim": [math.pi, 0.0],
            "hp": 1400.0,
            "max_hp": 1400.0,
            "cubes": 0,
            "weapons": ["lightning", "gun"],
            "charging": False,
        }]
        obs["alive"] = 10
        obs["t"] = 12.0
        obs["tick"] = 240
        obs["zone"]["center"] = [-200.0, 0.0]
        obs["zone"]["next_center"] = [-200.0, 0.0]
        obs["zone"]["radius"] = 500.0
        obs["zone"]["next_radius"] = 400.0
        obs["zone"]["dps"] = 20.0
        return obs

    def test_losing_exchange_moves_away_and_echoes_tick(self):
        bot = self._bot()
        obs = self._losing_obs()
        action = bot.act(obs)
        self.assertEqual(action["tick"], 240)
        self.assertEqual(bot.last_plan["decision"], "disengage")
        self.assertEqual(bot.last_plan["mode"], "leave")
        self.assertLess(action["move"][0], -0.2)
        self.assertLessEqual(math.hypot(*action["move"]), 1.0 + 1e-9)

    def test_favorable_fight_is_taken(self):
        bot = self._bot()
        obs = self._losing_obs()
        me = obs["self"]
        me["hp"] = 1400.0
        me["aim"] = [0.0, 0.0]
        obs["mechs"][0]["hp"] = 80.0
        obs["mechs"][0]["weapons"] = ["gun"]
        obs["mechs"][0]["aim"] = [0.0, 0.0]  # facing away
        obs["mechs"][0]["pos"] = [40.0, 0.0, 0.0]
        action = bot.act(obs)
        self.assertIn(bot.last_plan["decision"], ("commit", "trade"))
        self.assertEqual(bot.last_plan["mode"], "fight")
        self.assertEqual(action["tick"], obs["tick"])
        self.assertTrue(action["fire"][0])
        self.assertFalse(action["fire"][1])


if __name__ == "__main__":
    unittest.main()
