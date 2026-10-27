---
title: "AI Start Here"
type: hub
status: current
updated: 2026-10-26
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
5. [[04-Evidence/Evidence Index|Evidence Index]] — E1…E35 evidence records and their exact scopes.
6. [[03-Engineering/Reproduction Guide|Reproduction Guide]] — how to inspect, test, and (only when separately authorized) run natively.

Do not rely on prior chat history, provider memory, or assumptions from older OpenTTD
13.4 experiments. Repository files and retained evidence are the authority.

## 2. Documentation authority hierarchy

| Authority | Role |
|---|---|
| [[99-Source-Documents/CONTEXT]] | Canonical project context. Note: the repo-root `CONTEXT.md` bytes are pinned by retained authority manifests captured **2026-10-08** (sha256 `b94b966…`); the working-tree file has diverged past that pin since commit `bdbec43` (2026-10-11), so two protected-authority tests and one industry-production architecture check fail at baseline. The prepend-only 2026-10-18 addendum is working-tree-only and duplicate-recorded in [[99-Source-Documents/AI_HANDOFF]]. Resolving this requires a separate, explicitly authorized pin-repair/re-capture decision — do not silently reconcile. |
| [[99-Source-Documents/EVIDENCE_INDEX]] | Evidence index (E1…E35). Existing attempts are immutable. |
| [[99-Source-Documents/AI_HANDOFF]] | Vendor-neutral continuation guide for the actual local worktree. |
| [[99-Source-Documents/TASKS]] | Continuation task list (grants no runtime authority). |
| [[99-Source-Documents/REPRODUCE]] | Inspection/test/native-authorization command reference. |
| [[99-Source-Documents/README]] | Public product description, historical milestones, usage. |
| Older docs under `docs/`, `docs/handoff/<date>/` | Dated proof/preparation records; authoritative for what they themselves state. |

A source may be newer in *some* respects and older in others. Preserve dates, authority,
scope, and conflicts; never silently reconcile contradictory records.

## 3. Evidence-backed current state (snapshot, 2026-10-26)

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
| Milestone D4 native road + station construction | **PROVEN 2026-10-26 — FOUR ATTEMPTS CONSUMED, the completing identity is `D4-CORRIDOR-5` (E35); the first three ended incomplete.** `D4-CORRIDOR-1` (E21) halted `PHASE_HALTED_PREFIX_PRESERVED` (`op-00` only, £785; `op-01` refused £2,549 > £2,000). The Option C 8-op restage was implemented offline (E22), reviewed `PASS WITH CONCERNS` (E23), and staged as candidate-2 (E24), which was later proved stale (never consumed, not edited). Fresh candidate **`D4-CORRIDOR-3`** was staged (E27), then signed, verified and **consumed exactly once** (E28): `op-00`–`op-02` built and read back (£496,543 → £493,209), `op-03` interior join refused at admission as `NOT_BUILDABLE` (cost 0), `op-04`–`op-07` and the route read never executed. Result `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `FAILED_CLEANUP`; no authoritative after-save/receipt. **E29 (offline):** `op-03` was a redundant scheduled interior join, not an admission bug — scripted full-build endpoints already auto-connect the collinear segments (`pairs_ok 1`), while the perpendicular corner still needs its own join. Fresh schedule is v3, 7 ops, 22 planned exchanges / budget 28; v1/v2 retained for read-only replay. E30 separately verified candidate-3 credential removal and workspace disposal (`credential_removed: true`, `workspace_disposed: true`, workspace absent, no secret/config file); the historical `FAILED_CLEANUP`, absent `sockets_closed` and replay refusal remain, so this is not native success. E31 then staged fresh candidate **`D4-CORRIDOR-4`** from v3 (7 ops / 22 planned / cap 28 / £2,000 per-op, no interior join, corner retained, seal `88cd1ecc…fd22c3`, plan digest `b5b472ff…2283a78`, payload `4037c5d8…487c7f`). Candidate-4 was signed under the pinned anchor and **consumed exactly once** (E32): `op-00`–`op-05` built and read back (£4,004; £496,543 → £492,539), including the perpendicular corner and both stops; `op-06` depot was dispatched and the native log reports `BUILT`, but its 513-byte response exceeded the then-hard-coded 512-byte application limit and was rejected before parsing (`MalformedMessage`). No `confirm-06`, receipt or authoritative after-save; route read not reached. Phase `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `PHASE_HALTED_PREFIX_PRESERVED`; cleanup PASS (all four fields true), manifest 80/80. Offline E33 corrects protocol 4's decode bound to 640 (default 512 unchanged); the retained frame parses, but replay still refuses for missing durable confirmation. No retry or reuse of consumed identities; finally `D4-CORRIDOR-5` was staged from the reviewed v3 sources (independent fresh-context review **PASS 20/20**), every pre-signing gate was re-verified, and under the explicit 2026-10-26 operator authorization it was signed by the approved checklist (record `55486971…dec03` under the pinned production anchor) and **consumed exactly once (E35)**: 1 launch / 1 X25519 connection / 22 of 28 requests; all seven v3 ops dispatched with positive tested quotes equal to native costs within the £2,000 per-op ceiling (£785 + £1,398 + £1,151 + £71 + £307 + £292 + £390 = £4,394), each independently read back including `confirm-06` on the durable 513-byte depot response under the E33 640-byte bound; funds £496,543 → £492,149; route `ROUTE_VERIFIED` 23/23; authoritative receipt-bound `after.sav` `a81ac836…ef261`; cleanup certified; manifest 90/90; read-only replay `RECEIPT_VERIFIED`; historical evidence byte-unchanged. **Milestone D4 is COMPLETE (native) for exactly the reviewed v3 scope**; the claim is consumed and no vehicle/delivery/OPEX/ROI claim is implied. The authority-pin conflict is repaired explicitly (E26/ADR-014). | E21, E22, E23, E24, E26, E27, E28, E29, E30, E31, E32, E33, E35 |
| Offline V1/V2 semantic reconciliation (uncommitted work) | ADR-012 + ADR-013 accepted: 6 temporal + 19 definitional tiles resolved in the derived layer; combined P08 **planning** binding allowed, `p08_complete: false`; fusion gate **CLOSED** | [[05-Planning/Blockers]] |
| Full OPEX / net-profit / ROI | **UNKNOWN** — never invent | — |

## 4. Blockers and next action

- **D4 closed COMPLETE (2026-10-26, E35):** under the explicit operator
  authorization covering signing plus exactly one attempt, `D4-CORRIDOR-5` was
  staged from the reviewed v3 sources (independent fresh-context review
  **PASS 20/20**), every pre-signing gate re-verified fresh, signed by the
  documented approved checklist (record `55486971…dec03` verified under the
  pinned production anchor; the seed was captured, never displayed or logged,
  and cleared after signing) and consumed exactly once: 1 launch / 1 X25519
  connection / 22 of 28 requests; all seven v3 ops verified with quote-equal
  native costs (£4,394; £496,543 → £492,149), route `ROUTE_VERIFIED` 23/23,
  authoritative receipt-bound `after.sav` `a81ac836…ef261`, cleanup certified,
  manifest 90/90, read-only replay `RECEIPT_VERIFIED`; historical evidence
  (candidate-1/2/3/4, D2/D3) re-verified byte-unchanged. **Milestone D4 is
  COMPLETE (native) for exactly the reviewed v3 scope** — construction only,
  no vehicle/delivery/OPEX/ROI claim; the one-shot claim is consumed.
  Record: `docs/handoff/2026-10-26/d4-corridor-native-candidate-5-outcome.md`.
- **Recommended next engineering task (updated 2026-10-26):** D5 offline
  implementation T1–T6 is complete and uncommitted — protocol-5 contracts,
  the bounded fifteen-exchange package, the staging/preflight/replay proof
  module, 32 controlled VM tests and 29 temporary-staging native-orchestration
  tests pass. Design: `docs/d5-corridor-freight-design.md`; preparation/T6
  record: `docs/d5-corridor-freight-preparation.md`. A prior T7 review covered
  earlier D5 bytes; later source edits mean that review does not by itself
  establish a fresh comprehensive review of the current bytes, and no durable
  T7 review record is stored in the repository. Current revalidation re-ran
  the D5 suite (74 passed) and the D4/transport regression suite (71 passed)
  and verified the four 640-byte request-bound call sites; completing T7
  against the current bytes and archiving that record remain outstanding.
  Staging (T8) and any signing or launch (T9) remain separate gates exactly
  as recorded in the design's §12 — nothing exists yet: no candidate, claim,
  signature or authorization, and no native attempt has run, so native
  freight delivery remains UNKNOWN. Neither this note nor any vault page
  grants that authorization.
- **Superseded recommendation (2026-10-25, E33), retained as history:** the depot
  response-size defect is fixed offline: protocol 4 now uses its documented
  640-byte decode bound (version-one 512 default unchanged), and the retained
  513-byte payload parses. Next, stage a fresh, never-consumed candidate from
  reviewed source and re-run the focused suites plus `PRELAUNCH`/`PREFLIGHT`.
  After independent review, obtain ONE explicit operator authorization for
  signing and a single native attempt; this note grants neither. `D4-CORRIDOR-4`
  was consumed exactly once and must not be retried or reused: `op-00`–`op-05`
  built and read back (£4,004; £496,543 → £492,539), `op-06` depot's 513-byte
  response was rejected before parsing (native log says `BUILT`), no
  authoritative after-save/receipt exists, and the route read was not reached;
  result `PARTIAL_EXECUTION_EVIDENCE` / `verified: false` /
  `PHASE_HALTED_PREFIX_PRESERVED`, cleanup PASS, manifest 80/80. Replay now
  stops at the missing durable confirmation, not at the frame decoder.
  Candidate-3's historical `FAILED_CLEANUP` and absent `sockets_closed` remain
  unchanged and were judged attempt-scoped, not a prerequisite for candidate-4.
  Records:
  `docs/handoff/2026-10-25/d4-corridor-native-candidate-3-preparation.md`,
  `…-outcome.md`, `…-cleanup-remediation.md`, `…-candidate-4-preparation.md` and
  `…-candidate-4-outcome.md`.
  Historical candidate-2 records remain valid for their own dated scope:
  `docs/handoff/2026-10-22/d4-corridor-native-candidate-2-preparation.md` and
  `…-payload-verification.md`.
  **Operator-guidance correction (2026-10-24, documentation only):** the
  operator-key extraction commands in
  `docs/handoff/2026-10-17/operator-key-provisioning.md` §1 and
  `docs/handoff/2026-10-21/d2-native-clearing-candidate-3-preflight.md` §6(b)
  were corrected to the tested pipeline (`od`/`tr`, no `-noout` on the DER
  seed extraction, `pipefail` state captured and restored). It was validated
  with **synthetic keys only**; no production key was accessed and nothing
  was signed. A follow-up 2026-10-24 documentation pass added explicit
  extraction failure checks (exit status, `^[0-9a-f]{64}$` shape check,
  immediate `unset` + refusal on failure) and workflow-ordered explicit
  seed-cleanup commands (`unset SEED_HEX` only after the last legitimate
  same-shell use) to provisioning §1/§2/§4, keeping them consistent with
  the preflight §6(b) checks; same validation scope, still documentation
  only. A follow-up deviation record (2026-10-24,
  `docs/handoff/2026-10-24/operator-key-test-boundary-deviation.md`)
  documents that the preceding session's failure-path check had accessed
  the real operator PEM path (output discarded; key access acknowledged,
  no disclosure or persistence established), and re-validated all
  extraction/cleanup checks with **synthetic files only**. Still
  documentation, not authorization. The candidate was later signed and consumed
  under separate explicit authorization (E28); D4 remains **INCOMPLETE**
  *as of that dated correction — D4 was completed natively on 2026-10-26 by
  E35; see the close-out bullet above.*
  **Random-World follow-up (2026-10-25, offline):** ADR-012 records the
  delegated decision on the six temporal P08 tiles (save-instant census
  authoritative for their tree-lifecycle deltas, **planning evidence only**);
  the fail-closed application layer + tests are implemented (14/14 PASS),
  nothing was relabeled, the fusion gate stays closed and P08 remains
  `INCOMPLETE_TILE_CLASSIFICATION` (19 retained-UNKNOWN tiles outside the
  policy). **Rebinding pass (2026-10-25):** `rebind_p08_policy` re-derives and
  byte-compares the derived report against sealed inputs, accepting only the
  exact six-tile scope with verbatim rows (stale/edited/out-of-scope evidence
  refused; 24/24 tests PASS). At that point the computed binding was still
  **not allowed**: the 19 `UNKNOWN_OCCUPANCY` tiles remained unresolved. See
  [[06-Decisions/Decision Log]] ADR-012 and
  `docs/random-world-six-tile-policy-decision.md` §5.
  **19-tile root cause (2026-10-25):** all 19 retained `UNKNOWN_OCCUPANCY`
  tiles were diagnosed as one definitional group (census `CLEAR`, unowned,
  non-flat, already `SEMANTIC_RECONCILED` on `buildable`).
  **ADR-013 accepted and active:** native `GSTile.IsBuildable` semantics now
  map exactly those 19 tiles to `TERRAIN_MODIFICATION` in the derived layer
  only; the base ledger keeps them `UNKNOWN_OCCUPANCY`. The separate combined
  rebinding with ADR-012 computes `p08_binding.allowed: true` for **planning
  classification only**, with derived counts 339/63/29/19/0 and **zero**
  UNKNOWN. It records `p08_complete: false`; the sealed fusion gate remains
  **CLOSED** by the six temporal tiles and was not opened. No signing,
  candidate consumption, launch, AdminPort access or native evidence occurred.
  See [[06-Decisions/Decision Log]] ADR-013,
  `native-isbuildable-policy-report.json` and
  `p08-native-isbuildable-rebinding-report.json`.
- **Session addendum (2026-10-25):** (1) the explicit operator-authorized
  `CONTEXT.md` authority-pin repair (E26, ADR-014) preserves every retained manifest
  byte-for-byte and scopes only the exact historical/current digest transition; the
  three former baseline failures pass. (2) A read-only preflight proved
  `D4-CORRIDOR-2` stale (`verify_freeze`) because its frozen closure predates the
  accepted ADR-012/ADR-013 edits; the candidate was never consumed and was not edited.
  (3) A fresh candidate `D4-CORRIDOR-3` was staged from the current reviewed
  bytes and the verified D3 after-save (E27), then signed, verified and consumed
  by exactly one authorized native run (E28): `op-00`–`op-02` built and read
  back, `op-03` interior join refused at admission as `NOT_BUILDABLE` (cost 0),
  and `op-04`–`op-07` plus the route read never executed. Result
  `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `FAILED_CLEANUP`; no
  authoritative after-save/receipt. (4) Candidate-4 was staged from v3
  (`PRELAUNCH PASS` + `PREFLIGHT PASS`, E31), signed under the pinned anchor and
  consumed exactly once (E32): `op-00`–`op-05` built and read back (£4,004;
  £496,543 → £492,539), including the perpendicular corner and both stops;
  `op-06` depot's 513-byte response exceeded the then-hard-coded 512-byte
  application limit and was rejected before parsing, so no authoritative
  after-save/receipt or route read exists. `PARTIAL_EXECUTION_EVIDENCE`,
  `verified: false`, `PHASE_HALTED_PREFIX_PRESERVED`; cleanup PASS, manifest
  80/80. Offline E33 corrects protocol 4's decode bound to 640; the retained
  frame parses, but replay still refuses for missing durable confirmation. D4
  remains INCOMPLETE (native); next is a fresh separately authorized candidate.
  *(Closed 2026-10-26: E35 completed the chain — see the D4 close-out bullet
  above.)*
  Records: `docs/handoff/2026-10-25/context-authority-pin-repair.md`,
  `…/d4-corridor-native-candidate-3-preparation.md`, `…-outcome.md`,
  `…-candidate-4-preparation.md`, `…-candidate-4-outcome.md` and
  `…-response-limit-fix.md`.
  (5) Native attempt analytics (E34, offline, read-only) was implemented in a
  parallel workstream, verified over the same base, and integrated into the
  main checkout 2026-10-25: `app/experiments/native_attempt_analytics.py`,
  additive CLI subcommand `analyze-native-attempts` and focused tests. It
  reads retained attempt records only, copies statuses/verified flags
  verbatim, never counts an unverified or partial attempt as a verified
  success, keeps missing fields UNKNOWN, certifies cleanup fail-closed and
  states schedule-revision contrasts without causal claims. Post-integration:
  focused 34/34 + adjacent 84 PASS, deterministic outputs, the seven retained
  attempt directories hash-verify byte-identical. No candidate staged, no
  claim consumed, no native evidence created; D4 remains INCOMPLETE (native)
  as of that record. *(2026-10-26: D4 was then completed natively by E35 —
  see the D4 close-out bullet above.)*

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
(`docs/handoff/2026-10-17/`, plus newer records under `docs/handoff/2026-10-21/`,
`docs/handoff/2026-10-22/` and `docs/handoff/2026-10-25/`).
