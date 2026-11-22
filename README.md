# ProjektPHANTOM

Survival-first bot for the Builders Buildathon Mech Royale track (`mechfight/1`).

Placement is the score: `16 - place` (15 for a win, 0 for dying first). The bot
plays the same policy in practice and in the free-for-all: stay in the next
circle, break line of sight, heal, and shoot only when the fight is isolated
or point-blank. It does not assume the practice squad will refuse to shoot
each other.

## Run

```sh
python3 check/check.py -- python3 -u bot.py
python3 -m unittest discover -s tests -v
taskset -c 0 python3 evaluation/bench.py
```

`check/check.py` is the official conformance check. It replays a recorded
stream. Passing it says the protocol is valid. It is not a match result.

The starter kit has no local simulator. Practice scores come only from the
hosted leaderboard.

Match sandbox, from the kit README:

```sh
docker build -t phantom-bot .
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" phantom-bot
```

## Layout

`bot.py` is the entrypoint. `mechfight.py` is the official stdin/stdout wrapper,
unchanged. `strategy/` chooses a state, `navigation/` caches an 8 m walk grid
built once during `hello`, and `combat/` solves gun lead, mortar pitch, laser
charge, and the lightning cone. Weapon numbers are read from `hello.config`
and from each observation.

States: `SURVIVE`, `ROTATE`, `LOOT`, `REPOSITION`, `ESCAPE`, `ENGAGE`,
`RECOVER`, `ENDGAME`.

## Disclosure

- `mechfight.py`, `check/check.py`, `mechfight.schema.json`, `check/stream.jsonl.gz`,
  and `arena/` are from the official mechfight starter kit
  (https://www.joinbuilders.org/buildathon/tracks/builders/files/mechfight-kit.tar.gz).
- Bot logic under `bot.py`, `strategy/`, `navigation/`, `combat/`, `evaluation/`,
  and `tests/` is original team-authored code.
- Runtime dependencies: the Python standard library only. No third-party packages.
- License: MIT (`LICENSE`).

stdout is protocol only. Logs, if any, go to stderr. There is no network at
runtime. The repository is meant to stay under the 20 MB submission limit.
