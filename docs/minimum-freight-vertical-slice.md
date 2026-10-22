# Minimum controlled freight vertical slice

Architecture authority: local `CONTEXT.md`. Inspected HEAD is
`b10cd2dc99b241ff713b3211d87662be7d5136b7`, the immediate successor of requested
baseline `6a0da37fe2d43c5937fc14279816dfa5af79472e`. The successor already implements
the controlled pipeline. This task reuses it and adds end-to-end admission checks;
it does not introduce a competing observation, scenario or plan schema.

## Executable controlled path

Run `.venv/bin/pytest tests/test_p08_controlled_e2e.py`. The test composes
`WorldPlanningObservation`, owned supplemental/source admission,
`adapt_planning_facts`, `generate_road_scenario`, the unchanged
`optimize_candidate_network` CP-SAT optimizer, and `validate_execution_plan`.
See [the detailed controlled evidence contract](p08-15-3-controlled-end-to-end-p05-verification.md).

One positive qualified supply and one matching acceptance capability produce one
road freight OD. Industry and cargo IDs are fixture parameters resolved through
the qualification and structural models, not constants in the generator. The
controlled example supplies 120 cargo units, assumes transport of that historical
batch with one load per vehicle, and purchases four 30-unit vehicles. It generates
two truck stops, one depot and one road corridor. Planned CAPEX is 4290 GBP.
Acceptance is capability, not measured consumption. The planning calendar and
single-load policy are explicit assumptions, not observed travel times or future
production guarantees.

| Input | Evidence class in this test |
| --- | --- |
| Industry/cargo identities, capability, qualified month and production | Simulated complete qualification stream using the existing observation validators; these query/model families have separate historical 15.3 proof |
| Supply, compatible OD, selected geometry, fleet count, cost arithmetic | Derived from admitted inputs |
| Terrain, catchment, buildability, engine availability/capacity/prices, construction prices, source bytes, calendar and demand policy | Explicit controlled fixtures/benchmark assumptions |
| Native company authorization/finance, construction legality, current engine purchase legality, source-save/runtime correspondence, realized cargo transport | Unavailable for this plan |

No input to this integration test is a newly acquired native observation. The
source byte fixture is not an executable save. `PreparedWorldManifest` fingerprint
semantics remain unchanged. Native executable admission stays fail-closed even
after an optimal solve. Zero production and valid qualified empty target sets
remain admitted observations and produce explicit no-service outcomes.

## OpenTTD 15.3 native execution gap

Checked the local generated GameScript documentation with project version 15.3 at
`/home/fed/Downloads/OpenTTD-Docs/openttd-15.3-docs-gs/html/index.html`, including
the company, test mode, road, engine, vehicle, order and station class pages.
Road and vehicle declarations were also checked against the official 15.3 tag.
These are API availability checks, not execution proof.

| Required operation | Exact 15.3 API boundary | Repository evidence / remaining work |
| --- | --- | --- |
| Company context | `GSCompanyMode(company_id)`, `GSCompanyMode.IsValid()` | No verified 15.3 freight mutation implementation. Bind an existing authorized company and check permissions and funds. |
| Construction testing | `GSTestMode()` under company mode | Implement synchronous command validation, cost accounting and failure evidence. Test mode does not create infrastructure or vehicle IDs for subsequent commands. |
| Road selection and construction | `GSRoad.SetCurrentRoadType(GSRoad.ROADTYPE_ROAD)`, `GetCurrentRoadType()`, `BuildRoad(start, end)` | Read-only selector work exists; no native-proven 15.3 construction executor. Build the supplied corridor and depot branch with correct road-bit geometry. |
| Two terminal freight stops | `GSRoad.BuildRoadStation(tile, front, GSRoad.ROADVEHTYPE_TRUCK, GSStation.STATION_NEW)` | Implement exact footprints/fronts and retain returned command results; verify station identity, ownership, catchment and connections. |
| Depot | `GSRoad.BuildRoadDepot(tile, front)` | Implement one depot and verify ownership, orientation and corridor connection. |
| Engine availability and purchase | `GSEngine.IsBuildable(engine_id)`, `GSVehicle.BuildVehicle(depot, engine_id)` | Implement company-specific admission and four purchases for this fixture plan; retain and validate every vehicle ID. No refit is required for the supported default-cargo slice. |
| Orders | `GSOrder.AppendOrder(vehicle_id, destination, order_flags)` | Map plan pickup/delivery flags explicitly, validate with `AreOrderFlagsValid`, and verify count/destinations/flags using `GetOrderCount`, `GetOrderDestination`, `GetOrderFlags`. |
| Start | `GSVehicle.StartStopVehicle(vehicle_id)` | This toggles state. Check stopped state before issuing it and verify `GSVehicle.GetState` afterward; do not blindly replay. |
| Post-execution verification | `GSRoad.AreRoadTilesConnected`, `IsRoadDepotTile`, `IsRoadStationTile`; `GSStation.GetStationID`; `GSTile.GetOwner`; `GSVehicle.GetEngineType`, `GetCapacity`, `GetState`; order reads above | Add bounded 15.3 handlers and same-run state evidence. Existing structure/production reads do not prove these constructed objects or freight delivery. |
| Execution receipt | Existing correlated AdminPort/GameScript transport and `GSAdmin.Send` | Transport/observation proof exists. Implement a separate plan/action-bound machine-verifiable receipt with native IDs, actual verification, partial failure, request deduplication and lifecycle evidence. Historical 13.4 P06 receipts do not establish 15.3 execution. |

Before these operations, acquire real bounded supplemental facts and prove
prepared-source/runtime correspondence. Preserve source, structural, production,
scenario and plan identities separately. Native construction commands and runtime
launches are outside this task.

Sources: [15.3 road declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.hpp),
[15.3 vehicle declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_vehicle.hpp).
Other exact signatures above were read in the version-verified local GameScript
class pages. No historical 13.4 fixture establishes these 15.3 API claims.

## Verification on 2026-10-11

- Focused observation, adapter, candidate, P05, plan and preparation run: 348 passed.
- Final end-to-end file including eight added negative cases: 62 passed.
- Ordinary serial suite: 3634 passed, 48 skipped, three real OpenTTD tests
  deselected in 567.65 seconds. This run collected before the eight new cases;
  those are covered by the final end-to-end run above.
- Repository Ruff and format checks passed, as did the scoped `ty` check of WPO,
  qualified result types, adapter and road generation, and `git diff --check`.
- Deterministic golden-record, repeated-admission and reordered-input assertions
  passed through the actual optimizer and plan validator.
- SHA-256 comparison preserved 1588 other initially captured tracked/untracked
  files. All 1360 entries in the historical Attempt 1 integrity manifest match.
- OpenTTD launches, real Admin connections and real native requests: all zero.
- No staging, commit or push. Only the end-to-end test file and this report changed
  during the task; all pre-existing local edits were preserved.
