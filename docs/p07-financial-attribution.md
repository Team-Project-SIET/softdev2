# P07 financial attribution — offline deterministic attribution and reconciliation

Status: **implemented and verified on 2026-10-18** on branch `devmodule2` (local
uncommitted P07 scope; nothing is committed or pushed by this work). This is the
dedicated P07 financial-attribution progress document. It records the capability
inventory, the implemented attribution layer, the reconciliation/coverage
reports over the retained evidence packages, and the smallest-possible missing
native observation contract.

No native launch, AdminPort connection, evidence mutation or commit is included.
Retained evidence directories and native records were read only.

## 1. Capability inventory (pre-existing P07 finance code)

| Capability | Existing implementation | Status |
|---|---|---|
| Deterministic operating-window cash identity and profit/ROI gates | `app/simulation/openttd/freight_finance.py` (`reconcile_cash`, `reconcile_snapshots`); pinned tests in `tests/test_freight_finance.py` | Reused as-is; identities mirrored, not re-implemented |
| Continuous five-year finance reconciliation, setup cash coverage, period aggregates | `app/experiments/freight_continuous_analytics.py`, continuous.nut retained report shape | Reused as-is |
| Native receipt CAPEX classification (`sum(mutation_costs[:6])` = infrastructure, `mutation_costs[6]` = vehicle purchase) and native `financial-reconciliation-v1` record | `app/simulation/openttd/freight_native_network.py` | Reused as-is (read-only pins) |
| Batch service receipts with per-service construction readbacks | retained `service-receipt-*.json` / `receipt.json` | Reused as-is |
| Performance insights layer with OBSERVED/DERIVED/HYPOTHESIS/UNKNOWN semantics | `app/experiments/performance_insights.py` | Reused; only extended by the minimal `financial_attribution` status field (§3.4) |

What P07 finance did **not** provide before this work:

1. No normalized, signed, category-attributed ledger over the retained evidence
   (CAPEX by kind, revenue, aggregate expenses, funding, residuals) with
   declared sources/derivations/missing-data behaviour per entry.
2. No unified reconciliation statements that run the pinned identities over the
   *retained documents and native records* and report whether each identity
   holds (`identity_verified`) instead of just computing residuals.
3. No per-service financial attribution binding retained receipts to services,
   with operating-expense attribution declared UNKNOWN rather than inferred.
4. No coverage indicators stating exactly *what* the retained evidence can and
   cannot attribute (and what would change that).
5. No explicit, machine-readable claim gate: every profit/ROI-shaped metric is
   listed as UNSUPPORTED with a reason and the observations required to ever
   support it (instead of simply being `null` in the document).

## 2. Implementation

New module: `app/experiments/financial_attribution.py` (offline only; no
OpenTTD/AdminPort code paths, no network access, no native launch).

### 2.1 Evidence-shape dispatch

`build_financial_attribution(document, ...)` dispatches on the detected P07
document shape exactly as `performance_insights.build_performance_insights`
does:

- **continuous** (`summary.json` with `snapshots`): network finance block,
  `setup_cash_coverage`, retained receipts from the offline-recovery runtime
  directory, 85 period rows over observed aggregates.
- **network-evaluation** (`evaluation.json`): verified metrics, per-service
  metrics, and the retained native
  `native-network-financial-reconciliation-v1` record referenced by the
  report's `evidence_directory`.

`analyze_financial_attribution(source, output, compare=...)` builds one
attribution document (plus optional descriptive cross-run comparison) into an
output directory and writes:

- `financial-attribution.json` — machine-readable attribution (schema 1)
- `financial-attribution.md` — the full report (excerpt in §4)
- `financial-attribution-summary.txt` — terminal-style summary
- `financial-comparison.json` — only when 2+ runs are compared

### 2.2 Normalized signed-movement ledger

The ledger is a closed category set (`LedgerEntry` contract). Amounts are
**signed GBP movements from the company cash perspective: inflows positive,
outflows negative**. Retained native/derived records store "decrease"/spending
fields as positive magnitudes, so the ledger normalizes: an unattributed cash
decrease of 50 becomes `-50`, construction spending becomes `-28459`, and the
expense aggregate becomes `-16312`. The stored (positive) value and the
normalization rule are both declared per entry (`derivation` and
`missing_data_behavior` fields), so nothing is silently transformed.

Categories: `FUNDING_CAPITAL`, `COMPANY_INITIAL_CASH`,
`CAPEX_CONSTRUCTION_{ROAD,FACILITY,OTHER,UNSPLIT}`, `CAPEX_VEHICLE_PURCHASE`,
`REVENUE_TRANSPORT`, `EXPENSE_AGGREGATE_UNALLOCATED`,
`OPEX_{VEHICLE_RUNNING,LOAN_INTEREST,PROPERTY_MAINTENANCE}`,
`LOAN_PRINCIPAL_MOVEMENT`, `UNATTRIBUTED_CASH_MOVEMENT`.

Core rule: **UNKNOWN is not zero; missing transactions are never
manufactured**. A missing amount stays `UNKNOWN` with `amount_gbp=None`; an
unattributed residual keeps its own category and is never reclassified into an
expense category or into profit.

### 2.3 Reconciliation statements

Each statement (`ReconciliationStatement`) mirrors a deterministic identity
over one window and reports `residual_gbp`, `residual_is_zero`, and
`identity_verified`:

- `recon-setup-window` (continuous): funding → operation-opening cash; CAPEX
  and measured setup expenses are terms here, and are excluded from the
  operating window (never deducted twice).
- `recon-operating-window` (continuous): runs the pinned `reconcile_cash`
  identity from `app/simulation/openttd/freight_finance.py` directly with
  `capex=0` — it is called, not re-implemented, so residual semantics cannot
  drift from the committed finance module. The retained
  `unknown_cash_movements` field is preferred; when the field is absent the
  residual is recomputed from retained terms (never estimated), and when both
  exist they must agree, otherwise `identity_verified=False` is reported and
  neither value is reclassified.
- `recon-funding-to-admission` and `recon-batch-window` (network-evaluation
  with a retained native record): mirror the native financial reconciliation
  and verify against it rather than trusting it.

If the recomputed residual differs from the retained one, both are reported and
neither is reclassified (`identity_verified=False` is a finding, not a repair).
A residual whose window terms are all missing is emitted as an UNKNOWN term
with no amount, never as a zero.

### 2.4 Per-service attribution and claims

Per-service `ServiceAttribution` binds retained receipts (or per-service
batch metrics) to services: CAPEX total plus kind/category split, payment
income, and vehicle-profit delta — each with OBSERVED/UNKNOWN status. Operating
expenses are `UNKNOWN` per service (no retained basis) and a `missing` list
declares what would be needed. Seven claim metrics — `operating_profit`,
`net_profit`, `roi`, `payback_period`, `cost_per_cargo_unit`,
`service_profitability`, `network_financial_efficiency` — are emitted as
`AttributionClaim(status="UNSUPPORTED", reason, required_observations)`. No
code path can produce a profit/ROI number from incomplete data.

### 2.5 Retained-evidence readers (strictly read-only)

- `discover_receipts(roots)` → retained `service-receipt-{0..7}.json` (capped
  at 8, ordered).
- `read_capital_gift(roots)` → scenario-capital gift delta from a completed
  `capital-read-response.json`; incomplete reads raise instead of guessing.
- `read_native_reconciliation(roots)` → the native reconciliation payload;
  schema must be exactly `native-network-financial-reconciliation-v1`.
- Roots follow the document's `offline_recovery.original_directory` /
  `evidence_directory`.

### 2.6 Retained-evidence write guard

`analyze_financial_attribution` refuses to write when the output directory
resolves inside any passed source directory or any retained directory
referenced inside the documents. Outputs therefore cannot mutate evidence.

### 2.7 Structured-report integration (minimal)

`performance_insights.PerformanceInsights` gained one optional field,
`financial_attribution`, filled by `compact_status(document)` — a document-only
compact view (classification, observed document amounts, unknown OPEX
categories, operating residual, per-service revenue status, missing claim
metrics). Bottleneck and recommendation semantics are untouched. The deferred
import avoids an import cycle.

## 3. Verification

- New tests: `tests/test_financial_attribution.py` — 33 offline tests over
  controlled fixtures plus read-only real artifacts (`skipif` guard):
  classification, sign normalization, receipt CAPEX semantics vs the pinned
  native classification, kind split from succeeded readbacks, pinned
  `reconcile_cash` residual derivation and drift detection, inconsistency
  flagging, statement identities, reader validation, claim/limitation
  structure, a structural walk asserting no profit/ROI-shaped field carries a
  number, pipeline/write-guard, and real Attempt 19 + fixed-demo attributions.
- Regression: `tests/test_performance_insights.py` — 28 passed (unchanged).
- Pinned focused 2026-10-18 checkpoint suite (REPRODUCE.md) + new tests:
  **181 passed**.
- `.venv/bin/ruff check` / `.venv/bin/ruff format --check` clean on all touched
  files; `.venv/bin/python -m compileall -q app/experiments` clean;
  `git diff --check` clean.
- Independent adversarial code review (read-only subagent over the real
  artifacts, module sources and pinned finance code): verdict **APPROVE**, no
  blocking findings. Substantive review observations were then resolved:
  the operating-window residual now calls the pinned `reconcile_cash`
  directly (`capex=0`) instead of re-implementing the formula; `DERIVED`
  residual terms with missing amounts are demoted to UNKNOWN; observed
  receipt infrastructure without retained kind readbacks stays in the ledger
  as unsplit OBSERVED CAPEX; the retained-evidence zero-decrease asymmetry is
  documented (statements record `residual_is_zero`, the ledger omits exact
  zero native/setup decrease rows); receipt files without succeeded readbacks
  degrade to observed unsplit/UNKNOWN rather than a strict schema gate
  (retained receipt records carry no schema field to validate).

## 4. Reconciliation and coverage reports (retained evidence, read-only)

### 4.1 Attempt 19 five-year offline run (continuous)

Source `artifacts/experiments/p07-attempt19-five-year-offline/summary.json`
(sha256 `1a1eb384…`), receipts and capital readback from
`artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19/`.
Classification: `PARTIAL_FINANCIAL_ATTRIBUTION`; terminal status FAILED is
preserved separately (offline recovery never re-labels it).

Ledger highlights (24 entries, all per-entry provenance in
`financial-attribution.json`):

| Category | Amount GBP | Status | Window |
|---|---:|---|---|
| `REVENUE_TRANSPORT` | 50935 | OBSERVED | operating |
| `EXPENSE_AGGREGATE_UNALLOCATED` | -16312 | OBSERVED | operating |
| `CAPEX_CONSTRUCTION_ROAD` | -3910 / -4067 / -4138 | OBSERVED | setup (per receipt) |
| `CAPEX_CONSTRUCTION_FACILITY` | -1019 × 3 | OBSERVED | setup (per receipt) |
| `CAPEX_VEHICLE_PURCHASE` | -4429 × 3 | OBSERVED | setup (per receipt) |
| `FUNDING_CAPITAL` | 400000 | OBSERVED | funding window (capital readback) |
| `COMPANY_INITIAL_CASH` | 100000 | DERIVED | funding window |
| `OPEX_{VEHICLE_RUNNING,LOAN_INTEREST,PROPERTY_MAINTENANCE}` | UNKNOWN ×3 | UNKNOWN | operating |
| `UNATTRIBUTED_CASH_MOVEMENT` | -1500 / -50 | DERIVED | operating / setup |

Reconciliation: `recon-setup-window` residual **-50 GBP**, identity verified
(the retained record stores the unattributed setup decrease as +50; the ledger
signs it -50). `recon-operating-window` residual **-1500 GBP**, identity
verified. The -1500 matches the document's own `reconcile_cash` residual; the
chain total across reconciled windows is -1550.

Coverage: `capex_category_separation=ROAD_FACILITY_VEHICLE` (observed),
`per_service_capex_attribution=OBSERVED` (3 of 3 receipts),
`per_service_revenue_attribution=UNKNOWN` (cargo monitors count units, not
revenue), `expense_classification_complete=False` (observed flag),
`unattributed_cash_movement_gbp=-1500`,
`unattributed_fraction_of_gross_inflows=0.029449`, `net_cash_flow_gbp=33123`.
85 period rows carry observed network revenue and the expense aggregate per
period (first row: 0 revenue / 213 aggregate expenses, `PARTIAL_ATTRIBUTION`).

All seven profitability claims: UNSUPPORTED.

### 4.2 Fixed demo (network evaluation with retained native record)

Source `artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a-report/`
(sha256 `2e53178c…`), native records and receipts from the referenced evidence
directory. Classification: `PARTIAL_FINANCIAL_ATTRIBUTION`.

Ledger highlights:

| Category | Amount GBP | Status | Window |
|---|---:|---|---|
| `REVENUE_TRANSPORT` | 1022 | OBSERVED | serial batch window |
| `CAPEX_CONSTRUCTION_UNSPLIT` | -15172 | OBSERVED | setup |
| `CAPEX_VEHICLE_PURCHASE` | -13287 | OBSERVED | setup |
| `FUNDING_CAPITAL` | 400000 | OBSERVED | funding window |
| `COMPANY_INITIAL_CASH` | 100000 | DERIVED | funding window |
| `EXPENSE_AGGREGATE_UNALLOCATED` | UNKNOWN | UNKNOWN | serial batch window (`operating_costs=null`) |
| `OPEX_*` | UNKNOWN ×3 | UNKNOWN | serial batch window |
| `UNATTRIBUTED_CASH_MOVEMENT` | -384 / -678 | DERIVED | funding→admission / batch window |

Reconciliation: `recon-funding-to-admission` residual **-384 GBP**, verified;
`recon-batch-window` residual **-678 GBP**, verified against
`471501 − (499616 + 1022 − 28459)`. The two window residuals add to **-1062**,
matching the native record's `funded_to_final_unallocated_cash_decrease`.

Per-service attribution from retained receipts (all OBSERVED): CAPEX
9358 / 9515 / 9586; revenue 340 / 356 / 326 (sums to network revenue 1022 —
`per_service_revenue_sums_to_network=True`); vehicle profit delta 306 / 324 /
289. Shared infrastructure CAPEX = 15172 − (4929+5086+5157) = 0
(`INFRASTRUCTURE_VEHICLE` separation, `capex_split_consistency=True`).
Per-service operating expenses: UNKNOWN.

All seven profitability claims: UNSUPPORTED.

## 5. Missing native observation contract (smallest possible set)

The OPEX split and every profitability metric are structurally UNSUPPORTED
from the retained evidence. The retained `continuous.nut` capture writes
`loan_interest=null`, `expense_categories=null` and
`vehicle_operating_expenses=null` into every snapshot, and the GameScript read
API exposes expenses only as one quarterly company aggregate. Exactly four
new native observations would unlock attribution (each claim lists these as
`required_observations`):

1. **Expense-category amounts** (vehicle running costs, property, loan
   interest, other) for exactly the observed window — the quarterly aggregate
   cannot be split after the fact.
2. **Synchronous quarter-boundary cash samples** so cash windows and quarter
   counters align and the unattributed residual isolates only engine movements
   outside the aggregate.
3. **Per-service revenue** (or a declared engine basis for attribution) —
   cargo monitors count units, not money; retained batch receipts currently
   provide the only per-service payment income.
4. **Mid-window CAPEX bound to the same window as the revenue** it is compared
   against.

Until all four exist, the module keeps OPEX categories UNKNOWN and all seven
claims UNSUPPORTED rather than estimating.

## 6. Remaining limitations

1. Attribution consumes already-verified P07 documents; verification is not
   repeated here.
2. UNKNOWN is not zero; missing transactions are never manufactured. Amounts
   may be absent (`amount_gbp=None`) where evidence is absent — never
   estimated, never zero-filled.
3. Unattributed cash residuals are never classified as expenses or profit,
   and the residual's engine origin (e.g. vehicle long-run depreciation
   timings, transfer motions) is not identified by the retained evidence.
4. The expense aggregate is company-level; the read API cannot split vehicle
   running costs, property and loan interest.
5. Historical native attempt terminal status (FAILED for Attempt 19) is
   preserved separately; offline recovery never re-labels the consumed
   attempt, so attribution here describes recovered evidence, not a live run.
6. The descriptive cross-run comparison shares world identity and
   normalization only; it never claims causality or improvement.
