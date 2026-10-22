# First native terrain/road acquisition slice: design and audit

Authority: local `CONTEXT.md`; repository baseline
`b10cd2dc99b241ff713b3211d87662be7d5136b7`. Design only: no handler, collector,
planning change, native execution, freeze, staging or commit. The ask-matt router
and codebase-design guidance support retaining the existing admission interface;
no competing terrain model or new proof framework is proposed.

## 1. Verified source and bindings

OpenTTD tag **15.3**, resolved commit
`14ec60f248547d4d062a1160f0fc26d742319888`. Tagged raw files were fetched again and
matched the earlier local audit copies where present. The generated GS documentation
at `/home/fed/Downloads/OpenTTD-Docs/openttd-15.3-docs-gs/html/` identifies version
15.3; classGSTile, classGSMap, classGSRoad and classGSAirport confirm bindings.
Source hashes and tag resolution are retained in `/tmp/p08-terrain-design/`;
these are audit calculations, not a proof freeze.

Source references below point to the exact tag. `ScriptX::Y` binds to `GSX.Y`;
these classes are marked `@api ai game`. Every proposed call is a read. The handler
must run in valid deity mode, not enter a company to make construction decisions.

| C++ API → exact GS binding; arguments | Return, units, range | Invalid/context semantics |
|---|---|---|
| `ScriptMap::GetMapSizeX/Y` → `GSMap.GetMapSizeX/Y()` | SQInteger, tile dimensions; native supported axes up to 4096 | Read actual runtime dimensions; DTO's broader 65536 ceiling is not native authority |
| `ScriptMap::GetMapSize` → `GSMap.GetMapSize()` | SQInteger, tile count = width×height | Maximum native index width: 8 decimal digits |
| `ScriptMap::GetTileIndex` → `GSMap.GetTileIndex(x,y)` | TileIndex, `y*width+x` | Implementation does not validate coordinates; validate before calling |
| `ScriptMap::IsValidTile` → `GSMap.IsValidTile(tile)` | bool | Requires index in map **and non-MP_VOID**; numeric bounds alone are insufficient |
| `ScriptMap::GetTileX/Y` → `GSMap.GetTileX/Y(tile)` | SQInteger, tile coordinates | -1 invalid tile; valid coordinates less than their dimension |
| `ScriptTile::GetMinHeight` → `GSTile.GetMinHeight(tile)` | SQInteger, bare terrain height levels, 0–255 | -1 invalid; ignores foundations; stale header 0–15 prose is not enforced |
| `ScriptTile::GetSlope` → `GSTile.GetSlope(tile)` | Slope, bare corner/steep encoding, represented 0–31 | invalid 0xFFFF; reject sentinel/unsupported values, never map to flat |
| `ScriptTile::IsBuildable` → `GSTile.IsBuildable(tile)` | bool | false invalid tile/mode; true for clear land, trees, some coast and selected one-piece road ends; **not command legality** |
| `ScriptTile::IsWaterTile/IsCoastTile/HasTreeOnTile/IsFarmTile/IsRockTile/IsRoughTile` → matching `GSTile` methods `(tile)` | Six bools | false invalid; coast also includes trees on shore; farm/rock/rough describe clear-land subtypes |
| `ScriptTile::HasTransportType` → `GSTile.HasTransportType(tile,type)` | bool, usable track status | Only RAIL/ROAD/WATER used. ROAD can be false for one-piece roads/roadworks; WATER can be true on coast. Header forbids AIR |
| `ScriptAirport::IsAirportTile` → `GSAirport.IsAirportTile(tile)` | bool | false invalid/nonairport; station airport predicate, not air track status |
| `ScriptTile::IsHouseTile/IsStationTile` → `GSTile.IsHouseTile/IsStationTile(tile)` | bool | false invalid; distinguishes houses and station MP types |
| `ScriptIndustry::GetIndustryID` → `GSIndustry.GetIndustryID(tile)`; `IsValidIndustry(id)` | IndustryID / bool | invalid industry sentinel for invalid/nonindustry tile; normalize to None only through validity check; admitted IDs 0–63999 |
| `ScriptTile::GetOwner` → `GSTile.GetOwner(tile)` | ScriptCompany.CompanyID, registered company 0–14 or -1 | -1 for invalid, houses, industry and owners not resolving to a company, including town/unowned categories; does **not** distinguish all ownership classes |
| `ScriptRoad::IsRoadTile` → `GSRoad.IsRoadTile(tile)` | bool | MP_ROAD except depots, plus selected-type drive-through stops; invalid false; includes road crossings/partial roads |
| `ScriptRoad::HasRoadType` → `GSRoad.HasRoadType(tile,road_type)` | bool | false invalid/unavailable/type absent; requires availability before absence can be interpreted |
| `ScriptRoad::IsRoadTypeAvailable` → `GSRoad.IsRoadTypeAvailable(road_type)` | bool | valid deity/company mode; type 0–63; company availability is context dependent |
| `ScriptRoad::GetCurrentRoadType` → `GSRoad.GetCurrentRoadType()` | RoadType | Script selector, not a tile's type; require available ordinary `ROADTYPE_ROAD=0` |
| `ScriptRoad::AreRoadTilesConnected` → `GSRoad.AreRoadTilesConnected(from,to)` | bool, directed observed relationship | false invalid/nonadjacent/unavailable selector; examines road/tram-category endpoint bits and destination disallowed directions; not exact engine routing |
| `ScriptDate::GetCurrentDate` → `GSDate.GetCurrentDate()` | Date, economy date ordinal | Uses TimerGameEconomy; proposed contract accepts 0–2147483647; calendar setting still needs binding |

References: [map declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_map.hpp),
[map implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_map.cpp),
[tile declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_tile.hpp),
[tile implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_tile.cpp),
[road declarations](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.hpp),
[road implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.cpp),
[airport implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_airport.cpp),
[industry implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.cpp),
[owner resolution](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_company.cpp),
[date implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_date.cpp),
[tile validity](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/tile_map.h),
[height bound](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/tile_type.h),
[map bounds](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/map_type.h).

## 2. Minimum facts and occupancy classification

Reuse `Region` and `TileFact` in `supplemental_planning_facts.py`. Tile identity,
coordinates, dimensions, min_height, slope and named native predicates are
**NATIVE FACT AVAILABLE**. Coordinate indexing/cardinal adjacency and conservative
occupancy categories are **DERIVABLE FROM VERIFIED FACTS**. The generator's
`vacant()` predicate and proposed equal-height construction corridor are
**CONTROLLED APPROXIMATION**, not native legal commands.

Generic internal `GetTileType(MP_*)`, raw road-piece bits and all ownership classes
are **UNAVAILABLE** through the audited public getters. `GetTerrainType` describes
normal/desert/rainforest/snow climate, not MP tile type. Exact permissions,
vehicles in the way, town authority and native command success remain **UNKNOWN**
for this slice. No fabricated general tile-type integer is sent.

Keep valid occupied tiles in the complete rectangle. Houses/stations/industries
are identified by their predicates; water/coast/clearing/transport are separate.
Unclassified valid objects have native buildable=false and remain unsupported
for placement. Invalid tiles fail the region rather than becoming false-filled
records. An invalid owner is not proof of unowned or unrestricted land.

Project `air_transport` from IsAirportTile, not HasTransportType(AIR).
The earlier API audit's four-transport-type description is corrected here:
the 15.3 HasTransportType binding explicitly excludes TRANSPORT_AIR. The earlier
document is preserved; this proposal uses the verified airport predicate.
Project `road` conservatively as IsRoadTile OR HasTransportType(ROAD) OR HasRoadType(tile,0).
This prevents one-piece ordinary roads from appearing vacant. This is a documented
Boolean normalization into the existing field, not a new DTO or a claim to enumerate
every unavailable tram/custom depot. Those unsupported states cannot become
vacant because native buildability is false. Rail and water_transport retain
their native track-status meanings. All current generator exclusions remain.

## 3. Existing roads versus proposed roads

The slice requires IsRoadTypeAvailable(ROADTYPE_ROAD)=true, explicitly selects
ROADTYPE_ROAD, and verifies current selector 0; otherwise fail
UNSUPPORTED_ROAD_TYPE before tile reads. Native startup selector is internal
INVALID_ROADTYPE=63. Selection changes script state only, never the world.
See [the controlled selector repair](../p08-15-3-road-selector-repair.md) for
the consumed failure, fixture correction and accounting contract.
HasRoadType(tile,0) identifies selected ordinary-road presence. It is not an
exhaustive road-type catalog. Other/mixed road and tram layouts are unsupported
for reuse; do not label them ordinary-only.

For cardinal neighbors **inside the declared rectangle**, record directed
AreRoadTilesConnected in both directions only when both endpoints have type 0.
Retain a separate assessed-neighbor mask. False outside the assessed mask means
unknown, not absent. The API checks a road/tram category, not exact powered-engine
compatibility; positive results are conditional native predicate observations,
not YAPF routes, unpaired road-piece enumeration or bridge/tunnel connectivity.
No read outside coverage is required. Comparing reciprocal directions across pages
helps detect drift but does not prove atomicity.

The current generator rejects all occupied road tiles. Thus these diagnostics
cannot cause reuse of existing infrastructure. Its corridor is **PROPOSED ROAD
CONSTRUCTION** over controlled-feasible bare tiles, never an observed built road.
**REAL POST-CONSTRUCTION CONNECTIVITY** needs separate command and execution proof.

## 4. Deterministic region selection before feasibility

Python selects one preliminary producer/cargo/acceptor relationship using existing
positive qualified supply, freight catalog and capability references, sorted by
(producer ID, cargo ID, acceptor ID). No native buildability or catchment is assumed.
The first such relationship is an area-of-interest choice, not an admitted OD.

Take the bounding box of the two known anchors with a fixed one-tile margin on
each side; clamp to numeric map bounds. Reject if width×height>256. Do not try
another pair, expand, truncate or stitch disjoint strips after this failure.
Native validity then checks every selected tile, including possible MP_VOID edges.
Known anchors do not prove that nearby footprints are useful or vacant.

One rectangle is required by the current domain; it is not full-map coverage.
Later catchment may use at most two scopes, with exactly N records per scope and
at most 512 total. This first slice supplies none of those scope facts. Facilities,
fronts and corridors must later remain inside the same accepted rectangle.
Failure is explicit INSUFFICIENT_COVERAGE / INVALID_TILE, not global world infeasibility.

## 5. Proposed protocol, pagination and collector interface

Names are **proposed**, not implemented commands. Reuse protocol 1 and existing
request-ID validation (1–64 safe ASCII), secure Gamescript transport, correlated
receipts, completion PING/PONG and owned stdout evidence. No new Admin packet type.

Request exact fields:
`protocol=1`, `type="tile_facts_page"`, `request_id`, `region=[x,y,w,h]`, `cursor`.
Cursor is a row-major **ordinal**, not native tile ID; first 0, next adds record
count. Page size fixed 5, no caller-controlled limit. Nonterminal pages contain
exactly 5; final page contains min(5,N-cursor). Cursor must be a multiple of 5 and
less than N. Within each sweep Python sends unique sequential request IDs.

Success exact fields: request fields with `type="tile_facts_page_result"`, plus
`status="ok"`, `map=[width,height]`, `next_cursor`, `has_more`, `date_before`,
`date_after`, `tiles`. Terminal next_cursor is null and has_more=false; otherwise
next_cursor=cursor+len(tiles), has_more=true. No sentinel/extra empty terminal page.
Tile IDs are strictly increasing row-major; no duplicate, omitted or reordered rows.

Compact row: `[tile_id,min_height,slope,flags,industry_id,owner,road0,out,in,assessed]`.
Bits 0–12 of flags, in order: buildable, water, coast, tree, farm, rock, rough,
conservative road, rail, water_transport, airport, house, station. Flags ≤8191.
Industry sentinel becomes null, otherwise 0–63999; owner -1 or 0–14. road0 is 0/1.
The three direction masks are 0–15, bits N/E/S/W. They describe selected-type
conditional connectivity, not proposed construction. Adjacent tiles outside the
rectangle have assessed bit zero. Coordinates are derived and checked through
native X/Y against the selector before projection into existing TileFact.

Error exact fields: protocol, type=result, valid request_id, status="error",
error_code (fixed ASCII enum ≤32 characters), cursor (0–255 or null), failed_tile
(native-width integer or null). No arbitrary exception text or partial tile rows.
Invalid unsafe request IDs are logged/rejected without reflecting them. Handler
exceptions, send failures or absent post-alive evidence fail the session; no retry.

Future Python collector accepts an already-owned transport/context, admitted WPO
when applicable, existing Region and explicit budgets. It returns immutable existing
TileFact tuples and references to command-specific exchange/evidence records.
Road/owner diagnostics remain raw evidence, not another planning terrain schema.
No partial result is a SupplementalPlanningFacts bundle. That constructor/importer
remains unchanged and cannot admit missing settings, costs, engines or catchment.

Current GameScriptTransport dispatch supports existing commands only. Future
implementation needs an explicit typed request/response/receipt validation branch;
an unknown command must never fall through to a WorldInfoReceipt. No new generic
collector or coordinator is introduced by this design.

## 6. Exact payload and work calculations

The accompanying test-only fixture/assertions use compact sorted ASCII JSON,
matching GSAdmin's compact nlohmann JSON output for these safe field types.
Native [ScriptAdmin serialization](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_admin.cpp)
and [Admin network path](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/network/network_admin.cpp)
remain distinct from the tighter **512-byte application** limit and 1450 native
GSAdmin limit. No strings needing escaping occur except validated identifiers.

Use maximum field widths: tile 8 digits, height 3, slope 2, flags 4, industry 5,
owner 2, road0 1, masks 2 each; row = 42 bytes including brackets/commas.
Maximum-width valid selector example is `[4000,4000,15,17]` (255 tiles), with
64-character ID, 3-digit cursor, 4-digit dimensions and 10-digit economy brackets.
Empty-list success envelope = 294 bytes. For n≥1:
`294 + 42*n + (n-1) = 293 + 43*n`.
Five rows: **508 bytes**; six: **551**, rejected. Request: **159 bytes**.
These are conservative independent-field-width bounds; maximum flags/industry/
terrain combinations need not coexist in a native world. They are not an assertion
of a particular world's observed response size. Repeated maximum-width rows in
the size vector are calculation inputs, not an admissible semantic page.
The maximum-width error fixture is **227 bytes** (reserved upper bound 255).
No hash strings are fabricated or repeated in the payload to imply native provenance.

For N≤256: `P=ceil(N/5)≤52`. One sweep ≤52 application requests; proposed coherence
comparison uses two sweeps: **104 requests**, **104×508=52832 response bytes**.
This pool upper bound deliberately does not credit shorter final/early-cursor pages.

Native getter work is a different counter from Admin protocol operations. Per tile
at most 44 calls: GetTileIndex/IsValid/X/Y (4), height/slope (2), buildable plus six
terrain predicates (7), three road predicates (3), rail/water (2), airport/house/
station (3), industry ID/validity (2), owner (1), and four neighbors ×(index,
validity,type-presence,two directed connectivity calls) (20). Per page at most six
additional reads: dimensions (2), economy dates (2), current road selector and
availability (2). Two sweeps: **2×256×44 + 104×6 = 23152 native getter calls**.
This excludes pure argument arithmetic, logs/serialization and internal C++ work;
controlled handler tests must verify scheduling/runtime bounds, not call these zero-cost.

Reuse existing per-query accounting: outbound Gamescript + inbound response +
completion PING + PONG = **4 ideal frames/operations**. Proposed hard allowance
8 per query includes every decoded additional frame; exhausted bounds fail before
admission. Thus **104×8=832 query operations** (ideal 416).
For a standalone proposed two-sweep session: establishment PROTOCOL/WELCOME 2,
setup subscription/PING/PONG 3, query cap 832, graceful QUIT 1:
**2+3+832+1=838 post-auth frames**. Authentication/encryption enablement is outside
this post-auth count; EOF is not a frame. Stdout GSLog markers add no Admin frames
when CONSOLE subscription is excluded. Receipts reconcile secure observer counters;
they are not added again. No reset, retry or reconnect.

All figures are **design ceilings**, not a real-proof authorization/freeze ceiling.
Combined qualification+terrain accounting is unresolved until a new continuous-run
phase order and transport request capacity are reviewed: existing qualification
completion/cleanup and caps cannot simply resume. Add the terrain phase before
cleanup, retaining prior counters; never reuse the historical 9094 ceiling.

## 7. Provenance, coherence and save limitations

Bind exchanges to the same owned process and connection objects, secure session,
runtime executable/version/hash, world/config identity and complete bridge package
hash. Record map dimensions, selected road context, region, request/cursor sequence,
raw bytes/receipts, independent GS markers and economy brackets. Python links them
to existing WPO composition, final structural and qualified production digests.
Hash canonical existing fact projection separately from raw exchange evidence;
eventually SupplementalPlanningFacts.semantic_digest includes all required facts.
Neither matching industry IDs nor an echoed digest proves ownership or native origin.

Combined future acquisition must use the bridge including this handler **before M0**,
then uninterrupted qualification through M1/M2 and terrain capture after final M2
collection, still within that same M2 economy month. Every before/after bracket
must be nondecreasing and inside WPO's existing M2 boundaries. A replacement
connection/process/config/content/bridge or month rollover aborts this strict slice.
Attempt 4 cannot be grafted onto a future runtime or changed bridge package.

Collect two complete sequential sweeps; compare normalized tile/road/owner values
and dimensions, retaining both brackets/evidence. Reject any discrepancy as drift.
Equality means repeatable observed regional values, **not an atomic snapshot**;
transient changes, vehicle movement and later changes remain possible. Do not claim
pause/frozen-world semantics. A stronger pause/stability/source-capture policy needs
its own audit and authorization. No incomplete sweep is promoted to complete.

Loaded content/settings identity needs external pinned file manifests plus later
native corroboration. Calendar/timekeeping and seed are deferred bindings; their
absence blocks real complete supplemental admission, not controlled terrain tests.

Preserve separate original prepared bytes → actual load → uninterrupted evolved
runtime → M2 structure / qualified M1 historical production → supplemental reads →
post-qualification save bytes. This task proves none of the save arrows. A future
issuer must establish exact owned load and save operations, same state/epoch and
capture coherence, source/config/content/runtime pins, and artifact byte digests.
Only existing `world_manifest_hash` defines the manifest fingerprint. No WPO/tile
digest can stand in for save identity; controlled correspondence and byte hashing
remain unable to grant real-executable authority.

## 8. Evidence, errors and future proof sequence

Reuse existing command marker conventions:
`BRIDGE_REQUEST_RECEIVED → TILE_FACTS_READ → BRIDGE_RESPONSE_SENT →
BRIDGE_POST_RESPONSE_ALIVE`; Python:
`TILE_FACTS_REQUEST_SENT → TILE_FACTS_RESPONSE_RECEIVED →
TRANSPORT_RECEIPT_CREATED → TILE_FACTS_VALIDATED`.
The future read marker must include region/cursor/count/map/road context/date
brackets and exact row values (bounded per-row lines permitted under TILE_FACTS_READ).
Compare markers to received rows independently; require post-alive and completion
barrier. Receipt hashes alone are insufficient. No parallel evidence system.

Design failure categories: INVALID_TILE, INVALID_REGION, REGION_OUTSIDE_MAP,
TILE_LIMIT_EXCEEDED, MISSING_NATIVE_FACT, UNSUPPORTED_TILE_STATE,
UNSUPPORTED_ROAD_TYPE, MALFORMED_RESPONSE, DUPLICATE_TILE, INCOMPLETE_REGION,
WRONG_CURSOR, WRONG_REQUEST_ID, SOURCE_MISMATCH, PAYLOAD_TOO_LARGE,
FRAME_BUDGET_EXCEEDED, HANDLER_EXCEPTION, SNAPSHOT_DRIFT, RUNTIME_CHANGED,
CONNECTION_REPLACED. Map these to existing typed transport/admission/budget errors
and future session failure evidence. Unknowns never become placement facts.
Known valid occupied tiles need not fail acquisition; they are unavailable for
placement. Unsupported/missing mandatory representations fail rather than drop rows.

Future steps (none executed here):

1. Controlled thin handler: strict schema, getters only, compact size checks,
   ordinary context, no graph or construction decisions; mock/SQVM verification.
2. Controlled Python collector at the existing transport interface; complete-region,
   pagination, evidence, budget and mismatch tests; two-sweep drift rejection.
3. Single-page real proof: separately reviewed new source/runtime/contract freeze
   and explicit one-attempt authorization. Establish one page, not region coverage.
4. Complete-region/two-sweep real proof: new bounded attempt freeze and authorization;
   demonstrate all declared tiles and precise accounting, no retry/reconnect.
5. Combined fresh qualification/supplemental run: new bridge and combined phase/cap
   review, new freeze and authorization. No reuse of consumed Attempt 4 lineage.
6. Trusted save correspondence: separate audited issuer/load/capture/save contract,
   new authorization/freeze before any native load/save activity. No automatic real
   planning/execution promotion after a successful query.

## 9. Deferred dependencies and remaining blockers

After terrain: establish settings/content/seed/calendar pins and supported road
context; acquire intended-industry catchment for at most two scopes; acquire
default-cargo engine availability/capacity; acquire engine and infrastructure costs;
then assemble full SupplementalPlanningFacts and test same-run WPO/P08/P05 admission.
These protocols are not designed in full here. Company-specific construction
legality and trusted post-qualification save correspondence remain separate proof
paths; neither follows from flat terrain or successful mathematical optimization.

No essential getter for the existing bare-tile minimum is missing. Controlled
terrain/road query implementation can proceed with the documented restrictions.
Real full supplemental/P08 input remains blocked by unimplemented acquisition,
combined runtime/accounting/evidence issuance, deferred facts and trusted save
correspondence. Generic tile taxonomy/raw unpaired pieces/all owner classes remain
unavailable; existing-road reuse and advanced geometry are outside this slice.
