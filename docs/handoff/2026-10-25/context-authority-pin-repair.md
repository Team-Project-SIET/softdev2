# CONTEXT.md authority-pin repair — explicit re-capture (ADR-014)

Status: **REPAIRED (offline).** The 2026-10-08 historical pin stays frozen and
unmodified; one operator-authorized, byte-exact supersession record now scopes
the transition to the current canonical `CONTEXT.md`. All other protected
entries remain byte-exact. No native action, no signing, no candidate
consumption.

## 1. Defect

Three baseline checks failed because retained protection manifests pin
`CONTEXT.md` to sha-256 `b94b96649b466e73e25c9df9409bd745e311b84273bedfd9a111792869e3b7b3`
(captured 2026-10-08), while the live file is
`36648f9c2fee4106efb35ae4ee8722983ebdfb482889e66ad53d759f6fa7cc29`:

- `tests/test_proof_endpoints.py::test_protected_history_and_context_exact`
- `tests/test_qualification_dispatch_repair.py::test_protected_historical_authority_remains_exact[CONTEXT.md]`
- `tests/test_industry_production_proof.py::test_architecture_authority_unchanged`

The historical bytes are **not retained**: they are in neither reachable Git
history (`bdbec43:CONTEXT.md` is `98f860…`, `4c633fa:CONTEXT.md` is `36648f…`)
nor repository artifacts. No claim that the historical bytes are recoverable is
made.

## 2. Authorized decision

Explicit operator authorization was given in this session (2026-10-25) for an
explicit pin repair, recorded as **ADR-014**. The repair:

- keeps every retained manifest and protected artifact byte-unchanged;
- adds `docs/authority/context-authority-supersession.json`, binding exactly
  one path, the historical digest `b94b966…`, the successor digest `36648f…`,
  `historical_bytes_retained: false`, and the authorizing decision;
- adds a fail-closed validator
  `app/simulation/openttd/proof/authority_supersession.py` that first verifies
  the frozen manifest's own digest, then substitutes **only** the recorded
  path/digest pair, and delegates every other entry to the unmodified
  `validate_protection` contract;
- updates the three checks to use that wrapper / resolver.

The base `validate_protection` is unchanged and still rejects the diverged
`CONTEXT.md` without the supersession (covered by a regression test), so the
repair does not weaken historical protection.

## 3. Files changed

| Path | Change |
| --- | --- |
| `docs/authority/context-authority-supersession.json` | new authority record (ADR-014) |
| `app/simulation/openttd/proof/authority_supersession.py` | new fail-closed validator |
| `tests/test_authority_supersession.py` | new focused tests (8) |
| `tests/test_proof_endpoints.py` | protected check uses the wrapper |
| `tests/test_qualification_dispatch_repair.py` | CONTEXT row resolved through the record |
| `tests/test_industry_production_proof.py` | architecture check resolves the historical pin |

## 4. Validation

- Focused: 7 new authority tests + the three repaired checks — 16/16 PASS.
- Broader: `test_historical_protection.py`, `test_qualification_dispatch_repair.py`,
  `test_industry_production_proof.py`, `test_proof_endpoints.py` — all PASS.
- Full suite: see the session report; the three baseline failures are gone.
- D4 candidate-2 preflight was re-run read-only and **failed** for an unrelated,
  pre-existing reason: its frozen closure predates the post-staging ADR-012/013
  edits to `app/planning/p08_v2_snapshot.py` and
  `app/simulation/openttd/v2_semantic_reconciliation.py`. See
  `d4-corridor-native-candidate-3-preparation.md`; candidate-2 was not edited.

## 5. Honesty and limits

- This is offline documentation/authority repair, not native evidence.
- The historical pin remains historical: its bytes are UNKNOWN on this machine.
- No Git stage/commit/push/reset/clean/stash; no launch; no AdminPort; no
  authorization or claim created or consumed.
