# Complete raw industry-production native proof preparation

The public `complete-raw-production` mode integrates one continuous secure Admin
session with structural collection followed by complete raw production coverage.
Baseline HEAD: `278a3792b34fdb58085aff4e999dabac482cf21a`.
Preparation does not authorize native execution. Real combined execution remains
unproven until a separately authorized immutable attempt completes.

## Public execution and phase barriers

The authoritative entry point is `python -m app.simulation.openttd.proof`.
Its `prepare --mode complete-raw-production` command creates the isolated frozen
contract. `preflight --mode complete-raw-production` validates that contract and
reaches the final subprocess boundary with creation blocked. A future authorized
`run --mode complete-raw-production --authorize-one-launch` uses the same runner;
there is no wrapper or separate structural/production CLI invocation.

Inventory must finish with a digest before capability starts. Capability must
finish with a digest before cargo catalog starts. The complete catalog is
referentially validated before structural assembly. Production starts only after
a complete, digest-finalized same-run StructuralWorldObservation exists.
Canonical targets are capability.produces relationships, ordered by industry ID
then cargo ID. Accepted-only and catalog-only cargoes are excluded. The target
tuple is immutable before the first production query; zero targets are valid.
Every target receives exactly one industry_production request, with no retry,
reconnect or resume.

The separate immutable IndustryProductionObservation requires the exact source
structural digest and identical process, connection, runtime, world/config and
bridge identities. StructuralWorldObservation is unchanged. Exact coverage may
be complete while qualified_for_planning remains false; successful transport or
non-zero production cannot qualify history.

## Combined accounting derivation

The combined backend specializes the established StructuralFrameBudget and uses
its encrypted/decrypted frame observer throughout all phases. Receipt accounting
validates that same counter; it does not add frames to a second counter.

| Category | Conservative post-auth frames |
| --- | ---: |
| Encrypted PROTOCOL and WELCOME | 2 |
| One UPDATE_FREQUENCY, setup PING and PONG | 3 |
| Inventory | 256 |
| Capability | 256 |
| Catalog | 512 |
| Production | 4096 |
| Graceful QUIT | 1 |
| Total | 5126 |

Query operations include outbound request/control frames and decoded inbound
frames admitted during each query. Query completion PING/PONG are already part
of the query allowance. The production allowance is 512 × 8, conservatively
allowing four ancillary frames beyond a normal four-operation subscribed query.
Eight is a ceiling, not an assertion of eight frames per native result.

The transport subscribes once before inventory and remains registered through
production. Encrypted PROTOCOL/WELCOME count; authentication before encryption
enablement does not. Graceful QUIT counts once; TCP EOF is not a frame. Phase
barriers and target finalization are Python operations. GameScript liveness comes
from owned stderr and adds no Admin traffic. Thus the whole continuous-session
ceiling is **1024 + 4096 + 2 + 3 + 1 = 5126**, with six lifecycle frames paid once.
Counters never reset and per-phase budgets remain independent.

Application ceilings are **96 + 512 = 608** requests and
**49152 + 171520 = 220672** response bytes. Production has at most 512 records
and the unchanged audited 335-byte worst-case V1 response. Application/native
payload limits remain 512/1450 bytes. production_level remains deferred and
excluded. Raw production, station allocation, transported percentage and economy
brackets retain their audited semantics; allocation does not mean vehicle pickup
or delivery completion.

## Native economy-window authority

[The exact 15.3 source audit](complete-raw-production-economy-window-authority.md)
identifies ScriptDate::GetCurrentDate / GSDate.GetCurrentDate as economy-date
metadata. Both V1 brackets are current-state captures; equal brackets are legal.
They do not identify a qualified historical production interval.

The isolated fresh-world profile explicitly uses calendar timekeeping (0) and
starting year 1950. SERVER_WELCOME.start_day identifies the configured initial
calendar date, not the current date. Under this pinned profile, the native
Gregorian conversion yields the initial economy-month identity without another
application command. All response brackets must remain inside that initial
month. A crossing fails immediately; there is no waiting or fallback. Historical
Attempt-2 values are never expected constants. Save loading and wallclock
profiles are outside this proof contract.

## Lifecycle, evidence and ownership

The lifecycle records prepared, launched, Admin active, combined session started,
structural collection started/completed, targets finalized, raw production
started/completed and combined semantic verification. It then records cleanup,
process reap, endpoint closure, credential removal, workspace disposal and
post-run integrity. Only the complete ordered sequence permits COMPLETED and
final PASS. Semantic success before cleanup is an intermediate result. Cleanup,
integrity or terminal evidence persistence failure produces FAILED.

Existing structural evidence is retained unchanged. Every production query
requires GameScript received → production read → response sent → post-response
alive, and Python request sent → response received → receipt created → semantic
record validated. Combined evidence additionally records target finalization,
exact coverage, observation assembly, qualification evaluated as false and final
combined verification. Partial records remain truthful and incomplete on failure.

The repaired shared ownership graph protects immutable canonical sources and
historical evidence, permits disposable runtime materialization removal, requires
credential removal and retains generated evidence. Resolved paths and aliases
cannot overlap cleanup roots. Runtime-copy content identities are separate from
persistent source identities. Source/history validation runs after disposal.

The distinct proof kind is `complete-raw-production`. Historical production
Attempt 1 remains FAILED and Attempt 2 retains its single-query PASS. They are
supporting evidence, not failure predecessors for this proof kind. A post-launch
failure consumes its attempt and requires a newer freeze and fresh authorization.
The first future destination is exactly:
`artifacts/runtime/openttd-15.3-complete-raw-production-real-attempt1/`.
The first immutable freeze is:
`artifacts/runtime/openttd-15.3-complete-raw-production-real-prelaunch/`.

## Claim boundaries

Collection remains NON-ATOMIC and PRE-DECISION. Autonomous/external changes can
create snapshot drift during the longer session. Fresh-world seeded production
history remains ambiguous even with complete coverage. Observed rollovers are
zero and qualified_for_planning is false. Later planning qualification requires
a separately authorized two-rollover phase. There is no world lock, optimizer,
evaluation telemetry or P08 adaptation. Independent production source: NONE.
P08 completion: NO. Real combined execution and real same-run structural /
production provenance remain NOT YET PROVEN at preparation.
