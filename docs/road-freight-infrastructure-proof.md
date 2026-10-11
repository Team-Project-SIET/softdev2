# OpenTTD 15.3 road freight infrastructure proof

This bounded probe reuses the proven road runner's secure Admin session, generated
64x64 seed-42 disposable world, no-op company AI, source seal, native saves and
cleanup. Python owns admission and receipt verification. The separate version-15
`RoadFreightProof` GameScript tests and constructs one horizontal four-tile layout:

```text
bay truck stop -> access road start -> access road end <- road depot
```

All four sites must be native-observed flat, equal-height, vacant and unowned. The
bounded candidate policy contains the existing 32 access-road pairs. Nonvacant
sites are skipped during discovery. Any failed native test, affordability gate,
construction or independent readback stops the attempt. No alternate construction
site, reconnect, retry, rollback or second launch follows a failed admission.

## Exact API authority

The [tagged 15.3 road API](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.hpp)
and [implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_road.cpp)
provide `BuildRoadFull(start,end)`,
`BuildRoadStation(start-1,start,ROADVEHTYPE_TRUCK,GSStation.STATION_NEW)` and
`BuildRoadDepot(end+1,end)`. Both facilities have explicit adjacent entrance tiles.
`GSCompanyMode(0)` supplies ownership and charges the company's funds.
`GSAccounting` with `GSTestMode` observes each cost before admission and again
immediately before its command. The 10000 total cost limit is an authorization
ceiling, not a cost estimate. Independent nonoverlapping test sites avoid assuming
that test mode simulates a preceding construction.

Readback uses `IsRoadTile`, `IsRoadStationTile`, `IsRoadDepotTile`, exact facility
front tiles and `GSTile.GetOwner`. The [15.3 station API](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_station.hpp)
checks a valid owned station with truck-stop capability and no bus-stop capability.
The [15.3 road-bit implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/road_map.cpp)
includes bay-stop and depot entrance bits, so `AreRoadTilesConnected` can check all
three links in both directions.

## Proof gates and limits

Focused tests exercise the actual Squirrel handler with controlled APIs, the
simulated one-shot lifecycle and retained receipt replay. A simulated lifecycle is
not native evidence. Tests cover admission failures, each rejected command,
incorrect ownership/entrances/connectivity, changed costs, independent read
mismatch, stale packages, invalid actions and retained-artifact corruption.

The immutable prelaunch record binds the pinned binary and source hashes, staged
package, generated world, exact execution command, candidate policy and expected
readback. The final construction plan binds that seal, before-save bytes, native
site facts and three observed native test costs. Limits are one process, one continuous
secure connection, 38 requests, three distinct construction commands, no retries,
no reconnects, 512-byte application responses and the 1450-byte GSAdmin limit.

After each construction Python requests an independent native read and verifies
stage topology, owners and spending before advancing. The aggregate receipt binds
all three construction/read pairs, stable station identity, total spending and
before/after saves. Offline verification replays ordered unique secure frames,
plan/save hashes and cleanup evidence. Historical artifacts remain unchanged.

## Native outcome

The single authorized attempt passed on OpenTTD 15.3. Ten bounded inspections
selected vacant tiles 1291–1294. Company 0 built full access road on 1292–1293, a
bay truck stop at 1291 facing 1292, and a depot at 1294 facing 1293. Three distinct
commands returned `BUILT`; three subsequent native `read` operations verified
ownership, truck-stop station ID 0, exact fronts and bidirectional topology.
Funds were 100000 before construction, then 99686, 99379 and 98989. Observed test
costs and actual spending agreed at 314, 307 and 390, totaling 1011.

The retained plan digest is
`768dc6dcb02e8464a77f088b2bc9ee21a4ca01630b3423e08c9968880a5fa9f1`.
The prelaunch digest is
`bc529369ed117acce0eebb9b43d2bda291d814a619dceddef47496cdb602ec1b`.
Evidence is retained at
`artifacts/runtime/openttd-15.3-road-freight-infrastructure-attempt1/`, including
source/package copies, controlled gates, immutable seal/claim, native secure
frames, all requests/responses, before/after saves, plan, receipt and cleanup.

The offline `verify` command passed. Exactly one launch, one connection attempt,
one continuous secure connection and 16 requests were used. There were no retries,
reconnections or second launch. Cleanup reaped the process, closed the stream and
listeners, removed the credential and disposed the owned workspace. All 1956
pre-existing runtime artifacts remain byte-identical, and the previous native
road-segment receipt still verifies. Focused tests passed with 163 tests; Ruff,
format, scoped typecheck and whitespace checks passed.

This proves infrastructure only; no vehicles, orders or freight deliveries are included.
