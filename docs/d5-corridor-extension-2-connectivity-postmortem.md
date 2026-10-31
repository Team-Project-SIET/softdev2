# D5-CORRIDOR-EXTENSION-2 — Connectivity Postmortem and Station-Terminal Design

Status: offline postmortem record. The attempt D5-CORRIDOR-EXTENSION-2 is permanently
consumed; its evidence is immutable and unmodified by this investigation. No native
attempt, candidate, authorization artifact, world mutation, or delivery claim follows
from this document. Nothing here re-verifies the corridor.

## 1. Evidence of record

Directory: `artifacts/experiments/d5-corridor-extension-native-candidate-2/`

All entries of `artifact-manifest.sha256` verified byte-for-byte with
`sha256sum -c` — every listed artifact returned `OK`, none drifted, and none of
the three staged `.sav` world files were touched after the attempt.

### 1.1 The three successful native operations

From `result.json` (`phase.completed`, schema `company-corridor-receipt-v1`,
each `verification: NATIVE_STATE_CHANGED`, plan digest
`6d912a3dc95a78bf82914000478b7df67b7e57852c94978926167cb32c52c15d`):

| op | request | native command | built | pins | quote/cost |
|----|---------|----------------|-------|------|------------|
| ROAD_FULL | `full-00` | `CMD_BUILD_ROAD` (`is_ai` long-road, full) | BUILT | start 50096 → end 50864, 4 tiles | £1,144 |
| ROAD_CONNECT | `road-01` | `CMD_BUILD_ROAD` | BUILT | start 50095 → end 50096, 2 tiles | £142 |
| ROAD_STATION | `station-02` | `CMD_BUILD_ROAD_STATION` | BUILT | tile 50863, front 50864 | £307 |

`result.json` records 10 requests, 1 native launch, `state_changed: true`,
`preflight: PASS`, `dispatch_state: CONFIRMED`, `last_status: BUILT`.

### 1.2 Funds arithmetic

Opening authorized funds £492,149. Verified native costs: 1,144 + 142 + 307
= £1,593. £492,149 − £1,593 = **£490,556**, which matches:

- every per-op readback funds field, and
- the final route read `route-00` (`funds: 490556`) exactly.

No drift anywhere in the retained frame stream.

### 1.3 The station receipt (native readback, `station-02-response.json`)

- `sid: 2` — a new station, distinct from the corridor stations 0 and 1.
- `stop: true`, `drive_through: false`, `truck: true` — a bay truck stop.
- `tile: 50863`, `front: 50864`.
- `linked: true` — native `linked` means `GSRoad.GetRoadStationFrontTile(50863)
  == 50864`, i.e. the engine stores the stop's entrance direction as facing
  tile 50864. **It is an orientation fact, not a vehicle-access fact.**
- `stop_owner: 0`, `front_owner: 0`,
  `stop_min_height: 1 == front_min_height: 1`,
  `stop_slope: 0 == front_slope: 0`, `front_road` gate passed (road present).
- The post-build independent read (`confirm-02`) repeats all of the above.
- `eligible: true`, `cost: 307 < max_cost: 2000`.

The route read `route-00-response.json` reports:
`connected_pairs: 28`, `first_fail: 28`,
`witness tiles[28] = 50864`, `tiles[29] = 50863`,
`pickup_stop/pickup_truck/pickup_sid = true/true/0`,
`delivery_stop/delivery_truck/delivery_sid = true/true/2`, `eligible: false`.

The production replay over the retained frames returned the fail-closed label
`ATTEMPT_FAILED_EVIDENCE_PRESERVED` (`result.json: status FAILED,
verified false`), and `cleanup.json` records a certified workspace disposal.

## 2. Root cause of the pair-28 failure

### 2.1 What the route reader checks

`app/simulation/openttd/d5_extension_package/main.nut`, `ObserveRoute`
(lines 525–567), checks every adjacent witness pair with the same predicate:

```squirrel
local joined = Linked(a, b) && GSTile.GetOwner(a) == q.company &&
    GSTile.GetOwner(b) == q.company
```

`Linked` (line 184) is bidirectional native adjacency:

```squirrel
function Linked(a, b) {
    return GSRoad.AreRoadTilesConnected(a, b) && GSRoad.AreRoadTilesConnected(b, a)
}
```

Both pair-28 endpoints are legitimately company-owned (the station readback
proved `stop_owner: 0` and `front_owner: 0`), so the failure component is
`Linked(50864, 50863)`: at least one road-bit direction between the road tile
50864 and the bay stop tile 50863 is absent in the live world.

### 2.2 OpenTTD 15.x source semantics (verified against 15.0 source)

- `GSRoad::AreRoadTilesConnected(t1, t2)` (`src/script/api/script_road.cpp`):
  requires Manhattan distance 1, current road type available, and
  `HasBit(GetAnyRoadBits(t1, rtt), dir_1) &&
  HasBit(GetAnyRoadBits(t2, rtt), dir_2)` plus `DisallowedRoadDirections`
  gating. It is not an "ordinary road only" predicate — it handles every
  road-bearing tile.
- `GetAnyRoadBits` (`src/road_map.cpp:54`): for an `MP_STATION` bay road stop
  it returns exactly `DiagDirToRoadBits(GetBayRoadStopDir(tile))` — the single
  entrance bit pointing at the front tile. For a normal road tile it returns
  the stored road bits.
- Therefore, between a road tile `f` and a bay stop `s` with entrance facing
  `f`, `Linked(f, s)` succeeds **iff the front road tile `f` stores a road bit
  directed at `s`**. The stop's own entrance bit is always present.
- `GetTileTrackStatus_Station` (`src/station_cmd.cpp:3688`) exposes the same
  one-direction track on bay stops (side-sensitive), and the road pathfinder
  (`src/pathfinder/yapf/yapf_road.cpp`, `follow_track.hpp`) moves vehicles on
  the road-bit graph, with bay stops enterable only through the front — the
  `Linked` edge is the same edge the game's own connectivity model uses.
- `CmdBuildLongRoad` (`src/road_cmd.cpp`) under the GameScript path
  (`ScriptRoad::_BuildRoadInternal` → `is_ai = true`, `full` flags)
  stores full straight road bits at the end tile of the run, but only along
  the run's axis (full build: both halves unmasked, so start<end leaves full
  axis bits at both ends; plain build masks each end tile to a single bit
  toward the other, after swapping half flags when start_tile > end_tile).
  `CheckFlatLandRoadStop` (`src/station_cmd.cpp`) is a pure validate/price
  routine and never adds a road bit to the front tile, and a bay stop only
  preserves the underlying road bits when it is a drive-through (an
  over-road bay build prices a landscape-clear, so a stop never *adds* a
  road bit to the front tile) — so the lateral stop build could never have
  created the missing bit.

### 2.3 The decisive geometry

Map width is 256 tiles (witness steps of 256 are y-advances):

- The ROAD_FULL corridor 50096 → 50864 runs along the **y axis** at x = 176:
  tiles (176,195) 50096, (176,196) 50352, (176,197) 50608, (176,198) 50864.
- The stop sits at **(175,198)** — one tile *west* of the road end, lateral to
  the road axis.
- Tile 50864, as the end tile of a y-axis `is_ai` full road build, stores road
  bits in the **y** directions only (toward 50608, and the far half toward
  (176,199)). It has **no x-direction road bit** toward 50863.
- The stop's entrance faces 50864 (proven by `linked: true` ⇒
  `GetBayRoadStopDir(50863)` = the direction of 50864), so the stop's own bit
  toward 50864 exists.

Empirical cross-check inside the same route read: pair index 0,
`45748 → 45747`, is also a **bay-stop tile → front-road pair**, and it was
accepted (the read reports 28 connected pairs with `first_fail` 28). There the
front road tile (179,178) is in line on the x-axis road run and does store the
bit toward the stop. The identical production predicate passes on one
`road → station` pair and fails on the other — refuting any claim that the
verifier applies an "ordinary road-only" predicate to station tiles.

### 2.4 Verdict

**Root cause: actual physical connectivity defect (Explanation A).**

The route verifier's `Linked` predicate is the correct,
source-supported OpenTTD adjacency test; it never wrongly required an
ordinary-road shape of the station tile (Explanation B is refuted by the
semantics in 2.2 and by the passing pair 0). The construction *plan* modeled
the geometry wrongly: it placed the truck stop lateral to a y-axis dead road
end, at a tile the front road tile never received a road bit toward. The
engine accepted `CMD_BUILD_ROAD_STOP` with that entrance direction (valid
command, free ground, ownership ok), so "station built successfully" and
`linked to front` metadata were both true while the road-bit graph — and
therefore any road vehicle — could not reach the stop. After the construct,
the pair could not pass and the D5 stage correctly failed closed.

The evidence of record distinguishes A from B deterministically:
`linked: true` pins the engine-side entrance orientation of stop 2 toward
50864, so the stop's `GetAnyRoadBits` contribution contains the front
direction bit; with both tile owners at 0, the only way `Linked` fails is the
missing road bit on 50864. Not UNKNOWN.

A limitation is recorded honestly: the retained funds/cost/readbacks prove
network adjacency, not real pathfinding success. No read-only GameScript
surface exposes vehicle reachability (no "station reachable" predicate), and
nothing in the readback is equivalent to a live vehicle pathfinding or cargo
delivery test. The definitive freight proof remains a separately authorized
native freight/delivery attempt over the corrected corridor.

## 3. Corrected terminal construction design

Constraint honored: bay stop on an ordinary road tile can only *persist* alongside an existing road as a
drive-through stop, and the pinned design is a bay truck stop
(`drive_through` is force-refused by the production gate). So the stop must
occupy fresh ground adjacent to a front road tile that stores a road bit
aimed at the stop. (A bay stop over an existing road tile is not engine-
forbidden, but the engine prices a landscape-clear that tears out the road
the spur depends on, and the production `Vacant` gate refuses non-vacant
stop tiles regardless.)

**Primary design — one-tile road spur, stop beyond it (4 native ops):**

1. `ROAD_FULL` 50096 → 50864 (£1,144) — unchanged.
2. `ROAD_CONNECT` 50095 → 50096 (£142) — unchanged.
3. `ROAD_SPUR`: built with **full-build semantics** —
   `GSRoad.BuildRoadFull(50864, 50863)` — through a **dedicated spur op
   kind** added in the fresh candidate (see the constraint block below;
   the existing `full`/`road` eligibility predicates both refuse this
   corner state, and beheading the consumed attempt is not an option).
   A plain `GSRoad.BuildRoad(50864, 50863)` is **rejected here**: for a
   non-full
   two-tile build with `start_tile > end_tile` the half flags swap and each
   end tile is masked to a single bit toward the other — leaving 50863 with
   exactly one bit (toward 50864) and none toward 50862, relocating the
   consumed attempt's failure to the new pair 50863 → 50862. Under full
   build (`is_ai`, both halves unmasked) 50863 receives full `ROAD_X` —
   bits toward 50864 *and* toward 50862 — and 50864 gains the x-direction
   bit toward 50863 alongside its y bits. Both pairs 50864 ↔ 50863 and
   50863 ↔ 50862 then pass `Linked`.
4. `ROAD_STATION` tile **50862**, front **50863**, bay truck stop,
   `GSStation.STATION_NEW` (station ids 0/1 remain; the stop sid is verified
   new). Front 50863 is an ordinary road tile with a bit aimed at the stop
   (its far half), so the terminal pair passes.

Witness path grows to 31 tiles (`… 50095, 50096, 50352, 50608, 50864, 50863,
50862`), 30 pairs. Constraints to carry into a fresh attempt:

- pin 50862 as a **surveyed** live-flat/vacant/unowned debris-free tile and
  50863 as live-road-grade ground before staging; the previous survey covers
  50863 as ground but predates the spur decision;
- the fresh candidate must add a **dedicated spur op kind** with its own
  eligibility predicate: neither existing kind admits it. `full` requires
  both corners roadless company-invalid ground (`Eligible("full")`,
  `main.nut:482-486`), which 50864 — company road after the corridor —
  cannot satisfy; `road` requires both endpoints already company road,
  which 50863 still is not. The spur predicate must require exactly:
  start corner = built company road, end corner = company-invalid roadless
  ground, `covered == 1`, `pairs_ok == 0`, with the native quote deciding
  buildability. Its **post-build receipt stays natively observable only**:
  spur `pairs_ok == 1` (`Linked(50864, 50863)` both directions — this
  natively proves 50863's bit toward 50864) and `covered == 2`. The
  50862-facing bit of 50863 has **no read-only GameScript probe** (no road
  bits getter exists in the 15.x `GSRoad` static list;
  `AreRoadTilesConnected(50863, 50862)` cannot test it while 50862 is
  roadless) — so it is *not* pinned as a spur-receipt clause. It is proven
  systemically, fail-closed, by the terminal route witness pair 29
  (50863 → 50862): `verify_corridor_route` refuses the whole attempt on
  that pair's absence, and the route gate is asserted against a forged
  stop record in the test suite. A zero-mutation test-mode quote probe
  (quoting `road 50863→50862` and asserting a one-missing-piece cost) is
  the optional belt-and-braces variant if the fresh candidate wants the
  bit proven at spur-post time instead. Every other
  existing gate stays untouched;
- budgets must absorb the spur's native quote (pinned quote only;
  no planning assumption of £0); the spur runs through its own
  spur op kind as pinned above (the existing `full` admission cannot
  accept its company-road start corner);
- the 640-byte response bound and the 10-exchange request budget must be
  recomputed for 13 requests, and `MAX_RUN`/depot-slot message sizing re-checked.

**Alternative design (only if 50862 is not surveyable fresh):** extend y-axis
by one tile (50920) only if it verifies live-flat/vacant in a fresh survey, and
place the stop at tile 50920, front 50864 (in-line, front tile already carries
the far-half y bit). Requires the terrain beyond the current dead road end,
which the consumed survey evidence does not cover; it is the fallback.

**Rejected variants:** building the stop as drive-through (violates the pinned
non-freight-open truck-stop design `drive_through: false` gate); a plain
`BuildRoad` spur (masked end-bit, finding above); placing the stop on the
existing road tile 50863 (the landscape-clear pricing removes the spur road,
and the production `Vacant` gate refuses it); any edit to the consumed world
(forbidden; the attempt is consumed and its evidence is immutable).

## 4. Tests added (production paths, offline)

File: `tests/test_corridor_extension_native.py` (appended section
"the final route witness: pair semantics and station-terminal gates"):

- `test_route_witness_accepts_ordinary_road_to_road_pairs` — road-only
  witness derives `ROUTE_VERIFIED` through `verify_corridor_route`.
- `test_route_witness_accepts_the_road_to_station_terminal_pair` — the full
  30-tile witness with a bay truck-stop terminal derives the receipt when
  connectivity is reported complete.
- `test_route_witness_refuses_the_failed_final_pair_of_the_consumed_attempt`
  — the exact 28/29, `first_fail` 28 shape (50864 → 50863) is refused; a
  forged or incomplete terminal record (`delivery_stop/truck/sid` all
  correctly true and new) can never turn a disconnected station into a
  successful route — the connectivity rule dominates the metadata.
- `test_route_witness_refuses_mutated_terminal_flags` — each of the seven
  terminal structure flags is individually required.
- `test_route_witness_refuses_witness_path_drift` and
  `test_route_witness_refuses_a_mutating_route_read` — path correlation and
  the zero-cost pure-observation property.
- `test_station_gate_refuses_forged_and_drifting_terminal_records` —
  production `_station_gate` refusals: sid merge onto {0,1}, drive-through
  where the pin is a truck stop, and linkage missing.

Existing gates retained unmodified (drive-through / merge / linkage / funds
/ schedule / abort-free replay) — no production predicate was changed or
weakened, and no mocked shortcut bypasses the native read: the acceptance
tests exercise the real verifier, the refusal tests exercise the real
verifier's failure paths. The verifier itself was left untouched because the
root cause is not a verifier-modeling defect.

## 5. Independent review

A fresh-context reviewer inspected the exact change set (this document and
`tests/test_corridor_extension_native.py`) against a local OpenTTD source
checkout. Verified as correct: the root-cause verdict (Explanation A, not B),
the `AreRoadTilesConnected`/`GetAnyRoadBits` semantics, the pair-0
counter-example (`45748 → 45747`, a bay-stop pair that passes the same
predicate), the tile arithmetic (50864 = (176,198), 50863 = (175,198)),
funds arithmetic £492,149 − £1,593 = £490,556, evidence integrity
(`sha256sum -c` 48/48 OK, read-only), verifier integrity (no connectivity
gate touched or weakened), no freight/vehicle/order/cargo surface enabled,
and the full new test suite (`74 passed`). Unverifiable offline: the exact
15.0 → 15.3 runtime delta (the local checkout is 15.0; all cited APIs are
long-stable and no finding depends on a 15.3-only delta).

The reviewer initially returned **BLOCKED** with two material defects, both
now amended in place:

1. The §3 primary design as first written specified
   `GSRoad.BuildRoad(50864, 50863)` for the spur — bit-exact simulation of
   `CmdBuildLongRoad` shows a plain non-full build with
   `start_tile > end_tile` masks each end tile to a single bit, leaving
   50863 with no bit toward 50862 and relocating the consumed failure to
   the new pair. §3 now pins the spur to **full-build semantics** (the
   `full` op kind, `GSRoad.BuildRoadFull(50864, 50863)`), which leaves both
   end tiles with full axis bits.
2. The amended wording overstated engine law in two places: "a bay stop
   may only be built over an existing normal road when it is a
   drive-through" (corrected: the over-road bay build is priced via a
   landscape-clear rather than forbidden, and only a drive-through
   preserves the underlying road bits), and the routine name
   `CheckFlatLandRoadStation` (corrected: `CheckFlatLandRoadStop`, a pure
   validate/price path that never writes road bits to the front tile).
3. On re-review the amendment itself hit a second material defect: the
   pinned "full op kind" spur is inadmissible under the unchanged
   production gates — `Eligible("full")` (`main.nut:482-486`) requires
   roadless company-invalid corners, which 50864 (company road) cannot
   satisfy, and `Eligible("road")` requires both endpoints already
   company road, which 50863 is not. §3 and the constraint block now pin
   a **dedicated spur op kind** for the fresh candidate with its own
   corner-state predicate, all other gates untouched. The reviewer also
   re-verified bit-exactly that `BuildRoadFull(50864, 50863)` is
   swap-safe and unmasked at both ends (both tiles gain full x-axis
   bits), so the spur geometry stands.
4. A third probe found the then-pinned post-build predicate's
   50862-facing-bit clause unobservable (no `GSRoad` road-bits getter
   exists; `AreRoadTilesConnected(50863, 50862)` cannot discriminate
   while 50862 is roadless). The constraint block now pins the spur
   receipt to the natively observable form (`pairs_ok == 1` both
   directions + `covered == 2`) and defers the 50862-facing bit
   systemically to the fail-closed terminal witness pair 29
   (50863 → 50862 through `verify_corridor_route`), with an optional
   zero-mutation test-mode quote probe as belt-and-braces.

Final reviewer verdict on the amended document: **PASS** — the
root-cause verdict, spur bit semantics, dedicated-spur eligibility,
observable spur receipt, witness deferral, verifier integrity, test
suite (74 passed), funds arithmetic, and evidence integrity
(48/48 manifest entries OK) all verified against the OpenTTD source
and the retained evidence. Unverifiable offline: the exact 15.0 → 15.3
runtime delta (local checkout is 15.0; all cited APIs are long-stable
and no finding depends on a 15.3-only delta). If any further reviewer
cannot establish the cited semantics or finds a material defect, the
verdict is **BLOCKED**.

## 6. Exact next step

1. Complete the §5 independent review (fresh context).
2. Stage a **fresh** D5-CORRIDOR-EXTENSION-3 candidate from the pinned
   prerequisite with the §3 primary schedule (4 native ops, 31-tile witness,
   30 pairs, spur-aware budget bounds), including a fresh terrain survey
   covering tile 50862 — never reusing D5-CORRIDOR-EXTENSION-2 or any consumed
   identity/seal.
3. Obtain fresh operator authorization for that candidate only.
4. Run the authorized native attempt. The corridor is **not** verified until
   the corrected terminal proof passes (30/30 pairs, new stop sid, paired
   truck-stop classification, pinned funds chain) inside a `ROUTE_VERIFIED`
   receipt of that fresh attempt, replayed fail-closed from its retained
   frames. Freight/delivery claims are out of scope here and remain a
   separate authorized native attempt.
