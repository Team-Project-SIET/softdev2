import socket,json,errno
from pathlib import Path

def states(port):
 return [r.split()[3] for r in Path('/proc/net/tcp').read_text().splitlines()[1:] if int(r.split()[1].split(':')[1],16)==port]
def bind(port,host,reuse):
 with socket.socket() as s:
  s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,int(reuse))
  try:s.bind((host,port));return 'PASS'
  except OSError as e:return errno.errorcode[e.errno]
rows=[]
for host in ('127.0.0.1','0.0.0.0'):
 for old_reuse in (False,True):
  for active in ('never_accepted','server','client','accepted_survives'):
   l=socket.socket();l.settimeout(2);l.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,int(old_reuse));l.bind((host,0));port=l.getsockname()[1];l.listen()
   if active!='never_accepted':
    c=socket.socket();c.settimeout(2);c.connect(('127.0.0.1',port));s,_=l.accept();s.settimeout(2)
   if active in ('server','client'):
    a,p=(s,c) if active=='server' else (c,s);a.shutdown(socket.SHUT_WR);assert p.recv(1)==b'';p.close();assert a.recv(1)==b'';a.close()
   l.close()
   row=dict(host=host,old_reuse=old_reuse,active_close=active,kernel_states=states(port),new_loopback_no_reuse=bind(port,'127.0.0.1',False),new_loopback_reuse=bind(port,'127.0.0.1',True),new_wildcard_no_reuse=bind(port,'0.0.0.0',False),new_wildcard_reuse=bind(port,'0.0.0.0',True));rows.append(row)
   if active=='accepted_survives':s.close();c.close()
for v6only in (0,1):
 with socket.socket(socket.AF_INET6,socket.SOCK_STREAM) as l:
  l.setsockopt(socket.IPPROTO_IPV6,socket.IPV6_V6ONLY,v6only);l.bind(('::',0));l.listen();rows.append(dict(ipv6_wildcard_v6only=v6only,ipv4_loopback_rebind=bind(l.getsockname()[1],'127.0.0.1',False)))
Path('/tmp/endpoint-v5-diagnosis/socket-matrix.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows,indent=2))
