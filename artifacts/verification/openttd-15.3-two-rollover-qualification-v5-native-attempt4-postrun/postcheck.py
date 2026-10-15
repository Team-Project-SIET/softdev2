import json,hashlib,subprocess
from pathlib import Path
from app.simulation.openttd.proof.harness import manifest,verify_freeze
from app.simulation.openttd.admin_crypto import AuthorizedKey
from app.simulation.openttd.qualification_clock import NativeReadExchange,NativeReadReceipt
p=Path('artifacts/runtime/openttd-15.3-two-rollover-qualification-real-attempt4'); f=Path('artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v5')
load=lambda x:json.loads(x.read_text())
pre=load(f/'PRELAUNCH.json');source=load(f/'source-freeze.json');hist=load(f/'historical-integrity.json')
verify_freeze(source);assert manifest(f)==(f/'artifact-manifest.sha256').read_text();assert manifest(p)==(p/'artifact-manifest.sha256').read_text()
for r in hist['entries']:assert hashlib.sha256(Path(r['path']).read_bytes()).hexdigest()==r['sha256'],r['path']
for r in hist['credential_identities']:
 k=Path(r['path']);assert k.stat().st_mode&0o777==r['mode'];assert AuthorizedKey.from_bytes(k.read_bytes()).public_hex==r['public_key']
assert subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()==pre['checkpoint_head']
e=load(p/'proof-evidence.json');s=load(p/'qualification-session.json');life=load(p/'process-lifecycle.json');prod=load(p/'production-observation.json');a=load(p/'anchor'/'structural-observation.json');z=load(p/'final'/'structural-observation.json')
assert e['status']=='REAL_SUCCESS' and e['source_integrity'] and e['launches']==e['connections']==1 and e['retries']==e['reconnects']==0
assert e['states'][-1]=='COMPLETED' and e['states'].index('POSTRUN_INTEGRITY_VERIFIED')<e['states'].index('COMPLETED')
assert all(life[k] for k in ['reaped','sockets_closed','credential_removed','workspace_disposed','postrun_integrity_verified']);assert not life['remaining_processes'];assert not life['cleanup_error']
assert not Path(pre['workspace']).exists()
assert s['targets_anchor']==s['targets_final'];assert {r['industry_id']:r['construction_date'] for r in s['lifetimes_anchor']}=={r['industry_id']:r['construction_date'] for r in s['lifetimes_final']}
assert prod['complete'] and prod['qualified_for_planning'];assert prod['source_structural_world_digest']==z['structural_world_digest']
assert a['same_process'] and a['same_connection'] and z['same_process'] and z['same_connection']
for k in ['bridge_digest','configuration_digest']:assert a[k]==z[k]
for t in s['semantic_evidence']['native_transactions']:
 x=t['exchange'];NativeReadExchange(x['request_payload'].encode(),x['response_payload'].encode(),NativeReadReceipt(**x['receipt']),tuple(x['network_sequence']),x['protocol_operations']).validate()
 assert t['gamescript']['sequence'][0]=='BRIDGE_REQUEST_RECEIVED' and t['gamescript']['sequence'][-1]=='BRIDGE_POST_RESPONSE_ALIVE'
rows=[json.loads(l) for l in (p/'transactions.jsonl').read_text().splitlines()];assert len(rows)==e["requests_sent"]
for r in rows:
 assert r['delivery']=='SENT' and r['validated'];assert hashlib.sha256(r['response'].encode()).hexdigest()==r['receipt']['response_payload_sha256'];assert r['gamescript'].get('sequence',r['gamescript'].get('ordered_sequence'))[-1]=='BRIDGE_POST_RESPONSE_ALIVE'
first=next(r for r in rows if r['request']['type']=='industry_page');assert 'anchor' in first['request']['request_id'];assert first['gamescript']['ordered_sequence'][0]=='BRIDGE_REQUEST_RECEIVED'
last=rows[-1];assert last['request']['type']=='economy_clock';assert json.loads(last['response'])['economy_month']==3
assert all('production_level' not in r for r in prod['records'])
usage=s['semantic_evidence']['phase_usage']; totals=[sum(v[i] for _,v in usage) for i in range(3)];assert all(t<=c for t,c in zip(totals,[1072,368080,9088]));assert e['accounting']['total_post_auth_frames']==totals[2]+6<=9094
out={'historical_files':len(hist['entries']),'source_inputs':len(source),'archived_credentials':len(hist['credential_identities']),'integrity':'PASS','transactions':len(rows),'phase_usage':usage,'first_anchor_request':first,'final_guard':last,'totals':totals,'frames':e['accounting']['total_post_auth_frames'],'clock':s['clock'],'qualified_month':load(p/'qualified-month.json'),'anchor':a,'final':z,'production':prod,'cleanup':{k:v for k,v in life.items() if k!='admin_frame_accounting'},'lifecycle':e['states']}
Path('/tmp/qualification-attempt4-v5-verification/postrun-audit.json').write_text(json.dumps(out,indent=2))
print('Native qualification, receipts, liveness, budgets, cleanup and historical/source integrity PASS',totals)
v=life['endpoint_verification']
assert v['policy']=='linux-kernel-endpoint-closure-v1'
assert all(v[k] for k in ['process_reaped','reservation_released','listener_closed','connection_closed'])
assert v['game_port']==pre['game_port'] and v['admin_port']==pre['admin_port']
assert not v['immediate_rebindability_required'] and not v['connection_probe']
before=load(Path('/tmp/qualification-attempt4-v5-verification/v5-persistent-before.json'))
for path,digest in before.items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest,path
snap={str(x):hashlib.sha256(x.read_bytes()).hexdigest() for x in p.rglob('*') if x.is_file()}
Path('/tmp/qualification-attempt4-v5-verification/attempt4-before-offline.json').write_text(json.dumps(snap,indent=2))

limits=load(f/'qualification-contract.json')['resources']
for phase,counts in usage:
 bounds=limits['phase_bounds'][phase]
 assert all(count<=bounds[key] for count,key in zip(counts,['requests','response_bytes','query_operations']))
assert dict(usage)['clock'][0]<=limits['clock_requests']
assert sum(len(r['response'].encode()) for r in rows)==totals[1]
assert e['requests_attempted']==e['requests_sent']==totals[0] and e['ambiguous_requests']==0
assert a['complete'] and z['complete']
m2=s['clock']['samples'][2]
assert all(m2['month_start']<=r['economy_date_before']<=r['economy_date_after']<m2['month_end'] for r in prod['records'])
assert sorted((r['industry_id'],r['cargo_id']) for r in prod['records'])==[tuple(t) for t in s['targets_final']]
assert len(prod['records'])==len(set((r['industry_id'],r['cargo_id']) for r in prod['records']))
assert e['accounting']['categories']['establishment']==2 and e['accounting']['categories']['setup']==3 and e['accounting']['categories']['cleanup']==1
assert all(r['request']['type'] in ['economy_clock','industry_page','cargo_page','industry_cargo','industry_lifetime','industry_production'] for r in rows)
assert 'INDUSTRY_PAGE_READ' in first['gamescript']['ordered_sequence']
print('Exact phase ceilings, coverage, M2 brackets, no mutation, first M1 handler and lifecycle accounting PASS')
