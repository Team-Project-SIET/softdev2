---
title: "Milestone Index"
type: milestone
status: current
updated: 2026-10-26
tags:
  - openttd
  - milestone
---

# Milestone Index

Two milestone tracks exist in the records:

1. **P-track** (architecture stations P01–P08) — spec:
   [[01-Architecture/Planning and Execution Boundary]].
2. **D-track** (native construction ceremonies on OpenTTD 15.3, Seed 17 world) — D1…D4:
   `docs/p08-bounded-clearing-construction.md`, E17–E35.

Plus **attempt history** — native execution attempts (delivery/canonical/qualification)
which are indexed by evidence ID and preserved immutably
([[04-Evidence/Evidence Index]]). Attempts are not milestones themselves; several
milestone records are *closed by* an attempt's consumed evidence.

## Track state at a glance

| Milestone | Proposition | Status | Evidence / record |
|---|---|---|---|
| P01–P08 stations | Planner/executor architecture specified & partially implemented | see [[01-Architecture/Planning and Execution Boundary]] | spec sections per Pxx |
| D1 | Reusable-contract mapping (road ceremony → clearing) | Offline complete, controlled | `docs/p08-bounded-clearing-construction.md` |
| D2 | Native tile clearing | **PROVED** | E17 |
| D3 | Native bounded levelling chain (2 clears + 16 raises) | **PROVEN** (closed 2026-10-22) | E18, E19 |
| D4 | Native road run ×2 + corner + 2 truck stops + depot on post-D3 world | **PROVEN, 2026-10-26** (candidate-5: all seven v3 ops verified with quote-equal native costs, `ROUTE_VERIFIED` 23/23, authoritative `after.sav`, cleanup certified, manifest 90/90, replay `RECEIPT_VERIFIED`; failed/partial history E21/E28/E32 stays immutable) | E35, E21, E28, E32, E33 |
| Stable fixed demo | Playable 3-service MVP at checkpoint `a348016` | **VERIFIED** | E1 |
| Canonical create/reload Q3 | Canonical constructed fleet save/reload correspondence | **PROVEN** (reload-only scope) | E2 |
| Random World native service execution | Plan→construct→deliver in a random world | **FAILED / BLOCKED** at `INCOMPLETE_TILE_CLASSIFICATION` | E4, E8, E16 |
| Tile Classification V2 census capture | Fresh 450-tile schema-2 census | **CAPTURE COMPLETE, FUSION REJECTED** | E14, E15, E16 |
| Two-rollover qualification (Attempt 2) | Native qualification with complete observations | Native phase SUCCESS/COMPLETED; overall **FAILED** (post-run verification failed) | CONTEXT §20 |

Dated details: [[02-Milestones/Completed Milestones]], [[02-Milestones/Pending Milestones]].

## Historical native attempts (milestone-relevant)

| Attempt | Date | What it proved / failed | Status |
|---|---|---|---|
| Attempt 4 | 2026-10-11 | First single-vehicle freight delivery, 20 coal, £341 income, £9,358 CAPEX | VERIFIED receipts |
| Attempt 9 | 2026-10-13 | Planner-driven delivery; P08/P05 → native build/load/deliver/pay, 20 coal | VERIFIED |
| Attempt 12 | 2026-10-14 | Two serial services in one world, aggregate accounting without duplication | VERIFIED (shared-asset reuse unproven) |
| Attempt 15 | (scaling checkpoint `219580c`) | Bridge crash after first road command (£2,512) | **FAILED**, consumed |
| Attempt 17 | (checkpoint `ea8e92f`, 2026-10-14 accounting evidence) | Three serial services, 60 coal, £1,018, full fixes from 15 | VERIFIED receipts |
| Attempt 19 | 2026-10-15 | Five economy years continuous operation | Native terminal **FAILED** (finalization collision); separate offline recovery verified |
| Attempts 10, 11 | pre-12 | NETWORK_INDUSTRY_BUILD_FAILED etc. | **FAILED**, consumed, preserved |
| Would-be capacity attempt (A/B/C prep; no seal/claim/launch exists) | — | Fourth-vehicle intervention prepared offline; native execution | **BLOCKED** (no retained canonical pre-intervention save) |

Environment caveat: retained artifacts under `artifacts/` are Git-ignored and may be
absent in other checkouts → those facts become UNKNOWN there ([[04-Evidence/Evidence Preservation]]).

## Attempt 17 verified detail (three-service native freight)

One launch, one secure connection; 87 execution requests, 33 mutations.

| Service | Coal | Revenue | Command CAPEX |
|---|---:|---:|---:|
| 4 → 5 | 20 | £340 | £9,358 |
| 2 → 3 | 20 | £352 | £9,515 |
| 0 → 1 | 20 | £326 | £9,586 |
| **Network** | **60** | **£1,018** | **£28,459** |

Reconciliation: £500,000 − £28,459 + £1,018 − £1,067 = £471,492 (unallocated decrease £1,067;
subcategories partially UNKNOWN). Serial batches; concurrent throughput and paid
shared-asset reuse unproven. Click-through receipts at `artifacts/runtime/openttd-15.3-first-freight-delivery-attempt17/`.
