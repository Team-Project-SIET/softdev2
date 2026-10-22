> Handoff status, 2026-10-17: retained native create Q3 and fresh-process reload-only
> Q3 are PROVEN. Earlier preparation/pending statements below are historical.
> Reload-only proves no fourth-vehicle purchase, dispatch or unpause. Read the
> [current handoff](../AI_HANDOFF.md) and evidence index before continuing.

# One additional freight vehicle: controlled preparation

Attempt 19 remains FAILED; separately verified offline evidence supplies the baseline.
No launch or Admin connection is authorized. No native Attempt 20 seal is prepared.

P07's 60 monthly endpoints show mean source queues S1 459.72, S2 651.42,
S3 557.10 cargo. These are sampled means, not continuous queue integrals.
S2 and S3 each delivered 980 cargo in 1,826 economy days. Full 20-unit
batches and persistent queues justify testing extra capacity, but do not prove
that fleet size causes the bottleneck. S2 is the first test candidate because
it has the larger sampled monthly queue; revenue by service remains UNKNOWN.

| Arm | S1 vehicles | S2 vehicles | S3 vehicles | P05 CAPEX estimate |
|---|---:|---:|---:|---:|
| A | 1 | 1 | 1 | £25,607 |
| B | 1 | 2 | 1 | £30,036 |
| C | 1 | 1 | 2 | £30,036 |

These controlled plans validate against retained P08 resource, supply and budget
inputs. Original cargo demand stays at 20 per service. Opt-in P05
`minimum_vehicles_by_demand` explicitly requires the fleet allocation and original
services; increasing the fleet limit alone would not do that. Empty allocations
preserve existing serialization, canonical identities and optimizer behavior.
The comparison rejects changed route geometry/infrastructure. P05 still models
one trip per vehicle; it predicts neither annual throughput nor headways.

An additional observed engine cost £4,429 historically. Its sampled annual
running-cost rate is £421, which is not a measured expense. Future purchase
quotes, actual incremental operating expenses, per-service revenue, profit and
ROI are UNKNOWN. Baseline observed CAPEX £28,459 differs from P05's estimate;
do not treat the full-plan estimate as a native upgrade quote.

Freeze hashes of scenario, original execution plan, source archive, snapshots,
receipts and result before any later preparation. Keep the same qualified
initial save (never the final save), world/cargo, original route/order flags, funding/loan policy,
construction/start timing, timekeeping, 1,826-day horizon and telemetry cadence.
A fresh matched A is necessary: historical Attempt 19 is contextual evidence,
not an equivalent fresh control for a future treatment. Keep the historical
`frozen-source.zip` immutable; stage the same newly telemetry-enabled bridge
archive for every future arm and record its separate hash. Verify a common
paused purchase/dispatch boundary before measuring each arm.

Success requires higher target and network delivered cargo and network revenue
than matched A, with exact annual deltas and no implied per-service revenue.
Report extra command-local CAPEX, observed cash/expense changes and every
unexplained residual. Compare queue samples, bounded arrival/departure and
loading/unloading intervals, carried cargo and completed deliveries; censored
or inferred events must retain their classification. A positive revenue delta
alone cannot establish profit. No numeric improvement is forecast.

Native readiness remains BLOCKED by the canonical fleet save and verified reload
described below. Fourth-vehicle execution/receipt binding and integrated telemetry
are implemented and controlled-tested; they have not run natively.

## Fourth-vehicle execution and receipts

The existing continuous GameScript accepts one explicit `capacity-add` intervention
on service 0, 1 or 2, followed by an independent `capacity-read`. No route or station
is added. The bounded sequence tests and executes vehicle purchase, two fixed
orders and start, checking ownership, engine, exact cargo capacity, vehicle count
and preservation of the original three vehicles. Partial mutation retains its
physical vehicle ID, completed command ledger and raw response; it is never retried
or accepted as a complete receipt.

`freight_native_network.execute_capacity_intervention` uses the existing secure
exchange, records separate purchase CAPEX and binds the new physical vehicle to
the original logical service. Original `service-receipt-N.json` files remain
immutable. `capacity-receipt.json` binds the intervention responses and timing;
offline replay reconstructs the multi-vehicle service and verifies exact secure
command/readback bytes, uniqueness and ordering. Purchase CAPEX is counted once.

The purchase requires a verified paused boundary and fixed-vehicle policy. The
future matched loader must supply that boundary, verify effective command-pause
settings, and coordinate unpause before continuous operation. The current fresh
world launcher does not acquire a matched boundary; preflight refuses explicit
capacity experiment metadata for every arm. Do not bypass it by editing PRELAUNCH.

## Exact matched-state prerequisite

`inspect_capacity_source` verifies retained save/link hashes without claiming
loaded-world correspondence. Attempt 19's `before.sav` and `qualified.sav` precede
construction; `after.sav` and `failure.sav` follow operation. None is a retained
paused post-construction/pre-intervention save containing the original three
vehicles. Existing byte-clone preparation explicitly remains `NOT_RELOADED`.

Missing prerequisite: acquire and verify one canonical constructed-fleet save,
plus a reload path preserving GameScript logical/physical bindings and matching
native map, industries/production, infrastructure, orders, company, finances,
economy date, timekeeping and fixed-vehicle policy. This cannot be established
offline from the retained saves. `validate_capacity_branches` rejects unequal
proposed A/B/C states and shared identities; equality alone is not native proof.
No new experiment identity or Attempt 20 seal is prepared until these checks pass.

Use the existing P07 analyze-continuous-freight CLI with the opt-in
`--prepare-capacity-experiment` flag (see README); its JSON includes the exact
service/demand mapping, scenario/plan hashes, controlled plans and blockers.
The standalone Python API is
`app.experiments.capacity_experiment.prepare_capacity_experiment(attempt, p07)`.

The next native step is separately authorized canonical save/reload qualification,
followed by independently authorized fresh A and B runs. C stays available as an
alternative. No authorization is shared between acquisition, A, B or C.

## Canonical qualification preparation, 2026-10-15

Status: CANONICAL QUALIFICATION DRIVERS READY. The dedicated `proof.canonical_fleet`
driver reuses the existing native backend, secure session, planning, console saves
and owned cleanup. The ordinary freight launcher still admits fresh worlds only;
its matched-capacity preflight block remains in force.
There were zero native launches and zero Admin connections during preparation.
Attempt 20 remains unused. Five-year monitoring is outside this qualification.

The canonical state has three completed original services, exactly three owned
vehicles stopped empty in their original depots, and their original two station
orders. Station identities, owners, cargo, queues, route tiles, depot ownership,
industry production, company cash and loan must have independent native readback.
Auto-renew is disabled. Record both economy and calendar dates, their fractional
positions, and the timekeeping mode. No delivery or movement is permitted before
common dispatch, including during construction. Acquisition executes stages 0 through
8, independently reads each stage and seals each service without stage 9's start.
The qualification GameScript rejects that start command and retains command logs.

The continuous bridge now supplies versioned `Save()` and `Load(version, data)`
callbacks. Constructed checkpoints persist the three logical service records,
physical vehicle IDs, active service, replay maps, request counters and funding
state as basic value trees. Reload skips world reconstruction. Partial or operated
checkpoints remain saveable for diagnostics but cannot resume as constructed fleets.
This is controlled persistence coverage, not native reload proof. Native cargo
monitor state must be independently checked or initialized identically before
dispatch; its preservation is not established by serializing bridge fields.

The existing owned-console `save` helper waits for the unique save-completion log
and hashes the resulting `.sav`. OpenTTD's console appends `.sav` itself. GameScript
data is stored inside that save. The reload driver must load those exact bytes in
a new owned process, with the same runtime, content, effective settings and bridge.
No callback may reconstruct stations or vehicles to hide missing state.

`freight_canonical.py` defines offline observations and exact correspondence.
Its integrity seal binds the save and raw readback SHA-256 values and exclusively
creates the provenance file. It rejects changed dates, bindings, positions,
finances, cargo and infrastructure. Only qualification identity, script tick and
raw readback digest may differ across observations. Wall-clock timestamps, request
IDs, process IDs and log offsets belong outside semantic state. Schema acceptance
and matching caller-supplied records cannot establish native completeness.
The implemented collector enumerates all map tiles, six owned stations, industries,
their cargo, three vehicle bindings, native orders and persisted service plan IDs.
It checks complete coverage, owned depots and connected road paths. The existing
OpenTTDLab save parser supplies exact native calendar/economy dates and fractions,
calendar subfraction and world tick counter from bounded paused snapshots.
`collect_canonical` fixes the pre-intervention fleet at three stopped originals;
`verify_intervention_snapshot` permits only the receipted extra vehicle, its CAPEX
cash delta and the explicit original start flags. It checks the full remaining state.
Keep the save, raw transcripts, command logs, bridge archive, effective configuration,
content identities, provenance and any partial failure diagnostics together.

Two separately authorized launches are required, using these distinct proposed
qualification identities. They are not native seals or consumed attempts.

1. `canonical-fleet-create-q3`: construct without dispatch, verify all three stopped
   vehicles and empty loads, pause, independently read the full boundary, save once,
   read it again and reject any semantic drift. Freeze the save and provenance.
   Stop and clean up the owned process. Retain failure saves and logs on any failure.
2. `canonical-fleet-reload-q3`: verify the frozen bytes before one fresh launch.
   Keep the loaded world paused before its first vehicle or economy tick. Independently
   read the full state and compare it with stage 1. Verify paused heartbeat, persist
   correspondence evidence and stop with controlled cleanup. No additional purchase,
   dispatch or unpause is reachable in this reload-only stage.

Paused purchase is not yet native-qualified. OpenTTD 15.3
[runs GameScript while world simulation is paused](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/openttd.cpp#L1127-L1140).
Its [command-pause policy](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/command.cpp#L132-L148)
permits vehicle construction at `NoLandscaping` or `AllActions`. This source-level
permission does not establish that the packaged purchase, order and start sequence
completes while paused in the target runtime. Record the effective setting and
require native test, execution and independent readback without advancing world time.
Never unpause merely to make purchase succeed.

After qualification, fresh A and B each load the frozen canonical save under separate
authorization. Verify exact correspondence before intervention. A adds nothing;
B adds only its S2 vehicle and the existing two orders. Record its command-local
CAPEX and exact cash delta. Reject changes to the original three vehicles, route,
orders, funding, date or cargo. Start all original vehicles under pause in the same
service order, verify no physical movement, then unpause once for common dispatch.
B's fourth vehicle may already have its start flag set by the existing intervention,
but must remain physically stationary until that unpause. Prove these conditions
before claiming a matched experiment. No A or B run is authorized by this document.

`dispatch_loaded_arm` supplies concrete snapshot/save verification and native
unpause acknowledgement to `dispatch_common`. Both arms require the same canonical
save, bridge, runtime and gameplay configuration before intervention. Only network
game/admin ports differ in the normalized configuration identity. Public transport
keys are independently frozen in each isolated workspace. A paused script heartbeat
must advance while semantic world time stays fixed. Missing acknowledgements,
restricted construction or any unexplained drift fail the stage without retry.

Prepare and preflight stage 1 without launch:

```bash
.venv/bin/python -m app.simulation.openttd.proof.canonical_fleet prepare \
  artifacts/runtime/canonical-fleet-create-q3 --stage canonical-fleet-create-q3
```

Only after separate explicit authorization, the stage 1 launch command is:

```bash
.venv/bin/python -m app.simulation.openttd.proof.canonical_fleet create \
  artifacts/runtime/canonical-fleet-create-q3 --authorize-one-launch
```

After reviewing successful creation evidence and cleanup, prepare stage 2:

```bash
.venv/bin/python -m app.simulation.openttd.proof.canonical_fleet prepare \
  artifacts/runtime/canonical-fleet-reload-q3 --stage canonical-fleet-reload-q3 \
  --canonical artifacts/runtime/canonical-fleet-create-q3
```

Only after its own separate explicit authorization, the stage 2 launch command is:

```bash
.venv/bin/python -m app.simulation.openttd.proof.canonical_fleet reload \
  artifacts/runtime/canonical-fleet-reload-q3 --authorize-one-launch
```

Stage 2 proves reload correspondence only, without purchase, dispatch, unpause or
monitoring. Paused purchase requires a later separate qualification. A consumed stage cannot
be relaunched. Stage 2 preparation rejects missing creation results, claims, raw
readbacks, cleanup or source integrity. Both launch commands require explicit flags
and their independently sealed identities. Do not reuse historical final saves.

The preceding persistence preparation passed 226 controlled tests across canonical correspondence/persistence,
capacity execution/transport/monitoring, matched state, continuous operation,
cleanup ownership, scenario funding, packaged native-network validation and
freight-delivery regression suites. The 30 new canonical tests also passed
independently. Ruff check, Ruff format check and `git diff --check` passed.
Focused diagnosis reproduced lost bindings before correction. Independent parent
review caught and verified a correction for diagnostic saves without scenario funding.
No native claim follows from these results.

Before Q1, the completed drivers passed 298 focused tests, including packaged GameScript
execution, acquisition/save bracketing, reload/persistence, native collector
coverage, paused restrictions, dispatch, receipt regressions and cleanup failures.
Ruff, formatting, focused runtime typecheck and `git diff --check` pass.
Independent integration review reproduced and corrected duplicate verifier arguments
and evidence-write failures that could interrupt cleanup. Q1 subsequently failed as
recorded below; fresh reload and paused purchase remain unperformed.

## Q1 failure and Q2 repair

`canonical-fleet-create-q1` is consumed and immutable. Its one launch failed before
Admin connection or service construction. `PrepareDemo` called the parent through
closure `.call`, adding a native VM frame. OpenTTD 15.3 then rejected the first
`GSIndustryType.BuildIndustry` as non-suspendable. No canonical save was created.
The relative diagnostic filename was resolved by native `SAVE_DIR`, causing the
separate `File not writable` error. Q1's original result, logs and archive stay intact.

The corrected bridge assigns inherited command-bearing methods to instance slots
and invokes those slots directly. This preserves the receiver and initialization
order without closure `.call`'s native frame. The same correction covers canonical
construction and command handling. Read-only `Save`, vehicle-count and construction
logging delegates keep their existing invocation. No global replacement is applied.

The save helper sends an absolute, quoted filename without `.sav`; native `ConSave`
adds that suffix. The helper restricts the target to the authorized artifact directory
and rejects traversal, aliases, symlinks and existing targets. Success requires a fresh,
exact native acknowledgement, a nonempty regular file and verified SHA-256. Diagnostic
saves check process liveness while tolerating the already-recorded script failure.
Fresh save errors still fail, and the original startup exception remains separate.

The standalone runner uses OpenTTD 15.3's unmodified embedded Squirrel sources at
commit `14ec60f248547d4d062a1160f0fc26d742319888`. It executes the packaged startup
with controlled game API peers, actual `sq_can_suspend`, suspension and callback-result
resumption. It checks receiver binding, completion order, command failures and errors.
The Q1 invocation and adjacent command-wrapper regressions must fail in that same VM.
This validates VM execution context; it does not prove native industry construction.

Run the VM check with an exact, clean OpenTTD 15.3 source checkout:

```bash
PYTHONPATH=. .venv/bin/python tests/validate_canonical_squirrel.py \
  --source /tmp/canonical-squirrel-15.3 \
  --report artifacts/validation/canonical-fleet-create-q2/suspension.json
```

The report destination must be fresh. Q2 preparation freezes the report, helper
sources and exact staged-package correspondence in its provenance. The commands
above prepare Q2 only. Its native launch still needs separate explicit authorization.
Do not retry Q1, run reload, or consume Attempt 20 during this repair.

## Bounded telemetry

`freight_telemetry.telemetry_request(request_id, service, vehicle)` prepares a
read-only `continuous-telemetry` request. Service indices 0/1/2 correspond to
P07 S1/S2/S3. The producer validates ownership, engine, cargo capacity and fixed
orders and has a separate 20,000-request lifetime budget. Each JSON reply is
bounded to 1,450 bytes by `decode_telemetry`; `SampleWindow` caps each stream at
20,000 samples and suppresses transition inference across its configured tick gap.
These bounds are controlled-tested, not qualified native collection.

| Metric | Measurement boundary |
|---|---|
| Tick, economy date, tile, state, speed, load, capacity, source queue | Direct point samples |
| Stopped in depot, at station | Direct sampled predicates; neither establishes servicing or idle duration |
| Departure, arrival, loading, unloading | Possible transitions bracketed between samples |
| Cargo carried and frequency | Last source load, observed net unload delta and censored candidate-cycle rate |
| Exact event times, completed cycles, avoidable idle, servicing duration | UNKNOWN |

Do not sum repeated service queue or industry-delivery counters across vehicles.
The industry monitor remains service-level; it cannot attribute delivery to the
new vehicle independently. Exact completed delivery frequency requires additional
native observation, not relabeling sampled candidate cycles.

The existing monitor now issues these requests when explicitly configured. Version
2 `capacity_telemetry` seals vehicle count and maximum tick gap; physical IDs are
derived from independently replayed runtime receipts rather than predicted before
purchase. Per-vehicle profit and running-cost rate are sampled alongside location,
load and queues. Three logical service delivery counters and network finance stay
separate from the three or four vehicle streams. Extra vehicles never duplicate
service deliveries or network revenue.

Raw exchanges, telemetry JSONL, snapshot references and derived summaries replay
together. The same secure session uses bounded request/frame budgets, at most
3,601 samples per vehicle, 64 MiB artifact/frame limits and existing deadlines
and log limits; exhaustion fails closed. Samples are OBSERVED, transitions and
censored candidate cycles DERIVED, unsupported durations/frequency UNKNOWN.
Run fresh matched A with the same telemetry-enabled bridge as B and C. Preserve
the original archive and freeze identical new bridge bytes across arms. Each arm
requires its own authorization; C remains optional. Do not treat historical
Attempt 19 as matched A.

```bash
.venv/bin/pytest -q tests/test_freight_capacity_execution.py \
  tests/test_freight_capacity_transport.py tests/test_freight_capacity_monitor.py \
  tests/test_freight_matched_state.py tests/test_freight_continuous.py
```

Q2 repair verification completed with 352 focused tests passing, including packaged
GameScript execution, save-path failures, canonical construction, correspondence,
receipts and cleanup. Ruff, formatting, focused typecheck and diff whitespace checks
passed. Independent Codex review reran all seven exact-VM cases; the resulting report
matched the preserved report byte for byte, including package and helper hashes.
The interrupted pytest exit 1 was reproduced as a minimal capacity-test parent peer
missing `PrepareDemo`, required by the eager method alias. The real parent defines it;
the peer now defines a fail-loud method. No production change was needed for that failure.
Q1's original archive, prelaunch digest and evidence manifest remain unchanged.
Repair validation launched no OpenTTD process and opened no Admin connection.
Q2 preparation freezes inputs only; construction and diagnostic saving still need
separately authorized native qualification.


## Q2 failure and Q3 selection protocol repair

`canonical-fleet-create-q2` is consumed and immutable. Its one native launch and
one encrypted Admin connection completed startup and world preparation, then failed
on `select-1` with `CANONICAL_UNSEALED_SERVICE`. The first selection created service 0
at stage 0 and acknowledged it. Python's first loop immediately selected service 1;
its second loop would have built and sealed services afterward. GameScript correctly
required every previous selection to be sealed at stage 10. There was no intervening
build, seal or suspension. This was a driver/bridge contract mismatch, not lost state.
No service vehicle was constructed. The subsequent transport timeout obscured the
fatal in the original result; retained stderr and request/response artifacts preserve it.

The corrected acquisition order is one selection, independent activation read,
stages 0 through 8 with readbacks, then an explicit correlated `canonical-seal`
acknowledgement, before the next service selection. Services keep indices 0/1/2;
sealing advances stage 9 to 10 without dispatch. Missing, duplicate, wrong-service
or partial seals remain invalid. Canonical selection admits only the already sealed,
stopped original fleet; ordinary freight keeps its existing empty-fleet policy.
Native fatal reporting preserves the explicit GameScript reason as primary and
retains a stalled exchange's timeout separately, with request correlation evidence.

Q2's diagnostic save succeeded through the absolute-path workflow. Its SHA-256 is
`61704c8fee07e0630afa51968a7c8f04d7dd1e3a4ff6e0338fee2d899f344735`.
It is a failure diagnostic, not a canonical constructed-fleet save. Q1/Q2 evidence
must remain unchanged. Q3 uses a new VM report under
`artifacts/validation/canonical-fleet-create-q3/suspension.json` and the fresh
`canonical-fleet-create-q3` identity. Preparation permits no native launch or Admin
connection; Q3 creation still requires separate explicit authorization.

Q3 repair validation: 365 focused tests passed, covering canonical construction,
persistence/correspondence, original freight receipts/offline replay, safe saves and
cleanup. Ruff, formatting, focused typecheck and whitespace checks passed. Independent
Codex review checked both corrections and reran a clean exact-15.3 standalone VM build:
all 19 cases passed, including the complete three-service protocol with 33 native peer
suspend/resume commands. Old ordering, old empty-fleet admission, invalid/duplicate/
missing seals, wrong build order and partial mutations are rejected. The report pins
the exact packaged source and helper hashes. Controlled API peers validate VM/protocol
behavior, not native construction or reload. Q1/Q2 full artifact hashes are verified
unchanged before and after Q3 preparation. Q3 remains unconsumed.


## Reload Q1 road-context failure and reload Q2 repair

Creation Q3 is PROVEN; its protected canonical save SHA-256 remains
`51e45689ae40dfa53c2cc150a05076fcb6e5cc2f38ec4eff56908372ab1297eb`.
Reload Q1 is consumed and FAILED. Its one process and encrypted connection restored
service bindings, stopped empty vehicles 4/5/6, orders, cash, loan and exact clocks.
Collection rejected depot classification before full correspondence or any purchase.

Offline replay reproduces the depot-ownership invariant failure. All serialized map
arrays in Q3's save and Q1's reload snapshot are byte-identical. Depot tiles
2709/1557/404 retain tile type ROAD, road subtype DEPOT and owner 0. Vehicle locations,
orders and service depot bindings agree. The error is process-local API context:
15.3 ScriptStorage initializes road_type to INVALID_ROADTYPE; ScriptRoad's depot
and connectivity predicates require an available current type. Construction sets
road type 0; restored startup skips construction, and the page collector does not
initialize that context. Q1 did not directly record GetCurrentRoadType; the source
trace and controlled VM reproduction establish the missing initialization path.

Reload Q2 explicitly initializes context before its readback save and collector,
using the existing frozen bridge's `activate-reload-context` read for service 0.
That handler selects ROADTYPE_ROAD in company 0 mode, verifies current type and
availability, and returns an owned-route snapshot. Python checks the exact source
plan, sealed stage, paused date/cash, vehicle, capacity, orders, speed/load and route
flags before proceeding. Strict depot ownership, connectivity and full semantic
comparison remain unchanged. No depot flags are fabricated or ignored.
The existing company-mode scope restores its caller; road type 0 intentionally
remains selected for subsequent pages. Active service selection and request counters
are process-local routing metadata; the original physical/logical bindings and world
state must not change. No command builds, dispatches or unpauses vehicles.

The GameScript package is byte-identical to Q3, preserving its original bridge hash
and exact package equality in correspondence. Only Python orchestration and VM API
peers/tests change. The new report is
`artifacts/validation/canonical-fleet-reload-q2/suspension.json`.
Read-only API peers model 15.3's road-type predicates; the exact 15.3 standalone VM
executes packaged Save/Load, activation reads and collector pages for same-world,
uninitialized reload, wrong-type, corrected-type and unavailable-type cases.
This is offline protocol validation, not fresh native reload proof.
Reload Q2 requires its own separate native-launch authorization. Q1 cannot be reused.

Reload Q2 offline validation: 387 focused regressions passed (386-suite plus the new
consumed-reload guard), with the final 41 driver/context cases rerun independently.
Ruff, formatting, runtime typecheck and whitespace checks passed. Independent Codex
review verified the initializer and source correspondence. A clean exact-15.3 VM
build passed all 25 cases, including the old-context failure and corrected same-world/
restored collection. VM report hashes match the actual packaged source and helpers.
All creation Q1/Q2/Q3 and reload Q1 evidence must remain byte-identical after preparation.
The new qualification remains unconsumed; no native launch or Admin connection was
performed during diagnosis, correction or preparation.


## Reload Q3: explicit reload-only qualification

Reload Q2 remains frozen and UNCONSUMED. Its native launch was blocked in prelaunch
review, with zero launches and Admin connections: its archived driver unconditionally
called `qualify_purchase` after `verify_reloaded`. It cannot satisfy a no-purchase
contract and must not be modified, resealed or silently executed under another policy.

The new `canonical-fleet-reload-q3` identity seals an exact `reload-only` execution
contract: purchase=false, dispatch=false, unpause=false, exact semantic correspondence
and paused heartbeat before/after collection. Preflight rejects a missing, altered or
expanded contract. The reload branch has no call to purchase, dispatch or unpause and
no option to enable them. The standalone paused-purchase implementation remains for
later separately prepared and authorized work; it is unreachable from this branch.

The sequence loads the exact protected Q3 save, establishes Road Type 0 through the
existing read-only handler, records a restored-originals boundary, creates a paused
readback snapshot, collects and compares the complete native state, then verifies a
second boundary. GameScript ticks must advance while original bindings, positions,
loads, finances and economy date stay fixed. Strict date fractions/world tick and all
map, cargo, infrastructure and order checks remain in the semantic collector.

Success writes `reload-observation.json` and a hashed `reload-correspondence.json`
receipt with both boundary acknowledgements. Native request/response transcripts and
save clocks remain retained. The result is `CANONICAL_RELOAD_ONLY_VERIFIED` only when
correspondence succeeds; evidence or cleanup failures override that result. Existing
cleanup closes the one connection, reaps the process, verifies closed endpoints and
removes credentials/workspace. Failed correspondence stops before further boundary
work, retaining diagnostic saves when possible; it never continues into a purchase.

All historical artifacts, including Q2's unconsumed workspace, remain unchanged.
Q3 uses the same Q3 canonical save and identical GameScript package; no bridge-identity
exception or relaxed world comparison is introduced. Its packaged VM validation is
`artifacts/validation/canonical-fleet-reload-q3/suspension.json`. Preparation authorizes
zero native launches or Admin connections. Native Reload Q3 needs separate explicit
authorization after independent preflight.

Reload-only Q3 validation: 402 focused regressions and 25 clean exact-15.3 packaged
VM cases passed. Ruff, formatting, focused typecheck and diff whitespace checks passed.
Independent Codex review verified the new boundary, receipts, strict comparisons and
cleanup paths. The same full-run tripwire fails on frozen Q2's successful-correspondence
path, proving it catches the original purchase continuation; it passes on Q3. Missing
or modified no-purchase contracts fail before runtime. Failure paths stop without
purchase, dispatch or unpause. The exact Q3 GameScript package remains unchanged.
