---
title: "Home"
type: hub
status: current
updated: 2026-10-24
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

## Current position (2026-10-25 snapshot)

- Stable fixed demo **VERIFIED** (E1) — 3 services, 60 coal, £1,022 revenue.
- Milestone D3 native terraforming **PROVEN** (E19); **D4 remains INCOMPLETE —
  consumed attempts only** (E21, E28). `D4-CORRIDOR-3` was signed, verified and
  consumed once on 2026-10-25: `op-00`–`op-02` built and read back (£496,543 →
  £493,209), `op-03` interior join refused at admission as `NOT_BUILDABLE`
  (cost 0), `op-04`–`op-07` and the route read not executed; no authoritative
  after-save/receipt, cleanup incomplete. Next: fix `op-03` admission, then a
  fresh separately authorized candidate → [[05-Planning/Next Actions]].
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
- Vault captured **2026-10-22** against `devmodule2` (commit `5872689`, dirty tree).
  Implementation changes after that date are **not reflected** here — re-verify against
  the working tree before acting. See [[00-Project/Current Status]].
