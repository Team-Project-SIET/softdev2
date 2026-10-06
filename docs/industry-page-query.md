# OpenTTD 15.3 industry page query

Controlled implementation only. Local `CONTEXT.md` is the architecture authority.
The secure ACK and independently verified world-info real milestones are already
passed. This change neither rewrites their retained proof evidence nor claims a
real industry proof. No game launch, live Admin connection, production proof
preparation, source freeze, or P08 integration is part of this slice.

## Protocol and cursor

Python → authenticated AdminPort → thin GameScript → compact response → Python
observation. AdminPort remains a control/query/telemetry plane, not a bulk map pipe.
Protocol 1 uses exact fields, safe ASCII request IDs of 1–64 bytes, strict integer
fields (booleans are not integers), and compact sorted-key JSON on Python output.

First page:

```json
{"after_id":null,"limit":5,"protocol":1,"request_id":"industries-0","type":"industry_page"}
```

Continuation:

```json
{"after_id":7,"limit":5,"protocol":1,"request_id":"industries-1","type":"industry_page"}
```

Response (one-record intermediate page requested with limit 1):

```json
{"has_more":true,"industries":[{"id":7,"tile":71,"type":12,"x":7,"y":1}],"next_after_id":7,"protocol":1,"request_id":"industries-0","status":"ok","type":"industry_page_result"}
```

`after_id` is null for the first page or an industry ID in 0..63999. Return only IDs
strictly greater than the cursor, in strictly ascending order. `limit` is 1..5.
An intermediate page must have exactly `limit` records, `has_more=true`, and
`next_after_id` equal to the last record's ID. A final page, including an empty
world or exhausted cursor, has `has_more=false` and `next_after_id=null`.
An exactly full final page is final if the validity lookahead finds no further ID.
Repeated requests produce the same response in an unchanged world; a transport
session still requires fresh request IDs to prevent delayed-response reuse.

Pagination is a best-effort observation of a live world, not an atomic snapshot.
Industry creation/removal or ID reuse across pages can change the observed inventory.
The controlled fixtures and future proof world must remain stable throughout the
sequence. Snapshot/session generations are deferred. Stable-world fixtures have
no overlaps or gaps, including naturally sparse IDs.

## Exact 15.3 API authority

Verified against the official **15.3 tag**, not historical AI examples:

- [script_industrylist.hpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industrylist.hpp):
  `GSIndustryList()` inherits `GSList`; native `FillList<Industry>` enumerates the
  industry pool, not map tiles.
- [script_industry.hpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.hpp):
  `GSIndustry.IsValidIndustry(id)`, `GSIndustry.GetLocation(id)`,
  `GSIndustry.GetIndustryType(id)`. The location is the engine's industry location
  origin; it is not a footprint or proof that reverse tile lookup identifies the industry.
- [script_map.hpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_map.hpp):
  `GSMap.IsValidTile(tile)`, `GSMap.GetTileX(tile)`, `GSMap.GetTileY(tile)`,
  `GSMap.GetMapSizeX()`, `GSMap.GetMapSizeY()`.
- [script_list.hpp](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_list.hpp):
  `source.Sort(GSList.SORT_BY_ITEM, GSList.SORT_ASCENDING)`, `Begin()`, `Next()`,
  `IsEnd()`. Explicit documented sorting removes dependence on default list order.
- [API CMake configuration](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/CMakeLists.txt)
  selects `game;GS`; [SquirrelExport.cmake](https://github.com/OpenTTD/OpenTTD/blob/15.3/cmake/scripts/SquirrelExport.cmake)
  replaces the `Script` prefix with `GS` and registers inherited classes/methods
  marked `@api ai game`. This verifies the generated GameScript names by source
  inspection; the controlled Squirrel VM is not an engine-binding compatibility proof.

`tests/reference/industry_page_bindings_15_3/manifest.json` records exact official
URLs and SHA-256 hashes for 16 API, engine, and generator files. Pre-existing
industry references matched the remote tag byte for byte; world-info references
and all historical proof files were left intact.

`industry_type.h` establishes 64000 IndustryID pool slots and 240 industry types.
The transport accepts ID 0..63999 and type 0..239 (numeric domain, not proof that a
particular NewGRF type exists). `map_func.h` establishes row-major tile indexing:
`tile = y * width + x`. Python validates against supplied, already verified
`WorldInfoResponse` dimensions. Industry origins need not be occupied industry tiles.

## Payload bound

The shared application bound stays **512 bytes**; no global limit changed.
The documented native `GSAdmin.Send` ceiling stays **1450 bytes**.
15.3 `ScriptAdmin::Send` converts the fixed Squirrel table to compact
`nlohmann::json::dump()` output. Safe ASCII IDs need no JSON escaping.

Conservative fields: 64-byte request ID, five-digit industry ID/cursor, three-digit
type, ten-digit tile (non-sentinel uint32), five-digit coordinates. Each record
plus its separator costs at most 62 bytes. An over-approximated envelope costs
192 bytes (allowing numeric cursor together with the longer `false` token, even
though final-page semantics require null). Thus:

`floor((512 - 192) / 62) = 5`

Five-record conservative bound: **502 bytes**; six: **564 bytes**. Application
headroom: **10 bytes**; native headroom: **948 bytes**. Strictly ascending real
records and valid final/intermediate cursor semantics can be smaller. Requests
also remain comfortably inside 512. Parsers/packet encoders reject oversized
messages; GameScript limits fixed fields and record count before send.

## GameScript work and read-only policy

Each request constructs one native industry-ID list, selects native item-ascending
iteration, filters IDs through the cursor, and checks validity. It reads location,
type and coordinates for at most five returned industries, plus validity-only
lookahead for `has_more`. Invalid (removed) list members are skipped. Invalid
location/type or duplicate/out-of-order returned IDs reject the query without a
response; there is no repair or retry.

The native list inherently contains the current industry IDs, potentially the
whole industry pool. No second ID array, full world snapshot, or industry-record
cache is built in GameScript. Native sorting uses the existing ordered item map
(`ScriptListSorterItemAscending`); it does not run a Squirrel sorting callback.
Cursor filtering still traverses the ID prefix: worst-case O(number of industry
IDs) per page, not O(page size) enumeration. This is not a constant-opcode claim.
The engine can yield script execution as its opcode budget requires. Record work
and output are bounded; the event loop retains its bounded batch and script-tick
yield. Future native cursor seeking can be considered if prefix work matters.

No full-map scan, optimizer, pathfinder, analytics, cargo aggregation, footprint
enumeration, construction, company mode, vehicles, orders, terraform, finance,
industry creation/removal, or RCON command is used. The test allowlists retain
only the exact read/query/event/log/send APIs required by ping, world-info, and
this industry slice.

## Python boundaries and validation

`industry_page.py`: frozen `IndustryPageRequest`, `IndustryRecord`,
`IndustryPageResponse`, digest-bound receipt and exchange. Response records are
an immutable tuple. Strict parsing rejects extra/missing/duplicate JSON keys,
invalid integer/domain values, wrong response type/status/protocol, wrong request
ID, unsorted/duplicate IDs, invalid cursor/progress, oversized and malformed pages.
Location validation requires x/y bounds and the row-major tile equation.

`GameScriptTransport.industry_page(request, world)` reuses the supplied secure
session. The shared bounded query engine preserves world-info's subscription and
completion barriers, distinct timeout/disconnect/protocol failures, no retries,
and duplicate-response rejection. Unrelated non-lifecycle Admin packets are ignored.

`industry_query.collect_industries(...)` is the Python observation assembly seam.
It returns `list[IndustryRecord]` after all correlated pages pass validation. It
binds every exchange to the exact sent request, validates across-page ascending
IDs/duplicates and cursor progress, and uses a finite page budget. Exhaustion
raises rather than returning partial success. Default budget and the unchanged
transport-session request cap are 256; prior requests consume session capacity.
Large inventories/session rotation are outside this first slice. No connection
is opened by the helper. DTOs, query client, and observation assembly import no
P08/planning domain contracts; future mapping to `PreparedWorldManifest` belongs
above this layer.

## Evidence and verification limits

Each page is its own request-ID-correlated transaction. Native GameScript order:

`BRIDGE_REQUEST_RECEIVED → INDUSTRY_PAGE_READ → BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE`

The read marker contains request ID, after-ID, requested limit, returned count,
next cursor, and has-more. The send marker is emitted only after successful send;
liveness follows the existing tick yield. The evidence parser selects each
transaction from a multi-page log, rejects duplicate/reordered/non-native markers,
and retains source log, line numbers, structured metadata, and raw-log SHA-256.
It does not add a whole-payload log line.

Python/Admin order:

`INDUSTRY_PAGE_REQUEST_SENT → INDUSTRY_PAGE_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → PAGE_VALIDATED`

Receipts bind request/response SHA-256 digests; semantic page validation is a
separate step. There is no total timestamp ordering across Python and GameScript
channels. Correlation binds the two locally ordered chains, not a fabricated
cross-process clock.

Transport/protocol verification proves envelope correlation and bounded exchange.
Record semantic validation proves domain ranges, ordering, cursor and location
consistency using verified world dimensions. **SERVER_WELCOME has no independent
industry inventory**. This slice and a future real industry proof cannot claim an
independent second-source industry-list comparison. World-info's independently
verified GameScript/SERVER_WELCOME map-dimension claim remains unchanged.

This is the first bounded world-entity query, not full P08 extraction: no cargo,
production, transported amounts, stockpiles, names, stations, footprint, NewGRF
metadata, candidate graph, planner optimization, or preparation manifest mapping.
Real industry-proof preparation and source freeze remain a separate task.

The existing shared prelaunch safety guard formerly banned all `GSIndustry`
references. Its small compatibility update permits only `GSIndustryList` and the
three read-only `GSIndustry` methods above, retaining all other mutation bans.
Controlled preflight/CLI regression fixtures use the updated bridge-package hash;
retained historical prelaunch/proof identities are never rewritten. No
industry-proof command, lifecycle, preparation, or source freeze is added.

## Controlled verification

Final focused industry tests: **63 passed**, including an actual maximum-field
Squirrel response of **501 bytes** (inside the conservative 502-byte bound) and
send-failure evidence/liveness behavior. Focused compatibility run: **409 passed**
(before the final two additional industry checks). Ordinary suite:
**1437 passed, 38 skipped**; real-runtime/PostgreSQL opt-ins were not enabled.

Ordinary coverage includes world-info 45, world-info proof 30, bridge 18,
bridge protocol 29, bridge transport 23, secure Admin/crypto 62, proof evidence 25,
causality 28, production proof CLI 5, external runtime 28, P04 observer 34,
P03 transport/world evidence/live controlled 73 (one opt-in skipped), P05 optimizer
37, P06 execution 51, P07 evaluation/realized/proof harness 43 (three migration
opt-ins skipped), and P08 preparation/probe/lifecycle 78 controlled tests.

Ruff check, format check, applicable `ty` check over OpenTTD/planning source and
relevant typed tests, `git diff --check`, authored-file whitespace audit, and
transport/query import-boundary audit passed. A broader exploratory typecheck
also included `tests/test_planning.py`; it exposes 15 pre-existing diagnostics
in invalid-input/string-to-Decimal tests, outside this change. No unrelated tests
or planner code were changed to suppress those diagnostics. Standards and Spec
reviews both reported zero findings.

Gameplay launches: **0**. Live Admin connections: **0**. All industry runtime
behavior used the controlled Squirrel fake API and supplied fake streams.
No industry real-proof preparation was run; no commit or push was performed.
