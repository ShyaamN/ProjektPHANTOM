# STATUS

Updated: 2026-11-22 (UTC)

## Working features

- Official `mechfight.py` wrapper, unchanged. Entrypoint `bot.py`. Stdlib only.
- `hello` loads the arena once (about 33 ms here) into an 8 m walk grid. Paths are cached and replanned on a timer, on a new goal, or when stuck. Not every tick.
- States: SURVIVE, ROTATE, LOOT, REPOSITION, ESCAPE, ENGAGE, RECOVER, ENDGAME. Zone entry outranks a fight. Silence is the default; shots reset regen and carry hundreds of meters.
- Return fire: at HP of at least 0.35, an isolated attacker inside the live gun range, with line of sight and the torso already on them, gets the gun only. Laser, mortar, and lightning stay off. Below 0.35 the bot keeps running.
- Gun lead, mortar pitch, laser charge/release, lightning cone and energy reserve. Numbers come from `hello.config` and the live weapon `stats`.
- Upgrade utility prefers armor, plating, and regen. Second weapon priority is laser, then mortar, then lightning. The gun stays in slot 0.
- Stuck recovery: if commanded movement does not change position for 1 s, jump, sidestep, and replan.

## Latest verified score

none yet

The kit has no simulator. `check/check.py` is a conformance replay, not a match. No hosted practice match has been submitted from this environment.

## Known bugs

- Buildings are blocked volumes. The bot does not path onto roofs.
- An 8 m cell can close an alley narrower than the cell. The server still slides the mech along walls.
- Docker is not available in this environment, so the match sandbox (`--network none --cpus 1 --memory 512m --read-only`) was not run. One-core latency was measured with `taskset -c 0`.
- No live match has confirmed that the torso slew lines up shots before the engage window expires.

## Test results

Official example bot, `python3 check/check.py -- python3 -u python/example_bot.py`:

```
ready in 30 ms: name 'example-py'
observations: 300  answered in time: 300  missed the 50 ms budget: 0 (0 came late)
answer time ms: p50 0.2  p90 0.3  p99 0.8  max 0.8
PASS
```

This bot, `python3 check/check.py -- python3 -u bot.py`:

```
ready in 55 ms: name 'phantom'
observations: 300  answered in time: 300  missed the 50 ms budget: 0 (0 came late)
answer time ms: p50 0.3  p90 0.7  p99 2.6  max 2.8  (this machine, not the 1-CPU match container)
answers to older queued observations (dropped): 0  wrong tick: 0  bad lines: 0  debug drawings: 300 (0 over the caps)
PASS
```

`python3 -m unittest discover -s tests`: 24 tests, OK. A healthy bot inside the next circle, facing one mech at 30 m, enters ENGAGE. A hurt bot (HP 0.36) in RECOVER returns gun fire at an isolated mech at 100 m when the aim is on them, and does not fire at HP 0.34, off aim, past gun range, or when a second mech is nearby.

Decision latency inside the suite (60 observations, caches warm): p50 0.06 ms, p99 2.23 ms, max 2.23 ms.

`taskset -c 0 python3 evaluation/bench.py` (300 observations, 1 core):

```
init_ms 32.3
n 300 p50 0.04 p90 0.40 p99 2.18 max 2.22
```

All of those are wall times on this machine. They are not match scores.

## Next three priorities

1. Push the public GitHub repo and submit it on the Mech Royale track. This environment has no `gh` auth and no Docker.
2. Read the hosted practice replay and tune the engage/heal thresholds from real deaths. Do not tune only against the house squad.
3. Add roof routing where a prism top is a walkable surface and the jet can reach it. Late circles reward height.

## Git commit SHA

Return fire: `2f6ed83e8c058128d3eaa9acc09335bd7da2038d` on `cursor/phantom-survival-bot-bc75`.

Push the tip of that branch. Nothing on it has a hosted score. Nothing has been submitted. GitHub auth is still blocked, so there is no remote.
