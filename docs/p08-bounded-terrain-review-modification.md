# Independent review record — bounded terrain-modification planning support

Reviewer: independent OpenCode agent session (`ses_eb5f8fdb0ffe4NEvbi0T9jk0oD`),
run after implementation, over the new milestone diff only
(`app/planning/p08_terrain.py`, the `app/planning/p08_road.py` terrain hook,
`tests/test_p08_bounded_terrain.py`, this milestone's records). Prior-milestone
diff bodies (e.g. `full_load_batch`) were explicitly out of scope and only
checked for non-interference. The reviewer was read-only: no OpenTTD launch,
no connection, no commits, no artifact mutation.

## Blocking findings (all resolved before the final report)

- **B1 — `_group_ops` latent crash.** The removed
  `assert before_by_host.setdefault(min(hosts), before) == before` asserted
  that all points hosted on the same minimum-id host tile share one `before`
  height. A valid constructible capture (a steep tile at the map's NW corner
  inside a levelling corridor, hosting both a raise and a lower point) violates
  it, crashing `plan_bounded_levelling` — and, via the pipeline hook, a
  previously clean no-road outcome path. It also encoded validation in an
  `assert` (vanishes under `python -O`). **Resolution:** assertion and
  bookkeeping removed; per-`(host, kind)` grouping already represents a host
  carrying both a raise and a lower group correctly as separate deterministic
  ops; `cleared` set iteration additionally made order-explicit via `sorted`.
- **A1 — record-precision defect in the Seed 17 "82" definition** (blocking
  only because the record pins reproducible numbers): the original parenthetical
  ("no tree/rough/… flags") did not match the reproducible set. **Resolution:**
  the record and `EVIDENCE_INDEX.md` E10 now state the verified breakdown:
  111 `buildable=False` forbidden-class tiles; 82 of them neither
  water/coast/water-transport nor industry (50 tree, 13 rough, 19 of dropped
  house/station class); 23 of the 82 on slopes `!= 0`.

## Advisory findings and their treatment

- **A2** — "house or station" prose overreach: softened in the record and the
  test docstring (only 19 fence-slot endpoints carry the dropped class; every
  adjacency is fenced regardless because any adjusted corner pulls a
  forbidden-class tile into the region).
- **A3** — "clears precede corner writes" is per-host-tile, not global:
  wording corrected in record and docstring; proposals are non-executable
  diagnostics, so no global execution order is claimed.
- **A4** — phantom "returns the original outcome untouched" clause removed;
  the helper always attaches the planning outcome, connected scenarios never
  reach it.
- **A5** — winner key wording now states the lexicographic tuple
  (corner ops, clearings, hops, target height, corridor identity).
- **A6/A7/A8** — accepted as documented behavior, not defected: budget caps
  apply fail-closed to the selected winner; mixed-rejection top-level codes
  keep `NO_CONNECTED_LEVELED_CORRIDOR`; both search passes always run (best
  valid candidate wins) with the module docstring now matching the code.
- **A9** — stray non-ASCII character in a test docstring fixed; pending-review
  link in the record is this file.

## Independently affirmed (reproduced by the reviewer, not taken on trust)

- Corner-height model matches the official slope bits, including steep slopes
  (opposite-of-unmasked corner +2); halftile encodings rejected.
- The named-corner→shared-map-point mapping (N=(x,y), E=(x,y+1), W=(x+1,y),
  S=(x+1,y+1)) is the **unique** zero-contradiction mapping among all 24
  permutations on the retained Seed 17 capture.
- Seed 17 structural rejection is sound and proven from the facts at replay
  time (no hardcoded route): 31 pickups at height 2, 20 deliveries at height 1,
  capture-wide neighbor height deltas `{0: 1664, 1: 46}` (no ≥2-step escape),
  23/23 unordered height-step adjacencies have a forbidden-class endpoint.
- Determinism: total heap ordering `(cost, tile_id)`, strict parent improvement,
  total candidate key; replay produces identical digest/detail/expansions
  (176 expansions).
- Hook non-interference: `_with_terrain_proposal` only at the two
  `NO_BOUNDED_CORRIDOR` branches; rejection `code`/`detail` byte-identical;
  connected scenarios untouched; all pinned strings in
  `tests/test_p08_bounded_routing.py` unchanged and green.
- 15.3 API claims in the record match the implemented command surface
  (`RaiseTile`/`LowerTile` = `CMD_TERRAFORM_LAND`, `LevelTiles` prohibited,
  `DemolishTile` classified clearing prerequisite, mandatory `GetCornerHeight`
  readbacks). No native execution was performed.
- Rule compliance: offline-only (costs `None`, no invented facts), planning-only
  (no executable actions, `PLANNING_ONLY` / `UNSUPPORTED_PENDING_SEPARATE_VALIDATION`
  markers), honest UNKNOWN accounting.

## Post-resolution gates

`ruff check` + `ruff format --check` clean on all touched files; `compileall`
clean; `git diff --check` clean; combined suite
`test_p08_bounded_terrain` (14) + `test_p08_bounded_routing` (15) +
`test_p08_controlled_road` (62) + `test_p08_controlled_e2e` (62) +
`test_p08_terrain_design_audit` (18) all green, exit 0. Typecheck unavailable
offline (no `mypy`/`ty`/`pyright` binary).
