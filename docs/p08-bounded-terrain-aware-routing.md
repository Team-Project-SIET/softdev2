# P08 bounded terrain-aware routing — Seed 17 analysis and extension

Recorded 2026-10-17 against the live `devmodule2` working tree. **Offline only**:
no OpenTTD launch, no AdminPort connection, no consumption of any native
authorization, no mutation of retained evidence. Controlled/offline results and
native observations stay distinct throughout.

## 1. Root cause of the retained `NO_BOUNDED_CORRIDOR`

The consumed one-shot smoke
`artifacts/demos/playable-demo-698799a2dfb146948fd2983ff2032253` captured the
complete native 450-tile coal rectangle (industry 0 at (183,173) → industry 1 at
(172,199), COAL, radius-3 modified catchment). Replaying its immutable
`network-facts-0.json` through the P08 supported corridor model proves:

| Fact group | Count | Meaning |
|---|---:|---|
| Buildable flat vacant corridor tiles | 339 | The only supported road corridor tiles |
| Water tiles | 17 | Native non-road, incl. the x=179 column y=186–198 |
| Tree tiles | 50 | Natively `buildable=false` |
| Rough tiles | 13 | Natively `buildable=false` |
| Industry tiles | 12 | Occupied |
| Natively non-buildable steep-slope tiles | 19 | Slope 8/9/12/13 escarpment |

The pickup catchment (31 eligible stops, height 2, x=180–184 y=171–178) and the
delivery catchment (20 eligible stops, height 1, x=170–176 y=197–200) lie in
**disconnected components** of the supported corridor graph:

1. The height-2 plateau ends in a band of natively non-buildable steep-slope
   tiles (rows 181–189); the supported model requires flat, equal-height,
   cardinal adjacency, so no supported tile crosses it.
2. The x=179 water column (y=186–198, with fringe tiles x=178/y=186 and
   x=180/y=198–200) plus trees/rough block every remaining approach down to the
   height-1 basin servicing industry 1.
3. The only southward land route around the water column would have to leave
   the captured rectangle (unobserved tiles) — an unsupported inference.

Consequences, each verified by exhaustive component analysis of the retained
facts (not by re-running P08 over a smaller slice):

- **No connected route exists through any supported buildable tile** in the
  captured area: pickup and delivery stops never share a component.
- **The first-four-stop search did not miss a feasible detour**: the
  disconnection holds for *all* 31×20 eligible stop pairs, not only the first
  4×4 the formal search enumerates. The retained failure was already a
  complete-search outcome under the supported model; the new reachability
  oracle makes that explicit and recorded.
- **A 2..47-road-tile route cannot exist under supported construction** for
  this world snapshot, so the construction limit is not the binding constraint.
- **Station/catchment facts remain valid**: coverage (pickup 40/450 and
  delivery 28/450 industry-covered rows) and stop placement are achievable;
  only corridor connectivity fails.

## 2. Implemented extension (P08 `corridor_reachability`)

`app/planning/p08_road.py` gains a deterministic bounded route search ahead of
the existing candidate selection:

- `corridor_reachability(pickups, deliveries, tiles, width, *, budget)` — one
  shared-super-source uniform-cost Dijkstra sweep over *every* eligible vacant
  covered stop (not only the first four). `(cost, tile_id)` heap ordering keep
  the sweep deterministic; expansion work is bounded per phase by the existing
  `MAX_PATH_EXPANSIONS` (4096) and fails closed (`SEARCH_LIMIT_EXCEEDED`).
  - A disconnected result is a **complete infeasibility proof** recorded with
    the eligible stop counts in the `NO_BOUNDED_CORRIDOR` reason.
  - A connected result records per-delivery **witness routes**.
- The incumbent first-four-stop candidate selection is **unchanged**: identical
  pair enumeration, identical `shortest_path`, identical depot and facility
  composition. The consumed fixed demo replays its frozen corridors
  unchanged (regression test below), preserving the pinned P08/P05 decision
  replay contract; no fixed-demo behavior changes.
- `witness_order` — deterministic candidate order for witnesses: supported
  2..47-interior corridors first (shortest, then smallest tile identity), then
  over-long corridors (still returned for an explicit upstream
  `NATIVE_CORRIDOR_BOUND` rejection, as before).
- Witness fallback — only when the incumbent selection finds no candidate
  while the oracle proved connectivity: beyond-first-four stop pairs become
  candidates through the same `assemble`/depot/2..47 pipeline. This recovers
  feasible detours the 4-station-per-role bound previously discarded, with no
  change to any previously successful decision.
- `ControlledRoadScenario.reachability_expansions` records the oracle's
  bounded expansion work separately from the selection search.
- All existing contracts are preserved: TileFact/RoadFacts inputs,
  vacancy/slope/height semantics, 512-tile capture budget, 2..47 admission
  (checked before P05 by the network layer), 4096-expansion cap, 31..20 stop
  eligibility rules, provenance digests and rejection codes.

Not implemented, deliberately: bridges, tunnels, demolition, tree clearing,
terrain levelling (see §4) and any corridor over unsupported terrain. The
search remains general World-fact-driven; nothing is Seed-17-specific.

## 3. Retained Seed 17 replay result

`tests/test_p08_bounded_routing.py::test_seed17_retained_observation_replay`
loads the retained immutable native facts and asserts:

- 450 complete tile facts; 339 supported corridor tiles; obstruction buckets
  17 water / 50 trees / 12 industry / 13 rough / 19 steep-slope.
- 31 eligible pickup stops and 20 eligible delivery stops.
- The reachability oracle is bounded, deterministic and disconnects the two
  catchments: `NO_BOUNDED_CORRIDOR` is a **proven** outcome, not a
  first-four-stop artifact.
- Tree clearing alone cannot connect the catchments (strict supported
  semantics). The optimistic levelling lower bound — relaxing the equal-height
  rule and allowing passage across the non-buildable steep-slope escarpment —
  bounds the required detour at ≤ 25 total corridor tiles (23 interior road
  tiles, inside the 2..47 native bound) but presumes terrain levelling that
  no verified GameScript API provides.

The complete retained replay for routing still yields **no executable
candidate** for the coal pair: planning remains `NO_FEASIBLE_SERVICES`,
P05 is not run, no construction or delivery is claimed, and delivery/OPEX/
profit/ROI remain UNKNOWN. The previous native authorization stays consumed;
a fresh native validation would need a new reviewed frozen-input preparation
and a separate one-shot authorization.

## 4. Construction feasibility classification (Phase C)

| Operation | Feasibility effect for Seed 17 coal pair | Classification |
|---|---|---|
| Tree clearing (50 tiles) | Does **not** connect the catchments (proven from retained facts) | Implementable only via native construction actions, but **insufficient**; excluded from executable plans |
| Rough-land building (13 tiles) | Does not connect | Same as above: insufficient; no clearing evidence needed |
| Additional turns | Turns are already unrestricted in the supported road model; not a barrier | Already supported; no enabling value |
| Corridor levelling / crossing the 19 natively non-buildable steep-slope tiles | Would connect (detour ≤ 2..47 interior tiles) but requires terrain modification of natively non-buildable land | **Unsupported** — OpenTTD 15.3 GameScript exposes no land raising/lowering or demolition commands for GS companies; no verified foundation/earthworks command exists; requires a separate milestone with native Levelling evidence before any executable plan may use it |
| Bridges over the 17 water tiles | Would connect across x=180 | **Excluded** by this milestone's restrictions; unsupported in the executable plan |
| Tunnels / demolition | Not needed by any connecting route | Excluded |

No unsupported construction action enters any executable plan; planning cost
estimates remain separate from observed native spending.

## 5. Tests and verification

- `tests/test_p08_bounded_routing.py` (17 tests): detour around obstacles,
  multiple turns, corridor/depot geometry, unsupported terrain
  (water/slope/height/industry), missing capture facts, catchment precedence,
  beyond-first-four witness recovery with P05 compatibility, witness ordering
  with the 2..47 preference, oracle determinism and budget exhaustion
  (fail-closed), diagnostic reason composition, retained Seed 17 replay, and
  the retained fixed-demo corridor regression.
- Existing suites remain green: P08 controlled road + e2e (124), terrain
  design audit (18), REPRODUCE focused sets (90 + overlaps), freight
  planning/network/delivery (145). Ruff lint/format clean; `git diff --check`
  clean; `compileall` clean. **Typecheck unavailable offline** (no `ty`/mypy
  binary is installed; `[tool.ty]` carries env paths only).
- Independent OpenCode review: see [the review record](p08-bounded-routing-review.md).

## 6. Remaining native validation requirements

Nothing in this record establishes native feasibility or performance. A new
native attempt would require, in order: a fresh reviewed frozen-input identity
(`app/demo_smoke_preflight.py` preflight PASS), a separately granted one-shot
launch authorization (the previous one is consumed and never retried), the
existing capture checklist (facts 1–7 of
[random-world-observation-inventory](random-world-observation-inventory.md)),
then P08/P05 on admitted native facts with any candidate rejection retained as
diagnostics. Expected honest outcomes remain possible in both directions: a
proven `NO_BOUNDED_CORRIDOR` (as retained for the coal rectangle) with the
complete-search justification, or bounded candidates for other pairs if their
supported corridors connect.
