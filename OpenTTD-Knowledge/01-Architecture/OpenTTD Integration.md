---
title: "OpenTTD Integration"
type: architecture
status: current
updated: 2026-10-22
tags:
  - openttd
  - architecture
  - gamescript
---

# OpenTTD Integration

**Sources:** [[99-Source-Documents/CONTEXT]] §2, §4, §6–§9, §16, §19; verified 15.3 API
facts re-appear in project records (E10/E11/E15). Everything below is scoped to
**OpenTTD 15.3** unless a record says otherwise. Historical 13.4 behavior is regression
context only.

## Version, runtime and authority

- Primary runtime: OpenTTD **15.3**, Linux generic amd64; binary and OpenGFX 8.0 are
  SHA-256-pinned ([[03-Engineering/Runtime and Environment]]).
- GameScript API version: `GetAPIVersion()` returns `"15"` — never `"15.3"`
  (OpenTTD ≥ 12 uses major-version API identifiers; CONTEXT §16).
- OpenTTD 14+ expanded company-control capabilities available to GameScript — one reason
  15.3 is preferred over the old 13.x environment.
- Documentation authority order (CONTEXT §4):
  1. verified OpenTTD 15.3 project-local documentation
  2. official OpenTTD 15.3 documentation
  3. OpenTTD 15.3 source / engine implementation
  4. historical OpenTTDLab / 13.4 behavior
- Remote project-local docs repo (`OpenTTD-Docs`) completeness is **unverified**; verify
  OpenTTD behavior against official 15.3 docs and / or 15.3 sources.

## Why AdminPort + GameScript

- OpenTTD 15.3 provides a native path between an external AdminPort client and the active
  GameScript; incoming AdminPort GameScript JSON becomes a `GSEventAdminPort`; GameScript
  sends back via `GSAdmin.Send(table)`. No filesystem polling needed (CONTEXT §6).
- `GSCompanyMode(company_id)` scopes commands to the selected company: construction owned
  by the company, costs charged to it, insufficient funds can fail commands, normal
  ownership constraints apply (CONTEXT §7).

## GameScript lifecycle rules

- `Start()` must remain alive: loop + `Sleep(1)`. Returning terminates the script.
  `Sleep()` counts **script ticks**, not wall-clock milliseconds (CONTEXT §15).
- Event queue: `GSEventController.IsEventWaiting` / `GetNextEvent`; events of interest
  include industry open/close, vehicle crashed/lost, company bankrupt, station first
  vehicle, town founded, AdminPort message (CONTEXT §17).
- Save/load: `Save()` persists integer/string/array/table/bool/null; pending events must
  not be assumed to survive; commands must be retry-safe around `request_id`.

## Native facts captured from the project's own records

These are established by retained evidence/records, not folklore:

- A prepared save's stored GameScript/AI identity can resolve to the engine dummy AI if no
  staged AI exists; dummy AI dies instantly (`Start()` returns → `ScriptInstance::Died()`)
  while a live GameScript still warns on save. Repairs stage the stored AI package and
  treat `which is no longer available` save-load fallback wording as fatal (E15).
- Same-type, same-town industry planning rule rejected a coal-mine build in Attempt 10
  (`multiple_industry_per_town=0`); later network preparation explicitly sets and checks
  `economy.multiple_industry_per_town=true` ([[04-Evidence/Failed Attempts]]).
- Tree tiles grow/die by economy mechanics (`tree_cmd.cpp` `TileLoop_Trees`), which is why
  the V2 census at a later instant disagreed on 6 tiles (E16 + reconciliation record).
- Terraforming is `CMD_TERRAFORM_LAND` (raise/lower corner), `LevelTiles` prohibited per
  project analysis (partial-apply + test/exec divergence), and terrain-modification
  execution is **PROVEN** at bounded scope by D3 (E10, E19).
- Clearing is `GSTile.DemolishTile` / `CMD_LANDSCAPE_CLEAR`, proven by D2/E17 (single tile,
  £15) and D3/E19 (£30/£45).

## Useful GameScript APIs (catalog from CONTEXT §8, grouped)

Roads: `GSRoad.BuildRoad/BuildRoadFull/BuildOneWayRoad`, `BuildRoadDepot`,
`BuildRoadStation`, `BuildDriveThroughRoadStation`, `RemoveRoad/Depot/Station`.
Orders: `GSOrder.AppendOrder/InsertOrder/RemoveOrder/MoveOrder/SkipToOrder/CopyOrders/
ShareOrders/SetOrderFlags/SetOrderCondition/SetOrderCompareFunction/SetOrderCompareValue/
SetOrderRefit`.
Map: `GSMap.GetMapSize(,X,Y)`, `GetTileIndex`, `GetTileX/Y`, `DistanceManhattan/Square`,
`IsValidTile`.
Tiles: `GSTile.IsBuildable(IsBuildableRectangle)`, `GetSlope`, `GetMinHeight/GetMaxHeight`,
`GetOwner`, `HasTransportType`, `GetCargoAcceptance`, `GetCargoProduction`,
`GetTownAuthority`, `GetClosestTown`.
Industries: `GSIndustry.GetIndustryCount/GetLocation/GetIndustryType`,
`GetLastMonthProduction/Transported/TransportedPercentage`, `GetAmountOfStationsAround`.
Stations/cargo: `GSStation.GetCargoWaiting*` / `GetCargoPlanned*`
(so the Python optimizer can consume network/cargo state without parsing savegames).
Terraform (15.3): `GSTile.RaiseTile/LowerTile/LevelTiles(prohibited by project)/DemolishTile`

Existence of any console/RCON command must be verified against 15.3 docs/sources before
use (CONTEXT §18).

## GameScript must stay thin

Execution-only bridge: process AdminPort requests, run synchronous commands under
`GSCompanyMode`, emit bounded correlated messages, expose readback. **All optimization,
planning, identity and validation live in Python** ([[01-Architecture/Planning and Execution Boundary]]).

## Execution-style (test-before-execute)

`Plan → Validate/Test → Execute → Verify actual state → Receipt`
(CONTEXT §12). `GSAsyncMode` exists but queued results can differ from estimates; initial
proofs use deterministic synchronous behavior.
