# P08 15.3 minimum facts and prepared-source identity

Architecture/prerequisite contract, 2026-10-08. Authority: local `CONTEXT.md`.
Baseline HEAD: `6a0da37fe2d43c5937fc14279816dfa5af79472e`.
This refines [the previous audit](world-planning-observation-and-p08-audit.md),
which remains unchanged as a record of the earlier design-only state.

**Scope:** a pure immutable observation seam and WorldPlanningObservation are
implemented and controlled-tested. Supplemental fact DTOs, source-link DTOs,
queries, P08 adapter and generator changes are **not implemented** here. Qualified
production Attempt 4 under V5 remains passed; no historical evidence is rewritten.
No native execution, Admin requests, source freeze, staging, commit or push.

## 1. Proven observations and limits

The existing 15.3 pipeline proves final structural inventory/capabilities/catalog,
complete production, exact structural-source identity, two adjacent economy
rollovers, fully bounded M1, stable produced targets/relevant industry lifetime,
fresh M2 structure/production, one continuous runtime/secure connection, cleanup,
integrity, lineage and final offline acceptance. Supply and structure are real
observations. They do not prove terrain/catchment/engine/cost extraction, measured
consumption, prepared-save loading, atomic world capture or P08 integration.

Final structure contains industry ID/type/tile/x/y; produces/accepts; cargo ID,
four label bytes encoded as hex, freight/classes/town effect; map/runtime/config/
bridge identities. Production contains qualified historical raw production,
station allocation and percentage, exact source relation and M2 capture brackets.
Relevant producer construction identity is calendar identity, not economy time.
No new quantity is inferred from capability or tile catchment counts.

## 2. Pure-type seam: extraction rather than another model hierarchy

Previous dependency paths included structural observation → cargo/capability
collection module → transport, and qualification result → coordinator → secure
Admin/transport/accounting. Bridge identity also imported runtime workspace staging.

Extracted, unchanged definitions:

| New pure module | Responsibility | Existing compatible imports |
|---|---|---|
| `observation_identity.py` | RuntimeIdentity, VersionInspection, BridgePackage metadata | `runtime.identity`, `gamescript_bridge` |
| `observation_protocol.py` | Existing bounded wire values/errors/canonical validation | `gamescript_protocol` |
| `capability_observation.py` | Immutable capability observation, budget and validated transaction | `industry_capability` |
| `catalog_observation.py` | Immutable catalog observation/budget/page/reference checks | `cargo_catalog` |
| `observation_session_evidence.py` | Frozen structural/production session evidence | Original session modules |
| `qualified_production.py` | Existing phase, immutable qualification evidence/result and exact validation | `qualification_session` |

Structural/production/clock/lifetime/evidence DTO modules import these pure
providers. Existing collectors retain the same classes through aliases; class
identity, field layout, validators, canonical bytes and digests are preserved.
Legacy Admin WELCOME annotations in dimension helpers are typing-only: importing
observations does not load Admin codecs/session, crypto, process lifecycle or
GameScript execution. Pure wire values and native-log evidence remain data;
there is no package staging, socket creation, subprocess or script invocation.

The moved definition ASTs were compared to their originals: no definition-body
changes. A golden controlled coordinator capture taken **before** extraction checks
exact final structural/production bytes and digests afterwards. Existing semantic
qualification progression and accounting validation remain in the same result
constructor; it was moved, not replaced by a weaker successful flag.

Source freezing already enumerates every Python file under `app/simulation/openttd`;
future preparation therefore includes extracted modules automatically. No existing
freeze is updated or recaptured. Old freezes are historical contracts, not current
execution authorization after source changes.

## 3. WorldPlanningObservation implemented domain contract

Module: `app/simulation/openttd/world_planning_observation.py`.
Frozen fields: `structural: StructuralWorldObservation` and
`qualification: QualifiedProductionResult`. Production, context and qualified
month are derived references. There are no copied industry/cargo/production lists.

Construction revalidates typed structure and the full qualification result,
requires complete and qualified production, exact final-source object relationship
and digest, same process/connection/runtime/world/config/bridge context, exact
produced-target coverage/references, and valid native qualified-month identity.
M1 anchor or an equal-content substitute cannot replace the actual final M2
source. Missing/partial/unqualified/damaged inputs fail; no bypass flags exist.

`structural_world_digest` is the actual existing property name. Context is
`structural.inventory.context`, not a new structural context field. Qualified
month is M1; production capture and planning structure are M2. Zero quantity and
complete qualified empty target sets are valid. A later adapter may fail with no
positive selectable OD; that is not an invalid observation.

Canonical WPO payload is exactly schema `world-planning-observation-v1`, final
structural digest, production digest, qualified economy year/month/start/end
(exclusive), and ordered relevant industry/construction-date identities. SHA-256
is `composition_digest`. Version 1 binds the existing restricted qualification
profile. No request IDs, pages, paths, poll timestamps, receipts or process addresses
are hashed. Equivalent semantics in different runs can have equal digests;
admission still requires matching owned context. Neither existing component digest
nor downstream world fingerprint changes.

This model establishes semantic admission, not proof cleanup/offline acceptance
or a save association. A real-data issuer must verify accepted immutable proof
artifacts before supplying a real input. Controlled fixtures do not become native
attestations. Retained-artifact reconstruction of opaque run handles remains a
future importer obligation, not a hidden file reader inside this model.

## 4. Smallest useful P08 slice

Choose ROAD, one explicit **qualified-supply-to-acceptor historical OD benchmark**,
freight cargo, at least one positive qualified record and one distinct structurally
accepting industry. Minimum output has two 1×1 freight road stops, one compatible
1×1 depot with a shared connected front, one directed loop-free corridor, one
positive-capacity default-cargo non-articulated public road engine, and one positive
CargoDemand. More station/corridor/fleet alternatives are optional bounded policy;
P05 still selects supplied alternatives using its unchanged CP-SAT model.

The required geometry is a declared finite planning region containing the chosen
facilities/fronts and every corridor-search tile. Missing tiles are hard boundaries.
A route outside the region is unsupported, not evidence that no route exists in
the world. Conservative flat, equal-height, vacant ordinary-road terrain avoids
clearing, slopes, foundations, rail, existing-road ownership, bridges and tunnels.
One useful controlled fixture can be tiny; full-map native transport is not required.

**Current-generator compatibility limitation:** old `validate_snapshot` requires
all map tiles and hard-gates 13.4. Its station sampler uses exact industry footprints.
It cannot consume a partial 15.3 region today. A future generator/input port must
explicitly support region coverage or preserve a tiny complete-map controlled
fixture; do not lie about map dimensions or mark partial extraction complete.
Existing algorithms are reusable, not already integrated. No such port occurs here.

For the minimum *future* input, choose native industry-specific coverage candidate
lists plus pair-specific catchment checks instead of requiring a full footprint
scan. This explicitly changes the future input/sampler contract, not existing code.
The alternative legacy footprint-backed sampler requires exact footprint completeness
and remains optional. Pure Dijkstra/candidate logic stays in Python. OpenTTD/YAPF
routes vehicles over constructed infrastructure; it does not generate P08 candidates.

## 5. Field-by-field P05/P08 dependency matrix

Notation: **R** minimum required; **E** real-execution validity; **D** deferred.
Availability concerns authoritative 15.3 observation, not synthetic historical
fixtures. Exact API signatures/units/sentinels/context are documented in the
[source-audited API appendix](p08-15-3-native-fact-api-audit.md); bindings below
refer to that audit. Consumer paths are under `app/planning`.

| Field / consumer | Meaning; type and units | Need | Current source | 15.3 source candidate | Validation | Provenance | Available / missing implementation | Blocks minimum? |
|---|---|---|---|---|---|---|---|---|
| Map width/height; domain, candidate adjacency | Positive int; tiles | R | Structural context / old snapshot | Already proven map/WELCOME | Native tile index = y×width+x; bounds | Structural context/digest | Available | No |
| Industry ID/type/anchor; demand/locations | Native ints, tile/x/y | R | Final inventory | Existing inventory pipeline | Resolve exact inventory IDs | Final structural digest | Available | No |
| Produces/accepts; OD eligibility | Sorted tuple cargo IDs | R | Final capabilities | Existing capability pipeline | Exact catalog refs; no acceptance-as-consumption | Final structural digest | Available | No |
| Relevant producer construction identity; provenance | Native calendar ordinal int | R | Qualification lifetimes | Existing lifetime pipeline | Exact relevant ID coverage/stability | Qualification witness | Available for producers; accepting-only lifetime absent | No for benchmark; E gap for replacement-sensitive sinks |
| Supply; CargoDemand quantity | Qualified cargo units, int ≥0 | R | Qualified production | Existing production pipeline only | Exact produced pairs; complete/qualified/source match | WPO/production digest and M1 | Available | No; all-zero/no OD fails selection honestly |
| Cargo ID/label/freight; demand/fleet filtering | Int; 4 bytes; bool | R | Final cargo catalog | Existing catalog pipeline | Lossless deterministic planner label mapping; collision reject | Catalog/final structural digest | Available native bytes; mapping not implemented | Yes, mapping implementation |
| Qualified-month identity; supply policy | Economy year/month and ordinal bounds | R | Qualification result | Existing clocks | Bounded M1, M2 brackets separate | WPO witness | Available | No |
| Planning start/horizon/deadline; scenario/domain | Configured calendar date; positive days; latest<horizon | R | Request/policy, not supply quantity | No native getter required for configured benchmark | Explicit calendar-economy profile and configured benchmark start; do not guess current calendar from economy time | Policy/request identity | Contract defined; policy DTO not implemented | Yes, policy implementation |
| Region tile index/x/y; candidates/corridor | Native global tile ints; finite set | R | Old all-map snapshot | GSMap validation plus bounded selected tile requests | Exact declared region coverage; no missing/extra/duplicate | Same runtime/source and region identity | Not observed; DTO/query absent | Yes |
| Height/slope; eligible, corridor | Height levels int; native slope mask | R | Old tile probe | GSTile.GetMinHeight/GetSlope | Reject invalid; flat and equal-height neighbor/front edges | Region/native receipt | Not observed | Yes |
| Vacancy/build eligibility; candidates/corridor | Native predicate bool/bitset | R | Old tile probe | GSTile.IsBuildable, water/coast/tree/farm/rock/rough/transport predicates, GSIndustry.GetIndustryID | Validate tile before false/sentinel; strict exclusion, no buildable==vacant shortcut | Region/profile | Not observed | Yes |
| Pickup candidate coverage; station selection | Sorted native tile IDs per industry | R | Old footprints/radius sampler | GSTileList_IndustryProducing(id,radius) | Complete bounded list for supported industry/profile/region; reject overflow | Exact native producer + structural digest | API confirmed; query/DTO absent | Yes |
| Delivery candidate coverage; station selection | Sorted native tile IDs per industry | R | Old footprint sampler | GSTileList_IndustryAccepting(id,radius) | Pair-specific ≥8 check; do not promise exclusive delivery to intended industry | Native sink ID/source/profile | API confirmed; query/DTO absent | Yes |
| Pair tile production/acceptance; station selection | Producer count; acceptance eighths | R | Old TileCargoFact | GSTile.GetCargoProduction/GetCargoAcceptance(tile,cargo,1,1,radius) | Invalid -1 reject; pickup>0, acceptance≥8; source count not supply | Native pair + region + capture bracket | Not observed | Yes |
| Effective catchment/settings; candidate eligibility | Radius tiles; bool integer settings | R | Old fixed radius3/threshold8 | GSStation.GetCoverageRadius(TRUCK_STOP); GSGameSettings | Exact effective radius, supported modified catchment/neutral-service profile | Config plus native corroboration | Frozen config may support part; no complete fact receipt | Yes |
| Stop/depot footprint/orientation; PlanningLocation/ResolvedSite | 1×1 tile; N/E/S/W and front | R | Python policy outputs | Audited native 15.3 restricted road-stop/depot geometry | Nonoverlap, front adjacency/height/connectivity; no unknown native station class | Policy + region/candidate digest | Policy design confirmed; future port absent | Yes, controlled contract/generation port |
| Corridor tiles/connectivity; InfrastructureCandidate | Ordered native tile tuple, not metres | R | Python bounded Dijkstra | No GS path-search query | Orthogonal loop-free flat eligible path through fronts/shared-depot anchor; deterministic limits | Region/policy/candidate digest | Algorithm reusable; new input seam absent | Yes |
| Engine ID/public availability; RoadFleetOption | Native engine int; bool; observation-day availability | R | Old GSEngineList/company probe | GSEngineList(ROAD), IsValidEngine/IsBuildable | Deity enumeration then public availability filtering, no future-company guarantee | Runtime/content/time scope | API confirmed; query/DTO absent | Yes |
| Engine cargo/articulation/road type; fleet compatibility | CargoID; bool; RoadType | R | Old engine facts | GetCargoType/IsArticulated/GetRoadType; GSRoad compatibility | Default selected cargo; non-articulated; ordinary road compatible; no refit claims | Engine/catalog/content identity | Not observed | Yes |
| Capacity; VehicleDefinition | Cargo units int>0 | R | Old GetCapacity | GSEngine.GetCapacity | Reject -1/zero; default-cargo non-articulated scope | Engine facts/catalog | Not observed | Yes |
| Engine speed; VehicleDefinition | Native int; converted Decimal km/h>0 | R | Old *1.00584 | GSEngine.GetMaxSpeed | Exact documented conversion; not travel-time guarantee | Engine/profile + unit policy | API confirmed, receipt absent | Yes |
| Road type availability/speed cap; constraints | RoadType; native cap int, 0 unlimited | R | Old ordinary-road assumption | GSRoad.IsRoadTypeAvailable/GetMaxSpeed | Available compatible ordinary road; road cap conversion2.01168 distinct from engine1.00584 | Content/profile/native fact | Not observed | Yes |
| Road/stop/depot build costs; InfraCandidate | Money native GBP integer ≥0; piece/structure units | R | Old GetBuildCost | GSRoad.GetBuildCost(type,BT_ROAD/BT_TRUCK_STOP/BT_DEPOT) | -1 reject; explicit road-piece geometry normalization, coefficient bounds | Config/content/cost capture/policy | Not observed | Yes |
| Purchase cost; fleet/objective | Native GBP integer≥0 | R | Old engine price | GSEngine.GetPrice | -1 reject; integer-to-Decimal without float | Engine/content/time facts | Not observed | Yes |
| Running cost; VehicleDefinition | Native GBP/economy-year; policy GBP/day | R | Old annual/365 | GSEngine.GetRunningCost | -1 reject; named calendar-economy /365 rounding policy; not native daily measurement | Engine/timekeeping/unit policy | Not observed | Yes |
| Budget/revenue assumptions; constraints/economics | Optional Decimal GBP and benchmark coefficients | D/R | Supplied policy | No native revenue getter needed; funds not assumed | Finite nonnegative values; P05 fixed-point bounds | Request/policy | Can be configured; revenue may be absent | No native gap |
| Base set/content/seed; manifest/scenario/bindings | Version strings, uint32 seed, file hashes | R | Owned runtime freeze, old descriptor | Frozen installed-file authority; GSGameSettings generation_seed and optional GSNewGRFList corroboration | Exact selected content; seed sentinel reject; no GRFID==file hash | Owner source record/config/runtime | Some V5 file/config evidence exists; no complete reusable prepared-source chain | Yes, typed bindings |
| Prepared source digest; manifest/source staging | SHA-256 actual save bytes; byte count | E / R existing manifest path | Old prepared_save_digest | Owned external save hash; no GS getter | Actual byte SHA; non-symlink owned staged copy; exact load/capture chain | Prepared-source link | Missing for qualified Attempt4 | Blocks real compatible prepared source; controlled fixture can model it |
| Manifest resolved sites/catalog/buildable tiles; scenario validation | Candidate-dependent typed projection | R | Current projection | Pure Python from admitted observations/facts/candidates | Existing world_manifest_hash and scenario validator | Source+WPO+facts+policy sidecar | Existing builder 13.4-specific input; no new adapter | Yes, future adapter; not new native query |

## 6. Missing-fact category classification

| Category | Classification | Minimum decision / reason |
|---|---|---|
| A Terrain/elevation | REQUIRED FOR MINIMUM P08 | Restricted flat-road region must contain verified heights; no full-world terrain requirement |
| B Slope/buildability | REQUIRED FOR MINIMUM P08 | Flat vacant subset and exact front/path checks; buildability alone insufficient |
| C Station footprints | REQUIRED FOR MINIMUM P08 as policy output | Fixed 1×1 road stops; general station/industry footprints OPTIONAL / DEFERRED under coverage-list input |
| D Depot placement | REQUIRED FOR MINIMUM P08 | One 1×1 shared road depot/front; placement computed Python-side |
| E Catchment/coverage | REQUIRED FOR MINIMUM P08 | Effective radius and pair-specific predicates; counts are not supply |
| F Road/rail infrastructure | Ordinary road identity REQUIRED FOR MINIMUM P08; rail/reuse OPTIONAL / DEFERRED | Reject existing infrastructure in the strict region; no rail graph/track catalog |
| G Corridor feasibility | REQUIRED FOR MINIMUM P08 | Complete finite region + bounded Python Dijkstra; whole-world reachability deferred |
| H Cargo properties | ALREADY PROVIDED | Native IDs/labels/freight/classes available; lossless planner mapping needed |
| I Engine availability | REQUIRED FOR MINIMUM P08 | Public deity availability sufficient for controlled benchmark; company-specific authorization REQUIRED FOR REAL EXECUTION VALIDITY |
| J Capacity | REQUIRED FOR MINIMUM P08 | Positive default-cargo capacity; refit and articulated capacity OPTIONAL / DEFERRED |
| K Construction costs | REQUIRED FOR MINIMUM P08 | Native base pieces/stop/depot with explicit conservative normalization; actual command cost/authority/funds REQUIRED FOR REAL EXECUTION VALIDITY |
| L Purchase costs | REQUIRED FOR MINIMUM P08 | P05 needs fleet capex and running cost; native quote not finance authorization |
| M Industry identity/location | ALREADY PROVIDED | Numeric/location/structural source and producer lifetime; accepting-only replacement-sensitive lifetime REQUIRED FOR REAL EXECUTION VALIDITY where sink identity is claimed |
| N Acceptance capability | ALREADY PROVIDED | Destination eligibility, not measured demand; operational catchment is missing in category E |
| O Qualified production | ALREADY PROVIDED | Sole quantitative supply, exact target set, zero valid |
| P Content/NewGRF/seed | REQUIRED FOR MINIMUM P08 bindings; partly available | File identity external; native integer seed available but unqueried; no exact content-file-hash GS getter |
| Q Prepared-save identity | REQUIRED FOR REAL EXECUTION VALIDITY and current manifest save path | Missing native linkage does not prevent controlled DTO fixtures; no fabricated save SHA |

UNKNOWN / SOURCE AUDIT REQUIRED does not apply to an invented getter: the required
read symbols are audited below. Exact actual content/load/coverage evidence remains
unknown until acquired; unsupported GS save/hash/full-footprint getters are
explicitly absent. General refit capacity, arbitrary-world/road-stop content and
company-specific construction feasibility remain deferred rather than mandatory.

## 7. Exact 15.3 native authority

See [native API audit](p08-15-3-native-fact-api-audit.md) for every C++/GS symbol,
argument/return type, units, sentinel, mode restriction and primary-source link.
It uses tagged **15.3**, not historical 13.4 fixtures. Confirmed reads cover tile
height/slope/predicates, industry-specific coverage lists, pair catchment,
station radius, road costs/availability/power/speed, engine list/availability/
default cargo/capacity/articulation/cost/speed, integer settings and NewGRF metadata.

Important corrected assumptions: running cost is per economy-year; engine speed
conversion remains 1.00584 but road speed cap uses 2.01168; deity engine availability
is public availability, not every company's permission; tile production is producer
count. Generation seed is a readable integer setting, not a save identity. NewGRF
IDs exclude static GRFs and do not hash files. There is no supported GS prepared-save
SHA, loaded-save-byte SHA, installed base-set file SHA or generic depot_class getter.

All proposed acquisition is read-only. No build commands or company creation are
used as probes. Native construction implementation only establishes supported
geometry/unit restrictions; it does not prove a candidate will later construct.

## 8. Concrete future minimum-fact schema

The following frozen typed schema is a contract for the **next controlled task**,
not implemented DTOs. Compose existing IDs/provenance; do not duplicate WPO.

```text
MinimumRoadPlanningFactsV1
    source: ObservedPlanningSource | ControlledPlanningFixtureSource
    world_observation_digest: SHA256
    region: PlanningRegion(rectangle global coordinates, maximum 256 tiles)
    tiles: tuple[PlanningTileFact]                 # exact region, ordered native IDs
    coverage: tuple[IndustryCargoCoverage]         # exact selected native pair/sink
    road: OrdinaryRoadFact                        # type, availability, speed cap
    engines: tuple[DefaultCargoRoadEngineFact]     # ordered unique IDs, bounded 32
    costs: NativeRoadCostFacts                     # explicit piece/stop/depot units
    profile: CalendarEconomyFlatRoadProfileV1      # content/catchment/time authority
    capture: SupplementalCaptureIdentity          # M2 brackets, provenance/receipts

PlanningTileFact
    tile_index, x, y, height_levels, slope_mask
    vacant_build_eligible; exclusion predicates
    industry_id: native ID | absent

IndustryCargoCoverage
    source_industry_id, destination_industry_id, cargo_id
    pickup_tiles, delivery_tiles: sorted unique tuple[TileIndex]
    per_tile_producer_count / acceptance_eighths
    effective_radius_tiles; bounded region correspondence
    complete [derived from validated terminal pages, counts and exact coverage]

DefaultCargoRoadEngineFact
    engine_id, default_cargo_id, road_type, public_available, articulated
    capacity_cargo_units, purchase_gbp, running_gbp_per_economy_year
    maximum_speed_native_units

MinimumRoadPreparationPolicyV1
    configured benchmark start_date; horizon_days
    cargo label mapping = native uppercase hex H -> planner Identifier "cargo-" + H
    supply policy = qualified-month historical-OD benchmark (no forecast)
    default-cargo-only; non-articulated; freight; ordinary road; flat vacant region
    stop/depot footprint1x1; deterministic order/limits
    cost policy = explicit road pieces + stop/depot base costs
    running cost normalization = calendar-economy annual /365, six-decimal half-even
```

Region ≤256 is a proposed supported-input cap, not permission to fetch every tile
in every world or change existing proof ceilings. A region that cannot include the
chosen OD/facilities/fronts/path is unsupported. Coverage lists can be filtered to
this explicit region only after complete native coverage metadata is verified;
they must not silently truncate source coverage and call it complete. Missing
coverage/unknown native values fail, not default to false/zero.

The label mapping is lossless even for non-text label bytes and produces a valid
P05 Identifier; reject duplicate native labels/mapping collisions. Fleet identifiers
use `road-engine-<nativeID>` with compact native bindings. Availability covers
benchmark day0 only (`available_from_day=available_through_day=0`), not future
engine introduction/retirement. Positive demand, deadline, manifest/source, capacity,
geometry, fixed-point and P06 action-count limits remain mandatory; unsupported
large quantities fail rather than being clipped. The road estimate is an explicitly
named piece-normalization benchmark, not an exact native command quote.

The engine catalog policy may require at least one valid supplied engine without
claiming catalog completeness, provided its source declares the exact deterministic
bounded selection predicate. If a complete catalog is claimed, paginate exact
coverage and fail overflow. This is different from mandatory exact supply-target
coverage, which cannot be reduced to the chosen OD.

Configured service demand is explicitly a benchmark request. Potential demand
from acceptance is not consumption; measured consumption is not required for the
minimum slice and is not manufactured. Qualified zero supply is retained in WPO;
selection can return no selectable positive OD without producing a scenario.

## 9. Bounded acquisition and thin GameScript feasibility

Keep application responses ≤512 bytes, below native GSAdmin.Send ≤1450 bytes.
Do not enlarge envelopes to native maximum. No handlers are implemented here.

Proposed families: profile/settings scalars; road costs/type scalars; one engine
record or deterministic engine-ID page; one tile record; tiny coverage-ID page;
and one selected tile/cargo catchment record. All request IDs/arguments/ranges/
output sentinels are validated in Python; GS performs only bounded native reads.
Reserve worst-case response envelopes before selecting records/page size. A safe
initial design uses one tile or engine record per response and coverage-ID pages
of at most eight uint32 IDs; reject any serialized result over512 rather than emit
partial success. Exact schemas/byte proofs belong to controlled contract tests.

Proposed independent ceilings for one region/OD: one profile read, one road/cost
read, up to64 bounded engine-ID pages plus32 engine records, up to64 coverage pages
(two lists), ≤256 tile reads, ≤512 pair catchment reads, and bounded scalar clock
guards. These are **design caps**, not a new native authorization or modification
of qualification's 304/1072/368080/9088/9094 frozen ceilings. A later supplemental
owner must audit worst-case bytes/frames/time and freeze its own authorization;
it may not append unbudgeted queries to V5. An exhausted coverage/catalog cap is
unsupported input, not a retry or silent subset.

Bind every batch to exact WPO/source/context/profile, declared finite region and
M2 capture brackets. Data collected in another runtime require an explicitly proven
saved-state chain; they cannot share an opaque original process handle by assertion.
Supplemental facts are non-atomic. Bounded dates, same-run provenance and profile
restrictions do not prove immunity to later geometry/availability changes; real
execution must revalidate its own conditions.

Full-map streaming is not default. Candidate-only reads without complete corridor
region cannot prove path feasibility. Offline save extraction is an alternative
only after a verified 15.3 parser/content/schema and source-state correspondence
contract; no such extractor is supplied or assumed here.

## 10. Identity creation points: keep seven layers distinct

| Layer | Creation and exact meaning | Current status |
|---|---|---|
| A Source prepared-save bytes | Owned actual file hash before staging/loading; original state | Missing for Attempt4, whose qualification used a generated world |
| B PreparedWorldManifest | Constructed after candidate generation; source digest, runtime/content/dimensions/seed, resolved planner sites/catalog/buildable tiles | Existing strict schema and controlled old P08 construction |
| C Loaded runtime | Owner proves actual process loaded exact staged A, with pinned binary/config/content and load evidence | Save-to-runtime relation missing; no retrospective claim |
| D Runtime after rollovers | Continuous process/connection/world/config/bridge while time/world can evolve | REAL-PROVEN qualification, not identical save bytes |
| E Final M2 structural observation | Fresh post-second-rollover structure with canonical structural digest | REAL-PROVEN |
| F M1 qualified production captured in M2 | Dynamic digest includes source E, production values and qualification; capture brackets separate | REAL-PROVEN |
| G Candidate-generation input | Composition of WPO + supplemental facts + policy + prepared-source links | Design-only; no candidate output here |

A source-save digest does not equal a post-rollover/final-save digest by assumption.
A runtime/world ID is not a hash of every world byte. Structural digest is not a
save digest. WPO digest is not prepared manifest fingerprint or planner scenario
hash. Optional final save S2 must hash its own actual bytes and record a separate
capture relation; it cannot rewrite A or replace the qualified source identity.

## 11. Typed prepared-source provenance contract

Proposed immutable contract (not yet implemented):

```text
PreparedSaveIdentityV1
    save_sha256: SHA256; byte_count: positive int
    native_version, content_identity
    save_role: Literal["input_prepared", "post_qualification_capture"]
    evidence_digest                               # owner evidence; paths excluded

SourceToRuntimeLoadV1
    prepared_source: PreparedSaveIdentityV1
    runtime: existing RuntimeIdentity
    world/config/bridge references: existing observation context identities
    owner_load_evidence_digest
    staged_bytes_identity == prepared_source.save_sha256
    process/connection ownership: exact context references

QualifiedSourceChainV1
    load: SourceToRuntimeLoadV1                    # mandatory only for saved-source claim
    observation: WorldPlanningObservation
    supplemental_facts_digest
    optional final_save: PreparedSaveIdentityV1
    final_capture_correspondence_evidence_digest
    preparation_policy_digest

CandidateSourceIdentityV1
    world_observation_digest; supplemental_facts_digest
    preparation_policy_digest; source_chain_digest
    # later sidecar links native industry/cargo/lifetime + candidate SourceReference
```

No persisted object address/path enters semantic identity. Opaque handles are
live owned references only. Persisted real artifacts need a trusted importer
that validates ownership/evidence lineage and constructs one shared provenance
context; recreating equal-looking strings is not proof of a same run.

Required future saved-source proof: hash original and staged bytes, protect their
ownership against substitution, validate pinned binary/content/config and the
exact load invocation, retain successful engine load/lifecycle evidence (argv
intent alone is insufficient), correlate authenticated welcome and native facts
with that owned loaded runtime, and retain uninterrupted qualification. Native
API has no checksum-of-loaded-save getter; load evidence is an external owner claim
backed by process/bytes/native correspondence, not independent production evidence.

If real execution is intended from a post-qualification save, capture/hash **new**
save bytes and establish exact correspondence to final observed/fact source state.
Pausing/saving/loading or another process needs separate future authorization and
coherence rules. Do not substitute a new saved world for the continuous qualification
runtime or assert an atomic correspondence from two adjacent log timestamps.
Prepared execution may use a distinct loaded process only through explicit saved
state provenance; it does not become the original qualified connection.

| Relation | Evidence status now |
|---|---|
| Generated world config/binary/content owner → qualification runtime | ALREADY REAL-PROVEN under V5's generated profile |
| Original prepared-save bytes → actual loaded runtime | MISSING; proposed typed contract DESIGN ONLY |
| Runtime → continuous M0/M1/M2 clocks/structure/producer lifetimes/production | ALREADY REAL-PROVEN |
| Final structure → qualified production exact source/coverage | ALREADY REAL-PROVEN and CONTROLLED-VALIDATED |
| Typed qualification objects → WPO admission/digest | CONTROLLED-VALIDATED this task |
| WPO → 15.3 terrain/engine/cost facts | DESIGN ONLY / native acquisition MISSING |
| Final state → final saved bytes → executable prepared world | MISSING |
| Old synthetic save/snapshot → old P08 manifest/scenario | CONTROLLED-VALIDATED only, not real15.3 loading |
| WPO/facts/source chain → P08 input/candidates/scenario | DESIGN ONLY; adapter NOT IMPLEMENTED |

A controlled fixture source is a distinct typed fixture identity backed by immutable
fixture bytes and explicit synthetic-runtime context. It can test source/manifest
validation without claiming real loading. A real observed source must require
accepted proof/owner evidence. No generic true flag, `force` or fallback to fixtures
may change one into the other. Both require qualified production admission.

## 12. World fingerprint and manifest compatibility

Retain PreparedWorldManifest and create the candidate-dependent manifest only
once inputs/candidates are validated. Retain the existing source_digest meaning
for its saved-world execution branch. For a manifest describing post-qualification
planning state, source_digest must identify the actual post-qualification capture
S2 with proven final-state correspondence, not the original input save A. A remains
the load predecessor. Without S2/correspondence, do not publish a real executable
manifest for these observations. Bind original and final save identities
separately when they differ; do not silently choose whichever hash is available.

`world_manifest_hash(manifest)` is the sole downstream world_fingerprint. It hashes
canonical manifest fields, including prepared-save source, native/content pins,
map/seed, planner resolved sites, cargo/vehicle labels and buildable tiles. It is
not merely a save hash or structural observation hash. Scenario hash additionally
binds quantities, economic assumptions, fleets and candidate costs; P05/P06/P07
use these identities. No new competing world fingerprint is introduced.

Use separate WPO/facts/source/policy digests in provenance sidecars and compact
SourceReference values. Candidate-to-observed native pair/lifetime references must
resolve exactly; do not dump observations into every candidate or relabel runtime
world_id as a native save fingerprint. Current P03 staging checks actual source
save bytes against manifest source_digest and is unchanged.

## 13. Validation gates, limitations and concrete blockers

Future minimum input admission requires: valid WPO; all exact qualified target
references retained; positive chosen benchmark OD if producing a scenario;
resolvable freight label/cargo/native industry references; coherent supplemental
source/profile/content/time scope; exact complete finite region and coverage;
strict flat vacancy/front/footprint/connectivity; compatible available default
road engine and positive capacity; supported native units/cost normalization;
actual saved-source identity if claiming prepared-world execution; and existing
P05 scenario/manifest/source invariants. Fail with typed missing/unsupported/limit/
identity/reference/provenance errors, no accepted partial scenario.

The contract is sufficiently concrete for **controlled supplemental fact DTO and
source-contract implementation**. Blockers remaining for *real P08 integration*:
new bounded query handlers and evidence/accounting; actual native region/engine/
cost/seed observations; saved-source-to-runtime/final-state capture proof; trusted
accepted-evidence importer; the 15.3 region/coverage input and candidate port;
company/execution feasibility and downstream save correspondence. None is solved
by the qualified supply observation alone.

Known limits: one freight OD historical benchmark; no measured sink consumption;
no prediction/forecast, refit/articulation, rail, terrain modification, clearing,
existing infrastructure reuse, universal road network reachability, atomic state,
independent production source, or construction-success guarantee. Proposed cost
normalizations are planner policy, not native command-test receipts.

## 14. Small remaining milestones and verification

1. Implement the documented pure supplemental/source DTOs and strict fixture
   validation, exact finite-region/pair coverage, units/cost/label/source chain tests.
2. Implement a trusted accepted-artifact issuer/importer with real-versus-controlled
   source separation; preserve current historical acceptance/immutable lineage.
3. Implement the pure P08 adapter and explicit bounded-region/coverage generator
   input port in a separately scoped task; preserve existing P05 semantics.
4. Validate candidate combinations and manifest/source/scenario/P05 bindings using
   controlled data; no native authority inferred from fixtures.
5. Separately design, budget and authorize native supplemental acquisition and
   saved-source/final-state proof before claiming real15.3 P08 integration.

Qualification cadence/limits and dispatch remain unchanged: interval1 second,
deadline300 seconds, clock304, applications1072, bytes368080, query operations9088,
post-auth frames9094; M0→M1→M2, exact targets/lifetimes, fresh M2 production and guard,
production_level excluded. No mutation, executor, optimizer objective or P08 code
is changed here.

Final verification and worktree-integrity results are recorded below.

**READY FOR CONTROLLED P08 SUPPLEMENTAL FACT CONTRACT IMPLEMENTATION**

## 15. Final controlled verification and worktree report

- Pure import/compatibility and WPO domain tests: **34 passed**. Fresh interpreter imports load no Admin/secure transport/GameScript execution/P08/OR-Tools/process lifecycle.
- Golden before-refactor structural/production bytes and digests: **PASS**. Moved definition bodies and pure protocol AST: **unchanged**.
- Focused P03–P08/observation/qualification/transport suite: **1,070 passed, 1 skipped**.
- Initial serial suite found a missing legacy CargoCatalogRecord export; exact reproduction retained, export restored, compatibility assertion added. Isolated compatibility/domain recheck: **35 passed**. No semantic validator or historical fixture was weakened.
- Final serial ordinary suite: **2,738 passed, 39 skipped**, 262.48 seconds. Initial failed verification log is retained under `/tmp/p08-prerequisites/ordinary.log`; final log is `ordinary-final.log`.
- Ruff: **PASS**; format: **PASS**, 352 files already formatted; applicable scoped typecheck: **PASS**. `git diff --check`, new-document whitespace/links and import audit: **PASS**.

| Ordinary-suite group | Passed | Skipped | Failed |
|---|---:|---:|---:|
| Pure-type and WorldPlanningObservation | 34 | 0 | 0 |
| Structural observations/proof | 117 | 0 | 0 |
| Production/raw coverage/proof | 266 | 0 | 0 |
| Qualification/native clock/lifetime/accounting | 224 | 1 | 0 |
| P08 preparation/probe/lifecycle | 78 | 0 | 0 |
| P05 optimizer | 37 | 0 | 0 |
| Planning/P02/P03 | 97 | 1 | 0 |
| P06/P07 | 56 | 0 | 0 |

Remaining bridge/transport/Admin/P04/lineage/lifecycle regressions also pass in the ordinary suite. Native/PostgreSQL opt-ins remain skipped; no native flag or public proof CLI was used.

Baseline files hashed: **2947**; intended existing source files changed: **25**. Every other baseline file is byte-identical. Historical artifacts, Attempt4 PASS, Attempts1–3, V1–V5, complete-raw/production proofs, old controlled fixtures, CONTEXT.md and the prior audit are unchanged.

Files changed by this task:

- `app/simulation/openttd/cargo_catalog.py`
- `app/simulation/openttd/cargo_page.py`
- `app/simulation/openttd/cargo_page_evidence.py`
- `app/simulation/openttd/gamescript_bridge.py`
- `app/simulation/openttd/gamescript_protocol.py`
- `app/simulation/openttd/industry_capability.py`
- `app/simulation/openttd/industry_cargo.py`
- `app/simulation/openttd/industry_cargo_evidence.py`
- `app/simulation/openttd/industry_inventory.py`
- `app/simulation/openttd/industry_page.py`
- `app/simulation/openttd/industry_page_evidence.py`
- `app/simulation/openttd/industry_production.py`
- `app/simulation/openttd/industry_production_evidence.py`
- `app/simulation/openttd/production_observation.py`
- `app/simulation/openttd/production_session.py`
- `app/simulation/openttd/qualification_clock.py`
- `app/simulation/openttd/qualification_evidence.py`
- `app/simulation/openttd/qualification_session.py`
- `app/simulation/openttd/qualification_stability.py`
- `app/simulation/openttd/qualification_state.py`
- `app/simulation/openttd/runtime/identity.py`
- `app/simulation/openttd/structural_world.py`
- `app/simulation/openttd/structural_world_session.py`
- `app/simulation/openttd/world_info.py`
- `app/simulation/openttd/world_info_evidence.py`
- `app/simulation/openttd/capability_observation.py`
- `app/simulation/openttd/catalog_observation.py`
- `app/simulation/openttd/observation_identity.py`
- `app/simulation/openttd/observation_protocol.py`
- `app/simulation/openttd/observation_session_evidence.py`
- `app/simulation/openttd/qualified_production.py`
- `app/simulation/openttd/world_planning_observation.py`
- `docs/p08-15-3-minimum-facts-and-source-identity.md`
- `docs/p08-15-3-native-fact-api-audit.md`
- `tests/fixtures/observation_type_compatibility.json`
- `tests/test_observation_type_boundary.py`
- `tests/test_world_planning_observation.py`

Pre-existing work preserved exactly: README.md, docs/srs.md, docs/specs/planning-executor-boundary.md, .env.example, CONTEXT.md, app/planning/preparation/, docs/specs/p08-world-preparation-design.md, prior audit, historical P08 fixtures/tests, and ther.md. Original unrelated tracked diff is byte-identical. HEAD unchanged; index empty. Staged **NO**, commit **NO**, push **NO**. Native launches **0**, live Admin connections **0**, real requests **0**. No native freeze or adapter created.
