# P07 performance analytics extension — offline inventory and design (Agent B)

Status: **implemented and verified on 2026-10-18** on branch `devmodule2`, date
2026-10-18. This document is the dedicated Agent B analytics
progress/integration document required by the P07 analytics task. It records the
capability inventory, the gaps that were actually implemented, and the
integration notes for later P05 feedback work.

No native launch, AdminPort connection, evidence mutation or commit is included.

## 1. Capability inventory (pre-existing P07 analytics)

Inventory verified against the working tree on 2026-10-18, `devmodule2` baseline
`a348016` plus local uncommitted work. Native evidence packages were read only.

| Capability | Existing implementation | Status |
|---|---|---|
| Single-run receipt evaluation with planned/actual metric comparison, provenance, findings | `app/experiments/freight_evaluation.py` (`evaluate_freight`, `FreightMetric`, `FreightEvaluation`) | Reused as-is |
| Multi-service network evaluation and deterministic initial feedback codes | `app/experiments/freight_network.py` (`evaluate_freight_network`, `optimization_feedback`) | Reused as-is |
| Cohort/descriptive history, CSV/JSON summary, self-contained SVG charts | `app/experiments/freight_analytics.py` (`summarize`, `render_html`, `analyze`, `_bars`) | Reused as-is (`_bars` reused for new charts) |
| Continuous five-year reporting: monthly/quarterly/annual periods, finance reconciliation, setup cash coverage, charts, offline-recovery classification | `app/experiments/freight_continuous_analytics.py`, `app/simulation/openttd/freight_finance.py` (`reconcile_snapshots`, `reconcile_cash`) | Reused as-is |
| Operational terminal summary for the fixed demo (OBSERVED/DERIVED/UNKNOWN labels, milestone rates) | `app/demo_operations.py` (`operational_snapshot`, `terminal_status`, `write_operational_report`) | Reused as-is |
| Descriptive demo report comparison (2..16 P07 report dirs, world metadata retention) | `app/demo_operations.py` `compare_operational_reports` | Reused as-is |
| Controlled P05/p08 allocation alternatives and A/B capacity preparation | `app/experiments/freight_alternatives.py`, `app/experiments/capacity_experiment.py` | Reused as-is (referenced by recommendations) |
| Content-addressed run history | `app/experiments/freight_history.py` | Reused concept; no schema change |
| Economy/game/clock separation metrics | `app/experiments/game_time.py` | Reused as-is |

## 2. Genuine gaps (implemented by this extension)

1. **No structured post-execution insight document.** Existing reports are
   either per-run evaluations or the continuous summary; there is no unified,
   machine-readable answer to "how well did the network perform, where are the
   bottlenecks, what should the optimizer consider next" with declared units,
   observation periods, sources, derivation methods, missing-data behaviour and
   OBSERVED/DERIVED/HYPOTHESIS/UNKNOWN status per metric.
2. **No deterministic bottleneck analysis.** The Attempt 19 bottleneck analysis
   existed only as an ad-hoc reproduction snippet in
   `docs/five-year-freight-performance-analysis.md` (episodes, cadence, waiting
   counts). It is now a deterministic, tested module.
3. **No structured optimization recommendation layer.** The network feedback
   codes are specific to metric-estimate mismatches; there was no general
   advisory record with evidence, reason, confidence, expected improvement
   direction, missing information and suggested next experiment.
4. **No cross-report performance comparison with world identity.**
   `compare_operational_reports` covers fixed-demo report dirs only. There was
   no comparison over continuous reports (`INSUFFICIENT_DATA` semantics,
   matched-world detection, normalized per-economy-day rows).
5. **No future-feedback contract.** The conceptual flow
   Native Observations → P07 evaluation → Operational history → Bottleneck
   detection → Optimization recommendations → Future planning experiments had no
   explicit data contract.

## 3. What was added

Implementation (all additive, Agent B scope):

- `app/experiments/performance_insights.py`
  - `PerformanceInsights` contract (schema 1): observation window, declared
    metrics, per-service summaries, bottleneck assessments, advisory
    recommendations, limitations, optional time series and comparisons.
  - `build_performance_insights()` accepting either a P07 continuous
    `summary.json` document or a network `evaluation.json` document.
  - Deterministic bottleneck detection reproducing the retained Attempt 19
    analysis semantics (unloading episodes, cadence, waiting growth, load/stall
    sample fractions) with explicit `INSUFFICIENT_DATA` behaviour.
  - Deterministic advisory recommendations (advisory only; they never modify
    P05 objectives, purchase vehicles or execute construction).
  - `compare_performance_rows()` with matched-world detection and
    INSUFFICIENT_DATA classification.
  - Renderers: concise terminal summary, Markdown report, bounded SVG charts
    (reusing `_bars`), and `analyze_performance()` writing `insights.json`,
    `performance-report.md`, `terminal-summary.txt` and
    `insights-charts.html` next to (never inside) retained evidence.
- `app/experiments/cli.py`: new offline subcommand
  `analyze-performance-insights SOURCE --output DIR [--compare DIR ...]`.
- `tests/test_performance_insights.py`: controlled fixtures plus read-only use
  of the retained Attempt 19 and fixed-demo evidence.

Implementation details that keep the semantics defensible:

- **Network roll-ups are named distinctly** (`network_delivered_cargo`,
  `network_revenue`, …) so that per-service rows with identical names can never
  shadow the network-level values in lookups; `_network_metric()` resolves
  candidates in priority order.
- **Finance semantics**: CAPEX stays OBSERVED from verified receipts; vehicle
  OPEX, operating profit and ROI remain UNKNOWN while expense attribution is
  incomplete; the retained aggregate expense total and the reconciled
  unattributed cash residual are declared with their boundaries intact.
- **Episode model**: `_episodes()` coalesces consecutive positive delivered-cargo
  increments; any flat, non-positive or missing sample separates episodes. A
  service whose delivered counter starts as `None` (not yet in service) is
  handled: the first real increment opens the first episode instead of crashing
  or merging across the missing baseline.
- **Backlog classification thresholds** (deterministic, unit-tested):
  `INSUFFICIENT_DATA` under 3 samples or no waiting observation; growth ratio >
  1.2 over first-/second-half sample means → `GROWING_BACKLOG_SAMPLE_HYPOTHESIS`;
  positive-waiting fraction ≥ 0.5 with recurring episodes →
  `CAPACITY_BOTTLENECK_HYPOTHESIS`; positive-waiting fraction < 0.5 →
  `NO_SUSTAINED_BACKLOG_OBSERVED`.
- **Comparison statuses**: same world ⇒ pair candidate; pair only becomes
  `MATCHED_DESCRIPTIVE` when both sides have complete normalized data (cargo and
  observation days); same-world rows whose partner lacks comparable data stay
  `INSUFFICIENT_DATA`; different worlds ⇒ `UNRELATED_WORLD`; no known world
  identity ⇒ `INSUFFICIENT_DATA`. World identity is read best-effort from
  retained `PRELAUNCH.json` records (source dir, offline-recovery origin, or the
  evaluation's evidence directory).

## 3a. Complete offline example

`artifacts/experiments/p07-performance-insights-example/` (untracked, inside
the gitignored `artifacts/` tree; no retained evidence directory touched):

| File | Content |
|---|---|
| `insights.json` | Full `PerformanceInsights` document (SHA-traced to the Attempt 19 `summary.json` and its `PRELAUNCH.json` world recipe) |
| `performance-report.md` | Human report: FAILED terminal status, headline metrics, per-service table, bottleneck reasoning, advisory recommendations, limitations |
| `terminal-summary.txt` | Concise operational summary (UNKNOWN stays visible) |
| `insights-charts.html` | Bounded SVG charts reusing the existing P07 `_bars` generator |
| `comparison.json` | `MATCHED_WORLD_COMPARISON` of Attempt 19 (1826 days, 2980 cargo, £50,935 revenue, £28,459 CAPEX) and the fixed demo (163 days, 60 cargo, £1,022 revenue, £28,459 CAPEX), same analytical world recipe (seed 42, 64×64, NATIVE_GENERATED_DEMO), matched-pair rows only |

Command used (offline only):

```
.venv/bin/python -m app.experiments.cli analyze-performance-insights \
  artifacts/experiments/p07-attempt19-five-year-offline \
  --output artifacts/experiments/p07-performance-insights-example \
  --compare artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a-report
```

## 3b. Verification performed

- `pytest tests/test_performance_insights.py` (28 tests) and the related suites
  `test_freight_continuous_analytics.py`, `test_freight_capacity_report.py`,
  `test_freight_alternatives.py`, `test_freight_analytics.py`,
  `test_legacy_retirement.py`, `test_demo_operations.py`,
  `test_experiment_cli.py`, `test_experiments.py` — all pass.
- `ruff check` (whole `app/`) and `ruff format --check` clean for the four
  touched files; `compileall` clean; `git diff --check` clean.
- No typechecker is installed in this environment (pyproject only references a
  `ty` environment section), so type-checking was not run.

## 3c. Independent review outcome

An independent reviewer session traced the module, the CLI block and the tests
(against the requirement contract above), re-ran the suite (28/28, none
skipped), inspected the generated example artifacts and reported
`REVIEW: NO BLOCKERS` with one MAJOR truthfulness defect plus minors, all
resolved in this workspace before finalization:

- **MAJOR (fixed)**: `_episodes` coalescing condition accidentally split
  consecutive positive increments into per-snapshot episodes, contradicting the
  declared derivation. Fixed to `index - last_positive > 1`; a dedicated
  coalescing test was added; example regenerated. Real Attempt 19 results are
  again 51/49/49 episodes with 35–37 economy-day spacing, matching the
  documented five-year bottleneck analysis.
- **Fixed**: `native_terminal_status` is now read from the retained
  `offline_recovery.original_terminal.status` (was hardcoded FAILED per absent
  data; a future recovered run with a different status is no longer relabeled).
- **Fixed**: `delivery_frequency` no longer partially sums — it is UNKNOWN when
  any service series lacks an assessable episode count.
- **Fixed**: `unloading_episodes` stays UNKNOWN from a single delivered sample
  (zero episodes is not stated from one sample).
- **Fixed**: rows with unknown world identity are `INSUFFICIENT_DATA`, never
  presented as `UNRELATED_WORLD`; so are rows failing to normalize (e.g. a
  0-day window).
- **Fixed**: the write guard also protects evidence directories referenced
  inside the retained documents (`offline_recovery.original_directory`,
  `evidence_directory`), resolving relative references against the report dir.
- **Fixed (docstring only)**: `_network_metric` semantics documented exactly
  (first existing candidate wins even when UNKNOWN).
- **Fixed (CLI)**: malformed retained documents (KeyError/TypeError) reject
  cleanly with exit 1 instead of a traceback; no output is created on failure.
- **Fixed**: stale `comparison.json` removal when a rerun has no comparison;
  dead code (`metric_rows`) removed; exception tuple handling (see the PEP 758
  follow-on note below).

Follow-on allowed minors intentionally left as designed: `_bars` private
import matches three sibling modules' precedent; the per-milestone exception
tuple in `performance_insights.py` uses the valid PEP 758 unparenthesized form
`except OSError, json.JSONDecodeError:` on the pinned Python 3.14 (the earlier
review note said "parenthesized"; the code is intentionally unparenthesized).

## 4. Evidence used

| Source | Kind | Use |
|---|---|---|
| `artifacts/experiments/p07-attempt19-five-year-offline/summary.json` | Historical offline recovery of Attempt 19 (native terminal FAILED, separately verified) | Full-scale real-data tests and the complete offline example |
| `artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a-report/evaluation.json` | Verified fixed-demo native P07 evaluation | Fixed-demo compatibility tests and second example |
| `artifacts/experiments/p07-attempt19-five-year-offline/metrics.csv`, `charts.html` | Same derivation | Cross-checked annual/monthly expectations in tests |

Attempt 19's original native terminal status remains FAILED; insights derived
from its offline recovery keep that status visible and never relabel it.
Financial attribution boundaries are preserved: no profit, ROI, OPEX categories
or break-even are invented where the retained evidence is incomplete.

## 5. Parallel-work boundaries

- Owned/edited here: `app/experiments/performance_insights.py` (new),
  `tests/test_performance_insights.py` (new), this document, and one additive
  CLI subcommand in `app/experiments/cli.py`.
- Not touched: GameScript packages, runtime preparation, AdminPort transport,
  native capture, P08/P05 optimizer modules, Agent A files, frozen artifacts,
  `CONTEXT.md`, `TASKS.md`, `EVIDENCE_INDEX.md`.
- Deferred (documented only): none blocking; if a later integration wants a
  shared-file change (for example wiring insights into
  `app/planning/network_cli.py`) it must be agreed after Agent A finishes.

## 6. Integration notes for future P05 feedback

`PerformanceInsights.recommendations` rows are pure data
(`app/experiments/performance_insights.AdvisoryRecommendation`):
`recommendation_id`, `code`, `scope`, `confidence`, `reason`, `evidence`,
`expected_improvement_direction`, `advisory_only=True`,
`missing_information`, `suggested_next_experiment`. The layer issues no native
commands and mutates nothing; a future P05 integration would consume the
document after human review and separately authorized experiments. Follow-up
candidates already have controlled contracts in
`app/experiments/capacity_experiment.py` (A/B/C vehicle allocations) and
`app/experiments/freight_alternatives.py` (offline alternatives), so no new
optimizer framework is required.
