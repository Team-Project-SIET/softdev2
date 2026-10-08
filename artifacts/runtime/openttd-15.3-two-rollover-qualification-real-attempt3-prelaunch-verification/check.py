import json
from pathlib import Path
from app.simulation.openttd.proof.harness import PROJECT, manifest, verify_freeze
from app.simulation.openttd.proof.native import load_prepared
from app.simulation.openttd.proof.qualification_lineage import validate_historical_attempt,validate_lineage,derive_next_attempt
from app.simulation.openttd.proof.enrichment_preparation import checkpoint_head
from app.simulation.openttd.proof.historical_protection import validate_protection
root=PROJECT/'artifacts/runtime'
f=root/'openttd-15.3-two-rollover-qualification-real-prelaunch-v3'
m=json.loads((f/'PRELAUNCH.json').read_text())
assert m['proof_kind']==m['mode']=='two-rollover-qualification'
assert m['attempt']==m['prelaunch_revision']==3
assert m['attempt_id']=='two-rollover-qualification-v3-native-attempt3'
assert checkpoint_head()==m['checkpoint_head']==m['baseline_head']
assert (f/'artifact-manifest.sha256').read_text()==manifest(f)
source=json.loads((f/'source-freeze.json').read_text());verify_freeze(source)
history=json.loads((f/'historical-integrity.json').read_text());assert validate_protection(PROJECT,history)==m['protected_unique_count']
for number in (1,2):
 old=root/('openttd-15.3-two-rollover-qualification-real-prelaunch'+('' if number==1 else '-v2'))
 meta=json.loads((old/'PRELAUNCH.json').read_text())
 dest=Path(meta['attempt_directory'])
 validate_historical_attempt(old,dest)
 try:validate_lineage(old,json.loads((old/'attempt-lineage.json').read_text()),meta['prelaunch_revision'],dest)
 except ValueError:pass
 else:raise AssertionError('Consumed predecessor reusable')
next_value=derive_next_attempt(f,m['prelaunch_revision'],Path(m['attempt_directory']))
assert json.loads(json.dumps(next_value))==json.loads((f/'attempt-lineage.json').read_text())
c=json.loads((f/'qualification-contract.json').read_text());r=c['resources']
assert tuple(r[k] for k in ('clock_requests','application_requests','response_bytes','query_operations','lifecycle_frames','post_auth_frames'))==(304,1072,368080,9088,6,9094)
assert (r['poll_interval'],r['timeout'])==(1.0,300.0)
p=load_prepared(f,mode=m['mode'])
assert p.public_key==m['public_key'] and p.key_path.stat().st_mode & 0o777==0o600
assert p.public_key not in {i['public_key'] for i in history['credential_identities']}
private=p.key_path.read_bytes()
for q in f.rglob('*'):
 if q.is_file() and q.name!='.admin-secret':assert private not in q.read_bytes() and private.hex().encode() not in q.read_bytes(),q
result=dict(identity=m['attempt_id'],freeze=str(f),destination=m['attempt_directory'],head=m['checkpoint_head'],source_inputs=len(source),protected_files=m['protected_unique_count'],historical_attempt1='PASS',historical_attempt2='PASS',predecessors_reusable=False,next_attempt=3,contracts='PASS',credential_mode='0600',fresh_credential='PASS',private_bytes_excluded='PASS',launches=0,connections=0,requests=0)
Path('/tmp/qualification-attempt3-prelaunch-review/validation.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
