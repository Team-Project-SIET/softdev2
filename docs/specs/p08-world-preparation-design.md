# P08 — OpenTTD World Preparation and Candidate Graph Generation

Status: implementation authority supplied by the user; real extraction proof is
separately authorized and has not been performed. P08 remains uncommitted.

## Boundary

PreparationRequest → read-only GameScript extraction → strict immutable
ExtractedWorldSnapshot → canonical serialization and reparse → pure Python
demand, station, shared depot, construction corridor, fleet and cost generation
→ PreparedWorldManifest, PlanningScenario, ExecutionBindings,
PreparationProvenance → existing P02 validation → P05.

Extraction facts remain separate from planning schema v1. No ORM, database,
process handles or wall-clock timestamps belong in semantic artifacts. P04 Admin
is observation-only and is not the extraction channel. OpenTTDLab's result parser
is not a map geometry authority.

P08 generates the candidate search space. P05 chooses the network, P06 executes
construction, and P07 evaluates realized outcomes. Construction search solves
unbuilt geometry; it is neither vehicle routing nor YAPF. P08 does not guarantee
global optimality beyond candidates, future supply, profitability or arbitrary
future construction success. No subsequent planning phase is defined here.

## Supported profile

OpenTTD 13.4, OpenGFX/default content, temperate, preparation-compatible worlds,
no NewGRFs or competing active companies, road freight, flat eligible vacant
land, 1x1 terminal truck stops, exactly one shared road depot, explicit orthogonal
road corridors and immediately buildable non-articulated default-cargo freight
engines with authoritative positive default capacity. No refit-dependent capacity.

Reject slopes, water/coast construction, clearing/trees, bridges, tunnels,
crossings, demolition, terraforming, existing infrastructure reuse, rail generation
and unsupported content. Unsupported profile and extraction facts fail explicitly.
Arbitrary historical saves are not assumed preparation-compatible.

## Extraction and identity

Versioned internal facts include runtime/content pins, dimensions, seed,
landscape, preparation date/company query context, tile index and coordinates,
flatness/slope/height evidence, land/water, occupancy/transport, eligibility,
industry native identities/anchors/footprints, production/acceptance/catchment,
observed last-month quantities, native cargo and road-engine catalogs,
availability, native cost evidence, completeness and policy identity. Include
only facts used by preparation.

Strict parse → canonical serialize → canonical reparse → authoritative object
precedes projection and hashing. Normalize enumeration-only collections; retain
corridor tile order and existing route/action ordering semantics. Semantic IDs
are deterministic. Prepared save SHA-256 becomes manifest.source_digest;
existing world_manifest_hash is the sole world fingerprint. Existing
scenario_hash identifies planner inputs. Separate hashes identify request/policy,
snapshot, candidate report, bindings and provenance envelope.

Manifest contains pins, save digest, dimensions/seed, resolved sites, referenced
cargo/vehicle labels and conservative buildable_tiles, not full terrain internals.
Buildable means eligible under this profile, not a guarantee for arbitrary commands.
Native industry references feed existing P03 runtime projection. P03 checks
dimensions, seed and referenced objects, not complete terrain/cost identity.
Preparation artifacts must be retainable/linkable by P07 without metric changes
or a migration unless current storage demonstrably requires one.

## Demand policy

Enumerate positive observed last-month industry production and currently accepting
destinations. Resolve fixed OD deterministically using versioned policy. Emit
exactly one mandatory demand per P08 v1 scenario; do not duplicate one supply
quantity across mandatory demands. This is a preparation limitation only:
P05 remains capable of optimizing multiple supplied demands. Alternative
destination semantics, depot compatibility and overlapping segments motivate it.

Quantity is historical benchmark evidence, not a forecast, future guarantee or
horizon production. Generate earliest_day=0, latest_delivery_day=horizon_days-1,
priority=normal, max_transit_days=None. Preserve P02's strict deadline validation.
Retain policy in SourceReference and provenance.

## Candidate policies

Search bounded industry footprint/catchment neighborhoods, not all map tiles,
for 1x1 truck stops. Require in-bounds flat vacant eligible land, no reservations
or unsupported transport, native pickup/acceptance evidence (delivery at native
threshold), and valid oriented front. Use versioned deterministic compass-sector
ranking/sampling, at most four sites per role. Record eligible counts and sampling;
this is the sole intentional clipping policy. No sites: NO_STATION_CANDIDATE.

Generate exactly one eligible 1x1 shared road depot with deterministic orientation,
valid front outside station footprints and compatible road/depot class. Every
advertised corridor must include this same front anchor. No depot:
NO_DEPOT_CANDIDATE. Do not change P05 or schema to add compatibility relations.

Use deterministic Dijkstra with state (tile_index, incoming_direction), orthogonal
moves and integer/fixed-point objective: construction GBP, tile count, turns,
canonical tile sequence. Respect station entry/exit orientation and depot anchor.
Reject unsupported terrain/occupancy, reserved footprints, invalid edges and
repeated tiles. At most two loopless alternatives per directed station pair,
only where current P02/P05/P06 semantics safely represent them. Do not claim
overlapping segments jointly feasible or change overlap rules. Exhausted supported
space: NO_FEASIBLE_CORRIDOR; any search bound hit: CANDIDATE_LIMIT_EXCEEDED.

Project native road engines only when immediately buildable, freight,
non-articulated, default-cargo compatible, positive authoritative capacity,
supported road/depot class and no refit. Populate native identity, capacity,
purchase/running cost, speed, source and P06 bindings. Availability is day 0
through day 0 only. No compatible engines: FLEET_CATALOG_UNAVAILABLE.

Version native road/facility construction estimates. Reject clearing-required
tiles. No travel-time, YAPF, congestion or speculative profit costs.
revenue_gbp_per_cargo_unit remains None without explicit compatible assumptions.

Before publication, check every P05-selectable combination against current P02
and P06: stations, depot-front connectivity, geometry, fleet/cargo/depot, terrain
and executor capacity constraints. Any selectable invalid combination fails
INVALID_PREPARATION_OUTPUT; never defer this check to optimization/runtime.

## Hard limits (v1)

| Bound | Maximum |
| --- | ---: |
| Map tiles | 65,536 |
| Industries examined | 32 |
| OD/cargo relationships | 16 |
| Mandatory demands per scenario | 1 |
| Station candidates per role | 4 |
| Depots per scenario | 1 |
| Corridors per directed pair | 2 |
| Fleet options | 32 |
| Total infrastructure candidates | 64 |
| Corridor tiles | 4,096 |
| Search states per pair | 250,000 |
| Aggregate expansions | 2,000,000 |
| Canonical scenario bytes | 4 MiB |

No silent hard-bound truncation. Overflow is CANDIDATE_LIMIT_EXCEEDED. Station
sector sampling is documented separately from these overflow rules.

## Failures and lifecycle

Typed failures: UNSUPPORTED_WORLD, EXTRACTION_INCOMPLETE, UNKNOWN_CARGO,
NO_COMPATIBLE_DESTINATION, NO_STATION_CANDIDATE, NO_DEPOT_CANDIDATE,
NO_FEASIBLE_CORRIDOR, UNSUPPORTED_TERRAIN, FLEET_CATALOG_UNAVAILABLE,
CANDIDATE_LIMIT_EXCEEDED, WORLD_CHANGED_DURING_PREPARATION,
CATALOG_IDENTITY_MISMATCH, INVALID_PREPARATION_OUTPUT. Include stage, source
identity, affected object when relevant and bounded deterministic diagnostic.
Incomplete extraction must never publish a scenario.

The non-building OpenTTD 13.4 GameScript uses explicit company context only for
queries requiring it, supports paused extraction, emits bounded sequenced frames,
declared counts and terminal digest/completion, then becomes inert. Controlled
API-fidelity tests verify actual 13.4 method names/signatures and prohibit build
commands. Separate preparation lifecycle stages probe, invokes a launch seam,
collects evidence, verifies completeness/save identity, canonicalizes snapshot
and cleans up. Ordinary tests use fake runtimes. No real OpenTTD launch here.

## Implementation and acceptance

TDD slices: contracts/failures/limits; canonical synthetic snapshots; projection;
demand; stations/depot; corridors; fleet; combination safety; probe/parser;
controlled lifecycle; provenance; cross-P05/P06/P03/P07 integration; docs/status.

Cover canonical enumeration/terrain/order/save identity, demand policy/deadline,
station eligibility/acceptance/sampling, depot orientation/connectivity,
Dijkstra ties/obstacles/alternatives/limits, fleet filtering/order, every selectable
combination, P02/P05/P06/P03/P07 consumption, probe sequencing/counts/digest/API
fidelity/inert completion, all hard bounds and no partial publication.

Run focused P08, P05, P06, P02/P03, P04, P07 and affected controlled runtime
regressions, Ruff/format/typecheck, diff/whitespace/import audits. PostgreSQL only
if persistence changes. OpenTTD launches must equal zero. Stop after controlled
implementation and report readiness for separately authorized extraction proof.
Do not commit or push. Status remains P08 INCOMPLETE — real extraction proof
not yet performed.

## Concrete v1 implementation policies

- Station neighborhood is the bounded union of radius-three squares around actual
  industry footprint tiles. Eligible sites are ranked within N/E/S/W sectors by
  Manhattan distance to native anchor and tile index, then sampled in compass round
  robin order. Prefer fronts pointing away from industry, then N/E/S/W. Candidate
  counts are recorded before sampling. Modified station catchment must be enabled;
  native acceptance is at least eight eighths for a 1x1 truck stop.
- Depot `front-connectivity-distance-v1` ranks eligible depot tiles by summed
  Manhattan distance to sampled station fronts, then tile index, then N/E/S/W
  orientation. Exclude sampled station footprints/fronts as depot footprints.
  Removing the depot must leave its front and every sampled station front in one
  supported equal-height component. Every advertised corridor then includes that
  anchor. A sampled station pair with exhausted search has no edge; no edge is
  omitted after a limit hit. All sampled facility footprints stay reserved.
- Dijkstra labels retain incoming direction, anchor progress and visited-tile
  history. Histories with the same visited set/state retain up to the requested
  number of alternatives. Generated labels and expanded labels are both bounded
  per pair; expansions also share the aggregate budget. Search for a second
  alternative can hit a bound and invalidate preparation even after finding one.
  Open grids may reach the bound; no approximate or partial result is published.
- Native road piece cost is doubled for the conservative two-bit road tile
  estimate, including endpoint tiles; stop/depot costs are native base costs.
  Annual native running cost is converted to a daily estimate by dividing by 365
  and rounding half-even to 0.000001 GBP. It does not enter P05's capex objective.
  Native speed is retained as `native_speed_units`, then converted using exact
  decimal multiplier 1.00584 for the current km/h planning field.
- Accepted normal frames are `P08|sequence|kind|JSON`, with meta-declared counts,
  tile/industry/cargo/engine/cost rows, and `done` carrying counts and eight hex
  Adler-32 digits over preceding frame bytes plus newlines. Typed `failure` frames
  retain failure code/message and checksum. No failed stream publishes a snapshot.
  Frame bound is 8 KiB; aggregate console evidence is 64 MiB; cargo catalog bound
  is 32 and raw road engine catalog bound is 256. These transport bounds also fail
  explicitly. The script retains completed/inert status through Save/Load.
- Runtime/content/NewGRF pins and seed are supplied by the isolated generated-world
  adapter receipt; the probe cannot attest all content from GameScript alone.
  Runtime adapter start/collect/save/close are explicit seams, with no concrete
  native launcher invoked or bundled here. Source/prepared save and staged package
  identity are checked before retention. Cleanup completes before accepted artifacts
  are published. A sidecar index uses current P07 `ArtifactReference` values and
  links the same scenario/manifest hashes without changing P07 storage or metrics.
- Structural witness plans are internal validation objects only. Every selectable
  combination goes through existing P02/P06 validation, including P06 evidence
  capacity. Native catalog compatibility and P05 coefficient precision/range are
  also checked. P08 does not publish an ExecutionPlan or call the optimizer.

Native API fidelity sources are the pinned [OpenTTD 13.4 script API headers](https://github.com/OpenTTD/OpenTTD/tree/13.4/src/script/api),
with used declarations and source-header SHA-256 values retained in
`tests/fixtures/p08_api_13_4.json`. [Engine speed units](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/script/api/script_engine.hpp)
and [tile acceptance/production queries](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/script/api/script_tile.hpp)
are projected according to that version. The [paused state loop](https://github.com/OpenTTD/OpenTTD/blob/13.4/src/openttd.cpp)
continues GameScript execution; the probe neither pauses nor unpauses gameplay.

## Controlled verification — 2026-10-04

Baseline HEAD remains `6eacdb0b4c39b2dd886a4a749bbeb588f690d22f`.
P08 is uncommitted; `.env.example` is preserved. No commit or push was performed.
No P02/P03/P04/P05/P06/P07 source behavior, objective, schema or metric semantics
were changed. No migration or database integration was added.

| Scope | Passed | Skipped |
| --- | ---: | ---: |
| Focused P08 | 78 | 0 |
| P05 optimizer | 37 | 0 |
| P06 domain/executor | 71 | 0 |
| P02/P03 contracts/world/transport | 97 | 0 |
| P04 protocol/session/observer | 322 | 0 |
| P07 realization/evaluation/setup/live integration | 37 | 3 |
| Other controlled experiment/runtime regressions | 407 | 32 |
| Total | 1,049 | 35 |

The final whole controlled suite used `pytest -m 'not openttd'`; three real-OpenTTD
cases were deselected. All 35 skips were opt-in PostgreSQL cases. PostgreSQL was
not run because P08 does not touch persistence. A verification audit hook blocked
native OpenTTD subprocesses before execution: attempted native launches **0**,
actual launches **0**. Fake server peers and the embedded Squirrel VM are controlled
verification, not OpenTTD proof.

An unchanged P07 live-runner timing test timed out in the first whole-suite run;
its targeted rerun and the final whole suite passed. No runtime behavior or test
threshold was changed to obtain that result.

Whole-repository Ruff and format checks pass. Scoped `ty check` passes for
`app/planning/preparation` and the three new preparation test files. Tracked diff
checks and untracked-file diff/whitespace checks pass. The P08 import audit finds
no ORM, persistence, simulation, Admin, subprocess or optimizer import. Lifecycle
intentionally reuses the existing P03 data-only `_literal` serializer; no P03
behavior is modified. Separate standards and spec reviews found no remaining
blockers after corrections to native speed units, typed probe failures and typed
lifecycle filesystem errors.

Known concrete limits remain: conservative supported content/terrain, one historical
fixed OD demand, sampled station sites, one shared depot, direct loopless construction
corridors, bounded history-label search (including second-alternative exhaustion),
P06 evidence capacity and current fixed-point cost range, and no native launcher
bundled by P08. The runtime adapter must supply verified generation/content pins;
arbitrary old saves and real extraction are not established by controlled tests.

READY TO REQUEST AUTHORIZATION FOR REAL P08 EXTRACTION PROOF

P08 INCOMPLETE — real extraction proof not yet performed
