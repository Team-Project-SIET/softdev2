# Attempt

attempt: two-rollover-qualification-v3-native-attempt3  
freeze: /home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v3/PRELAUNCH.json  
predecessors: consumed native Attempts 1 and 2; both overall FAILED  
fresh authorization: received for exactly one native Attempt 3; stopped before launch

Failure classification: PRELAUNCH / ACCEPTANCE-READINESS VALIDATION FAILED.
The native destination was never created. No native Attempt 3 was consumed.

# Prelaunch validation and blocker

HEAD cc7f7479e3fbfa8c036901ba041dee1b97dc6b42 matches V3. Source/input identities (254), protected public
historical identities (1565), seven archived credential identities, V1/V2 identities,
Attempt 1/2 historical validation, consumed predecessor protection, next identity
Attempt 3, exact destination, bridge/qualification/polling/accounting authority,
binary/OpenGFX/GameScript/native production/economy/lifetime authority, cleanup ownership,
fresh credential mode 0600/private-byte exclusion, secure Admin configuration and
loopback EndpointReservation all validated. Public CLI guarded preflight reached
READY_TO_LAUNCH with subprocess creation blocked and no process/connection/request.

A further read-only acceptance-readiness check replayed the exact frozen regression
functions against temporary controlled history containing consumed Attempts 1/2/3.
This did not create, modify, or simulate native evidence in the repository authority.
Two deterministic failures appeared twice, each replay in 0.09 seconds:

- tests/test_historical_attempt_lineage.py::test_current_next_attempt_preserves_frozen_identity
  still requests revision 3/destination attempt3 and expects next=3. With three consumed
  launches the real helper derives native-attempt4, then correctly rejects destination
  attempt3 as consumed, before the test assertions.
- tests/test_historical_attempt_lineage.py::test_next_attempt_requires_new_freeze
  still requests attempt3 and expects error text `Newer freeze`; consumed-destination
  protection correctly reports `Attempt destination already consumed; exact new attempt
  destination required`.

Current real history's original Attempt 2 regression and new historical/next tests:
25 PASSED. They do not establish the required post-consumption acceptance condition.
The earlier V3 readiness assessment missed this test-isolation defect. Launching under
this unchanged freeze would not satisfy the mandatory final regression gate.

Stack: frozen test → derive_next_attempt → capture_lineage → validate_lineage →
unconditional consumed-destination rejection. Historical validation was not weakened.
No source repair, frozen-value regeneration, credential replacement, V3 modification,
V4 creation, alternate proof mode, native retry, commit or push occurred.

# Runtime

launches: 0  
connections: 0  
retries: 0  
reconnects: 0  
duration: N/A — native execution not started  
process continuity: N/A  
connection continuity: N/A  
resume: NO

# Economy

M0: NOT OBSERVED  
rollover 1: NOT OBSERVED  
M1: NOT OBSERVED  
rollover 2: NOT OBSERVED  
M2: NOT OBSERVED  
final guard: NOT RUN  
qualified month: NONE  
third rollover: N/A

# M1 anchor

structural digest: NONE  
industries: N/A  
T1 count: N/A  
L1 count: N/A  
month coherence: NOT ASSESSED

# M2 final structure

structural digest: NONE  
industries: N/A  
T2 count: N/A  
L2 count: N/A  
month coherence: NOT ASSESSED

# Stability

T1 == T2: NOT ASSESSED  
target additions: NOT ASSESSED  
target removals: NOT ASSESSED  
lifetime changes: NOT ASSESSED

# Final production

targets: N/A  
records: 0  
requests: 0  
response bytes: 0  
production digest: NONE  
complete: no observation produced  
qualified_for_planning: no observation produced

Attempt 2's truthful native SUCCESS and qualified historical observation remain
unchanged. They were not reused or attributed to Attempt 3.

# Accounting

clock requests: 0  
application requests: 0  
response bytes: 0  
query operations: 0  
lifecycle frames: 0  
post-auth frames: 0

Frozen ceilings unchanged: 304 / 1072 / 368080 / 9088 / 6 / 9094.
Frozen poll interval 1 second; deadline 300 seconds. No semantic/accounting changes.

# Native result

runtime semantic execution: NOT STARTED  
qualified observation: NONE  
cleanup: no native cleanup required  
post-run integrity: N/A; prelaunch/final source and historical integrity PASS

# Offline acceptance

original Attempt 2 lineage regression: PASS  
historical Attempt 1: PASS  
historical Attempt 2: PASS  
historical Attempt 3: N/A — no native Attempt 3 exists; recorded PRELAUNCH identity validates  
consumed-attempt reuse protection: PASS for Attempts 1/2; controlled consumed 3 rejected  
next-attempt derivation separation: current historical APIs pass; two frozen regression
fixtures fail when testing after controlled consumption of Attempt 3  
focused suite: full post-run suite NOT RUN — launch stopped  
ordinary suite: post-run suite NOT RUN — launch stopped  
overall final acceptance: FAILED before launch

# Cleanup

process reaped: N/A — no process created  
endpoints closed: YES — guarded preflight reservation closed  
credential removed: NO — unused original V3 credential retained unchanged, mode 0600  
workspace disposed: NO — no native runtime began; original V3 preparation retained  
integrity: PASS

# Claim boundary

controlled qualification: prior controlled proof retained; no new native claim  
real execution: NOT PERFORMED for Attempt 3  
qualified history: NOT PRODUCED by Attempt 3  
complete production: NOT PRODUCED by Attempt 3  
same-run provenance: N/A  
P08: NO  
atomic snapshot: NO  
independent source: NONE  
gameplay mutations: 0

# Historical integrity

V1: EXACT  
Attempt 1: EXACT  
V2: EXACT  
Attempt 2: EXACT, including overall failed offline acceptance  
V3: EXACT, public freeze/file set/source identities and unused original credential  
complete raw proof: EXACT  
production Attempt 1: EXACT  
production Attempt 2: EXACT  
CONTEXT.md: EXACT

Frozen protected-history validation covers 1565 public files and seven archived
credential identities. V3's public bytes/file set remain identical to the prelaunch
snapshot. The new sibling gate-failure record is a separate immutable outcome, not a
rewrite of V3. V3 now fails current-history execution eligibility due to its recorded
prelaunch failure: `Unknown, unacknowledged, or missing predecessor failure`. No further execution is authorized.

# Tests

lineage: 25 current-history checks PASS; 2 controlled prospective failures repeated twice  
qualification: public frozen validation PASS; native/post-run tests NOT RUN  
clock: frozen authority/contract validation PASS; runtime NOT RUN  
lifetime: frozen authority validation PASS; runtime NOT RUN  
polling/accounting: frozen public preflight PASS; runtime NOT RUN  
coverage: post-run suite NOT RUN  
production: frozen authority validation PASS; runtime/post-run suite NOT RUN  
cleanup/lifecycle: owner/preflight PASS; native cleanup NOT REQUIRED  
structural: frozen bridge/authority loaded; runtime NOT RUN  
bridge: digest/dispatch identity PASS; no requests sent  
P03-P08: no additional runtime or post-run suites under this stopped attempt  
ordinary: NOT RUN — no native execution reached post-run verification

# Quality

Ruff: PASS  
format: PASS  
typecheck: PASS (scoped qualification/lineage modules and tests)  
diff: PASS  
whitespace: PASS  
import boundary: PASS

# Evidence

Repository-convention immutable prelaunch failure: /home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v3-gate-failure.
Controlled replay logs, XML, scripts, public preflight output, validation and final
integrity audit: this directory. Native Attempt 3 destination remains unused.

# Status

OPENTTD 15.3 REAL TWO-ROLLOVER QUALIFICATION ATTEMPT 3 FAILED — NO RETRY PERFORMED — prelaunch controlled replay exposed two V3-frozen regressions that reject consumed Attempt 3
