# Failure diagnosis

V3 classification: PRELAUNCH FAILED — native Attempt 3 NOT consumed.  
runtime activity: 0 launches / 0 secure Admin connections / 0 real requests  
failing tests: tests/test_historical_attempt_lineage.py::test_current_next_attempt_preserves_frozen_identity
and ::test_next_attempt_requires_new_freeze  
root cause: tests intended current pre-execution derivation but read externally mutable
live history; the archived replay supplied three consumed native attempts while the
first test still requested destination Attempt 3 and asserted next native attempt 3.
The second test requested the same consumed destination but expected the newer-freeze
error instead of consumed-destination rejection.

First controlled reproduction: 2 failed in 0.11 seconds. Calls:
original frozen test → derive_next_attempt → capture_lineage → validate_lineage.
The supplied temporary history had Attempts 1 and 2 FAILED, Attempt 3 REAL_SUCCESS
with one launch/connection; all were consumed. Computed identity was
`two-rollover-qualification-v3-native-attempt4`; requested destination remained
`...real-attempt3`. Actual error: `Attempt destination already consumed; exact new
attempt destination required`. The second test expected error text `Newer freeze`.
No assertions requiring Attempt 3 as executable should be made in that consumed state.

Direct original tests on actual history after V3's gate failure: one failed with
`Newer freeze required; same-freeze reauthorization forbidden`; one passed. This is
consistent with the recorded V3 prelaunch failure requiring V4 while retaining native 3.

Classification: TEST CONTRACT BUG, plus a separately proven shared LINEAGE IMPLEMENTATION BUG.
The corrected tests isolate current and post-consumption lifecycle contexts. A minimal
single-consumed-attempt probe showed that failed consumption derived the next identity,
but successful consumption was rejected by the failure-only predecessor condition.
New tests failed four success cases before the implementation repair, while 30 cases passed.

The implementation repair changes that condition in qualification_lineage,
production_lineage and raw_production_lineage to recognize immutable terminal SUCCESS
as well as FAILURE as consumed runtime history. It retains exact identity/digest,
launch-count, newer-freeze, destination, complete-current-history and fresh-authorization
checks. No force/ignore parameter exists. Successful native terminal metadata is not
relabeled overall PASS. Qualification predecessor metadata now marks native failure
only for failed native status and preserves true post-launch failure when mandatory
offline verification failed, including Attempt 2's exact existing row.

Hypotheses tested: fixture lifecycle confusion (confirmed), failure-only terminal
consumption condition (confirmed), prelaunch failure incorrectly incrementing native
number (disproved). Exact real history already derived V4/native 3 before source edits.

# Lifecycle-context audit

| Occurrence | Context | Correct expectation |
| --- | --- | --- |
| current_next_attempt_preserves_frozen_identity | Isolated 1/2 consumed + V3 prelaunch failed; native 3 absent | V4/native 3; unchanged frozen V2 |
| next_attempt_requires_new_freeze | Same pre-execution history; unused destination 3, revision 3 is stale | Newer freeze rejection |
| wrong_destination cases 2/4/other | Before native 3 consumption | Reject; correct destination is 3 |
| controlled_consumption_separates_history_and_next | Only native 1/2 consumed | Native 3 |
| qualification preparation identity | Fresh controlled preparation before native 3 | V4/native 3 |
| after_attempt3_consumption_next_is_attempt4 | Controlled native 3 consumed, SUCCESS and FAILED variants | Historical 3 PASS; reuse NO; next native 4 |
| historical_attempt3_after_consumption_never_derives_next | Retained controlled V4/native 3 evidence | Historical 3 PASS without current history discovery |
| V3 retained prelaunch identity | Historical immutable 0/0/0 failure | PRELAUNCH; never counted as consumed native 3 |

There was no global replacement of native 3 with 4. Freeze revision and native attempt
number are separate. The archived original replay command now passes both repaired
tests because their intended pre-execution fixtures are self-contained; explicit new
post-consumption tests independently assert native 4 and prevent false confidence.

# Lineage semantics

before Attempt 3 consumption: real history has native 1/2 consumed and V3 prelaunch 0/0/0  
next executable: native Attempt 3 under V4, pending fresh authorization

after simulated Attempt 3 consumption: controlled temporary history only  
historical Attempt 3: PASS for successful and failed terminal results  
Attempt 3 reusable: NO  
next executable: native Attempt 4 under a newer controlled freeze (V5 in fixtures)

Historical validation binds proof kind, creating freeze/contract, native attempt ID,
destination, frozen predecessor lineage, terminal result, recursive evidence digest
and parent identities. A test makes both discovery and next derivation fatal during
historical validation, then validates consumed Attempt 3 successfully. Next derivation
also preserves the frozen identity bytes. Temporary simulated evidence never enters
actual repository runtime history. No V5 repository freeze was created.

# Attempt numbering

V3 native Attempt 3 consumed: NO  
V4 native attempt: Attempt 3  
reason: only native launches consume native numbers; V3 has exact 0/0/0 activity.
V3 is superseded as a prelaunch contract predecessor. The original native Attempt 3
destination remains absent/unused and is retained for the fresh V4 preparation.

The existing hardened rule supports a newer freeze for the same unexecuted native
attempt, with exact predecessor evidence and fresh authorization. The global
prelaunch-only continuation exception flag remains false because earlier native
Attempts 1/2 were post-launch; this does not change the zero launch count of V3.

# Contracts

polling: unchanged — 1 second / 300 seconds / 304 clocks  
requests: unchanged — 1072 ceiling  
response bytes: unchanged — 368080 ceiling  
query operations: unchanged — 9088 ceiling  
frames: unchanged — 6 deterministic lifecycle / 9094 total post-auth  
qualification: unchanged — M0→M1→M2, T1==T2, lifetime stability, fresh M2 production,
final M2 guard, production_level exclusion, P08 boundary  
dispatch: unchanged — RawObservationBridge.Handle.call(this, request)

Comparing the entire current qualification contract to frozen V3 shows exactly one
changed field: revision 3→4. Runtime destination remains native Attempt 3. All budgets,
phase bounds, authority semantics and dispatch fields are exact.

# V4

freeze: artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v4/PRELAUNCH.json  
attempt ID: two-rollover-qualification-v4-native-attempt3  
native attempt number: 3  
future destination: /home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-two-rollover-qualification-real-attempt3  
predecessors: native Attempt 1 POST-LAUNCH FAILED; native Attempt 2 POST-LAUNCH overall
FAILED (native SUCCESS/offline FAILED); V3 PRELAUNCH FAILED, exact 0/0/0  
fresh authorization required: YES

Exact V3 failure evidence digest: 6eb645197fb9fae0412604f3854ccfab3656a09987641c6d1c316b707bff9d00  
Exact V3 failure manifest digest: fe378550637cb6cd244d37f997cb20324d1df2de2fe5668924c54d7ea3e7af45  
Lineage digest: 7bcd4084b3d45e35e3c08abc853513d54cfccccb423cab9054696bde1ce4357d  
Protected manifest: ee1616548b0ce80b02371cbcf853e2c1d57e7cda7922078fdbc1de4843ab1270  
Bridge digest: d8b263ec580fe4f0f4bd96007da168ddc4d96a2b1b5d502b912f335026d711b3  
Proof configuration digest: 101f60d0ad6b8eaf02f08b49473661ec7557309b0bb86be8d78094c14d7925bf  
Accounting identity: 4762117cfecc1026b1a7ab661baa5fadd7ef55fa101f1ee408e9d0bab4ef12c6  
Polling policy digest: a56c1d383a90fe8827d68c15b830041a6111c385b81d93f0b10326a4e6b1faab

Fresh V4 credential generated after noncredential gates, mode 0600, distinct from V3
and every archived identity. Private bytes excluded from public evidence. V4's
lineage-context.json labels real pre-execution state separately from simulated
post-consumption state.

# Guarded preflight

Attempt 1 historical: YES  
Attempt 2 historical: YES  
V3 prelaunch: YES — exact immutable identity and 0/0/0  
Attempt 3 consumed: NO  
next executable: native Attempt 3  
Attempt 3 destination accepted for V4: YES  
READY_TO_LAUNCH: YES  
subprocess: NO  
Admin: NO  
request: NO

Only public prepare/preflight paths used. Subprocess and socket.connect audit guards
were installed throughout preparation/preflight. Public qualification, ownership,
native authority, polling/accounting, secure Admin configuration, exact destination,
EndpointReservation.allocate and final subprocess-boundary checks all passed.
No native execution is authorized by this readiness report.

# Controlled post-consumption regression

Attempt 3 historical validation: PASS, both SUCCESS and FAILED  
Attempt 3 reuse: rejected  
next attempt: native Attempt 4  
real runtime history mutation by simulated cases: NONE

# Historical integrity

V1: byte-identical  
Attempt 1: byte-identical  
V2: byte-identical  
Attempt 2: byte-identical, including failed mandatory offline acceptance  
V3: byte-identical  
V3 prelaunch failure evidence/report: byte-identical  
complete raw proof: byte-identical  
production Attempt 1/2: byte-identical  
CONTEXT.md: byte-identical

All 1627 captured public files and existing historical file sets are exact. The
V3 protected-history authority validates its 1565 public files and archived credentials.
The source audit permits exactly six changed files: three lineage validators,
qualification_contract, test_historical_attempt_lineage, test_qualification_preparation.
Native qualification, accounting, polling, clock/lifetime and bridge sources are exact.

# Tests

original failures: 2 isolated tests PASS; archived controlled replay 2 PASS  
lineage: all focused lineage regressions PASS  
prelaunch continuation: current 1/2/V3→native 3 matrix PASS  
qualification: preparation/coordinator/clock/lifetime/polling/accounting PASS  
complete raw coverage and production regressions: PASS  
cleanup/lifecycle: PASS  
structural/catalog/capability/inventory: PASS  
bridge/protocol/transport/secure Admin: PASS  
P03-P08: controlled regressions PASS; optional native integration tests skipped  
focused: 1985 passed, 3 skipped  
ordinary: 2674 passed, 39 skipped (serial, no native flags/xdist)

Ruff PASS; format PASS; scoped typecheck PASS; git diff --check PASS; whitespace PASS;
import-boundary PASS. No debug instrumentation. Controlled verification artifacts,
reproduction scripts and logs are retained here. No commit or push.

# Runtime activity

launches: 0  
connections: 0  
requests: 0

# Status

READY TO REQUEST FRESH AUTHORIZATION FOR OPENTTD 15.3 TWO-ROLLOVER QUALIFICATION ATTEMPT 3 UNDER V4
