# Controlled OpenTTD 15.3 P08 adapter and bounded road generation

Architecture authority: local `CONTEXT.md`. Baseline HEAD:
`6a0da37fe2d43c5937fc14279816dfa5af79472e`. This implementation is an offline
algorithm integration using existing admitted contracts. It supplies the existing
P02/P05 domain without changing its models, validators, optimizer or objectives.
It is not executable-world evidence. No native handler or proof freeze is created.

## Interface and responsibilities

```python
from datetime import date
from app.planning.p08_adapter import MonthlyBatchPolicy, adapt_planning_facts
from app.planning.p08_road import generate_road_scenario

road_input = adapt_planning_facts(
    validated_planning_fact_input,
    MonthlyBatchPolicy(start_date=date(2001, 1, 1)),
)
outcome = generate_road_scenario(road_input)
```

`adapt_planning_facts(ValidatedPlanningFactInput, MonthlyBatchPolicy)` returns frozen
`BoundedRoadInput`: original admitted input, policy, ordered industry/cargo mappings,
all qualified supply records (including zero), and compact `RoadProvenance`.
Industry anchors and capabilities come from final structural observations. Native
four-byte cargo labels map losslessly to `cargo-<uppercase hex>`; collisions reject.
The adapter does no geometry, selection, qualification, acquisition or optimization.

`generate_road_scenario(BoundedRoadInput)` returns either `ControlledRoadScenario`
or `NoRoadScenario`. The successful result contains the unchanged-contract
`PlanningScenario`, benchmark, facilities/fronts, corridor, fleet count, road-piece
count, search work and candidate provenance sidecar. It never invokes P05. P05
invocation is confined to controlled compatibility tests.

## Admission and provenance

Admission re-enters `ValidatedPlanningFactInput` using its authoritative constructor.
That constructor revalidates WPO, supplemental facts and prepared correspondence;
the adapter does not reproduce their semantic gates. Complete structure and
production, planning qualification, exact structural source, exact production target
coverage, same owned process/connection context, runtime/world/config/bridge,
industry/cargo references, complete declared coverage, M2 capture brackets, content
and seed coherence remain mandatory. Unchecked Pydantic/dataclass construction is
not a bypass. The generator re-derives and compares adapter mapping so a manually
fabricated supply or provenance field cannot enter candidate generation.

WPO, supplemental and admitted manifest identities remain separate. The sidecar
retains these identities, policy version/digest and controlled source trust. Each
infrastructure/fleet candidate references the sidecar digest and records numeric
producer, acceptor and cargo IDs plus relevant source tiles; fleet provenance also
records native engine ID. The admitted WPO retains exact month boundaries and
producer-lifetime provenance. Complete observations are not embedded in candidates.

## Historical-supply benchmark and time units

Policy version: `qualified-month-batch-v1`. Exactly one OD is selected from the
two declared supplemental coverage scopes. Both must resolve to distinct industries,
matching freight cargo, producer capability, accepting capability and positive
qualified supply. Native industry/cargo/acceptor order is the tie rule; at most one
eligible pickup/delivery combination exists under the two-scope bound. No historical
IDs are hard-coded. Positive supply outside collected relationship coverage is not
silently called covered.

Benchmark quantity equals the selected qualified month's **raw produced cargo
units**. It does not subtract station allocation, infer inventory, extrapolate a
future rate or measure sink consumption. The accepting industry is a potential
receiving industry. `Benchmark.measured_consumption` is None and the demand source
explicitly says `p08-benchmark-policy`. Zero production remains valid observation
data and is never converted to a positive demand.

The configured benchmark start must be a calendar month's first day. Horizon is
that configured month's 28–31 days; latest delivery is horizon minus one. This is
a historical batch assigned to a configured service window, not a claim that native
economy ticks identify the scenario calendar. Native supply economy year/month
remain separate in `QualifiedSupply` and the admitted qualification witness.

P05's actual road capacity rule is `count = ceil(quantity / capacity)`, with
`planned_trips_per_vehicle = 1`. It does not model trip duration, operating
frequency, loading, congestion or a vehicles-per-day rate. This policy explicitly
uses **one assumed load per purchased vehicle over the configured month**, with
at most 64 vehicles. Supply is never clipped to one vehicle's capacity or to that
limit: larger requirements return `CAPACITY_INFEASIBLE`. Capacity feasibility is
mathematical only; one trip in the horizon is not physically proven. Repeat-service
orders in P05 are not evidence of additional trips.

## Bounded station, corridor and depot geometry

Only flat buildable tiles without water/coast, trees/farm/rock/rough, any transport
infrastructure or industry occupancy are eligible. All facilities are 1×1. Pickup
requires intended-industry coverage and producer count >0; delivery requires intended
industry coverage and acceptance >=8 eighths. Catchment is taken from admitted
coverage under the recorded effective radius (3 or 4), never inferred from anchor
distance. Anchor Manhattan distance then tile ID only ranks eligible stop tiles.
The nearest four tiles per role are considered; outputs contain exactly two stops.

For each distinct stop pair, uniform-cost BFS searches covered cardinal neighbors
at equal height. It expands each eligible tile at most once, with N/E/S/W tie order.
The path is loopless; no diagonal, row wrap, missing tile, height transition,
crossing, bridge, tunnel, clearing or existing road reuse is admitted. Stops face
their respective next/previous path tiles. At least one interior road tile is needed.

One depot footprint is selected outside the path, with its front at a path interior,
by tile ID then N/E/S/W. This guarantees geometric connectivity without placing
the depot on the corridor or on a terminal stop. The depot front adds a road branch.
The first supported station pair with a depot is selected. Exhaustion describes
this bounded policy, not global world infeasibility: a different path or placements
outside the nearest-four slice might work.

| Work | Explicit bound |
|---|---|
| Region tiles / coverage scopes / coverage records | 256 / 2 / 512, unchanged |
| Imported artifact | 256 KiB, unchanged importer |
| OD combinations | At most one pickup/delivery relationship |
| Station ranking | Two scans of at most 256 tiles, four results per role |
| Station pairs | At most 16 |
| Path work | <=256 expansions per pair; <=4096 total |
| Depot checks | <=256 footprints ×4 neighbors per pair; <=16384 total |
| Engine records examined | <=32, unchanged |
| Successful output | Two stops, one depot, one corridor, one fleet option |
| Required fleet | <=64 vehicles; larger demand is not truncated |

No full-map extraction or search occurs. Terrain legality is a controlled predicate,
not an exact native command-test result. This construction geometry is not YAPF;
YAPF would later route vehicles over built infrastructure.

## Engine selection and costs

Choose the lowest-ID public-available, compatible ordinary-road, non-articulated,
default-cargo engine that meets the bounded fleet capacity policy. Existence is not
availability; refitting is excluded. Capacity and purchase price come directly from
admitted facts. Public deity availability says nothing about an eventual company's
balance, permissions or future availability. Day0 is the only asserted availability.

All monetary amounts remain exact Decimal GBP. Native annual running cost is retained
in the input and converted by the named calendar benchmark normalization `/365`,
six decimal places, half-even. This is not observed daily running cost. Engine speed
uses native ×1.00584; a nonzero road cap uses ×2.01168. The minimum of these maximum
speeds is descriptive, not average speed or a transit-time guarantee.

Road cost is a **controlled piece-count estimate**: two pieces per nonstation path
tile plus one additional piece at the depot front. Stop and depot footprints are
charged their admitted base prices once each; corridor station endpoint tiles do
not receive a second road charge. The shared corridor is one infrastructure candidate,
not one charge per vehicle or cargo. Engine purchases are charged once per required
vehicle by unchanged P05. Budget is a supplied benchmark cap on infrastructure plus
purchase capex, consistent with P05's objective; running costs are descriptive and
do not enter that objective. No revenue or measured consumption is invented.

Existing `preparation.costs.validate_cost_units` supplies exact fixed-point precision
and integer-range checks (including the configured budget). Missing/invalid cost
fields or mixed currency reject at supplemental admission; excess range and budget
infeasibility return typed no-scenario outcomes. The road normalization is not an
exact native complete-command quote. Town authority, station separation, ownership,
vehicle occupancy, finance and actual command costs remain unproven.

## Deterministic identities and prepared manifest

Site IDs use native industry/tile IDs and role; fleet uses native engine ID. Corridor
ID uses the existing P08 SHA-256 ordered-path convention (24 hex characters).
Canonical policy hashing normalizes Decimal spellings; supplemental DTOs canonicalize
input ordering. All search, ranking and iteration use explicit deterministic order.
Equivalent accepted semantic inputs produce identical candidate sets and scenario
canonical bytes, independent of Python hash/set iteration.

Candidate-dependent resolved sites, cargo/vehicle catalog and eligible buildable
tiles project into the admitted **controlled** manifest. Save source digest,
OpenTTD/base-set pins, dimensions and seed are preserved. An empty manifest projection
is a permitted controlled seam; any supplied nonempty projection must match exactly
and is never silently overwritten. The input manifest fingerprint is retained in
provenance; the downstream fingerprint is solely `world_manifest_hash(projected
manifest)`, as in existing P08. This is not a new world-fingerprint definition.
Industry world references bind the projected fingerprint and numeric native IDs.

The source digest remains an explicitly controlled original or final save identity.
It is never synthesized from structural, production or WPO digests, and never grants
executable post-qualification correspondence. P03 save staging remains unchanged.

## Failure outcomes and compatibility claims

Authoritative upstream typed errors reject malformed, incomplete, unqualified,
identity-conflicting, wrong-mode/road-type, missing-cost/reference/provenance or
invalid-correspondence input before generation. `AdapterError` preserves the cause
and classifies admitted revalidation failures without weakening their gates.
Valid but unserviceable worlds return `NoRoadScenario` with:

- `NO_ELIGIBLE_BENCHMARK` for qualified empty targets or incompatible covered OD;
- `ZERO_POSITIVE_SUPPLY` for qualified nonempty all-zero supply;
- `INSUFFICIENT_COVERAGE`, `MISSING_CATCHMENT`, `NO_STATION_PLACEMENT`;
- `INVALID_ENGINE_COMPATIBILITY`, `CAPACITY_INFEASIBLE`;
- `NO_BOUNDED_CORRIDOR`, `NO_DEPOT_PLACEMENT`;
- `COST_INFEASIBLE` or `CONFLICTING_IDENTITIES`.

There is no fake demand, incomplete scenario, force flag or promotion of negative
facts. Upstream errors retain their required field/reason; typed outcome detail
states the deterministic bounded failure. Controlled tests validate P05 schema,
relationships, world references, ceil capacity, budget and one-time shared costs,
then run unchanged P05 and its public execution-plan validator.

These claims are separate: schema valid; mathematically feasible; optimizer solution
found; real OpenTTD construction feasible. Only the first three are tested here.
`ControlledRoadScenario.classification` is `CONTROLLED_PLANNING_SCENARIO`, trust
remains `CONTROLLED_FIXTURE`. Its real-executable gate delegates to the existing
fail-closed correspondence gate. `SOURCE_BYTES_VERIFIED` also cannot become
`REAL_RUNTIME_CORRESPONDENCE_PROVEN` through generation.

## Existing P08 audit and future proof requirements

Reused: existing P05 contracts/canonical identities, supplemental/input/source/WPO
admission, and pure fixed-point cost validation. Historical correct algorithms
remain unchanged. Existing station sampling requires full industry footprints and
full-map tile indexing; historical projection gates 13.4 and raw unqualified supply.
Its waypoint Dijkstra retains path histories to require a loopless depot-anchor
path. This new minimum policy places the depot after a shortest corridor and uses
complete region coverage, so it uses finite uniform-cost BFS instead of rewriting
that correct, differently scoped Dijkstra. No historical component is replaced or
deleted. Old probe, lifecycle, snapshot, 13.4 API fixtures and tests remain historical
and are not imported by the new path.

Real qualified production remains proven by the existing accepted history. Native
supplemental acquisition remains NOT PROVEN: bounded settings/content/seed,
tiles/coverage, road costs and engine evidence require separately reviewed handlers,
budgets, same-run temporal/source coherence and accepted artifact issuance.
Real save-to-load and final-state-to-post-qualification-save correspondence remain
NOT PROVEN. Actual owned save bytes, load/capture evidence, runtime/content/config
pins, trusted issuer and independently accepted correspondence are required.
Finally, company-specific command tests, construction/executor evidence and real
service attribution need separate authorization and proof. This task grants none
of those claims and performs zero native launches, connections or requests.
