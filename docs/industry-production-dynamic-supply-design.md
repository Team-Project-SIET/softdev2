# OpenTTD 15.3 industry production / dynamic supply audit

Audit baseline HEAD: `b6f5cfaf65a4025edebf659cd4744b2534341ae1`.
Architecture authority: local CONTEXT.md, unchanged. This is audit and design only.
No protocol, models, tests, planner adapter or runtime lifecycle is implemented here.
The exact API/core audit is in [native API audit](industry-production-native-api-audit.md).

## Findings that control the design

**Last-month production is not capacity or a forecast.** During map generation,
15.3 initializes LAST_MONTH.production using cargo-scaled rate × 8 and, when
applicable, production-callback waiting × 8. Those initial values did not accumulate
through an elapsed month. Ordinary gameplay-created industries instead have zeroed
history. After rollover, the stored last-month bucket reflects the preceding
elapsed economy-month portion. A positive first query does not establish genuine
history; a zero does not establish absent structural capability.
[Creation and history update authority](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/industry_cmd.cpp#L1842-L1855).

**Transported is station allocation, not vehicle pickup or delivered demand.**
Industry statistics increment production as waiting output is released for station
distribution; transported increases by the return from MoveGoodsToStation, which
allocates output into station waiting cargo based on ratings. No nearby eligible
station yields zero transported. This does not measure a route's delivered goods,
revenue, throughput or profit.
[Industry accounting](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/industry_cmd.cpp#L524-L547),
[station allocation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/station_cmd.cpp#L4599-L4682).

**No Script API history-valid marker is exposed.** A client cannot distinguish
seeded history, absent history and genuine inactivity from a numeric production
field alone. Valid industry/cargo and membership checks distinguish API invalidity
(-1) from valid zero. Source/runtime elapsed-time provenance must qualify a planning
observation. GetLastProductionYear and construction date are contextual clues, not
proof of a full preceding economy-month bucket.
[ScriptIndustry implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.cpp#L75-L121).

## Production concepts and optimizer suitability

Classification: A = suitable input to an explicit supply estimator; B = useful only
after qualified warm-up; C = evaluation input rather than supply; D = descriptive
analytics; E = unreliable as direct quantitative supply. None guarantees future output.

| Concept / metric | Classification | Planning interpretation |
| --- | --- | --- |
| Instance produces/accepts membership | A for eligibility, E for quantity | Structural capability identifies possible relationships, not units available. |
| GetLastMonthProduction | B, then A for an explicit estimator | Historical cargo units for a closed economy-month, after provenance qualifies that window. Preserve raw value; projection into a horizon requires a separate policy. |
| Initial map-generated last-month value | E as historical supply | Seeded estimate; may be retained as initialization evidence but never silently relabelled measured history. |
| GetLastMonthTransported | C | Station allocation/service evidence; not unused capacity, future demand, pickup or final delivery. |
| GetLastMonthTransportedPercentage | C / D | Quantized/clamped service indicator; not a transport mode or marginal supply estimate. |
| GetProductionLevel | D; E as direct supply | Dimensionless current control level, not units/day. Engine rates and callbacks determine output. |
| Internal produced.rate | E / unavailable via industry Script getter | Core implementation state is not a legal new wire API; no invented GSIndustry.GetProductionRate. |
| GetStockpiledCargo | D; E as standalone output supply | Current accepted/input cargo waiting for processing, not output inventory or a guaranteed conversion yield. |
| IsCargoAccepted | D / separate operational eligibility | Instantaneous accepted/refused state; structural accepts membership alone is not current acceptance. |
| IndustryType raw/processing/increase flags | D / qualified structural eligibility | NewGRF authors control interpretation; no numeric capacity or conversion recipe. |
| GSTile.GetCargoProduction | A for catchment presence only | Counts nearby producing sources, including native industry cargo membership; not industry monthly volume. |

Sources: [ScriptIndustry contracts](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.hpp),
[IndustryType contracts](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industrytype.hpp),
[tile implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_tile.cpp#L223-L228),
[catchment production counting](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/station_cmd.cpp#L533-L560).

The industry counters are uint16 (0..65535), not unbounded totals. Independently
accumulated counters can wrap. Station fractional allocation also means the API
contract must not be replaced by an invented universal transported<=produced
assertion. Percentage uses a clamped 8-bit ratio converted to integer percent;
recomputing rounded 100*transported/produced is not API-equivalent. For a restricted
non-overflow controlled fixture, test the expected ordering, but preserve/reject
an anomaly by explicit observation policy rather than declaring generic protocol
malformed merely because it violates that assumed inequality.
[Storage and percentage](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/industry.h#L62-L77).

## Fresh-world and time semantics

| Time | What can be concluded |
| --- | --- |
| Immediately after map generation | Last-month production can already be nonzero due to seeded estimates; transported starts zero absent other saved/runtime activity. Not measured previous-month supply. |
| Some ticks/days, before first economy rollover | Current-month internal counters change; last-month APIs still expose the prior/seeded bucket. No current-month total or output-waiting industry getter is exposed by this API. |
| First rollover | Internal history rotates; the previous month becomes LAST_MONTH. It may cover only a partial month if generation/construction began mid-month. |
| Second rollover | For an industry present throughout the intervening month, LAST_MONTH can cover a fully elapsed economy-month. Earlier output changes and input availability still matter. |
| Multiple rollovers | APIs expose the latest last-month slot, not arbitrary historical periods. Core retains more history but ScriptIndustry does not export an indexed history getter. |
| Industry created later or loaded save with unknown provenance | Warm-up eligibility must be established again; the two numeric endpoints alone do not prove the object existed throughout the window. |

GSDate.GetCurrentDate/GetYear/GetMonth/GetDayOfMonth/GetDate are economy-time
queries in 15.3; do not infer Gregorian month length from Python datetime when
wallclock timekeeping is enabled. Calendar-based economy time shares Gregorian
calendar progression. Wallclock economy time uses 30-day months, independent of
slowed/stopped calendar technological progression. Pausing stops economy progression.
Script sleep/tick counts and OS elapsed seconds are not qualified month identities.
Exact tick progression and monthly callback ordering are recorded in the native audit.
[Date API and time domains](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_date.hpp#L22-L44),
[economy-date implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_date.cpp#L19-L53).

Zero ambiguity: valid zero can mean no elapsed history, zero seeded rate, no input,
no actual output, or a counter representation limitation. Invalid/closed industry,
invalid cargo and non-produced cargo return -1 from the quantity getters. Check
validity and same-run capability membership first. No getter proves permanence of
zero capacity; GetProductionLevel=0 or a close event is additional context, not a
universal diagnosis from zero output.

## Warm-up strategy comparison and recommendation

| Strategy | Correctness / usefulness | Determinism, cost and proof complexity |
| --- | --- | --- |
| Query immediately | Good API-binding proof; bad evidence of elapsed historical supply | Cheap/repeatable under fixed pins, but seeded values are ambiguous. |
| First economy rollover | Removes generation seed, but may expose a partial initial month | Moderate cost; insufficient generically unless exact month-start initialization and industry existence are proven. |
| Fixed game days | Can accidentally straddle incomplete months | Simple wait, wrong across timekeeping modes/month lengths; avoid. |
| Wait for a native history-valid flag | No such exposed industry Script API | Cannot implement honestly; positivity is not validity. |
| Structural/default output estimate | Relationship membership is reliable; amount is not | Cheap but unsuitable for quantitative planning without explicit model assumptions. NewGRFs defeat universal default rates. |
| Hybrid structure + qualified elapsed history | Best project fit; eligibility remains structural and historical quantities are separately labelled | Bounded, explicit economy-window warm-up costs at most the initial remainder plus one full month; freeze settings and endpoints. |

Recommend the hybrid. For a newly generated proof world, observe **two economy-month
boundaries**, then read the just-completed intervening full month. A first-boundary
shortcut is justified only in a separately frozen profile proving exact month-start
construction and complete interval coverage. This condition is economy-time based,
not a fixed wallclock sleep. Loaded saves need explicit provenance or fresh qualified
intervals. Do not report a native history_valid field that the API cannot supply.

A future native proof should pin a no-NewGRF profile with an eligible raw-output
industry, retain generation/start economy date and observed boundaries, establish
industry presence through the measured interval, and require at least one positive
produced cargo in the fully elapsed bucket. Query targets derive from live capability.
Other industries, especially processing industries without inputs, may legitimately
remain zero. Do not deliver cargo, construct service or change production controls
just to manufacture a nonzero read-only proof. Bound warm-up ticks/time and fail
without retry if the criterion is not met. Freezing a mature input save is another
future authorized profile, with its own source history and world identity.

## P08 requirements and current assumptions

The existing uncommitted P08 profile is pinned to 13.4/OpenGFX7.1, not a 15.3
compatibility claim (`app/planning/preparation/domain.py:SupportedWorldProfile`).
`candidates.py:select_demand` rejects non-positive last_month_production, selects one
fixed OD deterministically, copies that quantity into mandatory demand and sets the
deadline to horizon_days-1. The current design calls it a historical benchmark,
not a forecast. Pickup candidate screening also requires positive tile production.
No old P08 file is modified by this audit.

A 15.3 adapter must not inherit these assumptions silently:

- Positive last-month data can be initialization estimates; old selection does not
  retain a qualified economy-window/warm-up status.
- A monthly quantity is not horizon supply. A versioned supply/demand projection
  policy must state normalization, units, duration and uncertainty.
- The legacy probe loops over every active cargo for every industry. Non-produced
  cargo returns -1, while IndustryCargoFact requires NonNegativeInt. A future adapter
  must use capability membership/typed absence; never turn -1 into zero unnoticed.
- Tile production is a source-presence/catchment quantity, not the industry's
  production volume. Current acceptance is distinct from structural accepts.
- Freight is the OpenTTD freight-weight property; any freight-only benchmark demand
  filter is explicit planner policy, not proof that other cargo cannot be transported.

Future geometry/relationship candidate generation needs structural industry/cargo
relations and compatible facilities/engines/terrain. Quantitative optimizer input
additionally needs an explicit demand estimate, qualified observation window,
units and projection policy. A normalized rate may be derived from qualified month
units and that clock's duration; no native industry rate getter is promised.
Transported quantity is not required as supply; keep service evaluation separate.
A single historic month cannot guarantee processor conversion yields or future
production. P08 implementation/adaptation remains out of scope.

Repository authorities: `docs/specs/p08-world-preparation-design.md` demand policy;
`app/planning/preparation/candidates.py:55-98,136`; `probe_package/main.nut:114-140`;
`domain.py:SupportedWorldProfile,IndustryCargoFact,TileCargoFact`.

## Observation architecture

Keep StructuralWorldObservation unchanged: stable semantic industry relationships,
active cargo metadata and map/runtime identity. Add a future immutable
IndustryProductionObservation separately, with per-industry/cargo measurements,
qualified economy window, coverage/quality and same-run provenance. A future
WorldPlanningObservation can combine those validated observations plus an explicit
pre-decision estimate policy. A future planning/preparation adapter maps that
observation into PreparedWorldManifest/PlanningScenario; transport/query modules
must import neither planning model. Names here are proposals, not implemented types.

The production digest should cover sorted industry/cargo measurements, stable
window identity, semantic structural provenance and meaningful qualification policy.
It must exclude request IDs, pagination, timestamps, packet/evidence paths and
process addresses. Window and measurement values must affect the dynamic digest;
the structural digest must not change merely because another month elapsed.

## Proposed bounded protocol (not implemented)

Prefer **one industry + one produced cargo per request** for V1:

```json
{"protocol":1,"type":"industry_production","request_id":"...","industry_id":123,"cargo_id":1}
```

Candidate response fields:

```json
{"protocol":1,"type":"industry_production_result","request_id":"...","status":"ok","industry_id":123,"cargo_id":1,"economy_date_before":730485,"economy_date_after":730485,"last_month_produced":100,"last_month_transported":0,"last_month_transported_pct":0}
```

Each field has API authority: validity and produced membership checked against live
same-run components; amounts/percentage from the three GetLastMonth getters; dates
from GSDate.GetCurrentDate immediately before/after reads. Use GetYear/GetMonth to
establish the last completed economy month; reject a rollover during a read or
across the collection. Date fields denote observed economy dates, not invented
snapshot versions. Python owns qualification from generation/warm-up evidence.
No native history_valid flag, output stockpile, output rate, conversion ratio or
localized string is fabricated. Production level/input stockpile deserve separate
later semantics rather than stuffing unlike units into this historical V1 response.

A conservative canonical JSON maximum is **335 bytes**, with request_id64 ASCII,
industry_id63999, cargo_id63, both signed-int32 nonnegative dates2147483647,
produced65535, transported65535 and percentage100. Application headroom177 bytes;
native headroom1115 bytes; both 512 and strict <1450 limits hold. Calculation uses
sorted keys, compact separators and ASCII escaping, matching repository serializer
conventions. The date bound is a conservative storage envelope, not permission to
accept every integer as a valid GSDate. Typed errors also need bounded schema.

Native industry input/output slots can each contain16 cargoes. Returning all output
records with verbose fields in one industry batch cannot be justified under512.
Per-pair queries avoid pagination inside an industry and use bounded ascending
industry/cargo targets from capability. A future complete session must derive its
request/byte/frame ceilings afresh: 32 industries ×16 outputs =512 possible pair
queries, potentially 262144 bytes at a512-byte response bound. **Do not reuse the
structural96-request/49152-byte budget or authorize512 queries in this audit.** A
small first native proof should query one eligible pair only; complete production
collection requires its own explicit limits and authorization. An alternative
compact per-industry cursor-page protocol needs a separate serializer-bound design.

## Same-run ordering and barriers

Warm up before taking the final structural observation, then collect:

inventory → capability → catalog → structural assembly → production → dynamic
validation → future planning observation.

This keeps the already-proven structural chain intact and lets the complete catalog
validate every production cargo reference. Capability targets come only from the
same-run inventory. Structural complete/digest and catalog referential integrity
must precede production. Production must remain within one qualified last-month
identity; bracket dates for every result and compare across the session. A rollover,
changed industry identity, missing capability cargo or replaced connection fails
collection; no retry/resume. No historical cross-run observations are semantic input.

Warm-up itself can change industries. Comparing a beginning inventory to the later
inventory is not sufficient to prove arbitrary NewGRF identity continuity; construction
context/events and a deliberately restricted proof profile are required. Adding a
dynamic phase increases drift risk and proximity to a history rollover. Same economy
month plus date brackets protects bucket consistency, not atomicity of all fields.
No epoch/lock/save-reload mechanism is proposed here.

## Pre-decision input versus post-decision evaluation

Freeze immutable PRE-DECISION structural/production observations and an explicit
cutoff economy window before optimization. Planning provenance must name those
input digests and projection policy. POST-DECISION evaluation collects separately
identified later windows, linked to the applied plan/execution receipt. Never update
optimizer input in place, relabel post-action output as forecast input, or mix windows
that straddle intervention into an uncontaminated benchmark. A historical last-month
value overlapping the intervention is mixed evidence, not clean pre/post attribution.
Industry transported totals are not plan-attributed delivery metrics; P07 cannot
infer a particular route's success from them alone.

## Configuration and reproducibility risks

Freeze binary/source/API, landscape/date/timekeeping/calendar speed, seed and starting
world/save; industry/economy/cargo-scale settings; smooth/random production policy;
NewGRF identifiers, bytes, versions, parameters and callbacks; industry construction
and closure settings; companies/AI/GS policies and service state; paused intervals;
all warm-up endpoints, stop conditions and bounds. Same seed does not make arbitrary
wallclock reads identical. A fixed economy interval and exact world/settings profile
are needed for repeatable interpretation.

Random production changes/closure, economic recession, input delivery and player
service affect output. Industry callbacks may alter cargo membership, generation,
acceptance and production changes. Stockpiles and level are instantaneous and can
change within a nominal month. A zero industry cannot be made productive safely by
assertion. Do not use SetProductionLevel/SetControlFlags or other mutation APIs in
this read-only proof line. Do not generalize default-game rates to NewGRFs.
[Core production changes](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/industry_cmd.cpp#L2879-L3040),
[NewGRF production implementation](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/newgrf_industries.cpp).

## Controlled tests to plan (not implemented)

1. Valid single-pair canonical request/response and exact digests; ID/cargo/request
   correlation, strict schema, bounded errors, ascending pair targets.
2. Valid zero retained with explicit externally derived qualification; no-history
   zero and seeded positive must not become qualified observed supply automatically.
3. Map-generation seeded history, ordinary newly built industry zero, first partial
   rollover, full intervening month after second rollover, successive windows.
4. Multi-cargo industry coverage, missing/extra/duplicate pair result, unsupported
   produced cargo versus accepted-only cargo, missing catalog reference.
5. Invalid industry, closed industry, invalid cargo and native -1 reject semantic
   success; capability or construction identity changes invalidate same-run inputs.
6. Zero-production percentage, exact native quantization, max16-bit values and
   rollover/wrap anomaly policy; transported<=produced only for controlled restricted
   non-overflow fixtures where justified, not as universal protocol axiom.
7. Gregorian and wallclock economy-window identity, leap/December transition,
   before/after-read rollover and cross-result rollover fail, warm-up timeout fails.
8. Same process/connection/runtime/world/bridge provenance; no historical merging,
   replacement/retry/reconnect/resume; finite query/record/byte/frame bounds.
9. Dynamic digest changes with window/data; deterministic under reordered transport
   evidence; structural digest unchanged; source observations immutable.
10. Pre-decision cutoff and post-decision separation/leakage rejection.
11. Worst-case335-byte canonical response, <=512 and <1450; all-output batch rejected
    or separately bounded design; no native/localized debug representation.
12. No mutation APIs, no GetCargoIncome/delivered-demand fabrication, no P08 imports
    in DTO/transport/session modules. Existing structural real fixture remains valid.

## Verification and runtime activity

Exact tag15.3 source/API and generator inspection; static P08 repository search;
canonical payload calculation; documentation links/whitespace checks; git diff --check;
historical/context hash comparison. Production source untouched, so Ruff/format and
native tests are not required for this documentation-only task.

Gameplay launches=0. Live Admin connections=0. Real requests=0.
No commit or push. Historical evidence and CONTEXT.md unchanged.

Verified audit results: all 21 cited tag15.3 source files resolved successfully;
source hashes captured during inspection. Both new documents pass trailing-whitespace
checks; git diff --check passes. All 993 captured historical/CONTEXT hashes remain
exact. Baseline HEAD remains unchanged. Only the two new audit documents belong to
this task; pre-existing P08 and documentation changes remain untouched.

## Status

READY FOR CONTROLLED INDUSTRY-PRODUCTION QUERY DESIGN
