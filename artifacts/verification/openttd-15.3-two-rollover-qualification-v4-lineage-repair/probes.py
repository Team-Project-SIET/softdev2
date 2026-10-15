import json,tempfile
from pathlib import Path
from app.simulation.openttd.proof.harness import manifest
from app.simulation.openttd.proof import qualification_lineage as q
root=Path('artifacts/runtime').resolve()
value=q.derive_next_attempt(root/(q.PREFIX+'-real-prelaunch-v4'),4,root/(q.PREFIX+'-real-attempt3'))
print('EXACT_REAL_HISTORY',value['attempt_id'],'prelaunch=',[(r['freeze_revision'],r['classification'],r['launches'],r['connections'],r['requests']) for r in value['supersedes_prelaunch_attempts']])
print('REAL_DESTINATION_EXISTS',(root/(q.PREFIX+'-real-attempt3')).exists())
for status in ('REAL_FAILED','REAL_SUCCESS'):
 with tempfile.TemporaryDirectory() as tmp:
  p=Path(tmp);old=p/'freeze-v4';old.mkdir();(old/'PRELAUNCH.json').write_text(json.dumps(dict(mode=q.KIND,prelaunch_revision=4)))
  dest=p/(q.PREFIX+'-real-attempt1');dest.mkdir()
  (dest/'proof-evidence.json').write_text(json.dumps(dict(status=status,launches=1,connections=1,requests_sent=1,preparation=str(old),states=['COMPLETED'] if status=='REAL_SUCCESS' else ['FAILED'])))
  (dest/'artifact-manifest.sha256').write_text(manifest(dest))
  try:
   value=q.derive_next_attempt(p/'freeze-v5',5,p/(q.PREFIX+'-real-attempt2'))
   print('MINIMAL_CONSUMED',status,'=>',value['attempt_number'])
  except ValueError as error:print('MINIMAL_CONSUMED',status,'=>',str(error))
