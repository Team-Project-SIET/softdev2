---
title: "Evidence Preservation"
type: evidence
status: current
updated: 2026-10-22
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

## The CONTEXT.md authority-pin conflict (open, preserved)

Retained authority manifests pin **repo-root `CONTEXT.md` bytes as captured 2026-10-08**
(sha256 `b94b966…`): two `historical-integrity.json` freezes (attempt1, prelaunch-v4) and
the `structural-world-real-prelaunch` `source-freeze.json`. Since commit `bdbec43`
(2026-10-11) the file has moved past that capture, so:

- the two protected-authority tests and
- `test_industry_production_proof::test_architecture_authority_unchanged`

fail at baseline, independent of any new work. The 2026-10-18 header addendum to
CONTEXT.md is prepend-only, lives in the working tree, is explicitly **not** part of any
documentation commit, and is duplicate-recorded in [[99-Source-Documents/AI_HANDOFF]] so
it is not lost. Resolving the conflict (pin-repair or re-capture) is a **separate,
explicitly authorized decision** — do not "fix" it by editing bytes or tests.

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
