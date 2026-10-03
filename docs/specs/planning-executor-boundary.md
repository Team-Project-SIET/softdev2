# P01 — Simulation-Ready Planning Contracts and OpenTTD Executor Boundary

Status: P01 design specification, with current implementation context updated through
P04 (`84ccb61`). Planning schema: **v1**. P02 implements contracts and prelaunch
validation; P03 implements plan transport and runtime acknowledgement; P04 completes
Admin observation. The network optimizer, construction/purchase/order executor and
plan-attributed evaluation loop remain unimplemented. The target responsibilities
below remain design requirements, not claims that the complete loop exists.
See [current architecture and project status](../../README.md#current-architecture-and-project-status).

## 1. Problem statement

The product goal is profit-aware, multimodal route and fleet optimization evaluated in OpenTTD. Today, experiment strategies select and configure existing OpenTTD AIs. They do not produce Python-authored construction, route, or fleet decisions. The legacy delivery CVRP and persisted `Route` describe geographic shipments, trucks, and drivers, so neither is a simulation plan. A stable, replayable boundary is needed between a Python planner and an OpenTTD executor without moving optimization into the AI or disrupting the proven simulation/evaluation path.

## 2. Goals

- Specify what the planner receives, what it returns, and what a thin executor must execute or reject.
- Make road and rail first-class in v1, with mode-neutral identities and explicit mode-specific constraints.
- Bind each plan to a prepared world and experiment using versioned, deterministic artifacts.
- Keep planner estimates separate from final-save and Admin-observed outcomes.
- Define one high-level test seam: validate and stage a complete `ExecutionPlan` against a prepared world before OpenTTD launch. Exercise the same seam with a real, opt-in OpenTTD run later.

## 3. Non-goals

P01 does not implement a planner, optimizer, route construction algorithm, exact physical tile path optimizer, executor, AI control, closed-loop optimization, real-time replanning, dynamic rerouting, train scheduling optimization, ML, Kafka, GameScript, web UI, TUI redesign, legacy cleanup, packing integration, or air/water execution. It does not change routing, packing, database schema or migrations, the OpenTTD runtime, Textual, or OR-Tools.

## 4. Terminology

| Term | Meaning |
| --- | --- |
| `ScenarioConfig` | Existing experiment identity and OpenTTD configuration text; does not describe planner-visible cargo/sites. |
| `PlanningScenario` | Immutable, typed snapshot of planner-visible world, demand, options, economics, and limits. |
| `PlanningLocation` | Stable scenario-local node whose canonical position is an OpenTTD tile. |
| `RoutePlan` | Planned service and order intent for a cargo flow; never the legacy delivery `Route`. |
| `FleetOption` | A vehicle or consist choice available to the planner. |
| `FleetPlan` | Selected vehicle groups and counts for routes. |
| `InfrastructurePlan` | Explicit construction intent and build ordering. |
| `ExecutionPlan` | Immutable envelope containing all decisions required of the executor. |
| Prepared world manifest | Versioned evidence that scenario-local nodes, tiles, cargo and vehicle definitions resolve in the world to be launched. P02 represents this evidence and P03 validates supplied prepared-world facts; general world extraction/preparation is not thereby implemented. |
| Estimated / realized | Planner predictions / measured OpenTTD outcomes, stored and named separately. |

## 5. Current architecture and evidence

The active production path selects either `ExperimentService → OpenTTDLabRunner → OpenTTD → public save parser → experiment persistence` for batch execution, or `ExperimentService → LiveSimulationRunner → owned OpenTTD → Admin telemetry + explicit final save/public parser → experiment persistence` for live execution. Batch execution does not construct live observation dependencies. `SimulationRunner.run(config, run_id, artifact_dir)` returns `SimulationResult`. The live path prepares pinned OpenTTD 13.4/OpenGFX 7.1 assets and a private workspace, launches one owned process, observes it over loopback Admin, explicitly saves, parses the save via public OpenTTDLab, and records terminal evidence. [T17 production smoke](../live-production-smoke.md) proves the live path with SimpleAI road-only, one world, complete telemetry, final save, artifact hashes, and a persisted result. [T16 failure matrix](../live-failure-matrix.md) records existing startup, observation, finalization, and persistence failure handling.

`PlanningStrategy.configure` currently yields `PlanningConfiguration` plus `AIConfig`; baseline trAIns and SimpleAI road-only/multimodal strategies delegate actual planning to those AIs. `PlanningStrategyRecord` identifies this strategy selection, **not** a Python planner or a stored route plan. `LiveLaunchPreparation` currently accepts only these known strategy/configuration pairs, validates integer AI settings, and copies a pinned AI archive into a per-run workspace. P03 now supplies a separate explicit staging path in `app/planning/transport.py`:
Python validates, hashes and stages an `ExecutionPlan` and matching prepared-world
evidence into a generated data module packaged with `P03ThinExecutor`. The thin AI
consumes/decodes that plan, validates transported identities and runtime-world facts,
and acknowledges route, fleet-group and infrastructure-action IDs. It does not
perform infrastructure construction, fleet purchase or service-order execution;
its accepted receipt proves receipt/validation, not action execution. This path is
not yet accepted as plan input by the production `ExperimentService` or its pinned
external-AI launch preparation. [Runtime identity and proof coverage](../planning-runtime-world-identity.md)
describe Attempt #6 against the current thin-AI source.

`AdminObserver` is an observation seam, with outbound join, quit, subscription, poll, and ping packets. Its company-level economy and vehicle/facility counts do not reveal train consist, route-level throughput, or gross revenue and costs separately. The final parser currently exposes money, loan, current-period income, expenses, and cargo delivered, not a complete profit breakdown. The [retained prototype report](../../prototype/live_admin/REPORT.md) confirms these limits. Admin is not a general plan command channel.

The legacy `CVRPOptimizer` takes depot/customer latitude and longitude, kg demand, and 1–3 vehicle kg capacities, minimizes Haversine distance with OR-Tools, and returns depot-to-depot stops. `RoutingService` translates shipment, customer, and vehicle database rows and saves operational routes. Those IDs and its driver/shipment lifecycle cannot be relabeled into OpenTTD identities. The packing heuristic works on three-dimensional packages and loading sequence independently.

## 6. Target architecture

```text
scenario/world preparation → PlanningScenario + prepared world manifest
                                     ↓
                          Python planner/optimizer
                                     ↓
          ExecutionPlan (+ EstimatedPlanMetrics as separate estimate)
                                     ↓
            validate → hash → retain → stage → thin OpenTTD AI
                                     ↓
                    existing simulation runner
                                     ↓
           Admin telemetry + final save/public parser
                                     ↓
             RealizedSimulationMetrics + experiment outcome
```

Python owns optimization. The executor owns faithful setup and operation. The existing runner owns process lifecycle, observation, final save, and evaluation. A future candidate-selection loop can submit plans repeatedly but is outside P01.

## 7. Planning domain model and shared conventions

All contracts are immutable, strict, JSON-compatible typed records with no ORM entities, arbitrary extension dictionaries, or TUI models. IDs are nonempty, scenario-local stable strings unless explicitly defined otherwise. Each collection has deterministic ordering and duplicate IDs fail validation. Monetary amounts use fixed-point decimal strings in the scenario currency (v1: `GBP`); no binary floating point in canonical artifacts. Time is an integer OpenTTD game day relative to the scenario start, with day 0 at launch. Speeds use an explicitly named unit, never an unlabeled number. An optional `SourceReference` contains `source_kind`, `source_id`, and `source_version` or digest; it conveys provenance only and cannot become the canonical node, demand, or vehicle ID.

## 8. `PlanningScenario`

Required: `schema_version = 1`, `scenario_id`, `scenario_version`, `world_fingerprint`, OpenTTD and base-set pins, map `width_tiles`/`height_tiles`, `seed`, start game date, `horizon_days`, supported modes, locations, cargo demands, fleet options, infrastructure candidates, economic assumptions, and constraints. The world fingerprint binds generation settings **and** a prepared world manifest containing resolved sites, cargo definitions, engine availability and relevant map constraints. The seed alone does not prove industry placement or buildability. Planning cannot proceed on an unverified or changed manifest.

`economic_assumptions` names currency and versioned estimates for revenue, build/purchase/running costs, finance, and penalties; unknown parameters are explicitly `unavailable`, not zero. `constraints` holds typed budgets, permitted modes, service windows, and platform/train-length limits as applicable. Fields with no verified world source are absent from v1 scenarios rather than invented. Scenario records are independent of `ExperimentScenario` ORM rows and derived from explicit preparation/adapters.

## 9. `PlanningLocation`

Canonical identity is `location_id`, a stable scenario-local candidate site/node ID, with required zero-based integer tile `(x, y)` (`x` east/right, `y` south/down; `0 ≤ x < width`, `0 ≤ y < height`). `kind` distinguishes industry origin, industry destination, station candidate, depot candidate, and service waypoint. A verified `WorldReference` may add an OpenTTD industry/station identifier and world fingerprint; such runtime IDs are not portable plan identities. Sites include permitted modes, station/depot footprint or orientation constraints when known, and provenance. Multiple locations may occupy or refer to one tile only when their typed roles and occupancy rules allow it. Latitude/longitude may be translated by a future adapter, never used as the OpenTTD canonical coordinate.

## 10. `CargoDemand`

Required: `demand_id`, OpenTTD cargo type identifier **as resolved in the world manifest**, origin and destination `location_id`, positive integer `quantity`, explicit cargo unit (v1 `cargo_units`), earliest day, latest delivery day within the horizon, and source reference. Optional priority and service constraint use typed enums/limits. Demand is an intended transport quantity, not a parcel count, kg, volume, or guaranteed production. Cargo compatibility and actual availability must be checked against the prepared world; uncertain production is an explicit planning assumption.

## 11. `FleetOption`

Required: `option_id`, mode (`road` or `rail` in v1), verified OpenTTD vehicle type/family reference, compatible cargo types, capacity in cargo units per vehicle or wagon, purchase cost in GBP, running cost with time basis, speed with unit, availability period, and source/version. Reliability is optional only if a verified value and interpretation exist. Road options specify road vehicle class and depot compatibility. Rail options specify locomotive and allowed wagon options, each wagon's cargo/capacity/cost/length, locomotive cost/running cost/power or traction constraint where sourced, total length unit, and platform compatibility. Values must come from a pinned world/vehicle catalog; the current telemetry code does not supply them. These are choices, not purchased instances.

## 12. `RoutePlan`

Required: stable `route_id`, mode, ordered service nodes (`location_id` plus stop role), origin/destination, assigned `demand_id` and quantity, assigned `fleet_group_id`, referenced infrastructure IDs, stop/order intent, and provenance/constraints. Stop order specifies pickup, delivery, and any service/depot visits without relying on optimizer internals. V1 `path_kind = station_to_station_intent`; the route specifies service and the exact infrastructure objects it uses, **not** an exact physical route through every traversed tile. It may name an explicit infrastructure corridor whose geometry is separately specified. It cannot silently authorize the executor to invent a different station, corridor, stop, or route. If the specified infrastructure or orders cannot be realized, execution fails. Full exact physical tile path optimization is deferred.

## 13. `FleetPlan`

`FleetPlan` contains nonempty planned groups. Each `FleetGroup` has `fleet_group_id`, mode, `option_id`, positive integer count, assigned route IDs and cargo IDs, start/order intent, and a concrete composition. For road, composition identifies one vehicle type per instance. For rail, it identifies locomotive type, wagon types and integer counts, computed cargo capacity, and total length; option catalog and platform limits must agree. Total group purchase and running-cost estimates are derivable from explicit quantities, not hidden AI choices. Replacement/renewal is excluded from v1; no replacement means no automatic substitution. Maximum train capacity or length is never assumed economically optimal; future optimizers may compare multiple valid consist sizes.

## 14. `InfrastructurePlan` decision

Infrastructure is **separate** from `RoutePlan` because stations, depots, and corridors can be shared by multiple services and have their own build cost, tile occupancy, dependencies, and construction order. V1 contains ordered, stable `construction_id` actions: station or depot at an approved candidate site, and road/rail segment along an explicitly enumerated buildable tile sequence with transport type and endpoints. Required footprint/orientation, dependencies, estimated build cost, and route users are explicit. This is a supplied construction template, not a route-finding algorithm. Crossings/bridges/tunnels, demolition, terraforming, and adaptive construction are unsupported in v1 and cause a typed rejection if needed. If the initial implementation cannot establish a fixed buildable corridor, it must narrow the fixture before claiming executor support; it may not ask the AI to discover one.

## 15. `ExecutionPlan`

Top-level immutable envelope: `schema_version = 1`, `plan_id`, `scenario_id`/`scenario_version`/`world_fingerprint`, `planner_name`/`planner_version`, `strategy_identifier`/`strategy_version`, deterministic planner inputs digest, optional planner random seed, route collection, `FleetPlan`, `InfrastructurePlan`, and validation declaration (`validator_version`, supported-mode set, validated world fingerprint). It contains the planner's decisions only. `plan_hash` is a derived SHA-256 digest of the canonical envelope **excluding `plan_hash` itself**. The retained artifact records the digest beside or in an outer manifest. `plan_id` is stable and included in the hash; equal IDs with different hashes are a conflict. A generation timestamp may appear only in the outer artifact metadata, not the hash or decisions. Estimated metrics are a separately typed artifact linked by `plan_hash`, so estimates cannot change the authoritative plan identity.

## 16. Schema and versioning strategy

Planning schema integer `1` is independent of application/package version, OpenTTD version, AI version, and telemetry/outcome manifest versions. Every scenario, plan, and serialized estimate states its own schema version. Readers accept only versions they explicitly support; unknown major or future versions are rejected before launch as `UNSUPPORTED_PLAN_VERSION`. No best-effort field guessing or silent defaulting. Contract evolution requires a documented migration that produces a new artifact and hash; existing artifacts remain replayable with pinned readers/executors.

## 17. Deterministic serialization and hashing

Canonical representation is UTF-8 JSON with sorted object keys, no insignificant whitespace, normalized Unicode, fixed schema-defined list ordering, lowercase enum tokens, integers for counts/days/tiles, and canonical decimal strings for money or other fractional quantities. No NaN, infinity, floats, timestamps, filesystem paths, ORM dumps, pickle, or arbitrary `dict[str, Any]` in hash input. Explicit null is permitted only for declared optional fields; no absent-versus-null ambiguity. Sort ID-indexed collections by ID; preserve semantic order for stops and construction actions. SHA-256 over exact canonical bytes, rendered as lowercase hex, binds the planner output and permits byte-for-byte artifact comparison. The scenario and prepared-world manifest have their own digests; the plan embeds their identity/fingerprint, and the experiment retains all three. Hashing proves integrity, not buildability.

## 18. Validation rules

Run strict parsing and cross-reference validation **before OpenTTD launch**: known schema/modes; scenario identity and world fingerprint match; unique IDs; all referenced nodes, demand, vehicle options, fleet groups, routes, and construction actions exist; all tiles in bounds; compatible cargo units/types; positive quantities, capacities, counts, costs where applicable; consistent endpoint/stop order and route mode; assigned cargo quantities do not exceed stated demand without explicit split; route fleet and infrastructure references agree; budget and service windows are coherent; road depot/vehicle class matches; rail locomotive/wagon combination, traction, length, platform, cargo compatibility, and route infrastructure are supported. Reject unsupported construction features. Then perform a preflight against the exact prepared world for occupancy, connectivity and availability where the world manifest permits. Static validation cannot guarantee build success after launch; the thin AI must report a typed setup failure on the first rejected action. Never launch on known invalid input.

## 19. Python planner boundary

Conceptual port: `plan(PlanningScenario, planner settings/seed) → ExecutionPlan + EstimatedPlanMetrics`, possibly producing multiple candidates one at a time. The planner sees only typed scenario data and an immutable prepared-world manifest reference. It does not know subprocess lifecycle, Admin packets, Squirrel syntax, PostgreSQL ORM, TUI state, or artifact paths. It may use OR-Tools or another internal method later, but those details cannot leak into the contract. The highest testing seam is a complete `PlanningScenario → ExecutionPlan → validation/staging result` with a fake prepared-world catalog; targeted pure contract tests supplement it.

## 20. OpenTTD executor boundary

Conceptual port: submit a validated `ExecutionPlan` plus matching prepared-world handle and pinned executor configuration; return a typed setup receipt or setup failure, then hand the existing runner its unchanged simulation/evaluation responsibility. The exact Python method signature is deferred until the staging/lifecycle owner is chosen. The boundary validates supported schema and hashes, resolves world references, stages the plan, and ensures each construction/purchase/order action either matches the plan or fails with evidence (`plan_hash`, action ID, code, sanitized diagnostic, observed world identity). It must not optimize, reroute, change economic strategy, silently choose substitutes, invent fleet composition, or call the planner. The setup receipt records executed IDs and their result/status; partial setup never counts as a valid evaluation. The live runner's current startup, observation and finalization semantics remain the simulation path.

## 21. Thin OpenTTD AI responsibilities

The implemented P03 AI reads/decodes the supplied plan, checks its declared
identity/version and runtime world, and emits bounded acknowledgement evidence.
It then sleeps without constructing infrastructure, purchasing vehicles or assigning
orders. The target execution responsibilities remain: build stated infrastructure
in order, purchase stated vehicles/consists, assign stated orders, start service,
and emit evidence of actual action results. It may resolve plan IDs to runtime handles and enforce engine API preconditions. It may not choose a different location, connection, fleet, timetable, cargo, route, or objective. A world-dependent resolution failure is a setup failure. Python is authoritative for optimization. A plan-driven AI is distinct from current trAIns/SimpleAI strategy experiments and must be explicitly identified and pinned.

## 22. Plan transport recommendation

| Candidate | OpenTTD 13.4 fit | Determinism, size, debugging, security, complexity |
| --- | --- | --- |
| Raw JSON/static plan file in AI directory | AI file access and parser behavior are unproven here | Readable and size-flexible, but requires a verified 13.4 AI sandbox/file API and safe parser; not selected without proof. |
| AI settings carrying plan data | Existing launcher accepts only integer setting values | Too small for routes/infrastructure and prone to encoding/version errors; use at most a bounded plan identifier/hash if supported later. |
| Generated Squirrel data module inside a pinned thin-AI package | P03 implements and proves module loading and isolated packaging for its bounded v1 fixture | Deterministic generated constants can encode a bounded v1 plan; inspectable in retained source/package artifact; requires strict escaping, size cap, and hash/checksum checks. |
| Other deterministic pre-start artifact | Depends on verified 13.4 APIs | May be reconsidered if a simpler file read is proven. |

**Recommended v1:** validate canonical JSON in Python, then generate a data-only Squirrel module using a fixed serializer and package it with a pinned thin AI in the isolated pre-start workspace. Python planning code emits only the JSON contract; the transport adapter owns generation. Retain the canonical JSON, generated module/package digest, generator version, and plan hash. P03's retained Attempt #6 proves this transport for the bounded fixture;
it does not establish arbitrary OpenTTD load limits or general construction execution. Reject oversized or unrepresentable plans prelaunch. Treat generated data as untrusted text: escape strings, allowlist tokens, cap size/depth, and never interpolate raw plan text as executable code. The existing `LiveLaunchPreparation` pinned-AI allowlist and asset checks must be extended explicitly in the later implementation; P03's separate staging supports plan transport, while production launch integration
and actual action execution remain absent. Admin remains observation-oriented, never a general command transport.

## 23. Experiment and provenance integration

Future experiment input should distinguish: scenario/world manifest identity; planning strategy identity; planner identity/version/configuration; generated `ExecutionPlan` artifact reference and hash; thin-AI/executor version; and OpenTTD/OpenGFX pins. A run receives an immutable plan artifact (generated before run creation or atomically associated before launch) and retains its reference/hash with the run outcome and final artifacts. A config can request planner generation or select an already generated plan for replay, but a single run executes one resolved hash. `ScenarioConfig` and `ExperimentScenario` remain experiment identity/configuration records; `PlanningScenario` is a separate snapshot. Current `planning_strategies` rows identify AI selection; a future plan-driven strategy must be explicit rather than silently changing those rows' semantics. `ExperimentRun` links the strategy, plan identity/artifact, world fingerprint, execution receipt, and `SimulationRun`; DB row IDs are local links, never sole reproducibility keys. P01 does not choose a database migration or change current persistence. Replay requires matching artifact hashes, scenario/world fingerprint, runtime/AI pins, and planner seed/inputs; stochastic in-game behavior is reported as a reproducibility limit, not hidden.

## 24. Estimated versus realized metrics

`EstimatedPlanMetrics` has `plan_hash`, estimator name/version, assumptions digest, horizon, currency, predicted delivered cargo, revenue, infrastructure spend, vehicle purchase/running costs, finance, penalties, and estimated net profit, with unknown components explicitly unavailable. It is planner-side evidence used to rank candidates. `RealizedSimulationMetrics` has `plan_hash`, run identity, simulation date/horizon, metric name/value/unit/source, final-save and telemetry artifact hashes, coverage/completeness, and optional derived measures with formula/version. The final save is authoritative for current canonical outcome fields; Admin adds time-series observations and coverage, not an alternative profit number. Current final parser exposes company money, loan, current-period income, expenses, and delivered cargo; it does **not** directly expose all proposed profit components or full-run net profit. Future extraction/derivation must be separately specified before labeling a realized `profit`. Estimated profit must never be stored or displayed as realized profit.

## 25. Profit objective contract

Planner objective: maximize estimated net economic return over the stated horizon, with named terms for expected cargo revenue (delivery amount and applicable distance/time effects), infrastructure construction, vehicle acquisition, running costs, financing/interest only when the experiment models it, undelivered-cargo and lateness penalties, and infeasibility as hard rejection rather than a favorable score. Each estimate names source, units, sign convention, and assumptions. The initial objective may use a supported subset only if omitted terms are marked unavailable and candidate comparisons use a consistent model. OpenTTD-measured outcomes use the game's actual mechanics and existing final parser/telemetry; they can disagree with estimates. Realized profitability cannot be asserted from current-period income minus expenses alone without defining period and expense semantics.

## 26. Multimodal extensibility

Core IDs, locations, cargo, orders, costs and assignments are mode-neutral. `mode` is a tagged variant, with mode-specific option, infrastructure, and validation fields. V1 recognizes road and rail. Future `air` and `water` require new tagged variants, station/vehicle/build rules, and executor capability/version negotiation; unknown modes are rejected in v1 rather than coerced to road. No core `truck_id`, `road_distance_km`, geographic lat/lon, or driver ID.

## 27. Road requirements

Road plans specify road-capable pickup/delivery station sites, a compatible depot, explicit road corridor construction template, a road vehicle option, cargo capacity, vehicle count, and ordered pickup/delivery/depot orders. One-way roads, turn restrictions, and traffic-dependent timing require explicit future support; v1 rejects any corridor needing unsupported features. The AI cannot select an alternate road because a chosen tile is blocked.

## 28. Rail and consist requirements

Rail plans specify rail-capable station/platform and depot sites, an explicit rail corridor template, a compatible locomotive and wagon composition, wagon cargo compatibility, consist capacity, total length, purchase/running costs, and orders. Validate locomotive/wagon availability, traction/rail type where sourced, station/platform length, and infrastructure dependency. Multiple valid wagon counts must be representable so a later optimizer can compare purchase, running, service and revenue tradeoffs. **Maximum capacity is not automatically maximum profit.** Scheduling, signals, junction optimization, bridges/tunnels and exact rail path optimization are later work; if a proposed rail plan needs them for buildability, v1 reports unsupported/unbuildable rather than improvising.

## 29. Legacy adapter boundary

A future `LegacyDemandAdapter` may translate `Customer`/`Shipment`/`Package` to explicit `PlanningLocation`/`CargoDemand` only with a defined geospatial-to-tile mapping, cargo-unit conversion, world reference validation, and `SourceReference`. The legacy CVRP may later supply a `PlanningRouteCandidate` for planner evaluation, never an `ExecutionPlan` by renaming. `RoutingService`, its operational route tables, driver assignment, and shipment lifecycle stay isolated and cannot be used as the simulation plan store.

## 30. Packing boundary

Three-dimensional packing remains an optional independent planning constraint. A future adapter may report vehicle feasibility, effective load, or loading-order restrictions with provenance. OpenTTD cargo units are not physical parcel placement; v1 core plans contain no box dimensions, 3D coordinates, stacking, or loading-heuristic data.

## 31. Typed failure model

| Stage | Codes / treatment |
| --- | --- |
| Planning input/generation | `INVALID_SCENARIO`, `PLANNER_INFEASIBLE`, `PLANNER_FAILURE`; no plan or launch. |
| Validation/prelaunch | `UNSUPPORTED_PLAN_VERSION`, `SCENARIO_MISMATCH`, `INVALID_PLAN`, `UNKNOWN_NODE`, `UNSUPPORTED_MODE`, `INVALID_FLEET`, `UNSUPPORTED_CONSTRUCTION`, `PLAN_TRANSPORT_FAILURE`; no OpenTTD process. |
| Executor setup after launch | `UNBUILDABLE_INFRASTRUCTURE`, `INVALID_FLEET`, `EXECUTOR_SETUP_FAILURE`, `WORLD_RESOLUTION_FAILURE`; retain plan hash, failing action and partial receipt, mark experiment failed, do not score as a valid candidate. |
| Runtime/observation/finalization | Existing typed startup, protocol, `OBSERVER_LOST`, timeout, finalization and cleanup handling remains under the runner. |
| Persistence | Existing terminal/telemetry persistence and outcome-manifest evidence rules remain distinct. |

Failure diagnostics must be bounded and sanitized. A prelaunch validation failure must not be misreported as `OBSERVER_LOST`; a partial build must not produce a successful optimization evaluation even if a final save is available. Failure category and original plan identity survive later cleanup/persistence errors according to the existing outcome precedence rules.

## 32. Representative v1 scenario

A small, pinned OpenTTD 13.4/OpenGFX 7.1 generated map (proposed 64×64, seed fixed in fixture), short horizon, one verified industry-origin to destination cargo flow, one road service candidate, one rail service candidate, one road vehicle option and two rail consist sizes. Scenario preparation must discover and freeze actual industry/cargo/vehicle IDs, candidate tiles, station/depot footprints, and simple road/rail corridor templates **before** planning; the seed alone cannot supply them. Use separate road-only and rail-only `ExecutionPlan` fixtures against the same scenario to test mode variants, one plan per run. Keep quantity and costs small enough to validate selection and setup; do not claim optimization quality. P01 defines this fixture but does not run or implement it. If no generated map meeting the fixed corridor requirements can be proven, use a pinned prepared save/map fixture with the same manifest contract rather than allowing AI pathfinding.

## 33. Security and trust

Plan files and world manifests are untrusted inputs even when locally generated. Enforce size/depth/count limits, strict schemas, hash checks, safe identifiers, and no arbitrary paths or code fields. Stage in the existing isolated workspace with exclusive creation, confined paths and pinned package digests. Generated Squirrel data must contain only serializer-produced literals; planner strings cannot become executable expressions. Do not record Admin or database secrets in plan artifacts, failures, logs, or provenance. The retained plan, generated transport artifact, save, and parsed result carry separate hashes. The current outcome manifest is trusted local recovery evidence, not a signature or authorization mechanism.

## 34. Testing strategy

Tests should assert observable contract behavior: accepted plans stage the stated actions, invalid plans fail before launch, and build rejection returns the original action/plan hash without substitution. Avoid testing private serializer helpers or optimizer implementation details as the main evidence. Pure contract tests cover canonical hash stability, version rejection, referential integrity, road/rail variants, consist/platform constraints, and scenario mismatch. A controlled fake prepared-world/executor seam tests one complete scenario-to-stage flow and deterministic failures; existing `tests/test_live_launch_preparation.py`, `tests/test_live_runner.py`, `tests/test_experiments.py`, `tests/test_final_result.py`, and [T16 matrix](../live-failure-matrix.md) provide patterns for lifecycle, identity, and failure evidence. A later opt-in OpenTTD 13.4 smoke uses one small road plan and one rail plan only after the transport spike; verify exact action receipts, one world per run, final save, telemetry, plan provenance, and cleanup. P01 performs no runtime test.

## 35. Migration and adoption strategy

1. Introduce typed scenario/plan/validation/serialization artifacts with no runtime or database integration; retain legacy routing/packing and existing AI experiments.
2. Prove the 13.4 thin-AI package/module transport and setup evidence on a pinned tiny world; extend pinned asset and launch preparation allowlists explicitly.
3. Add a plan-driven experiment entry point above the existing live runner, immutable plan artifact retention, and provenance linkage, with necessary persistence decisions made in that later ticket.
4. Add road and rail executor actions behind the validated boundary, then opt-in real OpenTTD acceptance runs.
5. Only later add a profit-aware Python planner and candidate evaluation loop. Existing `PlanningStrategy` experiments remain readable under their original meaning.

## 36. Open questions for implementation tickets

- Which pinned 13.4 thin-AI package loader and data-module size limit can be demonstrated safely?
- How will world preparation produce a stable, verified manifest for generated industry positions, vehicle catalogs, and tile occupancy without launching an evaluation world twice?
- Which minimal road/rail construction templates are supported by the first executor and AI API, especially rail signals/platforms?
- Which final-save fields can support a versioned full-horizon realized economic measure beyond today's canonical metrics?
- What persistence mechanism will retain immutable plan/receipt references beside `ExperimentRun` while preserving current outcome recovery semantics?

These questions do not change v1 contract semantics: unresolved support yields typed rejection, not implicit executor discretion.

## 37. Acceptance criteria

P01 is satisfied when this document unambiguously defines the planner's `PlanningScenario` input and `ExecutionPlan` output; scenario-local tile locations and cargo units; route service intent versus physical infrastructure; fleet groups and rail consist choices; separate ordered infrastructure; road/rail validation; schema v1 and canonical hash; recommended pre-start transport; thin AI's allowed actions; typed planning/setup/runtime failures; experiment plan provenance; estimated versus realized economics; isolated legacy/packing adapters; and the tiny first scenario. No implementation or database/runtime change is part of acceptance.

## Next implementation ticket recommendation

**P02 — Planning schema v1, canonical serialization, and prelaunch validation.** Implement immutable typed `PlanningScenario`/`ExecutionPlan` contracts and world-manifest references, canonical SHA-256 artifacts, and strict cross-reference validation against a tiny fixed fixture. Stop before AI transport, construction, experiment persistence, or a new optimizer.
