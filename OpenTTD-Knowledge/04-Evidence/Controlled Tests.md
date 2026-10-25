---
title: "Controlled Tests"
type: evidence
status: current
updated: 2026-10-26
tags:
  - openttd
  - evidence
  - controlled
---

# Controlled Tests

**CONTROLLED** = offline tests, synthetic fixtures, or controlled validation. It never
proves native runtime behavior — that boundary is the project's cardinal discipline.

## Why controlled work exists

Preparation, contracts, planners, and diagnostics are developed and validated offline so
that the rare, one-shot, operator-authorized native attempts arrive with sealed frozen
inputs and preflighted gates. A controlled pass is a *readiness* signal, not a *native*
claim ([[07-Reference/Status Definitions]]).

## Major controlled conclusions (scope-bound)

| Item | What it is | Where |
|---|---|---|
| 512-tile random capture correction | Controlled/offline; no new native run: 512 fully observed tiles per rectangle; fixed demo stays 256; road path 2..47 unchanged; profile `random-rectangle-512-v1` (45 s, ≤546 reads/relationship) | E5 |
| Observation pipeline readiness | Offline verification + independent review; suites 90+297+216 (11 skipped); no native observation collected | E7 |
| Bounded reachability oracle | `corridor_reachability` over eligible vacant stops; frozen corridor regression intact; Seed 17 coal disconnect = complete-search proof | E9 |
| Bounded terrain-modification planning | Typed budgets (32 corner ops, ±1 step, 8 clears, 128 region, 47 interior road), planning-only proposals; `NO_CONNECTED_LEVELED_CORRIDOR` (176 expansions) for retained Seed 17 | E10 |
| Tile classification + feasibility (additive) | Schema-2 wire; five segment classes; `assess_world_feasibility`; readiness registry; 13+24 focused tests | E11 |
| V2 capture preparation | Receipt/exchange/sweep; 90-page plan; refuse-on-missing-seam staging; 16+7+9(+1) tests | E12 |
| V2 execution path | Staging/dispatch/runner/correspondence policy; 10+10+10+8 tests, offline | E13 |
| V2 diagnosis/repair | 35 focused tests incl. consumed-log replay; AI staging sealed | E15 |
| Offline V1/V2 semantic reconciliation | 450-tile replay: 77 definitional / 6 temporal / 0 contradictions / 0 unresolved → `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`. ADR-012 (6 temporal) + ADR-013 (19 definitional) active; combined P08 planning binding allowed (`p08_complete: false`), fusion gate CLOSED; focused/combined tests 41/83 | [[05-Planning/Blockers]] (uncommitted record) |
| Controlled P08→P05 chain | Observation admission, supplemental facts, prepared-source correspondence, bounded generation, P05 optimization, execution-plan validation — controlled source bytes are not an executable save | CONTEXT §20 |
| Synthetic flat fixture | 31-road-tile route, 1 selected service, £1,830 estimated construction/purchase | E5 (never a Seed 17 native result) |
| P07 analytics extension | Offline implementation verified on retained Attempt 19/fixed-demo evidence; advisory-only; FAILED terminals stay visible | 2026-10-18 checkpoint; README §P07 |
| Capacity experiment prep | A/B/C controlled plans (`minimum_vehicles_by_demand`); queue stats sampled | `docs/capacity-experiment.md` |
| D4 Option C 8-op restage + review | Offline 8-op split-run-B schedule (per-op ceiling unchanged, versioned derivation, budget 31); independent review = **`PASS WITH CONCERNS`** — 55 tests re-run fresh and the read-only `verify` replay of the consumed candidate returned the E21 verdict byte-identically; E24 re-runs the same 55 tests green after the operator-approved `CORRIDOR_ATTEMPT` → `D4-CORRIDOR-2` identity edit and stages the fresh candidate (PRELAUNCH/PREFLIGHT PASS) | E22, E23, E24 |
| D4 candidate-3 native run | **Consumed exactly once (native, partial):** 3/8 ops built and read back; `op-03` admission `NOT_BUILDABLE` (cost 0), runner refused unquoted dispatch; `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `FAILED_CLEANUP`; no authoritative after-save/receipt; replay refuses incomplete cleanup; manifest 48/48. No retry or reuse. | E28 |
| D4 candidate-3 cleanup remediation | **Read-only verification:** workspace disposed and credential removed (`cleanup.json` flags), workspace absent, no secret/config file or process/listener; historical `verification_error` and missing `sockets_closed` retained, so outcome/replay refusal unchanged; 48/48 manifest. | E30 |
| D4 v3 correction and candidate-4 staging | **Offline:** v3 7-op schedule (no redundant interior join, corner retained, 22 planned / cap 28, £2,000 per-op); focused suites 55/55 PASS; candidate-4 `PRELAUNCH PASS` + `PREFLIGHT PASS` (later signed and consumed in E32); no claim/launch at staging. | E29, E31, E32 |
| D4 candidate-4 native run | **Consumed exactly once (native, partial):** `op-00`–`op-05` built and read back (£4,004; £496,543 → £492,539); `op-06` depot native log reports `BUILT`, but its 513-byte response exceeded the then-hard-coded 512-byte limit and was rejected before parsing; `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `PHASE_HALTED_PREFIX_PRESERVED`; no authoritative after-save/receipt; cleanup PASS (all four fields); manifest 80/80. No retry or reuse. | E32 |
| D4 protocol-4 response bound | **Controlled/offline fix (E33):** version-one decode default remains 512; protocol 4 explicitly uses 640. The retained 517-byte depot frame (513-byte JSON payload) decodes and correlates to `BUILT`; exact 640 passes, 641 fails; malformed/truncated/duplicate/invalid-UTF-8 bodies fail closed; multibyte UTF-8 measured in bytes; absolute frame-body bound 32763. Focused suites 129/129 PASS; `ruff check --ignore UP037` passed with four pre-existing `UP037` findings unchanged; compile/diff clean. No receipt or native verification is created; replay still stops at the missing durable response. | E33 |
| Native attempt analytics (integrated) | **Offline read-only analytics over retained native attempts:** run-level planned/executed metrics, per-op RECEIPT/HALT/PENDING rows, fail-closed cleanup certification, milestone-lineage comparisons (descriptive only, no causal claim, no pooling across unrelated source worlds); statuses/verified flags verbatim, unverified attempts never counted as verified successes, OPEX/net-profit/ROI stay UNKNOWN. Focused 34/34 + adjacent 84 PASS post-integration; deterministic example (7 attempts, 4 verified, 3 partial/failed); retained evidence hash-unchanged. | E34 |
| D4 candidate-5 signing + single native run | **Consumed exactly once (native, verified):** under the explicit operator authorization covering signing plus one attempt — signing by the approved checklist (Option 1, seed never displayed, signature verified under the pinned anchor before writing), record `55486971…dec03`; all seven v3 ops dispatched with positive tested quotes equal to native costs within the £2,000 per-op ceiling (£785 + £1,398 + £1,151 + £71 + £307 + £292 + £390 = £4,394) and each independently read back, including `confirm-06` under the E33 640-byte bound (513-byte depot response retained); funds £496,543 → £492,149; route read `ROUTE_VERIFIED` 23/23; authoritative `after.sav` `a81ac836…ef261`; receipt `PHASE_COMPLETE`; cleanup certified; manifest 90/90; replay `RECEIPT_VERIFIED`. The one-shot claim is consumed. | E35 |

## Suite counts are dated, not additive

Recorded counts belong to their own records and dates ("prior extension suite counts and
VM results are historical, not rerun claims" — REPRODUCE). Do not sum, do not re-cite as
fresh runs, and never present a controlled suite result as native verification.

## Controlled tooling gaps (honest)

- Typecheck repeatedly recorded unavailable offline (mypy not installed; `ty` configured,
  not installed) — recorded in E9/E10/E11/E15 and the AI_HANDOFF validation notes.
- Full-tree test/lint/type health remains UNKNOWN beyond recorded checks.
- Baseline authority-pin failures are known and preserved ([[03-Engineering/Testing Strategy]]).

## Controlled → native promotion rule

Only a consumed one-shot attempt with retained receipts can advance a status. The
promotion path is: preparation record → reviewed candidate (`PENDING_AUTHORIZATION`) →
preflight → operator authorization → one launch → readback/receipt → close-out record
(reference: E12→E13→E14/E15→E16 and E18→E19). All current prepared items:
[[02-Milestones/Pending Milestones]].
