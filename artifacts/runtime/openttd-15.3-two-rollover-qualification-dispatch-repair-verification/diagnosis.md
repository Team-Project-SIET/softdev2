# Qualification Attempt 1: dispatch failure, not aged deadlines

Attempt 1 is immutable POST-LAUNCH FAILED history. Its revision-1 freeze is consumed.
Checkpoint: `cc7f7479e3fbfa8c036901ba041dee1b97dc6b42`.
No native retry is part of this controlled repair.

## Evidence and timeline

The owned native log starts at 08:24:43 and ends at 08:25:51 local time. These
are log timestamps, not a reconstructed monotonic timeline. Python events and
native frames provide partial-order authority; absent timestamps are not invented.

Secure establishment and subscription precede the baseline clock. Transactions
1–59 report January 1950; transaction 60 reports February 1, date 712254.
Transaction 61 is the M1 pre-anchor guard. Every clock transaction has a validated
receipt, native read, response and post-response liveness chain. Baseline date is
712223 (January 1). The overall 300-second bound was not exhausted.

After the guard, Python enters ANCHOR_STRUCTURAL, constructs a new
StructuralWorldSession, and sends `openttd15-qualification-001-anchor-inv-p001`.
The retained last transaction says delivery SENT and INDUSTRY_PAGE_REQUEST_SENT.
The native shared counter admits one outbound ADMIN_GAMESCRIPT frame. No inbound
application response, receipt or matching GS request/read/response marker exists.
Classification is **B: sent, no GS receive evidence**. This is not evidence that
the encrypted send never happened. GS receive markers occur inside the handler,
so their absence can also mean failure before dispatch reaches that handler.

The resulting timeout is reported as `TransportTimeout: structural-world phase
deadline expired`, then cleanup, post-run integrity and FAILED. Cleanup passed.
There was no lifetime query, second rollover, final collection or production query.

## Proven root cause

The adapter introduced `base.Handle(request)`. Exact tagged OpenTTD 15.3's
modified Squirrel lexer has `parent`/TK_PARENT and has no `base` keyword. Its
compiler emits GETPARENT for TK_PARENT. Consequently `base` is an ordinary,
undefined identifier. The installed `squirrel-lang` test interpreter recognizes
modern `base`, masking the incompatibility.

A standalone interpreter compiled from unmodified tagged 15.3 Squirrel sources
reproduces: 61 successful clock reads followed by the exact recorded industry_page
payload throws **the index 'base' does not exist**. The actual composed bridge,
controlled native stubs and recorded payload reproduce this too. The event-loop
catch suppresses that exception and continues; it never reaches the raw handler's
BRIDGE_REQUEST_RECEIVED marker. Python waits for a response that was not sent.
The generic structural error is a translation of this individual response timeout.

Changing only delegation to `RawObservationBridge.Handle.call(this, request)`
passes both the exact tagged interpreter and the installed controlled interpreter.
The explicit call preserves the receiver and works across the two language
versions. No production/clock/lifetime DTO, payload or native metric API changes.
The raw proven bridge package is unchanged. The compatibility defect is specific
to the qualification composition; its fix covers every delegated raw command.

Authority: [15.3 lexer](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/3rdparty/squirrel/squirrel/sqlexer.cpp),
[15.3 compiler](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/3rdparty/squirrel/squirrel/sqcompiler.cpp).
Exact copies and digests are in tests/reference/qualification_dispatch_15_3.
The standalone probe supplies allocator/error-output integration only; compiler
and VM sources are unchanged. It runs controlled Squirrel, not OpenTTD gameplay.

## Rejected hypotheses

| Hypothesis | Result / evidence |
|---|---|
| Absolute structural deadline inherited from qualification start | Rejected: structural has no absolute phase deadline; it is constructed after M1 guard. |
| Structural timeout starts at coordinator construction | Rejected: fresh relative asyncio request timeout starts on each query. Virtual waits of 60/120 seconds still collect successfully. |
| Polling mutates shared transport deadline | Rejected: no shared absolute transport deadline; caller supplies min(5, remaining overall) per call. |
| Expired/completed structural object reused | Rejected: distinct new anchor and final sessions are constructed at their phase entry. |
| Request sent, response handling stalled | Request was sent; no response handling began. Tagged-VM repro proves dispatch fails first. |
| Deadline prevents send | Rejected by SENT ledger and admitted outbound frame. |
| Prolonged polling starves non-clock commands | No starvation required: even zero prior clock calls reproduce old delegation failure. |
| Connection alive but command dispatch fails | Proven dispatch incompatibility; 61 completed encrypted clock exchanges support preceding transport health. |
| Structural response exists but is rejected | No retained frame, payload or GS response marker; deterministic repro emits none. |
| Another timeout translated to generic phase error | Proven: StructuralWorldSession converts TimeoutError (including TransportTimeout) to that message. |

## Deadline ownership

| Concept | Owner / creation / clock | Scope / consumer |
|---|---|---|
| Overall qualification | ProductionQualificationSession.collect entry; monotonic absolute +300; outer asyncio timeout | Entire session including polling, collections, evidence. Never renewed. |
| Polling | Same overall absolute bound plus finite shared poll count | Both rollover waits, cadence >=1 second; no wall-clock qualification evidence. |
| Structural collection | New single-use session at anchor/final entry | No separate absolute phase deadline; each query/evidence has relative <=5 and remaining overall bounds. |
| Lifetime collection | Qualification session loop at its phase | Each new query/evidence bounded independently; same overall deadline. |
| Production collection | New production session after stability | Same fresh per-query/evidence timeout and overall guard; no old observation relabeling. |
| Transport request | _read_query entry; asyncio monotonic relative min(5, remaining overall) | Subscription if needed, send, response, completion barrier. No mutation/reuse between commands. |
| Semantic evidence/liveness | Each bounded callback plus native evidence loop | Fresh <=5-second relative callback and native monotonic +5 loop; outer remaining overall still applies. |
| Setup | Owned listener +30, bridge setup +10 from entry | Pre-collection setup; separate from qualification's collect-entry deadline. |
| Cleanup | Shared bounded close/quit/wait/escalation owner | Cleanup after failure remains permitted; it cannot qualify or resume the failed session. |

There is no hidden phase-wide 5-second collection budget. Five seconds bounds an
individual transaction/evidence callback, not a complete 96-request collection.
The explicit 300-second overall bound includes all collections. Fresh local
request/evidence budgets cannot resurrect an expired overall attempt.
No timeout values or polling values were increased or changed.

## Contract impact

Only dispatch implementation, explicit deadline/dispatch authority metadata,
source identities, lineage, revision and destination change. Resource arithmetic
remains 304 clock requests /1072 application requests /368080 response bytes /
9088 query operations +6 once-per-session lifecycle frames =9094 post-auth frames.
Qualification semantics M0→M1→M2, T1==T2, lifetime stability, fresh M2 production,
final guard, production_level deferral and P08 exclusion remain unchanged.

Revision 2 must name fresh attempt2, retain failed Attempt 1 digests and its native
attempt ID, and use no prelaunch continuation exception. Fresh authorization is
required. This controlled repair does not establish real two-rollover qualification.
