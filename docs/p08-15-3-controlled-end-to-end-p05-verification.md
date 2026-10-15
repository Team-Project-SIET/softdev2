# Controlled P08 to P05 end-to-end verification

Architecture authority: local `CONTEXT.md`. Baseline HEAD:
`6a0da37fe2d43c5937fc14279816dfa5af79472e`. This is controlled offline integration
verification of the existing contracts. It creates no native proof, coordinator,
production CLI, executable-source receipt or proof freeze.

## Exact tested path

`tests/test_p08_controlled_e2e.py` composes the existing public functions directly:

1. Check accepted recipe, manifest and correspondence bytes against
   `tests/fixtures/p08_controlled_e2e/accepted-digests.json`. Decode the recipe using
   a test-only strict `Contract` model and the two existing manifest/link models.
2. Use the existing controlled `QualificationWire`/`collect` fixture to produce
   genuine validated structural and qualified-production **models** over an
   in-memory fake stream. Construct
   `WorldPlanningObservation(result.verification.stability.final, result)`.
   All evidence, qualification and WPO validators run. There is no persisted-WPO
   importer in the current contract; the recipe is not a new WPO serialization.
3. `import_planning_facts(root, "supplemental.json", expected_bytes_digest=...,
   world=world)` checks owned file bytes, size, JSON/schema, semantic digest,
   source identity, references, declared coverage and provenance.
4. `import_prepared_source(root, "original-source.bin", world=world,
   manifest=manifest, links=links)`
   verifies controlled source bytes and admits controlled correspondence.
5. `ValidatedPlanningFactInput(world, imported.artifact.facts, prepared.correspondence)`
   re-enters authoritative admission without bypassing any validation.
6. `adapt_planning_facts(admitted, MonthlyBatchPolicy(...))` returns
   `BoundedRoadInput`; `generate_road_scenario(input)` returns a controlled scenario
   or typed no-scenario outcome.
7. Round-trip the actual `PlanningScenario` schema, call
   `optimize_candidate_network(scenario)`, and independently check the result with
   `validate_execution_plan(result.plan, scenario)` and semantic/cost/fleet oracles.

The positive path does not instantiate internal candidate models or mock admission
validators. Only the native wire/catalog/capability fixture is controlled. The
source byte fixture is deliberately not an executable OpenTTD save.

## Historical supply and benchmark policy

The controlled stream preserves M0 baseline, qualified M1 (February 1950), and
final collection M2 (March 1950). Production is collected at M2 and records the
qualified historical M1 quantity. Final structure supplies the planning source;
neither period is replaced by the configured planning calendar.

The fixture has one producing industry and one accepting industry. Their numeric
IDs and cargo are recipe parameters, rather than generator constants. Capability,
freight catalog identity and admitted catchment all match. Quantity is 120
`cargo_units`, with no measured consumption. Acceptance is a potential receiving
relationship. Equivalent reordered artifact collections select the same OD.

Policy `qualified-month-batch-v1` assigns that historical quantity to January 2001,
31 days, under one assumed load per purchased vehicle. Separate tests check 28,
29, 30 and 31 days without changing qualified supply or its month. Capacity is 30
cargo units per vehicle; four vehicles serve 120 units. An independent oracle
finds the smallest integer fleet whose total capacity covers the quantity. Exact
division, remainder, minimum demand, fleet 64, fleet 65, zero capacity and large
quantity are exercised. Requirements above 64 return `CAPACITY_INFEASIBLE` and
are never clipped. There is no guarantee of future supply or actual trip time.

## Controlled geometry and bounds

The positive region contains 32 covered tiles. Generated facilities are pickup
139, delivery 144 and depot 76; depot front is connected to a corridor interior.
Corridor `[139, 140, 141, 142, 143, 144]` is cardinal, continuous and loopless.
Independent checks inspect every footprint/path tile, admitted catchment,
orientation/front, height, slope, occupancy and transport/terrain flags.
No unknown terrain, diagonal, unsupported crossing or fabricated existing road
is used. Controlled feasibility does not imply native construction legality.

One station pair uses 22 path expansions. Additional tests admit exactly 256
tiles, two scopes, 512 coverage records and 32 engines; reject each over-limit
artifact before search; and exercise all 16 station pairs. The unchanged search
bound is 4096 expansions. Ordinary overflow cannot arise under 16 pairs ×256
tiles; fault injection lowers the guard solely to verify its failure response.

That test reproduced one integration defect: an exhausted aggregate search guard
raised `AssertionError`. The minimal repair adds `RoadOutcome.SEARCH_LIMIT_EXCEEDED`
and returns `NoRoadScenario` at that guard. No algorithm, bound, P05 model, validator
or objective changes. The retained red logs are
`/tmp/p08-controlled-e2e/search-budget-red.log` and `initial-integration.log`.

## Independent costs and unchanged P05

Native fixture GBP costs are road piece 10, each stop 50, depot 100, engine purchase
1000. The independent oracle derives piece count from unique path neighbor edges
and the depot branch, rather than copying the generator's piece formula. Nine
pieces cost 90; two stops cost 100; depot costs 100: infrastructure 290. Four
vehicles cost 4000. Total planned CAPEX is **4290 GBP / 429000 pence**.

Tests compare this oracle with each generated cost, selected infrastructure,
actual fleet count, public result metrics and the real CP-SAT integer objective.
A test wraps the actual solver without changing its constraints/objective and
reads integer coefficients and integer solution values; no approximate floating
point comparison is used. Fixed-point precision cases also cover fractional GBP.
Budget 4290 is accepted; 4289.99 is rejected by generation and independently by
P05. Negative costs and mixed currencies fail authoritative artifact admission.

The annual native running cost is retained and normalized by `/365` with six
Decimal places, half-even, as benchmark daily metadata. Changing it does not
change planned CAPEX. P05 still minimizes infrastructure plus vehicle purchase
cost. A separate multi-demand P05 stress case reuses the same infrastructure and
charges it once, while scaling purchases with actual fleet groups. It is not a
second native supply observation. Duplicate candidate identities, dangling
dependencies, invalid relationships and corrupted plans are rejected by existing
typed optimizer/plan validation errors. Zero-capacity P05 input is infeasible.

The unchanged optimizer uses one worker and random seed zero, requires OPTIMAL,
then applies deterministic lexicographic tie-breaking. Demand served, vehicle
capacity, candidate references, selected dependencies and budget are checked.

## Identity, lineage and replay evidence

`verification.json` is a deterministic test golden record, not a native receipt.
It retains WPO/structural/production/supplemental digests, source byte and controlled
correspondence identities, input/projected manifest fingerprints, policy identity,
qualified month, OD/quantity/units, counts, candidate IDs, scenario/plan hashes,
solver status and exact independent cost/capacity results.

Projected fingerprint is exclusively `world_manifest_hash(scenario.world_manifest)`.
It preserves admitted prepared-source bytes/pins and includes candidate-dependent
sites/catalog. It is not WPO or structural digest. Reordering accepted facts changes
artifact byte identity but preserves canonical facts, candidates, manifest, scenario,
plan and objective. A genuine stop/catchment change changes candidate-dependent
identity while preserving original source byte identity.

Candidate sources and compact sidecars retain WPO, supplemental, input manifest,
policy and OD identities plus relevant tiles and engine. The P05 plan binds the
immutable scenario via `planner_inputs_digest`, projected fingerprint and selected
candidate IDs. The solution does not need a competing provenance schema.

Final pytest JUnit reports and a sorted, timestamp-free summary of executed
integration cases are retained under `/tmp/p08-controlled-e2e/`. Together with the
golden record they distinguish expected deterministic evidence from actual test
execution, including the negative cases. Transient logs/timestamps are not replay
identities. Existing historical records and imported fixtures are not rewritten.

## Negative outcomes and trust

Tests exercise wrong byte/source digest, runtime/content/settings mismatch,
incomplete coverage; unqualified/incomplete production and structural source
mismatch; zero production and empty qualified targets; absent stop/catchment/depot,
disconnection and occupancy; exhausted search guard; incompatible/unavailable/zero
capacity engines and fleet ceiling; missing facts, negative costs and mixed units;
budget/capacity/dependency/relationship infeasibility; and attempted real admission.
Valid zero/unserviceable observations remain valid and produce typed no-scenario
outcomes without constructing fake positive demand. Malformed artifacts fail
existing typed admission errors.

Artifact, correspondence, adapter, candidates and scenario remain
`CONTROLLED_FIXTURE` / `CONTROLLED_PLANNING_SCENARIO`. The prepared-byte wrapper's
`SOURCE_BYTES_VERIFIED` means only that controlled bytes were hashed. A successful
solve does not promote either classification. Real-executable admission still fails
closed. A positive pipeline test blocks process launch and socket/native access
and verifies its input bytes are unchanged.

Supported claims: `SCHEMA_VALID`, `CONTROLLED_CANDIDATE_FEASIBLE`,
`P05_MATHEMATICALLY_FEASIBLE`, `P05_OPTIMAL_SOLUTION_FOUND`.
`REAL_OPENTTD_CONSTRUCTION_FEASIBLE` and `REAL_OPENTTD_EXECUTION_VERIFIED` remain
NOT PROVEN. All native activity is zero. Three `openttd` tests are deliberately
deselected, rather than reported as passed:

- `tests/test_live_production_smoke.py::test_one_real_production_live_run`
- `tests/test_openttd_integration.py::test_real_fixed_seed_simulation`
- `tests/test_planning_transport_live.py::test_one_real_p03_setup_proof`

## Prerequisites for real OpenTTD 15.3 input

Native supplemental acquisition still needs separately reviewed bounded APIs and
same-run evidence for settings/content/seed, covered terrain/catchment, costs and
available compatible engines. Real prepared-save correspondence still needs owned
valid save bytes, load/capture evidence, final post-qualification state correspondence,
runtime/content/config pins and an accepted trusted issuer. Actual command legality,
company permissions/finance and execution require their own authorized native
verification. Controlled integration resolves none of those real-world claims.
