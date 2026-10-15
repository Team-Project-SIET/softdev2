import ast
import hashlib
import json
from pathlib import Path

before=json.loads(Path('/tmp/qualification-lineage-protected.json').read_text())
for name,expected in before.items():
    assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==expected,name
roots={Path(n).parts[2] for n in before if n.startswith('artifacts/runtime/') and len(Path(n).parts)>3}
for root in roots:
    directory=Path('artifacts/runtime')/root
    expected={n for n in before if Path(n).is_relative_to(directory)}
    actual={str(p) for p in directory.rglob('*') if p.is_file() and p.name!='.admin-secret'}
    assert actual==expected,root
from app.simulation.openttd.proof.historical_protection import validate_protection
v2=Path('artifacts/runtime/openttd-15.3-two-rollover-qualification-real-prelaunch-v2')
old_count=validate_protection(Path.cwd(),json.loads((v2/'historical-integrity.json').read_text()))
paths=list(Path('app/simulation/openttd').glob('qualification*.py'))+list(Path('app/simulation/openttd/proof').glob('*lineage.py'))+list(Path('app/simulation/openttd/proof').glob('qualification*.py'))+[Path('app/simulation/openttd/proof/offline_verification.py'),Path('tests/test_historical_attempt_lineage.py'),Path('tests/test_qualification_dispatch_repair.py'),Path('tests/test_qualification_preparation.py')]
for p in paths:
    text=p.read_text()
    assert all(line.rstrip()==line for line in text.splitlines()),p
    if str(p).startswith('app/'):
        for n in ast.walk(ast.parse(text)):
            modules=[a.name for a in n.names] if isinstance(n,ast.Import) else [n.module or ''] if isinstance(n,ast.ImportFrom) else []
            assert not any(m.startswith('app.planning') or 'evaluation' in m for m in modules),(p,modules)
    assert '[DEBUG-' not in text,p
print(json.dumps(dict(protected_public_files=len(before),historical_protection_v2=old_count,historical_integrity='PASS',whitespace='PASS',import_boundary='PASS',debug_instrumentation='NONE',files_checked=len(paths)),indent=2))
