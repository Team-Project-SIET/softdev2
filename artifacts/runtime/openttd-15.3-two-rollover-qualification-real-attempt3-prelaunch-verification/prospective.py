"""Replay only the frozen regression tests against controlled consumed history."""
import json
import tempfile
from pathlib import Path

import pytest

from app.simulation.openttd.proof.harness import manifest
from app.simulation.openttd.proof.qualification_lineage import PREFIX,KIND

with tempfile.TemporaryDirectory(prefix='qualification-consumed3-') as temporary:
 root=Path(temporary)
 for number in (1,2,3):
  suffix='' if number==1 else f'-v{number}'
  freeze=root/f'{PREFIX}-real-prelaunch{suffix}';freeze.mkdir()
  (freeze/'PRELAUNCH.json').write_text(json.dumps(dict(mode=KIND,prelaunch_revision=number)))
  native=root/f'{PREFIX}-real-attempt{number}';native.mkdir()
  record=dict(status='REAL_SUCCESS' if number==3 else 'REAL_FAILED',launches=1,connections=1,requests_sent=1,preparation=str(freeze),attempt_id=f'two-rollover-qualification-v{number}-native-attempt{number}',states=['COMPLETED'] if number==3 else ['FAILED'])
  (native/'proof-evidence.json').write_text(json.dumps(record))
  (native/'artifact-manifest.sha256').write_text(manifest(native))
 source=Path('artifacts/runtime')/f'{PREFIX}-real-prelaunch-v2'/'attempt-lineage.json'
 (root/f'{PREFIX}-real-prelaunch-v2'/'attempt-lineage.json').write_bytes(source.read_bytes())
 class ControlledHistory:
  def pytest_runtest_setup(self,item):
   item.module.ROOT=root
 result=pytest.main(['-ra','--tb=long','tests/test_historical_attempt_lineage.py::test_current_next_attempt_preserves_frozen_identity','tests/test_historical_attempt_lineage.py::test_next_attempt_requires_new_freeze','--junitxml=/tmp/qualification-attempt3-prelaunch-review/prospective.xml'],plugins=[ControlledHistory()])
 print('CONTROLLED_POST_CONSUMPTION_EXIT',result)
 raise SystemExit(result)
