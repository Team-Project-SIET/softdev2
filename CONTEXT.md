# OpenTTD Integration Project Context

## 1. Project Goal

The goal is to connect the existing Python logistics/planning system to **real OpenTTD 15.3** and allow externally generated plans to be:

1. created by Python,
2. validated,
3. executed inside OpenTTD,
4. verified against actual game state,
5. returned as machine-verifiable execution evidence.

The project should use documented OpenTTD 15.3 APIs and engine behavior rather than depending on assumptions inherited from older OpenTTDLab/OpenTTD 13.4 experiments.

---

## 2. Primary Runtime Target

Current target:

```text
OpenTTD 15.3
Linux generic amd64
```

Local OpenTTD installation:

```text
/home/fed/Downloads/openttd-15.3-linux-generic-amd64
```

OpenTTD 13.4 is **not** a project requirement.

Earlier use of OpenTTD 13.4 came from the OpenTTDLab environment and should be treated only as a historical compatibility/regression baseline.

---

## 3. Main Codebase

Primary project repository:

```text
https://github.com/Team-Project-SIET/softdev2.git
```

Development work has been performed on:

```text
devmodule2
```

The project is primarily Python.

Important technologies already used include:

```text
Python
OR-Tools
SQLAlchemy
PostgreSQL
Alembic
pytest
Ruff
uv
Docker Compose
```

Do not rewrite unrelated planner/domain logic when changing the OpenTTD integration.

The preferred strategy is to isolate/refactor the OpenTTD adapter/transport/executor boundary.

---

## 4. OpenTTD Documentation Authority

The repository:

```text
https://github.com/AgnesTachyon-feet/OpenTTD-Docs.git
```

is intended to serve as the project-local OpenTTD documentation repository.

Locally researched/generated OpenTTD 15.3 documentation is usable when its contents and version have been verified. Do not assume that the remote GitHub contents currently contain all referenced OpenTTD 15.3 AI, GameScript, or engine documentation unless verified; remote documentation availability remains unverified.

When project-local documentation is unavailable or incomplete, verify OpenTTD-specific behavior against official OpenTTD 15.3 documentation and/or OpenTTD 15.3 source code.

When implementing or reviewing OpenTTD behavior, prefer evidence in this order:

1. verified OpenTTD 15.3 project-local documentation
2. official OpenTTD 15.3 documentation
3. OpenTTD 15.3 source / engine implementation
4. historical OpenTTDLab / OpenTTD 13.4 behavior

Fresh verified OpenTTD 15.3 evidence always overrides historical assumptions. Do not assume old OpenTTD behavior still applies to 15.3 without verification.

---

# 5. Architecture Direction

## Previous Architecture

Earlier proof work assumed approximately:

```text
Python Planner
      |
      v
plan / transport file
      |
      v
Thin AI
      |
      v
OpenTTD
```

This approach should no longer be assumed to be the final architecture.

P03/P06 established real-game proofs of the Thin AI / transport approach on OpenTTD 13.4 through OpenTTDLab. P07 has controlled integration coverage; real plan-attributed evaluation remains unproven. These remain historical regression evidence, not proof of OpenTTD 15.3 compatibility or the selected 15.3 architecture.

---

## Preferred Architecture

Current preferred architecture:

```text
┌─────────────────────┐
│ Python Planner      │
│ OR-Tools / logic    │
└──────────┬──────────┘
           │
           │ command protocol
           ▼
┌─────────────────────┐
│ Python AdminPort    │
│ Client / Transport  │
└──────────┬──────────┘
           │
           │ JSON
           ▼
┌─────────────────────┐
│ OpenTTD AdminPort   │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ Bridge GameScript   │
└──────────┬──────────┘
           │
      GSCompanyMode
           │
      validate/test
           │
         execute
           ▼
┌─────────────────────┐
│ OpenTTD 15.3       │
│ Real Game World     │
└──────────┬──────────┘
           │
           ▼
    evidence / receipt
           │
           ▼
┌─────────────────────┐
│ Python Verifier     │
└─────────────────────┘
```

The GameScript should remain a relatively thin integration/execution bridge.

Complex route optimization and logistics planning should remain in Python.

---

# 6. Why GameScript + AdminPort

OpenTTD 15.3 provides a native communication path between an external AdminPort client and the active GameScript.

Relevant protocol concepts include:

```text
ADMIN_PACKET_ADMIN_GAMESCRIPT
ADMIN_PACKET_SERVER_GAMESCRIPT
ADMIN_UPDATE_GAMESCRIPT
```

The engine converts incoming AdminPort GameScript JSON into:

```text
GSEventAdminPort
```

GameScript can send information back using:

```text
GSAdmin.Send(table)
```

Therefore external Python ↔ OpenTTD communication does not need to depend on filesystem polling.

---

# 7. GSCompanyMode

A major reason GameScript is preferred is:

```text
GSCompanyMode(company_id)
```

Within this scope, commands execute on behalf of the selected company.

This means:

- construction is owned by the company,
- costs are charged to that company,
- insufficient funds can cause failure,
- normal ownership constraints apply.

This allows the GameScript bridge to execute real player/company operations.

OpenTTD 14+ significantly expanded company-control capabilities available to GameScript, so OpenTTD 15.3 is preferred over the old 13.x environment.

---

# 8. Useful OpenTTD APIs

## Roads

Examples:

```text
GSRoad.BuildRoad
GSRoad.BuildRoadFull
GSRoad.BuildOneWayRoad
GSRoad.BuildRoadDepot
GSRoad.BuildRoadStation
GSRoad.BuildDriveThroughRoadStation
GSRoad.RemoveRoad
GSRoad.RemoveRoadDepot
GSRoad.RemoveRoadStation
```

---

## Orders

OpenTTD 15.3 GameScript supports operations including:

```text
GSOrder.AppendOrder
GSOrder.InsertOrder
GSOrder.RemoveOrder
GSOrder.MoveOrder
GSOrder.SkipToOrder
GSOrder.CopyOrders
GSOrder.ShareOrders
GSOrder.SetOrderFlags
GSOrder.SetOrderCondition
GSOrder.SetOrderCompareFunction
GSOrder.SetOrderCompareValue
GSOrder.SetOrderRefit
```

---

## Map

Useful world extraction APIs:

```text
GSMap.GetMapSize
GSMap.GetMapSizeX
GSMap.GetMapSizeY
GSMap.GetTileIndex
GSMap.GetTileX
GSMap.GetTileY
GSMap.DistanceManhattan
GSMap.DistanceSquare
GSMap.IsValidTile
```

---

## Tiles

Examples:

```text
GSTile.IsBuildable
GSTile.IsBuildableRectangle
GSTile.GetSlope
GSTile.GetMinHeight
GSTile.GetMaxHeight
GSTile.GetOwner
GSTile.HasTransportType
GSTile.GetCargoAcceptance
GSTile.GetCargoProduction
GSTile.GetTownAuthority
GSTile.GetClosestTown
```

---

## Industries

Examples:

```text
GSIndustry.GetIndustryCount
GSIndustry.GetLocation
GSIndustry.GetIndustryType
GSIndustry.GetLastMonthProduction
GSIndustry.GetLastMonthTransported
GSIndustry.GetLastMonthTransportedPercentage
GSIndustry.GetAmountOfStationsAround
```

---

## Stations and Cargo Flow

Useful APIs include:

```text
GSStation.GetCargoWaiting
GSStation.GetCargoWaitingFrom
GSStation.GetCargoWaitingVia
GSStation.GetCargoPlanned
GSStation.GetCargoPlannedFrom
GSStation.GetCargoPlannedVia
GSStation.GetCargoPlannedFromVia
```

These APIs may allow the Python optimizer to consume real network/cargo state without parsing savegames directly.

---

# 9. World-State Extraction

The GameScript bridge may also serve as a world-state extractor.

Possible Python-side representation:

```text
WorldState
├── map
├── towns
├── industries
├── stations
├── vehicles
├── infrastructure
└── companies
```

Do not send the entire world in one AdminPort packet.

Prefer paginated/chunked requests:

```text
map_info

industries page=0
industries page=1

stations page=0

vehicles page=0

tiles region=x1,y1,x2,y2
```

---

# 10. AdminPort Message Size

`GSAdmin.Send(table)` converts the supplied table to JSON.

The generated JSON must not exceed:

```text
1450 bytes
```

Therefore the application protocol should use small messages.

Example:

```json
{
  "type": "command_result",
  "request_id": "p08-000123",
  "status": "ok",
  "object_id": 42
}
```

Large snapshots must be chunked. Do not assume an equivalent inbound AdminPort → GameScript limit without evidence.

---

# 11. Command Protocol

Every externally initiated operation should have a stable:

```text
request_id
```

Suggested lifecycle:

```text
COMMAND
   ↓
ACCEPTED
   ↓
VALIDATED
   ↓
EXECUTED
   ↓
VERIFIED
   ↓
COMPLETED
```

Failure states should include at least:

```text
REJECTED
FAILED
TIMEOUT
DUPLICATE
```

Do not use wall-clock sleeps as proof that OpenTTD finished an operation.

---

# 12. Test Before Execute

The integration should follow:

```text
Plan
  ↓
Validate / Test
  ↓
Execute
  ↓
Verify actual state
  ↓
Receipt
```

Use OpenTTD test/execution facilities where appropriate.

`GSAsyncMode` exists but should not be the default for the initial controlled proof because queued command results can differ from initial estimates.

Initial proofs should prioritize deterministic synchronous behavior.

---

# 13. Proof and Evidence

A GameScript message saying:

```text
"success"
```

is not sufficient proof by itself.

Evidence should ideally combine:

```text
planner request
      ↓
GameScript execution result
      ↓
actual world-state verification
      ↓
AdminPort command/log evidence where available
      ↓
receipt
```

Useful AdminPort subscriptions include:

```text
ADMIN_UPDATE_DATE
ADMIN_UPDATE_COMPANY_INFO
ADMIN_UPDATE_COMPANY_ECONOMY
ADMIN_UPDATE_COMPANY_STATS
ADMIN_UPDATE_CONSOLE
ADMIN_UPDATE_CMD_NAMES
ADMIN_UPDATE_CMD_LOGGING
ADMIN_UPDATE_GAMESCRIPT
```

`ADMIN_UPDATE_CMD_LOGGING` is especially relevant for controlled real-game proof.

---

# 14. Save / Load / Idempotency

GameScript `Save()` can persist basic serializable data such as:

```text
integer
string
array
table
bool
null
```

Pending events should not be assumed to survive save/load.

Commands must therefore be retry-safe.

Example:

```json
{
  "request_id": "p08-000123",
  "command": "build_road"
}
```

The bridge should remember enough information about completed commands to avoid executing the same request twice after:

```text
reconnect
retry
load game
process restart
```

---

# 15. GameScript Lifecycle

`Start()` must remain alive.

Correct shape:

```nut
function Start()
{
    while (true) {
        // process messages/events
        Sleep(1);
    }
}
```

Returning from `Start()` terminates the script.

`Sleep()` operates in script ticks, not wall-clock milliseconds.

Python must therefore depend on explicit protocol acknowledgements instead of assumptions about elapsed time.

---

# 16. API Version

For OpenTTD 15.3:

```nut
function GetAPIVersion()
{
    return "15";
}
```

Do not use:

```text
"15.3"
```

OpenTTD >= 12 uses major-version API identifiers.

---

# 17. Events

GameScript provides an event queue:

```text
GSEventController.IsEventWaiting
GSEventController.GetNextEvent
```

Relevant events include:

```text
industry opened
industry closed
vehicle crashed
vehicle lost
company bankrupt
station first vehicle
town founded
AdminPort message
```

Future architecture may use:

```text
initial world snapshot
+
incremental event updates
```

instead of repeatedly extracting the entire world.

---

# 18. RCON

AdminPort also exposes remote console execution.

Relevant protocol concept:

```text
ADMIN_PACKET_ADMIN_RCON
```

Potential future uses include:

```text
game/server lifecycle automation
saving
loading
console inspection
script management
test orchestration
```

Do not assume a specific console command exists until it has been verified against OpenTTD 15.3 documentation/source.

---

# 19. Existing P03 Work

P03/P06 established real-game proofs on OpenTTD 13.4 through OpenTTDLab. P07 has controlled plan-attributed evaluation coverage.

Those proofs remain useful historical regression evidence.

They demonstrate that the previous Thin AI / transport approach was capable of working in the OpenTTD 13.4 environment.

They must NOT be treated as proof of OpenTTD 15.3 compatibility.

The project is now intentionally evaluating a different integration boundary for OpenTTD 15.3 based on AdminPort + GameScript.

Lessons from P03 should be preserved:

- deterministic tests,
- explicit proof criteria,
- controlled real-game attempts; no repeated uncontrolled attempts,
- retained logs/evidence,
- cleanup after execution,
- do not claim success without execution evidence proving actual behavior.

Do not preserve the old transport mechanism merely because code already exists.

---

# 20. Current implementation and evidence status

Status reviewed on 2026-10-11 against branch `devmodule2`, baseline commit
`b10cd2d` before this documentation update.

Committed OpenTTD 15.3 work includes secure AdminPort transport, correlated ACK,
world information, paginated industry inventory, capability enrichment, cargo
catalog, same-run structural observation and production observation contracts.
Python assembles typed observation and evidence models; the GameScript remains thin.

Production completeness means exact produced-pair coverage. Planning qualification
also requires a coherent observed economy-month window and stability checks.
The audited V1 response remains bounded to 335 bytes, with at most 512 production
requests. `production_level` is deferred.

Two-rollover qualification Attempt 2 reached native SUCCESS/COMPLETED with complete,
qualified observations. Mandatory post-run offline verification failed, so overall
Attempt 2 remains FAILED. Historical validation and next-attempt derivation have
since been separated. Attempt 3 readiness requires fresh authorization and does
not change either consumed attempt's status. See
[qualification readiness](docs/two-rollover-qualification-attempt3-readiness.md).

The committed [controlled P08-to-P05 verification](docs/p08-15-3-controlled-end-to-end-p05-verification.md)
composes observation admission, supplemental facts, prepared-source correspondence,
bounded road generation, P05 optimization and execution-plan validation. Controlled
source bytes are not an executable save. Accepted bytes and schemas do not establish
runtime correspondence. P05 consumes supplied candidates; it does not perform YAPF
or arbitrary terrain search.

Local uncommitted work also contains preparation/extraction modules, terrain
acquisition, company-owned road mutation, freight infrastructure, vehicle lifecycle
and a bounded freight-delivery proof. Local reports record road construction and
vehicle departure proofs. This documentation commit does not publish those sources,
reports or runtime artifacts. End-to-end native P08/P05 execution, attributed 15.3
evaluation and closed-loop optimization remain incomplete.

---

# 21. Refactoring Principle

Do not rewrite the planner.

Prefer:

```text
existing planning/domain logic
          +
new OpenTTD adapter
          +
AdminPort transport
          +
GameScript bridge
```

Conceptually:

```text
Planner
   ↓
OpenTTDCommand / Plan
   ↓
OpenTTD Adapter
   ↓
AdminPort Transport
   ↓
GameScript Executor
   ↓
Real OpenTTD
```

OpenTTD-specific concepts should remain isolated from the core optimization/domain layer where practical.

---

# 22. Initial transport proof and next engineering direction

The initial AdminPort + GameScript round trip has been proven. The following criteria describe that initial transport milestone, not the full planner/executor acceptance gate.

Initial transport proof:

```text
Python Admin client
  ↓
ADMIN_PACKET_ADMIN_GAMESCRIPT
  ↓
OpenTTD 15.3
  ↓
GSEventAdminPort
  ↓
Bridge GameScript
  ↓
GSAdmin.Send(...)
  ↓
Python receives ACK
```

Success criteria:

1. Python connects to the real OpenTTD 15.3 AdminPort.
2. Python sends one small identifiable JSON request.
3. The running GameScript receives the corresponding AdminPort event.
4. The GameScript sends an acknowledgement using `GSAdmin.Send()`.
5. Python receives and correlates that ACK using the request ID.
6. Evidence/logs prove the complete round trip.

No game-world mutation is required for this proof. Do not start with road construction, vehicle execution, full P06 executor replacement, P08 whole-world extraction, or large planner refactoring.

Only after this round-trip transport is proven:

```text
GSCompanyMode
  ↓
test/validate
  ↓
one small real command
  ↓
world-state verification
  ↓
receipt
```

A small deterministic proof is more valuable than implementing a complete road/vehicle planner before proving the bridge.

---

# 23. Non-Goals for Initial Proof

Do not initially optimize for:

```text
maximum performance
large maps
full network extraction
async command batching
multiplayer production deployment
complete transport-mode support
all vehicle types
all OpenTTD versions
BaNaNaS / Online Content publishing
GameScript public distribution
```

BaNaNaS is an optional future distribution layer only.

Initial target:

```text
OpenTTD 15.3
single controlled environment
small JSON request / correlated ACK
no game-world mutation
deterministic evidence
```

---

# 24. Working Rule for Future Chats / Agents

This file is the canonical project context. It is included in version control by explicit user instruction. Keep committed capabilities, local uncommitted work, historical evidence, controlled verification and accepted native proof distinct.

Before modifying OpenTTD integration code:

1. inspect current repository state;
2. inspect relevant existing P03/P08 implementation;
3. verify OpenTTD-specific assumptions against the 15.3 docs;
4. preserve working domain/planner behavior;
5. change the smallest necessary integration boundary;
6. run focused tests first;
7. run ordinary quality gates afterward;
8. perform real-game proof only when prerequisites pass;
9. retain evidence/logs from the controlled attempt;
10. do not claim success without actual execution evidence.

When this file conflicts with fresh verified OpenTTD 15.3 documentation, update this file rather than silently working around the conflict.
