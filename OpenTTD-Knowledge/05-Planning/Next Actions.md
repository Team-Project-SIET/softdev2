---
title: "Next Actions"
type: planning
status: current
updated: 2026-10-22
tags:
  - openttd
  - planning
  - tasks
---

# Next Actions

One recommended next engineering task plus alternatives, all permission-aware.
Source order: [[99-Source-Documents/TASKS]] item 8 (2026-10-22) → [[99-Source-Documents/AI_HANDOFF]]
"Preservation and next action" (2026-10-18 addendum) → [[99-Source-Documents/REPRODUCE]].

## Recommended next task — D4 restage decision (offline, no launch)

**What:** candidate `D4-CORRIDOR-1` was consumed by its one operator-authorized launch
2026-10-22 and the ceremony halted at `op-01` (`PHASE_HALTED_PREFIX_PRESERVED`,
`verified: false`, D4 INCOMPLETE — E21). No D4 candidate is staged now; the next D4 step
is an offline decision, not a launch: pick the op-01 path — raise the £2,000
per-operation ceiling (re-signed authorization payload, staging-time) or rescope/split
the 17-tile run — then prepare a FRESH reviewed candidate (staging → prelaunch →
read-only preflight) under the existing one-shot rules. Any future launch needs ONE
fresh explicit operator authorization; none exists. The consumed candidate's frozen
closure must never be edited or reused.

**Why this first:** it is the recorded open blocker for extending the verified post-D3
world (`fbebef54…d59e`) toward truck stops and a depot; `op-00`'s verified prefix
(£785, funds £496,543 → £495,758) is retained evidence of the only executed op.

**Steps (offline only):**

1. Read [[99-Source-Documents/EVIDENCE_INDEX]] E21 and the close-out record §9
   (`docs/handoff/2026-10-22/d4-corridor-native-candidate-1-outcome.md`).
2. Record the ceiling/scope decision as a staging-time decision (no live override).
3. Only after that decision: prepare a fresh candidate from current reviewed source;
   then request ONE fresh explicit operator authorization for that candidate.
4. Do not touch the consumed `D4-CORRIDOR-1` evidence; never retry a consumed attempt.

⚠ This page does not constitute authorization. Nothing here creates a claim.

## Secondary candidates (while the D4 restage decision is pending)

| Option | Nature | Why after D4 |
|---|---|---|
| Random-World classification follow-up (offline/decision) | Offline analysis/decision work only: formalize the same-instant re-observation candidate for the six temporal tiles, or prepare the operator-policy decision record | The AI_HANDOFF addendum (2026-10-18) names this as the open offline continuation; it needs its own reviewed record; uncommitted reconciliation results ([[05-Planning/Blockers]]) feed it |
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
