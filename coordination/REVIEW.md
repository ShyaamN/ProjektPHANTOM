# REVIEW

## Protocol

- Wrapper is the kit file, byte-identical to `python/mechfight.py`.
- `check/check.py` and the schema are the kit files.
- Actions always include `tick`, a move of length at most 1, a two-bool `fire`, and a finite aim. Optional `pick`, `take`, `drop`, and `reload` are sent only when used.
- Missing observation fields are read with `.get`. A missing map logs to stderr and the bot still answers, steering without a grid.
- No prints on stdout. The one init line goes through `mf.log` to stderr.

## Design risks

- Placement, not kills, is the objective. The default is to not shoot. That can lose a finals duel to a bot that pokes for free. ENGAGE exists for an isolated target inside 125 m (70 m when hurt) with line of sight, and point-blank shots are allowed in ESCAPE. This has not been seen in a live match.
- Practice squads add hunters when you kill them. The policy does not special-case that. It simply refuses fights it does not think it can take. If hosted scores show we die without ever shooting back at the one early hunter, the next change is a narrower self-defense band, not a chase.
- Roofs are out of reach of the planner. A late circle on a building will be treated as a wall.
- Self-splash and lightning energy are guarded. Mortar aim at a moving target is three iterations of the closed-form pitch. It is not a full server replay.

## Submission

- Repo tree is about 2.0 MB, under the 20 MB limit. Most of that is the official arena.
- MIT license. Reused code is the kit wrapper, checker, schema, stream, and map. Bot logic is original. No third-party libraries.
- Public GitHub push is blocked until `gh` is authenticated. Do not invent a repository URL.
- Finals entry must be chosen explicitly if it should differ from the best practice submission. Nothing has been submitted yet, so there is no best practice commit to preserve.

## Checks not run

- `docker build` and `check.py` under `--network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534`. Docker is not installed here. One-core timing was run with `taskset` instead. Memory footprint is the heightmap plus the grid, far under 512 MB, but that is not a cgroup test.
