# P08 bounded terrain-aware routing — independent OpenCode review

Recorded 2026-10-17, offline only. Reviewer: an independent OpenCode subagent
session (fresh context, no shared reasoning chain), given the uncommitted diff
(`app/planning/p08_road.py`, `tests/test_p08_bounded_routing.py`,
`docs/p08-bounded-terrain-aware-routing.md`, TASKS.md/EVIDENCE_INDEX.md
pointers) and instructed to verify by inspection and offline test runs. No
OpenTTD launch, no AdminPort connection, no evidence mutation, no commits.

## What the reviewer verified independently

- Test runs: `p08_bounded_routing` + `p08_controlled_road` + `p08_controlled_e2e`
  → 141 passed (both retained artifact sets installed, so the Seed 17 and
  fixed-demo replay tests really executed); `p08_terrain_design_audit` → 18
  passed; ruff check/format clean.
- Recomputed from the retained immutable Seed 17 facts
  (`…698799a2dfb146948fd2983ff2032253/network-facts-0.json`): 339 vacant tiles;
  17 water / 50 trees / 12 industry / 13 rough / 19 steep-slope; 31 eligible
  pickup and 20 eligible delivery stops; oracle disconnected the catchments
  (176 expansions, not exhausted); qualified coverage rows 40 (pickup) and 28
  (delivery).
- Confirmed no Seed-17-specific constants anywhere in `app/`; `station_tiles`
  has no other callers; the incumbent pair-enumeration loop bytes are
  unchanged; the fail-closed `SEARCH_LIMIT_EXCEEDED` fallback detail is
  identical to the pre-change message; the native `2..47` admission
  (`freight_native_network.py`) matches `witness_order`'s retained ordering
  exactly.
- Dijkstra determinism and boundedness inspected: total-order heap keys, each
  tile pushed at most once (strict relaxation), budget caps pops and
  exhaustion is typed (never a guessed "connected" answer).

## Findings and dispositions

| # | Severity | Finding | Disposition |
|---|---|---|---|
| 1 | BLOCKING | Dangling review-record link (`docs/p08-bounded-routing-review.md`, referenced by the routing record §5 and E9) — the record did not exist. | Resolved: this record is now authored; links valid. |
| 2 | MINOR | Doc §3 levelling detour figures inconsistent with recomputation (claimed ≤ 44 total / 28 interior; recomputed 25 total / 23 interior). | Fixed: doc now states ≤ 25 total / 23 interior (independently recomputed here from the retained facts before editing). |
| 3 | MINOR | Doc located the water barrier at x=180; retained facts place the main column at x=179, y=186–198 with fringe tiles x=178/y=186 and x=180/y=198–200. | Fixed: doc table and §1 line corrected. |
| 4 | MINOR | Length-2 witnesses (adjacent stops) survive the fallback filter but are dropped by `witness_order` (`len >= 3`), so the pre-existing "first-four-stop exhausted" detail is shown although the complete oracle found unusable witnesses. Pre-change behavior identical; nothing regressed. | Accepted as-is (behavior-safe, no bias fingered); noted here for the record. |
| 5 | MINOR | Budget check precedes the stale-heap-entry skip, so `expansions == budget` with only stale entries left can report exhaustion when all real nodes were settled. Direction of error is over-rejection, typed and fail-closed. | Accepted as-is (safe direction); noted. |
| 6 | MINOR | `SEARCH_LIMIT_EXCEEDED` details say "aggregate path expansion bound exceeded", but the oracle and selection each get an independent 4096 budget. | Accepted as-is (direction-safe); doc §2 wording changed to "bounded per phase". |
| 7 | MINOR | `test_route_never_leaves_the_captured_tile_facts` contained a vacuous assertion (neighbors only yields tiles in the dict, so membership is tautological). | Fixed: vacuous assertion removed; the meaningful region-membership check and the by-construction-untraversable comment remain. `neighbors` dropped from the test imports. |
| 8 | MINOR | Dead scaffolding loop in `test_reachability_oracle_is_deterministic_and_uniform_cost`. | Fixed: deleted. |
| 9 | MINOR | "Byte-stable/byte-equal" overclaim for the fixed-demo regression: the test compares selected corridor *coordinates* against the frozen `planning-scenario.json` inside the process; it never diffs artifact bytes. | Fixed: E9 wording now "the fixed demo's frozen corridor selection reproduces unchanged (regression test)". |
| 10 | MINOR | `full_load_batch` batch-mode engine filter additions (`p08_road.py`, `p08_network.py`, `freight_native_network.py`) ride in the same dirty tree but outside this task's reviewed change (default `False` leaves every reviewed path unchanged; `tests/test_random_distance.py` covers it). | Out of scope: retained-tree work from a prior session, not part of this diff; recorded here rather than silently merged into this record. |
| 11 | MINOR | Seed 17 replay test hardcoded map width 256. | Fixed: test now reads `facts.source.map_width` (also in the Phase C levelling BFS). |

Positive checks with no finding: `MAX_PATH_EXPANSIONS = 4096` and
`MAX_STATIONS_PER_ROLE = 4` unchanged; all `RoadOutcome` codes reused with none
invented; TileFact/`vacant`/`neighbors` reuse only; provenance digests flow
through `assemble` unchanged; executable plans contain only DEPOT/STATION/
SEGMENT on vacant tiles — no bridges, tunnels, demolition or levelling
anywhere in the reviewed diff; Phase C exists only as classification; E9
explicitly hedges delivery/OPEX/profit/ROI as UNKNOWN with no overclaim.

## Verdict

Post-fix state: all blocking findings resolved; findings 4–6 accepted as
documented behavior-safe edge cases. Re-verified after the fixes:
`tests/test_p08_bounded_routing.py` → 17 passed; ruff check and format clean
on the touched test file; no behavior change in `app/` after the fixes (test
and documentation edits only).

REVIEW: PASS
