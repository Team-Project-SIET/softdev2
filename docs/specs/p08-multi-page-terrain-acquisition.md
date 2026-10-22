# P08 bounded multi-page terrain acquisition plan

## Status and problem

Design only, 2026-10-10. Architecture authority is `CONTEXT.md`. This plan consumes
the [offline evidence baseline](openttd-offline-evidence-baseline.md) and the
[existing terrain design](../p08-15-3-native-terrain-road-acquisition-design.md).
It neither implements acquisition nor authorizes native execution.

The current retained-attempt verifier proves one fixed page, not a region sweep.
The repository already has a controlled two-sweep collector in
`app/simulation/openttd/terrain_collection.py`, with `TerrainBudget`,
`TerrainObservation` and `TerrainFrameBudget`. The next milestone integrates those
existing pieces with a bounded, independently verifiable production proof package.
It does not need another general collector or a replacement planning model.

## Evidence levels

| Level | Established scope |
| --- | --- |
| Actual OpenTTD 15.3 | One native process/session/request produced five terrain/road records for tiles 65–69 in region [1,1,5,1]; Python validated the page. Historical native REAL_PASS remains supported within local attestation. |
| CONTROLLED only | Repaired offline contract, 188 canonical identities, exact inventory and lineage, cleanup, endpoints and result consistency; two-sweep collector, drift/coverage/accounting failure tests and supplied-stream transport tests. |
| Planned, not established by current proof package | Multi-page attempt writer/verifier integration, immutable aggregate budgets, page-index retention, whole-attempt gates and aggregate offline replay. |
| Separate approved native proof required | Bounded region/two-sweep behavior, measured cumulative runtime accounting, real session lifetime, then any full-map or production-world claim. |

A 256-tile region is at most 1/16 of a 64x64 map. It is not full-map acquisition.
The current tile protocol restricts a region to at most 256 tiles. Full-map coverage
would need a separately designed partition/aggregation contract and authorization;
this milestone does not silently change that limit.

## Enumeration and coverage

Keep protocol 1 and page size 5. Freeze map dimensions, exact rectangle, expected
row-major tile identities, sweep count and request-ID grammar in the future reviewed
subject. For region `(x,y,w,h)`, `N=w*h`, ordinal `i` maps to
`tile=(y+i//w)*map_width+x+i%w`. Cursor is the regional ordinal, not a tile ID.

Each sweep starts at cursor 0. Nonterminal pages have five records; the last page
has `min(5,N-cursor)`. Next cursor equals cursor plus record count, or null on the
terminal page with `has_more=false`. No empty sentinel page is requested. A sweep
must contain exactly `ceil(N/5)` pages and N unique expected tiles in order.

The collector must reject missing/reordered pages, cursor discontinuity, repeated
request identity, duplicate tile identity, conflicting record, wrong rectangle/map,
and premature or late terminal status. Never merge partial pages into a complete
observation. A consistent duplicate is still a protocol violation, not a retry.

## Budgets and accounting

These are existing controlled ceilings or proposed proof requirements, not approved
runtime budgets. Future authorization must bind the actual selected scope and totals.

| Quantity | Existing controlled regional ceiling |
| --- | --- |
| Tiles | N <=256 per region |
| Pages | `P=ceil(N/5)` <=52 per sweep |
| Sweeps/requests | 2 sweeps; <=104 page requests |
| Request JSON | <=159 bytes/page; <=16,536 aggregate application bytes at 104 requests |
| Response JSON | <=508 bytes/page; <=26,416/sweep; <=52,832 total |
| Query operations | <=8/page; <=416/sweep; <=832 total |
| Post-auth frames | 2 establishment + 3 setup + <=832 query + 1 cleanup = <=838 |
| Native getters | Static bound `44*N+6*P` per sweep; <=23,152 across two sweeps |
| Capture | Existing 262,144 bytes per stream; overflow fails, not silent evidence truncation |

Request/response byte totals cover application JSON, not framing/encryption or disk
metadata. Accounting must retain actual byte lengths and every admitted frame;
authentication/encryption establishment is outside the post-auth frame counter.
Getter totals are statically bounded unless a separately validated instrumentation
contract observes them. The existing ordinary-road initialization setter is separate
from getters and must be budgeted explicitly for the whole script/session.

The single-page proof's 111-byte request, 420-byte selected response, 14-frame and
226-getter limits are not multi-page limits. The native 1450-byte GSAdmin ceiling
does not replace the tighter 508-byte application ceiling.

A hypothetical 4096-tile map with unconstrained five-tile pages would require 820
pages per sweep and 1640 requests for two sweeps. That arithmetic is not executable
under the current 256-tile region contract. Sixteen 256-tile partitions instead
require 16*52=832 pages per sweep, because each partition has its own final page.
Neither layout is approved or included in this milestone.

## Session, time and coherence

Own one process and one authenticated encrypted Admin connection for the whole
attempt. Subscribe once, keep monotonic counters and send sequential correlated
requests with completion barriers and independently retained native markers. Do not
reconnect, retry, resume or reset budgets. A new process/session is a new attempt.

`TerrainCollector` currently defaults to five seconds per query and separately five
seconds per evidence retrieval. At 104 requests, those waits alone can sum to 1040
seconds. This is not a complete attempt deadline. The future reviewed contract must
choose explicit startup/authentication, per-page, evidence, sweep, total-session and
cleanup deadlines from controlled measurements. The single-page 90-second attended
wrapper is not a multi-page lifetime allowance. Deadline expiry retains failure
and invokes bounded cleanup without publishing successful acquisition.

For the existing WPO-dependent collector, all response date brackets must be ordered
and remain within the declared qualified economy month; process, session, frame-budget
object, source and map identity must remain unchanged. A standalone terrain proof
cannot fabricate a WPO to satisfy that dependency. Choose explicitly between a
standalone regional contract and a same-run qualified integration before implementation.
The minimum native milestone is a standalone small regional proof; combined WPO
admission remains a later separately reviewed integration.

Compare both completed sweeps' normalized ordered full tile rows and dimensions,
including heights, slopes, occupancy, selected ordinary-road presence, directed
connectivity and ownership. Retain both raw exchanges and their date brackets.
Equality establishes repeatable observations, not an atomic snapshot. World changes
between or within sweeps, transient changes restored before sweep two, and changes
after observation are not excluded. Do not infer construction legality from road0=0.

## Retention and offline acceptance design

Reuse durable reviewed canonical inputs and public runtime commitments. Retain no
plaintext private keys or authentication passwords, and never copy temporary
workspaces wholesale. Keep declared external historical authority immutable.

The proposed multi-page writer needs an explicit authorized page index containing
sweep/ordinal/request identity, exact request/response and receipt artifact identities,
byte lengths and digests, cursor/coverage and accounting references. Its exact allowed
artifact paths must be derived from the trusted future operation and frozen page
plan, not a mutable manifest. Aggregate result gates must be reconciled with verified
complete coverage, equality, budgets, lifecycle, cleanup and disposal evidence.

Retain one bounded final native log. Reference each execution snapshot by exact
start/end/length/hash and request lifecycle association. Do not duplicate cumulative
logs per page. The present `terrain-execution-log-v1` verifier requires start_offset=0
and one request identity; multi-page support must explicitly adapt lifecycle parsing
and range semantics. Decide whether the existing policy still describes the new
representation precisely; introduce a version only if its actual contract changes.
Do not claim this document makes current single-page evidence reusable as a sweep.

At the maximum regional ceiling, request plus response payload storage is <=69,368
bytes, before receipts/index/metadata. Two capture streams add <=524,288 bytes.
Canonical source objects, receipts, row markers and JSON metadata are additional
storage, not covered by the payload bound. Set an explicit total retained-package
ceiling after controlled writer measurements. Verify projected marker output fits
capture limits before native authorization; reject overflow rather than omit facts.

The offline verifier must reconstruct every page from retained bytes, compare raw
facts/receipts/markers, validate ordering and totals, independently compare sweeps,
reconcile all mandatory result gates and reject unindexed artifacts. Acceptance must
work after permitted candidate/runtime/credential cleanup, from another cwd and a
fresh interpreter using retained packages plus declared immutable external authorities.

## Failure, interruption and cleanup

Any malformed response, unexpected frame, budget exhaustion, source change, world
identity/date drift, conflicting page, missing marker, timeout or session replacement
fails the attempt. Retain bounded partial evidence and explicit failure status; do
not report partial coverage as complete or mathematical infeasibility.

Cleanup must reconcile raw/normalized observations, process termination/reaping,
connection/listener/game endpoint closure, permitted residual TCP TIME_WAIT,
credential disposal and post-run integrity. Relevant LISTEN/ESTABLISHED/CLOSE_WAIT
must fail despite a successful summary. Preserve credentials/workspace evidence
only within mandatory cleanup rules; never preserve the secret to make offline
verification reproducible. A failed cleanup cannot be overridden by a result gate.

Interruption consumes no retry permission. Retain the durable claim and failure,
then require a new reviewed attempt and authorization for any future native run.

## P08/P05 boundaries

Python owns assembly and coverage/equality validation. The GameScript stays a thin
read-only handler with explicit ordinary-road selector initialization and no candidate
search or construction. Preserve `TileFact` projection and retain raw diagnostics.

A complete regional observation is not a complete `SupplementalPlanningFacts` bundle.
Settings/content/seed/calendar correspondence, costs, engines, industry catchment,
WPO/source and saved-world correspondence remain separate requirements. P08 candidate
generation consumes accepted facts only within their declared rectangle and provenance.
Insufficient coverage is explicit, never extrapolated to the rest of the world.
P05 remains a supplied-candidate optimizer; this milestone changes neither its logic
nor execution authorization. No acquisition PASS grants P05 construction or P07 evaluation.

## Implementation sequence and verification gates

| Step | Proposed work | Gate before advancing |
| --- | --- | --- |
| 1 | Select standalone region versus qualified same-run scope; freeze page plan and derive cumulative budgets | Reviewed scope, time/storage/frame/getter bounds; no native authorization |
| 2 | Reuse controlled collector; adapt production attempt writer, exact inventory and offline aggregate verifier | Full-path controlled tests for 1/5/6/255/256 tiles, coverage and drift, all cross-contract mutations |
| 3 | Establish multi-request marker/log ranges and whole-attempt gates | Append-only logging accepted; committed-byte mutations, duplicate markers, contradictory result/cleanup reject |
| 4 | Complete controlled lifecycle and independent acceptance | Candidate/runtime cleanup, fresh interpreter, no secret retention; focused/ordinary/lint/type/import/history checks |
| 5 | Independent bounded adversarial review | Every mandatory challenge conclusive; no mutable-manifest acceptance bypass |
| 6 | Separately prepare a future immutable proof package | Reviewed current source inventory, exact artifact contract, endpoint/credential identity, operation and budgets; unauthorized seal only if separately requested |
| 7 | Separately authorize one small multi-page native proof | Exact digest, attempt, destination, Model A attended allowance; no retry/reconnect/resume |
| 8 | Separately review regional two-sweep native proof | Native observations, accounting, equality and offline acceptance; no full-map or production-world claim |
| 9 | Later qualified/P08 integration | Complete independent supplemental facts and source correspondence, separate approved proof |

No implementation, sealing or execution step is performed by this plan. Required
approvals remain scope/budget review, any future contract representation change,
explicit seal preparation and exact one-attempt native authorization.
