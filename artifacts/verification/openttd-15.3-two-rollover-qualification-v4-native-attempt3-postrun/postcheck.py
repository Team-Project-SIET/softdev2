import ast,json,hashlib,subprocess
from dataclasses import asdict
from pathlib import Path
from app.simulation.openttd.proof.harness import manifest,verify_freeze
from app.simulation.openttd.proof.historical_protection import validate_protection
from app.simulation.openttd.proof import qualification_lineage as q
from app.simulation.openttd.qualification_clock import NativeReadExchange,NativeReadReceipt
root=Path.cwd();out=Path('/tmp/qualification-attempt3-v4-verification');runtime=root/'artifacts/runtime';f=runtime/(q.PREFIX+'-real-prelaunch-v4');load=lambda p:json.loads(p.read_text());pre=load(f/'PRELAUNCH.json');p=Path(pre['attempt_directory']);contract=load(f/'qualification-contract.json');limits=contract['resources']
verify_freeze(load(f/'source-freeze.json'));assert manifest(f)==(f/'artifact-manifest.sha256').read_text();assert manifest(p)==(p/'artifact-manifest.sha256').read_text()
for n,d in load(out/'v4-persistent-before.json').items():assert hashlib.sha256(Path(n).read_bytes()).hexdigest()==d,n
hist=load(f/'historical-integrity.json');assert validate_protection(root,hist)==hist['unique_count']
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==pre['checkpoint_head']
e=load(p/'proof-evidence.json');s=load(p/'qualification-session.json');life=load(p/'process-lifecycle.json');prod=load(p/'production-observation.json');a=load(p/'anchor/structural-observation.json');z=load(p/'final/structural-observation.json')
assert e['status']=='REAL_FAILED' and not e['source_integrity'] and e['launches']==e['connections']==1 and e['retries']==e['reconnects']==0
assert e['states'][-1]=='FAILED' and e['states'][-2]=='PROCESS_REAPED' and 'QUALIFIED_OBSERVATION_ASSEMBLED' in e['states']
assert life['reaped'] and load(out/'supplemental-cleanup.json')['postrun_integrity_verified'];assert not life['remaining_processes'];assert not life['cleanup_error'];assert not Path(pre['workspace']).exists()
assert s['targets_anchor']==s['targets_final'];assert {r['industry_id']:r['construction_date'] for r in s['lifetimes_anchor']}=={r['industry_id']:r['construction_date'] for r in s['lifetimes_final']}
assert not prod['complete'] and not prod['qualified_for_planning'] and prod['production_digest'] is None;assert s['semantic_evidence']['phase']=='COMPLETED' and s['semantic_evidence']['failure'] is None and s['semantic_evidence']['production']['complete'];assert prod['source_structural_world_digest']==z['structural_world_digest'];assert a['same_process'] and a['same_connection'] and z['same_process'] and z['same_connection']
for k in ['bridge_digest','configuration_digest']:assert a[k]==z[k]
for t in s['semantic_evidence']['native_transactions']:
 x=t['exchange'];NativeReadExchange(x['request_payload'].encode(),x['response_payload'].encode(),NativeReadReceipt(**x['receipt']),tuple(x['network_sequence']),x['protocol_operations']).validate()
 assert t['gamescript']['sequence'][0]=='BRIDGE_REQUEST_RECEIVED' and t['gamescript']['sequence'][-1]=='BRIDGE_POST_RESPONSE_ALIVE'
rows=[json.loads(l) for l in (p/'transactions.jsonl').read_text().splitlines()]
for r in rows:
 assert r['delivery']=='SENT' and r['validated'];assert hashlib.sha256(r['response'].encode()).hexdigest()==r['receipt']['response_payload_sha256'];assert r['gamescript'].get('sequence',r['gamescript'].get('ordered_sequence'))[-1]=='BRIDGE_POST_RESPONSE_ALIVE'
first=next(r for r in rows if r['request']['type']=='industry_page');assert 'anchor' in first['request']['request_id'];assert first['gamescript']['ordered_sequence'][0]=='BRIDGE_REQUEST_RECEIVED'
last=rows[-1];assert last['request']['type']=='economy_clock';guard=json.loads(last['response']);assert guard['economy_month']==3
assert all(r['economy_date_before']==r['economy_date_after']==guard['economy_date'] for r in prod['records']);assert all('production_level' not in r for r in prod['records'])
usage=s['semantic_evidence']['phase_usage'];totals=[sum(v[i] for _,v in usage) for i in range(3)];assert totals[0]==len(rows)==e['requests_sent'];assert totals[0]<=limits['application_requests'] and totals[1]<=limits['response_bytes'] and totals[2]<=limits['query_operations'];assert e['accounting']['total_post_auth_frames']==totals[2]+6<=limits['post_auth_frames']
for phase,value in usage:
 bound=limits['phase_bounds'][phase];assert all(value[i]<=bound[k] for i,k in enumerate(['requests','response_bytes','query_operations']))
historical=[]
for row in q.lineage_rows(load(f/'attempt-lineage.json')):
 dest=runtime/row['evidence_directory'];identity=q.read_attempt(dest)
 if identity.launches:
  old=Path(load(dest/'proof-evidence.json')['preparation']);q.validate_historical_attempt(old,dest)
  try:q.validate_lineage(old,load(old/'attempt-lineage.json'),identity.freeze_revision,dest)
  except ValueError:pass
  else:raise AssertionError('Historical execution reuse allowed')
 historical.append(asdict(identity))
identity=q.validate_historical_attempt(f,p)
try:q.validate_lineage(f,load(f/'attempt-lineage.json'),pre['prelaunch_revision'],p)
except ValueError:pass
else:raise AssertionError('Attempt3 execution reuse allowed')
historical.append(asdict(identity));next_value=q.derive_next_attempt(runtime/(q.PREFIX+'-real-prelaunch-v5'),5,runtime/(q.PREFIX+'-real-attempt4'));assert next_value['attempt_number']==4
paths=list((root/'app/simulation/openttd').glob('qualification*.py'))+list((root/'app/simulation/openttd/proof').glob('*lineage.py'))+list((root/'app/simulation/openttd/proof').glob('qualification*.py'))+[root/'app/simulation/openttd/proof/offline_verification.py',root/'tests/test_historical_attempt_lineage.py',root/'tests/test_qualification_preparation.py']
for path in paths:
 text=path.read_text();assert all(x.rstrip()==x for x in text.splitlines()),path;assert '[DEBUG-' not in text,path
 if path.is_relative_to(root/'app'):
  for node in ast.walk(ast.parse(text)):
   modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
   assert not any(n.startswith('app.planning') or 'evaluation' in n for n in modules),(path,modules)
result=dict(historical_files=len(hist['entries']),source_inputs=len(load(f/'source-freeze.json')),archived_credentials=len(hist['credential_identities']),integrity='PASS',transactions=len(rows),phase_usage=usage,first_anchor_request=first,final_guard=last,totals=totals,frames=e['accounting']['total_post_auth_frames'],clock=s['clock'],qualified_month=dict(economy_year=s['clock']['samples'][1]['economy_year'],economy_month=s['clock']['samples'][1]['economy_month'],boundary_start=s['clock']['samples'][1],boundary_end=s['clock']['samples'][2],admission_retained=False),anchor=a,final=z,production=prod,cleanup={k:v for k,v in life.items() if k!='admin_frame_accounting'},supplemental_cleanup=load(out/'supplemental-cleanup.json'),native_semantic_execution='SUCCESS',public_cleanup='FAILED',public_final_admission=False,overall='FAILED',lifecycle=e['states'],historical=historical,next_lineage=next_value,whitespace='PASS',import_boundary='PASS')
(out/'postrun-audit.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:result[k] for k in ['historical_files','source_inputs','archived_credentials','integrity','transactions','totals','frames','whitespace','import_boundary']}));print('Historical Attempts 1/2/3 PASS; V3 prelaunch PASS; all native reuse rejected; conceptual next native Attempt4 (no new freeze created)')
