# D4 Native Road & Station Construction — fresh candidate-5 staging + independent review

Status: **fresh candidate `D4-CORRIDOR-5` staged at
`artifacts/experiments/d4-corridor-native-candidate-5/`,
`PENDING_AUTHORIZATION`; `PRELAUNCH PASS` + read-only `PREFLIGHT PASS`;
independent review verdict **PASS** (20/20 recorded checks, fresh-context
reviewer, read-only). No claim, no authorization file, nothing launched,
no signing. Milestone D4 remains **INCOMPLETE (native)**.**

Date: 2026-10-25. Predecessors:

- [candidate-4 outcome](d4-corridor-native-candidate-4-outcome.md) (consumed
  exactly once; `op-06` response-size halt; must not be retried)
- [response-limit fix](d4-corridor-response-limit-fix.md) (E33 offline protocol
  correction, validated)
- [candidate-4 preparation](d4-corridor-native-candidate-4-preparation.md)
  (E31 — the staging procedure followed here)

No retry, re-sign, claim creation/consumption, OpenTTD launch, AdminPort
access, save mutation, or Git stage/commit/push/reset/clean/stash was
performed. Evidence-index registration for this record is left to the
operator (no new E-number is claimed here).

## 1. Identity decision

Candidate history at staging time:

| Identity | State | Disposition |
| --- | --- | --- |
| `D4-CORRIDOR-1` | consumed once (E21) | never retry or reuse |
| `D4-CORRIDOR-2` | never consumed; **stale** (E24/E27) | frozen closure predates ADR-012/ADR-013; not launchable; never edit or reuse |
| `D4-CORRIDOR-3` | consumed once (E28) | never retry or reuse |
| `D4-CORRIDOR-4` | consumed once (E32) | never retry, reuse, re-sign or relabel; retained evidence immutable |
| `D4-CORRIDOR-5` | **staged by this record** | fresh, never consumed, `PENDING_AUTHORIZATION` |

No repository reference to `D4-CORRIDOR-5` existed before staging
(repo-wide search: absent; `git log -S 'D4-CORRIDOR-5' --all`: empty), and no
candidate-5 directory existed. The single identity constant
`CORRIDOR_ATTEMPT` was advanced from `D4-CORRIDOR-4` to `D4-CORRIDOR-5`
before staging — the same one-constant staging change used for the E31
candidate-4 staging. No other runtime byte was changed for this staging.

## 2. Active schedule and invariants (v3)

| Invariant | Verified value (re-derived from current source, not quoted) |
| --- | --- |
| Schedule version | `3` (`SCHEDULE_VERSION`) |
| Road operations | **7** (`ROAD_OP_COUNT = 7`) |
| Planned exchanges | **22** (`7 × 3 + 1`); request cap **28** (`+6` slack) |
| Per-operation cost ceiling | **£2,000** (`MAX_CORRIDOR_COST`) |
| Redundant interior join `48047↔48303` | **absent** |
| Perpendicular corner join `45743↔45999` | **present** (op-03, `BuildRoad`) |
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

Plan digest triple-match: re-derived `plan_digest_of(corridor_schedule())`,
the sealed `PRELAUNCH.json` `plan_policy.plan_digest`, and the E29-documented
v3 digest all equal
`b5b472ff5ae15d74ad618436eb36603dd07fbaf091c14610bd7f6e8862283a78`.

## 3. Staged candidate

| Fact | Value |
| --- | --- |
| Directory | `artifacts/experiments/d4-corridor-native-candidate-5/` (created `exist_ok=False`) |
| Attempt | `D4-CORRIDOR-5`, milestone `D4-CONSTRUCTION`, kind `corridor` |
| Prelaunch schema | `d4-corridor-native-prelaunch-v1` |
| PRELAUNCH seal | `505b5d493752845041838e5f4dfc6d068f09a8ccb8a264bba3a7a1ba490a4a7c` (matches `PRELAUNCH.sha256`) |
| Authorization payload | sha-256 `77a965f0d0b0404637385c522bd518a2ab525ec249be67d5f848416ed455d0e4` over 2,307 canonical bytes (byte count identical to the staged candidate-4 payload; same v3 shape) |
| Plan digest | `b5b472ff5ae15d74ad618436eb36603dd07fbaf091c14610bd7f6e8862283a78` (v3, 7 ops) |
| Source world | D3 `after.sav` `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e`; staged `source.sav` byte-exact match; prerequisite `D3-TERRAFORMING-1` binding re-verified against the retained D3 record |
| Pinned binary | `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c` |
| Frozen closure | 3,448 entries; every entry re-hashed and matched during review |
| Endpoints | admin `54655` / game `50765` (workspace `isolated/openttd-15.3-7u83knw5`, mode `0700`; configs and `.admin-secret` mode `0600`) |
| Budgets | 1 launch, 1 connection, 7 road ops, 22 planned / 28 request cap, 0 retries/reconnects, per-op ceiling £2,000, `response_bytes: 640` |
| Authorization | `PENDING — requires ONE fresh operator authorization after all preflight gates` |
| Claim / authorization file | **absent** (never-consumed state) |

## 4. Protocol-limit verification (E33, current state)

All confirmed against current source and re-executed offline (not taken from
any earlier report):

| Condition | Result |
| --- | --- |
| Non-protocol-4 default decode bound stays **512** | `observation_protocol.MAX_PAYLOAD_BYTES = 512`; a 513-byte app payload is refused with `MalformedMessage` under the default |
| Protocol 4 explicitly permits **640** | `MAX_CORRIDOR_RESPONSE_BYTES = 640`; 640 app bytes decode/encode (inclusive), 641 refused |
| Requests remain bounded at **512** | `MAX_CORRIDOR_REQUEST_BYTES = 512`; request serialization refuses >512 (retained depot-06 request wire, 231 bytes, well inside) |
| AdminPort frame limit enforced | `MAX_GAMESCRIPT_PAYLOAD_BYTES = AdminFrameDecoder.MAX_FRAME_LENGTH - 4 = 32763`; bounds validated (positive int, ≤ ceiling); the 32763 ceiling is enforced on both encode and decode |
| UTF-8 / schema / correlation / malformed strict | non-UTF-8, unterminated, embedded-NUL, truncated, duplicate-key and empty bodies still fail closed under the 640 bound; invalid bounds raise `ValueError` |
| Retained 513-byte depot response decodes + correlates offline | the retained candidate-4 `depot-06` admin frame (517 bytes, kind 124, 513-byte app payload) decodes under the explicit 640 bound and correlates to status `BUILT`, cost 390, funds 492,149, tile 45487, front 45743 (`regression evidence only, not a native result`) |
| Replay honesty | replaying candidate-4 now gets past the frame decoder and stops at the honest gate `retained gateway response lacks its durable response file`; it claims no success. Replaying never-consumed candidate-5 returns `AUTHORIZATION_UNVERIFIED` / `CLAIM_ABSENT` |
| Live + replay decode paths | both corridor decode sites pass `max_payload_bytes=MAX_CORRIDOR_RESPONSE_BYTES` explicitly; no global-limit raise |

## 5. Checks and results (actually run, 2026-10-25)

| Check | Actual result |
| --- | --- |
| `.venv/bin/python -m pytest -o addopts='' -q` on the four focused suites (run twice: before and after the identity advance) | **129 passed** both times |
| `py_compile` on the changed module | exit 0 |
| `ruff check --ignore UP037` on the changed module | All checks passed |
| `git diff --check` | clean |
| `corridor_construction_native prepare …/candidate-5` | exit 0, **PRELAUNCH PASS** |
| standalone `corridor_construction_native preflight …/candidate-5` | exit 0, **PREFLIGHT PASS** (re-derives schedule pins, route scope, world binding, prerequisite binding, 3,448-entry freeze, endpoint reservation — read-only) |
| `verify …/candidate-5` (read-only) | structured `AUTHORIZATION_UNVERIFIED` / `CLAIM_ABSENT`; no receipt claimed |
| `verify …/candidate-4` (read-only) | refuses at the honest missing-durable-response gate (`retained gateway response lacks its durable response file`) |
| retained candidate-4 manifest | **80/80 OK** (`sha256sum -c`, no failures) |
| D3 prerequisite manifest | 385/385 OK; D3 authorization/claim/outcome bytes untouched |
| current runtime | no OpenTTD process; no listener on candidate ports 54655/50765; no staged secret outside the candidate workspace |

## 6. Independent review (NOT the preparer's self-review)

The review package was reviewed by a **fresh-context independent reviewer**
(a separate agent invoked after preparation, with no access to the
preparer's working assumptions, operating strictly read-only: no repository
file created or modified, no native operations, no Git mutations, pytest run
with `-p no:cacheprovider`). The reviewer re-derived **everything** from the
repository records and retained evidence itself: candidate-history
uniqueness, the sealed PRELAUNCH record, seal and authorization-payload
digests, the D3 world pin and prerequisite binding, the full 3,448-entry
frozen closure (every entry re-hashed), the v3 schedule pins and plan-digest
triple-match, budgets, the E33 protocol statics and dynamics over the
retained candidate-4 depot frame, replay honesty for both candidates, the
four focused test suites (129 passed), the offline preflight (PASS), the
runtime isolation snapshot, and the scope of the working-tree deltas against
the E33 changed-file table.

**Reviewer verdict: `PASS` — 20/20 recorded checks, zero failures.**
Key reviewer-observed figures (independently computed): seal
`505b5d493752845041838e5f4dfc6d068f09a8ccb8a264bba3a7a1ba490a4a7c`;
payload digest `77a965f0d0b0404637385c522bd518a2ab525ec249be67d5f848416ed455d0e4`
over 2,307 canonical bytes; plan digest `b5b472ff…2283a78`; source world
`fbebef54…d59e`; frozen closure 3,448/3,448; focused tests 129 passed;
`PREFLIGHT PASS`; candidate-5 `AUTHORIZATION_UNVERIFIED`/`CLAIM_ABSENT`;
candidate-4 evidence 80/80 OK with the honest replay refusal; no
result/claim/authorization/cleanup file inside candidate-5 (no unauthorized
consumption).

Reviewer observations (non-failing, recorded verbatim in intent):

1. The identity-constant advance (together with the E33 fix) is
   **uncommitted working-tree delta** versus HEAD — the same pattern as the
   prior offline records; the frozen closure binds the actual working-tree
   bytes, so the freeze is exact regardless of Git state.
2. Unrelated working-tree content (E34 analytics module, docs/vault sync,
   root clutter) is present but outside the corridor runtime path and, where
   applicable, covered by the freeze; hygiene note only.
3. The operator's production signing key/anchor is correctly **out of
   scope** — that is the separate authorization gate, not reviewable here.

## 7. Authorization boundary and next gate

This record covers candidate preparation, sealing, artifact staging, offline
preflight and the review package **only**. It does NOT authorize:

- Signing or re-signing; creating or consuming a claim.
- Launching OpenTTD or accessing AdminPort; native execution or save mutation.
- Reusing candidates 1/2/3/4 in any form; editing any retained evidence.
- Git staging, commits, pushes, resets, cleans, or stashes.

**Next gate:** one explicit, separate operator authorization covering
(a) signing `D4-CORRIDOR-5` under the pinned anchor and (b) a single
one-shot native attempt with its verification. Until that authorization is
given, signing must not proceed. Milestone D4 remains **INCOMPLETE
(native)**: preparation and offline validation satisfy no native acceptance
criterion, and candidate-5 has no claim, no receipt, and no verified result.

## 8. Files touched by this session

- `app/simulation/openttd/proof/corridor_construction_native.py` — one
  identity constant (`D4-CORRIDOR-4` → `D4-CORRIDOR-5`); no other runtime byte
- `artifacts/experiments/d4-corridor-native-candidate-5/` — new staged
  candidate (`PRELAUNCH.json`, `PRELAUNCH.sha256`, `graphics-identity.json`,
  isolated workspace incl. staged `source.sav`)
- `docs/handoff/2026-10-25/d4-corridor-native-candidate-5-preparation.md`
  (this record; no E-number claimed)
