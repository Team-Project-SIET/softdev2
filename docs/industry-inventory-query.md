# Bounded multi-page industry inventory (controlled implementation)

Local CONTEXT.md is the architecture authority. Real ACK, world-info, and
industry-page attempt #2 milestones remain passed; attempt #1 remains permanently
failed. Historical evidence is immutable. This slice does not prepare or execute
a real multi-page proof, create a prelaunch freeze, launch OpenTTD, connect to a
live Admin endpoint, or send a real application request.

## Interface and layering

The unchanged protocol remains `industry_page` / `industry_page_result`, protocol
1. Requests carry request_id, after_id, and limit. Responses carry compact
id/type/tile/x/y records, next_after_id, and has_more. Protocol maximum is five
records; application payload bound is 512 bytes; native GSAdmin.Send ceiling is
1450 bytes. The default inventory page size is three. No throughput tuning is added.

`IndustryInventorySession(session_id, world, page_size=3, budget=..., timeout=5)`
is a single-use Python session. Its async `collect(transport, gamescript_evidence)`
uses an existing continuous Admin transport and a caller-supplied async native
evidence reader. That reader supplies the existing `IndustryPageEvidence` object
for each transaction from retained native logs. It must not initiate extra queries.
Both query and evidence waits have finite per-page deadlines. A successful result
requires complete canonical read/send/liveness metadata for every page.

`IndustryInventoryWorld.from_welcome(world_id, runtime_identity, welcome)` retains
caller-provided world/runtime identity and actual map dimensions from the
authenticated encrypted SERVER_WELCOME. This component does not authenticate or
connect; the caller supplies that verified session context. It sends no world-info
application request. Existing world-info dimensions remain accepted by the
compatibility `collect_industries` list API.

Layering stays: transport DTO → page client/session → immutable
`IndustryInventoryObservation` → future preparation adapter → P08 domain model.
No planning/preparation/domain imports appear in query or observation modules.
The existing list collector uses the same bounded cursor walker but does not claim
native GameScript session evidence. It keeps page size five for compatibility;
its page budget is now capped at 32, with the same record/byte/operation ceilings.

## Finite budgets

| Hard default/maximum | Value | Reason |
| --- | ---: | --- |
| Accepted industries | 32 | Current P08 v1 industry profile in preparation/domain.py and its design spec |
| Pages | 32 | At minimum page size one, a stable 32-record world needs at most 32 pages |
| Cumulative response bytes | 16,384 | 32 pages × unchanged 512-byte application ceiling |
| Admin frame operations | 256 | 32 × 8; initial subscription/query normally costs 7, later pages 4, with bounded headroom for unrelated packets |

`IndustryInventoryBudget` can tighten each cap; it cannot raise these hard limits
or accept zero, negative, boolean or fractional bounds. At default page size three,
a stable 32-industry world completes in at most eleven pages. Empty inventory
requires one valid terminal page. Worlds exceeding the profile fail; no truncated
inventory is returned as complete.

Operations count outgoing and incoming Admin frames during page queries, including
initial subscription if needed, AdminPing/Pong completion barriers, and unrelated
incoming packets. These barriers are protocol operations, not extra GameScript
application requests. Authentication precedes this session and is not performed
here. The remaining frame allowance is passed into the production transport and
checked while frames are sent/decoded, not just after a response. An unrelated
packet flood fails the query. Without a query-supplied allowance, single-page,
world-info, and ping behavior retain their existing limits and semantics.

## Cursor chain and identity

First cursor is null. Every continuation uses the previous last returned ID, with
records strictly greater than after_id and globally strictly ascending. Sparse IDs
are normal: 0,1,2 → 5,8,13 → 21. The final page must have has_more=false and
next_after_id=null; a full final page is valid without an extra empty request.
An empty first terminal page yields an immutable empty record tuple and complete=true.

IDs are deterministic: `<session_id>-p001`, `-p002`, ... `-p032`. The session prefix
must fit the existing 64-byte ID constraint including its suffix; all IDs are
validated before I/O. No clocks/randomness are used. A session ID must be fresh on
the connection; transport request-ID reuse is rejected.

Repeated/regressing cursors, empty or short intermediate pages, missing
continuations, duplicate/nonascending IDs, wrong envelopes/identities, duplicate
responses, inconsistent locations and budget overflow all fail. Raw response
size, receipt digests, per-page network order, and semantic metadata are validated.
Existing map indexing semantics are reused; no new tile formula is introduced.

## Completion, failure and evidence

`IndustryInventoryObservation` is frozen, with immutable page transactions and
records, session/world/runtime identity, dimensions, count, first/last ID,
response byte total, frame operation total, and ordered page receipt/digest access.
Its constructor rejects partial/nonterminal chains, extra pages after completion,
and budget violations. complete is computed by successful validated construction;
it cannot be supplied to promote a partial observation.

Inventory canonical bytes are a compact JSON array of ascending records with
sorted id/type/tile/x/y keys. SHA-256 excludes session IDs, paths, clocks and logs.
Identical inventory records produce the same digest across different sessions.

Every page retains the existing independent local chains:

- GameScript: BRIDGE_REQUEST_RECEIVED → INDUSTRY_PAGE_READ → BRIDGE_RESPONSE_SENT
  → BRIDGE_POST_RESPONSE_ALIVE.
- Python/Admin: INDUSTRY_PAGE_REQUEST_SENT → INDUSTRY_PAGE_RESPONSE_RECEIVED
  → TRANSPORT_RECEIPT_CREATED → PAGE_VALIDATED.

Canonical null/integer/boolean fields remain mandatory. Receipt response digests
bind each retained page; no native SHA observation is invented. No total timestamp
order between the two processes is imposed.

Python session order is INVENTORY_SESSION_STARTED → PAGE_1_VALIDATED → ... →
FINAL_PAGE_VALIDATED → INVENTORY_ASSEMBLED → INVENTORY_SESSION_COMPLETED. Its frozen
evidence snapshot retains ordered request IDs/digests, response digests, requested
and continuation cursors, page/record/byte/frame totals, terminal has_more and
inventory digest. A failure ends in INVENTORY_SESSION_FAILED without a completed
inventory digest. Already validated network exchanges and receipts remain exposed
through page_exchanges even if native evidence subsequently fails.

Timeout and disconnect remain distinct transport failures. The session is spent
after any collection attempt, including cancellation or failure. There is no
automatic retry, resend, reconnect, resume or lost-ACK guess. Replacement of the
transport's session during pagination is rejected. The caller retains ownership
of the connection and runtime lifecycle.

## Consistency and claim limits

V1 is a best-effort inventory over a stable world. Controlled fixtures and a
future real proof require no gameplay mutation throughout the session. Creation
or removal during pagination can cause missing observations or changed records;
v1 guarantees no concurrent snapshot consistency. No snapshot IDs, clocks, epochs
or resume generations are introduced.

A completed observation proves one valid terminating cursor chain, assembly of
every record returned by it, and per-record semantic validation inside independently
observed SERVER_WELCOME map bounds. **Independent second-source inventory: NONE.**
No other Admin subsystem independently reports the complete industry set.
Completion relies on the adapter's has_more/cursor semantics and stable-world
assumption; it is not an independent inventory reconciliation.

GameScript is unchanged and remains a thin page adapter: native Industry-pool
enumeration and deterministic sorting are O(industry count) per request, with at
most the requested number of record reads plus validity lookahead. Full-map scans,
bulk world JSON, cargo/production/station enumeration, optimization, pathfinding,
analytics and gameplay mutations are absent. Complete assembly occurs only in
Python. This remains identity/location observation, not full P08 extraction.

## Controlled verification

57 inventory tests and the ordinary suite (1,573 passed, 38 skipped) pass, including
the controlled native Squirrel two-page sequence. Focused regressions passed
849 tests with one existing skip before final connection-identity hardening; the
final inventory and ordinary runs cover that hardening. Spec and Standards review,
Ruff, format, applicable typecheck, diff, whitespace and import audits passed.
All 339 protected historical files and CONTEXT.md remain byte-identical, and the
bridge matches successful attempt #2. Gameplay launches, live Admin connections
and real requests are zero. Results are retained in
`artifacts/runtime/openttd-15.3-industry-inventory-controlled-verification/`.
No future real proof preparation/freeze has been created. Runtime-critical Python
changes require a fresh freeze and explicit authorization in a separate task.
