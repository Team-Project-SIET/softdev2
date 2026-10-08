"""Retain the prelaunch stop through the repository's evidence serializer only."""
import hashlib
import json
import shutil
from pathlib import Path

from app.simulation.openttd.proof.harness import PROJECT,manifest,verify_freeze
from app.simulation.openttd.proof.historical_protection import validate_protection
from app.simulation.openttd.proof.qualification_lineage import read_attempt,validate_historical_attempt
from app.simulation.openttd.proof.world_attempt import record_prelaunch_failure

root=PROJECT/'artifacts/runtime'
f=root/'openttd-15.3-two-rollover-qualification-real-prelaunch-v3'
m=json.loads((f/'PRELAUNCH.json').read_text())
source=json.loads((f/'source-freeze.json').read_text());verify_freeze(source)
history=json.loads((f/'historical-integrity.json').read_text());validate_protection(PROJECT,history)
freeze_public={str(p.relative_to(f)):hashlib.sha256(p.read_bytes()).hexdigest() for p in f.rglob('*') if p.is_file() and p.name!='.admin-secret'}
reason=('PRELAUNCH acceptance-readiness validation failed: V3-frozen test_current_next_attempt_preserves_frozen_identity and test_next_attempt_requires_new_freeze fail after controlled Attempt 3 consumption; tests still request the consumed Attempt 3 execution destination. 2 deterministic failures. Native execution not started; no retry performed.')
archive=root/'openttd-15.3-two-rollover-qualification-real-attempt3-prelaunch-verification'
archive.mkdir(exist_ok=False)
for p in Path('/tmp/qualification-attempt3-prelaunch-review').iterdir():
 if p.is_file():shutil.copyfile(p,archive/p.name)
(archive/'freeze-public-before.json').write_text(json.dumps(freeze_public,sort_keys=True,indent=2)+'\n')
# Evidence recording does not call any run/launch/connection path.
record_prelaunch_failure(f,ValueError(reason))
gate=f.with_name(f.name+'-gate-failure')
identity=read_attempt(gate)
assert identity.classification=='PRELAUNCH'
assert (identity.launches,identity.connections,identity.requests)==(0,0,0)
assert not Path(m['attempt_directory']).exists()
verify_freeze(source);validate_protection(PROJECT,history)
after={str(p.relative_to(f)):hashlib.sha256(p.read_bytes()).hexdigest() for p in f.rglob('*') if p.is_file() and p.name!='.admin-secret'}
assert after==freeze_public
assert (f/'artifact-manifest.sha256').read_text()==manifest(f)
for n in (1,2):
 old=root/('openttd-15.3-two-rollover-qualification-real-prelaunch'+('' if n==1 else '-v2'))
 oldmeta=json.loads((old/'PRELAUNCH.json').read_text())
 validate_historical_attempt(old,Path(oldmeta['attempt_directory']))
summary=dict(attempt=m['attempt_id'],freeze=str(f),destination=m['attempt_directory'],overall='FAILED',classification='PRELAUNCH_FAILURE',native_runtime='NOT_STARTED',failure_phase='PRELAUNCH_ACCEPTANCE_READINESS',reason=reason,launches=0,connections=0,requests=0,retries=0,reconnects=0,resume=False,current_history_regressions='25 PASSED',prospective_post_consumption_regressions='2 FAILED (two deterministic reproductions)',source_integrity='PASS',protected_historical_integrity='PASS',v3_public_freeze_unchanged=True,native_destination_created=False,source_repaired=False,v3_modified=False,v4_created=False,gate_evidence=str(gate))
(archive/'verification.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
(archive/'artifact-manifest.sha256').write_text(manifest(archive))
print(json.dumps(summary,indent=2))
