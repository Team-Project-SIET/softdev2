# Native execution attempt analytics — offline run-level metrics (parallel workstream)

Status: **implemented and verified on 2026-10-25** in isolated worktree
`/home/fed/codes/softdev2-attempt-analytics` (detached `devmodule2` at
`775ecab`) and **integrated into the main checkout** (`devmodule2`, dirty
working tree over the same base `775ecab`) on 2026-10-25; see §8. This is the
analytics feature of the parallel workstream "OpenTTD Analytics Feature
Completion"; it is offline and read-only. No native launch, AdminPort
connection, authorization, claim, signing or candidate consumption is
included, and nothing was staged, committed or pushed.

During the isolated workstream this document did not touch the Obsidian vault
(`OpenTTD-Knowledge/`), which is governed by its own impact-review rules. At
integration the vault received only the scoped updates recorded in §8; the
retained attempt evidence stayed byte-identical throughout.

## 1. Capability inventory (pre-existing; verified in the worktree)

Verified against the committed baseline plus the retained records:

| Capability | Existing implementation | Reused here |
|---|---|---|
| Single-run planned/actual evaluation | `app/experiments/freight_evaluation.py` | No (different artifact family) |
| Cohort summaries + SVG/HTML/CSV | `app/experiments/freight_analytics.py` (`summarize`, `render_html`, `analyze`, `_bars`) | `_bars` reused |
| Continuous five-year reporting | `app/experiments/freight_continuous_analytics.py` | No |
| Fixed-demo terminal snapshot + report comparison | `app/demo_operations.py` | No |
| Bottlenecks/advisories/comparisons over P07 reports | `app/experiments/performance_insights.py` | Contract/report style reused |
| Content-addressed freight run history | `app/experiments/freight_history.py` | No |
| Corridor phase verification contracts | `app/simulation/openttd/corridor_construction.py` (`corridor_phase_outcome`) | Unchanged, not imported |

## 2. The concrete gap

The requirements-evidence matrix lists D2/D3/D4 native attempts separately,
each with only narrative status; nothing aggregates *run-level* facts above a
single attempt. In particular:

1. No structured planned-vs-executed execution metrics per attempt (ops,
   request budget/usage, per-op cost vs the retained per-op ceiling).
2. No cross-attempt comparison inside a milestone lineage (schedule revisions
   v1→v2→v3, halt surfaces, evidence prefixes).
3. No bounded, evidence-backed effectiveness observation over the schedule
   revisions — and no honest guard that stops it from becoming a causal claim
   from one or two runs.

## 3. What was added (additive only)

- `app/experiments/native_attempt_analytics.py`
  - Reads each retained native attempt directory: `PRELAUNCH.json` (plan-side
    schedule, budgets, per-op ceiling, plan digest, source world), `result.json`
    (executed counters, phase receipts, halt/pending marks, verbatim statuses),
    `cleanup.json` (fail-closed certification) plus consumption markers
    (`LAUNCH-CONSUMED.json`, `CLAIM.json`), never writing to inputs.
  - Emits `AttemptAnalytics` (run-level facts and DERIVED ratios),
    `MilestoneLineage` groups with adjacent-attempt deltas, and documented
    observation codes:
    - `SCHEDULE_REVISED` — plan schedule revision between attempts.
    - `DESCRIPTIVE_EVIDENCE_PREFIX_SEQUENCE` — receipt-backed executed-op
      fraction of *each attempt's own planned ops*; each fraction compares an
      attempt with its own plan. Direction words (`non-decreasing` /
      `non-increasing` / `mixed`) are descriptive only and the statement
      explicitly refuses causal claims; the statement also says records whose
      verified flag is false stay outside the verified outcome count.
    - `HALT_SURFACES` — halt labels and verified flags copied verbatim.
    - `UNRELATED_SOURCE_WORLDS` / `INSUFFICIENT_IDENTITY` /
      `INSUFFICIENT_DATA` / `INSUFFICIENT_ATTEMPTS` — fail-closed guards; a
      pooled sequence is only stated when every attempt shares exactly one
      source-world identity and its prefix fraction is known.
  - Outputs (`.`-free, deterministic, no timestamps): `execution-metrics.json`
    (schema 1), `attempt-ops.csv` (per-op RECEIPT/HALT/PENDING rows),
    `execution-report.md`, `execution-charts.html` (bounded SVG via the
    existing `_bars` generator; unknown values stay visible), and
    `terminal-summary.txt`.
- `app/experiments/cli.py`: additive subcommand
  `analyze-native-attempts SOURCE [SOURCE…] --output DIR` (exit 1 with
  `analysis rejected: …`, no output created, on malformed documents).
- `tests/test_native_attempt_analytics.py`: 34 focused tests (synthetic
  attempts + read-only retained-evidence regressions SKIPped when the records
  are absent).

## 4. Truthfulness rules carried over

- Statuses (`PHASE_HALTED_PREFIX_PRESERVED`, `FAILED_CLEANUP`,
  `NATIVE_STATE_VERIFIED`, …) and `verified` flags are copied verbatim;
  nothing is relabeled.
- `verified_outcomes` counts only records whose own `verified` flag is true;
  partial/failed records count separately and never enter the verified count,
  matching "exclude unverified or failed attempts from success metrics".
- The receipt-backed evidence-prefix fraction is explicitly *not* a success
  metric: it is coverage of executed effort against an attempt's own plan.
- UNKNOWN stays UNKNOWN: a dispatched op with a refused response keeps cost
  UNKNOWN (`_FAILURE_NOTE`); no OPEX, profit, ROI or runtime results are
  invented; file presence never certifies an authoritative after-save.
- `cleanup.json` certification is fail-closed: `PASS` only when all four
  conditions are present and true with no errors; `NOT_PASS` when any
  condition is missing or false (it does not claim native cleanup failed);
  `UNKNOWN` with no file.

## 5. Evidence used (retained, read-only)

| Source | Use |
|---|---|
| `artifacts/experiments/d4-corridor-native-candidate-{1,3,4}/` (E21/E28/E31/E32 records; result/PRELAUNCH/cleanup read only) | D4 lineage: planned ops 6/8/7, receipt-backed ops 1/3/6, prefixes 0.1667→0.375→0.8571, op-cost totals £785/£3,334/£4,004, request utilization 0.16/0.3226/0.6786, halts `op-01`/`op-03`/`op-06`, cleanup PASS/NOT_PASS/PASS |
| `artifacts/experiments/d3-terraform-native-candidate-1/` | Verified complete attempt: 16/16 receipts, prefix 1.0, £3,382, PHASE_COMPLETE |
| `artifacts/experiments/d3-clearing-native-candidate-{1,2}/`, `d2-clearing-native-candidate-3/` | Clearing per-command costs £30/£45/£15 and funds; unrelated source worlds guarded |

Copies of these directories were made into the worktree for tests (verified
byte-identical; the originals were never modified). The main checkout's
`M`-state files belong to the active candidate-4 workflow and were not read as
authority for anything beyond what their retained records themselves state.

## 6. Verification performed

- `pytest tests/test_native_attempt_analytics.py` — 34 passed (includes the
  retained-evidence regression tests over all seven record directories).
- Focused adjacent suites unchanged:
  `test_experiment_cli.py`, `test_performance_insights.py`,
  `test_freight_analytics.py`, `test_experiments.py` — 109 passed,
  9 skipped (skips are pre-existing retained-artifact-availability guards).
- `ruff check` and `ruff format --check` clean for the three touched files;
  `compileall` clean. CLI smoke run produced the complete offline example
  (exported to the gitignored
  `artifacts/experiments/native-attempt-analytics-example/` in the worktree):
  7 attempts, 4 verified outcomes, 3 partial/failed outcomes, deterministic
  outputs (two runs → identical bytes).

## 7. Boundaries

- No Git staging/commit/push/reset/clean/stash anywhere; no vault edits during the
  isolated workstream; no candidate/claim operations; no OpenTTD launch or
  AdminPort access.
- The module imports nothing from the active candidate-4 workflow
  (`app/simulation/openttd/proof/corridor_construction_native.py` is modified
  in the active checkout and deliberately not imported or relied upon).
- The schedule-effectiveness observation is a descriptive contrast over three
  retained attempts with changing plans; it never claims a causal effect of
  any revision, and the final D4 outcome remains incomplete (no authoritative
  after-save/receipt for candidate-4; `op-06` remains response-limited).
- Nothing here authorizes or prepares a native attempt. The D4 next step
  (response-size path correction and a fresh candidate) stays with the
  separate authorized workflow.

## 8. Integration into the main checkout (2026-10-25)

The four files were integrated from the isolated worktree into the main
checkout at `/home/fed/codes/softdev2` (branch `devmodule2`, dirty working
tree, same base `775ecab`, E33 protocol fix present and untouched):

- `app/experiments/native_attempt_analytics.py` (new), `app/experiments/cli.py`
  (additive `analyze-native-attempts` subcommand only), `tests/
  test_native_attempt_analytics.py` (new), `docs/native-attempt-analytics.md`
  (this document).

No file overlapped between the worktree diff and the active checkout's
modifications; `cli.py` was unmodified in the main checkout at integration, and
the worktree's change is its documented additive hunk over the identical base.
Integrated file bytes hash-match the worktree copies exactly.

Post-integration verification in the main checkout (all fresh runs, 2026-10-25):

- `pytest tests/test_native_attempt_analytics.py` — **34 passed** (includes the
  retained-evidence regressions over all seven record directories; no skips,
  because every retained directory exists here).
- Adjacent suites `test_experiment_cli.py`, `test_performance_insights.py`,
  `test_freight_analytics.py`, `test_experiments.py` — **84 passed** (the
  retained-artifact-availability skips seen in the worktree do not occur here).
- `ruff check` and `ruff format --check` clean for the three touched code
  files; `compileall` clean; `git diff --check` clean.
- The deterministic example was regenerated from the integrated
  implementation over the seven retained directories into the gitignored
  `artifacts/experiments/native-attempt-analytics-example/`: 7 attempts, 4
  verified outcomes, 3 partial/failed outcomes, 0 unknown; a second run into a
  separate directory produced **byte-identical** outputs for all five files.
- The seven retained evidence directories (626 files) hash-verify
  **byte-identical** before and after the analysis runs; all protocol-fix
  files (`gamescript_transport.py`, `corridor_construction.py`,
  `proof/corridor_construction_native.py` and their three test files) are
  byte-unchanged by the integration. The worktree was left untouched.
- Semantic spot checks over the regenerated example: no OPEX/net-profit/ROI
  field exists anywhere in the metrics document; `D4-CORRIDOR-4` keeps
  `PHASE_HALTED_PREFIX_PRESERVED` / `verified: false` verbatim with no
  success count (`success_ops` null) and `op-06` appears only as a HALT row
  with no cost; cleanup certification stays fail-closed (`NOT_PASS` for
  candidate-3).

Vault updates at integration (scoped, dated 2026-10-25; no retained records
relabelled and `OpenTTD-Knowledge/.obsidian/workspace.json` untouched):
evidence index E34 (root + byte-identical `99-Source-Documents/` copy),
`TASKS.md` item 9 (root + byte-identical `99-Source-Documents/` copy),
`docs/requirements-evidence-matrix.md` row, and the condensed vault notes
(`04-Evidence/Evidence Index.md`, `04-Evidence/Controlled Tests.md`,
`00-Project/Current Status.md`, `07-Reference/Important Paths.md`). D4 remains
**INCOMPLETE (native)**; no candidate, claim, signing, launch or native quote
exists for any fresh attempt.
