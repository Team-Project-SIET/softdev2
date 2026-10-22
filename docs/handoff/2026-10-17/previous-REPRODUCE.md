# Reproduce and verify safely

Run from `/home/fed/codes/softdev2`. This package targets Python 3.14
(`mise.toml`: 3.14.6), OpenTTD 15.3 Linux amd64. `pyproject.toml` and `uv.lock`
are dependency authority: openttdlab 0.0.75, OR-Tools, SQLAlchemy, Alembic,
psycopg, Pydantic/settings, pymonocypher 4.0.3.2; dev pytest/Ruff and
squirrel-lang 0.3.1. Use `uv sync --locked` to build a fresh environment when
needed, with network/install permission appropriate to that machine. Do not
replace the existing environment merely to inspect the handoff.

Inspect `git status --short --untracked-files=all`, `git branch --show-current`
and `git rev-parse HEAD`; compare E1/E2. A clone of HEAD alone omits the dirty
implementation and ignored evidence. Transfer the worktree securely; retain
source/diff and untracked files independently of Git. Do not bulk-copy `.env`,
private runtime credentials, agent account folders or cached authentication.
Public artifact hashes in E3 are an inventory, not an authenticated backup or
new historical protection authority. Verify transferred files against it; resolve
missing originals explicitly. Preserve historical absolute roots when required.

## Freshly run during handoff

```bash
.venv/bin/pytest -q tests/test_native_save_path.py tests/test_canonical_fleet_driver.py
```

47 passed, exit 0. E4 retains output. Tests use controlled seams and temporary
files; they do not launch OpenTTD or connect to AdminPort.

The exact embedded-VM check can compile a standalone C++ host without starting
OpenTTD. Requires `g++` with C++20 support and clean pinned OpenTTD source. The
inspected local checkout is `/tmp/canonical-squirrel-15.3`; temporary locations
are not durable dependencies and may disappear. For a replacement checkout use
OpenTTD's official source and exact commit
`14ec60f248547d4d062a1160f0fc26d742319888`, including Squirrel, core, fmt and
script headers. Follow the helper's source-checkout instructions and verify
`git rev-parse HEAD` plus no tracked `src` diff before execution.

Use a **fresh** report name (replace the example if it exists):

```bash
PYTHONPATH=. .venv/bin/python tests/validate_canonical_squirrel.py \
  --source /tmp/canonical-squirrel-15.3 \
  --report /tmp/next-agent-suspension-review.json
```

Never target `artifacts/validation/canonical-fleet-create-q2/suspension.json`:
that is frozen evidence. Acceptance is all seven expected positive/negative cases,
matching helper/package provenance and unchanged protected inputs. Standalone VM
success does not establish native game command behavior or save/reload success.
Fresh handoff rerun details are E8.

## Broader checks, not run for this handoff

Read relevant test code before expanding scope. Repository defaults make native
and PostgreSQL tests opt-in; never add `--run-openttd` for an offline review.
Suggested ordinary commands, whose results remain UNKNOWN until executed:

```bash
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
git diff --check
```

Focused typecheck examples are in README; `ty` is not a locked project dependency,
so record its exact version if using `uvx ty`. Do not format implementation files
as part of a handoff. PostgreSQL integration requires a separately configured
isolated database (`--run-postgres`), PostgreSQL 16 Compose service, migrations
and local credentials. Never use a production/shared database for tests. See
`tests/postgres_support.py`, `alembic/` and `app/config.py`. No DB was started here.

## Native reproducibility prerequisites — no launch authority

The driver currently pins binary path
`/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd` and expected SHA-256
`276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`
(`proof/harness.py`). Binary existence/digest and external assets must be checked
again before any future readiness approval; this handoff did not execute it.
Graphics archive identity/staging live in `proof/graphics.py`, runtime asset
contracts in `runtime/assets.py`; preserve the frozen graphics-identity record,
content/heightmap, generated effective settings and source archive per attempt.
Do not substitute a different 15.x build or rely on host default config/save paths.

Future native work requires reviewed frozen sources, matching staged package and
VM validation, isolated owned workspace, one encrypted authorized-key session,
reserved game/Admin endpoints, explicit request/frame/log/artifact/time budgets,
independent correspondence/readback and full cleanup evidence. Exact stage commands
and policies live in `docs/capacity-experiment.md`; they are historical/reference
instructions, not permission to execute. Existing Q2 preparation must not be recreated.
Read AI_HANDOFF and TASKS before any native action.

Offline historical replay commands in README may write derived output. Use a fresh
output directory, never an existing immutable package. Attempt 19 recovery has a
separate derived-finalization authority; keep the original FAILED result. Missing
historical canonical inputs cannot be fixed by rerunning a generator or updating
manifests. A passing current validator does not retroactively upgrade an old seal.
