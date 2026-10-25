# D4 Native Road & Station Construction — candidate-3 consumed outcome

Status: **`D4-CORRIDOR-3` CONSUMED EXACTLY ONCE under explicit operator
authorization. The phase is `PARTIAL_EXECUTION_EVIDENCE`: `op-00`–`op-02` built
and read back, `op-03` was refused at admission, `op-04`–`op-07` and the route
read were not executed, no receipt-bound `after.sav` exists, and the retained
result stays `verified: false`, `status: FAILED_CLEANUP`. Milestone D4 remains
INCOMPLETE (native).**

Predecessor:
[d4-corridor-native-candidate-3-preparation.md](d4-corridor-native-candidate-3-preparation.md)
(staging: seal `8cc8c1f7…7d24`, payload `e1163d09…068d`, `PENDING_AUTHORIZATION`).
The operator subsequently authorized signing of this candidate only, then
separately authorized this one-shot native run and its verification.

This record reports the executed attempt. No retry, re-sign, replacement
candidate, second launch, claim reuse or Git stage/commit/push/reset/clean/stash
was performed. The source tree's pre-existing user changes were not modified by
this attempt beyond the files listed in §9.

## 1. Authorization and pre-run gates

| Gate | Result |
| --- | --- |
| Candidate identity | `D4-CORRIDOR-3`, milestone `D4-CONSTRUCTION`, kind `corridor` |
| PRELAUNCH seal | `8cc8c1f70c1928ccfb6e10b169d442ec1d62f1826790f617b86c78a62dda7d24` — matched `PRELAUNCH.sha256` |
| Authorization payload | sha-256 `e1163d09b3344d020676443eec7a39b0299a2faab6d591dec7a7d0644d01068d`, 2,393 canonical bytes |
| `AUTHORIZATION.json` | sha-256 `5484cdc15aff885eababa181da2b75c96ca636c60625d383750ecc3639be705e`; payload exactly equal to the candidate-derived payload; 64-byte Ed25519 signature |
| Operator identity | `sha256-ed25519-public-key:cbb63ff58f17f13df3e1be0735fad18497e3a0c6ad6b5dd55491d708ae40c614` |
| `verify_authorization` | PASS under the pinned production anchor |
| Source save | `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e` — declared and actual `source.sav` matched |
| Prior claim/consumption | none; `CLAIM.json` and `LAUNCH-CONSUMED.json` absent |
| Read-only preflight | `PREFLIGHT PASS` immediately before the run |

The run command was the candidate's own `execution_command` exactly once. It
consumed the one-shot claim (`consumed: true`, `launches_allowed: 1`,
`retries: 0`) and recorded one launch and one encrypted AdminPort connection.

## 2. Executed operations

Funds started at **£496,543**. Each operation's quote matched its command cost.

| Op | Planned scope | Admission | Native cost | Readback | Funds after |
| --- | --- | --- | --- | --- | --- |
| `op-00` | run A `45747→45743`, 5 tiles | READY, £785 | BUILT, £785 | `confirm-00` READ, independent digest matched | £495,758 |
| `op-01` | run-B segment `45999→48047`, 9 tiles | READY, £1,398 | BUILT, £1,398 | `confirm-01` READ, independent digest matched | £494,360 |
| `op-02` | run-B segment `48303→50095`, 8 tiles | READY, £1,151 | BUILT, £1,151 | `confirm-02` READ, independent digest matched | £493,209 |
| `op-03` | interior road join `48047↔48303`, 2 tiles | **NOT_BUILDABLE**, cost 0 | **no command issued** | none | £493,209 |
| `op-04` | corner join `45743↔45999` | not reached | — | — | — |
| `op-05`–`op-07` | pickup stop, delivery stop, depot | not reached | — | — | — |
| route read | 24-tile witness, 23 pairs | not reached | — | — | — |

Verified prefix receipts exist for exactly `op-00`, `op-01`, `op-02`
(`company-corridor-receipt-v1`, `NATIVE_STATE_CHANGED`, each with its own
intent-scoped independent readback). Funds reconcile exactly:

```text
£496,543 − £785 − £1,398 − £1,151 = £493,209
```

## 3. Exact stopping point

`op-03` admission returned `status: NOT_BUILDABLE`, `eligible: false`, `cost: 0`,
`covered: 2`, `road0: true`, `road1: true`, `pair_total: 1`, `pairs_ok: 1`.
The runner correctly refused to dispatch a native command without a positive
tested READY quote and halted with:

```text
ValueError: native READY admission with positive tested cost required
```

The retained phase outcome is `PARTIAL_EXECUTION_EVIDENCE` with
`failed.label = op-03` and `world_state = UNCERTAIN_AFTER_FAILED_COMMAND`.
Nothing after that halt was executed, relabeled, retried or compensated.

## 4. Native state and authoritative save

| Fact | Value |
| --- | --- |
| Session-before save | `session-before.sav` sha-256 `a3e6b5102ae12f98fd782c5a417ac2bc2237397ef3ca66163ed4695ce369cc5c` |
| Retained diagnostic save | `after-diagnostic.sav` sha-256 `b52d0ecf9076c2dbc14531e7824aad49271265e06da7d5ef8b74ed578b9d970b` |
| Authoritative `after.sav` | **absent** |
| `receipt.json` | **absent** |
| Native launch / connection | 1 / 1 |
| Requests retained | 10 (within budget 31) |
| State changed | `true` for the three built segments only |

`after-diagnostic.sav` is **not** a receipt-bound authoritative save and must
never be used as one. The world beyond the three verified built segments remains
explicitly uncertain.

## 5. Cleanup and replay verification

The runtime was asked to quit and was reaped (`cleanup.json`: `quit_requested`,
`reaped`, `returncode: 0`, `remaining_processes: []`). No listener remains on
the game or AdminPort. The cleanup gate itself failed:

```text
verification_error: Live or ambiguous endpoint socket:
{'table': 'tcp', 'local': '127.0.0.1', 'local_port': 36515,
 'remote': '127.0.0.1', 'remote_port': 40094, 'state': 5, 'inode': 0}
```

At observation time the closing connection was in TCP state 5, not the accepted
`TIME_WAIT`. Consequently `cleanup.json` has no `sockets_closed`,
`workspace_disposed` or `credential_removed` success fields, the isolated
workspace was not disposed, and the result status is `FAILED_CLEANUP`.

Independent post-run observation shows the two sockets now in `TIME_WAIT` and
no listener on `33725`/`36515`; this does **not** retroactively make the retained
cleanup record successful.

Because cleanup aborted before workspace closure, the isolated operational
credential was not removed. It remains confined to the `0700` candidate
workspace at:

```text
artifacts/experiments/d4-corridor-native-candidate-3/isolated/openttd-15.3-aghwu0j0/secrets.cfg
```

The secret value is not reproduced in this record. Removing or rotating it is a
separate operator remediation; the retained evidence was left unmodified so the
failed cleanup remains diagnosable.

Read-only replay (`corridor_construction_native verify`) passed the manifest,
claim and authorization stages, then refused with:

```text
ValueError: halted attempt cleanup incomplete
```

No verified receipt is claimed. The run's own manifest re-verifies **48/48**
entries.

## 6. Acceptance assessment

| D4 acceptance area | Result |
| --- | --- |
| Candidate identity / authorization binding | PASS |
| One-shot claim / no retry | PASS |
| All eight scheduled operations executed | **FAIL** — 3/8 built |
| Per-operation receipts for the full schedule | **FAIL** — only `op-00`–`op-02` |
| Route receipt (23/23 witness pairs, stops, depot) | **FAIL** — not reached |
| Authoritative receipt-bound after-save | **FAIL** — absent |
| Funds reconciliation for executed ops | PASS — £496,543 → £493,209 |
| Cleanup certification | **FAIL** — `FAILED_CLEANUP` |
| Replay verification | **FAIL** — refused on incomplete cleanup |
| Milestone D4 complete | **NO — INCOMPLETE (native)** |

## 7. Evidence preservation

Authoritative evidence remains in
`artifacts/experiments/d4-corridor-native-candidate-3/`: `AUTHORIZATION.json`,
consumed `CLAIM.json`, `LAUNCH-CONSUMED.json`, `result.json`, `cleanup.json`,
`frames.json`, all retained request/response pairs, per-op evidence, retained
saves, runtime/session identities, logs, and `artifact-manifest.sha256`
(48/48 OK). The manifest was not rewritten after the run.

Diagnostic copies are kept separately (not authoritative, not covered by the
candidate manifest) in
`artifacts/diagnostics/d4-corridor-native-candidate-3-2026-10-25/`:
`run-console.log`, `verify-console.log`, `manifest-check.log` and
`checksums.sha256`.

The D3 after-save `fbebef54…d59e`, prior consumed attempts, `D4-CORRIDOR-1`,
the never-consumed stale `D4-CORRIDOR-2`, and historical manifests were not
edited.

## 8. What must not happen next

- Do not retry `D4-CORRIDOR-3`; its claim is consumed.
- Do not reuse or edit it, sign a replacement record, or create a replacement
  candidate without separate operator authorization.
- Do not treat `after-diagnostic.sav` as an authoritative after-save.
- Do not claim D4 complete.

Any future attempt requires a fresh, separately reviewed candidate regenerated
from the current reviewed source, with the `op-03` admission defect understood
and corrected, plus fresh explicit operator authorization.

## 9. Files touched by this outcome close-out

- `docs/handoff/2026-10-25/d4-corridor-native-candidate-3-outcome.md` (this file)
- `EVIDENCE_INDEX.md` — E28 row and addendum
- `docs/requirements-evidence-matrix.md` — D4 candidate-3 status
- `TASKS.md` — D4 task status
- Relevant Obsidian notes under `OpenTTD-Knowledge/` — status/evidence/task
  pointers
- `artifacts/diagnostics/d4-corridor-native-candidate-3-2026-10-25/` — separate
  diagnostic copies

No source, test, package, frozen evidence, candidate artifact, save or
authorization record was edited by this close-out.
