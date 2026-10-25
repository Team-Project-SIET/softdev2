---
title: "Evidence Preservation"
type: evidence
status: current
updated: 2026-10-25
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
authoritative, not in the candidate manifest). Because cleanup aborted before
workspace closure, the isolated operational credential remains under the
`0700` candidate workspace (`isolated/openttd-15.3-aghwu0j0/secrets.cfg`); its
value is never copied into records. Removing or rotating it is separate
operator remediation and must not rewrite the retained cleanup evidence.

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
