# Controlled OpenTTD 15.3 terrain/road query implementation

Local CONTEXT.md is architecture authority. This implements the first slice of
[native terrain/road design](p08-15-3-native-terrain-road-acquisition-design.md).
It establishes controlled behavior only: no native launch, live connection,
real request, qualification, save capture, construction or proof freeze occurred.
The preceding design and historical evidence remain unchanged.

## Public interfaces and composition

- `terrain_bridge_source()` in `terrain_bridge.py` composes the existing raw
  bridge with `terrain_bridge.nut`. The historical raw and qualification packages
  remain byte-identical. The extension inherits the existing event loop and its
  post-yield `BRIDGE_POST_RESPONSE_ALIVE` marker. Dispatch uses
  `RawObservationBridge.Handle.call(this, request)`, never `base.Handle`.
- `tile_facts.py` contains frozen protocol requests/responses, correlated SHA-256
  receipts and immutable exchanges. These are wire DTOs, not another tile domain.
- Existing `GameScriptSession` outbound validation and `GameScriptTransport` typed
  dispatch now explicitly admit `tile_facts_page`. The existing read-query path
  supplies subscription and completion barriers; no second Admin client exists.
- `TerrainCollector(world, source, region, ...)` consumes an already-owned
  `TerrainClient`: context, session identity, existing frame observer and the
  transport's typed query method. `collect(client, evidence)` is single-use.
  An owner supplies the context/evidence association; the collector never creates
  a process, connection, credentials or optimizer.
- Accepted `TerrainObservation` retains existing `TileFact` tuples, raw diagnostic
  rows, both sweeps, evidence and WPO/source lineage. `require_supplemental(facts)`
  checks an independently complete `SupplementalPlanningFacts` bundle; it does
  not fill missing catchment, engines, settings or costs.

## Native semantics and wire schema

Tagged 15.3 source identities match the preceding audit (19 files). Read APIs:
GSMap dimensions/index/validity/X/Y; GSTile bare height/slope/buildability,
water/coast/tree/farm/rock/rough, ROAD/RAIL/WATER track status, house/station and
owner; GSIndustry industry ID/validity; GSRoad current selector, availability,
road presence/type and both directed connectivity reads; GSAirport airport tile;
GSDate economy date. No AIR transport-status query, road-bit synthesis, generic
tile taxonomy, company switch, construction call or selector mutation occurs.

Current ordinary-road selector must be 0 and available. Invalid native tiles,
sentinel height/slope or unsupported scalar values fail; they never become flat,
vacant or connected. Ownership -1 remains an ambiguous non-company result.
Road presence conservatively combines three audited predicates. Houses/stations
remain in diagnostic flags and force projected TileFact.buildable=false because
TileFact has no house/station field. Read buildability is not construction permission.

Request: protocol=1, type=`tile_facts_page`, safe ASCII request_id (1–64 bytes),
region=[x,y,width,height], cursor. Exactly five fields, no caller-specified page
limit. Coordinates are bounded by native maximum axes 4096; rectangle area ≤256.
Actual runtime dimensions and native tile validity remain authoritative.

Success: protocol, type=`tile_facts_page_result`, request_id, status=ok, region,
cursor, map=[width,height], date_before/date_after, tiles, next_cursor, has_more.
Each row is [tile,height,slope,flags,industry-or-null,owner,road0,out,in,assessed].
The existing design defines flag order and N/E/S/W masks. Connectivity is assessed
only within coverage, on valid neighboring tiles with selected road presence.
Unknown exterior relationships have assessed=0, not evidence of disconnection.

Error: protocol, result type, safe request_id, status=error, bounded error_code,
cursor-or-null, failed_tile-or-null. No unbounded exception text or partial records.
Unsafe IDs are not reflected. Errors do not obtain successful read/liveness evidence.

## Exact serialization and pagination

Python enforces raw request ≤159 bytes. Native GetObject exposes decoded objects,
not original whitespace/duplicate JSON bytes; GS validates exact decoded fields
and bounded canonical values. It cannot independently attest the raw request size.
Python rejects duplicate JSON keys, escaping IDs, unsupported versions and shapes.

The tagged `ScriptAdminMakeJSON` implementation and its tagged nlohmann `json.dump`
were compiled into an offline probe with unmodified tagged compiler/VM sources.
The probe verifies integers, negative owner, null, bools and compact key ordering.
Size vectors are arithmetic upper bounds, not admissible repeated-tile pages:

- Request upper bound: **159 bytes**.
- Maximum scalar row: **42 bytes**.
- Empty success envelope: **294 bytes**, including terminal null/false.
- n≥1 rows: `294 + 42n + (n−1) = 293 + 43n`.
- Five rows: **508 bytes**; six: **551 bytes**.
- Maximum-width reserved error vector: **227 bytes**.

All supported request strings are safe unescaped ASCII. GS constructs canonical
JSON for evidence, checks its length ≤508, and sends the typed table through the
actual native serializer. The Python command gate also enforces ≤508, inside the
512-byte application and 1450-byte native Send limits. Neither truncation nor a
larger payload limit is used. Five records/page remains unchanged.

Traversal is row-major. Cursor is an ordinal, starts at zero, and advances by
exactly the returned count; nonterminal ordinals are multiples of five. Every
page must contain min(5, remaining) rows in exact expected positions. Final cursor
is null and has_more=false. Receiving a final page alone does not prove completeness.
Oversized/out-of-map rectangles fail without cropping or expansion. The collector
receives the preliminary rectangle; it performs no OD or placement search.

## Two sweeps, provenance and trust

Both complete sweeps use the same owned process/connection/session, context,
runtime, world/configuration, bridge, region and final M2 economy month. Every page
checks map identity and nondecreasing date brackets inside M2 before continuing.
Two canonical diagnostic sequences must match exactly, including ownership and
connectivity; reciprocal directed masks are checked across tile records.

WPO construction/admission is reused without weakening qualification gates.
Source references retain WPO composition, structural, qualified-production,
runtime, configuration, bridge and content identities. Unknown industry references
are rejected. Matching two sweeps proves bounded repeatability, not atomicity,
future stability, trusted content/settings acquisition or save correspondence.

The result's semantic digest hashes the source/region/diagnostic projection and
policy `terrain-two-sweep-v1`; it is an acquisition identity, never a competing
world_fingerprint or executable PreparedWorldManifest. Trust remains the existing
`CONTROLLED_FIXTURE` classification. Real-runtime/executable promotion is rejected.
Historical Attempt 4 is not reused as native acquisition evidence.

## Accounting and opcode work

Standalone `TerrainFrameBudget` configures the existing StructuralFrameBudget
observer; it does not constitute a real-proof freeze. The collecting owner must
attach it at the secure session's frame boundary before setup. Controlled fake
clients simulate that observer independently of receipts. Collector phase changes
and receipt totals reconcile with observer totals; the collector never increments
frame counters from receipts. No reset, retry, reconnect or resume is supported.

Per sweep: 256 tiles, ceil(256/5)=52 requests, ≤26416 response bytes, ≤416 query
operations. Two sweeps: **104 requests**, **104×508=52832 response bytes**,
**104×8=832 query operations**. Ideal query traffic is four operations: application
send, response, completion PING, PONG. Up to eight counts all decoded traffic.

Native getter upper bound is separate: 24 base reads plus up to four neighboring
sets of five =44/tile, plus six/page. Thus **2×256×44+104×6=23152**. Collector
reservations record this upper bound; they are not measured native C++ CPU work.
Controlled handler instrumentation checks actual script-level getter invocations.

Lifecycle: encrypted PROTOCOL/WELCOME 2 + explicit subscription/PING/PONG 3 +
owner's graceful QUIT 1 =6. Standalone ceiling: **832+6=838 post-auth frames**.
Collector does not send setup/QUIT or clock guards. Receipt/frame reconciliation
prevents hidden traffic from disappearing. Response capacity reserves a full
508-byte page before send. Partial failure retains evidence and yields no result.

Tagged Squirrel counts opcodes and can suspend/resume at the configured threshold
(default 10000). Offline worst-width five-row controlled getter cases stay below
10000, including canonical evidence serialization. This measures Squirrel work
with native getters stubbed; internal C++ getter cost and real scheduling remain
unproven. Native bounded loops and automatic suspension do not establish an atomic
read. Real preparation must review scheduling and frame limits for its exact runtime.
Combined qualification+terrain accounting and bridge composition are deferred;
838 and the historical 9094 must not be reused as combined-proof authorization.

## Evidence and failures

GS: BRIDGE_REQUEST_RECEIVED → TILE_FACTS_READ → BRIDGE_RESPONSE_SENT →
BRIDGE_POST_RESPONSE_ALIVE after existing event-loop yield. TILE_FACTS_READ logs
canonical response_json, binding rectangle, cursor, rows and continuation. No
verified GS SHA API is assumed; Python hashes these independent bytes and compares
the canonical projection, while the receipt binds exact wire bytes. Markers use
existing GSLog/stdout conventions and add no Admin console subscription.

Python exchange: TILE_FACTS_REQUEST_SENT → TILE_FACTS_RESPONSE_RECEIVED →
TRANSPORT_RECEIPT_CREATED → TILE_FACTS_VALIDATED. Successful receipt alone is
insufficient. Evidence must be canonical, correlated, ordered, complete and live.

`TileQueryError`, within existing BridgeProtocolError, carries bounded TileFailure
codes for region/tile/coverage, unsupported facts, malformed response, correlation,
cursor/duplicate/missing/incomplete sweep, byte/accounting exhaustion, provenance,
connection replacement, month crossing, drift and bridge failures. Existing typed
transport timeout/disconnect and frame-budget failures retain their established
classes. The collector is single-use even after failure; retained partial evidence
never becomes complete coverage.

## Controlled verification and remaining real prerequisites

A public receipt regression exposed JSON decoding before the response byte gate.
The new receipt method now rejects oversized bytes before decoding; the original
513-byte reproduction passes after the two-line admission-order repair. No existing
production observation semantics or P05 behavior changed.

Tests exercise actual composed handler dispatch and event-loop liveness, exact
15.3 compiler/VM and native serializer, bounded wire domains, completeness,
repeatability, source identity, supplemental compatibility, accounting and pure
import boundaries. Existing P08/P05/observation/qualification/accounting regressions
remain required; native OpenTTD-marked tests are deselected, not counted as success.
P08 adapter, candidate generator, P05 and historical evidence remain unchanged.

A single-page native proof still requires independently reviewed package staging,
exact source/runtime/settings/region pins, stdout evidence capture, secure observer
attachment, lifecycle/deadline accounting, offline acceptance, a newly authorized
attempt and freeze. No launch-ready real coordinator or native issuer is added.
Whole-region and combined same-run qualification proofs come later. Catchment,
engines, costs, content/seed acquisition, company construction legality and trusted
post-qualification save correspondence remain outside this slice.
