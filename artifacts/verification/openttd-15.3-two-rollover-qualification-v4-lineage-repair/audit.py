import ast,hashlib,json
from pathlib import Path
from app.simulation.openttd.proof.historical_protection import validate_protection
from app.simulation.openttd.proof.qualification_lineage import validate_historical_attempt,read_attempt
from app.simulation.openttd.proof.qualification_contract import qualification_contract

root=Path.cwd();runtime=root/'artifacts/runtime'
before=json.loads(Path('/tmp/qualification-v4-verification/protected-before.json').read_text())
for name,d in before.items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==d,name
roots={Path(n).parts[2] for n in before if n.startswith('artifacts/runtime/') and len(Path(n).parts)>3}
for name in roots:
 p=Path('artifacts/runtime')/name
 assert {str(q) for q in p.rglob('*') if q.is_file() and q.name!='.admin-secret'}=={n for n in before if Path(n).is_relative_to(p)},p
v3=runtime/'openttd-15.3-two-rollover-qualification-real-prelaunch-v3'
protected=validate_protection(root,json.loads((v3/'historical-integrity.json').read_text()))
old=json.loads((v3/'qualification-contract.json').read_text());new=qualification_contract()
assert {k:(old.get(k),new.get(k)) for k in set(old)|set(new) if old.get(k)!=new.get(k)}=={'revision':(3,4)}
changed=[]
for n,d in json.loads((v3/'source-freeze.json').read_text()).items():
 if hashlib.sha256(Path(n).read_bytes()).hexdigest()!=d:changed.append(str(Path(n).relative_to(root)))
allow={'app/simulation/openttd/proof/qualification_contract.py','app/simulation/openttd/proof/qualification_lineage.py','app/simulation/openttd/proof/production_lineage.py','app/simulation/openttd/proof/raw_production_lineage.py','tests/test_historical_attempt_lineage.py','tests/test_qualification_preparation.py'}
assert set(changed)==allow,(changed,allow)
for number in (1,2):
 f=runtime/('openttd-15.3-two-rollover-qualification-real-prelaunch'+('' if number==1 else '-v2'))
 m=json.loads((f/'PRELAUNCH.json').read_text());validate_historical_attempt(f,Path(m['attempt_directory']))
gate=read_attempt(v3.with_name(v3.name+'-gate-failure'))
assert gate.classification=='PRELAUNCH' and (gate.launches,gate.connections,gate.requests)==(0,0,0)
assert not (runtime/'openttd-15.3-two-rollover-qualification-real-attempt3').exists()
paths=list((root/'app/simulation/openttd').glob('qualification*.py'))+list((root/'app/simulation/openttd/proof').glob('*lineage.py'))+list((root/'app/simulation/openttd/proof').glob('qualification*.py'))+[root/'app/simulation/openttd/proof/offline_verification.py',root/'tests/test_historical_attempt_lineage.py',root/'tests/test_qualification_preparation.py']
for p in paths:
 text=p.read_text();assert all(x.rstrip()==x for x in text.splitlines()),p
 if p.is_relative_to(root/'app'):
  for node in ast.walk(ast.parse(text)):
   modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
   assert not any(n.startswith('app.planning') or 'evaluation' in n for n in modules),(p,modules)
 assert '[DEBUG-' not in text,p
print(json.dumps(dict(public_files_exact=len(before),historical_v3_protection_exact=protected,source_changes=sorted(changed),contract_changes={'revision':[3,4]},dispatch='EXACT',historical_attempt1='PASS',historical_attempt2='PASS',v3_prelaunch='PASS',native_attempt3_consumed=False,whitespace='PASS',import_boundary='PASS',debug_instrumentation='NONE'),indent=2))
