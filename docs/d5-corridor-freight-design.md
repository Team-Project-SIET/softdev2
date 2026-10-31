# D5 design — corridor freight cycle on the D4-built corridor (offline)

Status: **OFFLINE DESIGN ONLY.** No candidate, claim, seal, signature or
authorization exists or is created by this document. Nothing describes an
authorized native action. Any native execution for D5 requires the future
gates in §12: independent review, preflight, and a fresh explicit operator
authorization. Evidence-based facts cited here are the retained records of
committed identities; no historical evidence is rewritten or relabeled.

Predecessors consulted (all committed at `a20cbf7`): D4-CORRIDOR-5 outcome
(`docs/handoff/2026-10-26/d4-corridor-native-candidate-5-outcome.md`, E35),
road vehicle lifecycle proof (`docs/road-vehicle-lifecycle-proof.md`,
legacy lane), first-freight-delivery record
(`docs/first-freight-delivery-proof.md`, legacy lane), native-attempt
analytics record (`docs/native-attempt-analytics.md`, E34), the
requirements-evidence matrix and the planning boundary vocabulary.

## 1. Problem statement and measurable objective

D4 established the physical layer of the D-chain on the Seed-17 world: two
road runs joined by a perpendicular corner (`op-00`–`op-03`), a pickup truck
stop at tile `45748` with front `45747`, a delivery truck stop at `50351`
with front `50095`, and a depot at `45487` with front `45743`, all
`ROUTE_VERIFIED` 23/23 and receipt-bound by authoritative `after.sav`
`a81ac836…ef261` (E35). It proves **construction only**: no vehicle, order,
delivery, OPEX, net-profit or ROI fact exists anywhere in the D-chain
records, and the full OPEX/net-profit/ROI row of the matrix is
`UNKNOWN`.

Meanwhile the same repository has proven on *other* worlds, never on this
one: (a) the native vehicle purchase → single order → start → depot-departure
lifecycle (road-vehicle-lifecycle Attempt 2, legacy infrastructure lane,
engine 123, capacity 20, price £4,429, MOVED at ticks 23–73), and (b) a
complete native freight delivery cycle — full-load pickup, delivery with
unload, industry pickup/delivery monitors, quarter income increase
(`NATIVE_MULTI_SERVICE_DELIVERY_VERIFIED`,
`artifacts/runtime/openttd-15.3-first-freight-delivery-attempt17`). The
chain "Python logistics planning → validated plan → OpenTTD execution →
native-state verification → machine-verifiable evidence → optimization
analysis" breaks today at the third step on the D-chain world.

**Objective (measurable): put exactly one company-owned road vehicle on the
D4-built corridor in the candidate-5 `after.sav` world and complete exactly
one native pickup→delivery cycle for cargo 1, machine-verified:**

- D5-M1 the corridor is admitted natively before mutation: both stops
  present and truck-stop-typed, depot present, the retained 24-tile witness
  re-checks on the open road, company funds = £492,149, and the delivery
  stop's native cargo-1 acceptance is ≥ 1/8 with pickup-side industry 0
  visible as producer of cargo 1;
- D5-M2 exactly one compatible non-articulated road engine with default
  cargo 1 is admitted and purchased once with a **positive tested quote
  equal to the real price** within the £2,000 per-op ceiling;
- D5-M3 the order set is exactly `[pickup OF_FULL_LOAD, delivery
  OF_NO_LOAD]`, both goto-station orders, verified by independent readback;
- D5-M4 loading observed physically: a full load amount `L > 0` of cargo 1
  (station waiting drops into vehicle capacity, vehicle full/leaves station
  state), with transit observed by per-tick position sampling: every sampled
  position lies on the ordered witness (the pinned depot tile is exempt at
  any sample, since it is off-witness by construction) and sampled witness
  indices never regress
  (sampled-direction monotonicity); arrival requires the delivery tile with
  a full load. This is sampled evidence, **not** tile-by-tile continuity: a
  vehicle that left the witness and returned between two samples would not
  be observed, and the receipt makes no continuous-path claim;
- D5-M5 delivery observed physically: GSCargoMonitor pickup and delivery
  amounts for industry 0/1 **equal the observed load L exactly**, the
  vehicle is empty after unloading, and company accepted-cargo / recurring
  income increase within the same economy quarter with the delivery stop's
  last-accepted date corroborating it;
- D5-M6 finance reconciles exactly at every exchange boundary (per-exchange
  funds readbacks; purchase cost = quote; no invented cash deltas), and
  purchase + observed revenue are recorded in the receipt; annual running
  cost, OPEX, net profit and ROI stay **UNKNOWN**;
- D5-M7 a receipt binding the plan digest, the copy of the authoritative
  D4 `after.sav` (before) and a fresh authoritative `after.sav` (after)
  exists, replay-verifiable offline to `RECEIPT_VERIFIED`, with certified
  cleanup and a full artifact manifest — statuses copied verbatim so the
  existing `analyze-native-attempts` analytics (E34) consumes the attempt
  without modification.

Partial evidence (a halt at any gate) is an honest D5 outcome, not a
success: the same one-shot discipline that made D4 completeable applies.

## 2. In-scope / out-of-scope

**In scope (this milestone):**

1. Offline: protocol-5 contracts, the route optimizer production step, and
   the GameScript package for the corridor-freight ceremony (new, bounded,
   additive); proof/ceremony module reusing the proven D4 staging machinery
   (prelaunch/seal/claim/authorization/frame capture/saves/manifest/cleanup/
   replay skeleton); controlled tests; preparation and review documentation.
2. Native (only under §12 authorization): one staging over a copy of the
   candidate-5 `after.sav`; one launch / one secure X25519 connection;
   fetch site admission (D5-M1); purchase, two orders, start (D5-M2/M3);
   one load→transit→deliver observation (D5-M4/M5); finance readbacks
   (D5-M6); receipt, saves, cleanup, replay (D5-M7).

**Out of scope (explicitly not this milestone):**

- Full OPEX / net-profit / ROI (annual accounting): `UNKNOWN` forever in D5
  unless a separately designed accounting event (e.g. a verified
  calendar-rollover cost observation) proves it.
- A second vehicle, refits, articulated engines, buses, non-default cargo,
  transfers, waypoints, shared orders.
- Selling, disposing of or renaming the vehicle; changing industry
  production, acceptance or economy settings; unpausing; modifying the
  P05/P08 planner.
- Reusing any consumed identity (`D4-CORRIDOR-1/3/4/5`, lifecycle
  attempts), editing any retained evidence, or touching the D4 corridor
  topology (no construction ops at all).
- Any Git staging/commit/push as part of D5 native work; that stays a
  separate, later, explicitly authorized step.

## 3. Architecture, data flow, and dependencies

New files, mirroring the proven D4 layout:

| Artifact | Role |
|---|---|
| `app/simulation/openttd/corridor_freight.py` | Protocol-5 contracts (`FreightRequest`/`FreightReadback`/phase contracts), plan identity, admission/verification functions |
| `app/simulation/openttd/corridor_route_optimizer.py` | Offline map-to-route production step: feasible tiles → P05 candidates → selected route/plan, with bounded alternative enumeration and optional tile costs |
| `app/simulation/openttd/d5_freight_package/info.nut`, `main.nut` | GameScript bridge; ports the proven lifecycle kernel (`road_vehicle_package` Site/Compatible/VState/VCommand/Motion) plus the delivery-evidence kernel (`freight_delivery_package` GSCargoMonitor arming/snapshot semantics) bound to the D4 corridor geometry |
| `app/simulation/openttd/proof/corridor_freight_native.py` | Ceremony: staging, PRELAUNCH seal, claim, authorization payload, one-attempt runner, readback persistence, receipt build, cleanup, replay verifier; reuses `corridor_construction_native` helpers (encoding, freeze, manifest, save binding) and `road_vehicle_lifecycle` admission/verify semantics by import, not by copy, where they carry no extra world assumptions |
| `tests/test_corridor_route_optimizer.py` | Source-backed competing-route and CAPEX-objective tests over sealed census tiles |
| `tests/test_corridor_freight.py` | Controlled stub-VM protocol/admission/verification tests (pattern of `tests/test_corridor_construction.py`) |
| `tests/test_corridor_freight_native.py` | Ceremony-level offline tests: staging refusal cases, replay of controlled frames, retained-evidence regressions (skip when retained dirs absent) |
| `docs/d5-corridor-freight-design.md` (this file) and later a preparation/outcome record pair | Design now; staging/outcome records only when the real gates pass |

Data flow: candidate-5 authoritative `after.sav` (immutable input) → staged
isolated disposable copy → sanitized OpenTTD 15.3 runtime + admin crypto →
one X25519 secure Admin session → protocol-5 canonical-JSON exchanges →
per-phase independent verification in Python (P01/P02 contract discipline:
strict types, canonical bytes, `plan_hash` binding) → `receipt.json` +
endpoint/save evidence → offline replay verifier. Python owns optimization,
identity, validation, deadlines and evidence binding; GameScript executes
synchronous commands under `GSCompanyMode` and returns bounded correlated
readbacks — the one-line P01 rule, unchanged.

No planner changes: P05/P08 stay untouched. The D5 candidate is hand-staged
like D4's (one identity constant, frozen bytes); wiring the D5 ceremony into
the P05 optimizer is deliberately deferred until a first native cycle exists
(§11 T12).

### Dependency graph (see §11 for the ordered tasks)

```
T1 contracts ─▶ T2 GameScript package ─▶ T4 ceremony module
T1 contracts ─▶ T3 receipt/verify/replay offline ─▶ T4
T2/T3 ─▶ T5 controlled tests ─▶ T6 docs ─▶ T7 review gate ─▶ T8 staging
T8 ─▶ T9 operator authorization (future) ─▶ T10 the one attempt
T10 ─▶ T11 outcome records (matrix/analytics/close-out) ─▶ T12 planner wiring (later)
```

## 4. Entities, messages, state transitions, failure modes

### Protocol 5 (new; additive; never a silent relaxation of 512)

`FreightRequest` — canonical UTF-8 JSON, one NUL-terminated body, exact
stride from D4's `CorridorRequest`: fields `protocol: 5`, `op`,
`request_id: ^[a-z0-9-]{1,32}$`, `plan` (hex digest), `route_digest`
(hex digest, below), `company: 0`, `pickup: 45748`, `delivery: 50351`,
`depot: 45487` (all as strict TileIDs + `CompanyID` from `road_mutation.py`
types), the `site` op's ordered `route` tile list, `engine`, `vehicle`
(default −1), `max_cost: 2000`, `expected_cost: 0`, plus per-op phase
budget echoes so every readback is self-contained. Encoded size bound
`MAX_FREIGHT_REQUEST_BYTES = 640` (**named constant** — E33's lesson applied
from day one; no hard-coded literal returns). The 24-tile route plus its
64-character digest measures about 526 canonical bytes, so protocol 5 takes
the same additive 640 bound protocol 4 used for its witness response; it is
not a silent widening of the historical 512 rule.

`FreightReadback` — same correlation keys, `route_digest`, `funds`, `status`
literal, per-op typed fields; response bound
`MAX_FREIGHT_RESPONSE_BYTES = 640` (named constant, same additive precedent).
Outbound `GSAdmin.Send` stays below the 1450-byte engine ceiling and the
decoded frame ceiling stays `MAX_GAMESCRIPT_PAYLOAD_BYTES = 32763`.

**Route digest binding (trust boundary).** `route_digest` is
`sha256(",".join(str(tile) for tile in route))` over the ordered witness,
computed in Python. The selected route is the optimizer output (below), not
a hand-typed copy of the D4 path. The `site` exchange carries that route;
the GameScript validates it as a 3–24-tile cardinal path and latches its
digest for the attempt. Every later exchange must echo the same digest and
the same pickup/delivery/depot pins or is refused `STALE_ADMISSION` before
any purchase. Python independently re-derives the digest from the plan
witness and refuses a mismatched request before it is sent. The GameScript
cannot hash in Squirrel, so its latch is a consistency check, **not
independent authentication**; the Python `FreightPlan` (and its sealed plan
digest) is the trust anchor. An attacker who can already write the wire is
inside the trust boundary this design assumes is operator-controlled.

### Optimizer-derived route

`app/simulation/openttd/corridor_route_optimizer.py` turns authoritative
feasible tiles into P05 `PlanningScenario` candidates, runs the existing
`optimize_candidate_network` solver, and converts the selected decision into
the D5 `FreightPlan` (schema 2) that supplies `pickup`, `delivery`, `depot`,
all three `*_front` values, the witness and `route_digest`. A bounded
k-shortest **simple** path enumeration (Yen's) generates competing
geometries for the same endpoints; the P05 objective (planned CAPEX, then
the solver's deterministic lexicographic tie-break) chooses among them.
Optional source-backed `tile_costs_gbp` lets a longer but cheaper route win;
the optimizer never invents buildable tiles. It is not a general vehicle
pathfinder: bridges, tunnels, slopes, traffic, cargo choice and engine policy
are outside it.

The retained D5 candidate-5 world exposes only **one built** road route (the
24-tile D4 witness). Competing feasible routes in the sealed census data
prove the optimizer *can* select among alternatives and that a tile cost can
flip the decision, but they are not an executable D5 route: the D5 staged
run remains bound to the single built corridor. Genuine competing
**executable** routes are blocked on an authoritative post-D4 built-road
connectivity map or a second built route; that remains **UNKNOWN/PARTIAL**
and is not claimed as proven.

Ops (request→status, each with exact expected exchange state):

| op | Purpose | Success status | Native cost |
|---|---|---|---|
| `site` | admission packet (facts below) | `READY` / refusals typed | 0 |
| `engine` | enumerate + admit one engine/pair under the policy | `READY` | 0 |
| `purchase` | test-mode quote then `BuildVehicle` at depot | `BUILT` (new vehicle id) | quote £≤2,000 |
| `vread` | independent vehicle readback | `READ` | 0 |
| `order` | append pickup stop order (`OF_FULL_LOAD`) then delivery (`OF_NO_LOAD`) | `ORDERED` (per stop) | 0 |
| `order-read` | exact order inventory | `ORDER_SET_VERIFIED` | 0 |
| `monitor` | arm industry pickup/delivery monitors (keep_monitoring=true) pre-start | `ARMED` | 0 |
| `start` | start vehicle | `STARTED` | 0 |
| `load-watch` | window 1: full load observed at pickup | `LOADED` (with load readback) | 0 |
| `transit-watch` | window 2: tile transitions along the witness to delivery | `AT_DELIVERY` | 0 |
| `deliver-watch` | window 3: unloading + monitor consume (keep_monitoring=false) | `DELIVERED` | 0 |
| `finance` | funds + income/profit monitor readbacks | `FINANCE_VERIFIED` | 0 |
| `finish` | stop vehicle; final readback | `PHASE_STOPPED` | 0 |

Planned exchanges 15; hard request cap 32; the request-budget machinery is
D4's (admission refuses the 33rd request permanently).

`site` admission facts (all read natively in one exchange): both stops are
valid truck-stop-typed stations; depot is company-owned at `45487`; the
ordered route is a 3–24-tile cardinal path between the stops with exactly
one depot front, its digest matches every later exchange through the latch,
and the 24-tile witness re-checks as connected road on the company's
network; `GSStation.GetCargoAcceptance(delivery, cargo 1) ≥ 1/8`; industry
0 visible as producer (last-month production for cargo 1 is reported as a
fact, `WAITING_{pickup}` reported as fact); funds = £492,149 exact; company
owns zero vehicles pre-purchase; pause state false. Every fact is read, not
inferred; any mismatch is a typed refusal before any mutation.

Orders: destination ids are the **station IDs of the built stops** (read
from `site`'s station readbacks; never hard-coded tile math), per the
proven delivery contract.

### Phases and state transitions

```
staged (PRELAUNCH sealed) → PREFLIGHT PASS → independent review PASS
→ PENDING_AUTHORIZATION → signed (AUTHORIZATION.json)
→ claim consumed → LAUNCH
→ admitted[site READY] → purchased → ordered → started
→ LOADED → AT_DELIVERY → DELIVERED → finance verified → finished
→ receipt built → cleanup certified → REPLAY RECEIPT_VERIFIED
```

Halt taxonomy (fail-closed, statuses copied verbatim into `result.json` by
the same machinery D4 used): `PARTIAL_EXECUTION_EVIDENCE` /
`PHASE_HALTED_PREFIX_PRESERVED` on any mid-phase halt after honest evidence
retention; admission refusals (below) halt **before any mutation**;
`WINDOW_EXHAUSTED` / observation-derived statuses are recorded as
**inconclusive**, never relabeled as success; `verified` flips true only on
the full chain through replay.

### Typed failure modes

| Class | Examples | Behavior |
|---|---|---|
| Admission refusals before mutation | `INVALID_SITE` (missing stop/depot witness/acceptance < 1/8), `NO_ENGINE`, `UNAVAILABLE_ENGINE`, `INSUFFICIENT_FUNDS`, `COST_LIMIT`, `COST_CHANGED` (quote ≠ realized), `PAUSED` | halt, zero-cost, evidence retained |
| Readback discipline | `READBACK_MISMATCH` (correlation/identity/order-set/footprint), `OUT_OF_ORDER` (exchange-state machine) | halt prefix-preserved |
| Observation | `CLOCK_STALLED`, `WINDOW_EXHAUSTED`, wall-deadline expiry | inconclusive; optionally later stops (never a success) |
| Runtime | listener/connection/launch failures, script-log health findings | cleanup still runs and is certified; attempt `FAILED_*` |
| Cleanup | any of the 4 flags false | historical record stays failed, like candidate-3's |

## 5. Security and trust boundaries

- **Operator-only trust anchor:** signing and launching require the exact
  §12 gate; the pinned production anchor
  `cbb63ff5…40c614` (operator identity for E35) verifies the authorized
  record before any write; the seed pipeline is the E35-approved checklist
  (seed extraction never printed/logged/passed as argument; derived key
  equality checked before write; `unset` after).
- **Python owns trust:** identity, canonical bytes, `plan_hash`, deadline
  enforcement, per-op admission (positive tested quote), receipt build and
  replay live in Python; the GameScript bridge executes only scheduled
  synchronous ops and returns readbacks — it cannot mint receipts,
  authorize itself, or persist beyond the isolated workspace.
- **Secrets:** the isolated operational credential is generated inside the
  isolated workspace (`0600`), is never copied into Python records or Git,
  and is removed at cleanup (`credential_removed: true`), with workspace
  disposal certified; the retained `cleanup.json` remains the certificate.
- **Offline ≠ native:** controlled artifacts never count as native proof;
  native claims exist only in consumed-attempt evidence bound by the
  manifest, and only after `replay == RECEIPT_VERIFIED`.
- **Immutability:** candidate bytes are frozen at staging (3,448-entry
  frozen closure over this repository's reviewed files per the D4
  procedure); consumed evidence is never edited; a consumed one-shot claim
  can never be re-used, anywhere, ever.

## 6. Offline and future native test strategy

**Offline (implemented during D5 implementation, before any staging):**

1. Protocol tests: canonical stride, size boundaries (exact 640 passes,
   641 refuses, both directions) on the shared live/replay request transport
   helper, the production 526-byte `site-00` request through outbound
   validation, encoding and replay parsing, malformed/truncated/duplicate-key/
   invalid-UTF-8/double-NUL bodies fail closed, correlation validation,
   route-digest equality and drift refusal, multibyte counting in bytes.
2. admission/verification stub tests: controlled SQVM stub world (pattern:
   `tests/test_corridor_construction.py` build_vm/run_phase) exercising the
   ops sequence above with quote-mismatch refusals, order-set exactness,
   monitor arithmetic (delivered == observed L), quarter income checks,
   and off-by-funds reconciliation refusals.
3. Ceremony tests: staging refusal paths (mixed identity, missing
   prerequisite save, non-empty claim), replay verifier refuse paths on
   tamper-evidence, budget-machine regressions.
4. Regressions: the existing corridor/transport/protocol/planning suites
   must stay green unchanged (no D4 file reverts); retained D4 evidence
   regressions skip-when-absent and never re-launch.

**Future native test (the real evidence, only under §12 authorization):**

the one staged attempt per §3; failure windows produce retained
`frames.json`, per-op evidence, `after-diagnostic.sav` and a failure save
when the world mutates, exactly like D4 candidate-4's honest partial record.

## 7. Required machine-verifiable evidence

A consumed D5 attempt is complete when **all** of the following exist and
hash-verify:

1. `PRELAUNCH.json` + `PRELAUNCH.sha256` (seal digest) over the staged
   candidate, schema `d5-freight-prelaunch-v1`, plan digest
   triple-matched (sealed record / re-derived / docs) and the optimizer
   route digest matched to the plan witness;
2. source-save binding: a copied `session-before.sav` whose sha equals the
   candidate-5 authoritative `after.sav` `a81ac836…ef261` (the world D5
   runs on), plus the frozen closure re-verified by a fresh read-only
   `PREFLIGHT PASS`;
3. signed `AUTHORIZATION.json` payload digest (canonical bytes over the
   candidate's own staged payload) and one-shot `CLAIM.json` consumed with
   `LAUNCH-CONSUMED.json`;
4. `frames.json` plus unique retained request/response pairs for every
   planned exchange (15 planned; ≤32 budget), with persisted response
   files for every exchange (the E32 lesson: never rely on a native log the
   client failed to persist);
5. per-phase evidence: `site` admission bundle (facts as typed records),
   per-op readbacks, load/monitor arithmetic records, `finance` records;
6. `receipt.json` binding `plan` digest + before/after save digests; a
   fresh authoritative `after.sav` distinct from the retained
   `after-diagnostic.sav` (never a substitute);
7. `result.json` (`verified`/`status`/counters verbatim), certified
   `cleanup.json` (4 flags true, return code 0), 90-file-style
   `artifact-manifest.sha256` re-verifiable offline;
8. read-only replay verifier exit 0 with `RECEIPT_VERIFIED` rooted at
   `app.simulation.openttd.proof.corridor_freight_native`;
9. record shapes still compatible with `analyze-native-attempts` (E34):
   same document names, statuses copied verbatim, cleanup fail-closed —
   verified by running the analytics CLI over the staged example and (after
   consumption) the real attempt, byte-identical twice.

The D5 design itself produces **no** E-id; the next free index entry (E36)
is assigned only when a real record exists.

## 8. Budget, packet-size, cleanup, replay, idempotency constraints

- **Requests:** planned 15 in one fixed order (§4); hard cap 32; zero
  retries and zero reconnects enforced; each `request_id` unique forever.
- **Launch:** exactly 1 OpenTTD 15.3 process, exactly 1 X25519 connection,
  welcome identity matched (revision 15.3, seed 17), pid recorded.
- **Wall clock:** 900 s total runtime budget (D4's); per-phase caps:
  `load-watch` ≤ 2048 script ticks / ≤ 30 economy days / ≤ 60 s wall;
  `transit-watch` ≤ 2048 ticks / ≤ 60 s; `deliver-watch` ≤ 2048 ticks /
  ≤ 60 s; polling one script tick per sample with naive-readback clock
  sanity (regression/stall fail-closed; pause-state failure) — the same
  bounds the legacy delivery proof used, which are caps, not promises.
- **Packet sizes:** request ≤ 640 canonical bytes on both the live and
  replay paths; response ≤ 640 by default; frame (3 + body + NUL) ≤ 640 + 4;
  outbound GameScript string ≤ 1450; the shared Admin frame ceiling stays
  32763/32767. The generic version-one transport default remains 512.
- **Cleanup:** same contract as D4 (reap, close both endpoints, workspace
  disposal, credential removal; certified 4/4 true, return 0; endpoints
  individually certified incl. kernel TIME_WAIT-only state); post-run
  isolation re-verified (no process/listener, `isolated/` empty).
- **Replay:** ordered-unique exchange replay, per-op re-verification, exact
  stale/refusal taxonomy; deterministic — two runs byte-identical; a
  partial receipt can never replay as a success label.
- **Idempotency:** `purchase` exactly once (a second buy is `OUT_OF_ORDER`);
  each order appended exactly once and re-read; monitors armed once and
  consumed once; `finish` issued once. No op is retried after a refusal; a
  failed attempt's identity is closed forever like D4's consumed identities.

## 9. Explicit pass/fail acceptance criteria

| # | Criterion | PASS | FAIL |
|---|---|---|---|
| A1 | Staging (offline) | PRELAUNCH seal matches `PRELAUNCH.sha256`; payload digest matches candidate bytes; frozen closure re-verified inside a fresh read-only `PREFLIGHT PASS`; never-consumed state | any seal/freeze identity mismatch refuses staging |
| A2 | Review gate | fresh-context independent review returns PASS (all checks) | any FAIL/PASS-WITH-CONCERNS keeps the candidate unlaunched |
| A3 | Authorization gate | explicit operator authorization record covers signing + exactly one attempt | no authorization record → PENDING_AUTHORIZATION forever |
| A4 | Site admission (native) | all §4 `site` facts hold; funds £492,149 | any fact fails → zero-mutation halt |
| A5 | Engine/purchase | one admitted engine; tested quote > 0 equals realized price ≤ £2,000; exactly one purchase | quote mismatch/second purchase/order violation |
| A6 | Order set | exactly `[pickup OF_FULL_LOAD, delivery OF_NO_LOAD]`, both goto-station | any extra/missing/mistyped order |
| A7 | Loading | observed full load `L > 0`; vehicle-full state; waiting decrement consistent | no load within window → `WINDOW_EXHAUSTED` (inconclusive, not passed) |
| A8 | Delivery | monitor pickup & delivery amounts == L; vehicle empty after unload; accepted-cargo/income increase in the same quarter with corroboration | any mismatch → halt, no receipt |
| A9 | Finance | every per-exchange funds delta reconciles exactly; purchase recorded at quote | any unexplained delta |
| A10 | Evidence | §7 items 1–8 all present and re-verified; replay `RECEIPT_VERIFIED` (exit 0) | missing piece → `verified: false`, no label |
| A11 | Cleanup | 4/4 flags true, rc 0, endpoints certified, workspace absent | any false → historical `FAILED_CLEANUP` preserved |
| A12 | Preservation | D2/D3/D4 evidence byte-unchanged (candidate-5 manifest 90/90, candidate-4 80/80 re-verified); analytics over the attempt byte-identical twice; all matrix status vocabulary (PROVEN/CONTROLLED/PREPARED/PARTIAL/FAILED/UNKNOWN) intact | any tamper |

Only when A1–A12 all pass does the matrix line "D5 corridor freight cycle"
become PROVEN for exactly the staged D5 scope. Any partial result keeps the
D5 milestone PARTIAL/FAILED and states precisely which criteria were not
met. Full OPEX/net-profit/ROI remain **UNKNOWN** regardless of outcome
(D5-M6 records observed costs and income only).

## 10. Risks, assumptions, fallback behavior

| Risk | Likelihood/effect | Fallback |
|---|---|---|
| Industry 0's cargo-1 production too slow: waiting stays 0 ⇒ no full load within the window | medium; attempt ends `WINDOW_EXHAUSTED` (inconclusive), funds −price only | close the attempt with retained evidence; analysis; a follow-up D5 design may carry longer windows or an operator-approved production decision — never a silent retry |
| Delivery-stop acceptance below 1/8 natively (census measured 0 pre-construction) | low-medium; admission refuses before mutation | typed `INVALID_SITE`; no order, no purchase; the acceptance fact will then be the design finding of record |
| No compatible engine exists in this world | low; `NO_ENGINE` refusal | close attempt; policy review offline |
| Vehicle cannot route the built road (e.g. one-way/slope nuance invisible to construction) | low-medium; `INVALID_ROUTE`/`RUN_FAILED` at transit | halt with witness + path frames; the corridor validator gains a defect-finding record |
| Price changed by world state at purchase (inflation/settings) | low; `COST_CHANGED` | refuse; quote health check offline first |
| Response bound exceeded by a D5 readback | low; encoding refuses before send | shrink that readback, or give it a named larger constant (640 precedent), then a fresh review gate |
| Native scene differs from controlled stub semantics (15.3 API drift) | low on this pinned runtime | controlled tests + documented 15.3 API pins; staged but unlaunched candidate until review clears |
| Full-load order leaves the vehicle at the delivery station cycling after D5 ends | expected world behavior | documented; the `finish` op stops the vehicle (owned, not sold); no further authority implied |

Assumptions: the candidate-5 `after.sav` loads on the staged runtime
(verified for candidate-5 itself, same machinery); GSCargoMonitor semantics
match the legacy proof's 15.3 findings (same engine, same API family);
company 0 funds are £492,149 exactly as E35 recorded (re-read natively at
`site`, refused if not).

Fallback behavior everywhere: fail-closed halts with evidence preserved,
cleanup always attempted and certified, no relabeling, no identity reuse,
and forward-path conclusions written only as new dated records.

## 11. Dependency-ordered implementation tasks and critical path

All T1–T8 are offline. T9/T10 are future gates inside the D5 implementation
task, executed only under their own explicit operator authorization:

| # | Task | Depends on | Output |
|---|---|---|---|
| T1 | Protocol-5 contracts in `corridor_freight.py` (§4) + focused tests | — | typed request/readback/plan, bound constants |
| T2 | `d5_freight_package` GameScript (port lifecycle + delivery kernels, bind D4 geometry) | T1 | staged package bytes |
| T3 | Receipt/verify/replay offline functions (D4 helpers by import) | T1 | verifier skeleton, deterministic outputs |
| T4 | Ceremony module `corridor_freight_native.py` (schedule, admission, run-per-phase, cleanup wiring) | T1–T3 | staging + run + replay commands |
| T5 | Controlled/retained/regression suites (§6) all green; ruff/py_compile/`git diff --check` | T4 | 129+ regressions intact, new counts recorded |
| T6 | Preparation guide + spec docs (`docs/d5-corridor-freight-…`), task-list/matrix planning rows | T5 | documentation set |
| T7 | **Gate: independent fresh-context review (read-only, PASS)** | T6 | review record |
| T8 | Staging per D4 procedure (one identity constant in T4's module; frozen closure; PREFLIGHT PASS) | T7 | candidate `-candidate-1` PENDING_AUTHORIZATION |
| T9 | **Gate: explicit operator authorization** (signing + exactly one attempt) | T8 | signed AUTHORIZATION.json |
| T10 | The one native attempt (§3/§9) | T9 | result per §7 |
| T11 | Outcome records: handoff outcome, matrix/EVIDENCE_INDEX E-entry, TASKS, analytics run, close-out | T10 | evidence rows E36+… |
| T12 | Later: P05 optimizer wiring + planning-vs-execution analytics on real facts | T11 separate design | out of this milestone |

Critical path: T1 → T4 → T5 → T7 → T8 → T9 → T10 → T11. The plan mirrors
D4's proven chain: contracts → package → ceremony → tests → review →
staging → authorization → one attempt → records.

## 12. Future independent-review and explicit-authorization gates

1. **Gate A — independent review (mandatory):** after T6, a fresh-context,
   read-only reviewer receives the diff set plus this design and the D4
   outcome record; verdict PASS only if the design's typed invariants,
   budget caps, test coverage and staging procedure hold. No PASS ⇒ no
   staging.
2. **Gate B — preflight:** only after Gate A, stage the candidate and run
   `PRELAUNCH` + read-only `PREFLIGHT` per the D4 procedure; the never-
   consumed precondition and the frozen-closure re-hash bind the current
   source bytes to the reviewed ones.
3. **Gate C — explicit operator authorization (mandatory, separate):** a
   dedicated authorization message must cover (a) signing the staged
   candidate and (b) exactly one native attempt. Nothing in this design,
   the task list, any vault note or any prior authorization grants it; the
   E35 anchor proving machinery applies unchanged, with the seed-handling
   checklist and `unset`-after-sign discipline.
4. **Gate D — outcome discipline:** after the attempt, all records are
   written from retained bytes only; statuses copied verbatim; no receipt,
   verified label, success metric, capture or replay assertion is created
   except by the replay verifier; partial and inconclusive outcomes stay
   partial and inconclusive; OPEX/net-profit/ROI stay UNKNOWN until a
   separately designed accounting event proves them.

## Appendix: status vocabulary carried forward, D5 edition

- `PROVEN` — only what a consumed D5 attempt's retained bytes plus a
  passing replay verifier establish (`RECEIPT_VERIFIED`), scoped to §9.
- `CONTROLLED` — the offline contracts, optimizer route selection and tests
  in T1–T5; currently **CONTROLLED (offline)** in the preparation record.
- `PREPARED` — the D5 work items in §11 before T7.
- `PARTIAL` / `FAILED` — any halt taxonomy state in §4, preserved exactly.
- `UNKNOWN` — full OPEX, net profit, ROI, sustained-network economics,
  and any fact a D5 attempt does not and cannot establish.
