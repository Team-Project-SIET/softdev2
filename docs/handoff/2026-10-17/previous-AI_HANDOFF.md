# AI handoff — 2026-10-16

Read this with [CONTEXT.md](CONTEXT.md), [TASKS.md](TASKS.md),
[EVIDENCE_INDEX.md](EVIDENCE_INDEX.md), and [REPRODUCE.md](REPRODUCE.md).
This package describes the local worktree, not merely the Git commit. It grants
no runtime authority. No implementation changes are part of this handoff.

## Repository identity and preservation

VERIFIED repository identity: branch `devmodule2`, HEAD
`ea8e92fe3912d034b1d33923c2e71a20b0b1438f` (E1). Before this handoff there
were 19 modified tracked files and extensive untracked implementation, tests,
documentation and fixtures. Exact paths are in E1; file hashes are in E2.
Do not discard, reset, clean, auto-stage, or commit this work on the assumption
that it belongs to the handoff. The untracked root `--version` is an executable
file of unknown purpose: preserve it and do not execute it.

No `AGENTS.md` was found in the repository or its ancestor directories through
`/` during inspection. `.agents/` and `.codex/` are empty restricted directories.
There is no existing AGENTS file to edit or silently replace. Established rules
in CONTEXT, specifications, proof documents and production validators remain in
force. If another checkout has AGENTS.md, read and reconcile it before changes.
No rules were intentionally relaxed. The pre-handoff CONTEXT bytes are preserved
as `docs/handoff/context-before.md`; its older implementation-status section is
historical, superseded by this dated handoff.

## Status vocabulary

| Label | Meaning |
|---|---|
| VERIFIED | A stated proposition supported by identified inspected evidence; scope and whether freshly executed must be explicit. |
| PARTIAL | Some relevant evidence exists, but at least one required gate is missing. |
| PREPARED | Source/package/contracts exist; native execution acceptance is not established. |
| FAILED | A consumed attempt or check failed; later repair never rewrites its outcome. |
| UNKNOWN | Evidence is missing, unavailable, or not inspected sufficiently. |

A test passing with controlled peers verifies that test's behavior, not native
compatibility. A retained report verifies that the report records an outcome;
its presence alone does not independently replay or authenticate that outcome.

## Architecture and ownership

Python owns domain contracts, candidate generation, OR-Tools CP-SAT selection,
validation, evidence binding and offline verification. P08 generates bounded road
candidates from admitted observations and supplemental facts; P05 selects supplied
candidates. It is not arbitrary terrain routing or YAPF. `app/planning/` owns those
contracts; `app/planning/preparation/` contains local world preparation/extraction.

`app/simulation/openttd/` owns secure AdminPort transport, bounded GameScript JSON,
world/industry/cargo/production/terrain observation and freight verification.
`freight_delivery_package/*.nut` contains the native bridge. Python sends correlated
requests; GameScript runs synchronous company commands under `GSCompanyMode`, then
independent state readback and receipts establish outcomes. `proof/` owns isolated
preparation, one-shot launches, retention, immutable identity and cleanup.
`runtime/` owns process/config/asset boundaries. Keep optimization in Python and
change the smallest integration boundary; do not rewrite unrelated planner logic.

`app/experiments/` owns CLI, offline P07 analysis, comparison, deterministic feedback,
capacity experiments and history. `app/database/`, `alembic/` and PostgreSQL support
persistence; tests also use in-memory SQLite. `prototype/live_admin/` is historical.
`tests/reference/` holds pinned source excerpts, `tests/fixtures/` controlled and
historical checkpoints. `reports/` and `ther.md` are supplementary historical notes,
not new execution evidence. E2 inventories the complete nonsecret source/doc tree;
architecture inspection concentrated on entry points, contracts, tests and proof
boundaries, not a claim of line-by-line review of every file.

## Current implementation and evidence limits

| Area | Status at handoff and supporting evidence |
|---|---|
| Save path and canonical orchestration guards | VERIFIED controlled: 47 tests freshly passed, E4. |
| Q1 canonical creation | FAILED: retained result records 1 launch, 0 connections, 0 mutations, native script/asset error; no canonical save. E5. |
| Q2 repair | PREPARED for native qualification. Direct instance-slot delegates replace command-bearing closure `.call` boundaries; absolute save helper and controlled tests exist. E4/E6/E7. No native Q2 result or claim was present at inventory time. |
| Exact 15.3 VM suspension | Retained seven-case report records expected positive and negative behavior, E6. Fresh rerun is separately recorded in E8; it uses controlled API peers and is not native construction. |
| Single/multiple service native freight | PARTIAL overall product scope. README and retained Attempts 4/9/12/17 record delivery milestones; no full historical replay was run for this handoff. E9. Arbitrary maps, rail and autonomous closed-loop optimization remain unproven. |
| Five-year Attempt 19 | FAILED historical native terminal. PARTIAL acceptance: separate derived offline recovery records five years; original evidence remains immutable. E10. Never relabel native terminal as success. |
| Capacity fourth vehicle / telemetry / matched A-B | PREPARED, controlled implementation only. Native readiness blocked on canonical save, fresh-process reload, paused correspondence and intervention. E7. |
| Terrain single-page native vs offline acceptance | PARTIAL: documentation supports historical native REAL_PASS; full historical offline acceptance AUDIT_BLOCKED by 13 missing canonical inputs. E11. No recovery or waiver is implied. |
| Multi-page terrain / two-sweep acquisition | PREPARED/local controlled work; native completeness and end-to-end acceptance UNKNOWN here. Read dedicated contracts before reuse. E12. |
| Full suite, PostgreSQL suite, broad lint/typecheck on this exact tree | UNKNOWN for this handoff; prior counts in docs are historical reports, not reruns. |

## Q1/Q2 and safety rules

Target OpenTTD is **15.3**, Linux generic amd64. OpenTTDLab 13.4 results and fixtures
are historical regression evidence only. Prefer verified local 15.3 docs, official
15.3 documentation and source over old behavior. Remote documentation completeness
is UNKNOWN. Do not infer 15.3 compatibility from 13.4 passes.

Q1 `canonical-fleet-create-q1` is consumed and immutable. The closure `.call` native
VM frame prevented suspension at the first industry command. A relative diagnostic
save also resolved through native SAVE_DIR and failed. Keep the original result,
logs, source archive, PRELAUNCH digest and manifest intact. Do not retry Q1.

Q2 `canonical-fleet-create-q2` is already prepared locally. Do not run its prepare
command again into that directory. Existing staging contains a private runtime
credential: transfer public evidence separately and provision private credentials
through a secure local channel; never copy it into this documentation or Git.
VM validation must use clean OpenTTD source commit
`14ec60f248547d4d062a1160f0fc26d742319888`, real suspension/resumption and the
negative old-boundary cases. A generic Squirrel parser cannot replace this check.
Report destinations must be fresh, and preparation binds report/helper/package
hashes. Never overwrite the frozen suspension report to make preflight pass.

Saving requires an absolute quoted filename within the authorized artifact directory,
without `.sav` (native ConSave appends it). Reject aliases, symlinks, traversal and
existing targets. Require a unique fresh exact native acknowledgement, a nonempty
regular file and SHA-256. Diagnostic saving may tolerate the prior recorded script
failure but requires a live owned process and rejects new save errors. Preserve the
original startup exception separately from diagnostic-save failure. See E4/E7.

No OpenTTD launch, AdminPort connection, reload, Attempt 20 consumption or matched arm
is authorized by this handoff. Every future native stage needs explicit separate
one-launch authorization bound to its reviewed identity, frozen inputs, ports,
budgets and cleanup rules. Preparation/preflight is not launch permission. No retry,
reconnect, auto-resume or manual PRELAUNCH edits to bypass a gate. Reload is a distinct
launch after successful creation review; A/B/C each need their own authority.

Treat retained evidence and historical commitments as read-only. Use a fresh output
for derived analysis. Never regenerate old manifests/seals, rewrite statuses, repair
missing history with invented bytes, or delete failure diagnostics. The externally
reviewed PRELAUNCH digest is authority; mutable manifests and SEAL self-checks are
not independent authorization. CONTROLLED cannot become REAL evidence. Unknown
policies, missing inputs and mismatched gates fail closed. Preserve exact canonical
inventories, ownership/materialization provenance, historical absolute-root binding,
log ranges, authentication lineage, endpoint observations and cleanup attestations
(E11). Existing broader inventories do not replace the 1,868-artifact/1,847-path
historical baseline. The missing original 24-case audit matrix remains missing;
the reconstructed summary is explicitly secondary provenance.

Keep credentials out of logs/docs/Git. `.env` is ignored; `.env.example` was already
untracked before this work. Do not print secret values or bulk-stage files.
Ignored `artifacts/` is essential local evidence and is not transported by a normal
Git clone. Preserve it securely with E3, excluding private credentials; absolute-root
contracts may require the original path or separately reviewed relocation, never
editing a historical seal to fit a new machine.
