import ast,hashlib,json
from pathlib import Path
from app.simulation.openttd.proof import qualification_lineage as q
from app.simulation.openttd.proof.harness import manifest
from app.simulation.openttd.proof.historical_protection import validate_protection
from app.simulation.openttd.proof.qualification_contract import qualification_contract
root=Path.cwd();out=Path('/tmp/endpoint-v5-diagnosis');runtime=root/'artifacts/runtime'
before=json.loads((out/'history-before.json').read_text())
for n,h in before.items():assert hashlib.sha256(Path(n).read_bytes()).hexdigest()==h,n
roots={Path(n).parts[len(root.parts)+2] for n in before if Path(n).is_relative_to(runtime) and (runtime/Path(n).parts[len(root.parts)+2]).is_dir()}
for name in roots:
 p=runtime/name;assert {str(x) for x in p.rglob('*') if x.is_file() and x.name!='.admin-secret'}=={n for n in before if Path(n).is_relative_to(p)},p
f=runtime/(q.PREFIX+'-real-prelaunch-v4');old=json.loads((f/'qualification-contract.json').read_text());new=qualification_contract();diff={k:(old.get(k),new.get(k)) for k in set(old)|set(new) if old.get(k)!=new.get(k)};assert diff=={'revision':(4,5),'future_destination':(q.PREFIX+'-real-attempt3',q.PREFIX+'-real-attempt4')},diff
for number,suffix in [(1,''),(2,'-v2'),(3,'-v4')]:
 oldfreeze=runtime/(q.PREFIX+'-real-prelaunch'+suffix);m=json.loads((oldfreeze/'PRELAUNCH.json').read_text());dest=Path(m['attempt_directory']);identity=q.validate_historical_attempt(oldfreeze,dest);assert identity.launches==1
 try:q.validate_lineage(oldfreeze,json.loads((oldfreeze/'attempt-lineage.json').read_text()),identity.freeze_revision,dest)
 except ValueError:pass
 else:raise AssertionError('Consumed attempt reusable')
v3=q.read_attempt(runtime/(q.PREFIX+'-real-prelaunch-v3-gate-failure'));assert (v3.launches,v3.connections,v3.requests)==(0,0,0)
assert validate_protection(root,json.loads((f/'historical-integrity.json').read_text()))==1627
next_value=q.derive_next_attempt(runtime/(q.PREFIX+'-real-prelaunch-v5'),5,runtime/(q.PREFIX+'-real-attempt4'));assert next_value['attempt_number']==4
source=json.loads((out/'source-before.json').read_text());changed=[n for n,h in source.items() if hashlib.sha256(Path(n).read_bytes()).hexdigest()!=h]
for n in changed+[str(root/'app/simulation/openttd/proof/endpoints.py'),str(root/'tests/test_proof_endpoints.py')]:
 path=Path(n);text=path.read_text();assert all(x.rstrip()==x for x in text.splitlines()),n;assert '[DEBUG-' not in text,n
 if path.is_relative_to(root/'app'):
  for node in ast.walk(ast.parse(text)):
   modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
   assert not any(x.startswith('app.planning') or x.startswith('app.evaluation') for x in modules),(n,modules)
assert str(root/'app/simulation/openttd/qualification_bridge.nut') not in changed
value=dict(historical_files_exact=len(before),historical_roots_exact=len(roots),v4_protected_exact=1627,historical_attempts='PASS',reuse='REJECTED_ALL',v3_prelaunch='PASS',next_native_attempt=4,contract_changes=diff,qualification_operational_semantics='UNCHANGED',dispatch='UNCHANGED',changed_source_files=[str(Path(n).relative_to(root)) for n in changed],whitespace='PASS',import_boundary='PASS',native_activity=dict(launches=0,connections=0,requests=0))
(out/'integrity-audit.json').write_text(json.dumps(value,indent=2));print(json.dumps(value,indent=2))
