from pathlib import Path
import hashlib,json
from dataclasses import asdict
from app.simulation.openttd.industry_production import IndustryProductionRequest,IndustryProductionResponse,IndustryProductionReceipt,PRODUCTION_NETWORK_SEQUENCE
from app.simulation.openttd.industry_production_evidence import parse_industry_production_evidence
from app.simulation.openttd.proof.economy_authority import calendar_economy_month
from app.simulation.openttd.proof.historical_protection import validate_protection
from app.simulation.openttd.proof.raw_production_lineage import read_attempt
r=Path('/home/fed/codes/softdev2');p=r/'artifacts/runtime/openttd-15.3-complete-raw-production-real-attempt1';f=p.with_name('openttd-15.3-complete-raw-production-real-prelaunch')
def load(n):return json.loads((p/n).read_text())
meta=json.loads((f/'PRELAUNCH.json').read_text());frozen=json.loads((f/'source-freeze.json').read_text())
assert len(frozen)==215
assert all(Path(n).is_file() and hashlib.sha256(Path(n).read_bytes()).hexdigest()==h for n,h in frozen.items())
h=json.loads((f/'historical-integrity.json').read_text());assert validate_protection(r,h)==1258 and len(h['credential_identities'])==7
s=load('structural-observation.json');d=load('production-observation.json');c=load('combined-session.json');e=load('proof-evidence.json');cleanup=load('process-lifecycle.json')
assert e['status']=='REAL_SUCCESS' and e['states'][-1]=='COMPLETED' and e['error'] is None
assert e['launches']==e['connections']==1 and e['retries']==e['reconnects']==0
assert all(s[k] for k in ('inventory_complete','capability_complete','catalog_complete','complete','same_process','same_connection'))
assert d['complete'] and d['same_process'] and d['same_connection'] and not d['qualified_for_planning']
assert d['source_structural_world_digest']==s['structural_world_digest']
for file,key,value in [('structural-canonical.json','structural_world_digest',s['structural_world_digest']),('production-canonical.json','production_digest',d['production_digest'])]:
 assert hashlib.sha256((p/file).read_bytes()).hexdigest()==value
cap=load('capability-observation.json')['semantic_observation']; targets=tuple(sorted((v['industry_id'],k) for v in cap for k in v['produces']))
records=d['records'];assert targets==tuple((v['industry_id'],v['cargo_id']) for v in records)==tuple(map(tuple,load('production-session.json')['targets']))
assert len(targets)==len(set(targets))==10
industries=set(s['ordered_industry_ids']);cargos=set(s['ordered_cargo_ids']);assert all(i in industries and k in cargos for i,k in targets)
transactions=[json.loads(line) for line in (p/'transactions.jsonl').read_text().splitlines()];assert len(transactions)==31
from collections import Counter
counts=Counter(v['request']['type'] for v in transactions);assert counts=={'industry_page':5,'industry_cargo':10,'cargo_page':6,'industry_production':10}
assert all(v['validated'] and v['delivery']=='SENT' for v in transactions)
assert [v['request']['type'] for v in transactions]==['industry_page']*5+['industry_cargo']*10+['cargo_page']*6+['industry_production']*10
month=calendar_economy_month(load('welcome-evidence.json')['start_day']);rows=[]
raw=(p/'stderr.log').read_bytes()
for v in transactions:
 if v['request']['type']!='industry_production':continue
 request=IndustryProductionRequest.parse(json.dumps(v['request'],sort_keys=True,separators=(',',':')).encode());payload=v['response'].encode();response=IndustryProductionResponse.parse(payload)
 receipt=IndustryProductionReceipt.correlate(request.to_bytes(),payload);assert asdict(receipt)==v['receipt']
 evidence=parse_industry_production_evidence(raw,request.request_id);evidence.require_complete(request,response)
 assert tuple(v['events'])==PRODUCTION_NETWORK_SEQUENCE and month.contains(response.record)
 assert len(payload)<=335 and len(payload)<=512 and len(payload)<1450 and 'production_level' not in v['response']
 rows.append(asdict(response.record))
assert rows==records
assert sum(len(v['response'].encode()) for v in transactions)==7715
prodbytes=sum(len(v['response'].encode()) for v in transactions if v['request']['type']=='industry_production');assert prodbytes==2957
assert c['complete'] and not c['final_acceptance_pending'] and c['semantic_evidence']['total_response_bytes']==7715
assert e['accounting']['query_operations']==124 and e['accounting']['total_post_auth_frames']==130 and not e['accounting']['failed']
assert all(cleanup[k] for k in ('reaped','sockets_closed','credential_removed','workspace_disposed','postrun_integrity_verified')) and not cleanup['remaining_processes'] and cleanup['returncode']==0
assert not Path(meta['workspace']).exists()
assert read_attempt(p).terminal_status=='REAL_SUCCESS'
result=dict(status='PASS',requests=dict(counts),response_bytes=7715,production_response_bytes=prodbytes,query_operations=124,post_auth_frames=130,initial_month=asdict(month),equal_brackets=sum(v['economy_date_before']==v['economy_date_after'] for v in rows),structural_digest=s['structural_world_digest'],production_digest=d['production_digest'],source_identities_exact=215,historical_public_identities_exact=1258,archived_credentials_exact=7,records=rows,qualified_for_planning=False,rollovers_observed=0,cleanup='PASS')
Path('/tmp/authorized-raw-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='records'},indent=2))
from app.simulation.openttd.industry_page import IndustryPageRequest,IndustryPageResponse,IndustryPageReceipt
from app.simulation.openttd.industry_cargo import IndustryCargoRequest,IndustryCargoResponse,IndustryCargoReceipt
from app.simulation.openttd.cargo_page import CargoPageRequest,CargoPageResponse,CargoPageReceipt
from app.simulation.openttd.industry_page_evidence import parse_industry_page_evidence
from app.simulation.openttd.industry_cargo_evidence import parse_industry_cargo_evidence
from app.simulation.openttd.cargo_page_evidence import parse_cargo_page_evidence
schemas={'industry_page':(IndustryPageRequest,IndustryPageResponse,IndustryPageReceipt.correlate,parse_industry_page_evidence),'industry_cargo':(IndustryCargoRequest,IndustryCargoResponse,IndustryCargoReceipt.correlate_transport,parse_industry_cargo_evidence),'cargo_page':(CargoPageRequest,CargoPageResponse,CargoPageReceipt.correlate_transport,parse_cargo_page_evidence)}
for t in transactions:
 if t['request']['type']=='industry_production':continue
 Q,R,correlate,parser=schemas[t['request']['type']]
 qb=json.dumps(t['request'],sort_keys=True,separators=(',',':')).encode();rb=t['response'].encode();q=Q.parse(qb);resp=R.parse(rb)
 assert asdict(correlate(qb,rb))==t['receipt']
 parser(raw,q.request_id).require_complete(q,resp)
 assert len(rb)<=512 and len(rb)<1450
assert e['states'].index('POSTRUN_INTEGRITY_VERIFIED')<e['states'].index('COMPLETED')
assert c['semantic_evidence']['events'].index('STRUCTURAL_WORLD_VERIFIED')<c['semantic_evidence']['events'].index('PRODUCTION_TARGET_SET_FINALIZED')
result['all_structural_receipts_and_evidence']='PASS'
Path('/tmp/authorized-raw-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print('All 31 typed receipts, semantic responses and per-request GameScript evidence chains revalidated offline.')
