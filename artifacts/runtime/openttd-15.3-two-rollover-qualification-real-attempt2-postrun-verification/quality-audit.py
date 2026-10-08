import ast,json
from pathlib import Path
paths=list(Path('app/simulation/openttd').glob('qualification*.py'))+list(Path('app/simulation/openttd/proof').glob('qualification*.py'))+[Path('tests/test_qualification_dispatch_repair.py'),Path('tests/test_qualification_preparation.py')]
for p in paths:
 text=p.read_text();assert all(line.rstrip()==line for line in text.splitlines()),p
 if 'app/' in str(p):
  for n in ast.walk(ast.parse(text)):
   modules=[a.name for a in n.names] if isinstance(n,ast.Import) else [n.module or ''] if isinstance(n,ast.ImportFrom) else []
   assert not any(m.startswith('app.planning') or 'evaluation' in m for m in modules),(p,modules)
root=Path('artifacts/runtime/openttd-15.3-two-rollover-qualification-real-attempt2')
assert not list(root.rglob('.admin-secret'))
assert not any(b'-----BEGIN PRIVATE KEY-----' in p.read_bytes() or b'-----BEGIN OPENSSH PRIVATE KEY-----' in p.read_bytes() for p in root.rglob('*') if p.is_file())
print(json.dumps({'whitespace':'PASS','import_boundary':'PASS','private_key_file_exclusion':'PASS','files_checked':len(paths)}))
