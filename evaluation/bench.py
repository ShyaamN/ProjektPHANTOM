"""Time decisions on the recorded conformance stream.

This is a latency benchmark, not a match. Observations do not react to actions,
and the kit ships no simulator. Run it pinned to one core:

    taskset -c 0 python3 evaluation/bench.py
"""
from __future__ import annotations

import gzip
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import mechfight as mf  # noqa: E402
from strategy.brain import Brain  # noqa: E402


def main() -> None:
    path = os.path.join(ROOT, "check", "stream.jsonl.gz")
    with gzip.open(path, "rt") as handle:
        msgs = [json.loads(line) for line in handle if line.strip()]
    hello = msgs[0]
    hello["map"]["dir"] = os.path.join(ROOT, "arena")
    obs = [m for m in msgs if m.get("type") == "obs"]
    t0 = time.perf_counter()
    brain = Brain(hello)
    init_ms = (time.perf_counter() - t0) * 1000.0
    samples = []
    fires = 0
    for item in obs:
        mf.draw.clear()
        t1 = time.perf_counter()
        action = brain.act(item)
        samples.append((time.perf_counter() - t1) * 1000.0)
        if any(action.get("fire") or [False, False]):
            fires += 1
        if action.get("tick") != item["tick"]:
            raise SystemExit(f"tick mismatch {action.get('tick')} != {item['tick']}")
    samples.sort()

    def pct(p: float) -> float:
        return samples[min(len(samples) - 1, int(p * len(samples)))]

    print(f"init_ms {init_ms:.1f}")
    print(f"n {len(samples)} p50 {pct(0.50):.2f} p90 {pct(0.90):.2f} p99 {pct(0.99):.2f} max {samples[-1]:.2f}")
    print(f"decisions_with_fire {fires}")


if __name__ == "__main__":
    main()
