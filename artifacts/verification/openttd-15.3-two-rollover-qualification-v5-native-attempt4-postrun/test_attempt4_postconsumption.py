import json
from pathlib import Path
import pytest
from app.simulation.openttd.proof import qualification_lineage as q
ROOT=Path('/home/fed/codes/softdev2/artifacts/runtime')
FREEZE=ROOT/(q.PREFIX+'-real-prelaunch-v5')
META=json.loads((FREEZE/'PRELAUNCH.json').read_text())
DEST=Path(META['attempt_directory'])
def test_attempt4_historical_independent_of_current_derivation(monkeypatch):
 def forbidden(*a,**k):raise AssertionError('historical validation consulted current history')
 for name in ['derive_next_attempt','capture_lineage','relevant_failures']:monkeypatch.setattr(q,name,forbidden)
 identity=q.validate_historical_attempt(FREEZE,DEST)
 assert json.loads((DEST/'proof-evidence.json').read_text())['attempt_id']==META['attempt_id']
 assert identity.launches==identity.connections==1
 assert identity.freeze_revision==5
 assert identity.terminal_status=='REAL_SUCCESS'
def test_consumed_attempt4_reuse_rejected():
 with pytest.raises(ValueError):q.validate_lineage(FREEZE,json.loads((FREEZE/'attempt-lineage.json').read_text()),5,DEST)
def test_next_attempt5_does_not_modify_historical_identity():
 before=q.validate_historical_attempt(FREEZE,DEST)
 next_value=q.derive_next_attempt(ROOT/(q.PREFIX+'-real-prelaunch-v6'),6,ROOT/(q.PREFIX+'-real-attempt5'))
 assert next_value['attempt_number']==5
 assert q.validate_historical_attempt(FREEZE,DEST)==before
 assert not (ROOT/(q.PREFIX+'-real-prelaunch-v6')).exists()
