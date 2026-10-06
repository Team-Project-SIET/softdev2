# Industry cargo capability (controlled OpenTTD 15.3)

Implementation baseline HEAD: `d 7ee 72f 47149482841fcf 45cd 92b 222664bfb 3bd`.
CONTEXT.md remains the architecture authority and is unchanged. This task performs
zero OpenTTD gameplay launches, live Admin connections or real application requests.
Historical proof evidence is immutable; no new real-proof preparation is created.

## Semantics and exact API authority

This command reads structural capability: cargo types an industry can produce and
cargo types configured as accepted inputs. It does not read current production,
last-month quantities, transported cargo, stockpiles or transient acceptance.

Exact 15.3 [script_cargolist.hpp](https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/script/api/script_cargolist.hpp)
marks both list classes `@api ai game`. The verified native export generator replaces
`Script` with `GS` while retaining underscores. Exact GameScript names used:

- `GSCargoList_IndustryProducing(industry_id)`
- `GSCargoList_IndustryAccepting(industry_id)`
- `GSList.Sort(GSList.SORT_BY_ITEM, GSList.SORT_ASCENDING)`
- `GSIndustry.IsValidIndustry(industry_id)`
- `GSCargo.IsValidCargo(cargo_id)`

The accepting-list documentation explicitly includes cargoes temporarily not
accepted by that industry; `GSIndustry.IsCargoAccepted` represents a different,
transient state and is not called. The list constructors enumerate the industry's
native produced/accepted slots and filter invalid cargo types. They do not inspect
production history. Source authority copies and SHA-256 manifest are retained in
`tests/reference/industry_cargo_15_3/`, alongside existing verified list/industry
headers and export convention sources. CMake is unavailable in this environment;
binding names are verified directly against the exact generator rule and declarations,
not inferred from historical AI names or a fabricated generated output.

## Protocol and rejection

Request: protocol 1, type=`industry_cargo`, request_id, industry_id.
Response: protocol 1, type=`industry_cargo_result`, request_id, status=`ok`, industry_id,
produces=[cargo IDs], accepts=[cargo IDs]. No additional fields or metadata strings.
Existing canonical compact sorted-key JSON serialization is used by Python.

Industry IDs must be integers 0..63999 and valid in the native Industry pool before
list construction. Invalid/malformed requests follow the existing adapter rejection
policy: no response and no success/liveness transaction; callers fail by deadline.
An invalid industry is never represented by fabricated empty capability lists.
Valid empty sets, sparse IDs and overlap between input/output sets are supported.
Each set must be strictly ascending and unique; duplicates are rejected, not hidden.

## Cargo bounds and payload proof

Exact [cargo_type.h](https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/cargo_type.h)
defines NUM_CARGO=64: valid cargo IDs 0..63. This is the global cargo vocabulary,
not the number of cargo slots on one industry. Exact
[industry_type.h](https://raw.githubusercontent.com/OpenTTD/OpenTTD/15.3/src/industry_type.h)
defines INDUSTRY_NUM_INPUTS=16 and INDUSTRY_NUM_OUTPUTS=16. Industry construction and
cargo-type callbacks in industry_cmd.cpp use these bounds, including NewGRF industries.
The handler defensively rejects larger lists rather than truncating them.

A maximum industry ID63999, maximum 64-byte unescaped ASCII request ID, and two
16-item lists of two-digit IDs 48..63 produce **280 bytes** of canonical JSON.
The fixed envelope with empty lists is 186 bytes; each 16-ID list adds 47 bytes.
The application maximum remains 512 bytes (232-byte headroom); GSAdmin.Send's native
ceiling remains 1450 bytes (1170-byte headroom). Neither ceiling changes. Native
response field order does not change this length; only bounded ASCII scalars occur.
No industry cargo names/labels/classes/payment/town strings are duplicated.

## Python boundary and enrichment

Immutable DTOs: IndustryCargoRequest, IndustryCargoCapability, IndustryCargoResponse,
IndustryCargoReceipt and IndustryCargoExchange. Lists are immutable ordered tuples.
The existing secure transport provides one bounded query and duplicate-response
completion barrier; it never connects or retries for capability collection.
Receipt correlation binds request ID, industry ID and both payload SHA-256 values.

IndustryInventoryObservation → IndustryCapabilitySession → normalized immutable
IndustryCapabilityObservation. Every inventory record requires exactly one validated
capability transaction. Missing, extra or duplicate industry results cannot construct
complete=true. The inventory stays immutable and its original digest is preserved.
No cargo data enters transport-global mutable state; no P08 domain import or mapping.
Future layering remains cargo_catalog + industry_cargo + industry inventory → Python
world observation → future preparation adapter. Cargo metadata and production history
are separate later slices.

Deterministic request IDs are `<session_id>-i<five-digit actual industry ID>`; sparse
industry IDs are normal. All IDs are validated before I/O. No wall-clock/random IDs.
Hard/default caps: 32 industries, 32 requests, 16384 cumulative response bytes, 256 query
Admin frames. Tighter caps are supported; caps cannot be raised. Subscription and
completion Ping/Pong barriers and unrelated incoming frames count. Authentication
belongs to the already-established connection, outside this query session. Normal
32-query cost is 131 frames; the ceiling allows bounded unrelated traffic.

The session is single-use, with automatic retries 0 and reconnect/resume prohibited.
Timeout, disconnect, connection replacement, budget exhaustion or ambiguous response
fails the session without resend. Existing receipts are retained in failed session
evidence; no partial result is returned as complete. An empty inventory completes
without any capability request.

The canonical capability digest is SHA-256 of compact sorted-key JSON records:
industry_id, sorted produces, sorted accepts, in ascending industry ID order. It
excludes request order/IDs, packet boundaries, timestamps, logs and temporary paths.
It is separate from the previously proven inventory digest.

## Evidence, cost and limitations

Per request, independent local chains are:

- GameScript: BRIDGE_REQUEST_RECEIVED → INDUSTRY_CARGO_READ → BRIDGE_RESPONSE_SENT
  → BRIDGE_POST_RESPONSE_ALIVE.
- Python: INDUSTRY_CARGO_REQUEST_SENT → INDUSTRY_CARGO_RESPONSE_RECEIVED →
  TRANSPORT_RECEIPT_CREATED → CAPABILITY_VALIDATED.

Native read evidence retains industry ID, produced/accepted counts and optional
first/last IDs. Canonical helpers emit decimal integers and literal null; no object
or pointer/debug rendering is accepted. Python response digest binds the retained
payload; no native SHA source is invented. Session evidence is STARTED → validated
capabilities → CAPABILITY_OBSERVATION_ASSEMBLED → COMPLETED, or FAILED. No global
cross-process timestamp order is imposed.

One query validates one industry, reads/sorts at most 16 produced and 16 accepted
slots, serializes IDs and sends one response. No industry-list enumeration, full-map
scan, bulk dump, cargo metadata, optimization, pathfinding or analytics occurs.
No GSCompanyMode, construction, vehicle/order/terraform/finance/industry mutation
or gameplay RCON is introduced.

The native Squirrel seam executes actual production handler/Start logic against
controlled fake slot sources implementing verified constructors/list operations.
It proves handler sorting, canonical evidence and liveness in a native VM; it does
not execute OpenTTD's native Cargo/Industry pool bindings. Those real-engine facts
are source-verified; actual real capability enumeration remains unproven here.

Stable-world consistency is assumed across inventory and capability collection.
Industry creation/removal/change between queries can invalidate completeness;
no snapshot epochs or concurrent consistency guarantee exist.
**Independent second-source capability: NONE. Production-history claim: NOT INCLUDED.**

The bridge now supports cargo capability and has changed from the proven bridge.
Old real proofs remain historical passes; their old source freezes do not authorize
a future execution of changed source. Old proof-contract tests stage a byte-identical
checkpoint bridge fixture, preserving their strict pinned digest. Historical reports
and freezes remain untouched. Future cargo real-proof preparation requires a separate
new freeze and explicit authorization.
