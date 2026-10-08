# Attempt

freeze: /home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v4/PRELAUNCH.json  
attempt ID: two-rollover-qualification-v4-native-attempt3  
native attempt number: 3  
checkpoint HEAD: cc7f7479e3fbfa8c036901ba041dee1b97dc6b42  
runtime destination: /home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-two-rollover-qualification-real-attempt3  
predecessors: two-rollover-qualification-v1-runtime-b045142a46c304ba, two-rollover-qualification-v2-runtime-c2f8823bfa845c97, two-rollover-qualification-v3-prelaunch-b6c114daf6106fc7  
authorization: exactly one fresh real native Attempt 3 under V4; consumed by this run

# Prelaunch

Attempt 1 historical: PASS; consumed, nonreusable  
Attempt 2 historical: PASS; consumed, nonreusable; overall FAILED retained  
V3 prelaunch historical: PASS, exact 0/0/0, native Attempt 3 not consumed by V3  
Attempt 3 consumed before launch: NO  
next executable before launch: Attempt 3  
READY_TO_LAUNCH: YES (guarded public CLI preflight, no subprocess/connection/request)  
HEAD, source/input identities, protected history, archived credentials, V4 fresh credential 0600,
secure configuration, binary, graphics, bridge, authority, ownership, polling and accounting: PASS.
All limits matched the requested frozen contract.

# Runtime

launches: 1  
connections: 1, encrypted X25519 AuthorizedKey / Admin Protocol 3  
retries: 0  
reconnects: 0  
resume: NO  
duration: approximately 131.2 seconds between initial retained run authority and final proof evidence (file-time estimate; native duration not independently recorded)  
process continuity: YES, M0 through final M2 guard  
connection continuity: YES, M0 through final M2 guard  
runtime/world/config/bridge continuity: PASS  
gameplay mutations: 0

# Economy timeline

M0: January 1, 1950, economy ordinal 712223  
rollover 1: February 1, 1950, ordinal 712254; observed adjacent  
M1: February 1950  
rollover 2: March 1, 1950, ordinal 712282; observed adjacent  
M2: March 1950  
final guard: March 2, 1950, ordinal 712283; PASS  
third rollover: NO  
qualified month bounded by native evidence: February 1950 (M1)

# M1 anchor

structural digest: cb3986f04767359b76d6cefd8181b4830335665a2560316e014b9204ee7e7207  
industries: 10  
T1 count: 10  
L1 count: 9  
month coherence: PASS

# M2 final

structural digest: cb3986f04767359b76d6cefd8181b4830335665a2560316e014b9204ee7e7207  
industries: 10  
T2 count: 10  
L2 count: 9  
month coherence: PASS; fresh M2 collection

# Stability

T1 == T2: YES  
target additions: 0  
target removals: 0  
lifetime/fingerprint changes: 0; exact construction identity and structural equality  
lifetime construction authority: CALENDAR identity, not economy qualification boundaries

# Production

targets: 10  
records: 10, freshly collected in M2  
requests: 10  
response bytes: 2857  
source structural digest: exact final M2 digest  
production digest: NOT RETAINED by failed public attempt; not reconstructed  
native collection complete: YES (semantic_evidence.production.complete=true)  
coordinator qualification: validated and QUALIFIED_OBSERVATION_ASSEMBLED before cleanup  
retained public complete: false  
retained public qualified_for_planning: false  
production_level: DEFERRED / NOT INCLUDED  
station allocation: native allocation semantics; not pickup/delivery/destination throughput

The failed public retention path ties complete/qualified fields and canonical digest emission
to lifecycle acceptance. The ten records, validated semantic exchanges, stability gates and
qualification-completion events remain retained. No canonical qualified observation or
qualified-month artifact was emitted after the cleanup failure. Those missing acceptance
artifacts were not regenerated, and the failed native report was not rewritten.

# Accounting

clock requests: 115 / 304  
application requests: 185 / 1072  
response bytes: 42054 / 368080  
query operations: 740 / 9088  
lifecycle frames: 6 / 6  
post-auth frames: 746 / 9094  
phase budgets: all PASS; continuous shared object, no reset/transfer  
polling: 1 second; overall deadline 300 seconds; unchanged

# Native result

qualification coordinator semantic execution: SUCCESS, phase COMPLETED, failure=null  
qualified observation: assembled in coordinator; final admission NOT RETAINED  
public qualification lifecycle: FAILED after PROCESS_REAPED, before ENDPOINTS_CLOSED  
cleanup: FAILED, [Errno 98] Address already in use  
public post-run integrity gate: NOT REACHED (source_integrity=false)  
independent post-run source/historical verification: PASS  
receipts, typed semantic validation and post-response liveness: PASS for all 185 requests

The cleanup endpoint verification in raw_production_attempt calls
EndpointReservation.allocate on the frozen game/Admin ports after a successful process reap.
That bind-only check raised EADDRINUSE. A read-only socket listing immediately afterward
showed Admin port 39807 in TIME-WAIT, with no owned listener or established
connection. This is consistent with the bind test rejecting TCP TIME-WAIT, rather than a
remaining OpenTTD process. The preserved public evidence records the error, not a traceback;
no implementation was changed or runtime retried to test an alternative cleanup policy.

# Post-consumption lineage

Attempt 1 historical: PASS  
Attempt 2 historical: PASS  
V3 historical: PASS, PRELAUNCH 0/0/0 unchanged  
Attempt 3 historical: PASS against its own immutable V4  
Attempt 1 reusable: NO  
Attempt 2 reusable: NO  
Attempt 3 reusable: NO  
next native attempt: Attempt 4, derived conceptually with a future revision  
new freeze: NONE created; no future native execution authorized

# Offline acceptance

original V3 regressions: PASS, both isolated; original Attempt 2 lineage regression PASS  
V4 lineage and prelaunch continuation: PASS  
controlled Attempt 3 consumption / historical-vs-next: PASS  
focused suite: 1985 passed, 3 skipped, 0 failures/errors  
ordinary suite: 2674 passed, 39 skipped, 0 failures/errors, serial, no native/Postgres opt-in flags  
offline verification: PASS  
overall final proof acceptance: FAILED due public cleanup gate

# Cleanup

process reaped: YES; graceful quit, returncode 0, no remaining owned processes  
endpoints: no owned LISTEN/ESTABLISHED sockets observed; public immediate rebind gate FAILED  
credential removed: YES, public finally removed it  
workspace disposed: YES by supplemental ownership-validated disposal after public failure  
source integrity: PASS independently, 254 frozen inputs exact  
historical integrity: PASS independently, 1627 protected public files and 8 archived credential identities exact  
supplemental activity: 0 launches / 0 connections / 0 requests

Supplemental disposal used the retained ownership authority and existing cleanup API only.
It did not resume/retry execution or alter the failed lifecycle/evidence. The authorized
runtime-owned ephemeral workspace was removed; persistent V4 documents remain exact.

# Claim boundary

controlled qualification: PROVEN by controlled tests  
real two-rollover execution: native semantic sequence observed successfully; final proof NOT ACCEPTED  
qualified historical production: coordinator validation observed; planning admission NOT ACCEPTED  
complete production: ten-target native coverage observed; retained public complete=false  
same-run provenance: validated throughout native sequence  
P08: NO  
atomic snapshot: NO  
independent source: NONE

# Historical integrity

V1: byte-identical  
Attempt 1: byte-identical  
V2: byte-identical  
Attempt 2: byte-identical; native success and offline failure unchanged  
V3: byte-identical; PRELAUNCH 0/0/0 and failure report unchanged  
V4: persistent freeze documents/materialization templates byte-identical; authorized ephemeral workspace disposed  
complete raw proof: byte-identical  
production Attempt 1: byte-identical  
production Attempt 2: byte-identical  
CONTEXT.md: byte-identical  
Attempt 3 generated runtime evidence: manifest exact, unchanged through offline verification

# Tests

original V3 failures + original Attempt 2 regression: 3 passed, 0 skipped, 0 failures/errors  
post-consumption targeted cases: 7 passed, 0 skipped, 0 failures/errors  
lineage: PASS  
qualification preparation/coordinator: PASS  
clock: PASS  
lifetime: PASS  
polling/accounting: PASS  
complete raw coverage: PASS  
production and retained Attempt 1/2 regressions: PASS  
cleanup/lifecycle controlled tests: PASS; real public cleanup failed as recorded above  
structural/catalog/capability/inventory: PASS  
bridge/protocol/transport/secure Admin: PASS  
P03-P08 controlled regressions: PASS  
ordinary: 2674 passed, 39 skipped, 0 failures/errors

Optional real-runtime integrations were skipped; offline suites did not launch OpenTTD.
JUnit XML, exact focused file selection, public CLI logs, historical audits and supplemental
cleanup evidence are retained beside this report. No source changes, commits or pushes.

# Quality

Ruff: PASS  
format: PASS, 337 files already formatted  
typecheck: PASS, lineage/preparation plus qualification/session/accounting/transport scope  
diff: PASS  
whitespace: PASS on qualification/lineage sources and regression files  
import boundary: PASS, no planning/evaluation imports in audited qualification/lineage modules

# Status

OPENTTD 15.3 REAL TWO-ROLLOVER QUALIFICATION ATTEMPT 3 UNDER V4 FAILED — NO RETRY PERFORMED — cleanup endpoint rebind failed with EADDRINUSE after process reap
