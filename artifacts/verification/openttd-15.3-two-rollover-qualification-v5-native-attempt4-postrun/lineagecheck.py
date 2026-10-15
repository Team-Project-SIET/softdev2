import json,hashlib,ast
from pathlib import Path
from dataclasses import asdict
from app.simulation.openttd.proof import qualification_lineage as q
from app.simulation.openttd.proof.harness import verify_freeze
root=Path.cwd(); runtime=root/'artifacts/runtime'; out=Path('/tmp/qualification-attempt4-v5-verification'); f=runtime/(q.PREFIX+'-real-prelaunch-v5'); m=json.loads((f/'PRELAUNCH.json').read_text()); hist=[]
for num,suffix in [(1,''),(2,'-v2'),(3,'-v4'),(4,'-v5')]:
 freeze=runtime/(q.PREFIX+'-real-prelaunch'+suffix); meta=json.loads((freeze/'PRELAUNCH.json').read_text()); dest=Path(meta['attempt_directory']); identity=q.validate_historical_attempt(freeze,dest); assert identity.launches==1
 try:q.validate_lineage(freeze,json.loads((freeze/'attempt-lineage.json').read_text()),identity.freeze_revision,dest)
 except ValueError:pass
 else:raise AssertionError('consumed destination accepted')
 hist.append(asdict(identity))
v3=q.read_attempt(runtime/(q.PREFIX+'-real-prelaunch-v3-gate-failure'));assert (v3.launches,v3.connections,v3.requests)==(0,0,0)
next_value=q.derive_next_attempt(runtime/(q.PREFIX+'-real-prelaunch-v6'),6,runtime/(q.PREFIX+'-real-attempt5'));assert next_value['attempt_number']==5
original=q.derive_next_attempt
def forbidden(*a,**kw):raise AssertionError('historical validation derived next identity')
q.derive_next_attempt=forbidden
q.validate_historical_attempt(f,Path(m['attempt_directory']))
q.derive_next_attempt=original
for basename in ['v5-persistent-before.json','attempt4-before-offline.json']:
 for path,digest in json.loads((out/basename).read_text()).items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest,path
verify_freeze(json.loads((f/'source-freeze.json').read_text()))
for path,digest in json.loads(Path('/tmp/endpoint-v5-diagnosis/history-before.json').read_text()).items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest,path
for p in list((root/'app/simulation/openttd/proof').rglob('*.py'))+list((root/'app/simulation/openttd').glob('qualification*.py')):
 text=p.read_text();assert all(line.rstrip()==line for line in text.splitlines()),str(p)
 for node in ast.walk(ast.parse(text)):
  names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
  assert not any(n.startswith('app.planning') or n.startswith('app.evaluation') for n in names),(str(p),names)
(out/'postconsumption-lineage.json').write_text(json.dumps(dict(historical=hist,v3=asdict(v3),reusable=False,next_native_attempt=5,historical_independent=True,source_integrity='PASS',historical_integrity='PASS',whitespace='PASS',import_boundary='PASS'),indent=2))
print('Historical 1/2/3/4 PASS; V3 prelaunch PASS; all reuse rejected; next5; historical independent; source/history/whitespace/imports PASS')
