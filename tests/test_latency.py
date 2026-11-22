"""Decision time on the recorded match stream. The budget is 50 ms."""
from __future__ import annotations

import copy
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from combat.pilot import CombatBot
from tests.support import ROOT, load_stream


class LatencyTest(unittest.TestCase):
    def test_act_stays_inside_the_tick_budget_with_the_real_map(self):
        stream = load_stream()
        hello = copy.deepcopy(stream[0])
        hello["map"]["dir"] = os.path.join(ROOT, "arena")
        observations = [msg for msg in stream if msg.get("type") == "obs"]
        started = time.perf_counter()
        bot = CombatBot(hello)
        init_ms = (time.perf_counter() - started) * 1000.0
        self.assertLess(init_ms, 5000.0, f"map load took {init_ms:.0f} ms")

        bot.act(observations[0])  # warmup, not counted
        samples = []
        for obs in observations[1:]:
            t0 = time.perf_counter()
            action = bot.act(obs)
            samples.append((time.perf_counter() - t0) * 1000.0)
            self.assertEqual(action["tick"], obs["tick"])
        samples.sort()
        p50 = samples[len(samples) // 2]
        p95 = samples[int(len(samples) * 0.95)]
        p99 = samples[int(len(samples) * 0.99)]
        worst = samples[-1]
        # Printed for the run log. The assertion is the budget.
        print(f"\nact ms: init {init_ms:.1f}  p50 {p50:.2f}  p95 {p95:.2f}  p99 {p99:.2f}  max {worst:.2f}")
        self.assertLess(p99, 20.0, f"p99 {p99:.2f} ms")
        self.assertLess(worst, 45.0, f"max {worst:.2f} ms")


if __name__ == "__main__":
    unittest.main()
