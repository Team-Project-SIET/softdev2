---
title: "Completed Milestones"
type: milestone
status: current
updated: 2026-10-26
tags:
  - openttd
  - milestone
  - evidence
---

# Completed Milestones

Every entry is scoped to what its evidence actually supports. Historical OpenTTD 13.4
results do **not** establish 15.3 compatibility. Evidence records:
[[04-Evidence/Evidence Index]]; failure record: [[04-Evidence/Failed Attempts]].

## Fixed playable demo — E1 (checkpoint `a3480169dcbefefff7b1adfb060449643c8eb04c`)

**VERIFIED (native 15.3, in-scope):** P08/P05 selected 3 freight services (4→5, 2→3, 0→1);
vehicles 4/5/6 constructed; 20 coal delivered per service; **60 coal, £1,022 revenue,
£28,459 CAPEX**; graphical spectator joined and inspected; fresh P07 reporting, cleanup
and evidence checks PASSED. Retained package:
`artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a/`.
Limits: short serial delivery batches; revenue is timing-dependent and not profit;
Attempt 17's bundled £1,018 sample is a different run; no direct company control;
full OPEX/ROI UNKNOWN — remains the stable default.

## Canonical fleet create/reload Q3 — E2 (historical PROVEN engineering)

- Create Q3: `CANONICAL_CREATED_PENDING_FRESH_PROCESS_RELOAD` — 1 launch/connection,
  27 mutations.
- Reload Q3: `CANONICAL_RELOAD_ONLY_VERIFIED` — exact semantic correspondence, 1
  launch/connection, **0 mutations**, paused before/after, originals restored, heartbeat
  advances; protected source save SHA-256
  `51e45689ae40dfa53c2cc150a05076fcb6e5cc2f38ec4eff56908372ab1297eb`.
- Scope guard: reload-only. Purchase/dispatch/unpause and native intervention/matched
  A/B outcomes are **not** established by this milestone
  (→ [[02-Milestones/Pending Milestones]]).

## Native freight delivery attempts (stage-gated lineage)

| Attempt | Date | Result (scope-bound) |
|---|---|---|
| Attempt 4 | 2026-10-11 | Standalone delivery: 20 coal; offline replay verified £341 delivery income, £304 vehicle-profit increase, £9,358 construction+purchase. Plan-bound receipt retained. |
| Attempt 9 | 2026-10-13 | Planner-driven: P08/P05 selection → native construction → loaded arrival → industry-attributed delivery → payment; £325 income, £289 vehicle-profit increase, £9,586 CAPEX; receipt replayed offline; 1 launch, encrypted session, no retry. |
| Attempt 12 | 2026-10-14 | Two serial services in one world; industry IDs 0–3; aggregate 40 coal, £682 revenue, £19,101 CAPEX (infrastructure £10,243 + vehicles £8,858); shared CAPEX £0 — proves aggregate accounting without duplication, not paid reuse. |
| Attempt 17 | (accounting checkpoint `ea8e92f`, 2026-10-14) | Three serial services; 60 coal, £1,018 revenue, £28,459 CAPEX (see [[02-Milestones/Milestone Index]]); financial reconciliation £471,492; 8,522 protected files unchanged; checkpoints `16345fa`(12)/`93986e0`(9)/`92388cb`(standalone). |

Historical caution (README): the fixed demo's headline (60 coal/£1,022) and Attempt 17
(60 coal/£1,018) are different runs; never merge their ledgers.

## Milestone D2 — native clearing (E17, 2026-10-21)

Tile 46769 pinned from the sealed census (`TREES`, flags 9, elevation 2, slope 0, unowned)
was cleared by the single `GSTile.DemolishTile(tile)` (`CMD_LANDSCAPE_CLEAR`, **£15**
command-scoped cost = company cash delta £500,000 → £499,985, within the £10,000 cap and
the £15 test quote). Independent readback verified `NATIVE_STATE_CHANGED`
(TREES → CLEAR). Result `NATIVE_STATE_VERIFIED`, returncode 0, 4 requests
(`read-0`, `inspect-1`, `clear-1`, `read-2`), 1 launch / 1 encrypted X25519 connection,
claim `d2-clearing-claim-authorization-v2` consumed with zero retries, cleanup complete,
25-file manifest hash-verifies. The record-writing session did **not** initiate the
launch — it found the claim consumed and performed no re-run. Scope: exactly one tile in
the retained Seed 17 world.

## Milestone D3 — native bounded levelling (E18 staging, E19 close-out 2026-10-22)

All three one-shot candidates consumed; receipts re-verify `RECEIPT_VERIFIED` under the
read-only production replay verifier:

| Candidate | Operation | Pin | Cost |
|---|---|---|---|
| D3-CLEARING-1 | `CMD_LANDSCAPE_CLEAR` (TREES→CLEAR) | 45999 (175,179) | £30 |
| D3-CLEARING-2 | `CMD_LANDSCAPE_CLEAR` (TREES→CLEAR) | 49326 (174,192) | £45 |
| D3-TERRAFORMING-1 | 16 × `CMD_TERRAFORM_LAND` (S-corner raise, up, mask 0x2) | hosts 48558…50351 | £3,382 |

- Terraforming phase: 144 requests (16 operations × 9), statuses 16/16
  `NATIVE_STATE_CHANGED`, phase `PHASE_COMPLETE`; source save byte-bound to clearing-2's
  after-world; authoritative after.save
  `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e` (the distinct
  `after-diagnostic.sav` is retained, never substituted).
- Finance reconciles exactly: £500,000 − £30 − £45 − £3,382 = **£496,543** (confirmed in
  `verify-15` readbacks).
- Geometry: 27/27 raised-band tiles agree; post-D3 the planned 24-tile corridor
  45748(180,178) → … → 50351(175,196) is flat min-height 2, slope 0, CLEAR, unowned,
  industry-free on every tile.
- This world is the verified evidence base for D4 preparation (E20).

## Milestone D4 — native road & station construction (E20–E35; completed 2026-10-26)

Consumed as four one-shot identities over five staged candidates; three ended
incomplete and the final one completed the reviewed v3 schedule exactly:

| Identity | Date | Outcome (scope-bound) |
|---|---|---|
| `D4-CORRIDOR-1` | 2026-10-22 | Partial: `op-00` verified (£785), `op-01` refused £2,549 > £2,000 ceiling, halted, no receipt/after-save (E21) |
| `D4-CORRIDOR-2` | — | Staged only, never consumed; proved stale (closure predates ADR-012/ADR-013) (E24, E27) |
| `D4-CORRIDOR-3` | 2026-10-25 | Partial: 3 ops built (£2,534); redundant interior join correctly `NOT_BUILDABLE`; historical `FAILED_CLEANUP` preserved (E28; E30 remediation) |
| `D4-CORRIDOR-4` | 2026-10-25 | Partial: 6/7 ops built (£4,004); `op-06` depot 513-byte response rejected under the then-512-byte limit (E32; offline fix E33) |
| `D4-CORRIDOR-5` | 2026-10-26 | **COMPLETE — all seven v3 operations verified, route verified, authoritative after-save retained (E35)** |

The completing attempt (`D4-CORRIDOR-5`, consumed exactly once under the
explicit 2026-10-26 operator authorization covering signing plus one attempt;
all pre-signing gates re-verified; signed by the approved checklist and
verified under the pinned production anchor before writing):
1 launch / 1 X25519 connection / 22 of 28 request budget; every op dispatched
exactly once with a **positive tested quote equal to its native cost**, within
the £2,000 per-op ceiling, each independently read back via its
intent-scoped `confirm-XX`:

| Op | Planned scope | Inner pin(s) | Native cost | Readback | Funds after |
|---|---|---|---:|---|---:|
| op-00 | run A 45747→45743 (5 tiles) | 45747→45743 | £785 | `confirm-00` READ | £495,758 |
| op-01 | run-B segment (9 tiles) | 45999→48047 | £1,398 | `confirm-01` READ | £494,360 |
| op-02 | run-B segment (8 tiles) | 48303→50095 | £1,151 | `confirm-02` READ | £493,209 |
| op-03 | perpendicular corner road | 45743↔45999 | £71 | `confirm-03` READ | £493,138 |
| op-04 | pickup stop | tile 45748, front 45747 | £307 | `confirm-04` READ | £492,831 |
| op-05 | delivery stop | tile 50351, front 50095 | £292 | `confirm-05` READ | £492,539 |
| op-06 | depot | tile 45487, front 45743 (south) | £390 | **`confirm-06` READ** (513-byte durable response under the E33 640-byte bound) | **£492,149** |
| route read | 24-tile witness / 23 adjacent pairs | — | 0 | `ROUTE_VERIFIED`, 23/23, `first_fail_index −1` | £492,149 |

- Finance reconciles exactly and is confirmed twice (route read + depot
  readback path): £496,543 − £785 − £1,398 − £1,151 − £71 − £307 − £292 − £390
  = **£492,149**.
- Schedule invariants held: 7 ops / 22 planned exchanges / 28-request cap
  (22 used) / no redundant interior join / corner `45743↔45999` present.
- `receipt.json` (`PHASE_COMPLETE`, seven per-op receipts + route receipt)
  binds before-save `a3e6b510…5c5c` and the **authoritative** `after.sav`
  `a81ac836…ef261`; `after-diagnostic.sav` (`7a853eba…a3`) is a distinct
  diagnostic copy, never substituted; `result.json` returns `verified: true`,
  `status: NATIVE_CORRIDOR_VERIFIED`, return code 0.
- Cleanup certified (all four fields true, endpoints certified, workspace
  disposed, credential removed); artifact manifest 90/90 OK; the independent
  read-only replay verifier returns **`RECEIPT_VERIFIED`**.
- Evidence basis reviewed before authorization: the staged v3 candidate passed
  a fresh-context independent review **PASS 20/20** and was bound over the
  D3-verified world `fbebef54…d59e`; the one-shot claim is consumed.
  Record: `docs/handoff/2026-10-26/d4-corridor-native-candidate-5-outcome.md`.
- Scope: exactly corridor construction (two runs, corner join, two truck
  stops, depot, connected-route observation) over the post-D3 Seed 17 world.
  Not a vehicle, order, delivery, OPEX, profit or ROI claim; D5 remains a
  separate, fresh-authorization-gated milestone. Failed/partial/stale
  identities above are immutable and never retried.

## Tile Classification V2 — capture completed natively (E16, 2026-10-18)

90/90 pages, 450/450 tiles, schema-2 exchange, staged AI (`RoadProofCompany READY`) +
GameScript (`BRIDGE_STARTED protocol=1 api=15`) starting with zero script deaths,
exact per-page byte budgets (≤381 B response/page, ≤52,324 total), 0 mutations, cleanup
PASS. Offline rebinding reproduced recorded completeness byte-equal; 198-file manifest
hash-verifies. **Correspondence verdict `SOURCE_SAVE_FUSION` = REJECTED** (83
`PROJECTED_FLAGS_DIFFER`); nothing fused; the 19 historically UNKNOWN tiles were observed
CLEAR+buildable fresh but, as contradictions, stay UNKNOWN; P08 remains
`INCOMPLETE_TILE_CLASSIFICATION` (339 ROAD_BUILDABLE + 63 SUPPORTED_CLEARING + 19 UNKNOWN
+ 29 UNSUPPORTED). Capture success is **not** world correspondence.
→ reconciliation state: [[05-Planning/Blockers]].

## Historical baseline (explicitly not current)

- P03/P06 thin-AI transport + 13.4 road setup (Attempt #2, 2026-10-04) — retained
  regression evidence only; see [[01-Architecture/System Architecture]].
