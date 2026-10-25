---
title: "Next Actions"
type: planning
status: current
updated: 2026-10-25
tags:
  - openttd
  - planning
  - tasks
---

# Next Actions

One recommended next engineering task plus alternatives, all permission-aware.
Source order: [[99-Source-Documents/TASKS]] item 8 (2026-10-22) → [[99-Source-Documents/AI_HANDOFF]]
"Preservation and next action" (2026-10-18 addendum) → [[99-Source-Documents/REPRODUCE]].

## Recommended next task — review the offline v3 correction and prepare a fresh candidate (2026-10-25 update)

**Status update (2026-10-22, E24):** fresh-candidate preparation is **done**.
`docs/handoff/2026-10-22/d4-corridor-native-candidate-2-preparation.md` records
the staged candidate **`D4-CORRIDOR-2`** at
`artifacts/experiments/d4-corridor-native-candidate-2/`:
`PRELAUNCH PASS` + read-only `PREFLIGHT PASS`, seal `de0e16f7…04f00` (sha-256
`de0e16f73d71efbad636271217a4981b4e6350412184bdbdfa17533e3d304f00`), plan digest
`2a30e950…cabb3a` (v2, eight ops), 25 planned requests / budget 31, per-op
ceiling £2,000 unchanged, source world byte-bound to the replay-verified D3
after.sav `fbebef54…d59e`. The attempt identity is never-consumed — the module
constant was bumped (operator-approved) from the consumed `D4-CORRIDOR-1` to
`D4-CORRIDOR-2` before staging, with the focused suites re-run 55/55 PASS
afterward. The consumed candidate, the D2/D3 evidence and every retained
manifest remained unchanged.

**Status update (2026-10-25, E27):** candidate-2 is **stale and superseded**.
A read-only preflight on 2026-10-25 fails `verify_freeze` because two frozen
files changed after staging under the accepted ADR-012/ADR-013 work
(`app/planning/p08_v2_snapshot.py`,
`app/simulation/openttd/v2_semantic_reconciliation.py`). Candidate-2 was never
consumed and was **not edited**. A fresh never-consumed candidate
**`D4-CORRIDOR-3`** is staged at
`artifacts/experiments/d4-corridor-native-candidate-3/`: `PRELAUNCH PASS` +
read-only `PREFLIGHT PASS`, seal `8cc8c1f7…7d24`, plan digest
`2a30e950…cabb3a` (v2, eight ops), 25 planned requests / budget 31, per-op
ceiling £2,000, rebuildable payload `e1163d09…068d` (2,393 bytes), source world
`fbebef54…d59e`. Focused suites 55/55 PASS. Records:
`docs/handoff/2026-10-25/d4-corridor-native-candidate-3-preparation.md` and
`docs/handoff/2026-10-25/d4-corridor-native-candidate-3-outcome.md`.

**Outcome 2026-10-25 (E28):** `D4-CORRIDOR-3` was signed, verified and consumed
by exactly one authorized native run. `op-00`–`op-02` built and read back
(£496,543 → £493,209); `op-03` interior join was refused at admission as
`NOT_BUILDABLE` (cost 0), the runner halted without dispatch, and `op-04`–`op-07`
and the route read never executed. Verdict `PARTIAL_EXECUTION_EVIDENCE`,
`verified: false`, `FAILED_CLEANUP`; no authoritative after-save/receipt; replay
refuses incomplete cleanup. No retry or reuse.

**Offline correction 2026-10-25 (E29):** `op-03` was a redundant scheduled
interior join, not an admission defect. Scripted `BuildRoadFull` gives both
straight road bits at both endpoints, so the collinear run-B segments already
connect at `48047↔48303` (`pairs_ok 1`); the perpendicular corner
`45743↔45999` still needs its own join. The fresh schedule is v3, 7 ops, 22
planned exchanges / budget 28; v1/v2 replay derivations are preserved. Focused
suites 55/55 PASS; ruff, compile and diff checks clean. Record:
`docs/handoff/2026-10-25/d4-corridor-op03-root-cause.md`.

**Next step:** review E29, choose and approve a fresh candidate identity, stage
from the current reviewed source, review it, and request separate explicit
operator authorization for a new one-shot run. Do not reuse `D4-CORRIDOR-3`.

**Operator-guidance correction (2026-10-24, documentation only):** the key
extraction commands that the operator would follow were corrected in
`docs/handoff/2026-10-17/operator-key-provisioning.md` §1 and
`docs/handoff/2026-10-21/d2-native-clearing-candidate-3-preflight.md` §6(b):
`od`/`tr` replace the unavailable `xxd`, `-noout` is removed from the DER seed
extraction, and the shell's original `pipefail` state is captured and restored.
The pipeline was validated with **synthetic keys only**; the production key was
not accessed or tested, and nothing was signed. That earlier requirement was
superseded by execution: `D4-CORRIDOR-3` was signed and consumed exactly once
(E28) and must not be reused; candidate-2 remains stale. The current
requirement is a fresh candidate after the offline v3 correction, under new
explicit authorization. This correction creates no authorization and consumes
no claim.

**Review package prepared (2026-10-22, read-only):** the canonical
authorization payload was rebuilt offline from the candidate's own staged
`PRELAUNCH.json` with `operator_authorization.authorization_payload(metadata,
seal)` and cross-checked byte-equal against
`staged_authorization_payload_digest()` — canonical digest
`e85ea64ba8ec15c383e913a72df7d1e4bd13569496a83d297bf7ee2c1952ff17`
(2,393 canonical bytes; payload binds attempt, milestone, workspace, binary,
seal `de0e16f73d71efbad636271217a4981b4e6350412184bdbdfa17533e3d304f00`
(closing `…04f00`), target tile, company, clearing command, stale rule,
`max_cost` £2,000, source world `fbebef54…d59e`, the full budget table, the
exact execution command, the eight-op `operation_schedule` and its
`plan_digest` `2a30e950…cabb3a`; `schedule_version` is deliberately not a
signed key). The PRELAUNCH seal re-verified unchanged (`sha256sum` equals the
staged `PRELAUNCH.sha256`) and all 3,447 frozen closure entries hash-verified
OK against the working tree. **Shorthand corrected (2026-10-22):** several
status notes (incl. the E24 entries) had shortened the seal as
`de0e16f7…2bf00`, while the verified bytes end `…04f00`
(full `…3d304f00`, equal to the handoff §1 digest and the staged
`PRELAUNCH.sha256`); the binding was never affected because signature
verification recomputes the seal from file bytes, and the shorthand tails
were corrected in a later explicit documentation session — exactly the
correction path this note previously called for.
Binding facts: the consumed `D4-CORRIDOR-1`'s expected payload differs in
seven signed fields (`attempt`, `prelaunch_sha256`, `workspace`, `plan_digest`,
`operation_schedule`, `budgets`, `execution_command`) and its claim is
consumed, so a candidate-2 record can never authorize candidate-1 and vice
versa. Authorization stays **unsigned/pending** (`AUTHORIZATION.json` and
`CLAIM.json` do not exist for candidate-2); no launch, no connection, no
claim creation or consumption was performed for this review.

**Durable record (2026-10-22):** this review package was not stored as a
durable repository file when prepared, and its exact wording is history; the
durable, complete record of this verification is
`docs/handoff/2026-10-22/d4-corridor-native-candidate-2-payload-verification.md`
(exact seal, payload digest, plan digest, the 2,393 canonical bytes, the
3,447-entry frozen closure, the method, the schedule-version binding
limitation, the discrepancy findings and the corrections applied).
**Preservation correction (2026-10-22):** this note itself was written during
that review session (single write at 19:39:21), so any "all pre-existing
files preserved byte-for-byte" claim holds only when scoped as "except these
review-session documentation writes"; the exact bytes of this note
immediately before that write are UNKNOWN and no prior state is asserted.

**Why not before:** fresh staging required a never-consumed attempt identity
(can never be `D4-CORRIDOR-1`), a fresh directory (`mkdir exist_ok=False`), and
the completed E23 review — all satisfied on 2026-10-22.

**Standing rules unchanged:** the consumed `D4-CORRIDOR-1` candidate and its
frozen closure are never edited or reused; unauthorized retries are forbidden.

**Earlier steps (all complete):** the Option C implementation (E22) and its
independent review (E23, `PASS WITH CONCERNS`), then fresh staging per E24.

⚠ This page does not constitute authorization. Nothing here creates a claim.

## Secondary candidates (other offline work)

| Option | Nature | Why after D4 |
|---|---|---|
| Random-World classification follow-up (offline/decision) | Offline analysis/decision work only: formalize the same-instant re-observation candidate for the six temporal tiles, or prepare the operator-policy decision record | The AI_HANDOFF addendum (2026-10-18) names this as the open offline continuation; it needs its own reviewed record; uncommitted reconciliation results ([[05-Planning/Blockers]]) feed it. **Update 2026-10-24:** the operator policy decision record is prepared — `docs/random-world-six-tile-policy-decision.md` (Option A: new reviewed same-instant re-observation candidate under a fresh authorization; Option B: explicit operator policy declaring the save-instant census authoritative). The decision itself is the operator's; P08 stays `INCOMPLETE_TILE_CLASSIFICATION` until it lands. **Update 2026-10-24/25 — decision exercised (delegated); ADR-012, Option B:** the save-instant census is authoritative for the six tiles' tree-lifecycle deltas, planning evidence only; `apply_census_authority` is implemented fail-closed (14/14 tests PASS), P08 remains `INCOMPLETE_TILE_CLASSIFICATION` (19 retained-UNKNOWN tiles remain), Option A retained as optional future delta-confirmation only. **Update 2026-10-25 — rebinding pass:** `rebind_p08_policy` re-derives and byte-compares the policy report against sealed inputs, accepts only the exact six-tile scope (stale/edited/out-of-scope evidence refused; 24/24 tests PASS), derived evidence `p08-policy-rebinding-report.json`; computed binding still **not allowed** because the 19 `UNKNOWN_OCCUPANCY` tiles were unresolved. **Update 2026-10-25 — ADR-013 accepted (operator-authorized):** native `IsBuildable` semantics for exactly the 19 tiles → derived `TERRAIN_MODIFICATION`; base ledger unchanged. Separate combined rebinding verifies both policy reports and computes `p08_binding.allowed: true` for **P08 planning classification only**, with derived counts 339/63/29/19/0 and `p08_complete: false`; fusion gate remains **CLOSED**. No native evidence/launch/signing/candidate consumption. |
| Offline D4-adjacent engineering | e.g. preparing D5 (vehicle purchase/orders) contracts offline, tests only | Native execution of D5 is not designed yet; controlled prep cannot consume anything |
| Documentation hygiene | keep the vault in sync (this task) | always permissible; zero native authority |

## If you cannot decide (ambiguity protocol)

1. Re-read [[99-Source-Documents/TASKS]] in full — item ordering and dated "Done:"
   notes are the authority.
2. Check working-tree state (`git status --short`, candidate dirs' `CLAIM.json`
   presence) — a staged claim may already have been consumed by an operator action
   outside any chat (see E17/E19 "the record-writing session did NOT initiate the
   launch").
3. If both D4 execution *and* Random World facts are authorized simultaneously, prefer
   the task whose prerequisites (frozen inputs, preflight gates) are actually ready —
   otherwise write the missing prerequisite as a blocker and stop.
4. Never resolve ambiguity by "just trying it" against OpenTTD.

## Standing prohibitions for every next action

- No OpenTTD launch, AdminPort connection, authorization consumption, or consumed-attempt
  retry without the relevant explicit operator authorization.
- No Git staging/commit/push without explicit authorization.
- No deletion, rewrite, or regeneration of historical evidence.
- Cannot-solve + cannot-verify tool states are recorded honestly, never fudged
  ([[AI_START_HERE]] §7).
