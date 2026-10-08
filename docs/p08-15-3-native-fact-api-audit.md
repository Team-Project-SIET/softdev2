# OpenTTD 15.3 native planning-fact API audit

This is source research for a **future controlled road-first P08 supplemental-fact contract**, not a native observation or an implemented query adapter. `CONTEXT.md` remains architecture authority. The existing local P08 preparation package and fixtures target 13.4 and are consumers to audit, not 15.3 API authority. No OpenTTD process, Admin connection, query handler, save extraction, or native freeze was created for this audit.

Authority: the `OpenTTD/OpenTTD` **15.3 tag**, both Script API declarations and implementation, cross-checked against the locally generated GameScript documentation whose project version is 15.3 at `/home/fed/Downloads/OpenTTD-Docs/openttd-15.3-docs-gs/html/index.html`. C++ `ScriptX::Method` becomes `GSX.Method`; constructors become the corresponding GS classes. The local class pages confirm the bindings below. Source implementation controls invalid-value behavior where abbreviated documentation is insufficient.

## Minimum slice and available facts

The smallest useful existing P05-compatible slice is ROAD, one configured supply-to-acceptor OD benchmark, a positive qualified supply record, non-articulated default-cargo road engines, two 1×1 freight stops, one shared 1×1 road depot, and orthogonal flat vacant-land road corridors. Existing Python generation remains responsible for placements, candidate enumeration, bounded Dijkstra and deterministic ties. P05 selects supplied candidates; native pathfinding is not a substitute for this candidate-generation responsibility.

Already provided by the proven observation pipeline: industry numeric ID/type/anchor coordinates, produced/accepted capability relationships, cargo catalog identity/properties, complete qualified production and relevant producer construction identity. Additional native reads must not re-extract these facts as competing authority. Tile catchment production means **producer count**, not historical cargo quantity. Qualified raw production is the sole supply amount. Acceptance is eligibility, not measured consumption.

The minimum needs a **complete bounded planning region**, including every selected facility/front tile and every considered corridor tile. It does not need the entire map. It may reject worlds whose useful route leaves that region. Full industry footprints can be deferred if coverage lists identify candidate tiles directly; preserving the existing footprint-based sampler unchanged would instead require footprint input. These are distinct future contracts, not permission to silently change existing generation.

## Tile and coverage bindings

All arguments are native integers unless stated otherwise. `TileIndex` is a map tile index, not metres; coordinates resolve through `GSMap.GetTileIndex(x, y)`, `GetTileX`, `GetTileY`, and map dimensions. Validate `GSMap.IsValidTile(tile)` before interpreting any result. Every method in this table is a read, not a gameplay command. Deity mode is sufficient for the restricted vacant-land slice; company-relative road ownership is not inferred from deity reads.

| Required fact | C++ symbol → GameScript binding; arguments | Result / units | Invalid behavior and interpretation |
|---|---|---|---|
| Bare terrain elevation | `ScriptTile::GetMinHeight` → `GSTile.GetMinHeight(tile)` | `SQInteger`, height levels | `-1` invalid tile. Implementation returns `GetTileZ`; do not enforce the stale header's 0–15 description as a universal 15.3 bound. |
| Bare terrain slope | `ScriptTile::GetSlope` → `GSTile.GetSlope(tile)` | `ScriptTile::Slope`, corner/steep bit encoding | `SLOPE_INVALID = 0xFFFF` invalid tile; minimum accepts `SLOPE_FLAT` only. |
| Buildability predicate | `ScriptTile::IsBuildable` → `GSTile.IsBuildable(tile)` | `bool` | `false` invalid tile/mode. It can return true for trees, coast and some owned/town road ends: **true does not mean vacant, free, affordable or guaranteed constructible**. |
| Exclude water/coast | `ScriptTile::IsWaterTile`, `IsCoastTile` → `GSTile.IsWaterTile(tile)`, `.IsCoastTile(tile)` | `bool` | Invalid tile returns false, so validate identity first; water predicate excludes a buoy tile. |
| Exclude clearing | `ScriptTile::HasTreeOnTile`, `IsFarmTile`, `IsRockTile`, `IsRoughTile` → matching `GSTile` methods `(tile)` | `bool` | Invalid tile returns false. Strict slice rejects all these even if buildable. |
| Exclude infrastructure | `ScriptTile::HasTransportType` → `GSTile.HasTransportType(tile, transport_type)` | `bool`; ROAD/RAIL/WATER/AIR enum | Invalid tile returns false. Reject unknown transport enums in Python; implementation does not supply a general invalid-enum check. Query the four legal types; false is not itself a generic vacancy proof. |
| Exclude industry ownership | `ScriptIndustry::GetIndustryID` → `GSIndustry.GetIndustryID(tile)` | `IndustryID` | Invalid tile/non-industry tile returns invalid industry; combine with `GSIndustry.IsValidIndustry`. |
| Pair-specific pickup coverage | `ScriptTile::GetCargoProduction` → `GSTile.GetCargoProduction(tile, cargo, width, height, radius)` | `SQInteger`, **number of producers** | `-1` invalid tile/cargo, width/height ≤0 or radius <0. For a 1×1 stop require >0, and intended producer coverage evidence separately. |
| Pair-specific delivery acceptance | `ScriptTile::GetCargoAcceptance` → `GSTile.GetCargoAcceptance(tile, cargo, width, height, radius)` | `SQInteger`, acceptance eighths | Same `-1` conditions; ≥8 indicates acceptance. Not consumption volume or guaranteed exclusive routing. |

Source: [15.3 tile declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_tile.hpp), [tile implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_tile.cpp), [industry implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.cpp), [map declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_map.hpp).

`ScriptStation::GetCoverageRadius(StationType)` → `GSStation.GetCoverageRadius(GSStation.STATION_TRUCK_STOP)` returns integer tiles. It returns 3 with modified catchment, 4 with unmodified catchment; invalid/multiple station type or airport yields `-1`, unsupported single types yield `CA_NONE`. `GSTile.GetCargo*` internally substitutes unmodified radius when that setting is disabled. Read effective coverage and freeze it; do not unconditionally inherit 13.4 radius 3. These are deity-safe reads. [Station implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_station.cpp), [catchment constants](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/station_type.h).

`ScriptTileList_IndustryProducing(IndustryID, SQInteger radius)` → `GSTileList_IndustryProducing(id, radius)` and `ScriptTileList_IndustryAccepting(...)` → `GSTileList_IndustryAccepting(...)` expose industry-specific geometry-derived coverage candidates. Invalid ID/nonpositive radius produces an empty list. Neutral-station service restrictions and production/acceptance status can also produce an empty list. Constructors use actual industry tiles and exclude the industry footprint, but do **not** guarantee a buildable tile. Acceptance candidates check nonzero acceptance for some accepted cargo, not necessarily the selected cargo at the required ≥8 threshold. The header warns nearby similar industries may receive cargo instead. Apply cargo-specific and tile gates in Python. [Tile-list declaration](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_tilelist.hpp), [implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_tilelist.cpp).

`GSIndustry.GetLocation(id)` returns an anchor, `INVALID_TILE` when invalid; it is not a complete footprint. No single audited GS method returns the entire exact footprint. If the existing sampler requires it, bounded tile ownership reads must establish completeness for a declared region, or use a separately verified prepared-save extractor. An arbitrary radius around the anchor cannot assert complete footprint coverage. [Industry declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.hpp).

## Road geometry and cost bindings

Candidate footprints and orientations are **Python policy outputs**, not observations of existing stations. Native 15.3 `ScriptRoad::_BuildRoadStationInternal` passes width=1, height=1 and default road-stop class to the native road-stop command. `BuildRoadDepot` supplies one tile and front direction. These mutation implementations justify the restricted geometry only; neither method is permitted as a query or used in this task. Real execution has additional station-spacing, authority, ownership, finance and vehicle-in-the-way checks that vacancy predicates do not prove. [Road implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.cpp).

| Read | Exact binding | Semantics / invalid result / context |
|---|---|---|
| Road type availability | `ScriptRoad::IsRoadTypeAvailable(RoadType)` → `GSRoad.IsRoadTypeAvailable(road_type)` | `bool`; deity or valid company mode; invalid/unavailable false. Deity availability is not an arbitrary company's future authorization. |
| Base construction costs | `ScriptRoad::GetBuildCost(RoadType, BuildType)` → `GSRoad.GetBuildCost(road_type, GSRoad.BT_ROAD / BT_TRUCK_STOP / BT_DEPOT)` | `Money` integer pounds; unavailable type/unsupported build type `-1`. Road base price is for a piece of road, not a quoted complete arbitrary corridor. Flat-road policy must explicitly convert pieces/tiles and exclude clearing/foundations. |
| Road compatibility | `ScriptRoad::RoadVehHasPowerOnRoad(engine_road_type, road_road_type)` → matching `GSRoad` call | `bool`; false if either type unavailable. Minimum fixes an audited ordinary road type and excludes tram/custom-road alternatives. |
| Road speed cap | `ScriptRoad::GetMaxSpeed(RoadType)` → `GSRoad.GetMaxSpeed(road_type)` | `SQInteger`; `-1` unavailable, `0` unlimited. Unit differs from engine speed: convert using **2.01168**, not 1.00584. Required if selected road type is not explicitly unrestricted. |

Source: [road declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.hpp), [road implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.cpp). Script `Money` is native pounds independently of UI currency: [script types](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_types.hpp).

Existing P08 doubles the road-piece price and multiplies it by corridor tile count. In 15.3 native road construction charges `CountBits(pieces) × RoadBuildCost`; a normal two-piece tile supports that restricted per-tile normalization, but shared/intersection/end geometry needs explicit accounting rather than an exact-price claim. [Native road cost calculation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/road_cmd.cpp#L859).

Do not call `SetCurrentRoadType` merely to read explicit-roadtype costs; it changes script-local selection state and is unnecessary here. Reuse of existing road, rail, bridges, tunnels, slopes, foundations, terraforming, trees/coast clearing, articulated stop requirements and NewGRF road stops is **deferred**. Conservative exclusion is permitted; falsely claiming exact construction success is not.

## Engine bindings

`ScriptEngineList(ScriptVehicle::VehicleType)` → `GSEngineList(GSVehicle.VT_ROAD)` returns a native list. Deity mode enumerates road engines without company filtering, including unavailable engines; valid company mode filters company availability. Sort engine IDs and explicitly validate/filter each. This read requires neither company creation nor vehicle purchase. [Engine-list declaration](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_enginelist.hpp), [implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_enginelist.cpp).

All following reads take `EngineID engine_id`. They are accessible in valid deity/company mode and do not mutate vehicles. `IsValidEngine` checks enabled existence and, outside deity mode, availability or an engine already owned. Invalid modes/IDs must fail the supplemental contract rather than turn sentinel values into candidate data.

| C++ symbol → binding | Return and semantics | Invalid behavior / minimum restriction |
|---|---|---|
| `ScriptEngine::IsValidEngine` → `GSEngine.IsValidEngine` | `bool` | False invalid/disabled; availability scope matters. |
| `ScriptEngine::IsBuildable` → `GSEngine.IsBuildable` | `bool`, currently purchase-available | Deity checks public availability without exclusive preview; false invalid/unavailable. Engine implementation requires Available flag and nonempty company availability, not universal availability to every company. Does not prove a particular company's funds/depot. |
| `ScriptEngine::GetCargoType` → `GSEngine.GetCargoType` | `CargoType`, default/main cargo | `INVALID_CARGO` invalid/no capacity. Implementation selects largest articulated cargo capacity; do not assume a universal mixed-cargo mapping. |
| `ScriptEngine::GetCapacity` → `GSEngine.GetCapacity` | `SQInteger`, cargo units | `-1` invalid/no road/rail capacity; implementation returns first nonzero articulated cargo capacity. Minimum rejects articulated/mixed-cargo engines. |
| `ScriptEngine::IsArticulated` → `GSEngine.IsArticulated` | `bool` | False invalid/not road-or-rail; validate first. Minimum rejects true. |
| `ScriptEngine::GetRoadType` → `GSEngine.GetRoadType` | `ScriptRoad::RoadType` | `ROADTYPE_INVALID` invalid/not road. Require compatible audited ordinary road. |
| `ScriptEngine::GetPrice` → `GSEngine.GetPrice` | `Money`, purchase price in pounds | `-1` invalid. Actual dynamic engine price; not a UI-currency value. |
| `ScriptEngine::GetRunningCost` → `GSEngine.GetRunningCost` | `Money`, pounds per **economy-year** | `-1` invalid. A generic calendar-year interpretation is wrong. |
| `ScriptEngine::GetMaxSpeed` → `GSEngine.GetMaxSpeed` | `SQInteger`, internal speed unit | `-1` invalid; 15.3 documents ×**1.00584** for km/h. Aircraft additionally use plane-speed setting; aircraft excluded. |
| `ScriptEngine::GetName` → `GSEngine.GetName` | optional string | Null invalid; label is descriptive, engine ID plus content identity is authoritative. |

Sources: [engine declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_engine.hpp), [engine API implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_engine.cpp), [native IsEngineBuildable](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/engine.cpp#L1246). The header describes deity as buildable by all companies; the native implementation provides the narrower public-availability test above. Do not turn that prose into an all-company guarantee.

`ScriptEngine::CanRefitCargo(engine_id, CargoType cargo)` → `GSEngine.CanRefitCargo` returns bool; invalid engine/cargo false. It includes cargo already carried by default and any articulated part, so it does not establish default capacity for a refitted vehicle. Refit capacity is not supplied by these audited reads. The minimum chooses default-cargo-only engines and defers refit. There is no audited generic native `depot_class` string getter: `"road"` is a policy label justified by native road vehicle type/road type, not an extracted native name. [Engine refit contract](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_engine.hpp).

The historical P08 `/365` running-cost conversion is a **planning normalization**, not a native daily cost observation. Use it only under the supported calendar-economy annual accounting convention, document rounding, and retain annual source units. It is not valid merely because the process is 15.3; wallclock economy needs a different explicit policy. `GSEngine.GetMaxSpeed` is an upper bound, not observed travel time or guaranteed average speed.

## Cargo, settings, content and source identities

`ScriptCargo::GetCargoLabel(CargoType)` → `GSCargo.GetCargoLabel(id)` returns optional four-character label; invalid null. `ScriptCargo::IsFreight(CargoType)` → `GSCargo.IsFreight(id)` returns bool; invalid false. Both are deity-safe reads already represented in the proven cargo catalog; use that observation instead of duplicate extraction. [Cargo implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_cargo.cpp).

`ScriptGameSettings::IsValid(string setting)` → `GSGameSettings.IsValid(name)` recognizes integer settings; `GetValue(string)` → `GSGameSettings.GetValue(name)` returns `SQInteger`, `-1` for unknown/noninteger names, and reads `_settings_game` through the native descriptor. They are read-only and require no company. Exact audited candidates are:

| Setting | Meaning and scope |
|---|---|
| `station.modified_catchment` | Boolean integer controlling effective catchment semantics. |
| `station.serve_neutral_industries` | Boolean integer; coverage-list eligibility includes this restriction. |
| `economy.timekeeping_units` | Calendar versus wallclock economy; frozen qualification/time/cost profile must agree. |
| `game_creation.generation_seed` | Native stored uint32 generation seed; `NotInConfig` descriptor. Distinguish actual resolved generation seed from random-seed sentinel; value alone is not proof of loaded source bytes. |

[Settings API implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_gamesettings.cpp), [station settings](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/table/settings/game_settings.ini), [economy settings](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/table/settings/economy_settings.ini), [world seed descriptor](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/table/settings/world_settings.ini).

`ScriptNewGRFList()` → `GSNewGRFList()` returns non-static loaded GRF IDs. `ScriptNewGRF::IsLoaded(SQInteger grfid)`, `GetVersion(grfid)`, `GetName(grfid)` → matching `GSNewGRF` methods return bool, integer version, optional string; unknown version yields 0, unknown name null. These reads exclude static GRFs; ID/version are not cryptographic file identities and do not establish base-set identity. A no-gameplay-NewGRF profile can use an empty gameplay list as a corroborating native observation, while protected installed-file manifests remain necessary. [NewGRF declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_newgrf.hpp), [implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_newgrf.cpp).

There is no audited GS getter for prepared-save SHA-256, actual loaded save bytes, final-save SHA-256, OpenGFX installed file digests, or exact loaded NewGRF file SHA-256. These are **external ownership/provenance evidence**, not fabricated GS fields. Hash actual bytes with an owned Python lifecycle, establish the exact process launch/load relation, and preserve distinct source-save, runtime, final structure, production, and prepared-manifest identities. Attempt 4's proven generated-runtime qualification does not retrospectively prove a save-to-runtime relation.

## Bounded read-only acquisition design

The transport contracts remain application responses ≤512 bytes and native `GSAdmin.Send` ≤1450 bytes. No new native handlers or accounting ceilings are introduced here.

1. Bind a request to the admitted final structural observation, continuous runtime/config/bridge identity, declared region and profile. Supplemental facts must identify whether they were read during that same owned runtime or a separately proven saved-state lineage; never silently join another world.
2. Read only scalar effective settings, costs and bounded engine catalog records. Deterministically paginate engine IDs; include completeness/continuation and reject overflow. Never assume deity engine-list enumeration proves buildability without per-engine gates.
3. For selected industry pairs, request bounded candidate coverage IDs or explicit region tiles. Industry-list constructors perform native local geometry, not Python planning; cap construction/work and result count before declaring a supported input. Their internal industry bounding box may be large for unsupported content, so reject unsupported profiles rather than call them without a work bound.
4. Request individual tiles or tiny fixed-count pages with numeric bit predicates and cargo-specific catchment values. A contract must reserve worst-case canonical JSON envelope/IDs/value sizes so every response is ≤512; a 512-byte application maximum is not permission to emit a 1450-byte GS message.
5. Declare **exact coverage of a fixed finite planning region**, including corridor/front tiles. Candidate-only queries without corridor coverage cannot prove Dijkstra feasibility. Missing/out-of-region tiles are hard boundaries, not assumed vacant tiles. Expansion needs a new explicit bounded input, not unbounded discovery.
6. Python assembles typed facts, validates references and complete region/candidate coverage, then performs deterministic station/depot/corridor/engine planning. No map streaming default, graph search, optimizer, mutations or dynamic supply calculation inside GS.

Verified offline prepared-save extraction is an alternative only after a 15.3 parser/content-identity contract and source/runtime/final-state equivalence proof exist. No such extractor or proof is established by this research. A supplemental read spanning time is not atomic: record temporal brackets, enforce supported stability checks, and retain that claim boundary.

## Remaining implementation gaps and proof boundaries

- Implement controlled supplemental DTOs and strict complete-region/candidate coverage tests first; the exact bindings above make that contract defensible.
- Decide footprint-backed legacy sampler versus native-coverage-backed future sampler explicitly. This research changes neither generator.
- Define conservative flat-vacant-road cost accounting with audited road piece/tile units, fixed-point rounding and economy-time normalization.
- Add bounded read handlers only in a later task; prove settings, region, engine and cost observations with their own authorized native slice.
- Establish prepared-save→loaded-runtime provenance separately if using the existing prepared manifest/execution source contract. Neither structural digest nor qualified production digest is a save hash.
- Real execution feasibility remains stronger than planning geometry: company permissions, local authority, station spacing, current balance, occupancy changes and content-specific behavior require later validation. No construction command is authorized here.

Current status: APIs are **SOURCE-AUDITED**; supplemental native observations and save-to-runtime identity are **NOT REAL-PROVEN**. Qualified historical production remains **REAL-PROVEN** independently. P08 adapter remains **NOT IMPLEMENTED**.
