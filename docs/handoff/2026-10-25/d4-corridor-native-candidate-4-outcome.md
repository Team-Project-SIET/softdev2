# D4 Native Road & Station Construction — candidate-4 consumed outcome

Status: **`D4-CORRIDOR-4` CONSUMED EXACTLY ONCE under explicit operator
authorization. The phase is `PARTIAL_EXECUTION_EVIDENCE`: `op-00`–`op-05`
built and read back, `op-06` was dispatched and the native GameScript log
reports `BUILT`, but its response frame exceeded the 512-byte application
limit and was rejected before parsing; no independent readback or receipt
exists. The retained result stays `verified: false`, `status:
PHASE_HALTED_PREFIX_PRESERVED`. Cleanup completed and is certified. Milestone
D4 remains INCOMPLETE (native).**

Date: 2026-10-25. Predecessors:

- [candidate-4 preparation](d4-corridor-native-candidate-4-preparation.md) (E31)
- [candidate-3 cleanup remediation](d4-corridor-native-candidate-3-cleanup-remediation.md) (E30)
- [`op-03` root cause](d4-corridor-op03-root-cause.md) (E29)

No retry, re-sign, replacement candidate, second launch, claim reuse, or Git
stage/commit/push/reset/clean/stash was performed.

## 1. Cleanup-certification gate determination

**The documented procedure does not make full certification of
`D4-CORRIDOR-3`'s historical cleanup a hard prerequisite for a fresh
candidate.** The relevant rule is per-attempt:

- `docs/external-openttd-runtime.md` defines cleanup over the process and
  workspace owned by the launch; a failed reap retains files, and the launcher
  must retain artifacts before workspace disposal. It does not create a
  cross-candidate certification prerequisite.
- [`d4-corridor-native-candidate-3-outcome.md` §8](d4-corridor-native-candidate-3-outcome.md)
  lists the prerequisites for a future attempt: a fresh, separately reviewed
  candidate regenerated from current reviewed source, the `op-03` defect
  understood and corrected, and fresh explicit operator authorization. Cleanup
  certification of the consumed candidate is not listed.
- The read-only replay verifier requires `sockets_closed` only for the
  candidate it replays (`verify_corridor_attempt`, the `cleanup_complete`
  check). `preflight` checks its own candidate's absent claim, seal, frozen
  closure, v3 schedule and D3 prerequisite world; it does not consult another
  candidate's cleanup record.
- E30 verifies the actual isolation concern: the failed candidate-3 workspace
  is absent, `isolated/` is empty, no candidate-3 secret or config file
  remains, and no candidate-3 process or listener remains. The historical
  `verification_error` and the absent `sockets_closed` field are preserved
  verbatim; no successful cleanup field was fabricated.

Independent current-runtime checks before signing confirmed: no OpenTTD
process, no socket on candidate-3 ports `33725`/`36515`/`40094` or candidate-4
ports `44429`/`40763`, both isolated workspaces absent and both `isolated/`
directories empty, no staged secret remaining, pinned binary SHA-256
`276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`, and the
candidate-4 workspace mode `0700` with `openttd.cfg`, `private.cfg`,
`secrets.cfg` and `.admin-secret` mode `0600`. Candidate-4 preflight passed
again immediately before signing. The historical candidate-3 record therefore
remains `FAILED_CLEANUP` / replay-refused; that limitation was not rewritten
and did not block this fresh candidate.

## 2. Candidate identity and authorization

| Gate | Result |
| --- | --- |
| Candidate | `D4-CORRIDOR-4`, milestone `D4-CONSTRUCTION`, kind `corridor` |
| Directory | `artifacts/experiments/d4-corridor-native-candidate-4/` |
| PRELAUNCH seal | `88cd1ecc7b7b76d3f305deccdb820fa64782a6896e342263b4bb86b281fd22c3` — matched `PRELAUNCH.sha256` |
| Authorization payload | sha-256 `4037c5d8a6c8dc3bcc4998dcc4b906f80eb48536a00ffca6947574ccfa487c7f` over 2,307 canonical bytes; recomputed and matched before signing |
| Plan digest | `b5b472ff5ae15d74ad618436eb36603dd07fbaf091c14610bd7f6e8862283a78` (v3, 7 ops) |
| Source world | D3 `after.sav` `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e`; staged `source.sav` matched |
| Frozen closure | 3,448 entries; `verify_freeze` PASS |
| Schedule | v3: 7 road ops, 22 planned exchanges, request cap 28, per-op ceiling £2,000, no `48047↔48303` interior join, corner `45743↔45999` present |
| `AUTHORIZATION.json` | sha-256 `b069b48434b4cab8abf55400b878776fadb0d1917868c4f73e01fd8b7cb5db6d`; 64-byte Ed25519 signature; `verify_authorization` PASS under the pinned production anchor |
| Operator identity | `sha256-ed25519-public-key:cbb63ff58f17f13df3e1be0735fad18497e3a0c6ad6b5dd55491d708ae40c614` |
| Claim | consumed, `launches_allowed: 1`, `retries: 0` |
| Native launch / connection | 1 / 1 |

The approved secret-handling path was used: the operator private key was read
only to produce the signature, was never printed, copied into a report, or
placed in the candidate directory. The seed variable was cleared immediately
after signing.

## 3. Executed operations and funds

Funds started at **£496,543**.

| Op | Planned scope | Admission | Native cost | Readback | Funds after |
| --- | --- | --- | --- | --- | --- |
| `op-00` | run A `45747→45743`, 5 tiles | READY, £785 | BUILT, £785 | `confirm-00` READ, digest matched | £495,758 |
| `op-01` | run-B segment `45999→48047`, 9 tiles | READY, £1,398 | BUILT, £1,398 | `confirm-01` READ, digest matched | £494,360 |
| `op-02` | run-B segment `48303→50095`, 8 tiles | READY, £1,151 | BUILT, £1,151 | `confirm-02` READ, digest matched | £493,209 |
| `op-03` | perpendicular corner `45743↔45999`, 2 tiles | READY, £71 | BUILT, £71 | `confirm-03` READ, digest matched | £493,138 |
| `op-04` | pickup stop tile `45748`, front `45747` | READY, £307 | BUILT, £307 | `confirm-04` READ, digest matched | £492,831 |
| `op-05` | delivery stop tile `50351`, front `50095` | READY, £292 | BUILT, £292 | `confirm-05` READ, digest matched | £492,539 |
| `op-06` | depot tile `45487`, front `45743` | READY, £390 | native log says BUILT; response rejected before parsing | **none accepted** | frame reports £492,149 |
| route read | 24-tile witness, 23 pairs | not reached | — | — | — |

Verified prefix reconciliation:

```text
£496,543 − £785 − £1,398 − £1,151 − £71 − £307 − £292 = £492,539
```

This matches `inspect-06` funds exactly. The `depot-06` response frame body
reports `"status":"BUILT","cost":390,"funds":492149`, and `stderr.log` retains
`D4_RESPONSE depot-06 BUILT`. Because that frame was rejected before parsing,
the depot is **not** a verified operation and `£492,149` is not claimed as a
verified reconciliation.

## 4. Exact stopping point

After `inspect-06` and the admitted depot intent, the runner dispatched
`depot-06`. The response body was 513 bytes (admin frame 517 bytes, GameScript
payload 514 bytes including its NUL terminator), one byte above the
`MAX_PAYLOAD_BYTES = 512` application limit. `decode_gamescript` raised:

```text
MalformedMessage: GameScript packet exceeds application limit
```

The runner halted with `failed.label = op-06`,
`world_state = UNCERTAIN_AFTER_FAILED_COMMAND`, and
`dispatch_state = DISPATCHED_UNKNOWN`. It issued no retry, reconnect,
compensation, route read, or later operation. The phase record is
`PARTIAL_EXECUTION_EVIDENCE`.

## 5. Native state, saves, manifest, and replay

| Fact | Value |
| --- | --- |
| Session-before save | `session-before.sav` sha-256 `a3e6b5102ae12f98fd782c5a417ac2bc2237397ef3ca66163ed4695ce369cc5c` |
| Diagnostic save | `after-diagnostic.sav` sha-256 `abf3c8857e5449c0d46e8b51be3b8ccc5b218ae37f6cd249b3fc5ed5813945c0` |
| Authoritative `after.sav` | **absent** |
| `receipt.json` | **absent** |
| Candidate manifest | **80/80 OK** |
| Requests retained | 19 of 28 (6 × 3 verified exchanges + `inspect-06`; the `depot-06` request file is retained but its response file was never written) |
| Read-only replay | **fails with the same `MalformedMessage`**, before any verdict; no `PHASE_HALTED_EVIDENCE_PRESERVED` label is claimed |
| Cleanup | `reaped: true`, `sockets_closed: true`, `workspace_disposed: true`, `credential_removed: true`, `cleanup_error: []`, return code 0 |
| Remaining process/listener/workspace | none; candidate-4 `isolated/` empty |

`after-diagnostic.sav` is not a receipt-bound authoritative save and must never
be used as one. The world beyond the six verified operations remains uncertain.

## 6. Acceptance assessment

| D4 acceptance area | Result |
| --- | --- |
| Candidate identity / authorization binding | PASS |
| One-shot claim / no retry | PASS |
| v3 schedule invariants | PASS — 7 ops, 22 planned, cap 28, ceiling £2,000, no interior join, corner present |
| All seven scheduled operations executed and verified | **FAIL** — 6/7 verified; `op-06` response rejected |
| Per-operation receipts for the full schedule | **FAIL** — `op-00`–`op-05` only |
| Route receipt (23/23 witness pairs, stops, depot) | **FAIL** — not reached |
| Authoritative receipt-bound after-save | **FAIL** — absent |
| Funds reconciliation for verified ops | PASS — £496,543 → £492,539 |
| Cleanup certification | **PASS** — all four cleanup fields true, workspace disposed |
| Replay verification | **FAIL** — verifier raises `MalformedMessage` on the retained 513-byte response |
| Milestone D4 complete | **NO — INCOMPLETE (native)** |

## 7. Evidence preservation

Authoritative candidate evidence is in
`artifacts/experiments/d4-corridor-native-candidate-4/`: `PRELAUNCH.json`,
`PRELAUNCH.sha256`, `AUTHORIZATION.json`, consumed `CLAIM.json`,
`LAUNCH-CONSUMED.json`, `result.json`, `cleanup.json`, `frames.json`,
`session-before.sav`, `after-diagnostic.sav`, all retained request/response and
per-op files, runtime logs, and `artifact-manifest.sha256` (80/80 OK).

Diagnostic copies are separate and non-authoritative in
`artifacts/diagnostics/d4-corridor-native-candidate-4-2026-10-25/`:
`run-console.log`, `verify-console.log`, `manifest-check.log`,
`pre-run-authorization-check.log`, `cleanup-and-isolation-check.log`, and
`checksums.sha256`.

The D3 after-save, candidate-1, candidate-2, candidate-3, their manifests,
saves and authorization records were not edited.

## 8. What must not happen next

- Do not retry `D4-CORRIDOR-4`; its claim is consumed.
- Do not reuse, edit, re-sign or relabel this candidate.
- Do not treat `after-diagnostic.sav` or the unparsed depot frame as a
  verified depot build or an authoritative save.
- Do not claim D4 complete or a verified route.

A future attempt requires a fresh, separately reviewed candidate from current
reviewed source, a corrected response-size/application-limit path, fresh
authorization, and separate operator approval. This outcome record authorizes
none of those actions.
