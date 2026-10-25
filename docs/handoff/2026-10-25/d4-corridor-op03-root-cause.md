# D4 corridor `op-03` root cause and offline correction

Date: 2026-10-25
Scope: offline diagnosis and code correction only. No candidate was staged,
launched, retried or reused. `D4-CORRIDOR-3` remains consumed and
`D4` remains INCOMPLETE (native).

## Root cause

`op-03` was a redundant scheduled operation, not an admission bug.

OpenTTD's scripted `GSRoad.BuildRoadFull(tile, end_tile)` builds both straight
road bits at both span endpoints (`script_road.cpp` / `road_cmd.cpp`,
`is_ai` path). The two collinear run-B segments therefore auto-connect at
`48047 <-> 48303`.

The retained native observation proves that state: `covered 2`,
`road0/road1 true`, `pair_total 1`, `pairs_ok 1`. The package's road-op
eligibility correctly requires `pairs_ok == 0`; an already-connected pair is
not buildable. Admission returned `NOT_BUILDABLE` with cost 0, and the runner
correctly refused to dispatch without a positive tested READY quote.

The perpendicular corner `45743 <-> 45999` is different: the horizontal run-A
endpoint and vertical run-B endpoint do not carry facing road bits, so that
pair is not auto-connected and still needs its own `BuildRoad` join.

## Change

- Schedule derivation is now v3: 7 road ops, no interior join.
  `run A`, `run B` segment A, `run B` segment B, corner join, pickup stop,
  delivery stop, depot.
- v2 (8 ops, including the redundant interior join) and v1 (6 ops) are retained
  read-only for replay of consumed candidates.
- `SCHEDULE_VERSION = 3`, `ROAD_OP_COUNT = 7`, 22 planned exchanges, request
  budget/cap 28.
- `d4_corridor_package/main.nut` `StageIndex` now has 7 stages; the corner join
  is index 3 and site ops are 4-6.
- The offline stub models endpoint straight bits: collinear full runs
  auto-connect, perpendicular pairs do not.
- Regression coverage proves the interior pair is linked and ineligible for a
  road op, while the corner still admits, builds and reads back connected.

No consumed candidate bytes, saves, authorization records, claims or manifests
were modified. No native run or replacement candidate was created.

## Verification

- `pytest -q tests/test_corridor_construction_native.py tests/test_corridor_construction.py`
  55 passed (32 native contract + 23 wire/stub).
- `ruff check` on the changed proof and tests: clean.
- `python -m py_compile` on the changed Python files: clean.
- `git diff --check`: clean.

## Focused review result

The v3 derivation differs from v2 by exactly one entry: the interior
`road 48047..48303` op. All other entries and their order are unchanged. The
perpendicular corner `road 45743..45999` remains at v3 index 3.

Replay digests re-derived from the current source without reading candidate
artifacts:

- v1: `3bf3eddffa807cca2bde279425332d5079a025dec3b1dabe7114164822d8a912`
  (matches the retained consumed candidate-1 digest `3bf3eddf…d8a912`).
- v2: `2a30e95048e89ffa1420e0ae392b79f4d051f447d7a15a3edb896b4bbdcabb3a`
  (matches the retained consumed candidate-3 digest `2a30e950…cabb3a`).
- v3: `b5b472ff5ae15d74ad618436eb36603dd07fbaf091c14610bd7f6e8862283a78`.

Positive-tested-quote admission is unchanged: every inspect still latches a
positive native quote, and a zero/rejected/drifted quote cannot dispatch a
command. The per-op ceiling remains `MAX_CORRIDOR_COST = 2000`; the fresh
inventory is 22 planned exchanges and the request budget/cap is 28.

## Fresh-candidate prerequisites

1. Operator explicitly approves a fresh candidate identity; `D4-CORRIDOR-3`
   must not be reused and no substitute identity is chosen implicitly.
2. Review and accept this offline v3 correction and its focused validation.
3. Stage from the current reviewed source with a fresh seal, payload and
   authorization payload; never reuse candidate-3 evidence.
4. Run the prelaunch/preflight gates.
5. Obtain separate explicit operator authorization for exactly one new native
   attempt.

Do not stage before step 1. This review creates no authorization, claim or
native evidence.

## Residual credential remediation

`D4-CORRIDOR-3` cleanup remains `FAILED_CLEANUP`, so the isolated workspace was
not disposed and its operational `secrets.cfg` remains. Do not inspect, print,
copy or delete it as part of this task. The operator must complete the
documented credential-removal/workspace-disposal path in
`docs/external-openttd-runtime.md` (and the cleanup section of
`docs/handoff/2026-10-25/d4-corridor-native-candidate-3-outcome.md`), or rotate
the credential under the documented procedure, before treating the workspace as
clean. The secret value is not reproduced here.
