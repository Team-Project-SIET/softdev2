"""Public offline preparation/preflight; process creation and connect always blocked."""
import contextlib,io,json,sys
from pathlib import Path
from xml.etree import ElementTree

for name in ('focused','ordinary'):
 p=Path('/tmp/qualification-v4-verification')/(name+'.xml')
 suite=ElementTree.parse(p).getroot().find('testsuite')
 assert suite is not None and suite.get('failures')==suite.get('errors')=='0',name

def guard(event,args):
 if event in ('subprocess.Popen','socket.connect'):
  raise PermissionError('V4 preparation only: subprocess/connection prohibited')
sys.addaudithook(guard)
from app.simulation.openttd.proof import __main__ as cli
from app.simulation.openttd.proof.harness import PROJECT,manifest,write_json
from app.simulation.openttd.proof.qualification_contract import PRELAUNCH_DIRECTORY,ATTEMPT_DIRECTORY,KIND,REVISION
from app.simulation.openttd.proof.qualification_lineage import validate_historical_attempt,read_attempt,derive_next_attempt
from app.simulation.openttd.proof.native import load_prepared

root=PROJECT/'artifacts/runtime';freeze=root/PRELAUNCH_DIRECTORY;destination=root/ATTEMPT_DIRECTORY
assert REVISION==4 and destination.name.endswith('real-attempt3') and not destination.exists()
for number in (1,2):
 old=root/('openttd-15.3-two-rollover-qualification-real-prelaunch'+('' if number==1 else '-v2'))
 meta=json.loads((old/'PRELAUNCH.json').read_text())
 validate_historical_attempt(old,Path(meta['attempt_directory']))
v3=root/'openttd-15.3-two-rollover-qualification-real-prelaunch-v3'
gate=v3.with_name(v3.name+'-gate-failure');prelaunch=read_attempt(gate)
assert prelaunch.classification=='PRELAUNCH' and (prelaunch.launches,prelaunch.connections,prelaunch.requests)==(0,0,0)
next_value=derive_next_attempt(freeze,REVISION,destination)
assert next_value['attempt_number']==3
assert next_value['attempt_id']=='two-rollover-qualification-v4-native-attempt3'
assert len(next_value['post_launch_predecessors'])==2
assert len(next_value['supersedes_prelaunch_attempts'])==1
assert next_value['supersedes_prelaunch_attempts'][0]['evidence_digest']==prelaunch.evidence_digest
assert next_value['fresh_explicit_authorization_required']
sys.argv=['proof','prepare','--mode',KIND,'--directory',str(freeze)]
cli.main()
write_json(freeze/'lineage-context.json',dict(
 boundary='At V4 preparation, before any native Attempt 3 execution',
 native_attempt3_consumed=False,
 prior_freeze=dict(revision=3,classification='PRELAUNCH_FAILURE',launches=0,connections=0,requests=0,evidence_directory=gate.name,evidence_digest=prelaunch.evidence_digest,reason=json.loads((gate/'PRELAUNCH-FAILURE.json').read_text())['error']),
 native_predecessors=next_value['post_launch_predecessors'],
 authorization='Fresh explicit authorization required; none granted for V4 execution',
 simulated_post_consumption=dict(scope='Controlled tests only; actual history not changed',historical_attempt3='PASS',attempt3_reusable=False,next_native_attempt=4),
))
(freeze/'artifact-manifest.sha256').write_text(manifest(freeze))
p=load_prepared(freeze,mode=KIND)
assert p.key_path.stat().st_mode & 0o777==0o600
old_public=json.loads((v3/'PRELAUNCH.json').read_text())['public_key']
assert p.public_key!=old_public
history=json.loads((freeze/'historical-integrity.json').read_text())
assert p.public_key not in {r['public_key'] for r in history['credential_identities']}
private=p.key_path.read_bytes()
for file in freeze.rglob('*'):
 if file.is_file() and file.name!='.admin-secret':
  assert private not in file.read_bytes() and private.hex().encode() not in file.read_bytes(),file
sys.argv=['proof','preflight','--mode',KIND,'--directory',str(freeze)]
output=io.StringIO()
with contextlib.redirect_stdout(output):cli.main()
result=json.loads(output.getvalue())
assert result['state']=='READY_TO_LAUNCH' and result['process_creation_blocked']
assert result['launches']==result['connections']==result['requests']==0
assert not result['subprocess_created'] and not result['admin_connected'] and not result['request_sent']
assert result['evidence_destination']==str(destination)
assert result['lineage_predecessor_count']==3
result.update(attempt_id=next_value['attempt_id'],historical_attempt1_validates=True,historical_attempt2_validates=True,v3_prelaunch_validates=True,native_attempt3_consumed=False,next_native_attempt=3,fresh_credential=True,credential_mode='0600',private_bytes_excluded=True)
Path('/tmp/qualification-v4-verification/v4-preflight.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
print(json.dumps(dict(state=result['state'],attempt_id=result['attempt_id'],next_native_attempt=3,native_attempt3_consumed=False,predecessors=3,launches=0,connections=0,requests=0),indent=2))
