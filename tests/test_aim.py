"""Aim prediction: gun lead, laser release, mortar ballistics, lightning cone."""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from combat.aim import (
    beam_dodge,
    gun_hit_probability,
    gun_solution,
    laser_aim,
    laser_charge_fraction,
    laser_hit_probability,
    lightning_pick,
    mortar_angles,
    mortar_solution,
    simulate_ballistic,
    yaw_in_cone,
)


class GunLeadTest(unittest.TestCase):
    def test_stationary_target_due_east(self):
        sol = gun_solution((0.0, 0.0, 7.0), (252.0, 0.0, 7.0), (0.0, 0.0, 0.0), 252.0, 0.0, 400.0)
        self.assertAlmostEqual(sol["t"], 1.0, places=4)
        self.assertAlmostEqual(sol["yaw"], 0.0, places=4)
        self.assertAlmostEqual(sol["pitch"], 0.0, places=4)
        self.assertTrue(sol["reachable"])

    def test_crossing_target_is_led(self):
        # Target is due north and walking east. The aim point has to be east
        # of where they are now, and the bullet flight has to match that point.
        muzzle = (0.0, 0.0, 0.0)
        sol = gun_solution(muzzle, (0.0, 100.0, 0.0), (20.0, 0.0, 0.0), 252.0, 0.0, 300.0)
        self.assertGreater(sol["point"][0], 1.0)
        self.assertAlmostEqual(sol["point"][1], 100.0, places=4)
        self.assertLess(sol["yaw"], math.atan2(100.0, 0.0))
        dist = math.dist(muzzle, sol["point"])
        self.assertAlmostEqual(dist, 252.0 * sol["t"], places=3)

    def test_standoff_shortens_flight(self):
        sol = gun_solution((0.0, 0.0, 0.0), (0.0, 100.0, 0.0), (20.0, 0.0, 0.0), 200.0, 3.0, 300.0)
        dist = math.dist((0.0, 0.0, 0.0), sol["point"])
        self.assertAlmostEqual(dist, 3.0 + 200.0 * sol["t"], delta=0.05)
        self.assertLess(sol["t"], 100.0 / 200.0)

    def test_beyond_range_is_not_reachable(self):
        sol = gun_solution((0.0, 0.0, 0.0), (500.0, 0.0, 0.0), (0.0, 0.0, 0.0), 252.0, 0.0, 230.0)
        self.assertFalse(sol["reachable"])
        self.assertEqual(gun_hit_probability(500.0, 2.0, 0.6, 2.5, 0.0, 230.0), 0.0)

    def test_hit_probability_shrinks_with_range_and_speed(self):
        close = gun_hit_probability(12.0, 12.0 / 252.0, 0.6, 2.5, 0.0, 230.0)
        far = gun_hit_probability(180.0, 180.0 / 252.0, 0.6, 2.5, 0.0, 230.0)
        moving = gun_hit_probability(80.0, 0.6, 0.6, 2.5, 16.0, 230.0)
        still = gun_hit_probability(80.0, 0.6, 0.6, 2.5, 0.0, 230.0)
        self.assertGreater(close, 0.9)
        self.assertGreater(far, 0.0)
        self.assertLess(far, close)
        self.assertLess(moving, still)


class LaserTest(unittest.TestCase):
    def test_release_lead(self):
        yaw, pitch, point, dist = laser_aim((0.0, 0.0, 8.0), (10.0, 0.0, 8.0), (4.0, 0.0, 0.0), 0.5)
        self.assertAlmostEqual(point[0], 12.0, places=6)
        self.assertAlmostEqual(point[1], 0.0, places=6)
        self.assertAlmostEqual(yaw, 0.0, places=6)
        self.assertAlmostEqual(pitch, 0.0, places=6)
        self.assertAlmostEqual(dist, 12.0, places=6)

    def test_zero_release_aims_at_the_present(self):
        _yaw, _pitch, point, _dist = laser_aim((0.0, 0.0, 0.0), (5.0, 5.0, 1.0), (9.0, 0.0, 0.0), 0.0)
        self.assertEqual(point, (5.0, 5.0, 1.0))

    def test_charge_fraction_ramps_from_min_to_full(self):
        self.assertAlmostEqual(laser_charge_fraction(0.0, 0.75, 0.35), 0.35)
        self.assertAlmostEqual(laser_charge_fraction(0.75, 0.75, 0.35), 1.0)
        mid = laser_charge_fraction(0.375, 0.75, 0.35)
        self.assertAlmostEqual(mid, 0.35 + 0.65 * 0.5)

    def test_long_telegraph_is_easier_to_dodge(self):
        snap = laser_hit_probability(40.0, 0.05, 12.0, 2.5, 280.0)
        held = laser_hit_probability(40.0, 0.75, 12.0, 2.5, 280.0)
        self.assertGreater(snap, held)
        self.assertEqual(laser_hit_probability(400.0, 0.0, 0.0, 2.5, 280.0), 0.0)


class MortarTest(unittest.TestCase):
    def test_flat_ground_low_arc_lands(self):
        speed, gravity = 72.0, 22.0
        angles = mortar_angles(100.0, 0.0, speed, gravity)
        self.assertGreaterEqual(len(angles), 2)
        low, high = angles[0], angles[1]
        self.assertLess(low[0], high[0])
        self.assertLess(low[0], math.radians(45.0))
        self.assertGreater(high[0], math.radians(45.0))
        impact = simulate_ballistic((0.0, 0.0, 0.0), 0.0, low[0], speed, gravity, low[1])
        self.assertAlmostEqual(impact[0], 100.0, delta=0.05)
        self.assertAlmostEqual(impact[1], 0.0, delta=0.05)
        self.assertAlmostEqual(impact[2], 0.0, delta=0.05)

    def test_moving_target_is_where_the_shell_arrives(self):
        muzzle = (0.0, 0.0, 9.5)
        pos = (80.0, 10.0, 0.0)
        vel = (6.0, -2.0, 0.0)
        sol = mortar_solution(muzzle, pos, vel, 72.0, 22.0, -0.7, 1.3, 7.0, False)
        self.assertIsNotNone(sol)
        impact = simulate_ballistic(muzzle, sol["yaw"], sol["pitch"], 72.0, 22.0, sol["t"])
        self.assertAlmostEqual(impact[0], sol["point"][0], delta=1.0)
        self.assertAlmostEqual(impact[1], sol["point"][1], delta=1.0)
        self.assertAlmostEqual(impact[2], sol["point"][2], delta=1.0)
        # The lead is the target's own motion over the flight.
        self.assertAlmostEqual(sol["point"][0], pos[0] + vel[0] * sol["t"], delta=0.5)
        self.assertAlmostEqual(sol["point"][1], pos[1] + vel[1] * sol["t"], delta=0.5)

    def test_out_of_range_has_no_arc(self):
        # v^2/g ≈ 235 m on flat ground. 400 m cannot be reached.
        self.assertEqual(mortar_angles(400.0, 0.0, 72.0, 22.0), [])
        sol = mortar_solution((0, 0, 0), (400, 0, 0), (0, 0, 0), 72.0, 22.0, -0.7, 1.3, 7.0)
        self.assertIsNone(sol)


class BeamDodgeTest(unittest.TestCase):
    def test_steps_off_a_beam_that_just_passed(self):
        # Beam runs east along y=0. We are just north of it, so the dodge is north.
        beams = [{"kind": "laser", "age": 0.1, "path": [[-10.0, 0.0, 5.0], [10.0, 0.0, 5.0]]}]
        dodge = beam_dodge(0.0, 2.0, beams, radius=7.0)
        self.assertIsNotNone(dodge)
        self.assertGreater(dodge[1], 0.5)
        self.assertAlmostEqual(dodge[0], 0.0, places=4)

    def test_old_or_distant_beams_are_ignored(self):
        old = [{"kind": "laser", "age": 0.9, "path": [[-10.0, 0.0, 5.0], [10.0, 0.0, 5.0]]}]
        far = [{"kind": "lightning", "age": 0.1, "path": [[-10.0, 30.0, 5.0], [10.0, 30.0, 5.0]]}]
        self.assertIsNone(beam_dodge(0.0, 0.0, old))
        self.assertIsNone(beam_dodge(0.0, 0.0, far))


class LightningTest(unittest.TestCase):
    def test_yaw_points_at_the_target(self):
        # Cone membership uses yaw only. The nearest body inside the cone wins,
        # which is the protocol's "nearest target within range and cone".
        targets = [
            {"id": 1, "x": 40.0, "y": 0.0, "dist": 40.0},
            {"id": 2, "x": 20.0, "y": 1.0, "dist": math.hypot(20.0, 1.0)},
        ]
        got = lightning_pick(0.0, (0.0, 0.0), targets, 45.0, 30.0)
        self.assertEqual(got["id"], 2)

    def test_outside_cone_or_range_is_ignored(self):
        self.assertTrue(yaw_in_cone(0.0, math.radians(20.0), 30.0))
        self.assertFalse(yaw_in_cone(0.0, math.radians(40.0), 30.0))
        targets = [
            {"id": 1, "x": 10.0, "y": 0.0, "dist": 10.0},
            {"id": 2, "x": 30.0, "y": 30.0, "dist": math.hypot(30.0, 30.0)},
        ]
        # id 2 is 45° off and also near the range edge. Aim due east hits id 1.
        got = lightning_pick(0.0, (0.0, 0.0), targets, 45.0, 30.0)
        self.assertEqual(got["id"], 1)
        far = [{"id": 9, "x": 80.0, "y": 0.0, "dist": 80.0}]
        self.assertIsNone(lightning_pick(0.0, (0.0, 0.0), far, 45.0, 30.0))


if __name__ == "__main__":
    unittest.main()
