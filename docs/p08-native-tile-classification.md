# P08 native tile classification and generalized route feasibility — Task A–D record

**Date:** 2026-10-17, offline throughout (no game launch, no AdminPort connection, no
evidence mutation, no commit/push; the Seed 17 one-shot authorization remains consumed).

## Goal and non-goals

Continuation of bounded-terrain work for milestone "OpenTTD 15.3 — Native Tile
Classification and Generalized Route Feasibility": preserve native tile
classification that the frozen v1 capture contract dropped, generalize the P08
feasibility assessment over that classification, record construction readiness
per modification class, and make diagnostics distinguish the five specified
rejection families — without forcing Seed 17 to succeed and without any
arbitrary construction implementation.

Not done here: native execution of any kind, bridge/tunnel support, demolition
permission invention, renaming of any externally consumed diagnostic code.

## Task A — additive schema-2 tile classification

**What v1 loses.** The frozen `tile_facts_page` wire packs the three road
predicates into one bit and Python's `TileFact` projection keeps only 11 of the
13 wire flags, collapsing native `house`/`station` bits into `buildable=False`.
Seed 17 retains **19** such tiles (buildable=False, every projected ground/road
flag off, no industry): enough for vacancy admission, but their concrete
occupancy class is unrecoverable offline and is never inferred.

**The additive extension** (nothing frozen is touched):

- `app/simulation/openttd/tile_classification.py` — schema **2** contracts:
  new wire type `tile_classification_page` (protocol-1 envelope, explicit
  `schema=2` field), full 15-bit native predicate mask (no road packing;
  schema-1 bits 0–6/10–12 keep meaning, 7–9 split road/shift transports),
  rows `[tile, elevation, slope, flags15, industry, owner]`, industry `null`
  sentinel, owner −1..14; precedence-based `TileClass` (HOUSE, STATION,
  INDUSTRY, WATER, COAST, AIRPORT, ROAD, RAIL, DOCK, TREES, FARM, ROCK, ROUGH,
  CLEAR, `UNKNOWN_OCCUPANCY`); `TileClassificationIndex.from_pages` proves
  completeness (no gaps, no duplicates, no reordering tolerance) and exposes
  `unknown_tiles`/`class_counts`; explicit `TileFailure` codes
  `UNSUPPORTED_CLASSIFICATION_SCHEMA`, `CLASSIFICATION_UNAVAILABLE` (additive;
  v1 code identities unchanged). Budgets: PAGE_SIZE 5, request ≤159 bytes,
  response ≤508 bytes; same region/pagination/role guards as v1.
- `app/simulation/openttd/terrain_classification.nut` — additive handler
  mirroring the audited v1 terrain bridge guards (request identity, region,
  road-type selection, readbacks, date drift, canonical-JSON ≤508,
  `GSAdmin.Send`-only, no input reflection), evaluating all 15 predicates with
  no short-circuit and no packing.
- `app/simulation/openttd/terrain_classification_bridge.py` — composition
  authority: base `gamescript_bridge_package/main.nut` (same documented marker
  rename as the v1 composition) + the additive handler, digested with the
  established `name\0 len\0 content` convention. The v1 composition
  (`terrain_bridge.py`) and the frozen package bytes are not modified; the new
  package binds its own digest at capture time.

**Compatibility and fail-closed behavior.** v1 request/response/receipt
parsing is byte-identical (test: frozen v1 collapse semantics unchanged).
Missing classification evidence surfaces as `UNKNOWN_OCCUPANCY` tile facts and
`CLASSIFICATION_UNAVAILABLE` at the index level — never inferred from other
fields. Schema-2 native error envelopes carry the strict v1-style 8-field
shape plus `schema=2` (fields `protocol, type, schema, request_id, status,
error_code, cursor, failed_tile`) and parse into structured `TileFailure`
codes; a wrong field set or an unknown code is rejected at the envelope level.
The schema-2 capture cannot run until staged natively: it requires the
classified-composition preflight and a **fresh authorization** (one-shot,
separately owned); declaration alone is not a capture.

**Pre-capture blocker (recorded deliberately):** the v1 exchange pattern
binds each response to a receipt and validates the logged canonical bytes
against the parsed payload (`TileFactsReceipt`/`TileFactsExchange`). The
classification capture needs the same parity — a `TileClassificationReceipt`
that correlates the staged handler's logged canonical page bytes with the
parsed response — *before* any authorization is spent; this module provides
the wire contracts but not yet that receipt layer, and no capture is proposed
without it.

## Task B — generalized feasibility classification

`app/planning/p08_terrain.py` grows the planning-side classification (no
construction authority):

- `SegmentClass`: `ROAD_BUILDABLE`, `SUPPORTED_CLEARING` (DemolishTile-classed
  trees/farm/rock/rough), `TERRAIN_MODIFICATION` (corner-correctable clear
  ground), `UNSUPPORTED_CONSTRUCTION` (house/station/industry/transport
  footprints and water/coast; their conversion permissions are unverified
  offline), `UNKNOWN_OCCUPANCY`.
- `classify_segment(tile, tile_class=None, flags=None)`: legacy projection when no
  schema-2 evidence (dropped-class tiles stay UNKNOWN); schema-2 mapping when
  present; exact projection-coherence gate when the native mask is supplied
  (every shared predicate bit must project into `TileFact` identically —
  same-capture-instant rule);
  **contradictions between the sources downgrade to UNKNOWN**
  (fail explicit, no arbitration); a classified footprint refines a projected
  one without fighting it.
- `assess_world_feasibility(facts, pickups, deliveries, *, tile_classes=None,
  budget=MAX_PATH_EXPANSIONS)` reuses the planner `_levelling_search` under
  three bounded tiers: (1) supported classes, (2) +UNKNOWN tiles, (3)
  +blocked footprints; the corridor is reported under the least-invasive
  connecting tier with a per-class histogram, and the budget state is
  reported when the tier determination cannot finish. Deterministic winner:
  fewest hops, then lexicographic corridor.

**Retained Seed 17 replay (computed from facts, nothing hardcoded):**
450 observed tiles → 339 `ROAD_BUILDABLE`, 63 `SUPPORTED_CLEARING`, 19
`UNKNOWN_OCCUPANCY`, 29 `UNSUPPORTED_CONSTRUCTION`; assessment code
`INCOMPLETE_TILE_CLASSIFICATION` — a 24-tile corridor (20 road-buildable,
2 clearing, 2 unknown) exists only through tiles whose class the retained
evidence cannot establish (724 expansions). Feeding the schema-2 hypothesis
that those 19 tiles are houses/stations moves the code to
`UNSUPPORTED_CONSTRUCTION` (1056 expansions, same corridor shape). This is a
classification *sensitivity* demonstration, not a native finding: Seed 17's
retained result stays "no supported route, no executable proposal, P05 not
executed" and its consumption is final.

## Task C — construction readiness

`app/planning/construction_readiness.py`: typed records for `BUILD_ROAD`
(`GSRoad.BuildRoad`, executed in the fixed bounded path), `CLASSIFIED_CLEAR`
(`GSTile.DemolishTile`, exercised in the fixed path, not wired to terrain
proposals), `CORNER_RAISE`/`CORNER_LOWER` (`GSTile.RaiseTile`/`LowerTile`,
planning-only; no staged package issues them), `LEVEL_TILES`
(prohibited by contract for partial-apply and test/exec divergence),
`OCCUPANCY_CONVERSION` (out of scope; permissions unverified) and
`UNKNOWN_TILE` (schema-2 capture missing). Each record states native API,
preconditions, expected tile changes, neighbor effects, cost provenance
(runtime `GetBuildCost(BT_TERRAFORM)`/`GSAccounting` only), partial-failure
risks (multi-corner `CMD_TERRAFORM_LAND` masks are not atomic), post-command
readbacks, and the exact missing implementation.
`blocked_offline()` names the blockers: consumed authorization, no staged
terraforming executor, unverified house/station/industry conversion
permissions, UNKNOWN terraform spend.

## Task D — diagnostics

Additive stable codes in `FeasibilityCode`: `NO_CONNECTED_CORRIDOR`,
`TERRAIN_MODIFICATION_REQUIRED`, `UNSUPPORTED_CONSTRUCTION`,
`INCOMPLETE_TILE_CLASSIFICATION`, `SEARCH_BUDGET_EXCEEDED` (assessment-layer
budget code; the planner code `SEARCH_LIMIT_EXCEEDED` is unchanged for
retained replay), plus `CONNECTED_WITHOUT_MODIFICATION`. `NoRoadScenario`
gains `feasibility: FeasibilityDiagnosis | None` attached at the same two
`NO_BOUNDED_CORRIDOR` branches; pinned codes and detail strings are unchanged.
`FeasibilityDiagnosis` records world identity, relationship
(role/industry/cargo), observed coverage, segment counts, corridor histogram,
required-op inventory (tile-level only; grouped ops stay in
`plan_bounded_levelling`), expansions/budget state and a digest; `as_dict()`
is JSON-ready. No P07 delivery metrics are generated anywhere in the
assessment.

## Validation

New suites (offline): `tests/test_tile_classification.py` (13: wire gates,
precedence, unknown-not-guessed, schema mismatch, v1 compatibility,
composition purity incl. the six-field request-gate cross-check, native
error-envelope mapping, canonical key order) and
`tests/test_p08_feasibility_classification.py` (24: five classes, schema-2
mapping/refinement, exact projection-coherence gate over shared flag bits,
conflicts → UNKNOWN, Seed 17 retained assessment with 19/339/63/29 counts,
hypothesis sensitivity, budget codes, determinism, pipeline attachment with
pinned strings, connected-scenario cleanliness, readiness registry,
blockers). Pinned suites re-run green: bounded terrain, controlled road,
controlled e2e, bounded routing, design audit, tile-facts protocol, terrain
query, terrain historical-root/single-page/offline-retention and
gamescript-bridge packages. Ruff check/format clean
on touched files; compileall clean; `git diff --check` clean; typechecking
unavailable offline (no mypy/ty/pyright installed), reported rather than
skipped.

## Limits and next authorization

- Schema-2 classification waits on a fresh separately authorized capture
  (classification-package preflight → staged run → receipts); this document
  records nothing native.
- Tier codes reflect bounded, offline-verifiable knowledge only.
- Next recommended native milestone: one-shot classification capture over the
  Seed 17 rectangle using `terrain_classification_bridge` composition
  (schema-2 rows + owner + industry), then re-run the retained assessment to
  classify the 19 dropped-class tiles with observed values — enabling either
  the first authorized terrain-execution experiment or a definitive structural
  NO_CONNECTED conclusion under complete facts.
