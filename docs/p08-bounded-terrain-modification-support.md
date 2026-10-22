# Bounded terrain-modification planning support (P08, OpenTTD 15.3)

Status: offline implementation and validation complete; **native execution of
any proposal remains unsupported** until separately validated under a fresh,
reviewed one-shot authorization. The consumed Seed 17 smoke authorization is not
retried or reinterpreted. Nothing in this record runs OpenTTD, touches the
AdminPort, mutates evidence, commits or pushes.

## Why this extension exists

The prior milestone ([bounded terrain-aware routing](p08-bounded-terrain-aware-routing.md))
proved the retained Seed 17 coal pair disconnected in the *supported* corridor
graph and explicitly left levelling out of scope. This milestone implements the
smallest safe planning/validation extension for that gap: bounded levelling
proposals across limited height differences, as **diagnostics attached to
bounded P08 outcomes** — never as executable construction actions, never as a
way to turn `NO_FEASIBLE_SERVICES` into success.

## Verified 15.3 command surface (official sources, tag 15.3)

Checked against `src/script/api/script_tile.hpp`, `script_tile.cpp` and
`src/slope_type.h`:

- `GSTile.RaiseTile(tile, slope)` / `LowerTile(tile, slope)` issue
  `CMD_TERRAFORM_LAND` with an explicit corner bit mask; `GSCompanyMode`
  required; corners process west, south, east, north; one corner can cascade
  neighboring corners ("misc Terraforming" side effects); errors
  `ERR_AREA_NOT_CLEAR`, `ERR_TOO_CLOSE_TO_EDGE`, `ERR_TILE_TOO_HIGH`/`LOW`
  (plus `ERR_LIMIT_REACHED` from the command layer). Per-corner cost bills only
  via runtime `GetBuildCost(BT_TERRAFORM)` — never invented offline.
- `GSTile.LevelTiles(start, end)` (`CMD_LEVEL_LAND`) may apply partially on
  failure and may return `true` in test mode while failing in exec mode —
  therefore **prohibited in proposals**.
- `GSTile.DemolishTile(tile)` (`CMD_LANDSCAPE_CLEAR`, deity or company mode) is
  used only as the classified clearing prerequisite for trees/rough/rocks/fields
  (`MP_CLEAR`/`MP_TREES` ground types; all clear-infra requires a clear-op
  first).
- `GSTile.GetCornerHeight` / `GetMinHeight` / `GetSlope` are the mandatory
  post-operation readbacks (and `IsBuildable` is the pre-stop host readback).
- `IsBuildable` semantics (15.3): `MP_CLEAR`/`MP_TREES` true (slope does not
  matter), `MP_WATER` true only for coast, town-owned single-road-tiles true;
  houses, industry, stations, rail false. API existence does not prove a
  proposal feasible offline.

## Corner-height model (proven, used verbatim by the planner)

- Official slope bits (`slope_type.h`): W=1, S=2, E=4, N=8, steep=0x10. Steep
  slopes raise the corner opposite the unmasked corner by two steps, the three
  masked corners by one.
- Named corner of tile `(x, y)` maps to shared map points **N=(x, y),
  E=(x, y+1), W=(x+1, y), S=(x+1, y+1)**. This mapping was selected among the
  24 permutations by brute-force consistency against the retained Seed 17
  capture: zero shared-corner contradictions across all captured tiles.
- All four corner heights are therefore derivable from retained
  `(min_height, slope)`; no new native capture is needed to *plan* (only to
  *execute and verify*).

## Implemented contracts

`app/planning/p08_terrain.py` (new):

- `TerrainOp` — kinds `raise`/`lower`/`clear` only (no `level`), with official
  corner-name ordering (N, E, W, S), before/target heights, deterministic sort
  key; on the same host tile clear ops sort before corner writes
  (DemolishTile before RaiseTile/LowerTile there); proposals are
  non-executable diagnostics, so no cross-tile execution order is claimed.
- `TerrainProposal` — planning-only markers (`execution_status="PLANNING_ONLY"`,
  `native_execution="UNSUPPORTED_PENDING_SEPARATE_VALIDATION"`),
  `terraform_cost_gbp=None` (costs only via runtime
  `GetBuildCost(BT_TERRAFORM)`), `cost_category=CAPEX_CATEGORY_TERRAIN`
  ("terrain-modification") as the operational-analytics CAPEX extension point
  (is distinct from "transport-infrastructure"; attribution happens once a
  native attempt observes actual spend), required readbacks including
  `GSTile.GetCornerHeight`, stable SHA-256 digest, region/halo split.
- `TerrainInfeasibility` with typed codes: `UNSUPPORTED_SLOPE_ENCODING`,
  `NO_CONNECTED_LEVELED_CORRIDOR`, `SEARCH_LIMIT_EXCEEDED`,
  `FORBIDDEN_TILE_IN_REGION`, `UNOBSERVED_TILE_AFFECTED`,
  `TERRAIN_BUDGET_EXCEEDED`; rejection breakdown detail.
- Budgets (fail-closed): `MAX_TERRAIN_CORNER_OPS=32`,
  `MAX_TERRAIN_HEIGHT_DELTA_STEPS=1`, `MAX_TERRAIN_CLEARED_TILES=8`,
  `MAX_TERRAIN_REGION_TILES=128`, `MAX_TERRAIN_CORRIDOR_INTERIOR=47` (the
  native admission keeps road paths 2..47 tiles), shared with the existing
  `MAX_PATH_EXPANSIONS` search budget.
- `plan_bounded_levelling(facts, pickups, deliveries, *, budget, ...)` — takes
  retained facts directly (`SupplementalPlanningFacts`); retained replays cannot
  build `ValidatedPlanningFactInput` offline, so crossing that adapter is not
  required (and the e2e fixture worlds do not match Seed 17 industries anyway).
  Per candidate target height, a bounded shared-super-source Dijkstra yields one
  canonical corridor per connected delivery; two bounded passes run (outermost
  captured ring permitted, then ring excluded) so interior proposals are still
  enumerated when tree candidates die on capture-edge closures; every candidate
  is validated; the winner is the lexicographic minimum of (corner ops,
  clearings, hops, target height, corridor identity). Fully deterministic subject to the input bytes.
- Shared-corner region closure: every captured tile sharing an adjusted corner
  point joins the mutation region; a map-grid tile sharing an adjusted corner
  while missing from the capture rejects with `UNOBSERVED_TILE_AFFECTED`
  (no corner writes off-capture, ever). Halo = readback-only cardinal
  neighbors of the region.
- Clearing classification: tiles in the mutation region whose ground is
  trees/rough/rocks/fields require a classified `clear` op first — **including
  region rim tiles** that merely share a raised corner, not only corridor
  interior tiles.
- Unclassifiable obstructions: a retained tile that is neither buildable nor
  classified clearable is rejected, not guessed. This is load-bearing: the
  wire's 13th/12th flag bits (house/station) are deliberately *not* projected
  into `TileFact` (see `app/simulation/openttd/tile_facts.py`); they only force
  `buildable=False`. 15.3 `IsBuildable` is true for `MP_CLEAR`/`MP_TREES`
  regardless of slope, so such tiles cannot be MP_CLEAR ground — but the
  concrete obstruction class (house vs station vs other uncaptured type) is
  lost, and with it the clearing semantics (house demolition carries unknown
  town-rating behavior; stations are pre-existing infrastructure). Offline the
  planner must therefore reject; see Seed 17 below.

`app/planning/p08_road.py`:

- `NoRoadScenario` gains optional `terrain_proposal: TerrainOutcome | None`;
  the helper `_with_terrain_proposal` runs `plan_bounded_levelling` and attaches
  the resulting outcome (proposal or structured infeasibility) at both
  `NO_BOUNDED_CORRIDOR` branches of `generate_road_scenario` while keeping the
  code path and the pinned detail strings byte-identical. Connected scenarios
  never reach the helper. No new `ConstructionKind` is added; proposals never
  enter an executable `ExecutionPlan`.

## Seed 17 retained replay: structured rejection, with proof

Replaying the retained immutable capture
(`artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json`,
450 tiles) through `plan_bounded_levelling` yields
`NO_CONNECTED_LEVELED_CORRIDOR` deterministically (176 search expansions), and
the test suite proves why from the facts alone (independently reproduced by
the review):

- The eligible stops force a crossing: all 31 pickups sit at height 2, all 20
  deliveries at height 1; capture-wide neighbor height differences are only
  `{0: 1664, 1: 46}` — no `|Δ| ≥ 2` edge exists anywhere, so the ±1-step
  levelling budget has no higher-delta escape hatch in this world.
- There are **23 unordered height-step adjacencies** (46 ordered, `|Δ| ≤ 1`),
  and **every one has at least one endpoint classified forbidden** for the
  mutation region (`FORBIDDEN_TILE_IN_REGION` class: water/coast/industry/
  transport, or an unclassifiable non-buildable obstruction). Forbidden tiles
  can never be corridor members, so no crossing is possible at any target
  height.
- The capture contains **111** `buildable=False` (forbidden-class) tiles; of
  those, **82 are neither water/coast/water-transport nor industry** (50 tree,
  13 rough, 19 with no other projected class — these 19 are the tiles whose
  concrete obstruction class was dropped by the `TileFact` projection), and
  **23 of the 82 are on slopes `!= 0`** along the escarpment line. Only the 19
  no-projected-class tiles can be attributed to the dropped house/station wire
  bits (verified 15.3 `IsBuildable` is true for `MP_CLEAR`/`MP_TREES`
  regardless of slope); the rest are classified through their own flags.
- Consequently no corner write around a crossing can be authorized from the
  retained facts: the fence endpoint is either explicitly forbidden or an
  obstruction whose clearing semantics cannot be classified offline. This is
  the same underlying world fact the prior milestone reported as
  `NO_BOUNDED_CORRIDOR` — it is **not** reinterpreted as a search bug, and no
  proposal is fabricated for it. The mapping proof also reproduces: the
  chosen named-corner→map-point mapping is the unique zero-contradiction
  mapping among all 24 permutations on this capture.
- Missing-fact recovery path (documented, not invented): a future native capture
  preserving the house/station flags (or tile type) would allow classifying the
  remaining 19 fence tiles; whether DemolishTile on them is legal/advisable
  (town rating, station ownership) is native-review territory.

## Partial-mutation and test/exec discrepancy handling

- `LevelTiles` is prohibited outright (documented partial application +
  test/exec divergence), so proposals express intent only as per-corner
  `RaiseTile`/`LowerTile` ops plus classified clears.
- Even per-corner sequences are accepted by `CMD_TERRAFORM_LAND` as a whole;
  a mid-sequence failure can leave earlier corners applied. Proposals are
  therefore diagnostics, and any future native validation must include
  post-operation readbacks (`GetCornerHeight` etc.) and explicit
  partial-failure handling before a P05 milestone may consume the outcome.

## What a future native validation needs (not performed here)

1. A fresh, reviewed one-shot authorization (the previous one is consumed).
2. Optionally first, a capture extension preserving house/station (or tile
   type) per tile so escarpment fences like Seed 17's can be classified.
3. Native execution of a small `TerrainProposal` under `GSCompanyMode`, with
   pre/post `GetCornerHeight` readbacks, `GetBuildCost(BT_TERRAFORM)` cost
   capture, and documented behavior under `ERR_*` failures — before any claim
   about native terraforming success.

## Test record and gates

- `tests/test_p08_bounded_terrain.py` — 14 PASS: official slope-bit corner
  heights (incl. steep), supported/unsupported slopes, shared-corner region
  closure, deterministic digest, classified clearing, budget fail-closed
  behavior, unobserved-tile rejection, forbidden-region rejection, retained
  Seed 17 rejection + fence proof, fixed-demo pipeline hook, P05/P07
  compatibility checks, route-length bound. `pytest` prints no summary line in
  this environment; all runs verified by exit code and dot count.
- Pinned suites regressed green: `test_p08_controlled_road.py`,
  `test_p08_controlled_e2e.py`, `test_p08_bounded_routing.py`,
  `test_p08_terrain_design_audit.py` (159 total, dotted output).
- `ruff check` + `ruff format --check` clean on all touched files;
  `compileall` clean; `git diff --check` clean. Typecheck unavailable offline
  (no `mypy`/`ty`/`pyright` binary in this checkout) — reported, not skipped
  silently.
- Independent OpenCode review of the new diff: see
  [the review record](p08-bounded-terrain-review-modification.md).

## Honest accounting

- OPEX, profit and ROI for any Seed 17 service remain UNKNOWN; terrain
  modification CAPEX is *categorized* (`CAPEX_CATEGORY_TERRAIN`) but unpriced
  until runtime cost observation.
- Controlled fixtures prove planning/validation behavior only; they do not
  prove native terraforming success.
- No bridge/tunnel support; no height delta > 1 step; no water/coast/industry/
  road/rail mutation; Seed 17 native feasibility stays UNKNOWN until a fresh
  authorized native review.
