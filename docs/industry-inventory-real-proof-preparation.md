# OpenTTD 15.3 bounded multi-page industry inventory proof preparation

CONTEXT.md is the architecture authority. This preparation performs no OpenTTD
launch, live Admin connection, or real request. Historical ACK/world-info and
single-page Attempt #2 remain passed; Attempt #1 remains permanently failed.
Only fresh explicit authorization against this new freeze can execute the proof.

## Production entry point

Use the public production CLI only:

```sh
.venv/bin/python -m app.simulation.openttd.proof prepare --mode industry-inventory
.venv/bin/python -m app.simulation.openttd.proof preflight --mode industry-inventory
```

Preflight loads the frozen source/input and artifact manifests, pinned binary and
OpenGFX identity, unchanged bridge, strict evidence contract, canonical first
request and generation algorithm, restricted fresh key, isolated loopback config,
and historical integrity. EndpointReservation.allocate() reserves distinct TCP
and game UDP endpoints, then releases them. The audited dry run blocks subprocess
creation and socket connections and reaches READY_TO_LAUNCH. The future attempt
path is reserved in metadata; it remains absent until authorized execution claims
it atomically. No external wrapper or shell pagination is used.

## Frozen session and request generation

Session: `openttd15-industry-inventory-001`. Proof page size is **2**, while generic
inventory default remains **3** and protocol maximum remains **5**. Page IDs are
`openttd15-industry-inventory-001-p001`, `-p002`, ... `-p032`, produced by
inventory_request_id and canonical IndustryPageRequest.to_bytes(). Only the first
request is frozen as bytes; later requests are generated from actual prior cursors.
First after_id is null; each continuation is exactly previous next_after_id.
No clocks, random request identities, offsets or guessed industry IDs are used.

Future authorization ceilings: one gameplay launch, one continuous encrypted
Admin connection, at most 32 industry_page application requests, zero automatic
or manual retries, zero reconnects and zero other command types. The ceiling is
not a target: stop at the first valid has_more=false response. Admin subscription
and Ping/Pong barriers are protocol frames, not GameScript ping requests.

Frozen budgets stay 32 pages, 32 records, 16,384 response bytes and 256 Admin
frames. With page size two, 32 stable records need at most 16 pages, at most 8,192
response bytes at the per-message bound, and normally 67 subscription/query/barrier
frames. Every incoming/outgoing frame is also counted by the recorder, including
unrelated packets. No limits are increased. Each GSAdmin.Send remains independently
bounded by application 512 bytes and native 1450 bytes.

## World support and success policy

Reuse successful single-page Attempt #2's world-generation configuration: seed42,
64×64 temperate map, year1950, generator1, zero competitors, OpenGFX8.0. Preparation
compares the generation configuration and freezes historical response/config/proof
hashes as supporting inputs. IDs0,1,2 demonstrate that this configured world is
expected to force continuation with limit2. No preparation launch is used to count
industries, and future actual multi-page success remains mandatory.

Success requires at least two validated pages, first has_more=true, advancing
cursor continuation, strictly ascending unique global IDs, valid coordinates,
all bounds, final has_more=false and next_after_id=null, complete Python assembly,
canonical digest, native liveness per page, one connection and clean owned cleanup.
A valid one-page inventory fails with MULTI-PAGE CONDITION NOT ESTABLISHED; retain
its records/receipt and cursor_chain_complete evidence, without changing page size,
resending or relaunching.

All page/cross-page invariants use the controlled client unchanged. Tile indexing
uses its already verified OpenTTD semantics. Encrypted SERVER_WELCOME supplies
actual runtime dimensions for bounds; no world_info application request is sent.
Connection drop/replacement, timeout or ambiguous response immediately fails the
single-use session. There is no reconnect/resume or lost-ACK guess.

## Lifecycle and evidence

Typed lifecycle: PREPARED → LAUNCHED → ADMIN_ACTIVE → INVENTORY_SESSION_STARTED →
FINAL_PAGE_VALIDATED → INVENTORY_ASSEMBLED → INVENTORY_VERIFIED → COMPLETED, or
FAILED. Ordered structured page_cycles represent repeated PAGE_REQUEST_SENT →
PAGE_RESPONSE_RECEIVED → PAGE_RECEIPT_CREATED → PAGE_VALIDATED transactions; no
static state per page is manufactured.

Each page retains independently ordered chains:

- GameScript: BRIDGE_REQUEST_RECEIVED → INDUSTRY_PAGE_READ → BRIDGE_RESPONSE_SENT
  → BRIDGE_POST_RESPONSE_ALIVE, preceded by one BRIDGE_STARTED for the process.
- Python/Admin: INDUSTRY_PAGE_REQUEST_SENT → INDUSTRY_PAGE_RESPONSE_RECEIVED →
  TRANSPORT_RECEIPT_CREATED → PAGE_VALIDATED.

Canonical null/integer/boolean metadata remains strict. Correlate request identity,
protocol/types/status, after_id, limit, returned count, first/last IDs, continuation
and response digest where available. Native response SHA is not invented: Python
retained raw response digest binds native metadata. No cross-process timestamp
ordering is imposed. GameScript remains unaware of the Python session.

Python session evidence retains STARTED → PAGE_1_VALIDATED → ... → FINAL_PAGE_VALIDATED
→ INVENTORY_ASSEMBLED → INVENTORY_VERIFIED → INVENTORY_SESSION_COMPLETED, ordered
IDs/request and response digests/cursors, receipts, totals and inventory digest.
An immutable IndustryInventoryObservation represents the validated cursor chain.
Public failed-proof observations use complete=false, with cursor_chain_complete
separately identifying a traversal that finished before a later proof failure.
Transport/record semantics and full native page correlation have separate flags;
a receipt alone never establishes page_valid=true. Partial records remain retained.

Canonical inventory digest is unchanged: compact sorted-key JSON array of ascending
id/type/tile/x/y records. It excludes page boundaries, request IDs, logs, times,
addresses and paths. Different page splits digest identically. Records remain
world-observation DTOs; no PreparedWorldManifest/P08 import or mapping is introduced.

Future evidence includes identities/config/freeze/auth/protocol/WELCOME, session,
JSONL page requests/raw responses/receipts/verifications/native evidence, complete
or incomplete observation, canonical records/digest, raw supporting log, stdout/
stderr, process lifecycle, post-run source integrity, report and artifact manifest.
Raw page responses are retained once; metadata files refer to their digests.

## Failure, credentials and claim limits

Prelaunch failure retains zero activity, stops and permanently gates retry.
Post-launch failure retains evidence/partial records with complete=false, performs
bounded graceful shutdown and escalation if necessary, reaps the owned process,
checks endpoints, removes private credentials and verifies all frozen inputs and
historical files. No source repair occurs during an attempt. Later real execution
requires fresh explicit authorization. Fresh X25519 private bytes are stored only
in isolated .admin-secret mode0600, excluded from all public manifests/evidence;
public authorized-key identity is retained. Old proof secrets are never reused.

This is best-effort inventory over a stable world; concurrent industry creation or
removal has no consistent snapshot guarantee. No version clocks or epochs exist.
**Independent second-source industry inventory: NONE.** SERVER_WELCOME confirms
map bounds only, not industry IDs/types/count/existence. A future PASS establishes
real complete traversal of the GS cursor chain and assembly of every returned
record, not independent inventory equivalence, cargo/production verification or
P08 completion.

GameScript is byte-identical to successful Attempt #2. Exact 15.3 APIs remain
GSIndustryList (native Industry pool), GSList.Sort(SORT_BY_ITEM,SORT_ASCENDING),
GSIndustry.IsValidIndustry/GetLocation/GetIndustryType and GSMap.GetTileX/GetTileY.
Each page repeats list enumeration/sorting/traversal, so total work across pages
can exceed one full list walk; it is not O(page count) or O(records) alone. This
is acceptable under 32 records. No full-map scan, bulk industry_inventory_result,
cargo/production/station query, optimization, pathfinding, analytics or gameplay
mutation is added. AdminPort remains the compact query/control plane.

## Frozen preparation and controlled results

Freeze: `artifacts/runtime/openttd-15.3-industry-inventory-real-prelaunch/`, with 112 exact source/input hashes. Proof configuration SHA-256:
`8e0fbbb73c87530574d8de827d73a43d3ffb49b25a9457588d5014928ef12f1f`. First canonical request is 116 bytes, SHA-256
`fa20f866238a3368e73381c1e3073de7933eb7b4c862ae174545682cd0eb1361`. Bridge package remains
`2151a6a4b9669c3e9a0fef595c758f6f8aeae20a21a26c6f808ab23fcefdccfc`.
The two-record proof response bound using DTO field maxima is 288 bytes, leaving
224 application bytes and 1,162 native bytes of headroom.

Public guarded preflight reached READY_TO_LAUNCH with process creation blocked.
Preparation: 50 tests; inventory: 57; industry page: 63. Focused suite: 901 passed,
1 skipped. Ordinary suite: 1,623 passed, 38 skipped. Both reviews completed; failure
retention classifications were corrected and tested. Ruff, format, applicable
typecheck, diff, whitespace and import audits passed. All 348 protected historical
files and CONTEXT.md are unchanged. Launches/connections/real requests: 0/0/0.
Controlled verification is retained in `artifacts/runtime/openttd-15.3-industry-inventory-preparation-controlled-verification/`.
Fresh explicit authorization is required for future real execution.
