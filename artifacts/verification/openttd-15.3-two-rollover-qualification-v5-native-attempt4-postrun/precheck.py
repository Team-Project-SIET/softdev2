import json,hashlib,subprocess
from dataclasses import asdict
from pathlib import Path
from app.simulation.openttd.proof import qualification_lineage as q
from app.simulation.openttd.proof.harness import manifest
from app.simulation.openttd.proof.historical_protection import validate_protection
root=Path.cwd(); out=Path('/tmp/qualification-attempt4-v5-verification'); runtime=root/'artifacts/runtime'
f=runtime/(q.PREFIX+'-real-prelaunch-v5'); m=json.loads((f/'PRELAUNCH.json').read_text()); c=json.loads((f/'qualification-contract.json').read_text()); d=Path(m['attempt_directory'])
assert m['attempt_id']=='two-rollover-qualification-v5-native-attempt4' and m['attempt']==4 and m['prelaunch_revision']==5
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==m['checkpoint_head']==m['baseline_head']
assert (f/'artifact-manifest.sha256').read_text()==manifest(f)
expected=dict(clock_requests=304,application_requests=1072,response_bytes=368080,query_operations=9088,lifecycle_frames=6,post_auth_frames=9094,poll_interval=1.0,timeout=300.0)
for k,v in expected.items():assert c['resources'][k]==v,(k,c['resources'][k],v)
assert not d.exists() and not d.is_symlink()
next_value=q.derive_next_attempt(f,m['prelaunch_revision'],d)
assert json.loads(json.dumps(next_value))==json.loads((f/'attempt-lineage.json').read_text())
assert next_value['attempt_number']==4
historical=[]
for row in next_value['post_launch_predecessors']:
 dest=runtime/row['evidence_directory']; e=json.loads((dest/'proof-evidence.json').read_text()); freeze=Path(e['preparation']); identity=q.validate_historical_attempt(freeze,dest); assert identity.launches==1
 try:q.validate_lineage(freeze,json.loads((freeze/'attempt-lineage.json').read_text()),identity.freeze_revision,dest)
 except ValueError:pass
 else:raise AssertionError('Consumed destination executable')
 historical.append(asdict(identity))
assert len(historical)==3
prelaunch=[asdict(q.read_attempt(runtime/row['evidence_directory'])) for row in next_value['supersedes_prelaunch_attempts']]
assert len(prelaunch)==1 and prelaunch[0]['freeze_revision']==3 and (prelaunch[0]['launches'],prelaunch[0]['connections'],prelaunch[0]['requests'])==(0,0,0)
h=json.loads((f/'historical-integrity.json').read_text());assert validate_protection(root,h)==1708
snapshot={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in f.rglob('*') if p.is_file() and not p.is_relative_to(f/'isolated')}
(out/'v5-persistent-before.json').write_text(json.dumps(snapshot,indent=2))
(out/'prelaunch-audit.json').write_text(json.dumps(dict(attempt_id=m['attempt_id'],next_native_attempt=4,consumed_before=False,historical=historical,prelaunch=prelaunch,ceilings=expected,source_inputs=len(json.loads((f/'source-freeze.json').read_text())),protected_count=1708,private_bytes_published=False),indent=2))
ctx=json.loads((f/'lineage-context.json').read_text())['attempt3_acceptance']
for name,digest in ctx['evidence_files'].items():
 assert hashlib.sha256((Path(ctx['postrun_evidence_directory'])/name).read_bytes()).hexdigest()==digest,name
print('V5 exact; historical Attempts 1/2/3 PASS and nonreusable; V3 PRELAUNCH 0/0/0 PASS; Attempt 4 unconsumed; next 4; frozen limits exact')
