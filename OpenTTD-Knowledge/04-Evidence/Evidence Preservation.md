---
title: "Evidence Preservation"
type: evidence
status: current
updated: 2026-10-26
tags:
  - openttd
  - evidence
  - preservation
---

# Evidence Preservation

The project's long-term value depends on immutable evidence. These rules are drawn from
[[99-Source-Documents/AI_HANDOFF]], [[99-Source-Documents/EVIDENCE_INDEX]],
[[99-Source-Documents/CONTEXT]] §24 and the dated offline-evidence freeze spec
(`docs/specs/openttd-offline-evidence-freeze.md`).

## What must be preserved

Every consumed attempt keeps its full artifact set; e.g. the D-chain pattern
(E17/E19/E20):

- sealed `PRELAUNCH.json` + `PRELAUNCH.sha256`
- `AUTHORIZATION.json`, one-shot `CLAIM.json` / `LAUNCH-CONSUMED.json`
- `plan.json`, per-exchange request/response pair files, `frames.json`
- `receipt.json`, `result.json`
- owned `session-before.sav` / `after.sav` (+ distinct `after-diagnostic.sav`, retained,
  **never substituted**)
- `runtime-identity.json`, `cleanup.json`, logs, `artifact-manifest.sha256`

Demo/capture equivalents: `result.json`, `classification-completeness.json`,
`correspondence-verdict.json`, page pairs, `classification-receipts.json`, `CLAIM.json`,
`cleanup.json`, `stderr.log`, failure artifacts (`capture-failure.json`, `failure.sav`).

## Hash and identity discipline

- SHA-256 manifests are re-verified after any inspection that touches bytes
  (e.g. `sha256sum -c artifact-manifest.sha256`). Hashes identify bytes; they do not
  authenticate outcomes or replace production seals (EVIDENCE_INDEX preamble).
- Frozen attempt identity is consumed once: no retries, no identity transfer, no recreated
  packages. "Missing artifacts on another machine are UNKNOWN, not a reason to regenerate
  historical evidence."
- Transfer: carried with Git history + ignored evidence through a reviewed secure archive;
  compare hashes after transfer. Exclude `.env`, private keys, account/cache folders,
  temporary credentials.

## The CONTEXT.md authority-pin conflict — resolved 2026-10-25 (E26, ADR-014)

Retained authority manifests pin **repo-root `CONTEXT.md` bytes as captured 2026-10-08**
(sha256 `b94b966…`): two `historical-integrity.json` freezes (attempt1, prelaunch-v4) and
the `structural-world-real-prelaunch` `source-freeze.json`. Since commit `bdbec43`
(2026-10-11) the file has moved past that capture, so:

- the two protected-authority tests and
- `test_industry_production_proof::test_architecture_authority_unchanged`

fail at baseline, independent of any new work. The 2026-10-18 header addendum to
CONTEXT.md is prepend-only, lives in the working tree, is explicitly **not** part of any
documentation commit, and is duplicate-recorded in [[99-Source-Documents/AI_HANDOFF]] so
it is not lost. Resolution (explicitly operator-authorized 2026-10-25) keeps every retained
manifest and historical byte frozen and unmodified. One record
(`docs/authority/context-authority-supersession.json`) scopes exactly the
historical/current `CONTEXT.md` digest transition; the fail-closed validator
still delegates every other entry to the unchanged `validate_protection`
contract, and the base validator continues to reject the diverged file without
the record. The historical bytes are not retained, so no recovery is claimed.

## Partial native attempt with failed cleanup — `D4-CORRIDOR-3` (E28)

The 2026-10-25 one-shot D4 run was preserved exactly as executed even though its
cleanup gate failed: `result.json` (`PARTIAL_EXECUTION_EVIDENCE`,
`verified: false`, `FAILED_CLEANUP`), `cleanup.json` with its TCP state-5
`verification_error`, all 10 exchange pairs, the three built-op readbacks, the
diagnostic save and the 48-file manifest remain in the candidate directory.
`after-diagnostic.sav` is retained but is **not** an authoritative after-save;
no `after.sav` or `receipt.json` was fabricated. Read-only replay refusing
`halted attempt cleanup incomplete` is itself retained as the honest verdict.

Console logs and the manifest check are copied separately to
`artifacts/diagnostics/d4-corridor-native-candidate-3-2026-10-25/` (not
authoritative, not in the candidate manifest). The original cleanup aborted
before workspace closure, so the isolated operational credential remained under
the `0700` candidate workspace (`isolated/openttd-15.3-aghwu0j0/secrets.cfg`);
its value was never copied into records.

**Subsequent remediation (2026-10-25, E30):** the reported credential removal
and workspace disposal were verified read-only without reopening the workspace
or accessing the credential. `cleanup.json` now records
`credential_removed: true` and `workspace_disposed: true`; the workspace path is
absent, `isolated/` is empty, and no candidate-3 `secrets.cfg`, `private.cfg`,
`openttd.cfg`, process or listener remains. The file retains the historical TCP
state-5 `verification_error` and still has no `sockets_closed` field, so
`result.json` stays `FAILED_CLEANUP`/`verified: false` and read-only replay still
refuses `halted attempt cleanup incomplete`. The 48-file manifest re-verifies
against the remediated `cleanup.json`, which was rewritten and followed by a
manifest regeneration; the earlier manifest and cleanup bytes are not retained.
The remediation does not create an authoritative after-save, receipt or native
success, and does not rewrite the retained diagnosis. Full record:
`docs/handoff/2026-10-25/d4-corridor-native-candidate-3-cleanup-remediation.md`.

## Partial native attempt with certified cleanup — `D4-CORRIDOR-4` (E32)

The 2026-10-25 one-shot `D4-CORRIDOR-4` run is preserved exactly as executed:
six verified prefix operations, the dispatched-but-unparsed `op-06` depot frame,
the diagnostic save, all 19 retained request/response exchanges and the 80-file
manifest remain in the candidate directory. `result.json` records
`PARTIAL_EXECUTION_EVIDENCE`, `verified: false`,
`status: PHASE_HALTED_PREFIX_PRESERVED`; the 513-byte GameScript response
exceeded `MAX_PAYLOAD_BYTES = 512`, so no `confirm-06`, `receipt.json` or
authoritative `after.sav` was fabricated. `after-diagnostic.sav` is retained but
is **not** an authoritative after-save. Cleanup is certified (`reaped`,
`sockets_closed`, `workspace_disposed`, `credential_removed` all true,
`cleanup_error: []`, return 0) and the workspace is absent with no remaining
process or listener. Read-only replay raised the same `MalformedMessage` at the
time and is retained as the honest result; the later E33 offline fix advances
past that frame but still refuses for the missing durable response. This outcome
does not rewrite the candidate-3 `FAILED_CLEANUP` record: cleanup certification
was resolved as attempt-scoped, and the historical missing `sockets_closed`
remains unchanged.
Full record:
`docs/handoff/2026-10-25/d4-corridor-native-candidate-4-outcome.md`.

## Offline protocol-4 response-limit fix (E33)

The E32 halt was a client-side application-bound mismatch, not an oversized
transport frame. Protocol 4 permits 640-byte responses because the final route
read echoes the 24-tile witness, but `decode_gamescript` applied the version-one
512-byte limit to every protocol. The retained depot exchange is a 517-byte
Admin frame (3-byte header + 513-byte UTF-8 JSON + NUL). Encode/decode now take
a validated opt-in `max_payload_bytes` (default unchanged 512; absolute
frame-body maximum 32763), and protocol 4 passes its documented 640 bytes in
`CorridorReadback.parse_for`, the live exchange and retained-frame replay.
Malformed, truncated, duplicate-key, invalid-UTF-8 and genuinely oversized
messages still fail closed.

The fix is offline only. It does not alter the candidate-4 evidence, create a
receipt or verify the consumed attempt: replay now gets past the frame decoder
and stops at the next honest refusal — the client never persisted
`depot-06-response.json`, and no confirmation or authoritative `after.sav`
exists. Focused suites passed 129/129; `ruff check --ignore UP037` on the
touched files passed, while full `ruff check` reports only four pre-existing
`UP037` findings on unchanged lines, and `py_compile`/`git diff --check` were
clean. Full record:
`docs/handoff/2026-10-25/d4-corridor-response-limit-fix.md`. D4 remains
**INCOMPLETE (native)**; a fresh candidate, independent review and new explicit
operator authorization are still required.

## Consumed verified success — `D4-CORRIDOR-5` (E35)

The 2026-10-26 operator-authorized `D4-CORRIDOR-5` run is preserved exactly as
executed — this time as a **complete verified set**: the signed
`AUTHORIZATION.json` (record sha `55486971…dec03`; operator identity
`sha256-ed25519-public-key:cbb63ff5…40c614`, verified under the pinned
production anchor before writing; the signing seed was captured, never
displayed, logged or persisted, and cleared immediately after signing), the
consumed one-shot claim and `LAUNCH-CONSUMED.json`, all 22 retained
request/response exchanges plus `frames.json` (including the durable
513-byte `depot-06-response.json` written under the E33 640-byte protocol-4
bound), per-op `corridor-XX-…` evidence, the **authoritative receipt-bound
`after.sav`** (sha `a81ac836…ef261`; a separate `after-diagnostic.sav`
`7a853eba…a3` is retained and is never a substitute), `receipt.json`
(`PHASE_COMPLETE` with all seven per-op receipts plus the `ROUTE_VERIFIED`
23/23 route receipt), `result.json` (`verified: true`,
`status: NATIVE_CORRIDOR_VERIFIED`), certified `cleanup.json` (all four fields
true, return code 0, endpoints certified), `stdout.log`/`stderr.log`,
`runtime-identity.json` and the 90/90-OK `artifact-manifest.sha256` remain in
`artifacts/experiments/d4-corridor-native-candidate-5/`.

The one-shot claim is consumed; the identity must never be retried, reused,
re-signed or re-launched — any further native work needs a fresh reviewed
candidate and a fresh explicit operator authorization. Historical evidence was
re-verified byte-unchanged around the run: the D3 prerequisite record (seal
`edb6b34c…`, source save `fbebef54…d59e`), the candidate-1/2/3 directories and
manifests, and the candidate-4 consumed attempt (80/80 manifest re-verified
before the run). Full record:
`docs/handoff/2026-10-26/d4-corridor-native-candidate-5-outcome.md`.

## Offline recovery rules

- Offline recovery belongs in a **separate derived directory**; it never overwrites or
  relabels the original terminal (Attempt 19: E3).
- Keep OBSERVED native measurements / DERIVED aggregates / CONTROLLED inputs separate;
  missing samples are UNKNOWN.
- Do not reset/clean, broad-stage, overwrite historical files, recreate consumed packages,
  or infer runtime proof from controlled tests.

## Git discipline

- No staging/commit/push without explicit authorization; use a reviewed staging allowlist
  if a commit is later requested (AI_HANDOFF).
- Retained runtime artifacts are ignored and must stay un-pushed-by-default
  ([[99-Source-Documents/README]]).
- Important edge rule: a historical protection set later reported
  **8,522 protected files from Attempts 1–16 and CONTEXT.md unchanged** (README Attempt 17
  section) — protection coverage is broad; treat all of `artifacts/runtime/` and retained
  CONTEXT bytes as protected unless a record says otherwise.

## Validation of preservation itself

- Fresh documentation/source-preservation validation: `docs/handoff/2026-10-17/validation.md`
  (independent of native acceptance).
- Historical protections + record hashes: `previous-EVIDENCE_INDEX.md`,
  `evidence-hashes.json`, `docs/specs/openttd-offline-evidence-baseline-1.json`.
