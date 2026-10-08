# Same-run complete raw industry-production coverage

Status: controlled implementation only. Baseline checkpoint:
`278a3792b34fdb58085aff4e999dabac482cf21a`.

`CompleteRawProductionSession` extends the existing Python structural coordinator,
using one owner-supplied transport and context. It returns the unchanged immutable
`StructuralWorldObservation` and a separate `IndustryProductionObservation`.
There is no new planner composition model or P08 adapter. GameScript and the
industry_production protocol remain unchanged. Production_level is DEFERRED / NOT
INCLUDED. The production audit and dynamic-supply design remain semantic authority.

## Phase barriers and targets

A: complete inventory. B: complete capability. C: complete cargo catalog.
D: referential validation, complete structural assembly and finalized structural
digest. E: complete raw production. E cannot accept a historical structural source:
the coordinator obtains its source exclusively by collecting A–D on this session.

Targets are exactly every `(industry_id, cargo_id)` in each capability's `produces`,
ordered by ascending industry then cargo ID. The typed structural model already
validates inventory membership, unique ordered capability records and catalog
references; production revalidates those invariants. The target tuple has a read-only
public interface once the production session is constructed. Accepts-only and
unreferenced catalog cargoes never become targets. Empty industries or empty output
sets produce an empty complete observation with zero production requests.

Each pair is queried once. Missing, extra, duplicate, invalid, wrong-pair responses,
invalid receipt/evidence/liveness, provenance drift or exhausted budgets fail the
combined session. No retry, reconnect or resume is available. Completed structural
facts and partial production evidence remain available after failure, but no complete
combined result or production observation is published. The collector closes the
original session on failure with a bounded deadline; the runtime owner remains
responsible for process cleanup and the established final-success integrity gates.
Successful controlled collection does not itself mean native proof acceptance.

## Complete versus qualified

Complete means exact coverage of the immutable same-run produced target set, with
semantic and evidence validation and budgets satisfied. It does not mean elapsed
monthly history. This collector constructs only the initial qualification state:
zero observed rollovers, `complete=true`, `qualified_for_planning=false`. Zero and
nonzero native output are valid. Successful transport, positive values or complete
coverage never qualify the window.

The owner supplies one typed initial `EconomyMonth` reading. It is not derived from
wall-clock time or Python's calendar. Existing per-record date brackets must belong
to that month; crossing its boundary fails. There are no sleeps, date polling,
rollover counters or waits in this orchestration. A future separate warm-up phase
must observe two adjacent economy-month rollovers under the existing qualification
contract before any planning qualification claim.

Raw production remains the last-month native quantity, potentially seeded on a
fresh world. Transported remains station allocation, not vehicle pickup, delivery
or throughput. Percentage remains the native quantized/clamped integer percentage;
no synthetic percentage/rate/capacity is inferred. uint16 quantity semantics and
valid-zero ambiguity are preserved. Date brackets retain native economy-time
metadata. The audited V1 worst-case response remains exactly 335 bytes, under the
512-byte application maximum and 1450-byte native ceiling.

## Same-run provenance and digest

Both observations require identical opaque process and continuous connection
handles, runtime identity, world/configuration identity and bridge digest. The
production source digest must equal the just-finalized structural digest.
Context is checked before and after queries and evidence collection. A replaced
connection or historical source cannot satisfy this relation. Initial qualification
also binds that source and context.

Existing production digest semantics are unchanged: canonical pair order, raw
metrics, structural digest and qualification/window identity. Request IDs,
transaction execution order, packet boundaries, evidence paths, logs and capture
brackets within the same month do not define semantic identity. Records themselves
must remain canonical; transaction order may vary when validating an immutable
observation. The coordinator always executes canonical request order.

## Bounds and continuous accounting

| Bound | Structural | Production | Combined |
| --- | ---: | ---: | ---: |
| Application requests | 96 | 512 | 608 |
| Response bytes | 49152 | 171520 | 220672 |
| Abstract query operations | 1024 | 4096 | 5120 |

Production has at most 32 industries × 16 native output slots = 512 pairs.
512 × 335 = 171520 response bytes. Combined bounds are 96 + 512 = 608 and
49152 + 171520 = 220672. Phase-specific structural and production budgets still
apply even when the combined budget has headroom.

The existing structural query allowances are inventory 256 + capability 256 +
catalog 512 = 1024 (32 × 8 + 32 × 8 + 32 × 16). The existing production allowance
is 512 × 8 = 4096. The combined collector now enforces an eight-operation ceiling
on each production query, as well as its cumulative ceiling. This conservative
controlled allowance permits four bounded ancillary inbound frames beyond the
normal four operations. It is not copied from the single-native proof's frame limit.

Audited transport behavior: a normal subscribed query sends one GameScript request,
receives one response, sends its completion Admin ping, and receives its pong:
four query operations. The first structural query additionally performs subscription
plus setup ping/pong (three setup operations). These are counted in that first
exchange, once; production does not subscribe again. With clean controlled traffic,
actual combined operations are `4 × actual application requests + 3`, while Phase E
adds `4 × target count`. Authentication and cleanup are outside these query totals.

One monotonic ledger wraps all five phases and records each completed exchange's
cumulative request, response-byte and operation counts. There is no Phase E reset.
Local phase accounting remains validation data, not a replacement native frame
counter. A future real owner must keep the shared native Admin accounting continuous
and audit exact establishment/setup/cleanup and allowed ancillary frames for the
whole session. Native total post-auth-frame ceiling:
**DEFERRED TO REAL-PROOF PREPARATION**. The old structural 1030 and single-query 10
ceilings are not reused as a combined native contract.

## Evidence and claim limits

Structural event names and historical proofs are unchanged. Their own session
retains its full chain. The combined coordinator records phase barriers,
STRUCTURAL_WORLD_VERIFIED, RAW_PRODUCTION_PHASE_STARTED,
COMPLETE_PRODUCTION_COVERAGE_VALIDATED, RAW_PRODUCTION_OBSERVATION_ASSEMBLED and
COMBINED_SESSION_COMPLETED (or FAILED).

Each production transaction requires the existing four GameScript markers:
BRIDGE_REQUEST_RECEIVED → INDUSTRY_PRODUCTION_READ → BRIDGE_RESPONSE_SENT →
BRIDGE_POST_RESPONSE_ALIVE; and Python request → response → receipt → semantic
record validation. The production session additionally records phase start,
TARGET_SET_FINALIZED, per-record validation, complete coverage, observation assembly,
qualification evaluation and session completion. Qualification evaluation is false
for this initial raw slice. Transport success alone is insufficient.

This is PRE-DECISION and NON-ATOMIC. Longer collection increases snapshot drift
risk. There is no epoch, lock, atomic save, world freeze, rollback or guarantee that
structural facts stay unchanged during reads. Existing profile-stability assumptions
remain necessary; a month-crossing production read fails rather than waiting.
No optimizer, evaluation telemetry, gameplay mutation or P08 supply generation
participates.

Complete raw coverage and same-run structural/production provenance: CONTROLLED
ONLY. Real combined execution: NOT YET PROVEN. Qualified history: NOT PROVEN.
Independent production source: NONE. P08 completion: NO. The single-native Attempt 2
remains proven for its original source/configuration; Attempt 1 remains immutable
FAILED post-launch history. No historical report or freeze is rewritten by this work.
