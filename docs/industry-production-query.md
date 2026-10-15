# Controlled OpenTTD 15.3 industry production query

Baseline Git HEAD: `b6f5cfaf65a4025edebf659cd4744b2534341ae1`.
Local CONTEXT.md remains architecture authority. The retained
[native API audit](industry-production-native-api-audit.md) and
[dynamic supply design](industry-production-dynamic-supply-design.md) remain historical
semantics authority. This slice implements a controlled read-only query, not a native proof,
a qualified real production history, a runtime preparation, or a planner adapter.

## Protocol and exact source authority

`industry_production` targets one `industry_id` plus one produced `cargo_id`.
Canonical JSON uses sorted keys, compact separators and the existing ASCII serializer:

```json
{"cargo_id":1,"industry_id":3,"protocol":1,"request_id":"prod-001","type":"industry_production"}
```

The response type is `industry_production_result`, status `ok`. It echoes both IDs
and request ID, and retains `economy_date_before`, `economy_date_after`,
`last_month_produced`, `last_month_transported`, and `last_month_transported_pct`. There is no localized string, output stockpile, synthetic rate,
capacity calculation, or native history-valid flag. Invalid industry/cargo or a
non-produced relationship does not generate semantic success: the thin handler
rejects it and the bounded owner fails without retry.

| C++ Script API | Exact GameScript binding | Units / window / interpretation |
| --- | --- | --- |
| ScriptIndustry::IsValidIndustry | GSIndustry.IsValidIndustry | Current native industry validity. |
| ScriptCargo::IsValidCargo | GSCargo.IsValidCargo | Active native cargo validity; prior verified cargo authority reused. |
| ScriptIndustry::GetLastMonthProduction | GSIndustry.GetLastMonthProduction | uint16 cargo units reported in the previous economy-month bucket; invalid/non-produced returns -1. |
| ScriptIndustry::GetLastMonthTransported | GSIndustry.GetLastMonthTransported | uint16 cargo units allocated into station waiting cargo for that bucket; not vehicle pickup or delivery. |
| ScriptIndustry::GetLastMonthTransportedPercentage | GSIndustry.GetLastMonthTransportedPercentage | Native quantized/clamped integer 0..100 for that bucket; not a Python-computed percentage. |
| ScriptDate::GetCurrentDate | GSDate.GetCurrentDate | Economy-date reading immediately before and after the native metrics. |

Exact tag15.3 authority is hash-pinned in
`tests/reference/industry_production_15_3/manifest.json`, referencing the industry
implementation/header, economy-date implementation/header, native output slot bound,
and the already retained API CMake/Squirrel export generator. The generator selects
`game;GS`, replaces the Script prefix with GS and preserves static method names.
Production level remains dimensionless but is deferred from V1. Inspection and controlled
SQVM execution do not prove a real OpenTTD native binding.
[Industry implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.cpp),
[economy date implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_date.cpp),
[binding generator](https://github.com/OpenTTD/OpenTTD/blob/15.3/cmake/scripts/SquirrelExport.cmake).

## Payload contract

The audited V1 field set is retained unchanged, as explicitly selected by the user.
Production level is deferred; no native level read or response/digest field is included.
Maximum canonical response is **335 bytes**.

The worst case uses a 64-character safe ASCII request ID, industry63999, cargo63,
both economy dates2147483647, produced/transported65535, percentage100.
The canonical serializer test verifies the exact result:

- Application maximum512; headroom177 bytes.
- Native GSAdmin.Send ceiling1450; headroom1115 bytes, and response strictly <1450.
- No pagination: one bounded pair per request; Python bounds complete coverage.

Date integers are conservative wire envelopes. A coherent owner-supplied economy
month further constrains capture dates; the range is not a universal GSDate validity
claim. Malformed/extra fields, booleans pretending to be integers, wrong response
command/status/request/pair, native -1, and out-of-range metrics are rejected.

## Raw metrics and planning qualification

Fresh map generation can seed last-month estimates. Ordinary newly built industries
can expose zero history. A positive native value is not proof of elapsed observation;
zero can mean missing history, genuine inactivity, no input, or representation limits.
Structural capability remains the authority for eligibility.

`IndustryProductionRecord` retains exact raw quantities, native percentage, capture-date brackets. Amounts are independent uint16 counters which can
wrap, so `transported <= produced` is not a universal wire invariant. Neither service
percentage nor station allocation is future supply or post-delivery performance.
There is no general industry cargo-rate getter or output-stockpile getter. Input
waiting is a different excluded API.

`ProductionWindowQualification` is immutable and typed. Its states are:

1. `UNQUALIFIED_INITIAL`: zero observed economy-month rollovers.
2. `UNQUALIFIED_AFTER_FIRST_ROLLOVER`: the first replacement bucket can describe an
   initial partial month, so it is still unqualified.
3. `QUALIFIED_AFTER_SECOND_ROLLOVER`: the intervening full economy month is the
   measured window, provided same-run provenance and controlled evidence are valid.

The owner supplies `EconomyMonth` readings/boundaries from the audited economy clock.
Gregorian economy mode and wallclock 30-day economy mode are not replaced with Python
wall-clock duration. No native month query, polling process or real warm-up is added
here. Controlled tests supply explicit readings. A native preparation must establish
trustworthy observed boundaries and industry identity/existence throughout the measured
interval; synthetic readings are not a real qualification proof.

Duplicate readings return the same state; they cannot advance qualification. Skipped,
backward or nonadjacent boundaries fail. Runtime/process/connection/world/config/bridge
replacement fails. The qualified window is sealed; advancing past it requires another
explicit observation window. All response date brackets must remain inside its current
capture month. A rollover during/across reads fails instead of mixing buckets.

`complete` means exact validated produced-pair coverage. `qualified_for_planning` also
requires a two-rollover coherent window and valid source provenance. An initial seeded
positive observation can be complete and still unqualified. Receipt success never
implies qualification. Qualification/window identity is canonical semantic data, not a
UI label. These controlled states are not a claim of qualified real production history.

## Models, provenance and deterministic identity

The immutable `IndustryProductionObservation` references its complete source
`StructuralWorldObservation`, same-run `StructuralWorldContext`, qualification,
canonical records and validated transactions. Existing inventory, capability, catalog
and structural models are unchanged. It requires exact source structural digest,
process and connection object identity, runtime/map/world/config and bridge identity.
A historical structural proof cannot be attached to a different later runtime.

Targets come only from each source industry's `produces`, in ascending industry then
cargo order. Accepted-only cargo, missing industry/catalog record, extra/duplicate pair,
or incomplete coverage cannot assemble a complete observation. Shared produced cargo
across industries is valid; zero industries performs zero queries. Cargo metadata
remains in the immutable source catalog, not duplicated into production records.

The `industry-production-v1` canonical digest includes source structural semantic
digest, qualification status/count and observed economy-month identities/boundaries,
and sorted raw production/transported/percentage records. Capture-date
brackets remain retained evidence, not additional digest fields: the coherent month is
semantic window authority. Request IDs, transaction order, logs, packet boundaries,
paths, process addresses and UI labels are excluded. Equal semantic records/window
hash equally under different request IDs/order. Changing metrics/window/qualification
changes the dynamic digest; the source structural digest remains unchanged.

A future `WorldPlanningObservation` can require complete structural and complete,
qualified production observations with exact provenance, plus an explicit supply
projection policy. No composition model or PreparedWorldManifest/P08 adapter is
implemented here. Transport and query modules import neither planning nor evaluation.

## Bounded collection and transport ownership

`IndustryProductionSession` is single-use and PRE-DECISION only. Its deterministic
identity defaults to `openttd15-industry-production-001`, with child IDs `-p001` through
`-p512`. It uses the existing `GameScriptTransport.industry_production` read-query path,
shared native Admin send/receive authority and existing receipt/barrier semantics.
No new connection, fake native frame counter, reconnect or automatic retry is added.

Bounds derive from 32 source industries ×16 native output cargo slots:

- Maximum records / application requests512.
- Maximum cumulative response bytes512 ×335 =171520.
- Controlled query-operation allowance512 ×8 =4096, using the established bounded
  operation accounting abstraction. Every actual exchange operation consumes that
  continuous allowance. **This is not a new native total post-auth frame contract.**
  Native combined structural+production frame accounting is a later preparation task.
- Shared transport retains used IDs from structural collection; up to96 structural
  plus512 production IDs are supported, with a separate512 production-request ceiling.
  Existing other-command request limits remain unchanged.

Each transport transaction and subsequent liveness evidence wait has a finite timeout.
Failure prevents another query/phase, retains received exchanges and partial evidence,
and closes the originally owned connection (never a substituted connection). Cleanup
is bounded; a cleanup error is retained separately without replacing the original
failure. A partial session never publishes a complete observation or semantic digest.
There is no resume, resend or retry after failure.

## Evidence and pre/post-decision separation

GameScript per pair:
`BRIDGE_REQUEST_RECEIVED → INDUSTRY_PRODUCTION_READ → BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE`.
The read marker retains canonical integer pair/date/metric metadata; Python
correlates it against the validated response. No debug-object string formatting or
qualification logic is placed in GameScript. Native logging does not fabricate SHA-256;
Python request/response receipt digests supply that exact correlation authority.

Python per pair:
`INDUSTRY_PRODUCTION_REQUEST_SENT → INDUSTRY_PRODUCTION_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED → PRODUCTION_RECORD_VALIDATED`.

Session:
`INDUSTRY_PRODUCTION_SESSION_STARTED → validated records → PRODUCTION_OBSERVATION_ASSEMBLED → PRODUCTION_QUALIFICATION_EVALUATED → INDUSTRY_PRODUCTION_SESSION_COMPLETED`.
Failure is explicit and retains truthful coverage. Ordering is local/partial; no total
cross-process timestamp order is inferred.

The owner marks `ProductionDecisionBoundary` when optimization/intervention occurs.
Collection checks it before requests, after responses/evidence and before assembly.
POST-DECISION data fails rather than entering input observations. Future evaluation
has separately identified later windows and plan attribution; this collector imports
no evaluation telemetry. Owners must mark the boundary honestly; no optimizer is
implemented or invoked here.

## Preservation and claim boundary

Retained historical proofs/freezes/CONTEXT.md remain untouched. Older cargo and structural
proof preparation contracts pin the old bridge digest; their controlled regressions use
`tests/fixtures/structural_bridge_checkpoint`, a hash-verified byte-for-byte copy from the
baseline commit. Their frozen contracts are not changed to accept the expanded bridge.
The new production handler is exercised against the current package under controlled
SQVM fake APIs. A future native proof needs a new source/package preparation and fresh
explicit authorization.

Controlled production query = PROVEN by controlled fixtures.
Real native production binding = NOT YET PROVEN.
Qualified real production history = NOT YET PROVEN.
Independent production source = NONE. P08 completion = NO.

No gameplay mutation, live runtime, proof credential, production freeze, commit or push
belongs to this slice. Required launches/connections/real requests remain0/0/0.
