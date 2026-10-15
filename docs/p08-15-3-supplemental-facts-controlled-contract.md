# OpenTTD 15.3 controlled supplemental planning facts

This implements the next controlled seam after `WorldPlanningObservation` (WPO),
not a P08 adapter, native query handler, save parser, or construction proof.
`CONTEXT.md` remains architecture authority. Native meanings come from
[pinned 15.3 API audit](p08-15-3-native-fact-api-audit.md); the older untracked
13.4 preparation implementation is preserved, not adopted as native authority.

## Implemented interfaces

- `app/simulation/openttd/supplemental_planning_facts.py`: frozen strict Pydantic
  DTOs, complete bounded-region validation, canonical serialization/digest,
  observation references and cross-reference validation.
- `prepared_source_correspondence.py`: distinct manifest/save/observation identities,
  explicitly controlled or missing correspondence and a fail-closed real execution gate.
- `planning_fact_artifacts.py`: bounded read-only accepted artifact and save-fixture
  importing through owned directory descriptors, exact byte hashes and semantic validation.
- `planning_fact_input.py`: frozen `ValidatedPlanningFactInput` composes existing
  WPO, supplemental facts and correspondence. It revalidates inputs, exact source
  identities, M2 temporal brackets, seed and same-owned-run correspondence.

Domain imports load no AdminPort, secure transport, GameScript execution, runtime
process manager, P08 generation, OR-Tools or P05 implementation. Existing pure
`app.planning.domain.Contract`, `Digest`, `PreparedWorldManifest` and
`world_manifest_hash` are reused; no industry/cargo/production/fingerprint model
is duplicated. No existing WPO gate, observation serialization or digest changes.

## Road-only supported slice

The future consumer may attempt one qualified-supply-to-acceptor **benchmark**,
two 1×1 freight stops, one 1×1 depot, a corridor confined to the declared region,
and one non-articulated default-cargo ordinary-road engine. Python retains all
candidate enumeration, geometry, path search, rounding and policy decisions.
No engine selection or candidate generation occurs at this interface.

Rail, air, ships, articulated vehicles, refitting, tram/custom-road types,
existing infrastructure reuse, clearing, terraforming, bridges/tunnels, advanced
station layouts, measured consumption demand and whole-map extraction are deferred.
Minimum terrain policy can conservatively reject any non-flat/non-vacant location;
the DTO retains negative observations rather than turning them into buildability.

An admitted fact input does **not** guarantee a feasible candidate or nonzero supply.
Zero production and fully qualified empty target sets remain valid. A future adapter
must require an explicit usable pickup/delivery scope and compatible available engine
for its chosen benchmark; otherwise return a typed no-candidate/no-supply result.
`require_road_service_facts(industry_id, acceptor_id, cargo_id)` validates that
explicit pair against positive qualified supply, distinct acceptor, declared
pickup/delivery coverage, freight catalog membership and at least one publicly
available compatible default-cargo engine. It selects neither the pair nor an
engine and makes no corridor/buildability guarantee. It must never invent missing
coverage or costs. P05 still requires positive demands
and nonempty candidate/fleet/location collections when actually building a scenario.

## Field semantics and strict ranges

Every field is required unless explicitly nullable. Booleans are strict JSON
booleans; integer fields reject bool, floats and strings. IDs in different columns
remain separate native namespaces. Invalid native results must be rejected before
constructing DTOs, except the documented nullable industry sentinel normalization.
All facts depend on the bound world/config/content and M2 capture interval.

| DTO / fields | Source and meaning | Units/range; invalid/optional handling |
|---|---|---|
| `FactSource.world_observation_digest`, `structural_digest`, `production_digest` | Existing WPO/structure/production semantic identities | Lowercase SHA-256, exact WPO match; not save digests |
| `world_id`, `runtime_digest`, `configuration_digest`, `bridge_digest` | Existing owner context | World ID 1–64 characters; SHA-256 fields exact context match; metadata cannot establish live handle ownership |
| `content_digest` | Accepted external installed-content manifest identity | SHA-256; must match settings; no native file-hash getter or origin claim |
| `map_width`, `map_height` | Existing world dimensions | Tiles, 1–65536, exact WPO match |
| `Region.x/y/width/height` | Declared global-coordinate rectangle | Nonnegative origin, positive dimensions, area ≤256; inside map |
| `TileFact.tile_id/x/y` | GSMap tile conversion | Tile index = y×map_width+x; global coordinates, exact region membership; no duplicate/omitted tile |
| `min_height` | GSTile.GetMinHeight | Height levels; supported controlled profile 0–255, not a claim of a universal native 0–15 limit; -1 rejected |
| `slope` | GSTile.GetSlope | Native corner/steep bit value 0–31; 0xFFFF rejected; only 0 usable by minimum flat policy |
| `buildable` | GSTile.IsBuildable | Predicate, not final construction permission, vacancy or price |
| `water/coast/tree/farm/rock/rough` | Audited GSTile predicates | Strict bools; validate tile before interpreting false |
| `road/rail/water_transport/air_transport` | GSTile.HasTransportType for four legal types | Strict bools; infrastructure presence, not generic ownership |
| `industry_id` | GSIndustry.GetIndustryID(tile) | 0–63999 or None for audited invalid/non-industry result; non-null must resolve to structure |
| `CoverageScope.industry_id/cargo_id/role` | Explicit selected relationship scope | Industry 0–63999, cargo 0–63, pickup/delivery; relationship must resolve to produces/accepts |
| `CoverageFact.tile_id/industry_id/cargo_id/role` | Potential 1×1 stop coverage at each scoped tile | Every region tile for every declared scope, unique exact keys; no implication about other relationships/regions |
| `producer_count` | GSTile.GetCargoProduction(tile,cargo,1,1,radius) | Count of producers, 0–2³¹−1; -1 rejected; **not production quantity** |
| `acceptance_eighths` | GSTile.GetCargoAcceptance with same geometry | Eighths, 0–2³¹−1; -1 rejected; ≥8 eligibility, not consumption/delivery |
| `industry_covered` | Audited industry-specific producing/accepting tile-list membership | Strict bool; combines geometry with pair-specific scalar; not an operational station |
| `ContentSettings.generation_seed` | Audited resolved generation seed setting | uint32 excluding random sentinel 2³²−1; equals manifest seed |
| `modified_catchment`, `serve_neutral_industries` | Audited station settings | Strict booleans; no manufactured station/company |
| `effective_truck_stop_radius` | GSStation.GetCoverageRadius(TRUCK_STOP) | 3 when modified, 4 otherwise; -1 rejected; settings equality enforced |
| `timekeeping`, `context`, `gameplay_newgrf_ids` | Audited settings and collection profile | Literal calendar, deity-public, empty tuple; no wallclock/custom gameplay content |
| `RoadFacts.road_type_id/public_available` | GSRoad availability | Exactly ordinary road 0, true; unavailable/sentinel rejected |
| `max_speed_native` (road) | GSRoad.GetMaxSpeed | 0–65535, 0 unlimited; -1 rejected; ×2.01168 km/h, distinct from engine units |
| `road_piece_cost_gbp/truck_stop_cost_gbp/depot_cost_gbp/currency` | GSRoad.GetBuildCost for ROAD/TRUCK_STOP/DEPOT | Native integer GBP, 0–2⁶³−1, currency literal GBP; -1/missing rejected; road **piece**, not corridor quote |
| `EngineFact.engine_id` | Validated GSEngineList ROAD ID | 0–65534, unique; invalid/non-road excluded by acquisition contract |
| `default_cargo_id`, `engine_road_type_id` | GSEngine.GetCargoType/GetRoadType | Cargo 0–63 resolving to catalog; road 0–63 matching supported road; invalid sentinels rejected |
| `public_available` | GSEngine.IsBuildable under deity public scope | Strict bool retained; false means ineligible, not assumed available to every company |
| `articulated`, `has_power_on_road` | GSEngine.IsArticulated / GSRoad.RoadVehHasPowerOnRoad | Exactly false / true for supported engine records; incompatible excluded |
| `capacity_cargo_units` | GSEngine.GetCapacity for supported default cargo | 1–65535 cargo units; -1 rejected; no refit capacity inference |
| `purchase_cost_gbp` | GSEngine.GetPrice | Native integer GBP, 0–2⁶³−1; -1 rejected, current context-dependent quote |
| `running_cost_gbp_per_economy_year` | GSEngine.GetRunningCost | Same integer GBP bound per economy-year; not observed daily cost |
| `max_speed_native` (engine) | GSEngine.GetMaxSpeed | 1–65535; -1 rejected, ×1.00584 km/h; maximum, not average travel speed |
| `capture_economy_date_before/after` | Claimed accepted-artifact capture bracket | Native economy date ordinal 0–2³¹−1, nondecreasing inside final M2; not qualified M1 boundaries or native receipt proof |

Company-relative construction permissions, balance, station spacing and town
ratings remain absent. Public availability is not a future company guarantee.
A conservative two-road-piece/tile cost estimate and economy-year/365 daily cost
normalization belong to separately named future calendar benchmark policy, not
these native-unit facts. No price/capacity/geometry is fabricated for P05.

## Coverage, limits and canonical identity

A rectangle contains at most 256 tiles, covering bounded stop/front/depot/corridor
search for this controlled slice. Every tile has all required tile fact fields.
Up to two distinct industry/cargo/role scopes support the one-OD minimum;
each scope requires values for **every** region tile (including false/zero results).
Thus at most 512 coverage records. Up to 32 engine records support bounded fleet
alternatives; extra, missing, duplicate and out-of-region identities reject.
Coverage lists and engine catalogs make no whole-world completeness claim.
A location or relationship outside those scopes is unavailable, never implicitly vacant.

`to_bytes()` is sorted-key compact UTF-8 JSON. Tile records sort by native tile ID,
coverage scopes by industry/cargo/role, coverage by tile/industry/cargo/role,
engines by engine ID. Duplicates reject before sorting. `semantic_digest` hashes
these bytes, including schema, profile/settings/content, source semantic identities,
region, facts and semantically meaningful economy brackets. Input order, whitespace,
paths, request IDs, pagination, receipts and wallclock timestamps are absent.
This does not replace PreparedWorldManifest/world_fingerprint or WPO digest.

## Accepted artifact v1

Strict JSON envelope:

```json
{
  "schema_version": 1,
  "source_class": "CONTROLLED_FIXTURE",
  "facts_digest": "<sha256 of canonical facts>",
  "facts": "<SupplementalPlanningFacts JSON object, not a string>"
}
```

The placeholder above describes the shape; tests contain executable structured
examples. `source_class` accepts only CONTROLLED_FIXTURE or SOURCE_BYTES_VERIFIED.
The importer takes an owned directory, relative file path, accepted expected exact
byte SHA-256 and the admitted WPO. It hashes exact read bytes before parsing,
checks the canonical facts hash and expected WPO, rejects duplicate JSON keys,
nonfinite/malformed JSON, extra schema fields, conflicting references and limits.
The importer additionally resolves full WPO source identities, production/structural
references and M2 capture coherence. Assembly repeats those checks and validates
manifest/same-owner coherence.
Source classification never establishes actual native acquisition.

Maximum artifact and controlled save-fixture file size: **256 KiB each**. This is
a controlled importer bound sized for 256 tile + 512 coverage + 32 engine compact
records plus metadata; it is neither a native Admin budget nor permission to import
arbitrary production saves. Oversized inputs reject; future real-save import needs
its own appropriately bounded contract. JSON recursion failures reject. Read counts
are bounded even when a file grows. Files must be regular; files/directories below
the explicitly owned root are traversed with directory descriptors and O_NOFOLLOW.
Absolute, empty, dot/parent components, backslash paths, symlinks and special files
reject. Caller supplies the owned root; this is not a general filesystem sandbox.
No artifact is modified, copied into historical evidence or executed.

Hash checks establish exact accepted-byte identity, not truth of factual claims.
Even SOURCE_BYTES_VERIFIED cannot imply REAL_RUNTIME_CORRESPONDENCE_PROVEN.
The real classification exists as vocabulary but is not issuable by this importer.
See [correspondence contract](p08-15-3-prepared-source-correspondence-contract.md).

## P05 compatibility and future adapter inputs

| Mandatory PlanningScenario input | Classification / future source |
|---|---|
| Version, scenario ID, start/horizon, economics, constraints | DERIVABLE from explicit benchmark policy; not observed or auto-filled here |
| Map/native pins/seed | AVAILABLE WPO dimensions/runtime; CONTROLLED ONLY content/settings pins |
| Source save and canonical manifest fingerprint | CONTROLLED ONLY byte import + manifest; real correspondence still missing |
| Cargo labels/native relationships/industry anchors | AVAILABLE authoritative structural catalog/capability/inventory |
| Demand quantity | AVAILABLE qualified raw supply; positive chosen OD required for scenario; accepting capability is benchmark sink eligibility |
| Stops/depot/front geometry, resolved sites, locations | DERIVABLE by future Python generation from complete scoped tile/coverage facts; not implemented |
| Road segment geometry and costs | REQUIRES SUPPLEMENTAL FACT + explicit piece-count policy + future bounded search; not guaranteed buildable |
| Fleet definitions/capacity/compatibility/purchase/running/speed | CONTROLLED ONLY imported facts + explicit normalized policy; native acquisition missing |
| Candidate provenance/source references | DERIVABLE from existing WPO/facts/source/manifest identities; future adapter work |
| Nonempty candidate/fleet/demand sets and coherent IDs | STILL REQUIRES future generation and existing P05 validators; admission alone does not produce them |

The future adapter consumes `ValidatedPlanningFactInput` plus explicit benchmark
policy. It must validate required chosen coverage and usable engine/candidate facts,
map supply exclusively from complete qualified production, retain exact targets,
use acceptance as configured OD eligibility, carry compact source digests/references,
and preserve numeric industry ID plus final structure and producer lifetime provenance.
It must return typed no-supply/no-coverage/no-engine/no-route failures as applicable.
No existing P05 invariant/objective or historical P08 implementation is changed.

## Remaining work and claim boundary

1. Implement the separately scoped pure P08 adapter and explicit bounded-region,
   coverage-backed Python generation port, keeping historical 13.4 files intact.
2. Controlled end-to-end manifest/scenario/P05 tests using admitted fixtures.
3. Design/budget/authorize bounded native settings/tile/coverage/engine/cost handlers.
4. Prove actual supplemental acquisition and post-qualification save/load linkage.
5. Separately prove company/executor construction validity.

Qualified production remains real-proven. These contracts/importers are controlled
only. Native supplemental facts and executable saved-source correspondence remain
unproven. No native handlers, adapter, freeze, gameplay mutation or real runtime
activity are introduced. Historical proof and pre-existing work remain unchanged.

## Controlled verification and worktree integrity

- New supplemental/import/correspondence tests: **65 passed**. Combined with existing
  WPO/pure import-boundary tests: **99 passed**.
- Final settled serial ordinary suite (`pytest -m 'not openttd'`): **2803 passed,
  36 skipped, 3 deselected**, 285.43 seconds. Existing P03–P08, P05/preparation,
  structural/production/qualification/provenance, bridge and transport regressions pass.
- Ruff, repository format check (359 files), scoped new-module typecheck,
  diff/whitespace and import-boundary audits: **PASS**.
- An earlier overlapping verification run rejected a controlled raw proof because
  this task edited `planning_fact_artifacts.py` after that test froze source.
  Retained controlled source-freeze comparison identifies that exact changed file.
  Isolated reproduction against settled source: **1 passed**. The final serial run
  above ran without concurrent source/document edits and passed. Failure logs are
  retained under `/tmp/p08-controlled-contracts/ordinary-final.log`; final log is
  `/tmp/p08-controlled-contracts/ordinary-settled.log`. No historical evidence changed.
- Baseline HEAD remains `6a0da37fe2d43c5937fc14279816dfa5af79472e`.
  All **1507 pre-existing files**, including **942 artifact files**, remain
  byte-identical. Initial worktree: 28 tracked modifications, 23 untracked status
  entries. This task adds only four source modules, one test file and two documents.
- OpenTTD launches / live Admin connections / real requests: **0 / 0 / 0**.
  Native handlers, native freezes, P08 adapter, staging, commit and push: **NONE**.

**READY FOR CONTROLLED P08 ADAPTER IMPLEMENTATION**. Native supplemental acquisition,
trusted save/runtime/final-save correspondence and real construction validity remain
separate future proof blockers, not claims granted by these controlled contracts.
