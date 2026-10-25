---
id: ADR-012
title: "Six temporal tiles: the save-instant census is authoritative for tree-lifecycle deltas (planning evidence only)"
type: decision
status: accepted
date: 2026-10-24
updated: 2026-10-25
source: "docs/random-world-six-tile-policy-decision.md"
tags:
  - openttd
  - decisions
---

# ADR-012 — Six temporal tiles: the save-instant census is authoritative for tree-lifecycle deltas (planning evidence only)

## Decision

For the six `TEMPORAL_SECOND_INSTANT` tiles of the P08 V1/V2 semantic
reconciliation — exactly **43951, 47286, 47288, 48042, 48309, 51378** — the
delegated decision selects **Option B**: the save-instant census is declared
authoritative for these tiles' tree-lifecycle deltas, as **planning-evidence
authority only**. The operator delegated this decision (2026-10-24 session
instruction, explicit delegation: "The operator has delegated the decision
between Option A and Option B to you"); the runner-side agent exercises it in
the written record and implemented code below and for nothing else.

What it establishes, precisely:

- The disagreement *between the fresh census values and the retained V1 values*
  on those six tiles is attributed to elapsed world time (tree growth/death
  between the census instants 712224–712226 and the retained window
  712285–712291), mechanism-verified against OpenTTD 15.3 `tree_cmd.cpp`
  (`TileLoop_Trees`); both records are true observations of different instants.
- For **planning purposes** (P08 feasibility assessment inputs derived from the
  census), the census's observed values on those six tiles are the authority.
- Each census page carrying those tiles is a recorded **single-instant**
  observation (`date_before == date_after`, verified per page in the sealed
  candidate) — the policy accepts per-page instants, never a multi-day window.

What it does **not** establish:

- It does **not** relabel, rewrite, or equalize the two historical records. The
  retained V1 facts remain verbatim in their file, the six tiles remain
  individually ledgered as `TEMPORAL_SECOND_INSTANT` in the base
  reconciliation (that status describes provenance, not error), and the sealed
  fusion verdict `TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT` /
  `SOURCE_SAVE_FUSION REJECTED` stays untouched (ADR-010 unchanged).
- The **CensusAuthoritativeAssessment fusion gate (existing one) stays closed**:
  same-instant state equality between census and retained capture is
  structurally unachievable (arrow of time) and the gate's criterion is left
  untouched.
- The six tiles are "resolved" **only in the authority-attribution sense**; the
  derived P08 binding remains **not allowed** — 19 retained-UNKNOWN tiles, the
  sealed verdict immutability and the separate reviewed rebinding step remain.
- It does not cover any other tile, any future temporal tile, any genuine
  contradiction, or any `UNRESOLVED_DISTINCT_PREDICATE` evidence; scope is
  tiles + fields (`tree`, `rough`, `buildable` residuals observed on the six)
  and is enforced fail-closed by the parameterization of the application layer.
- It records no native evidence: nothing was captured, signed, consumed or
  launched under this decision.

## Source evidence

- `artifacts/experiments/v1v2-semantic-reconciliation/reconciliation-report.json`
  (verdict `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`; six failing tiles;
  77/6/0/0 ledger; `date_before == date_after` on all 90 census pages).
- `docs/p08-v1v2-semantic-reconciliation.md` (policy `vacant-projection-1`,
  mechanism attribution vs `tree_cmd.cpp`).
- `docs/random-world-six-tile-policy-decision.md` (2026-10-24 decision record,
  prepared before the delegation was exercised).
- 15/15 PASS re-run of `tests/test_v2_semantic_reconciliation.py` (2026-10-24).

## Alternatives considered (as recorded)

- **Option A — fresh same-instant native re-observation** of the six tiles
  under a fresh one-shot authorization: **rejected as the resolution path, on
  code-level feasibility, not on cost.** The same-state criterion is
  `SameStateProvenance.within_window(census_date)` over the *sealed, immutable*
  census instants vs the retained window (`v2_semantic_reconciliation.py`);
  both records' instants can never change, so no future observation can make
  the census and retained states same-instant. A fresh capture would at best
  *confirm* the already mechanically-explained deltas — it could not resolve
  which instant's state governs P08 planning, which is the actual open
  question. It is **retained as an optional, conditional future
  delta-confirmation run** (its own staged candidate + fresh authorization) if
  the operator later wants replay determinism against the retained timeline
  proven natively. No work may assume its outcome.
- **Adopting both simultaneously**: rejected because a policy that stands only
  *pending an unperformed experiment* would create contradictory assumptions
  (authority-by-default vs authority-pending-evidence).

## Consequences

- The reconciliation workflow gains an explicit, fail-closed, scope-contained
  application layer (`apply_census_authority`) that emits a *derived* policy
  verdict; the sealed inputs, sealed verdicts, base ledger and historical bytes
  are untouched, and the derived evidence is separately labeled (`PREPARED`
  analysis, no native proof).
- Future work that wants to consume the derived authority must re-derive it
  from the sealed inputs each run (no cached "resolved" state).
- Any drift in the sealed census/retained bytes makes the derived policy
  verdict fail closed.

## Rebinding pass (2026-10-25, offline; PREPARED analysis)

The separately reviewed P08 rebinding step named above is implemented as
`rebind_p08_policy` / `P08PolicyRebinding` in
`app/simulation/openttd/v2_semantic_reconciliation.py` and wired into the
snapshot adapter (`build_v2_snapshot_assessment(..., policy_report=...)` and
the `--policy-report` CLI flag in `app/planning/p08_v2_snapshot.py`).

- The supplied derived report is **re-derived from the sealed inputs and
  byte-compared**; stale, edited, narrowed, widened, non-ADR-012 or
  refusal-carrying reports are refused (`ValueError`). Accepted rows must
  preserve the sealed base values verbatim, and the scope must equal exactly
  the reconciliation's own temporal set. Out-of-scope tiles, contradictions
  and unresolved evidence can never be absorbed.
- The rebinding never changes the planning input, never relabels the base
  ledger (`TEMPORAL_SECOND_INSTANT` preserved), and never opens the fusion
  gate. `allowed` is computed from remaining blockers; on the sealed evidence
  it is **False** because the 19 retained-UNKNOWN (`UNKNOWN_OCCUPANCY`) tiles
  are outside ADR-012 and no separate admissible evidence exists.
- Derived, deterministic evidence:
  `artifacts/experiments/v1v2-semantic-reconciliation/p08-policy-rebinding-report.json`
  (sha256 `c9d11d41…107ed0`; `p08_binding.allowed: false`,
  `preserved_retained_status: INCOMPLETE_TILE_CLASSIFICATION`).
- Tests: `tests/test_p08_policy_rebinding.py` — 24/24 PASS (2026-10-25):
  valid sealed rebinding, byte determinism, provenance preservation,
  snapshot-integration without changing the pinned base assessment,
  out-of-scope tiles/fields, missing/malformed/stale/tampered evidence, and
  fail-closed refusal for contradictory or established bases.

The rebinding resolves *which evidence the remaining blocker is not about*;
it does not resolve the 19 UNKNOWN tiles and does not create native proof.
A 2026-10-25 diagnosis (`diagnose_unknown_occupancy`) shows those 19 are one
definitional group — census `CLEAR`, unowned, non-flat, already
`SEMANTIC_RECONCILED` on the `buildable` transformation — and are **not**
covered by this ADR. Resolving them requires a separate reviewed policy
decision on native-`IsBuildable` semantics or fresh same-instant evidence;
the fusion gate stays independently closed by the six temporal tiles.

## Supersession

<!-- none as of 2026-10-24 -->
