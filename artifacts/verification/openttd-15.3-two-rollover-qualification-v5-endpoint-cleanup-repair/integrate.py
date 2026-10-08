from pathlib import Path
root=Path('app/simulation/openttd/proof')
for name in ('world_attempt','production_attempt','cargo_attempt','cargo_page_attempt','industry_attempt','inventory_attempt','catalog_attempt','enrichment_attempt','structural_attempt','raw_production_attempt'):
 p=root/(name+'.py');s=p.read_text();anchor='from .harness import';pos=s.index(anchor);s=s[:pos]+'from .endpoints import verify_cleanup_endpoints\n'+s[pos:]
 import re
 pattern=r'(?P<indent> +)(?P<var>closed_endpoints|closed|endpoints|ports|held) = EndpointReservation.allocate\(\*prepared.endpoints\)\n(?P=indent)(?P=var).close\(\)'
 s,count=re.subn(pattern,lambda m:m['indent']+'cleanup.update(verify_cleanup_endpoints(prepared, cleanup, reservation))',s)
 assert count==1,(name,count)
 # Direct callers should preserve semantic failures as well as kernel read errors.
 s=s.replace('except OSError:\n            cleanup["sockets_closed"]', 'except (OSError, ValueError):\n            cleanup["sockets_closed"]')
 p.write_text(s)
p=root/'attempt.py';s=p.read_text();s=s.replace('from .gamescript_evidence import', 'from .endpoints import verify_cleanup_endpoints\nfrom .gamescript_evidence import');s=s.replace('raise RuntimeError("Process/session cleanup incomplete")','raise RuntimeError("Process/session cleanup incomplete")\n            lifecycle.update(verify_cleanup_endpoints(prepared, lifecycle, reservation))');p.write_text(s)
