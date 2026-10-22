---
title: "Native Verification"
type: evidence
status: current
updated: 2026-10-22
tags:
  - openttd
  - evidence
  - native
---

# Native Verification

What "VERIFIED"/"PROVEN" means and exactly which native behaviors are covered.

## Definition and rules

- **VERIFIED**: supported by inspected retained reports, within the stated scope — not a
  fresh re-run, not a broader claim, not "because tests pass".
- **PROVEN**: historical retained native engineering evidence that carried its full
  gate chain (recorded at the time; canonical Q3, D-milestones).
- A GameScript "success" message, a command ACK, or an empty vehicle alone is never
  delivery proof; receipts fail closed. Evidence combines planner request → execution
  result → actual world-state verification → AdminPort/log evidence → receipt (CONTEXT §13).
- Native capture success ≠ world correspondence (E16).

## Natively verified behaviors (in exact scope)

| # | Behavior | Where proven | Scope boundary |
|---|---|---|---|
| N1 | Full freight MVP loop: encrypt AdminPort, preamble, construct depot+roads+stops, purchase trucks, orders, loading, delivery, payment, per-service income readback | E1 (fixed demo, checkpoint `a348016`); E-attempt lineage 4/9/12/17 | One company; serial batches; one vehicle/service; bounded worlds; no direct player control; revenue≠profit; OPEX/ROI UNKNOWN |
| N2 | AdminPort round trip: request → `GSEventAdminPort` → `GSAdmin.Send` ACK correlated by `request_id` | CONTEXT §22 initial transport proof | No game-world mutation in that proof |
| N3 | Canonical constructed fleet save + fresh-process reload correspondence | E2 (Q3 create + reload) | Reload-only; no purchase/dispatch/unpause |
| N4 | Single-tile tree clearing (`GSTile.DemolishTile`, £15 cost accounting) | E17 (D2, tile 46769) | Exactly one tile in retained Seed 17 world |
| N5 | Bounded levelling: 2 clears + 16 compiled S-corner raises with per-op readbacks | E19 (D3) | Pre-defined corridor tiles only; £496,543 reconciliation |
| N6 | Encrypted schema-2 paginated tile-classification census (450 tiles/90 pages) | E14(failed→E15 repaired)/E16 (completed) | Capture only; SOURCE_SAVE_FUSION REJECTED; no fused world model |
| N7 | Random world native generation, discovery, spectator navigation, GUI inspection | E4, E8 (Seed 17) | No service construction/delivery; P05 NOT_RUN in smoke; funding mutation separate |
| N8 | Same-run qualification + production observation (two-rollover) | CONTEXT §20 Attempt 2 native phase | Overall attempt FAILED (post-run verification failed) — do not cite as passed qualification |

## What native verification requires (the D-ceremony chain)

1. A reviewed **candidate** (staged planner, frozen sources, sealed `PRELAUNCH.json`).
2. Independent preflight (`PREFLIGHT PASS`).
3. **One fresh operator authorization** → one-shot claim.
4. One launch + one encrypted connection.
5. Command hoisting + per-op independent readbacks.
6. Receipt verification replay; status `VERIFIED`/`NATIVE_STATE_VERIFIED`/`RECEIPT_VERIFIED`.
7. Full owned cleanup (process reaped, sockets closed, credential removed, workspace
   disposed) + artifact manifest.

The record-writing sessions for D2/D3 observed claims already consumed and explicitly did
not initiate launches — the authorization model is operator-owned (E17, E19).

## Proof vs correspondence vs capture (three different things)

- **Proof** (N1–N5): the executed action completed AND independent native readback agrees.
- **Capture** (N6): data collection completed — says nothing about agreeing with any
  historical projection.
- **Correspondence/fusion**: binding a fresh capture to retained evidence — currently
  REJECTED/unresolved ([[05-Planning/Blockers]]).

## Explicitly NOT natively verified (do not claim)

- Any service construction or delivery in a Random World.
- Direct company control via the game GUI.
- `GSAsyncMode`-based flows; engine integration beyond pinned ceremony shapes.
- OpenTTD 15.3 on platforms/layouts other than the pinned Linux amd64 distribution.
- Anything "...because code exists in the tree" ([[99-Source-Documents/AI_HANDOFF]]:
  presence in the dirty tree ≠ published or accepted natively).

## Where the bytes live

`artifacts/` per attempt (ignored by Git). Inventory/hash pointers:
[[04-Evidence/Evidence Preservation]]; index: [[04-Evidence/Evidence Index]].
