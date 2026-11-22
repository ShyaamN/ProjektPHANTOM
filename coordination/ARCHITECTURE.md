# ARCHITECTURE

`bot.py` calls `mf.run(Brain)`. `mechfight.py` is the official wrapper: it sends `ready`, answers only the newest observation, echoes `tick`, and logs tracebacks to stderr. stdout is protocol only.

## Tick

1. `ThreatBoard` records damage time, the last non-zone damage bearing, and a weighted circular mean of recent sounds.
2. Features: HP fraction, enemies sorted by distance, whether the nearest fight is isolated, line of sight through prisms, projectile dodge, zone timing, a nearby loot target.
3. `decide_state` picks one state. Order: ROTATE if outside the zone or the next circle must be entered, else ESCAPE, RECOVER, ENGAGE, ENDGAME, LOOT, REPOSITION, SURVIVE.
4. Movement. Fights strafe at a preferred range (farther if they hold lightning). Escape runs away from the nearest mech or the damage bearing, and back into the zone. Everything else follows a cached path, then a slide if the next cell is blocked.
5. Weapons. The state decides which triggers are allowed. Aim is solved from the live stats: gun lead, mortar ballistics, hitscan laser, lightning cone. The torso's actual aim has to be inside the gate or the trigger stays up. That saves ammo and, more importantly, does not reset the 5 s regen timer.
6. A pending offer is picked immediately. A weapon in pickup range is taken when the nearest mech is beyond 28 m and the bot is not engaging or escaping.

## Navigation

`navigation/map.py` reads `v2/world.json` and `v2/terrain.i16`. Prisms block the body unless the underside clears 9 m (walk under a bridge) or the top is within `step_up` (walk over a curb). Trees, cars, water, and barriers do not block movement or shots.

`navigation/grid.py` rasterizes that into 8 m cells (134 by 91 on this map, about 33 ms at hello). Edges steeper than 50 degrees and taller than `step_up` are not walked. A* is weighted and capped at 700 expansions. If the cap hits, the path still leads toward the closest reached cell. Replan when the goal changes, about every 2.5 s of match time, or when stuck.

## Combat

Shot origin is the muzzle (`stats.muzzle_height`, default 7 m). The mortar tube is `height + 0.5`. Pitch is clamped to `min_pitch` / `max_pitch`. Lightning will not fire if energy would fall through a 25 point reserve. A mortar is not fired inside its own splash, and it is reserved for blocked or long shots. The gun is the direct weapon.

## What this is not

There is no local match simulator. Nothing in `evaluation/` or `check/` produces a placement score.
