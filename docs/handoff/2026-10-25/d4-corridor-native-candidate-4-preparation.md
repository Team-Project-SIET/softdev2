# D4 Native Road & Station Construction — fresh candidate-4 staging

Status: **D4 STAGED — fresh candidate `D4-CORRIDOR-4` at
`artifacts/experiments/d4-corridor-native-candidate-4/`, `PENDING_AUTHORIZATION`;
`PRELAUNCH PASS` + read-only `PREFLIGHT PASS`; no claim, no authorization file,
nothing launched.**

Date: 2026-10-25. Scope: offline staging and read-only preflight after the
verified candidate-3 credential/workspace remediation (E30). This record creates
no authorization, claim, native quote or native evidence.

## 1. Identity decision

Candidate history:

| Identity | State | Disposition |
| --- | --- | --- |
| `D4-CORRIDOR-1` | consumed once (E21) | never retry or reuse |
| `D4-CORRIDOR-2` | never consumed; **stale** (E24/E27) | frozen closure predates ADR-012/ADR-013; not launchable; never edit or reuse |
| `D4-CORRIDOR-3` | consumed once (E28) | never retry or reuse; its cleanup remediation is E30 |
| `D4-CORRIDOR-4` | **staged by this record** | fresh, never consumed, `PENDING_AUTHORIZATION` |

No repository reference to `D4-CORRIDOR-4` existed before staging, and no
candidate-4 directory existed. The single identity constant
`CORRIDOR_ATTEMPT` was advanced from `D4-CORRIDOR-3` to `D4-CORRIDOR-4` before
staging. No other source, test or package byte changed for this staging.

## 2. Active schedule and invariants

The reviewed schedule is **v3**, not the consumed v1/v2 derivations.

| Invariant | Verified value |
| --- | --- |
| Schedule version | `3` |
| Road operations | **7** (`ROAD_OP_COUNT = 7`) |
| Planned exchanges | **22** (7 × 3 + 1 route read) |
| Request cap / staged budget | **28** (`PLANNED_CORRIDOR_REQUESTS = 22`, `+6` slack; nut `max_requests = 28`) |
| Per-operation cost ceiling | **£2,000** (`MAX_CORRIDOR_COST = 2000`) |
| Redundant interior join `48047↔48303` | **absent** |
| Perpendicular corner join `45743↔45999` | **present** (v3 op-03, `BuildRoad`) |
| Route witness | 24 tiles, 23 adjacent pairs |

Staged operations:

| Op | Kind | Pins |
| --- | --- | --- |
| `op-00` | `full` | `45747→45743`, 5 tiles |
| `op-01` | `full` | `45999→48047`, 9 tiles |
| `op-02` | `full` | `48303→50095`, 8 tiles |
| `op-03` | `road` | corner `45743↔45999`, 2 tiles |
| `op-04` | `station` | pickup tile `45748`, front `45747` |
| `op-05` | `station` | delivery tile `50351`, front `50095` |
| `op-06` | `depot` | tile `45487`, front `45743`, orientation `south` |

Plan digest:
`b5b472ff5ae15d74ad618436eb36603dd07fbaf091c14610bd7f6e8862283a78`
(matches the E29 v3 derivation exactly).

The interior join is absent because scripted `BuildRoadFull` builds both
straight road bits at both span endpoints, so the collinear run-B segments
`45999→48047` and `48303→50095` already connect at `48047↔48303`. The
perpendicular corner does not auto-connect and remains its own scheduled
`BuildRoad` operation.

## 3. Staged candidate

| Fact | Value |
| --- | --- |
| Directory | `artifacts/experiments/d4-corridor-native-candidate-4/` (created `exist_ok=False`) |
| Attempt | `D4-CORRIDOR-4`, milestone `D4-CONSTRUCTION`, kind `corridor` |
| Prelaunch schema | `d4-corridor-native-prelaunch-v1` |
| PRELAUNCH seal | `88cd1ecc7b7b76d3f305deccdb820fa64782a6896e342263b4bb86b281fd22c3` |
| Plan digest | `b5b472ff5ae15d74ad618436eb36603dd07fbaf091c14610bd7f6e8862283a78` (v3, 7 ops) |
| Authorization payload | sha-256 `4037c5d8a6c8dc3bcc4998dcc4b906f80eb48536a00ffca6947574ccfa487c7f` over 2,307 canonical bytes |
| Source world | D3 `after.sav` `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e` |
| Staged `source.sav` | byte-exact match to that D3 save |
| Frozen closure | 3,448 entries |
| Budgets | 1 launch, 1 connection, 7 road ops, 22 planned / 28 request cap, 0 retries/reconnects, per-op ceiling £2,000 |
| Authorization | `PENDING — requires ONE fresh operator authorization` |
| Claim / authorization file | absent |
| Isolated workspace | `isolated/openttd-15.3-jdkzyh6n` (mode `0700`) |

The staged candidate retains its own isolated runtime workspace, configuration,
public-key material, staged save and frozen source closure. The operational
secret is confined to the workspace and is not reproduced in this record.

## 4. Checks and results

| Check | Actual result |
| --- | --- |
| `pytest -q tests/test_corridor_construction.py tests/test_corridor_construction_native.py` | **55/55 PASS** (55 progress markers, exit 0, 0 failures) |
| `ruff check app/simulation/openttd/proof/corridor_construction_native.py` | **All checks passed** |
| `py_compile` on the changed module | exit 0 |
| `git diff --check` | clean |
| `corridor_construction_native prepare .../candidate-4` | exit 0, **PRELAUNCH PASS** |
| `corridor_construction_native preflight .../candidate-4` | exit 0, **PREFLIGHT PASS** |
| Standalone `verify` (read-only, no claim) | structured `AUTHORIZATION_UNVERIFIED` / `CLAIM_ABSENT`; no receipt claimed |
| Candidate-3 manifest after remediation | 48/48 OK (E30) |
| D3 pinned `after.sav` | unchanged `fbebef54…d59e` |

The standalone `verify` result is the expected never-consumed state: the
candidate has no claim, so no verified receipt is possible.

## 5. Source and admission review

- Budget enforcement remains the per-operation `max_cost` ceiling; there is
  deliberately no aggregate phase-spend budget.
- `admit_corridor` requires a fresh native `inspect` returning `READY`, an
  eligible verdict, a **positive tested cost within the ceiling**, and
  sufficient funds before any command may dispatch. A zero-cost or refused
  quote cannot dispatch.
- The v3 regression coverage proves the collinear interior pair is already
  linked and therefore ineligible for a road op, while the perpendicular corner
  still admits, builds and reads back connected.
- v1 and v2 derivations remain available only for read-only replay of the
  consumed records; fresh staging pins v3.
- The runner retains the three-exchange pattern per op and the pure-observation
  route read only after a complete phase.

## 6. What remains

1. Independent review of this staged candidate and its v3 invariants.
2. ONE fresh explicit operator authorization for a single native attempt, if
   the reviewer and operator accept it.
3. Signing under that separate authorization.
4. A separately authorized one-shot native run and its verification.

Signing, claim creation/consumption, OpenTTD launch, AdminPort access, save
mutation and native execution are **not authorized by this record**. Staging
does not complete D4; Milestone D4 remains **INCOMPLETE (native)**.

## 7. Files touched

- `app/simulation/openttd/proof/corridor_construction_native.py` — one identity
  constant (`D4-CORRIDOR-3` → `D4-CORRIDOR-4`)
- `artifacts/experiments/d4-corridor-native-candidate-4/` — new staged candidate
  (`PRELAUNCH.json`, `PRELAUNCH.sha256`, `graphics-identity.json`, isolated
  workspace)
- `docs/handoff/2026-10-25/d4-corridor-native-candidate-4-preparation.md` (this
  record)
- `EVIDENCE_INDEX.md` — E31
- `docs/requirements-evidence-matrix.md` — candidate-4 row
- Relevant Obsidian notes and the synchronized
  `OpenTTD-Knowledge/99-Source-Documents/EVIDENCE_INDEX.md` copy
