# EXPERIMENTS

Scores below are measurements from this machine. A conformance replay is not a match. The starter kit has no simulator. Practice score: none yet.

Leaderboard read from https://www.joinbuilders.org/buildathon/leaderboard on 2026-11-22 about 05:17 UTC. Mech Royale, scorer `builders-3`, 355 teams, baseline 1.15, cutoff 2026-11-22 16:00 UTC. Top of the embedded standings: 6.58 (2696, 2026-11-22T02:42:28Z), 6.48 (ImagineLosing), 6.46 (azing), 6.44 (tigerbyte), 6.42 (Farmers). The page copy still says 4 submissions an hour. The live board metadata said `practice_limit` 6 after the quota increase. Top 50 in that payload bottomed at 5.96.

## E0 — official example

Hypothesis: the kit example satisfies `check/check.py`.

Result: PASS. ready 30 ms, 300/300 in time, p50 0.2 ms, p99 0.8 ms, max 0.8 ms, 0 bad lines. Kept the example as a reference only. It is not our bot.

## E1 — survival bot, first tree

Hypothesis: an original survival policy can pass the protocol with decision time far under 50 ms.

Result: PASS. ready 54 ms, 300/300, p50 0.3 ms, p90 0.8 ms, p99 2.6 ms, max 2.8 ms. Unit tests 21/21. One-core bench (`taskset -c 0`): init 32.3 ms, p50 0.04 ms, p99 2.18 ms, max 2.22 ms. Map build 134x91, 3001 blocked cells, about 33 ms. Kept.

On the recorded stream the example's mech is nearly dead (9.5 HP at t=36.8). Our decisions there were SURVIVE 105, ESCAPE 54, RECOVER 141, mean move length 1.0, 0 fires. Fires stay at 0 because enemies inside 80 m show up on 4 ticks and the policy does not shoot at 55 m while hurt. That is the recorded trace, not a placement.

## E2 — don't heal outside the next circle

Hypothesis: RECOVER was parking on local cover outside the next circle (62 ticks on the recorded stream). Entering earlier, and rejecting cover that sits outside the next circle, should drop that count to 0 without a latency regression.

Change: `must_rotate` lead time 18 s to 35 s. Cover goals are used only when they already lie inside the next circle.

Result, same 300 observations:

| | before | after |
| --- | --- | --- |
| goals outside the next circle | 62 | 0 |
| RECOVER / SURVIVE / ESCAPE / ROTATE | 141 / 105 / 54 / 0 | 98 / 103 / 50 / 49 |
| check.py | PASS, p99 1.9 ms | PASS, p99 2.6 ms, max 2.8 ms |

Kept. This is a decision trace on a dead replay. It is not a practice score.

## Not scored yet

These need a hosted match. The levers are in the code.

- A. Survival-first versus aggressive: `wants_for` and `can_engage`. Default is silence unless the fight is isolated or point-blank. Locked by `test_isolated_mech_in_range_is_a_fight`: full HP, one mech at 30 m, inside the next circle, state ENGAGE. Not a match score.
- B. Cover versus straight movement: `_cover` plus the walk grid. E2 is the only measured step.
- C. Predictive aim. Synthetic crossing target, muzzle at origin, target (80, 0, 0) moving (0, 20, 0), bullet speed 252. Lead miss 0.000 m. Direct aim miss 6.349 m. Lead is what the bot uses.
- D. Energy reserve. Boost is for leaving the zone, escaping, a long rotate above 44 energy, or a very long walk above 78. Lightning keeps 25 energy.
- E. Upgrade order. Armor, plating, and nanites outrank weapon damage. Unit test: hurt mech picks `armor` over `sensors` and `gun_damage`.
- F. Hybrid versus the practice squad. The same rules run in a free-for-all. Nothing inspects bot identity or assumes enemies will not shoot each other.
