---
title: "Task Board"
type: planning
status: current
updated: 2026-10-26
tags:
  - openttd
  - planning
  - tasks
---

# Task Board

Derived from [[99-Source-Documents/TASKS]] (2026-10-17 list + 2026-10-18/22/25/26 updates).
This board **grants no runtime authority**; statuses reflect what the source documents
record, nothing more. Priorities below are the source documents' own ordering
("current product priority is the stable demo plus bounded Random World") — no invented
deadlines.

## Completed (per source records — offline work)

- [x] 1. Offline transfer verification — branch/HEAD, dirty paths, source hashes vs `docs/handoff/2026-10-17/`; ignored artifacts exist; hashes verified; **Done:** reviewed source/evidence inventory, no secret transfer, no historical edits. (2026-10-17 era; E6)
- [x] 2. Offline fresh random readiness — 512-tile profile, legacy 256 compatibility, staged bridge, budgets, qualified-month window, 47-tile filter, P05 timeout, diagnostics/replay/cleanup reviewed; focused tests run; frozen-input identity + independent preflight with staleness/runtime blockers explicit; zero launches. (E5, E7)
- [x] 4. Offline P07 continuation after accepted delivery — replay to fresh sibling output; verified totals/charts/history/attributions; **Done:** reproducible reports, native vs derived distinguished, no invented OPEX/profit/ROI.
- [x] 5. Later product work — offline bounded extensions so far: terrain-aware reachability oracle (E9); bounded terrain-modification planning (E10); native classification + generalized feasibility + three-tier diagnosis (E11); V2 preparation (E12); execution path + capture runner (E13); native V2 capture consumed → fusion REJECTED (E14/E15/E16).
- [x] 6. Separate engineering backlog items staged offline — fourth-vehicle controlled preparation + telemetry groundwork; canonical inputs still missing (blocked flag below). (README §capacity; `docs/capacity-experiment.md`)
- [x] 7. Tile Classification V2 executable path — execution blockers implemented offline and validated; authorization consumed 2026-10-18 (first launch FAILED → diagnosed/repaired offline → **capture completed natively**, fusion REJECTED). (E14, E15, E16)
- [x] 8. Milestone D3 complete; D4 preparation — D3 closed 2026-10-22 (E19); D4 candidate staged same day, `PRELAUNCH PASS` + `PREFLIGHT PASS` (E20).

## Consumed authorization (closed with immutable outcome)

- [x] 3. Separate authorization: one new Seed 17 native smoke — **authorization consumed 2026-10-17** under its reviewed frozen identity; outcome `NO_BOUNDED_CORRIDOR` → `NO_FEASIBLE_SERVICES`; P05 NOT_RUN; diagnostics retained (E8). Task is closed; the *failed outcome* is retained, not "undone". Also completed offline follow-ups: readiness record (E8-linked), bounded routing record (E9), terrain-modification record (E10), classification record (E11), and preparation records (E12, E13).
- [x] **D4 native execution — one shot on candidate `D4-CORRIDOR-1`** — authorization
  consumed 2026-10-22; the ceremony halted `PHASE_HALTED_PREFIX_PRESERVED` at `op-01`:
  `op-00` verified (£785; funds £496,543 → £495,758), `op-01` refused at admission
  (£2,549 > £2,000 ceiling), `op-02`–`op-05` and the route read never executed;
  `verified: false`, Milestone D4 INCOMPLETE (E21). Closed with the immutable halted
  outcome — never retried, never relabeled.

## Open / pending

- [x] **D4 restage decision** — **taken 2026-10-22, offline (E22, ADR-011):** Option C —
  keep the £2,000 per-operation ceiling unchanged and stage the 17-tile run B as two
  contiguous segments (45999→48047, 48303→50095) plus a separate interior road join
  (8 static ops, 25 planned exchanges, budget 31); implemented in the staging module +
  GameScript + tests (55 controlled PASS) with the schedule-version selector keeping
  the consumed attempt's replay re-derivable. Deliberately **no** aggregate phase
  budget (worst-case theoretical exposure 8 × £2,000 = £16,000 is an exposure bound,
  not a budget). Record:
  `docs/handoff/2026-10-22/d4-corridor-option-c-implementation.md`.
- [x] **Option C implementation review** — **done 2026-10-22 (E23):** independent
  read-only offline review returned **`PASS WITH CONCERNS`** — 55 tests re-run fresh,
  scoped lint/compile/`git diff --check` clean, the production read-only `verify`
  replay of the consumed candidate byte-identical to E21, artifact manifests verified
  before and after. Record:
  `docs/handoff/2026-10-22/d4-corridor-option-c-implementation-review.md`.
- [x] **Fresh D4 candidate-2 staging** — **done 2026-10-22 (E24):** the fresh
  candidate **`D4-CORRIDOR-2`** staged at
  `artifacts/experiments/d4-corridor-native-candidate-2/` from the reviewed E22
  implementation after an operator-approved one-constant identity bump
  (`CORRIDOR_ATTEMPT` consumed `D4-CORRIDOR-1` → never-consumed `D4-CORRIDOR-2`,
  suites re-run 55/55 PASS afterward): `PRELAUNCH PASS` + read-only
  `PREFLIGHT PASS`, seal `de0e16f7…04f00`, plan digest `2a30e950…cabb3a` (v2,
  eight ops), 25 planned exchanges / budget 31, source world byte-bound to the
  D3 after-save `fbebef54…d59e`. Record:
  `docs/handoff/2026-10-22/d4-corridor-native-candidate-2-preparation.md`.
  Preparation is **not** authorization; no `AUTHORIZATION.json` or claim exists.
- [x] **Read-only authorization-payload verification** — **done 2026-10-22:**
  the canonical authorization payload rebuilt offline from the candidate's
  staged `PRELAUNCH.json` (documented production functions, no key, no
  signing) matched the staged digest (`e85ea64b…52ff17`, 2,393 bytes), the
  frozen closure hash-verified 3,447/3,447 (0 missing, 0 mismatches), and the
  retained D2/D3/D4-consumed manifests re-verified unchanged. Verification
  only — nothing signed, no `AUTHORIZATION.json`, no launch. Record:
  `docs/handoff/2026-10-22/d4-corridor-native-candidate-2-payload-verification.md`.
- [x] **Operator extraction documentation correction** — **done 2026-10-24
  (documentation only):** corrected the key-extraction commands in
  `docs/handoff/2026-10-17/operator-key-provisioning.md` §1 and
  `docs/handoff/2026-10-21/d2-native-clearing-candidate-3-preflight.md` §6(b)
  to the tested `od`/`tr` pipeline (no `-noout` on DER seed extraction) with
  the shell's original `pipefail` state captured and restored. Synthetic-key
  validation only; no production key was accessed, nothing was signed, and no
  candidate/evidence/authorization file was touched. Option 2 (external-tool
  signing) remains excluded. D4 stays **INCOMPLETE**.
- [x] **Fresh D4 candidate-3 staging** — **done 2026-10-25 (E27):** candidate-2 was
  proved stale by a read-only preflight (its frozen closure predates the accepted
  ADR-012/ADR-013 edits; never consumed, not edited). Fresh never-consumed
  `D4-CORRIDOR-3` is staged at
  `artifacts/experiments/d4-corridor-native-candidate-3/` (`PRELAUNCH PASS` +
  read-only `PREFLIGHT PASS`, seal `8cc8c1f7…7d24`, plan digest
  `2a30e950…cabb3a`, payload `e1163d09…068d`, focused suites 55/55 PASS).
  Record: `docs/handoff/2026-10-25/d4-corridor-native-candidate-3-preparation.md`.
- [x] **One-shot native run of `D4-CORRIDOR-3`** — **consumed 2026-10-25 (E28):**
  signed and verified, then executed exactly once. `op-00`–`op-02` built and read
  back (£496,543 → £493,209); `op-03` interior join refused at admission as
  `NOT_BUILDABLE` (cost 0), so the run halted without dispatch; `op-04`–`op-07`
  and the route read never executed. `PARTIAL_EXECUTION_EVIDENCE`,
  `verified: false`, `FAILED_CLEANUP`; no authoritative after-save/receipt.
  Record: `docs/handoff/2026-10-25/d4-corridor-native-candidate-3-outcome.md`.
- [x] **Fix `op-03` join admission and prepare a fresh D4 candidate** — **offline
  correction and staging done 2026-10-25 (E29/E31):** `op-03` was a redundant
  scheduled interior join, not an admission bug; scripted `BuildRoadFull`
  endpoints auto-connect the collinear run-B segments, while the perpendicular
  corner still needs its own join. Fresh v3 schedule = 7 ops, 22 planned
  exchanges, cap 28, £2,000 per-op. `D4-CORRIDOR-4` was staged (`PRELAUNCH PASS` +
  `PREFLIGHT PASS`, seal `88cd1ecc…fd22c3`, plan digest `b5b472ff…2283a78`,
  payload `4037c5d8…487c7f`), `PENDING_AUTHORIZATION`, no claim or launch at that
  time; it was consumed later in E32.
  Candidate-3 cleanup remediation was separately verified (E30), without
  changing its historical failure. Records:
  `docs/handoff/2026-10-25/d4-corridor-op03-root-cause.md`,
  `…-candidate-3-cleanup-remediation.md`, `…-candidate-4-preparation.md`.
- [x] **One-shot native run of `D4-CORRIDOR-4`** — **consumed 2026-10-25 (E32):**
  signed under the pinned anchor and executed exactly once. `op-00`–`op-05` built
  and read back (£4,004; £496,543 → £492,539), including the perpendicular
  corner and both stops; `op-06` depot was dispatched and the native log reports
  `BUILT`, but its 513-byte response exceeded the 512-byte application limit and
  was rejected before parsing. `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`,
  `PHASE_HALTED_PREFIX_PRESERVED`; no authoritative after-save/receipt; cleanup
  PASS (all four fields true), manifest 80/80, replay raised the same
  `MalformedMessage` at the time. No retry, re-sign or reuse. Record:
  `docs/handoff/2026-10-25/d4-corridor-native-candidate-4-outcome.md`.
- [x] **Fix the depot response-size path** — **offline fix done 2026-10-25
  (E33):** protocol 4 permits 640-byte responses, but `decode_gamescript`
  applied the version-one 512-byte limit to every protocol. Encode/decode now
  take a validated opt-in bound (default unchanged 512; absolute frame-body
  maximum 32763), and protocol 4 uses 640 in `parse_for`, the live exchange and
  retained-frame replay. The retained 517-byte depot frame parses to `BUILT`;
  exact 640 passes, 641 fails, malformed/truncated/duplicate/invalid-UTF-8
  bodies fail closed. Focused suites 129/129 PASS; `ruff check --ignore UP037`
  passed with four pre-existing `UP037` findings unchanged; compile/diff clean.
  No receipt or native verification is claimed; replay now stops at the missing
  `depot-06-response.json`. Record:
  `docs/handoff/2026-10-25/d4-corridor-response-limit-fix.md`.
- [x] **Prepare a fresh D4 candidate and obtain authorization** — **done and consumed 2026-10-26 (E35):**
  the reviewed v3 schedule was staged as `D4-CORRIDOR-5` (staging 2026-10-25; fresh-context
  independent review **PASS 20/20**; the E33 protocol rules bound in the freeze), then
  signed under the explicit 2026-10-26 operator authorization and consumed exactly once:
  1 launch / 1 X25519 connection / 22 of 28 requests; all seven v3 ops dispatched with
  positive tested quotes equal to native costs within the £2,000 per-op ceiling
  (£785 + £1,398 + £1,151 + £71 + £307 + £292 + £390 = £4,394) and each independently read
  back including `confirm-06` (513-byte depot response under the 640-byte bound); funds
  £496,543 → £492,149; `ROUTE_VERIFIED` 23/23; authoritative `after.sav` `a81ac836…ef261`;
  cleanup certified; manifest 90/90; read-only replay `RECEIPT_VERIFIED`.
  **Milestone D4 is COMPLETE (native) for exactly the reviewed v3 scope**
  ([[02-Milestones/Completed Milestones]]). Consumed identities `D4-CORRIDOR-1/3/4/5`
  are never retried; stale `D4-CORRIDOR-2` stays frozen (E21, E24, E27, E28, E32, E33, E35).
  Record: `docs/handoff/2026-10-26/d4-corridor-native-candidate-5-outcome.md`.
- [x] **Design D5 — vehicle purchase, orders, delivery on the built corridor** —
  **designed offline 2026-10-26 (implementation-ready; not committed at design time):**
  one native cargo-1 pickup→delivery cycle on the D4 corridor over the
  candidate-5 `after.sav` world; explicit site admission (witness re-check,
  native delivery-stop acceptance ≥ 1/8, funds £492,149), positive-tested-quote
  purchase ≤ £2,000, exact `OF_FULL_LOAD`/`OF_NO_LOAD` order set, loading →
  transit → unloading with GSCargoMonitor amounts equal to the observed load,
  per-exchange funds reconciliation, receipt-bound before/after saves and
  replay `RECEIPT_VERIFIED`; budget/request/cleanup/idempotency constraints and
  dependency-ordered tasks T1–T12 recorded with review (T7) and
  explicit-operator-authorization (T9) gates. Design:
  `docs/d5-corridor-freight-design.md`. **Statuses: offline implementation
  T1–T6 complete (uncommitted, 2026-10-26) — protocol-5 contracts, the
  fifteen-exchange package, staging/preflight/replay module and
  32 unit + 29 native-orchestration tests; see
  `docs/d5-corridor-freight-preparation.md`. T7 independent review is next.
  No candidate, claim, signature or authorization exists; no native attempt
  was made; native freight delivery remains UNKNOWN; full OPEX/net-profit/ROI
  stay UNKNOWN (out of scope).**
  → [[05-Planning/Blockers]] §8, [[05-Planning/Next Actions]],
  [[02-Milestones/Pending Milestones]].
- [ ] **Random World facts** — recorded follow-up options: same-instant re-observation of
  tiles [43951, 47286, 47288, 48042, 48309, 51378], and/or operator policy decision on the
  save-instant census; both under a new reviewed candidate + fresh authorization
  ([[05-Planning/Blockers]]). A new random native run additionally needs fresh frozen
  inputs; never retry consumed identities.
- [x] **Protected-authority pin resolution** — **resolved 2026-10-25 (E26, ADR-014):**
  explicit, fail-closed supersession of exactly the historical/current CONTEXT.md
  transition; retained manifests unchanged, base validator unchanged
  ([[04-Evidence/Evidence Preservation]]).
- [ ] **Third-party/application backlog (separately scoped, later)** — obstructed terrain,
  long corridors, >32 industries, larger maps; fourth-vehicle matched A/B native work;
  continuous dispatch; five-year experiment expansion. All gated behind reviewed contracts
  + authorizations; fourth-vehicle native readiness currently BLOCKED (no canonical
  pre-intervention save).

## Board hygiene rules

- Never check a box without a source-recorded completion (E-ID or dated record).
- Never mark a task complete because tests pass, code exists, or a candidate is prepared.
- `DONE` offline items must not imply native authority was granted or consumed. In case
  of ambiguity, write the ambiguity and link the source ([[05-Planning/Next Actions]]).
