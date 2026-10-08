import socket,json,errno
from pathlib import Path
from app.simulation.openttd.proof.harness import EndpointReservation
s=socket.socket();s.settimeout(2);s.bind(('127.0.0.1',0));s.listen();port=s.getsockname()[1]
c=socket.socket();c.settimeout(2);c.connect(('127.0.0.1',port));a,_=s.accept();a.settimeout(2)
a.shutdown(socket.SHUT_WR);assert c.recv(1)==b'';c.close();assert a.recv(1)==b'';a.close();s.close()
rows=[r for r in Path('/proc/net/tcp').read_text().splitlines()[1:] if int(r.split()[1].split(':')[1],16)==port]
try:
 held=EndpointReservation.allocate(0,port);held.close();verdict='PASS'
except OSError as e:
 assert e.errno==errno.EADDRINUSE;verdict='EADDRINUSE'
print(json.dumps(dict(server_port=port,server_sockets_closed=True,kernel_rows=rows,naive_verdict=verdict)))
assert verdict=='PASS','closed listener falsely rejected by cleanup verifier'
