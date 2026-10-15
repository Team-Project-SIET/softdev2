# First native freight delivery: bounded proof

This proof extends the verified OpenTTD 15.3 road/vehicle lifecycle without P08/P05
inputs. Its disposable source is the infrastructure proof's `before.sav`: a native
company-owned world with no fleet. The infrastructure and vehicle Attempt 2
receipts bind the lineage. Historical saves, packages and receipts remain intact.

`freight_delivery_package` reuses byte-identical infrastructure and vehicle bridge
code. Python owns immutable policy/plan identities, encrypted transport, deadlines,
receipt replay and cleanup. The new handler admits one native producer/acceptor
relationship for an available non-articulated engine's default cargo. Positive
last-month production is supply evidence; acceptance is a capability. Truck-stop
catchment, vacant flat unowned route footprint, native test-mode costs, company
funds and native fleet capacity are admitted before mutation. No simulated planning
values enter the native runner.

At most 32 engines, 32 industries per cargo side and 64 layouts are examined. The
single L-shaped footprint has at most 48 road tiles, two bay truck stops and one
depot. Ten mutation requests build two route segments and a depot entrance spur, two stops, a depot, one
vehicle, two station orders and start the vehicle. Every stage has a separate
readback; the complete owned topology is required before purchase. Native costs
must match command accounting. Running expenses are never called delivery revenue.

## Delivery evidence contract

Readbacks must show source station cargo waiting, a full vehicle at the source,
loaded arrival at the destination, and an empty vehicle after unloading. Orders
are source `OF_FULL_LOAD` and destination `OF_NO_LOAD`, with no transfer. Native
industry-specific pickup and delivery monitors are armed immediately before start
and consumed once at completion. Both amounts and the company's accepted-cargo
increase must exactly equal the observed full load. Recurring company income and
vehicle profit must increase within the same economy quarter. The destination's
last-accepted date corroborates the event. A command acknowledgement, station
allocation, movement, an empty vehicle alone or ordinary cash changes cannot pass.

Tagged OpenTTD 15.3 authority:

- [Cargo monitor API](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_cargomonitor.hpp)
  and [implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_cargomonitor.cpp):
  reading starts/retains monitoring with `keep_monitoring=true`; reading with false
  stops it. Industry pickup attribution is counted upon final delivery, so it
  cannot replace independent physical loading readback.
- [Economy implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/economy.cpp):
  final acceptance records industry delivery and originating-industry pickup;
  final delivery pays the company and vehicle. Transfers do not establish payment.
- [Vehicle API](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_vehicle.hpp),
  [station API](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_station.hpp),
  [industry API](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.hpp),
  [company implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_company.cpp)
  supply cargo, ownership, order/state and actual recurring-income readbacks.

## Observation and runtime bounds

Each of four phases permits 2048 elapsed script ticks, at most 2049 samples,
one-tick polling, 30 elapsed economy days and a 60-second wall deadline. The whole
run has a 180-second deadline. These are operational caps, allowing substantially
more observation than the 256-tick departure proof; they do not guarantee a full
load or delivery on every route. Economy time is read from `GSDate` rather than
inferred from script sleeps. Pause, stalled/regressing tick, changed topology,
vehicle/order mismatch or economy-quarter rollover fails closed. Exhaustion is
inconclusive, never evidence of path blockage. One process, one secure connection,
zero retries/reconnects, at most 26 requests, 512-byte responses and the 1450-byte
GSAdmin ceiling apply.

The immutable prelaunch freezes policy, source/runtime/package hashes, predecessor,
exact command, budgets and cleanup. Native site admission is deliberately separate:
it can occur only after loading the disposable copy and must pass before mutation.
Only verified native delivery can produce a receipt; failures retain frames,
readbacks, logs and a failure save. Cleanup reaps the process, closes endpoints,
removes the credential and disposes the copied workspace. Controlled test artifacts
are simulated and provide no native delivery proof.

## Attempt 1 admission diagnosis, controlled follow-up

Status: `ADMISSION DIAGNOSTICS READY; NATIVE EVIDENCE REQUIRED`.
Attempt 1 remains failed. Its frozen `main.nut` matches the pre-diagnostic source.
The retained inspection has `NO_NATIVE_FEASIBLE_OD`, all ten identity values -1,
eight zero facts, tick 15, economy date 712223, unpaused company funds 100000,
vehicle -1, stage/cost zero. The result records one launch/connection/request and
zero mutations. Frames and logs contain no engine, industry or candidate inventory.
These sentinel arrays are **not candidate counts**. Generated engines, OD pairs,
layouts, and every intermediate survivor count are unknown; selected ODs are zero.
No first candidate rejection can be reconstructed from these bytes.

The exact ordered admission pipeline is:

1. Valid company 0, selected available ordinary road type; empty fleet, unpaused world.
2. At most 32 road engines; buildable/valid road engine, non-articulated, ordinary-road
   compatibility and power, valid default truck cargo, refittable default cargo,
   positive capacity. Sort accepted engine IDs.
3. Per engine/default cargo, producing and accepting lists each at most 32 entries.
   Enumerate engine-specific OD pairs; reject identical industry, nonpositive
   last-month production, then non-`CAS_ACCEPTED` destination.
4. Read native industry locations. Enumerate nine fixed northwest offsets per pair,
   globally at most 64 layouts. Construct L route, stop fronts and depot spur.
   Reject excessive route length, degenerate bend or invalid row/orientation.
5. Reject any invalid/border/duplicate/nonvacant footprint tile, then unequal height.
   Vacant requires buildable, flat, unowned, no water/coast/tree/farm/rock/roughness
   or existing transport. This is construction topology, not a YAPF route proof.
6. Require truck radius 1..4, unique positive-producing source in catchment,
   native tile production exactly 1, tile acceptance at least 8, and an actual
   destination industry tile in catchment.
7. Test seven construction/purchase commands. Require successful positive quotes,
   purchase quote equal to engine price, total at most 100000 and company funds.
   Only then return READY. Python additionally binds seal/save/predecessor and
   validates native fields, capacity, price, pause, vehicle absence, stage and cost.

Attempt 1's status proves setup/world gates passed, engine and industry limits were
not exceeded, and the layout bound was not exceeded. It proves nothing about which
candidate gates ran. Supply here is positive native last-month production, **not**
the separate two-rollover planning qualification. No qualified-planning input enters
this proof. Frozen-source/save/predecessor identities remain separate from OD facts.

Tagged 15.3 [industry implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.cpp)
returns the industry location tile, native last-month history, and distinguishes
temporary cargo refusal. The [tile implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_tile.cpp)
reads aggregate production/acceptance around tiles and uses the game's catchment
setting. Neither establishes that Attempt 1 returned production 1 or any other
value. Exact-one production and fixed offsets warrant investigation only if their
rejection counters are observed. No feasibility correction is justified yet.

Failure diagnostics use the existing `a + f` arrays only when an inspect failure
has `s[29] == 2`; successful identity arrays retain their original meaning.
Counter order is `engines_seen, engines_compatible, pairs, same_industry, no_supply,
not_accepted, layouts, topology, footprint, height, radius, pickup_identity,
production_count, acceptance, destination_coverage, quote, budget, funds`.
`s[28]` is the first observed rejection's one-based counter index, or zero.
Each candidate is charged only to its first rejecting gate. Pair counters count
engine-specific pairs, not unique ODs. Limits are 33 engines seen, 32 compatible,
32768 pairs/pair rejections, and 64 layouts/layout rejections. Engine/industry/search
limit statuses remain explicit. Engine incompatibility and footprint/quote predicates
are grouped gates. Before/after counts follow by subtracting rejection counters in
order; limit statuses mean partial traversal, not complete inventory.
The Python decoder validates bounds, counter conservation and first-reason integrity,
distinguishes no generated pairs from rejected pairs, and returns no diagnostics for
historical snapshots. Admission failures retain decoded diagnostics in their error.

Next action requires separate authorization: prepare a fresh diagnostic source freeze
and a separately bounded native inspection, retain its response, and identify the first
observed gate before proposing any feasibility correction. No new attempt is created
or authorized by this diagnosis.

## Working native MVP: Attempt 4

`WORKING FREIGHT MVP COMPLETE` for the standalone demonstration. The earlier
admission-diagnosis status above records the historical preparation stage.

Three follow-up launches were authorized and consumed separately:

- Attempt 2: one secure connection, one inspection, zero service mutations.
  Eleven engines were examined, ten compatible, seven engine-specific pairs,
  one no-supply rejection, 54 layouts, nine topology and 45 footprint rejections.
  The first actual candidate rejection was `footprint`; no layout reached catchment.
- Attempt 3: the native heightmap world and two industries were created, but a
  Squirrel `.call()` wrapper around inherited `Start()` prohibited suspension in
  `Sleep()`. No Admin connection or service requests occurred. Its process was
  reaped; a runtime-log-health error prevented automatic disposal verification.
  Endpoint/workspace cleanup was completed in the separately hash-bound
  `openttd-15.3-first-freight-delivery-attempt3-cleanup-recovery.json`. The original
  failure result and all consumed evidence bytes remain unchanged.
- Attempt 4: direct event-loop startup, preflight PASS, one process, one secure
  connection, 26 requests and ten service mutations. Native and offline verification
  both returned `NATIVE_DELIVERY_VERIFIED`. Cleanup reaped the process, closed
  endpoints, removed the credential and disposed the workspace.

The native flat demo uses seed 42 and a 64×64 grayscale heightmap loaded by OpenTTD.
It builds default temperate industry types 0/1 at native tiles 1300/1828 after
checking their native producer/acceptor cargo lists. Native readback identified
source industry 0, destination 1, cargo 1, engine 123 and capacity 20. The footprint
is read back as flat height-one land and cleared natively only when safe. At most
two industry builds and 50 clearing commands are permitted during preparation.
Production rates, allocation, loading, delivery and income are never set by the demo.
The game's own generation initialization supplied last-month production 96;
this is native supply evidence, not a two-rollover qualified planning observation.

Attempt 4 loaded and delivered **20 coal units**. Independent destination-arrival
and unloading samples, both industry monitors and company delivered-cargo increase
agree on 20. Native company income increased by **341 GBP**, vehicle profit by
**304 GBP**, and construction/purchase spending was **9358 GBP**. Retained saves,
frames, readbacks and the plan-bound receipt passed the offline verifier.

A controlled regression exposed an additional native-semantic defect before Attempt
4: vehicle test-mode purchase cannot succeed on an unbuilt depot. Tagged 15.3
[vehicle command code](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/vehicle_cmd.cpp)
requires an actual owned depot even in query mode. Admission now quotes the six
independent construction commands and reserves the native engine price. After
construction/readback of the depot and connected route, purchase must pass native
test mode and exactly match that price before execution. Funds, capacity, compatibility,
command accounting and route gates remain enforced.

Tagged 15.3 [production catchment code](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/station_cmd.cpp)
counts distinct industries supplying the cargo. The exact-one producer gate was
therefore retained; it was not the observed failure and did not need relaxing.

The supported workflow is the existing argparse freight proof module:
`next`, `prepare DIRECTORY --demo`, `preflight DIRECTORY`,
`run DIRECTORY --authorize-one-launch`, and `verify DIRECTORY`.
`OPENTTD_BINARY` and `OPENTTD_OPENGFX_ARCHIVE` configure pinned asset locations.
A new demo does not require the ignored historical predecessor saves or receipts.
See [README](../README.md) for complete setup, commands and result inspection.

Planning integration remains controlled. `freight_planning.py` reuses the existing
WPO/P08/P05/ExecutionPlan chain to compile an explicitly selected single-vehicle
service, retaining candidate and engine provenance. Real-source admission remains
blocked by unproven authoritative post-qualification save correspondence. The
working standalone native receipt is not relabeled as a P05 delivery receipt.
