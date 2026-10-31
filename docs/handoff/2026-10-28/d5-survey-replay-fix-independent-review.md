# Review: D5 survey replay "retained receipt" fix (fresh-eyes, post-attempt)

- Scope: `app/simulation/openttd/proof/corridor_accept_survey_native.py` (run arm receipt write vs. replay arm receipt comparison) and the three replay tests in `tests/test_corridor_accept_survey_native.py`.
- All 25 tests in `tests/test_corridor_accept_survey_native.py` pass locally (`pytest -q` → 25/25), including the three targeted replay tests (`replay_verifies_a_fully_consumed_survey_frame_sequence`, `replay_fails_closed_on_a_tampered_retained_receipt`, `replay_fails_closed_on_tampered_retained_census_findings`).

## What the fix does (verified)

Run arm writes `receipt.json` flat (lines 1056–1065):

```python
write_json(directory / "receipt.json", dict(phase, before_save_sha256=..., census_findings=compare_census_findings(...)))
```

Replay arm (lines 1479–1495):
- iterates **every key of the recomputed phase** and requires `name in retained_receipt and retained_receipt[name] == replay_phase[name]` (1486–1490). Both the written shape (`dict(phase, ...)`) and the compared key set (`for name in replay_phase`) derive from the *same* production `survey_phase_outcome` (contract module lines 554–571), so a key added to or removed from the phase outcome automatically syncs both sides — no silent divergence in either direction for phase keys.
- `replay_phase = json.loads(json.dumps(phase))` (1482) round-trips tuples/lists (e.g. `observation_kinds` is a tuple at contract module line 414; `receipts` holds tuples) — the commodity/mixed-container equality is handled correctly and semantics, not container type, define the match, mirroring the freight precedent (`corridor_freight_native.py:1895–1898`).
- `census_findings` is genuinely **re-derived** from the re-derived `phase["observations"]` (1491–1493; identical derivation at 1474–1476 for the verdict), never copied from the receipt, and refused if unequal (1494–1495).

Fail-closed posture is preserved:
- The receipt arm sits *inside* the `SURVEY_COMPLETION_VERIFIED` branch, which requires: re-derived `phase["verification"] == "SURVEY_COMPLETE"` from retained frames (1457), no halt + `command_accepted` (1459), exact launch/connection seal (1461–1465), 8 exchanges + certified cleanup (1466), `state_changed` false (1468), 8 outbound requests (1470), re-derived observations present (1472), and clean result flags (1477). Nothing in the receipt comparison can promote a refused/missing/malformed/stale attempt to verified; a receipt mismatch *raises* (never downgrades to incomplete — matching the fail-closed intent).
- Missing/malformed receipt in a real run is still refused via the exhaustive artifact-manifest check (1302–1316). Halting paths refuse incomplete cleanup (1524–1525).

## Findings

### Minor

1. **`before_save_sha256` is written into the receipt but never compared in replay — one key outside the sync mechanism.** `corridor_accept_survey_native.py:1056–1065` writes it flat alongside the phase keys; the replay comparison (1486–1490) iterates `replay_phase` keys only, so this key's value is never checked, and neither `session-before.sav` nor `session-before-identity.json` appears anywhere in `verify_survey_attempt` (grep: no `session-before`/`before_save` reference in the replay function). The printed verdict (1496–1502) also omits it. Contrast the sibling ceremony this file imports everything else from: `corridor_freight_native.py:1885–1898` re-derives *the entire written shape* as `expected = dict(phase, cycle=..., before_save_sha256=sha256(snapshot of `session-before.sav`), after_save_sha256=...)` and compares whole-dict equality — every written key is compared, including the before-save digest. The survey arm silently diverges from its own pattern for exactly this one key: rewriting `before_save_sha256` in `receipt.json` (plus re-signing the manifest) is never refused, while the module docstring claims replay re-derives "every retained fact independently" (1277–1279). This is an evidence-integrity gap, not an acceptance-predicate gap (a halted/stale attempt still refuses; the phase comparison is unaffected), so I rank it minor rather than material.
   - Narrowest remediation: in the `SURVEY_COMPLETION_VERIFIED` branch, add `if retained_receipt.get("before_save_sha256") != sha256(directory / "session-before.sav"): raise ValueError(...)`, mirroring `corridor_freight_native.py:1891`.

2. **No explicit "receipt missing" guard on the verified arm.** The comparison is gated on `if receipt_path.is_file():` (1480); a completed attempt with `receipt.json` deleted skips the whole receipt arm and still verifies. Today it is masked by the exhaustive-manifest invariant (a real completed run includes `receipt.json` in the manifest, so deletion trips "artifact manifest mismatch" at 1305), but the structural guard the freight twin has ("verified receipt record missing", `corridor_freight_native.py:1886–1887`) is absent here. If the manifest check ever changes shape or a manifest entry set is regenerated by a forger, the deletion becomes silent.
   - Narrowest remediation: change 1480 to `else: raise ValueError("verified receipt record missing")` (keep the manifest check; the explicit guard removes the hidden dependency).

3. **Replayed census hypotheses are not re-pinned to the retained census bytes.** Preflight pins every staged hypothesis row against the retained facts (`corridor_accept_survey_native.py:713–720`), but `verify_survey_attempt_identity` only checks that the hypothesis record is a dict containing a `"state"` key (1268–1270), and `compare_census_findings` in replay consumes `policy_replay["hypotheses"]` (1474–1476, 1491–1493) straight from the sealed metadata. A tampered hypothesis row (same `state`, different `hypothesis_acceptance_eighths`) plus suitably re-derived `census_findings` and a re-signed manifest passes every replay check; the divergence-hiding/forgery is only caught by a later preflight. This weakens the point of the tampered-census-findings refusal: the *expected* findings themselves are computed against an unpinned input.
   - Narrowest remediation: in `verify_survey_attempt_identity`, mirror preflight — for each staged row, `if row != census_hypotheses()["hypotheses"][row["observation_index"]]: raise ValueError(...)` (factoring the preflight loop into a helper used by both).

### Observation

4. **Duplicate re-derivation of census findings.** Lines 1474–1476 and 1491–1493 compute the identical expected findings twice inside one branch. Harmless but redundant; one variable would read better and remove any chance of the two drifting apart later.
5. **Extra keys in the retained receipt are accepted.** The comparison requires every recomputed phase key to be present and equal (1486–1490) but does not refuse unknown additional keys, so the receipt is compared only as a superset of the written shape, not as exact identity as freight does (whole-dict equality, `corridor_freight_native.py:1897`). Consequence-free today (the extra keys written are the two known ones and the census one is compared).
6. **Test-hygiene:** `test_replay_fails_closed_on_tampered_retained_census_findings` (781–791) doesn't restore `receipt.json` inside the test (the tampered state persists for the rest of the module fixture's lifetime). Harmless because it is currently the last test in the module run against that fixture, but a test appended after it would silently inherit a poisoned receipt.
7. **Test coverage is adequate for the fix:** the synthetic fixture writes the receipt in exactly the produced flat shape (lines 665–678, with a snapshot `session-before.sav`), the tampered-receipt test exercises a *phase value* mismatch (`production=105`, caught by the phase-key comparison), and the census test exercises findings mismatch. There is no test for a receipt **missing a phase key** (the `name not in retained_receipt` branch, 1486–1489) or for the missing-receipt case — cheap additions alongside findability remediating item 2.

## Predicate audit (no acceptance loosening)

- Forced/invented `SURVEY_COMPLETE` labels alone cannot verify: receipt verification is only reachable after the fully re-derived phase is complete (1457–1478), and the acceptance scan covers stale (response ordering 1412–1414), duplicate (1383–1387, 1406–1407), malformed (1393–1404), missing (1409–1411), refusal (via `survey_phase_outcome` verdicts), and inventiveness (manifest exhaustive check 1315–1316). The receipt fix only compares *more* strictly than before: it never returns success that the phase re-derivation didn't already establish, and it converts receipt divergence into a hard `ValueError` rather than a downgrade.

## Verdict

MATERIAL DEFECT: no
- No material defect found. Minor findings 1–3 above with narrow remediations as written; none of them accepts a refused/missing/malformed/stale exchange or a forced success label.
