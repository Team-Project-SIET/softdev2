import socket,json,errno,tempfile,time
from pathlib import Path
from types import SimpleNamespace
from app.simulation.openttd.proof.harness import EndpointReservation
from app.simulation.openttd.proof.endpoints import verify_cleanup_endpoints
r=EndpointReservation.allocate();game=r.game_port;r.close()
s=socket.socket();s.settimeout(2);s.bind(('127.0.0.1',0));s.listen();port=s.getsockname()[1];c=socket.socket();c.settimeout(2);c.connect(('127.0.0.1',port));a,_=s.accept();a.settimeout(2);events=[]
a.shutdown(socket.SHUT_WR);assert c.recv(1)==b'';events.append(['server_FIN_observed',time.monotonic()]);c.close();assert a.recv(1)==b'';a.close();s.close();events.append(['all_sockets_closed',time.monotonic()])
try:held=EndpointReservation.allocate(game,port);held.close();raise AssertionError('Expected naive false rejection')
except OSError as e:assert e.errno==errno.EADDRINUSE;events.append(['naive_EADDRINUSE',time.monotonic()])
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'PRELAUNCH.json').write_text(json.dumps(dict(game_port=game,admin_port=port)));v=verify_cleanup_endpoints(SimpleNamespace(directory=p,endpoints=(game,port)),dict(reaped=True,remaining_processes=[],cleanup_error=[]),r);assert v['sockets_closed'];events.append(['semantic_verifier_PASS',time.monotonic()]);print(json.dumps(dict(events=events,verification=v),indent=2))
