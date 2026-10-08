"""Repository public preparation and guarded preflight; no subprocess/connect."""
import contextlib,io,json,sys,hashlib
from pathlib import Path
from xml.etree import ElementTree as E
out=Path('/tmp/endpoint-v5-diagnosis')
for name in ('focused-final','ordinary'):
 s=E.parse(out/(name+'.xml')).getroot().find('testsuite');assert s is not None and s.get('errors')==s.get('failures')=='0'

def guard(event,args):
 if event in ('subprocess.Popen','socket.connect'):
  raise PermissionError('V5 preparation only: native process/connection prohibited')
sys.addaudithook(guard)
from app.simulation.openttd.proof import __main__ as cli
from app.simulation.openttd.proof.harness import PROJECT,manifest,write_json
from app.simulation.openttd.proof.qualification_contract import PRELAUNCH_DIRECTORY,ATTEMPT_DIRECTORY,KIND,REVISION
from app.simulation.openttd.proof.qualification_lineage import derive_next_attempt,validate_historical_attempt,read_attempt
from app.simulation.openttd.proof.native import load_prepared
root=PROJECT/'artifacts/runtime';freeze=root/PRELAUNCH_DIRECTORY;dest=root/ATTEMPT_DIRECTORY;assert REVISION==5 and not freeze.exists() and not dest.exists()
value=derive_next_attempt(freeze,REVISION,dest);assert value['attempt_number']==4 and value['attempt_id']=='two-rollover-qualification-v5-native-attempt4';assert len(value['post_launch_predecessors'])==3 and len(value['supersedes_prelaunch_attempts'])==1
for number,suffix in [(1,''),(2,'-v2'),(3,'-v4')]:
 old=root/('openttd-15.3-two-rollover-qualification-real-prelaunch'+suffix);m=json.loads((old/'PRELAUNCH.json').read_text());validate_historical_attempt(old,Path(m['attempt_directory']))
gate=read_attempt(root/'openttd-15.3-two-rollover-qualification-real-prelaunch-v3-gate-failure');assert (gate.launches,gate.connections,gate.requests)==(0,0,0)
acceptance=PROJECT/'artifacts/verification/openttd-15.3-two-rollover-qualification-v4-native-attempt3-postrun';assert (acceptance/'artifact-manifest.sha256').read_text()==manifest(acceptance);record=json.loads((acceptance/'verification.json').read_text());assert record['final_acceptance']=='FAILED' and record['offline_verification']=='PASS' and record['native_semantic_execution']=='SUCCESS' and record['public_cleanup']=='FAILED'
sys.argv=['proof','prepare','--mode',KIND,'--directory',str(freeze)];cli.main()
write_json(freeze/'lineage-context.json',dict(
 boundary='Before any native Attempt 4 execution; Attempt 3 consumed under V4',
 native_attempt4_consumed=False,
 native_predecessors=value['post_launch_predecessors'],
 prelaunch_predecessors=value['supersedes_prelaunch_attempts'],
 attempt3_acceptance=dict(native_qualification='SUCCESS',internal_qualified_observation=True,retained_qualified_for_planning=False,cleanup_acceptance='FAILED',offline_verification='PASS',overall='FAILED',reason=record['terminal_reason'],supplemental_integrity='PASS',postrun_evidence_directory=str(acceptance),evidence_files={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in acceptance.iterdir() if p.is_file()}),
 endpoint_diagnosis=dict(proven='Immediate rebindability falsely conflates listener/connection closure with port reuse; controlled TIME_WAIT reproduces EADDRINUSE',historical_failing_bind_index='UNKNOWN_NOT_RETAINED',historical_exact_syscall_state='UNKNOWN_NOT_RETAINED',formal_attempt3_result='FAILED_UNCHANGED'),
 authorization='Fresh explicit authorization required; native execution not authorized in this preparation',
))
(freeze/'artifact-manifest.sha256').write_text(manifest(freeze))
p=load_prepared(freeze,mode=KIND);assert p.key_path.stat().st_mode & 0o777==0o600
oldkeys={json.loads(x.read_text())['public_key'] for x in root.glob('openttd-15.3-two-rollover-qualification-real-prelaunch*/PRELAUNCH.json') if x.parent!=freeze};assert p.public_key not in oldkeys
history=json.loads((freeze/'historical-integrity.json').read_text());assert p.public_key not in {x['public_key'] for x in history['credential_identities']}
private=p.key_path.read_bytes()
for x in freeze.rglob('*'):
 if x.is_file() and x!=p.key_path:assert private not in x.read_bytes() and private.hex().encode() not in x.read_bytes(),x
sys.argv=['proof','preflight','--mode',KIND,'--directory',str(freeze)];output=io.StringIO()
with contextlib.redirect_stdout(output):cli.main()
r=json.loads(output.getvalue());assert r['state']=='READY_TO_LAUNCH' and r['process_creation_blocked'] and r['endpoint_verifier_loaded'];assert r['launches']==r['connections']==r['requests']==0;assert not r['subprocess_created'] and not r['admin_connected'] and not r['request_sent'];assert r['lineage_predecessor_count']==4 and r['evidence_destination']==str(dest)
r.update(attempt_id=value['attempt_id'],historical_attempt1='PASS',historical_attempt2='PASS',historical_v3='PASS',historical_attempt3='PASS',next_native_attempt=4,native_attempt4_consumed=False,credential_mode='0600',fresh_credential=True,private_bytes_excluded=True)
(out/'v5-preflight.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(dict(state=r['state'],attempt_id=r['attempt_id'],predecessors=4,launches=0,connections=0,requests=0)))
