# D4 Native Road & Station Construction — fresh candidate-3 staging

Status: **D4 STAGED — fresh candidate `D4-CORRIDOR-3` at
`artifacts/experiments/d4-corridor-native-candidate-3/`, `PENDING_AUTHORIZATION`;
`PRELAUNCH PASS` + read-only `PREFLIGHT PASS`; no claim, nothing launched.**

## 1. Why a fresh candidate was required

Candidate `D4-CORRIDOR-2` (E24) passed preflight on 2026-10-22, but its frozen
source closure no longer matches the live reviewed tree. A read-only
re-run on 2026-10-25 failed `verify_freeze` because exactly two frozen files
were changed by the later, accepted ADR-012/ADR-013 work:

- `app/planning/p08_v2_snapshot.py`
- `app/simulation/openttd/v2_semantic_reconciliation.py`

Candidate-2 was never consumed and was not edited, regenerated or reused. A
launchable candidate must freeze the current reviewed bytes, so a fresh
never-consumed identity and directory were staged under the existing ADR-011
Option C decision. The identity constant moved from `D4-CORRIDOR-2` to
`D4-CORRIDOR-3` (one line) before staging, per this session's operator
direction.

## 2. Staged candidate

| Fact | Value |
| --- | --- |
| Directory | `artifacts/experiments/d4-corridor-native-candidate-3/` (created `exist_ok=False`) |
| Attempt | `D4-CORRIDOR-3`, milestone `D4-CONSTRUCTION`, kind `corridor` |
| Prelaunch seal | `8cc8c1f70c1928ccfb6e10b169d442ec1d62f1826790f617b86c78a62dda7d24` |
| Plan digest | `2a30e95048e89ffa1420e0ae392b79f4d051f447d7a15a3edb896b4bbdcabb3a` (v2, 8 ops) |
| Authorization payload | sha-256 `e1163d09b3344d020676443eec7a39b0299a2faab6d591dec7a7d0644d01068d` (2,393 canonical bytes) |
| Source world | D3 `after.sav` `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e` |
| Frozen closure | 3,448 entries (includes the new authority-supersession module) |
| Budgets | 1 launch, 1 connection, 8 road ops, request budget 31 (25 planned), 0 retries/reconnects, per-op ceiling £2,000 |
| Authorization | `PENDING — requires ONE fresh operator authorization` |

The eight-operation schedule, route, per-op ceiling and exchange budget are
unchanged from E22/E24.

## 3. Commands and results

| Check | Result |
| --- | --- |
| `.venv/bin/python -m pytest -q tests/test_corridor_construction.py tests/test_corridor_construction_native.py` | **55/55 PASS**, 0 skipped |
| `... corridor_construction_native prepare artifacts/experiments/d4-corridor-native-candidate-3` | exit 0, **PRELAUNCH PASS** |
| `... corridor_construction_native preflight artifacts/experiments/d4-corridor-native-candidate-3` | exit 0, **PREFLIGHT PASS** |
| Consumed `D4-CORRIDOR-1` manifest | 28/28 OK |
| Candidate-2 `PRELAUNCH.json` sha-256 | unchanged `de0e16f7…04f00` |
| D3 `after.sav` | unchanged `fbebef54…d59e` |

## 4. What remains

ONE fresh explicit operator authorization for `D4-CORRIDOR-3`, then the
one-shot `run`. Every op is still quoted natively at its own admission inside
the unchanged £2,000 per-operation ceiling. No native quote exists for this
candidate yet.

## 5. Honesty and limits

- Staging is offline: no OpenTTD process, no AdminPort connection, no tile
  mutation, no claim/authorization file, no Git operation.
- Milestone D4 remains **INCOMPLETE (native)**.
- Historical £2,549/£785 quotes belong to the consumed `D4-CORRIDOR-1` attempt
  only.
