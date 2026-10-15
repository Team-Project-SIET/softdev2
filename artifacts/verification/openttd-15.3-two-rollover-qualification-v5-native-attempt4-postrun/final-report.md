# Attempt 4 under V5 — final acceptance

OPENTTD 15.3 REAL TWO-ROLLOVER QUALIFICATION ATTEMPT 4 UNDER V5 PASSED — QUALIFIED PRODUCTION READY FOR P08 ADAPTER DESIGN

## Attempt

- freeze: /home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v5/PRELAUNCH.json
- attempt ID: two-rollover-qualification-v5-native-attempt4
- native attempt: 4
- checkpoint HEAD: cc7f7479e3fbfa8c036901ba041dee1b97dc6b42
- predecessors: Attempt 1 POST-LAUNCH FAILED; Attempt 2 POST-LAUNCH FAILED overall/native SUCCESS/offline FAIL; V3 PRELAUNCH FAILED 0/0/0; Attempt 3 under V4 POST-LAUNCH FAILED overall/native SUCCESS/offline PASS/endpoint cleanup FAIL
- authorization: Exactly one real launch explicitly authorized in this session; no retry, reconnect or resume

## Runtime

- launches: 1
- connections: 1 encrypted secure Admin
- retries: 0
- reconnects: 0
- duration: approximately 131.4 seconds, runtime evidence creation-to-finalization window; precise monotonic total not retained
- process continuity: YES
- connection continuity: YES
- runtime/world/config/bridge continuity: YES
- gameplay mutations: 0

## Economy

- M0: 1950-01-01 (native economy date 712223)
- rollover 1: 1950-02-01 (native economy date 712254); adjacent M0 → M1
- M1: February 1950
- rollover 2: 1950-03-01 (native economy date 712282); adjacent M1 → M2
- M2: March 1950
- final guard: 1950-03-02 (native economy date 712283); PASS
- qualified month: February 1950
- third rollover: NO

## M1 anchor

- structural digest: cb3986f04767359b76d6cefd8181b4830335665a2560316e014b9204ee7e7207
- industries: 10
- T1 count: 10
- L1 count: 9
- month coherence: PASS
- structural observation: COMPLETE
- target/lifetime identities: FINALIZED

## M2 final

- structural digest: cb3986f04767359b76d6cefd8181b4830335665a2560316e014b9204ee7e7207
- industries: 10
- T2 count: 10
- L2 count: 9
- month coherence: PASS
- structural observation: COMPLETE
- target/lifetime identities: FINALIZED

## Stability

- T1 == T2: YES
- target additions: 0
- target removals: 0
- lifetime changes: 0
- lifetime/fingerprint stability: PASS; construction dates remain CALENDAR identity

## Production

- targets: 10
- records: 10
- requests: 10
- response bytes: 2857
- production digest: f873858c6aba09802d22b07898412731dc66d376609447576ac47fbce4fded72
- complete: true
- qualified_for_planning: true
- source structural digest: cb3986f04767359b76d6cefd8181b4830335665a2560316e014b9204ee7e7207; EXACT final M2 digest
- fresh M2 capture: YES; each target once; M2 economy brackets coherent
- production_level: DEFERRED / NOT INCLUDED
- station allocation: Native station allocation; not vehicle pickup or delivered throughput

## Accounting

- clock requests: 115
- application requests: 185
- response bytes: 42054
- query operations: 740
- lifecycle frames: 6
- post-auth frames: 746
- ceilings: 304 / 1072 / 368080 / 9088 / 6 / 9094
- independent phase ceilings: PASS; one continuous accounting object; no reset or budget borrowing
- polling/deadline: 1 second / 300 seconds; unchanged

## Endpoint cleanup

- owned process reaped: YES; returncode 0, quit requested and reaped
- reservation released: YES
- game UDP closed: YES
- endpoint: 127.0.0.1 game TCP/UDP 44655; secure Admin TCP 32803
- address family: AF_INET
- LISTEN present: NO
- active connection present: NO
- TIME_WAIT present: YES; client tuple [{'inode': 0, 'local': '127.0.0.1', 'local_port': 52488, 'remote': '127.0.0.1', 'remote_port': 32803, 'state': 'TIME_WAIT', 'table': 'tcp'}]
- immediate rebind attempted: NO
- connection probe: NO
- endpoint verifier result: PASS; linux-kernel-endpoint-closure-v1
- arbitrary sleep/native retry: NONE

## Cleanup

- credential removed: YES; private bytes excluded from public evidence
- workspace disposed: YES
- source integrity: PASS
- historical integrity: PASS
- post-run integrity: PASS
- native semantics / receipts / liveness: PASS

## Post-consumption lineage

- Attempt 1 historical: PASS
- Attempt 2 historical: PASS
- Attempt 3 historical: PASS
- Attempt 4 historical: PASS
- V3 prelaunch historical: PASS; 0/0/0 remains PRELAUNCH
- Attempts 1–4 reusable: NO
- Attempt 4 reusable: NO
- next native attempt: 5
- historical vs next semantics: Independent; historical Attempt 4 matches V5 without deriving its successor

## Offline acceptance

- endpoint regressions: PASS
- lineage: PASS
- original V3 / retained Attempt 2 regressions: PASS
- focused optional skips: PostgreSQL live smoke; separately gated P03 native launch; standalone tagged Squirrel interpreter
- original regression batch: 155 passed, 1 skipped
- focused: 2015 passed, 3 skipped; 0 failures/errors
- ordinary: 2704 passed, 39 skipped; serial; 0 failures/errors
- post-consumption Attempt 4 tests: 3 passed; historical validator does not consult current history; reuse rejected; successor 5 preserves historical identity
- supplementary audit correction: Initial temporary test referenced nonexistent AttemptIdentity.native_attempt_id; validation itself passed. Corrected temporary assertion reads native ID from retained proof-evidence.json. Initial output retained in postconsumption-initial.log/xml; no source/freeze repair.
- quality: PASS
- overall final acceptance: PASS

## Claim boundary

- controlled qualification: PROVEN
- real execution: PROVEN
- qualified historical production: PROVEN
- complete production: PROVEN
- same-run provenance: PROVEN
- P08: NO
- atomic snapshot: NO
- independent source: NONE

## Historical integrity

- V1: PASS; byte-identical
- Attempt 1: PASS; byte-identical
- V2: PASS; byte-identical
- Attempt 2: PASS; byte-identical
- V3: PASS; byte-identical
- V4: PASS; byte-identical
- Attempt 3: PASS; byte-identical
- V5: PASS; byte-identical
- complete raw proof: PASS; byte-identical
- production Attempt 1/2: PASS; byte-identical
- CONTEXT.md: PASS; byte-identical
- Attempt 3 exact EADDRINUSE cause: UNKNOWN, unchanged; controlled TIME_WAIT reproduction does not prove original socket cause
- Attempt 3 overall / retained qualification: FAILED / qualified_for_planning=false; unchanged

## Tests

- endpoint: PASS (focused and serial ordinary suite)
- reservation: PASS (focused and serial ordinary suite)
- cleanup/lifecycle: PASS (focused and serial ordinary suite)
- lineage: PASS (focused and serial ordinary suite)
- prelaunch continuation: PASS (focused and serial ordinary suite)
- qualification: PASS (focused and serial ordinary suite)
- clock: PASS (focused and serial ordinary suite)
- lifetime: PASS (focused and serial ordinary suite)
- polling/accounting: PASS (focused and serial ordinary suite)
- coverage: PASS (focused and serial ordinary suite)
- production: PASS (focused and serial ordinary suite)
- structural/catalog/capability/inventory: PASS (focused and serial ordinary suite)
- bridge/protocol/transport: PASS (focused and serial ordinary suite)
- secure Admin: PASS (focused and serial ordinary suite)
- P03–P08: PASS (focused and serial ordinary suite)

## Quality

- Ruff: PASS
- format: PASS
- applicable proof/runtime/lineage typecheck: PASS
- git diff --check: PASS
- whitespace audit: PASS
- import boundary audit: PASS
- source changes during execution: NONE
- commit: NO
- push: NO

## Status

OPENTTD 15.3 REAL TWO-ROLLOVER QUALIFICATION ATTEMPT 4 UNDER V5 PASSED — QUALIFIED PRODUCTION READY FOR P08 ADAPTER DESIGN
