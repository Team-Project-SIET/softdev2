"""Read-only comparison with handoff snapshots; never imports game runtime code."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'docs/handoff'
errors = []
counts = {}
for name in ('repository-files-before.json', 'local-artifacts-before.json'):
    rows = json.loads((BASE / name).read_text())
    counts[name] = len(rows)
    for row in rows:
        path = ROOT / row['path']
        if row['path'] == 'CONTEXT.md':
            path = BASE / 'context-before.md'
        if path.is_symlink() or not path.is_file():
            errors.append({'path': row['path'], 'error': 'missing or nonregular'})
            continue
        with path.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != row['sha256']:
            errors.append({'path': row['path'], 'error': 'hash mismatch'})
print(json.dumps({'scope': 'Captured public files only; additions and credentials excluded. CONTEXT checked against archived pre-edit copy.', 'counts': counts, 'errors': errors, 'passed': not errors}, indent=2))
raise SystemExit(bool(errors))
