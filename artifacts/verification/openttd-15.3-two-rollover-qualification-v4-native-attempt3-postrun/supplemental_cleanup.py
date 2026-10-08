import json,subprocess
from pathlib import Path
from app.simulation.openttd.proof.native import load_prepared,matching_processes
from app.simulation.openttd.proof.ownership import dispose_and_verify
out=Path('/tmp/qualification-attempt3-v4-verification');f=Path('artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v4');m=json.loads((f/'PRELAUNCH.json').read_text());p=Path(m['attempt_directory']);life=json.loads((p/'process-lifecycle.json').read_text());assert life['reaped'] and life['returncode']==0 and not life['remaining_processes'] and not life['cleanup_error']
assert not matching_processes(Path(m['argv'][0]))
ports=[m['game_port'],m['admin_port']];rows=[]
for port in ports:
 text=subprocess.check_output(['ss','-tan','sport = :'+str(port)],text=True);rows.append(text);assert 'LISTEN' not in text and 'ESTAB' not in text
(out/'owned-endpoints-readonly.txt').write_text('\n'.join(rows))
prepared=load_prepared(f,mode=m['mode']);key_removed=not prepared.key_path.exists();assert key_removed
result=dispose_and_verify(prepared,json.loads((f/'source-freeze.json').read_text()));result.update(public_cleanup_gate='FAILED',public_failure_preserved=True,process_reaped=True,credential_removed_by_public_finally=key_removed,no_owned_listener_or_established_connection=True,additional_launches=0,additional_connections=0,additional_requests=0)
(out/'supplemental-cleanup.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
