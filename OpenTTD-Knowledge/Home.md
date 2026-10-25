---
title: "Home"
type: hub
status: current
updated: 2026-10-26
tags:
  - openttd
  - hub
---

# OpenTTD Integration — Knowledge Vault

**Python plans it. OpenTTD 15.3 runs it. Receipts prove it.**

An OR-Tools logistics planner (P08 road candidates → P05 CP-SAT selection) executes
validated plans inside a real OpenTTD 15.3 world through an encrypted AdminPort +
GameScript bridge, then verifies outcomes against native state with machine-readable
receipts.

> Start at **[[AI_START_HERE]]**. Status vocabulary: [[07-Reference/Status Definitions]].

## Current position (2026-10-26 snapshot)

- Milestone D4 native road + station construction **COMPLETE (native) 2026-10-26
  (E35)**: under the explicit operator authorization covering signing plus
  exactly one attempt, `D4-CORRIDOR-5` was staged from the reviewed v3 sources
  (independent review PASS 20/20), every pre-signing gate re-verified fresh,
  signed by the approved checklist (record `55486971…dec03` under the pinned
  production anchor) and consumed exactly once — 1 launch / 1 X25519
  connection / 22 of 28 requests; all seven v3 ops dispatched with positive
  tested quotes equal to native costs within the £2,000 per-op ceiling
  (£785 + £1,398 + £1,151 + £71 + £307 + £292 + £390 = £4,394; funds £496,543 →
  £492,149), each independently read back including `confirm-06` on the durable
  513-byte depot response under the E33 640-byte bound; route `ROUTE_VERIFIED`
  23/23; authoritative receipt-bound `after.sav` `a81ac836…ef261`; cleanup
  certified; manifest 90/90; read-only replay `RECEIPT_VERIFIED`. Exactly the
  reviewed v3 scope — no vehicle/delivery/OPEX/ROI claim; the claim is
  consumed, so the next native step (D5 vehicle work) needs a fresh candidate
  + fresh authorization → [[05-Planning/Next Actions]].
- Stable fixed demo **VERIFIED** (E1) — 3 services, 60 coal, £1,022 revenue.
- Milestone D3 native terraforming **PROVEN** (E19); **the three earlier D4
  attempts are immutable history** (E21, E28, E32). `D4-CORRIDOR-4` was signed under the
  pinned anchor and consumed exactly once on 2026-10-25 (E32): `op-00`–`op-05`
  built and read back (£4,004; funds £496,543 → £492,539), including the
  perpendicular corner `45743↔45999` and both stops. `op-06` depot was dispatched;
  the native log reports `BUILT`, but its 513-byte response exceeded the then-hard-
  coded 512-byte `MAX_PAYLOAD_BYTES` limit and was rejected before parsing. No
  `confirm-06`, receipt or authoritative `after.sav`; the route read was not
  reached. Phase `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`,
  `PHASE_HALTED_PREFIX_PRESERVED`; cleanup PASS (all four fields true), manifest
  80/80. Offline E33 corrects protocol 4's decode bound to 640 (version-one 512
  unchanged); the retained frame parses, but replay still stops at missing
  durable confirmation. Candidate-3's historical `FAILED_CLEANUP` remains
  unchanged; cleanup certification was judged attempt-scoped, not a prerequisite
  for a fresh candidate. That chain was then completed by `D4-CORRIDOR-5` on
  2026-10-26 — first bullet above; retained chain history:
  → [[02-Milestones/Pending Milestones]], [[02-Milestones/Completed Milestones]].
  **Operator-guidance correction 2026-10-24 (documentation only):** the
  extraction commands in the provisioning doc and D2-3 §6(b) now use the
  synthetic-key-validated `od`/`tr` pipeline with `pipefail` state preserved;
  a follow-up pass added explicit extraction failure checks and
  workflow-ordered `unset SEED_HEX` cleanup to the provisioning doc,
  consistent with §6(b);
  no production key was accessed and nothing was signed at that time; the
  candidate was later signed and consumed under separate explicit authorization
  (E28).
- P08 temporal and definitional tiles: **resolved in the derived planning layer**
  by ADR-012 (six temporal, delegated 2026-10-24/25) and ADR-013 (19
  definitional, operator-authorized and accepted 2026-10-25). ADR-013 adopts
  native `IsBuildable` semantics for exactly the 19 tiles → derived
  `TERRAIN_MODIFICATION`; base ledger stays verbatim, sealed verdicts
  unrelabelled. Separate combined rebinding is `allowed: true` for **P08
  planning classification only**, with `p08_complete: false`; the fusion gate
  remains **CLOSED**. Focused tests 41/41, broader group 83/83. No native
  evidence, launch, signing or candidate consumption. → [[05-Planning/Blockers]] §2.
- Random World: Seed 17 native service execution remains **FAILED/BLOCKED**;
  V2 census captured natively but SOURCE_SAVE_FUSION **REJECTED** (E16) → [[05-Planning/Blockers]].
- Native attempt analytics: offline, read-only run-level analytics over the
  seven retained native attempt directories is **implemented and integrated**
  (E34, 2026-10-25) — statuses and verified flags copied verbatim,
  unverified/partial attempts never counted as verified successes, missing
  fields stay UNKNOWN (no OPEX/profit/ROI), cleanup certification fail-closed,
  lineage comparison descriptive only; deterministic outputs; retained
  evidence hash-unchanged; no candidate staged, nothing consumed →
  [[04-Evidence/Controlled Tests]].

## Navigate

| Area | Notes |
|---|---|
| **Project** | [[00-Project/Project Overview]] · [[00-Project/Current Status]] · [[00-Project/Roadmap]] · [[00-Project/Scope and Non-Goals]] |
| **Architecture** | [[01-Architecture/System Architecture]] · [[01-Architecture/Component Map]] · [[01-Architecture/Data Flow]] · [[01-Architecture/OpenTTD Integration]] · [[01-Architecture/AdminPort Protocol]] · [[01-Architecture/Planning and Execution Boundary]] |
| **Milestones** | [[02-Milestones/Milestone Index]] · [[02-Milestones/Completed Milestones]] · [[02-Milestones/Pending Milestones]] |
| **Engineering** | [[03-Engineering/Source Code Map]] · [[03-Engineering/Testing Strategy]] · [[03-Engineering/Reproduction Guide]] · [[03-Engineering/Runtime and Environment]] · [[03-Engineering/Troubleshooting]] |
| **Evidence** | [[04-Evidence/Evidence Index]] · [[04-Evidence/Native Verification]] · [[04-Evidence/Controlled Tests]] · [[04-Evidence/Failed Attempts]] · [[04-Evidence/Evidence Preservation]] |
| **Planning** | [[05-Planning/Task Board]] · [[05-Planning/Next Actions]] · [[05-Planning/Blockers]] · [[05-Planning/Technical Debt]] |
| **Decisions** | [[06-Decisions/Architecture Decision Records]] · [[06-Decisions/Decision Log]] |
| **Reference** | [[07-Reference/Glossary]] · [[07-Reference/Status Definitions]] · [[07-Reference/Important Paths]] · [[07-Reference/External References]] |
| **Source documents** | [[99-Source-Documents/CONTEXT]] · [[99-Source-Documents/AI_HANDOFF]] · [[99-Source-Documents/TASKS]] · [[99-Source-Documents/EVIDENCE_INDEX]] · [[99-Source-Documents/REPRODUCE]] · [[99-Source-Documents/README]] |

## Maintenance

- Update rules: [[AI_START_HERE]] §7.
- Vault captured **2026-10-22** against `devmodule2` (commit `5872689`, dirty tree);
  evidence notes were updated through **2026-10-26**. Implementation changes after the
  capture date may not be reflected here — re-verify against the working tree before
  acting. See [[00-Project/Current Status]].
