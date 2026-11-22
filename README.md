# phantom-duelist

Combat-first bot for the Builders Buildathon Mech Royale track (`mechfight/1`).

The score is `16 - finish place`. Dying first is zero, so this bot does not suicide for a kill. It takes a fight when the time-to-kill is favorable, strafes an even trade, and leaves when the exchange is losing, when two mechs are already aimed at it, or when the zone would kill it during a long fight. Every opponent is treated as a free-for-all threat, including one that is not shooting yet.

Aim is weapon-specific:

- **Gun** — constant-velocity lead. Bullet speed is world-frame speed along the aim (shooter velocity is not added). The 3 m shot standoff is in the intercept.
- **Laser** — hitscan at release, so the lead is only the target's motion during the remaining charge. Hold to charge, release when the torso is on the lead point. A close lightning user keeps the laser uncharged (short).
- **Mortar** — closed-form low arc, iterated so the shell meets a moving target. It will not fire into its own splash.
- **Lightning** — instant and yaw-gated. It fires only when the current aim is inside a tight slice of the cone and the wanted target is the nearest body in that cone.

`mechfight.py`, `check/`, `mechfight.schema.json`, `protocol.md`, and `arena/` are the official kit. `bot.py` and `combat/` are original.

There is no match simulator in the kit. `check/check.py` replays a recorded observation stream and checks the protocol. It does not produce a placement score.

```sh
python3 -m unittest discover -s tests -v
python3 check/check.py -- python3 -u bot.py
```

The image is the kit's Python layout: Dockerfile at the repository root, standard library only, nothing on stdout except protocol lines.

```sh
docker build -t phantom-duelist .
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" phantom-duelist
```

Do not submit this repository to the hosted leaderboard from an automated run. The track's attempt quota is shared.
