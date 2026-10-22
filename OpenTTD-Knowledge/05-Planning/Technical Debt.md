---
title: "Technical Debt"
type: planning
status: current
updated: 2026-10-22
tags:
  - openttd
  - planning
  - debt
---

# Technical Debt

Recorded, source-backed debt items. Only items stated by project records are listed;
"candidate" items are labeled as such.

## Architecture / code organization

- **Two-architecture lineage in the tree.** The legacy `transport-experiment`
  (OpenTTDLab/OpenTTD 13.4, DB-backed) path coexists with the 15.3 demo path, per design
  (README §Optional historical experiments). It is retained deliberately; the debt is
  awareness: do not confuse the two boundaries, and do not delete or refactor unrelated
  planner/domain code as part of integration work (CONTEXT §§3, 19, 21).
- **Large uncommitted working tree** — 218 status entries (2026-10-22): Random World,
  distance support, D-chain modules, analytics, reconciliation modules (e.g.
  `corridor_construction.py`, `v2_semantic_reconciliation.py`) are untracked (unpublished
  engineering). Committing any of it requires the reviewed staging-allowlist protocol
  (AI_HANDOFF checkout/transfer + preservation rules).
- **Typecheck without an installed tool.** `ty` is configured but not installed;
  historical "typecheck unavailable offline" notes recur across records (E9–E15). The
  honest fix is a fresh installed-tool run recorded as new evidence.

## Integrity / process debt

- **CONTEXT.md authority-pin conflict.** Open defect at the process level — pinned
  2026-10-08 bytes vs evolved file; failing tests at baseline; addendum uncommitted
  ([[04-Evidence/Evidence Preservation]]).
- **Classified-but-unbound world model.** The V2 census exists but cannot be bound into
  P08 (fusion REJECTED; six temporal tiles unresolved) — the knowledge is captured but
  operationally unusable until new authorized evidence/decision ([[05-Planning/Blockers]]).
- **Historical suites as evidence.** Per-record suite counts depend on local retained
  bytes; fresh clones cannot always reproduce them. Debt: treat as dated evidence,
  never re-cite fresh, keep the skip-if-evidence-absent patterns honest
  ([[03-Engineering/Testing Strategy]]).

## Environment / hygiene

- **Stray root file `--version`** — an unknown 694,136-byte untracked root file dated
  2026-10-15. Instruction: preserve it, do not execute it (AI_HANDOFF). *(Its purpose
  remains UNKNOWN — recorded, not investigated here.)*
- **`.env` and credential-adjacent directories** must stay excluded from any transfer and
  out of any vault/publishing surface (AI_HANDOFF).
- **Git-ignored retained evidence at scale** — protection manifests and ownership gates
  (`historical_protection.py`, ownership gates) guard them. Debt: any tooling change must
  re-run the preservation validators (E-preservation rules).

## Known limitations (architecture, not to be "fixed" casually)

- Observation budgets inherently bind capacities: 256-tile fixed demo capture vs 512-tile
  random profile; 47-road-tile paths; ≤32 industries/≤16 relationships/≤8 services in
  random mode ([[01-Architecture/Data Flow]]).
- Financial attribution gap: full OPEX/ROI unmeasured by design until a measured expense
  mechanism exists (README known limits) — assumptions must not be promoted into
  realized metrics.
- `economy.multiple_industry_per_town` style engine settings are now explicit precheck
  items for any world-preparation stage (Attempt 10 lesson).

## Not-debt (explicitly)

- The one-shot authorization ceremony, fail-closed gates, and immutable evidence are
  deliberate design, not friction to streamline.
- Preserving dated duplicates of statuses (e.g. CONTEXT §20 vs newest addenda) is
  intentional integrity behavior, not a duplication bug.
