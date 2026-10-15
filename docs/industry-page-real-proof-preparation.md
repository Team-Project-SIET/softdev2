# One OpenTTD 15.3 industry-page proof: preparation contract

Local `CONTEXT.md` remains the architecture authority and is unchanged. The real
secure ACK and independently verified world-info milestones remain passed.
Industry-page controlled implementation is passed. This task prepares a future
real proof; it does not execute one. No gameplay launch, live Admin connection,
real application request, commit or push is authorized here.

## Authoritative public lifecycle

The existing production CLI is extended with `--mode industry-page`:

```text
.venv/bin/python -m app.simulation.openttd.proof prepare --mode industry-page
.venv/bin/python -m app.simulation.openttd.proof preflight --mode industry-page
```

The second command installs an audit guard prohibiting `subprocess.Popen` and
`socket.connect`, loads the production preparation, verifies all source/inputs,
loads the typed page validator and evidence contract, calls
`EndpointReservation.allocate(game_port, admin_port)`, checks the native backend's
identity/credential/ownership gates, then returns `READY_TO_LAUNCH` with zero
activity. It does not call `launch()`. No external gate scripts or ad-hoc wrappers
are used. Preparation and preflight are public commands; tests inject only fake
assets/backends/streams at the existing seams.

The future run command is intentionally **not invoked**:

```text
.venv/bin/python -m app.simulation.openttd.proof run --mode industry-page --authorize-one-launch
```

That flag does not supply authorization in this preparation task. A separate
explicit user authorization is required for the future run. Its native backend
inherits verified binary, OpenGFX, isolated runtime, secure authentication,
subscription barriers, process ownership, log health, shutdown and reap behavior.
A distinct industry runner keeps the old ACK and world-info lifecycle behavior
and their retained evidence intact.

Industry lifecycle validation states:

`PREPARED → LAUNCHED → ADMIN_ACTIVE → INDUSTRY_PAGE_REQUEST_SENT → INDUSTRY_PAGE_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → PAGE_VALIDATED → POST_RESPONSE_LIVENESS_VERIFIED → COMPLETED`

Failures terminate in `FAILED`. Receipt creation and semantic validation remain
separate states and separate artifacts. A semantically invalid page may retain a
valid transport receipt, but never passes the proof.

## Frozen request and payload

Exact canonical production bytes (no trailing newline):

```json
{"after_id":null,"limit":3,"protocol":1,"request_id":"openttd15-industry-page-001","type":"industry_page"}
```

Size: **106 bytes**. SHA-256:
`0050e460326e397a32ada31d3608c3aa4a1a8826bff361593e8d17e322a2dab8`.

The protocol maximum remains five records and the application bound remains
512 bytes. Only this proof's request uses three. The conservative three-record
bound with this fixed 25-byte ID is **339 bytes**, leaving **173 bytes** below the
application bound and **1111 bytes** below the native 1450-byte ceiling. The shared
five-record bound remains 502. Record schema, cursor and canonical serialization
remain the [controlled industry-page protocol](industry-page-query.md).

The future proof sends exactly one industry query, after_id null, limit three.
It does not walk pages or assemble the full inventory. No ping or world-info
application request is allowed; Admin subscription/ordering packets and encrypted
SERVER_WELCOME are connection/protocol operations, not additional application
queries. Response records are never hard-coded into the production contract.

## Source authority and GameScript cost

`source-authority.json` copies the exact 15.3 source manifest from
`tests/reference/industry_page_bindings_15_3/manifest.json`. These API/engine/generator
sources are also included individually in the source/input freeze. The official
15.3 source was rechecked byte-for-byte against the retained manifest.

- `GSIndustryList`: generated from `ScriptIndustryList`, backed by native
  `ScriptList::FillList<Industry>` and the Industry pool.
- `GSList.Sort(GSList.SORT_BY_ITEM, GSList.SORT_ASCENDING)`: explicit native
  item-ascending iteration, independent of default order.
- `GSIndustry.IsValidIndustry`, `GetLocation`, `GetIndustryType`: read APIs only.
- `GSMap.IsValidTile`, `GetTileX`, `GetTileY`, `GetMapSizeX/Y`: validity and location.
- API CMake selects `game;GS`; `SquirrelExport.cmake` replaces `Script` with `GS`
  and registers the GameScript APIs. Source inspection verifies names; controlled
  VM tests are not a native-binding proof.

No map-tile scan. Native list construction and cursor-prefix traversal remain
O(industry count). At most three returned records receive location/type/coordinate
reads; has-more uses validity-only lookahead. Removed IDs are skipped as frozen in
v1. No cargo/production/station enumeration, terrain analysis or optimization.
The scalar first/last-ID logging extension adds no world model to GameScript.

## Validation and exact success policy

Strict production parsing validates protocol 1, exact request ID, result type,
status ok, exact fields, unique/ascending industry IDs, domains, cursor and
has-more semantics, count ≤3, 512-byte application bound and strict native bound.
The already verified row-major formula `tile = y * width + x` is reused.

Actual map width/height come from authenticated encrypted SERVER_WELCOME in the
same session. Bounds and tile consistency use those dimensions; no world-info
query is sent. `IndustryPageVerification` is immutable and carries request and
response digests, cursor/limit/count, IDs, next cursor/has-more, ordering/cursor/
coordinate/bounds/payload/count validity flags, map dimensions and runtime/bridge
identities. It does not represent a world snapshot.

Protocol-valid empty final pages stay allowed. Frozen first-proof success requires
**at least one and at most three valid records**, both complete correlated chains,
exactly one launch/connection/query, zero retries/mutations, clean exit/reap,
closed endpoints, credential removal and source/historical integrity. Empty
results retain transport and protocol evidence and classify as
`EMPTY_PAGE_RECORD_PROOF_NOT_ESTABLISHED`; the stronger milestone does not pass.
No industry is created merely to meet that policy. The fixed temperate 64×64,
seed-42, year-1950 default-content world is expected to generate industries, but
that expectation is not claimed as runtime evidence before launch.

## Evidence and claims

Native GameScript order:

`BRIDGE_STARTED → BRIDGE_REQUEST_RECEIVED → INDUSTRY_PAGE_READ → BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE`

The read marker retains request ID, after-ID, requested limit, count, first/last
IDs or null, next cursor and has-more. No duplicate payload dump is added.
GameScript has no verified native SHA-256 API in this adapter. Python attaches the
retained raw response digest to the correlated immutable evidence object, with
`response_digest_source` explicitly identifying **Python**, not a native hash
observation. This digest is available in the read-evidence contract without
inventing a second native source.

Python/Admin order:

`INDUSTRY_PAGE_REQUEST_SENT → INDUSTRY_PAGE_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → PAGE_VALIDATED`

Each chain is ordered locally. Exact protocol/request/result/status, first/last
metadata and response digest bind the transaction. No cross-process relation
between PAGE_VALIDATED and post-response-alive is asserted. Missing/duplicate/
malformed/startup/read/send/liveness or unrelated transaction evidence fails.
Ping ACKs and world-info results cannot satisfy the industry query. The recorded
session permits one exact canonical application request and rejects duplicates
before resend; duplicate responses also fail, including across receive calls.

The future proof establishes real Industry-pool enumeration, completed secure
transport, returned-record invariants, and locations inside independently
observed runtime map bounds. **No independent second-source industry inventory
exists.** SERVER_WELCOME independently exposes map dimensions, not industry
existence/type/location. World-info's stronger independent dimension-comparison
claim is preserved.

## Runtime, ownership and failure policy

Pinned OpenTTD 15.3 and verified OpenGFX 8.0; isolated HOME/XDG/config/data;
loopback-only dedicated game/Admin endpoints; fresh X25519_AuthorizedKey with
0600 private file, insecure login disabled, blank password, isolated bridge.
Source/input and bridge digests are checked before a future launch claim.

For the industry backend, readiness polling reads an owned child socket inode
and loopback LISTEN address in `/proc`, never opening an Admin readiness
connection. Once ready, exactly one secure connect/authentication is attempted.
No auth/connection retry, application resend or relaunch is permitted. Native
process cleanup is inherited, with independently re-reserved endpoints after
shutdown to prove closure.

Before launch: retain failure evidence, zero gameplay launches/connections/
queries, stop. After launch: retain raw/partial response, receipt and internal
logs before cleanup, stop/reap, close endpoints and remove credentials. A valid
receipt with failed semantic validation is retained as partial evidence. No source
repair during the attempt. Any second real proof needs new explicit authorization.
The attempt directory is atomically claimed and never reused or overwritten.

## New preparation and future destination

New preparation: `artifacts/runtime/openttd-15.3-industry-page-real-prelaunch/`.
Future result path: `artifacts/runtime/openttd-15.3-industry-page-real-attempt1/`.
The future result directory must remain absent during preparation, with no fake
runtime evidence. Metadata declares the path and expected files without creating
it. The new prelaunch directory alone contains prepared artifacts and an isolated
workspace; all previous evidence directories and CONTEXT.md remain byte-identical.

The sorted SHA-256 source/input manifest freezes runtime modules, secure Admin,
protocol/transport/DTO/query/evidence/validator/runner/CLI, bridge, source authority,
Python executable/crypto library, binary, graphics and configuration. Private-key
bytes/hash are excluded from public evidence and the source manifest. Only public
key identity and the restricted private-file path are used for preflight.

Future artifacts include final report, runtime/graphics/bridge identities,
source freeze/authority, sanitized config, authentication/protocol/welcome,
industry request/response, transport receipt, industry verification, both evidence
channels, semantic correlation, supporting logs, process lifecycle and manifest.
No full inventory, P08 mapping, optimization, production/cargo data or gameplay
mutation is part of this proof.

## Preparation verification

The public prepare and guarded preflight commands completed successfully. The
freeze contains 99 source/input hashes, all revalidated. Bridge package SHA-256:
`18cdded3f3b8ed7438ea06ce97b80578d72c1b4f7c5eb12755f75372e23ae50a`.
The fresh private credential is mode 0600 and excluded from public evidence.
All 234 protected historical files, including CONTEXT.md, remain byte-identical;
the future attempt directory is absent.

Preparation tests: 48 passed. Existing industry tests: 63 passed. Focused
regressions: 459 passed. Ordinary suite: 1,487 passed, 38 skipped. Ruff, format,
applicable type checking, diff/whitespace and query/proof import-boundary audits
passed. Existing planning execution integration imports remain outside the query
DTO/transport boundary. No gameplay launch, live Admin connection or real
application request occurred. No commit or push was performed.
