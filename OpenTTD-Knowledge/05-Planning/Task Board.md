---
title: "Task Board"
type: planning
status: current
updated: 2026-10-24
tags:
  - openttd
  - planning
  - tasks
---

# Task Board

Derived from [[99-Source-Documents/TASKS]] (2026-10-17 list + 2026-10-18/22 updates).
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
- [ ] **Fix `op-03` join admission and prepare a fresh D4 candidate** — open:
  diagnose why the interior join `48047↔48303` returned `NOT_BUILDABLE` with
  `road0/road1 true` and `pairs_ok 1`; correct the plan/admission contract, then
  stage a fresh candidate from current reviewed source, review it, and request
  separate explicit operator authorization. D4 remains INCOMPLETE (native).
  The consumed `D4-CORRIDOR-1`, stale `D4-CORRIDOR-2` and consumed
  `D4-CORRIDOR-3` are never retried or reused (E21, E27, E28).
  → [[05-Planning/Blockers]] §8, [[05-Planning/Next Actions]].
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
