"""Offline public preparation/preflight, with unconditional process/connect guards."""
import contextlib
import io
import json
import sys
from pathlib import Path


def guard(event, arguments):
    if event in ('subprocess.Popen', 'socket.connect'):
        raise PermissionError('Offline repair: subprocess and connection prohibited')

sys.addaudithook(guard)
from app.simulation.openttd.proof import __main__ as cli
from app.simulation.openttd.proof.qualification_contract import PRELAUNCH_DIRECTORY, ATTEMPT_DIRECTORY, KIND
from app.simulation.openttd.proof.qualification_lineage import validate_historical_attempt, derive_next_attempt
from app.simulation.openttd.proof.harness import PROJECT, manifest, write_json, sha256
from app.simulation.openttd.proof.native import load_prepared

root=PROJECT/'artifacts/runtime'
freeze=root/PRELAUNCH_DIRECTORY
destination=root/ATTEMPT_DIRECTORY
for number in (1,2):
    old=root/('openttd-15.3-two-rollover-qualification-real-prelaunch'+('' if number==1 else '-v2'))
    identity=validate_historical_attempt(old,root/f'openttd-15.3-two-rollover-qualification-real-attempt{number}')
    assert identity.launches==identity.connections==1
next_identity=derive_next_attempt(freeze,3,destination)
assert next_identity['attempt_number']==3
assert not next_identity['prelaunch_continuation_exception_used']
assert next_identity['fresh_explicit_authorization_required']
assert not destination.exists()
sys.argv=['proof','prepare','--mode',KIND,'--directory',str(freeze)]
cli.main()
write_json(freeze/'lineage-context.json', dict(
    attempt1=dict(
        overall='FAILED', failure_phase='POST_LAUNCH',
        root_cause='Unsupported Squirrel base.Handle dispatch',
        diagnosis='docs/two-rollover-qualification-attempt1-diagnosis.md',
        diagnosis_digest=sha256(PROJECT/'docs/two-rollover-qualification-attempt1-diagnosis.md'),
    ),
    attempt2=dict(
        overall='FAILED', failure_phase='POST_RUN_OFFLINE_VERIFICATION',
        native_runtime='SUCCESS', native_lifecycle='COMPLETED',
        qualification_complete=True, qualified_for_planning=True,
        cleanup='PASS', offline_verification='FAILED',
        root_cause='Historical V2/Attempt 2 regression recaptured current next-execution lineage after consumption',
        verification_digest=sha256(root/'openttd-15.3-two-rollover-qualification-real-attempt2-postrun-verification/verification.json'),
    ),
    predecessors=next_identity['post_launch_predecessors'],
    authorization='Fresh explicit authorization required; no prelaunch continuation exception',
    overall_pass_requires='Native lifecycle success AND mandatory offline verification success',
))
(freeze/'artifact-manifest.sha256').write_text(manifest(freeze))
p=load_prepared(freeze,mode=KIND)
assert p.key_path.stat().st_mode & 0o777 == 0o600
history=json.loads((freeze/'historical-integrity.json').read_text())
assert p.public_key not in {r['public_key'] for r in history['credential_identities']}
private=p.key_path.read_bytes()
for file in freeze.rglob('*'):
    if file.is_file() and file.name!='.admin-secret':
        assert private not in file.read_bytes() and private.hex().encode() not in file.read_bytes(),file
sys.argv=['proof','preflight','--mode',KIND,'--directory',str(freeze)]
output=io.StringIO()
with contextlib.redirect_stdout(output):
    cli.main()
result=json.loads(output.getvalue())
assert result['state']=='READY_TO_LAUNCH'
assert result['process_creation_blocked']
assert result['launches']==result['connections']==result['requests']==0
assert not result['subprocess_created'] and not result['admin_connected'] and not result['request_sent']
assert result['evidence_destination']==str(destination)
result.update(attempt_id=next_identity['attempt_id'],historical_attempt1_validates=True,historical_attempt2_validates=True,attempt2_reusable=False,next_attempt=3,fresh_credential=True,credential_mode='0600',credential_public_key=p.public_key,private_bytes_excluded=True)
Path('/tmp/qualification-lineage-verification/v3-preflight.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps(dict(state=result['state'],attempt_id=result['attempt_id'],historical_attempt1_validates=True,historical_attempt2_validates=True,attempt2_reusable=False,next_attempt=3,launches=0,connections=0,requests=0),indent=2))
