# D5 corridor freight cycle — offline preparation record

Status: **OFFLINE IMPLEMENTATION AND TEST PREPARATION.** This record describes
staged code and controlled offline tests only. No D5 candidate, seal,
signature, claim, authorization or native attempt exists or is created here.
No OpenTTD process was launched and no AdminPort connection was opened while
producing this record. Native freight delivery remains **UNKNOWN**; passing
offline tests are not native proof.

Predecessor design: `docs/d5-corridor-freight-design.md` (T1–T12, A1–A12).
Predecessor world: D4-CORRIDOR-5 receipt-bound `after.sav`
`a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261`.
The D4 candidate-5 directory is read-only in every test below.

## 1. What is implemented

- `app/simulation/openttd/corridor_freight.py` — protocol-5 request/readback
  contracts (640-byte named bounds), route-digest binding, the fixed
  fifteen-exchange schedule, admission/verification receipts, the fail-closed
  phase outcome and the cycle receipt.
- `app/simulation/openttd/corridor_route_optimizer.py` — offline production
  step from source-backed feasible tiles to a P05-selected route and D5
  plan (schema 2): bounded k-shortest simple path alternatives, optional
  per-tile CAPEX, and the fixed pickup/delivery/depot/front/witness pins.
- `app/simulation/openttd/d5_freight_package/main.nut` — the bounded native
  handler: site admission (including route shape and digest latch), engine
  enumeration and quote, one purchase, two order appends, order inventory,
  monitor arming, start, two independent vehicle readbacks, three bounded
  observation windows, finance corroboration and the single stop.
- `app/simulation/openttd/proof/corridor_freight_native.py` — offline staging
  of `D5-FREIGHT-1`, pinned prerequisite binding, preflight, the authorized
  execution ceremony and the replay verifier. The ceremony reuses the shared
  D2/D3/D4 freeze, claim, launch, session, replay and cleanup machinery; it
  introduces no second security framework.
- `tests/test_corridor_freight.py` — 32 controlled Squirrel-VM tests.
- `tests/test_corridor_freight_native.py` — 29 offline staging/preflight tests.
- `tests/test_corridor_route_optimizer.py` — 13 source-backed route/objective
  tests over sealed census tiles.

The staged exchange order is:

`site-00`, `engine-00`, `purchase-00`, `vread-00`, `order-00`, `order-01`,
`order-read-00`, `monitor-00`, `start-00`, `vread-01`, `load-00`,
`transit-00`, `deliver-00`, `finance-00`, `finish-00`.

## 2. Decisions and discrepancies

### 2.1 TileID geometry bounds versus the 65535 safety bound

Wire fields use the shared strict `TileID` type, whose transport bound is
`0 <= tile <= 65535` (`road_mutation.py` types, reused by
`corridor_freight.py`). That number is the highest index of the pinned
**256 × 256** Seed-17 map (`256 × 256 - 1`), not a universal geometric
validity rule. A map larger than 256 tiles per side would need a wider wire
bound before it could be staged.

Geometry is therefore checked twice, at different layers:

- **Python contract:** rejects a tile outside the numeric bound, a negative
  actor id, or a malformed correlation payload before any command.
- **GameScript:** re-derives `GSMap.GetTileX/Y`, `GSMap.IsValidTile` and the
  map width for every pinned stop, front, depot and witness tile, and the
  witness adjacency via `GSRoad.AreRoadTilesConnected`. A tile that is
  numerically admissible but geometrically invalid is refused natively as
  `D5_NATIVE_FACT`/`INVALID_SITE`, not inferred from the number alone.

This keeps the wire bound a safety bound and the compiled 24-tile witness the
geometric authority for the D5 world.

### 2.2 Thirteen logical operations, fifteen planned exchanges

The protocol defines thirteen distinct ops, but the schedule has fifteen
exchange ids because two ops legitimately run twice:

| Repeat | Exchanges | Why |
|---|---|---|
| `vread` | `vread-00`, `vread-01` | `vread-00` independently re-observes the just-purchased vehicle; `vread-01` independently re-observes the running vehicle after `start-00` and before loading. |
| `order` | `order-00`, `order-01` | One append per stop: pickup `OF_FULL_LOAD`, then delivery `OF_NO_LOAD`. |

So `13 ops + 1 extra vread + 1 extra order = 15 exchanges`. The former baked
`planned` table in `main.nut` held only fourteen rows and omitted `finish-00`,
which made the wire schedule and the package's admission table disagree. The
table now contains exactly the fifteen canonical ids in `FREIGHT_EXCHANGE_IDS`
order; no exchange was duplicated or invented. `PLANNED_FREIGHT_EXCHANGES`
and the package's dispatcher cap (32 unique ids) are asserted in both test
suites and in the staging preflight.

### 2.3 Cargo acceptance API and coverage radius

The design names `GSStation.GetCargoAcceptance`; that member does not exist in
OpenTTD 15.3's station API. The implementation uses the audited pair instead:

```squirrel
local radius = GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP)
local accept = GSTile.GetCargoAcceptance(DELIVERY, FREIGHT_CARGO, 1, 1, radius)
```

- The radius is **read natively**, not hardcoded. Per
  `docs/p08-15-3-native-fact-api-audit.md`, the effective truck-stop radius is
  3 tiles with modified catchment and 4 tiles with the default catchment in
  15.3; `GSTile.GetCargo*` also substitutes the unmodified radius when the
  setting is disabled. The point is to freeze and use the runtime's effective
  radius, not inherit a historical constant.
- `GSTile.GetCargoAcceptance` returns acceptance in **eighths**, so the
  package bounds the value to `0..8`. It reports the value as a fact; the
  authoritative threshold is enforced in Python:
  `admit_freight_site()` refuses `accept < 1`, i.e. the design's
  "at least 1/8" gate, before any mutation. The package's local `0..8` check
  is a native-fact sanity bound, not the admission policy.
- Acceptance is a **catchment** fact, not a promise of consumption volume or
  exclusive routing. The delivery window still has to observe the physical
  unload and the monitor arithmetic.

### 2.4 Transit-window behavior while the vehicle is still in its depot

`transit-watch` may legitimately start while the vehicle is still standing in
the pinned depot: `start-00` has been accepted, but the vehicle may not have
left yet. The window therefore treats `loc == DEPOT_TILE` as pre-departure
waiting, not a routing defect:

- in the depot: progress is recorded as `-1`, the sample budget advances, and
  the window keeps polling;
- on the witness: progress is the witness index;
- anywhere else off the witness: typed `INVALID_ROUTE`, because the vehicle
  drove where the corridor receipt never built road;
- at the delivery tile with a positive full load: `AT_DELIVERY`.

The same pre-departure tolerance is why `transit-00` and `deliver-00` carry no
day-budget echo. `WindowCaps` originally treated the protocol sentinel
`watch_days == -1` as a negative day cap, so those windows exhausted
immediately. The package now maps a negative/absent day echo to the module
`MAX_DAYS` cap; the tick cap remains the request's bounded `watch_ticks`.
`load-00` still carries both `watch_ticks = 2048` and
`watch_days = LOAD_WATCH_MAX_DAYS = 30`.

### 2.5 Plan identity is latched by the first accepted exchange

Every protocol-5 request carries the prelaunch seal as `plan`. The first
accepted exchange latches that digest in the package (`plan_id`); every later
exchange must present the same digest or is refused as `OUT_OF_ORDER`. This
closes the previous gap where a valid-looking request with a different plan
digest was silently answered `READY`. The package state is per staged
candidate and is never reset within an attempt.

### 2.6 Purchase receipt identity spans two exchanges

The purchase evidence is one receipt group over `purchase-00` (execution) and
`vread-00` (independent readback). The receipt therefore binds
`execution_request_id` and `readback_request_id` rather than a single
`request_id`. Both the offline test harness and the native runner accept the
current exchange id under any `*request_id` field, instead of assuming
`request_id` exists on every receipt. This is an evidence-shape rule, not a
relaxation: correlation still requires exactly the scheduled id, and the
purchase/readback pins, quote, cost, funds delta and stopped-in-depot state
must all verify.

### 2.7 Per-exchange funds readback

D5-M6 requires a funds fact at every exchange boundary. The site exchange now
returns the company balance alongside its admission facts, and purchase
returns the post-purchase balance. The cycle receipt reconciles the ledger
from those reads; no cash delta is inferred from a quote alone.

### 2.8 Route digest is a consistency latch, not authentication

The planner publishes an ordered route (the D4 witness or the optimizer's
selected alternative). Python derives
`route_digest = sha256(",".join(str(tile) for tile in route))` and sends it
on every protocol-5 exchange. `verify_request_against_plan()` re-derives the
digest from `FreightPlan.witness` and refuses a mismatched or stale request
before it reaches the wire. The package latches the digest accepted at
`site` and refuses later pickup/delivery/depot/route drift with
`STALE_ADMISSION` before purchase.

The GameScript cannot compute SHA-256 in Squirrel, so its latch proves only
that later exchanges agree with the accepted site admission. It is **not
independent authentication**. The Python plan, its sealed digest and the
operator-controlled wire are the trust anchor; the digest closes accidental
or partial route drift, not a compromised planner or transport.

### 2.9 Optimizer alternatives and the CAPEX objective

`corridor_route_optimizer.py` searches each supplied feasible tile set with
a bounded k-shortest **simple** path enumeration (Yen's), builds one P05
candidate per distinct geometry, and lets `optimize_candidate_network`
choose by planned CAPEX and its deterministic lexicographic tie-break.
`tile_costs_gbp` is optional source-backed input: raising the cost of one
tile can make a longer route cheaper and change the selection. The
optimizer never invents tiles; it refuses unrealistic inputs.

The tests use sealed census buildable tiles
(`43947/43948/43949/44203/44204/44205`, depot `44460`) and show the default
selection `(43947, 44203, 44204, 44205, 43949)` flipping to
`(43947, 43948, 44204, 44205, 43949)` when tile `44203` costs GBP 1000.
That proves selection among source-backed alternatives, not that a second
*executable* road route exists.

### 2.10 Single built route blocks an executable competing-route claim

In the retained D5 candidate-5 world only the 24-tile D4 witness is built
road. The sealed census data has no second built route; the competing census
paths above are feasible-tile evidence, not executable geometry. The staged
D5 run therefore remains bound to that single corridor. A genuine
"optimizer chose between competing executable routes" claim needs an
authoritative post-D4 built-road connectivity map or a second built route.
Until then this part is **PARTIAL/UNKNOWN** and is not claimed as proven.

### 2.11 Why the 640-byte bounds

The 24-tile `site` request plus the 64-character route digest is about 526
canonical bytes, past the historical 512-byte application bound. Protocol 5
therefore names `MAX_FREIGHT_REQUEST_BYTES = MAX_FREIGHT_RESPONSE_BYTES =
640`, the same additive precedent protocol 4 used. The 1450-byte
`GSAdmin.Send` ceiling and the 32763-byte frame ceiling are unchanged.
The named bound is applied explicitly on both protocol-5 request paths: the
live secure-session exchange and the retained-frame replay share one
encode/decode helper, so neither can silently fall back to the generic
512-byte default. Tests pin the production 526-byte `site-00` request,
exact-640 acceptance and 641-byte refusal on that shared transport path,
plus the unchanged generic 512-byte default.

## 3. Offline verification performed

| Check | Result |
|---|---|
| `tests/test_corridor_freight.py` | **32 passed** (controlled VM only) |
| `tests/test_corridor_freight_native.py` | **29 passed** (temporary staging only; includes the protocol-5 live/replay request-transport regressions) |
| Protocol-5 live/replay request transport | **PASS**: production 526-byte `site-00` accepted through outbound validation, live exchange and replay parsing; exact 640 accepted, 641 refused; generic 512 default retained |
| `tests/test_corridor_route_optimizer.py` | **13 passed** (sealed census tiles, no native run) |
| D5/corridor family (`test_corridor_*.py`) | **136 passed** |
| Planning family (`test_planning*.py`, `test_plan_*.py`, freight/supplemental/world observation) | **405 passed, 4 skipped** |
| D4 regressions (`test_corridor_construction*.py`) | included in the 136 above; retained evidence untouched |
| D5 staging/preflight rehearsal | **PASS** in a temporary directory; seal unchanged, no `CLAIM.json` |
| Prerequisite binding | **PASS**: D4-CORRIDOR-5 replay-verified; candidate-5 bytes unchanged before/after |
| Tamper refusals | **PASS**: config, source save, frozen source, removed closure entry, drifted schedule, drifted seal, existing claim, drifted world/optimizer/plan pins |
| Unconsumed candidate | **PASS (fail-closed)**: `AUTHORIZATION_UNVERIFIED` / `CLAIM_ABSENT` |
| Ruff / `compileall` / `git diff --check` | **PASS** (exit 0) |

The native test fixture stages a candidate only under pytest's temporary
directory, with the pinned prerequisite and pinned binary, and closes the
workspace at teardown. It never writes `artifacts/experiments/`, never
launches OpenTTD, never opens an AdminPort, and never creates a claim.

**Review status:** a prior T7 review covered earlier D5 bytes. Source edits
made after that review mean it does not by itself establish a fresh
comprehensive T7 review of the current bytes, and no durable T7 review record
is stored in the repository. The current revalidation recorded above re-ran
the D5 suite (74 passed) and the D4/transport regression suite (71 passed)
and verified the four 640-byte request-bound call sites. Completing T7
against the current bytes and archiving a durable review record remain
outstanding.

## 4. Honest status and remaining work

**VERIFIED (offline):** the protocol contracts, the 640-byte named bounds,
route-digest binding and drift refusal, the optimizer's bounded alternative
enumeration and CAPEX selection over sealed census tiles, the
fifteen-exchange schedule, admission/verification receipts, staging,
preflight (world/fronts/plan-model/optimizer/scenario/execution pins),
freeze/claim/seal gates, the request mapping, the fail-closed unconsumed
verdict and the exit-status contract.

**PARTIAL/UNKNOWN (optimizer-to-execution):** competing *feasible* routes
are proven; competing *executable* routes are not, because the retained
candidate-5 world has only one built road route. No second built route or
authoritative post-D4 built-road connectivity map exists in the repository.

**PREPARED (not run):** the `D5-FREIGHT-1` staging chain and the authorized
execution ceremony. No candidate exists in the repository and no
authorization has been requested.

**UNKNOWN (native):** site admission on the real candidate-5 world, engine
enumeration and quote, the real purchase, order placement, loading, transit,
unloading, monitor equality, finance corroboration, cleanup and replay. None
of these can be claimed from the offline suite.

**Still not a genuine optimizer-to-delivery POC.** The offline optimizer
production step now exists and selects among source-backed route
alternatives, but the D5 world still has only one built road route. The
product loop still needs:

1. an authoritative post-D4 built-road map (or a second built route) so the
   optimizer's choice is among competing **executable** routes, not only
   competing feasible-tile geometries;
2. independent review of the D5 preparation and native test evidence (T7);
3. one staged candidate (T8) and a fresh explicit operator authorization
   before any signing or launch (T9);
4. one authorized native attempt with an independently replay-verified
   `RECEIPT_VERIFIED` receipt and certified cleanup;
5. analytics/optimization feedback over real delivery facts only after that
   receipt exists.

No step above is authorized by this record.
