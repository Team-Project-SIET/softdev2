---
title: "AI Start Here"
type: hub
status: current
updated: 2026-10-22
tags:
  - openttd
  - entry-point
---

# AI_START_HERE — read this before any OpenTTD work

You are entering the knowledge vault of the **OpenTTD transport-planning integration project**
(repository `softdev2`, branch `devmodule2`). This vault documents the integration of an
existing **Python logistics/planning system (OR-Tools)** with **real OpenTTD 15.3** so that
externally generated plans can be created, validated, executed inside OpenTTD, verified
against actual game state, and returned as machine-verifiable execution evidence.

Vault capture date: **2026-10-22** (working tree of `devmodule2`, uncommitted implementation
included in the project's own records; commit `5872689`).

## 1. Read in this order

1. [[AI_START_HERE]] (this file) — orientation, rules, current state.
2. [[00-Project/Current Status|Current Status]] — evidence-backed state per area.
3. [[99-Source-Documents/CONTEXT]] — canonical project context (see §2 authority).
4. [[05-Planning/Task Board|Task Board]] and [[05-Planning/Next Actions|Next Actions]] — what work is authorized/planned next.
5. [[04-Evidence/Evidence Index|Evidence Index]] — E1…E21 evidence records and their exact scopes.
6. [[03-Engineering/Reproduction Guide|Reproduction Guide]] — how to inspect, test, and (only when separately authorized) run natively.

Do not rely on prior chat history, provider memory, or assumptions from older OpenTTD
13.4 experiments. Repository files and retained evidence are the authority.

## 2. Documentation authority hierarchy

| Authority | Role |
|---|---|
| [[99-Source-Documents/CONTEXT]] | Canonical project context. Note: the repo-root `CONTEXT.md` bytes are pinned by retained authority manifests captured **2026-10-08** (sha256 `b94b966…`); the working-tree file has diverged past that pin since commit `bdbec43` (2026-10-11), so two protected-authority tests and one industry-production architecture check fail at baseline. The prepend-only 2026-10-18 addendum is working-tree-only and duplicate-recorded in [[99-Source-Documents/AI_HANDOFF]]. Resolving this requires a separate, explicitly authorized pin-repair/re-capture decision — do not silently reconcile. |
| [[99-Source-Documents/EVIDENCE_INDEX]] | Evidence index (E1…E21). Existing attempts are immutable. |
| [[99-Source-Documents/AI_HANDOFF]] | Vendor-neutral continuation guide for the actual local worktree. |
| [[99-Source-Documents/TASKS]] | Continuation task list (grants no runtime authority). |
| [[99-Source-Documents/REPRODUCE]] | Inspection/test/native-authorization command reference. |
| [[99-Source-Documents/README]] | Public product description, historical milestones, usage. |
| Older docs under `docs/`, `docs/handoff/<date>/` | Dated proof/preparation records; authoritative for what they themselves state. |

A source may be newer in *some* respects and older in others. Preserve dates, authority,
scope, and conflicts; never silently reconcile contradictory records.

## 3. Evidence-backed current state (snapshot, 2026-10-22)

Condensed. Full scope/boundaries: [[00-Project/Current Status]]. Status vocabulary:
[[07-Reference/Status Definitions]].

| Area | Status (scope-bound) | Evidence |
|---|---|---|
| Stable fixed demo (`a348016` checkpoint) | **VERIFIED** native 15.3: 3 services/vehicles, 60 coal, £1,022 revenue, £28,459 CAPEX, spectator, P07, cleanup | E1 |
| Canonical create/reload Q3 | **PROVEN** historical engineering (reload-only correspondence) | E2 |
| Attempt 19 (five economy years) | Native terminal **FAILED**; separate offline recovery valid within derived scope | E3 |
| Random World (Seed 17) | Generation/discovery/spectator **VERIFIED**; smoke **FAILED** (`NO_BOUNDED_CORRIDOR`, P05 NOT_RUN) | E4, E8 |
| Tile Classification V2 | Capture **DONE natively** (90/90 pages, 450/450 tiles) but SOURCE_SAVE_FUSION verdict **REJECTED** (83 disagreements); P08 stays `INCOMPLETE_TILE_CLASSIFICATION` | E14–E16 |
| Milestone D2 native clearing (tile 46769) | **PROVED** | E17 |
| Milestone D3 native clearing + terraforming | **PROVEN** (receipts `RECEIPT_VERIFIED`, £496,543 reconciliation) | E18, E19 |
| Milestone D4 native road + station construction | **ATTEMPT CONSUMED — INCOMPLETE** (`PHASE_HALTED_PREFIX_PRESERVED`, `verified: false`): op-00 verified (£785), op-01 refused (£2,549 > £2,000), op-02–op-05 not executed | E21 |
| Offline V1/V2 semantic reconciliation (uncommitted work) | Partial: `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`; 6 temporal tiles keep the fusion gate closed; P08 binding **not allowed** | [[05-Planning/Blockers]] |
| Full OPEX / net-profit / ROI | **UNKNOWN** — never invent | — |

## 4. Blockers and next action

- **Recommended next engineering task:** the offline D4 restage decision — the previous
  one-shot authorization on candidate **`D4-CORRIDOR-1`** was consumed 2026-10-22 and the
  ceremony halted at `op-01` (E21, D4 INCOMPLETE); next step is the staging-time
  ceiling/scope decision, then a fresh reviewed candidate; only a fresh explicit operator
  authorization can ever run it. See [[05-Planning/Next Actions]], [[05-Planning/Blockers]] §8.
- **No vault note grants runtime authority.** Native launches, AdminPort connections,
  authorization consumption, and one-shot attempts require **separate explicit operator
  authorization**. Never retry a consumed attempt identity.
- Other open items (Random World observed-world facts, same-instant re-observation of six
  tiles or an operator policy decision, protected-authority pin repair): [[05-Planning/Blockers]].

## 5. Where things live

- Project frame: [[00-Project/Project Overview|Project Overview]], [[00-Project/Roadmap|Roadmap]], [[00-Project/Scope and Non-Goals|Scope and Non-Goals]].
- Architecture: [[01-Architecture/System Architecture|System Architecture]], [[01-Architecture/Component Map|Component Map]], [[01-Architecture/Data Flow|Data Flow]], [[01-Architecture/OpenTTD Integration|OpenTTD Integration]], [[01-Architecture/AdminPort Protocol|AdminPort Protocol]], [[01-Architecture/Planning and Execution Boundary|Planning and Execution Boundary]].
- Milestones: [[02-Milestones/Milestone Index|Milestone Index]] → Completed / Pending.
- Engineering: [[03-Engineering/Source Code Map|Source Code Map]], [[03-Engineering/Testing Strategy|Testing Strategy]], [[03-Engineering/Runtime and Environment|Runtime and Environment]], [[03-Engineering/Troubleshooting|Troubleshooting]].
- Evidence: [[04-Evidence/Native Verification|Native Verification]], [[04-Evidence/Controlled Tests|Controlled Tests]], [[04-Evidence/Failed Attempts|Failed Attempts]] (immutable), [[04-Evidence/Evidence Preservation|Evidence Preservation]].
- Planning: [[05-Planning/Task Board|Task Board]], [[05-Planning/Next Actions|Next Actions]], [[05-Planning/Blockers|Blockers]], [[05-Planning/Technical Debt|Technical Debt]].
- Decisions: [[06-Decisions/Architecture Decision Records|ADR index]] and [[06-Decisions/Decision Log|Decision Log]].
- Reference: [[07-Reference/Glossary|Glossary]], [[07-Reference/Status Definitions|Status Definitions]], [[07-Reference/Important Paths|Important Paths]], [[07-Reference/External References|External References]].

## 6. Locating implementation details in the repository

The vault sits at `<repo-root>/OpenTTD-Knowledge/`. All code paths in this vault are
written **relative to the repository root** (the parent of this vault), e.g.
`app/planning/p08_road.py`. Obsidian does not follow links outside the vault — open the
repository checkout for code and artifacts. Layout: [[03-Engineering/Source Code Map]],
paths: [[07-Reference/Important Paths]].

Key entry points to check first when changing code:

- Public demo CLI: `app/openttd_demo.py`
- P08 candidate generation: `app/planning/p08_adapter.py`, `app/planning/p08_road.py`
- P05 selection: `app/planning/optimizer.py` (`optimize_candidate_network`)
- Transport/bridge: `app/simulation/openttd/secure_admin.py`, `gamescript_transport.py`,
  `freight_delivery_package/*.nut`
- Proof/preparation runner: `app/simulation/openttd/proof/freight_delivery.py`
- D-milestone execution: `app/simulation/openttd/proof/corridor_construction_native.py`

## 7. Rules for updating these notes

1. Read `AI_START_HERE.md` first every session; check Git branch/working tree
   (`git branch --show-current`, `git rev-parse HEAD`, `git status --short`) and whether
   the vault still matches repository reality. Date every update.
2. Prefer linking to canonical information over duplicating it; update affected notes when
   implementation or verification results change project knowledge.
3. Record dates, evidence references (E-IDs), and the exact verification scope. Keep
   OBSERVED / DERIVED / CONTROLLED facts separate; missing samples are UNKNOWN.
4. Preserve contradictions and unresolved questions until they are properly investigated.
5. Never infer that an operation succeeded merely because a command was issued; native
   acknowledgment alone is not delivery proof (receipts fail closed).
6. Never delete, rewrite, or relabel historical evidence or failed outcomes — do not edit
   `99-Source-Documents/` (byte-for-byte copies) or any retained artifact.
7. Never launch OpenTTD, connect to AdminPort, consume an authorization, or repeat a
   one-shot attempt without explicit authorization; never stage/commit/push Git without it.
8. Record unavailable validation tools and unperformed checks honestly.
9. Use the templates in `90-Templates/` for new records ([[90-Templates/Evidence Record]],
   [[90-Templates/Task]], [[90-Templates/Decision Record]], [[90-Templates/Experiment Record]]).

## 8. Freshness warning

This vault is a snapshot captured on **2026-10-22** and may not reflect the latest
repository state until synchronized. The repository itself is intentionally dirty:
uncommitted implementation, evidence excluded from Git, and instruction files whose
commit state is governed by authority pins. Before acting on any fact here, verify it
against the working tree and the dated handoff inventory
(`docs/handoff/2026-10-17/`, plus newer records under `docs/handoff/2026-10-21/` and
`docs/handoff/2026-10-22/`).
