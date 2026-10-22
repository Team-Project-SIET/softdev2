"""Read-only handoff links and captured implementation/evidence byte checks."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DOCS = [
    'AI_HANDOFF.md', 'TASKS.md', 'EVIDENCE_INDEX.md', 'REPRODUCE.md',
    'CONTEXT.md', 'README.md', 'examples/openttd-demo/README.md',
    'docs/random-world-demo.md', 'docs/random-world-distance-support.md',
    'docs/capacity-experiment.md',
]
errors = []
counts = {}
for inventory in ('implementation-before.json', 'evidence-hashes.json'):
    values = json.loads((HERE / inventory).read_text())
    checked = 0
    for name, expected in values.items():
        # The demo guide is the sole intentional documentation edit inside examples.
        if name == 'examples/openttd-demo/README.md':
            continue
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(f'Changed or missing captured file: {name}')
        checked += 1
    counts[inventory] = checked
links = 0
for name in DOCS:
    path = ROOT / name
    text = re.sub(r'```.*?```', '', path.read_text(), flags=re.S)
    for match in re.finditer(r'(?<!!)\[[^\]]+\]\(([^)]+)\)', text):
        target = match[1].split('#', 1)[0]
        if not target or '://' in target or target.startswith('mailto:'):
            continue
        destination = (path.parent / unquote(target)).resolve()
        if not destination.exists():
            errors.append(f'Missing link in {name}: {target}')
        links += 1
print(json.dumps(dict(status='FAIL' if errors else 'PASS', checked=counts,
                      local_links=links, errors=errors), indent=2))
raise SystemExit(bool(errors))
