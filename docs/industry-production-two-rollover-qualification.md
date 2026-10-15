# Two-economy-month-rollover production qualification — controlled V1

The controlled qualification contract is implemented and tested. No real
qualification runtime, proof freeze, credential, P08 adapter, or optimizer is
created by this slice. Real two-rollover execution and qualified historical
production remain NOT YET PROVEN REAL.

## Why two adjacent rollovers

The baseline M0 can begin part way through a generated world's month. Its
last-month production values may be seeded; they cannot become final planning
supply merely by relabelling an initial observation. An explicitly observed
M0→M1 rollover witnesses M1's beginning. M1→M2 witnesses M1's end. Only fresh
native last-month production collected in M2 can describe fully bounded M1.
Elapsed wall-clock time and zero/non-zero production are not qualification
evidence. Jan→Mar is a skipped boundary, not two observed rollovers.

The immutable `NativeRolloverEvidence` distinguishes UNINITIALIZED, BASELINE,
FIRST_ROLLOVER, SECOND_ROLLOVER and FAILED. Equal and repeated same-month samples
are valid monitoring observations. New-month samples must be adjacent and on
native day 1. Backward dates, skipped months, missed first days, and M2→M3
collection fail. Clock evidence alone never sets qualification. Final admission
uses `QualifiedProductionResult` and `QualifiedProductionVerification`.

## Exact native authority and date domains

Pinned tag-15.3 primary sources are retained with URLs and SHA-256 manifests in
`tests/reference/economy_clock_15_3/`, `qualification_15_3/`, and
`qualification_timing_15_3/`. Generated names follow the pinned
`SquirrelExport.cmake` GameScript export authority.

| C++ Script API | GameScript binding | Input | Native result |
| --- | --- | --- | --- |
| ScriptDate::GetCurrentDate | GSDate.GetCurrentDate | none | signed Date economy-day ordinal from TimerGameEconomy |
| ScriptDate::GetYear | GSDate.GetYear | Date | SQInteger economy year |
| ScriptDate::GetMonth | GSDate.GetMonth | Date | SQInteger economy month, 1–12 |
| ScriptDate::GetDayOfMonth | GSDate.GetDayOfMonth | Date | SQInteger day, 1–31 |
| ScriptDate::GetDate | GSDate.GetDate | year/month/day | native economy Date from YMD conversion |
| ScriptIndustry::GetConstructionDate | GSIndustry.GetConstructionDate | IndustryID | CALENDAR construction Date; DATE_INVALID for invalid industry |

`script_date.cpp` uses economy converters. Negative date inputs return
DATE_INVALID. GetDate rejects invalid month/day ranges and years outside the
native domain. Boundary conversion uses day 1, avoiding normalized invalid
end-of-month dates. December→January increments the year; year zero is leap.
Native Date is an integer, not a wall-clock timestamp. The extreme maximum-year
wrap is unsupported and fails backward-date validation.

`economy_clock` captures one native current date, then reads its native year,
month, day and first-day boundaries. Python validates that all fields describe
one coherent date. V1 selects the **calendar-economy generated-world profile**;
wallclock-economy conversion (30-day months) is excluded. Equal query brackets
are legal. A late day-1 sample still witnesses the boundary under this
conservative contract; a first sample on day 2 cannot qualify it.

`industry_lifetime` captures the native calendar construction identity between
economy current-date brackets. Its construction integer is never interpreted
as an economy sample. The DTO deliberately permits a construction integer
numerically greater than an economy bracket: the domains are independent.

The additional conservative age gate is permitted only by
`QualificationProfile.synchronized_generated_calendar`. Exact source in
`misc.cpp` initializes generated calendar/economy dates to the same date in
calendar mode; `timer_game_economy.cpp` explicitly uses calendar conversion in
that mode. The selected profile requires default calendar pacing, no NewGRFs,
no save/load, no timekeeping changes, no restart, and no interventions. Only
under this source-backed synchronized profile is a **calendar** M1 boundary
computed from its calendar YMD for construction-age comparison. Arbitrary
saved worlds and wallclock economy are rejected; no general calendar/economy
conversion is claimed. Real-proof preparation must verify the profile against
actual immutable configuration, rather than trusting caller booleans.

## Thin adapter and transport

`qualification_bridge.nut` adds only bounded `economy_clock` and
`industry_lifetime` reads. It is composed with the unchanged proven raw bridge
by `qualification_bridge_source`/`stage_qualification_bridge`. The inherited
loop supplies the existing post-response liveness marker. There are no new
GameScript loops, rollover counters, history arrays, suitability flags, sleeps,
or gameplay commands. Python owns polling, sequencing and admission.

Both commands use the existing production transport's subscription and
completion PING/PONG machinery. Responses must pass request/type/target,
strict field/type coherence, receipt, semantic validation and native log
correlation. New payload maxima are canonical, with a 64-byte request ID:

| Query | Request bytes | Response bytes | Mandatory query frames | Conservative allowance |
| --- | ---: | ---: | ---: | ---: |
| economy_clock | 117 | 271 | 4 | 8 |
| industry_lifetime | 141 | 248 | 4 | 8 |

The four mandatory frames are request, response, completion PING and PONG.
Other admissible decoded frames consume the same conservative allowance;
there is no assumption that every future query always consumes exactly four.
Subscription is performed once before the owner starts. Every response must
also fit 512 application bytes and the native ceiling of less than 1450 bytes.
The proven industry_production contract remains unchanged: worst case 335
bytes, station-allocation transported semantics, native percentage, current
capture brackets, production_level DEFERRED / NOT INCLUDED.

## Single-use coordinator and stability

`ProductionQualificationSession` runs:

1. Native baseline M0, then paced polls for the first adjacent rollover.
2. M1 clock guard, complete anchor inventory→capability→catalog→structural
   observation, finalized produces-only T1, ascending producing-industry
   lifetimes L1, then an M1 clock guard.
3. Paced monitoring polls for the second adjacent rollover.
4. M2 clock guard, fresh complete final structural observation, finalized T2,
   ascending lifetimes L2, then target/lifetime stability validation.
5. Fresh complete **raw** final production, then an M2 clock guard.
6. Validate the bounded M1 metadata, fresh final structural digest, complete
   native/semantic evidence and budgets; only then admit a new qualified
   observation and complete the semantic coordinator.

T1==T2 is required; no intersection or silent omissions. Accepted-only and
catalog-only cargoes never become targets. L1==L2 and producing-industry
inventory fingerprints must match. Construction identities must predate the
calendar M1 boundary under the restricted synchronized profile. This
conservatively rejects same-day births/replacements that date-resolution
identity cannot otherwise distinguish. Vanilla produced cargo slots are
initialized in `DoCreateNewIndustry`; source production changes adjust rates
and history, not cargo identity. NewGRF-dependent cargo initialization and
callbacks are excluded by V1. Full structural digest equality is unnecessary:
unrelated catalog changes may be allowed, while final production always binds
to the FINAL M2 structural digest.

The stability guarantee concerns the final produced targets. Endpoint snapshots
are not a general event history of unrelated transient industries. The session
remains NON-ATOMIC; autonomous changes may occur. Stability is not a transaction
lock or an atomic world epoch.

T1==T2==empty is valid. All native clock and structural conditions remain
required, but zero targets send zero lifetime and zero production requests.
A complete empty observation can qualify. Each target set is an immutable,
read-only tuple once finalized. No initial M0 production is collected or reused.

## Operational polling policy and arithmetic

V1 uses a **1-second minimum paced interval** and **300-second fixed overall
session timeout**, including collections and evidence waits. A per-query/evidence
wait is bounded by the remaining overall deadline and the query's maximum
5-second timeout. Controlled tests inject virtual pacing; no real month waits
are performed. The operational clock can fail liveness but never prove a
rollover. Slow, paused or overloaded games fail rather than expanding bounds.

`gfx_type.h` defines normal ticks as 27 ms and `Ticks::DAY_TICKS` is 74: nominal
calendar-economy days are 1.998 seconds. Two longest consecutive months contain
62 days (nominal 123.876 seconds). This informs the one-second cadence and
300-second liveness policy but is NOT a hard real-time engine guarantee.
`StateGameLoop` stops economy progress during pause/modal progress; the dedicated
loop uses normal Tick/SleepTillNextTick scheduling. Fast-forward is excluded
for the networked dedicated profile. Calendar pacing/timekeeping settings and
server pause configuration must be verified in future real preparation.

A paced query may start only strictly before the overall deadline. For minimum
interval I and timeout T, at most `ceil(T/I)-1` paced polls can start. Collections
and response latency only reduce that count. Default maximum is 299 shared
across BOTH waits. Add baseline 1, anchor guards 2 and final guards 2:
**maximum clock requests = 1+299+2+2 = 304**. The provisional 143 cap is removed.

| Phase | Applications | Response bytes | Conservative query operations |
| --- | ---: | ---: | ---: |
| All clock samples | 304 | 304×271 = 82384 | 304×8 = 2432 |
| Anchor structural | 96 | 49152 | 1024 |
| Anchor lifetime | 32 | 32×248 = 7936 | 32×8 = 256 |
| Final structural | 96 | 49152 | 1024 |
| Final lifetime | 32 | 32×248 = 7936 | 32×8 = 256 |
| Final production | 512 | 171520 | 4096 |
| Total | **1072** | **368080** | **9088** |

The inherited shared secure native accounting pays establishment PROTOCOL/
WELCOME 2, subscription UPDATE_FREQUENCY/PING/PONG 3, and graceful QUIT 1,
**once**: total post-auth ceiling **9088+6 = 9094**. Completion PING/PONG is
already query traffic. Python phase changes, target finalization and semantic
markers send zero Admin frames; GameScript liveness arrives in the owned log.
There is no polling-specific second frame counter. Each phase has independent
request/byte/query caps; unused capacity cannot transfer. The owner correlates
receipt operations to one continuous native observer and rejects reset,
replacement or overflow.

## Evidence, failure and admission

Clock and lifetime native chains are REQUEST_RECEIVED→command_READ→
RESPONSE_SENT→POST_RESPONSE_ALIVE. Python chains are command_REQUEST_SENT→
command_RESPONSE_RECEIVED→TRANSPORT_RECEIPT_CREATED→command_VALIDATED.
Native raw logs, request/response SHA-256 receipts, metrics and liveness are
correlated per request. Qualification evidence retains both structural
components, fresh production transactions, rollover samples, native clock and
lifetime transactions, phase budgets and shared frame identities. Final result
validation reconstructs the native clock progression and checks the complete
local qualification semantic sequence. No total timestamp ordering is invented
between Python and GameScript producers.

Invalid clocks, skips, timeouts, exhausted polls, lineage changes, target or
lifetime changes, incomplete observations, missing evidence, invalid records,
M1/M2 guard crossings, accounting failures, reconnects and resumes terminally
fail. Completed components and truthful partial response/evidence survive;
no qualified result is published. Even if final raw production succeeds before
an M2→M3 guard failure, it remains **complete but unqualified**. The owner is
single-use after COMPLETED or FAILED, with zero retries and reconnects.

Coordinator COMPLETED denotes semantic collection completion. A future native
proof must still use the repaired shared cleanup ownership/lifecycle: Admin
close, process reap, endpoints closed, credential deletion, workspace disposal,
post-run source/history integrity, then final proof COMPLETED/PASS. This task
adds no alternate cleanup implementation or early native proof success marker.

## Claim boundaries and future P08 gate

Incomplete/unqualified and complete/unqualified states remain valid. Complete/
qualified requires all observed-window, stability, fresh-coverage, lineage,
coherence, evidence and budget gates. Incomplete/qualified is invalid.

M0 may contain seeded history; first rollover alone is insufficient. Fully
bounded M1, queried afresh in M2, resolves that initial seeded-history ambiguity
under the V1 contract. Raw zero and non-zero production remain valid.

This is PRE-DECISION observation. No planning, construction, vehicle operations,
evaluation telemetry or P08 imports enter the collection layer. The future P08
adapter may consume dynamic supply only when complete=true AND
qualified_for_planning=true; it is not implemented here. Atomic snapshot = NO,
independent production source = NONE, P08 completion = NO.
