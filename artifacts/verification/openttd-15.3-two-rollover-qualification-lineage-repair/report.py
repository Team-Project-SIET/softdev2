import json
import shutil
from pathlib import Path
from xml.etree import ElementTree

root=Path('/tmp/qualification-lineage-verification')
out=Path('artifacts/verification/openttd-15.3-two-rollover-qualification-lineage-repair')
out.mkdir(parents=True,exist_ok=True)
for p in root.iterdir():
    if p.is_file():
        shutil.copyfile(p,out/p.name)

def counts(name):
    suite=ElementTree.parse(root/(name+'.xml')).getroot().find('testsuite')
    return f"{int(suite.attrib['tests'])-int(suite.attrib['skipped'])} passed, {suite.attrib['skipped']} skipped; failures={suite.attrib['failures']}, errors={suite.attrib['errors']}"

freeze=Path('artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v3')
meta=json.loads((freeze/'PRELAUNCH.json').read_text())
preflight=json.loads((root/'v3-preflight.json').read_text())
lineage=json.loads((freeze/'attempt-lineage.json').read_text())
rows=lineage['post_launch_predecessors']
digests='\n'.join(f"- {r['native_attempt_id']}: native evidence `{r['evidence_digest']}`; native manifest `{r['evidence_manifest_digest']}`" for r in rows)
report=f'''# Failure classification

Attempt: two-rollover-qualification-v2-native-attempt2  
overall: FAILED  
native runtime: SUCCESS / COMPLETED  
qualification observation: complete=true, qualified_for_planning=true  
cleanup: PASS; runtime post-run integrity PASS  
offline verification: FAIL; failure phase POST-RUN OFFLINE VERIFICATION

# Failing regression

test: tests/test_qualification_dispatch_repair.py::test_new_lineage_requires_revision_two_attempt_two_and_runtime_predecessor  
expected: two-rollover-qualification-v2-native-attempt2  
actual: capture computed two-rollover-qualification-v2-native-attempt3, then raised
ValueError: Post-launch failure requires exact new attempt destination.  
isolated reproduction: failed before edits; final isolated test PASS.

# Root cause

historical validation semantics: validate retained evidence against its exact creating
freeze and frozen predecessor set, without current-next discovery.  
next-attempt derivation semantics: discover both consumed launches, derive Attempt 3,
and require a newer freeze and exact unused destination.  
conflation: C — BOTH / INVALID API DESIGN; regression test called next-derivation API
for retained historical identity, and execution validator coupled frozen identity to
current discovery.  
shared impact: seven duplicated lineage validators separated consistently; ACK,
world-info, inventory and single capability observation retain their distinct gates.

See [detailed diagnosis and API/caller audit](two-rollover-qualification-lineage-repair.md).

# Repair

modules: enrichment_lineage, cargo_page_lineage, catalog_lineage, structural_lineage,
production_lineage, raw_production_lineage, qualification_lineage; offline_verification;
qualification_contract/preparation and regression tests.  
historical API: validate_historical_lineage / validate_historical_attempt  
next-attempt API: derive_next_attempt (capture_lineage compatibility entry)  
consumed-attempt safety: unconditional execution rejection of consumed destinations  
execution safety: complete current-history matching, newer freeze, exact new destination,
fresh credential, fresh explicit authorization, no force/ignore parameter

# Attempt 2 status

native M0→M2: SUCCESS (January 1950 → February 1 → March 1; final guard March 2)  
qualified observation: PRESENT  
qualified_for_planning: true  
offline acceptance: FAILED  
overall: FAILED

REAL NATIVE TWO-ROLLOVER QUALIFICATION EXECUTION COMPLETED SUCCESSFULLY AND PRODUCED A
QUALIFIED OBSERVATION BEFORE FINAL OFFLINE ACCEPTANCE FAILED. Project proof remains FAILED.

# Next lineage

next attempt: Attempt 3  
next freeze: V3  
future destination: {meta['attempt_directory']}  
predecessors: BOTH consumed Attempts 1 and 2  
fresh authorization: REQUIRED; no prelaunch continuation exception

Attempt 1: POST-LAUNCH FAILED; unsupported Squirrel base.Handle dispatch.
Attempt 2: POST-LAUNCH overall FAILED; native qualification SUCCESS; mandatory offline
verification FAILED; historical/current-next lineage regression. V3 lineage-context.json
binds these separate outcomes and their supporting authority. Exact native evidence:

{digests}

Attempt 2's immutable offline manifest, XML verdicts and report digests are additionally
bound in its V3 predecessor row. Historical evidence and destination names are unchanged.

# Contracts unchanged

polling: 1 second; 300-second deadline; 304 max clocks  
requests: 1072  
response bytes: 368080  
query operations: 9088  
frames: 9094 post-auth  
qualification semantics: M0/M1/M2, T1==T2, lifetime stability, fresh M2 production,
final M2 guard, production_level exclusion and P08 boundary unchanged

# V3

freeze: {freeze}/PRELAUNCH.json  
attempt ID: {meta['attempt_id']}  
future destination: {meta['attempt_directory']}  
protected manifest: {meta['protected_manifest_sha256']}  
lineage digest: {meta['lineage_digest']}  
bridge digest: {meta['bridge_digest']}  
proof-config digest: {meta['proof_config_sha256']}  
accounting digest: {meta['frame_accounting_identity']}  
polling digest: {meta['polling_policy_digest']}

Fresh credential: generated after noncredential gates; mode 0600; distinct from archived
Attempt 2 identity; private bytes excluded from public artifacts.

# Guarded preflight

historical Attempt 1 validates: YES  
historical Attempt 2 validates: YES  
Attempt 2 reusable: NO  
next attempt: Attempt 3  
READY_TO_LAUNCH: YES  
subprocess: NO; unconditional subprocess audit guard installed  
Admin: NO; unconditional socket.connect audit guard installed  
request: NO

Public prepare/preflight paths used. V3 loads its qualification contract, accounting,
polling, ownership, secure Admin config; EndpointReservation.allocate resolves; final
subprocess boundary validates. Future native execution remains unauthorized.

# Historical integrity

Attempt 1: byte-identical  
Attempt 2: byte-identical, including mandatory failed post-run verification  
V2: byte-identical  
complete raw proof: byte-identical  
production Attempts 1/2 and earlier proof history: byte-identical  
CONTEXT.md: byte-identical

All 1,565 captured public files and existing historical directory file sets exact.
V2's 1,461 protected files and archived credential public identities/modes validate.
No historical evidence restored or rewritten.

# Tests

original failing: 1 passed  
lineage: new 24-case file PASS; existing lineage regressions PASS  
qualification: PASS  
proof: PASS, including complete raw and production Attempt 1/2 regressions  
cleanup: PASS  
P03-P08: controlled suites PASS; authorized native tests skipped  
focused final: {counts('focused-final')}  
ordinary final (serial, no xdist/native flags): {counts('ordinary-final')}

Ruff PASS; format PASS; scoped typecheck PASS; git diff --check PASS; whitespace PASS;
import-boundary PASS; no debug instrumentation. First intermediate broad run retained
its expected error-message compatibility failure; an intermediate ordinary run also
caught source editing during a controlled integrity check. Final stable reruns passed.
The separate isolated enrichment lifecycle rerun passed all three cases.

# Runtime activity

launches: 0  
connections: 0  
real requests: 0

No OpenTTD launch, AdminPort connection, real request, Attempt 2 retry, commit or push.

# Status

READY TO REQUEST FRESH AUTHORIZATION FOR OPENTTD 15.3 TWO-ROLLOVER QUALIFICATION ATTEMPT 3
'''
Path('docs/two-rollover-qualification-attempt3-readiness.md').write_text(report)
(out/'final-report.md').write_text(report.replace('(two-rollover-qualification-lineage-repair.md)', '(../../../docs/two-rollover-qualification-lineage-repair.md)'))
from app.simulation.openttd.proof.harness import manifest
(out/'artifact-manifest.sha256').write_text(manifest(out))
print('Report and controlled verification artifacts retained:',out)
