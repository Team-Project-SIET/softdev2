# Operator policy decision record — six temporal tiles (P08 V1/V2 reconciliation)

Date: 2026-10-24. **Decision requested, not made.** This document prepares the
explicit operator decision named as one of the two minimum-evidence paths in
`artifacts/experiments/v1v2-semantic-reconciliation/reconciliation-report.json`
and `docs/p08-v1v2-semantic-reconciliation.md`. Offline only: no OpenTTD launch,
no AdminPort connection, no candidate consumption, no signing, no Git
staging/commit. It grants no runtime authority and decides nothing by itself.

## 1. Acceptance criterion addressed

Random World Seed-17 correspondence (E4/E8/E16 chain): P08 stays
`INCOMPLETE_TILE_CLASSIFICATION` (339 ROAD_BUILDABLE / 63 SUPPORTED_CLEARING /
19 UNKNOWN / 29 UNSUPPORTED) because the fusion gate is closed by exactly six
temporal second-instant tiles. The offline reconciliation
(`SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`, uncommitted working-tree work,
not an indexed E-ID) accounts for **77 definitional `buildable` disagreements,
0 genuine contradictions, 0 unresolved**, and preserves the six temporal tiles:
**43951, 47286 (trees grew after the census instant), 47288, 48042, 48309
(rough-ground trees died to bare rough ground), 51378 (grass tree died to
vacant ground)** — mechanism verified against OpenTTD 15.3 `tree_cmd.cpp`
(`TileLoop_Trees`). P08 binding is **not allowed** while any of them stands.

Why the gate stays closed: the fresh census spans economy dates **712224–712226**
while the retained V1 capture window is **712285–712291** — tree-lifecycle
deltas therefore occurred between the two instants for these tiles, so no
same-state claim exists and fusing them would be inference, which the review
policy forbids.

## 2. The decision the operator is asked to make

Choose exactly one resolution path for the six tiles' tree-lifecycle deltas:

### Option A — Same-instant native re-observation (fresh evidence)

A bounded, separately-authorized re-observation of exactly
`[43951, 47286, 47288, 48042, 48309, 51378]` as a **single census with
`date_before == date_after`** (one instant, no multi-day window), sealed in a
**new reviewed candidate** under a fresh one-shot authorization, per ADR-007's
one-shot model.

- Prerequisites (each checked at staging; none currently satisfied): a frozen
  input identity naming the candidate uniquely (consumed identities are never
  reused), a bounded request plan for the six tiles reusing the proven schema-2
  classification exchange machinery, byte-retained pages, fail-closed
  correspondence handling, strict budgets (launches 1, connections 1,
  retries 0), and a full cleanup plan.
- If the fresh instant agrees with the retained V1 facts for all six tiles,
  the same-state blocker is discharged and the fusion gate can be re-evaluated
  in a separately reviewed record (P08 binding reconsideration).
- If it disagrees, the disagreement is retained evidence like any other —
  `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED` stands or is amended by that
  record only.
- Cost: one staging + review cycle, then ONE explicit operator authorization.

### Option B — Policy: declare the save-instant census authoritative (operator decision, no native run)

An explicit operator policy statement declaring the save-instant census
authoritative for these six tiles' tree-lifecycle deltas — i.e. accepting that
the observed 712224–712226 state (the deltas included) is the world fact being
planned against, rather than requiring re-observation at the retained instant.

- Prerequisites: the operator states the decision in writing (where: the
  decision thread / review record referencing this document and the
  reconciliation report), and it is sealed in a reviewed record (a new ADR
  recording full scope: the six tile IDs, the deltas accepted, the worlds it
  covers, and its non-goals).
- Consequence: the same-state requirement would be satisfied **by policy for
  these tiles' tree deltas only**; a separately reviewed fusion/rebinding
  pass could then re-open the P08 assessment pending its own gates (ADR-010
  still forbids relabeling the sealed verdicts — an accepted policy changes
  future evidence production, never historical records).
- Cost: a reviewed record only; no native attempt, no consumption. This does
  not change D4-CORRIDOR-2's `PENDING_AUTHORIZATION` or any D-status.

### Non-goals (both options)

- No relabeling, editing, regeneration or reuse of any historical evidence,
  sealed verdict, consumed candidate, or the D4-CORRIDOR-1 frozen closure.
- No authorization is granted by preparing this record; Option A still needs
  its own explicit one-shot operator authorization; Option B still needs the
  explicit written operator decision.

## 3. Immediate recommendation (fact-based only, no decision) — superseded by §5

> **Superseded 2026-10-24:** the operator delegated the choice and §5 records
> the exercised decision (Option B) with its implementation. The analysis
> below is retained as the pre-decision state of this record.

The reconciliation work is implementation-complete and offline-verified
(15/15 focused tests PASS this session: `tests/test_v2_semantic_reconciliation.py`).
Both options are fully specified above; the choice — fresh evidence vs.
accepting the observed instant — is an operator judgment about which evidence
class P08 planning should treat as authoritative, and the runner-side agent
cannot make it. Until it is made:
- P08 stays `INCOMPLETE_TILE_CLASSIFICATION` (all four counts unchanged);
- the six tiles stay individually recorded in the reconciliation ledger with
  their per-tile statuses (`SEMANTIC_RECONCILED` ×77, `TEMPORAL_SECOND_INSTANT` ×6);
- the uncommitted reconciliation work itself remains non-indexed working-tree
  state (its promotion to an evidence record, or its acceptance, is part of
  the Option B review record if chosen).

## 5. Decision (exercised 2026-10-24, delegated) — **Option B selected**

The operator delegated the choice between Option A and Option B to the
runner-side agent (2026-10-24 session instruction). The decision is recorded as
**ADR-012** (`docs/handoff/2026-10-24/adr-012-six-temporal-tiles-census-authority.md`)
and is **Option B**, for planning-evidence authority only, on these grounds
drawn from the live code (`app/simulation/openttd/v2_semantic_reconciliation.py`):

1. **Option A cannot resolve the actual ambiguity.** The same-state criterion
   is `SameStateProvenance.within_window(census_date)` over the **sealed,
   immutable** census instants (verified per page single-instant; window
   712224–712226) and the **sealed, immutable** retained window (712285–712291).
   No future native observation can change either record's instants, so a fresh
   re-observation could at best *confirm* that the six deltas are genuine
   timeline effects (already mechanically explained against OpenTTD 15.3
   `tree_cmd.cpp`, with 0 genuine contradictions). The open question — which
   instant's state P08 planning treats as authoritative — is a policy
   question, not an evidential one, so Option A would consume a staged
   candidate and a fresh one-shot authorization without resolving it.
2. **Adopting both simultaneously** would encode authority-by-default and
   authority-pending-experiment at once — contradictory assumptions; rejected.

**Option A is retained as an optional, conditional future
delta-confirmation run** (its own reviewed candidate + fresh authorization) if
deterministic-replay confirmation against the retained timeline is ever wanted.
No work assumes its outcome.

### Implementation status (PREPARED analysis; no native evidence)

- `app/simulation/openttd/v2_semantic_reconciliation.py` —
  `CensusAuthorityDecision` + `apply_census_authority` +
  `PolicyAppliedReconciliation`: explicit token (ADR-012), fail-closed
  refusals (scope ≠ sealed temporal set; hygiene/identity failures;
  unreproduced completeness; unverified manifest; non-single-instant pages;
  contradictions/unresolved never absorbed; fields outside the concept
  scope), verbatim evidence preservation, `vacant-projection-1` definitional
  rows passed through untouched, base report bytes immutable.
- CLI: `--apply-adr-012` emits the derived
  `census-authority-policy-report.json` from sealed inputs.
- Tests: `tests/test_census_authority_policy.py` — 14/14 PASS (2026-10-25),
  including the sealed Seed-17 replay (all six tiles resolve; base bytes
  unchanged; P08 binding still not allowed).
- Derived report (regenerated on demand):
  `artifacts/experiments/v1v2-semantic-reconciliation/census-authority-policy-report.json`.

### Rebinding pass (2026-10-25, PREPARED analysis; no native evidence)

`rebind_p08_policy` (same module) consumes the derived report for P08:
it re-derives the report from the sealed inputs and requires byte equality,
accepts only the exact six-tile temporal scope with verbatim field rows, and
refuses stale, edited, narrowed, widened, non-ADR-012 or refusal-carrying
reports. The snapshot adapter consumes it through
`build_v2_snapshot_assessment(..., policy_report=...)` / `--policy-report`
without changing the planning input or the pinned base assessment. Derived
evidence: `artifacts/experiments/v1v2-semantic-reconciliation/p08-policy-rebinding-report.json`
(sha256 `c9d11d41…107ed0`); tests `tests/test_p08_policy_rebinding.py`
24/24 PASS. The computed binding remains **not allowed**: the 19
`UNKNOWN_OCCUPANCY` tiles are outside ADR-012 and unresolved, so P08 stays
`INCOMPLETE_TILE_CLASSIFICATION`. See ADR-012 "Rebinding pass".

### What the six tiles' status is now

**Resolved in the authority-attribution sense only — not natively resolved.**
The base reconciliation still ledger-labels them `TEMPORAL_SECOND_INSTANT`
(provenance, not error), the sealed verdicts are unrelabelled, the fusion gate
stays closed, and **P08 remains `INCOMPLETE_TILE_CLASSIFICATION`** with the
339/63/19/29 segmentation unchanged (the 19 retained-UNKNOWN tiles are outside
ADR-012's scope). No observation was collected; nothing was signed, consumed
or launched.

## 6. Standing facts untouched by this document

D4-CORRIDOR-2 remains `PENDING_AUTHORIZATION` (no `AUTHORIZATION.json`,
`CLAIM.json` or `LAUNCH-CONSUMED.json` exists; not referenced by either option
above); Milestone D4 remains `INCOMPLETE`. Production-key and real-signature
validation have not been performed. OpenTTD 13.4 evidence does not support any
15.3 claim.
