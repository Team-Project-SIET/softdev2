# D4 corridor — Option C offline implementation record (split-run-B restage)

Status: **OFFLINE/CONTROLLED implementation of the staging-time restage decision — no
launch, no native evidence, Milestone D4 still INCOMPLETE (native).** The approved
Option C decision (recorded below and in ADR-011 of the knowledge vault's decision
log) is now compiled code: the corridor schedule is staged as **two contiguous
run-B segments plus a separate interior road join** (8 static ops), the GameScript
package mirrors the same ops, and every affected controlled test is updated. In
accordance with the D4 status rule, this work does **not** complete the milestone:
nothing native has been re-quoted, executed, verified or authorized.

This record is **documentation + controlled-source work only**. Its session launched
no OpenTTD process, connected to no AdminPort, issued no native mutation, created or
consumed no authorization/claim record, staged no candidate, and performed no Git
stage/commit/push/reset/clean/stash. The consumed candidate
`artifacts/experiments/d4-corridor-native-candidate-1/` was only ever read
(its replay tests re-derive its binding; its bytes are untouched).

Predecessor records:
[d4-corridor-native-candidate-1-outcome.md](d4-corridor-native-candidate-1-outcome.md)
(E21 close-out; §9 lists the restage options) and
[d4-corridor-native-candidate-1-preparation.md](d4-corridor-native-candidate-1-preparation.md)
(E20 historical staging, 19 exchanges, now superseded for fresh staging by E22).

## 1. The decision (Option C, staging-time, offline)

The consumed attempt ended `PHASE_HALTED_PREFIX_PRESERVED`: `op-00` (run A,
5 tiles, £785) was executed and verified; `op-01` (the 17-tile run
45999→50095) was refused at admission because its native quote exceeded the
authorized £2,000 per-operation ceiling (E21). Of the options recorded in the
close-out (§9), Option C was chosen: **keep the £2,000 per-operation ceiling
unchanged and rescope the staged schedule at staging time** so every operation is
individually re-quoted natively inside that ceiling:

| Op (new schedule) | Kind | Pins |
| --- | --- | --- |
| 0 | `full` | run A 45747→45743 (5 tiles) — unchanged |
| 1 | `full` | run-B segment 1 45999→48047 (9 tiles) |
| 2 | `full` | run-B segment 2 48303→50095 (8 tiles) |
| 3 | `road` | interior join 48047↔48303 |
| 4 | `road` | corner join 45743↔45999 (unchanged historical corner) |
| 5 | `station` | pickup 45748 front 45747 — unchanged |
| 6 | `station` | delivery 50351 front 50095 — unchanged |
| 7 | `depot` | 45487 front 45743 orientation `south` — unchanged |

Both run-B segments run before the interior join. Road pieces built by separate
commands do not auto-merge, so each join op carries its own admission (fresh
observation + fresh native quote) and its own readback; the geometry stays **two
straight runs joined by one corner** — the joins are build operations, not a
second geometric corner. `corridor_facts()`, `route_policy()` (the 24-tile/23-pair
witness read) and `MAX_CORRIDOR_COST = 2000` are unchanged.

**Cost semantics (recorded explicitly):**

- There is deliberately **no aggregate phase-spending budget** in the contract —
  the per-operation ceiling remains the only cost contract. If every one of the
  8 native-op admissions quoted the ceiling, the theoretical worst-case exposure
  would be **8 × £2,000 = £16,000**. That number is an *exposure bound*, not a
  budget, not an authorization, and not a predicted cost.
- **No native quotes exist for the new schedule.** The historical quotes (£2,549
  refused; £785 executed) belong to the consumed attempt and are controlled
  references only — they are not facts of this plan, and no fresh op can be
  costed before its own admission-time native quote inside a future authorized
  run.

## 2. Implementation changes (branch `devmodule2`, uncommitted)

| File | Change |
| --- | --- |
| `app/simulation/openttd/proof/corridor_construction_native.py` | `ROAD_OP_COUNT = 8`; `SCHEDULE_VERSION = 2`; `corridor_schedule()` rewritten as the deterministic 8-op derivation (split at `ceil(17/2)=9`, validated: segments ≥2 tiles, reassembly == compiled run B, interior join adjacency ±1/±`CORRIDOR_WIDTH`, corner == compiled corner, indexes 0–7, spans within `MAX_FULL_SPAN`, tile bounds); new `corridor_schedule_v1()` compiles the historical 6-op derivation byte-identically in content from the same pinned facts (never hand-retold); new `staged_plan_schedule(plan)` selects v2 for fresh records and v1 when `schedule_version` is absent, refusing unknown versions fail-closed; `plan_policy()` pins `schedule_version: 2` (joining the canonical authorization payload additively); `budgets()` derives `road_ops` from the schedule (8) and its docstring records the no-aggregate-budget rule; readback text and `prepare_candidate` guard updated; `verify_corridor_attempt` re-derives via the version selector. |
| `app/simulation/openttd/d4_corridor_package/main.nut` | `StageIndex()` baked keys now the 8 staged ops in execution order; loop bound 8; the pins comment documents the split-run-B derivation; planned-exchange comment updated (8 × 3 + 1 = 25, +6 slack); `max_requests = 31`. Wire contract semantics unchanged (per-op generic; the stub/VM request bounds already accommodate 9-tile segments). |
| `app/simulation/openttd/corridor_construction.py` | **unchanged** — wire contract v4 is per-op generic. |
| `tests/test_corridor_construction.py` | rewired to the 8-op schedule (all suites offline/controlled in the Squirrel VM); new `test_dispatcher_budget_refuses_the_request_after_the_cap` (25 planned → 31 cap, then refusal without reply) and `test_gamescript_stage_keys_track_the_staged_schedule` (static offline read of the shipped `main.nut` StageIndex keys == the Python derivation). 21 → **23** tests. |
| `tests/test_corridor_construction_native.py` | schedule/eight-op test rewritten with exact compiled pins; new `test_run_b_segments_reassemble_the_compiled_run` (segments = compiled halves, shared edge = interior join, straight-axis proof, witness intact); new `test_schedule_version_binding_selects_the_plan_derivation` (v2 fresh / v1 consumed replay / unknown refused / digests differ); new `test_site_ops_feed_the_entry_scoped_pins_with_their_intent` (site-op `_pins()` branch coverage); budget/inventory/wire counts 19 → 25 and 25 → 31. 29 → **32** tests. |

**Replay compatibility (why the version selector exists):** the consumed
`D4-CORRIDOR-1` staged the 17-tile run as ONE op (historical derivation, plan
digest `3bf3eddf…d8a912`). Its retained record binds that digest, so the replay
verifier must keep re-deriving exactly that schedule for it. Deriving the
historical 6-op schedule from the same `corridor_facts()` (not from hand-retold
numbers) keeps that binding re-derivable while fresh staging moves to the v2
derivation (plan digest of the 8-op schedule). Both suites' consumed-artifact
tests re-verified offline: `verify_corridor_attempt` still returns
`PHASE_HALTED_EVIDENCE_PRESERVED` / `completed ['full']` / `failed op-01` /
`pending op-02…op-05` read-only, unchanged.

## 3. Validation performed (offline, controlled)

| Check | Result |
| --- | --- |
| `.venv/bin/pytest tests/test_corridor_construction.py tests/test_corridor_construction_native.py` | **55 passed, 0 failed, 0 skipped** (wire suite 23, native suite 32; includes the consumed-artifact replay tests against `D4-CORRIDOR-1` — not skipped). The in-process Squirrel extension runs the VM suites without pytest's summary dots; only the summary line is shown. |
| `python -m compileall` (module + both test files) | clean |
| `ruff check` (changed module + both test files) | clean |
| `git diff --check` | clean |
| Offline derivation probe | `corridor_schedule()` = 8 ops exactly as decided; `corridor_schedule_v1()` = the historical 6 ops; version selector both ways; unknown version refused (`ValueError`); 25 scheduled request ids; all 25 planned requests ≤ 512 B (worst remains `route-00` at 304 B — the Data Flow note is unchanged); `MAX_CORRIDOR_COST = 2000`; `budgets` `requests 31` / `road_ops 8`. |
| Vault source-doc copies | `99-Source-Documents/EVIDENCE_INDEX.md` + `TASKS.md` refreshed byte-for-byte from the updated roots (sha256-verified equal). Other root docs (CONTEXT.md, README.md, AI_HANDOFF.md, REPRODUCE.md) untouched. |
| Neighboring suites (`p08` road/terrain) | not run — only the D4 corridor module and its package were changed; no `terrain_*`/`p08_*` module or its shared boundary is touched by this diff, so their results are not affected (recorded honestly as not run, not skipped-for-reason-free). |
| Typecheck (`mypy`/`ty`/`pyright`) | unavailable offline (recorded environment gap, unchanged). |

## 4. What this changes and what it does not

- **Offline/controlled only.** These are implementation + test bytes and dated
  records. No controlled test validates OpenTTD runtime behavior; controlled tests
  can never upgrade a project status.
- **No native evidence.** Nothing was quoted, built or verified natively for the
  8-op schedule. D4 remains **INCOMPLETE (native)**.
- **Old quotes are not new facts.** The £2,549/E21 refusal and £785/prefix numbers
  are history of the consumed attempt. Whether each new op is buildable inside
  £2,000 is decided only by its own future admission-time native quote.
- **Next engineering step (as recorded):** an independent offline review of this
  implementation; then, only after that review, fresh candidate staging and ONE
  fresh explicit operator authorization. Nothing here is that authorization, and
  no candidate is staged yet.
