# Same-runtime industry capability enrichment proof preparation

`CONTEXT.md` is the architecture authority. Implementation baseline HEAD is
`d7ee72f47149482841fcf45cd92b222664bfb3bd`. The proven cargo work is currently in
the worktree; this preparation creates no commit and rewrites no checkpoint.
All preparation, tests and guarded preflight use zero gameplay launches, live
Admin connections and real application requests.

## Production entry point and phases

Use the public `python -m app.simulation.openttd.proof prepare --mode industry-enrichment`
then `preflight --mode industry-enrichment`. The guarded preflight blocks subprocess
creation and socket connections and reaches READY_TO_LAUNCH through
`EndpointReservation.allocate()`. A future `run --mode industry-enrichment
--authorize-one-launch` requires separate explicit authorization against the new freeze.
There is no shell pagination, external wrapper, bulk command or private invocation.

The owned lifecycle is PREPARED → LAUNCHED → ADMIN_ACTIVE →
ENRICHMENT_SESSION_STARTED → INVENTORY_COMPLETED → CAPABILITY_PHASE_STARTED →
CAPABILITY_COMPLETED → ENRICHMENT_ASSEMBLED → ENRICHMENT_VERIFIED → COMPLETED.
FAILED is explicit. Child transaction evidence represents repeated requests.

Session ID is `openttd15-industry-enrichment-001`. Phase A collects a fresh
inventory through `industry_page` using the established child session
`openttd15-industry-inventory-001`, request IDs `-p001`, `-p002`, etc., proof page
size 2, first after_id=null and subsequent after_id=previous next_after_id.
The first valid has_more=false / next_after_id=null terminates this phase.
Generic default page size remains 3; maximum remains 5.

Only after complete inventory validation does Phase B query `industry_cargo`
exactly once per actual observed industry, in ascending ID order. Capability IDs
are `<enrichment-session>-i<five-digit actual industry ID>`, for example `-i00017`.
This existing project scheme supports sparse IDs and retains request-to-industry
mapping. It does not assume IDs 0–9, ten industries or a previous run's inventory.
The historical seed-42 64×64 world with five pages and ten industries provides
supporting expectation only. Valid empty worlds yield complete empty enrichment.

## Finite budgets and one connection

| Bound | Inventory phase | Capability phase | Combined ceiling |
| --- | ---: | ---: | ---: |
| Application requests | 32 pages | 32 industries/requests | 64 |
| Industry records | 32 | Exactly source inventory count | 32 |
| Response bytes | 16,384 | 16,384 | 32,768 |
| Admin query frames | 256 | 256 | 512 |

The combined ceiling sums the existing phase ceilings rather than weakening them.
With full two-record pages, 32 stable industries normally require 16 inventory
requests plus 32 capability requests (48). We retain the existing 32-page safety
semantics; 64 is a conservative authorization ceiling, never a target. Startup
Admin frames precede the query-session accounting. Each query checks its remaining
operation budget before sending; accepted cumulative records/bytes/frames are
validated after every response. Exceeding any phase or combined bound fails.

Both phases use one continuous secure Admin connection and one owned process.
Connection replacement, disconnect, timeout or ambiguity fails the whole session.
Retries, reconnects and resume are zero. Stop immediately after complete enrichment.
The stable-world profile permits no gameplay mutation. Concurrent external
industry creation/removal could break snapshot consistency; v1 has no epoch or
version clock and makes no concurrent-snapshot guarantee.

## Models and deterministic digests

The immutable `IndustryInventoryObservation` remains unchanged. Its digest hashes
ascending canonical id/type/tile/x/y and remains independent of page boundaries.
`IndustryCapabilityObservation` references that exact inventory and requires
exactly one validated result for every source ID, with no extra, missing or duplicate
industry. Empty produces/accepts and overlap across sets are valid; each set must
be unique, ascending, IDs 0–63 with at most 16 entries.

`IndustryEnrichmentObservation` binds the ordered capability transactions, source
inventory, runtime/world context, bridge and combined budgets. It retains source
inventory digest equal to inventory.inventory_digest, the separate capability
digest, and an enriched digest over canonical inventory_digest/capability_digest.
Capability digest hashes ascending industry_id and sorted produces/accepts, unchanged
from the controlled capability contract. Request IDs, request order, page boundaries,
timestamps, paths and logs do not affect logical digests. Source inventory is never
mutated and no transport/world observation module imports P08 planning contracts.

## Evidence and failure semantics

Every page retains the native local chain BRIDGE_REQUEST_RECEIVED →
INDUSTRY_PAGE_READ → BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE and Python
INDUSTRY_PAGE_REQUEST_SENT → INDUSTRY_PAGE_RESPONSE_RECEIVED →
TRANSPORT_RECEIPT_CREATED → PAGE_VALIDATED. Every capability retains the same
native chain with INDUSTRY_CARGO_READ and Python INDUSTRY_CARGO_REQUEST_SENT →
INDUSTRY_CARGO_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → CAPABILITY_VALIDATED.
Receipts bind raw request/response digests before semantic success; a receipt is
not verification. Canonical null/decimal/boolean markers remain mandatory.

The Python session chain is ENRICHMENT_SESSION_STARTED → INVENTORY_SESSION_STARTED
→ pages validated → INVENTORY_COMPLETED → CAPABILITY_PHASE_STARTED → capabilities
validated → CAPABILITY_OBSERVATION_ASSEMBLED → ENRICHMENT_VERIFIED →
ENRICHMENT_SESSION_COMPLETED. Cross-phase provenance compares exact ordered ID sets,
ledger bytes/receipts and source inventory digest. Native chains and Python chains
are validated independently; no cross-process timestamp order is imposed.

Prelaunch failure retains evidence with zero activity and stops. Post-launch failure
retains raw completed and partial transactions, accurate inventory completeness and
incomplete enrichment, then closes Admin, shuts down/reaps the owned process,
checks endpoints and removes credentials. No resend, reconnect, relaunch or source
repair is permitted. Late evidence/cleanup errors reconcile all final summaries
as failed. Any later real execution needs fresh explicit authorization.

## Native semantics, cost and claim limits

The GameScript package is byte-identical to the proven single-industry cargo bridge.
It knows individual queries, not sessions. Each page constructs/enumerates
GSIndustryList and sorts/traverses it; total work includes repeated list enumeration
and sorting across pages, not just O(page count) or O(records). Each cargo request
validates one industry, obtains and sorts native producing/accepting lists, reads
at most 16 IDs per list and sends one bounded result. There is no map scan, bulk
JSON, optimization, pathfinding, analytics or heavy world modeling in Squirrel.

Application bound remains 512 bytes; native GSAdmin.Send ceiling remains 1450.
No capability response aggregates industries. Structural accepting-list capability
can include cargoes temporarily not currently accepted. Transient acceptance,
last-month production/transported values, stockpile, quantities and cargo metadata
names/labels/classes are excluded. A separate cargo_catalog may normalize metadata.

A future PASS establishes complete traversal of the GameScript-provided cursor
chain, Python assembly and exactly-once native capability querying for every
observed industry in that same live runtime. SERVER_WELCOME supplies independent
map dimensions for coordinate bounds only.

- Independent inventory source = NONE.
- Independent capability source = NONE.
- Production history = NOT INCLUDED.
- P08 completion = NO.

## Freeze and credentials

The new freeze is `artifacts/runtime/openttd-15.3-industry-capability-enrichment-real-prelaunch/`.
It freezes runtime/OpenGFX/configuration, Admin/secure transport, unchanged bridge,
protocols, DTOs/validators, sessions/digests, CLI/lifecycle/evidence and combined
contract. PRELAUNCH records count/digests/HEAD; source-freeze is sorted deterministically.
A fresh private credential is mode 0600, kept only in the owned isolated runtime
workspace and excluded from public evidence. Historical public hashes omit private
material; historical files and CONTEXT.md remain byte-identical.

Future evidence destination is
`artifacts/runtime/openttd-15.3-industry-capability-enrichment-real-attempt1/`.
Preparation leaves it absent. Actual evidence will retain per-request payloads,
receipts, native/network chains, inventories, capability/enriched observations and
digests, authentication/WELCOME/lifecycle, raw logs and artifact manifest. Raw
payloads are not duplicated in native metadata logs.
