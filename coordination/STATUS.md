# phantom-duelist

Combat-first Mech Royale bot for ProjektPHANTOM. It takes a favorable fight and leaves a losing one. Placement is still the score (`16 - place`); dying first is zero. Opponents are treated as free-for-all threats, including ones that are not shooting yet.

## Features

- Gun lead with the shot standoff (`radius + 0.5`). Bullet speed is world-frame speed along the aim.
- Laser aim at the point where the target will be when the beam is released. Hold to charge, release on the lead. Do not start a charge into a lightning short.
- Mortar low arc, iterated so the shell meets a moving target. No fire into our own splash or a blocked arc.
- Lightning fires only when the current yaw is inside 12° and the wanted target is the nearest body in the cone.
- Commit / trade / disengage from time-to-kill, the recent damage exchange, focus fire, and the zone clock.
- A long-range gun fight closes instead of fleeing when we are healthy and their damage will not kill us before we arrive.
- Strafe, projectile dodge, and a step off a beam that just passed. Leave while facing the threat so the rear arc is not presented.
- Second weapon by the weapon triangle. Cubes and supply drops when they do not give up the fight.
- Upgrade pick prefers armor and the weapon in hand.
- The next zone circle is a hard margin. No chase outside it for a slow kill.

## Verified score

none yet

The kit has no match simulator. `check/check.py` replays a recorded stream and does not score placement. This bot was not submitted to the hosted leaderboard.

## check.py

Official example, run first:

```
ready in 27 ms: name 'example-py'
observations: 300  answered in time: 300  missed the 50 ms budget: 0
answer time ms: p50 0.2  p90 0.2  p99 0.6  max 0.7
PASS
```

This bot:

```
bot: python3 -u bot.py
ready in 30 ms: name 'phantom-duelist'
observations: 300  answered in time: 300  missed the 50 ms budget: 0 (0 came late)
answer time ms: p50 0.3  p90 0.4  p99 0.7  max 0.8  (this machine, not the 1-CPU match container)
answers to older queued observations (dropped): 0  wrong tick: 0  bad lines: 0  debug drawings: 300 (0 over the caps)
PASS
```

In-process `act()` on those 300 observations with `arena/` loaded: init 10.5 ms, p50 0.05 ms, p95 0.10 ms, p99 0.14 ms, max 0.16 ms.

Docker is not installed in this environment, so the read-only 1-CPU container re-check was not run. The Dockerfile is the official Python layout (stdlib only, `python3 -u`).

## Tests

38 unit tests, all passing.

- JSON: ready and action validate against `mechfight.schema.json`, finite numbers, move length ≤ 1, line under 64 KiB
- Tick echo on all 300 recorded observations, and the newest tick when two observations are written together
- Gun lead (stationary, crossing, standoff, beyond range) and hit probability
- Laser release lead and charge fraction
- Mortar ballistics, checked by simulating the shell
- Lightning cone and nearest-target pick
- Disengage: losing race, 2v1, final duel, zone, exchange deficit, long-range close
- Beam dodge and building / bridge line of sight
- Latency under the 50 ms budget

## Bugs

- Mortar aim starts at the tube and ignores the 3 m shot standoff (about 0.04 s).
- `cone_deg` is read as "within N degrees of aim yaw". The trigger uses 12° so a narrower cone still hits.
- If the map files are missing, line of sight is treated as clear.
- No measured placement score.

## Next three priorities

1. Correct laser-threat and lightning-cone numbers from a real match or a returned replay, not only from the formula.
2. Climb to roof loot. Pickups more than 8 m above the feet are ignored; jets and ledges are not planned.
3. Publish the repo and, when the shared hourly quota is free, one hosted practice submission. Not done in this run.

## SHA

3f57ae8cd6dd5446d61a277b64424855716604ad

That commit adds the bot. The tip of `main` is one commit later and only records this file. Submit the tip: it contains the bot and this status.

## Push

Blocked. `gh auth status` reports no GitHub login. There is no `GH_TOKEN` and no `gh` credential file. The Cursor GitHub connection can read the account ShyaamN and cannot create or push a repository from this environment. No URL is invented.
