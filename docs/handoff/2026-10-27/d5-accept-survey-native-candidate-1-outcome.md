# D5-ACCEPT-SURVEY-1 — candidate-1 consumed outcome: verified read-only native acceptance survey

Status: **`D5-ACCEPT-SURVEY-1` CONSUMED EXACTLY ONCE under the operator
authorization record of this session's task brief (signing + exactly one
bounded read-only survey). The eight-exchange survey ran to completion on
OpenTTD 15.3 with zero world mutation, and the independent replay verifier
returned `SURVEY_COMPLETION_VERIFIED` with certified cleanup. Result
`verified: true`, `status: NATIVE_SURVEY_COMPLETE`, exit 0.**

Date: 2026-10-27. Predecessors:

- [Preparation record](../../../docs/d5-acceptance-survey-1-preparation.md)
  (§7: explicit authorization required to execute)
- [D5 freight candidate-1 outcome](d5-corridor-freight-native-candidate-1-outcome.md)
  (the accepted-0 finding of record this survey re-measures)
- [candidate-5 D4 outcome](../2026-10-26/d4-corridor-native-candidate-5-outcome.md)
  (source world)

## 1. What happened, in order

1. **State verification.** Branch `devmodule2`, HEAD
   `1e6d6c1…94a96f` = `origin/devmodule2`, unchanged end to end. The working
   tree's dirty set (`EVIDENCE_INDEX.md`, `.obsidian/workspace.json`,
   `TASKS.md` + mirror, the D5 freight files, the untracked survey docs/
   implementation/tests) matched the §5-reviewed bytes; the pre-existing
   Obsidian workspace modification was preserved untouched. `survey` 25/25 +
   `survey native` 22/22 re-ran PASS (47 tests) before staging.
2. **Staging.** Fresh candidate
   `artifacts/experiments/d5-accept-survey-native-candidate-1/` staged from
   the reviewed bytes: `PRELAUNCH PASS` at prepare, then an independent
   fresh `PREFLIGHT PASS`. Seal
   `38b7667ec03af932f7ed37cc6c03fbee901f44d09484a400abd6caf745aeb06b`,
   schema `d5-accept-survey-prelaunch-v1`, attempt `D5-ACCEPT-SURVEY-1`,
   plan bound to `AcceptSurveyPlan` only. Source world = the authoritative
   D4 candidate-5 after-save
   `a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261`
   (re-verified through the prerequisite binding), binary sha
   `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`
   (OpenTTD 15.3), budgets: 8 planned exchanges / 32-request cap /
   `max_cost 0` / 300 s total / 512-byte protocol-6 bounds, hypotheses
   rebound from the retained census (`HYPOTHESIS` rows only).
3. **Authorization.** Payload digest rebuilt offline via
   `staged_survey_authorization_payload_digest`:
   `dc8a9adf9a7d345758bb4a25fc1389befdaaf2b5181f6cfff8c163cd2da23d47`
   (matches the module helper and the canonical rebuild). Documented
   signing checklist executed: `AUTHORIZATION.json`/`CLAIM.json` absent,
   seed never printed, derived public key equal to the pinned production
   anchor `5063982b…4880f`, 64-byte signature self-verified under the
   maintained verifier **before** writing, `AUTHORIZATION.json` written
   (sha-256 `d6fb23e92aec8bc6c820ad19496c25ee07ddcb8e9a9efdc3c74c2e7b8d20fd8f`),
   `verify_authorization` PASS, operator identity
   `sha256-ed25519-public-key:cbb63ff5…40c614` (unchanged production
   anchor). No freight key reuse; scope = the survey-only payload.
4. **The one attempt.** `run` consumed the claim exactly once: 1 launch
   (pid 29823), 1 fully encrypted X25519 AdminPort connection, welcome
   identity matched exactly (`revision 15.3`, `seed 17`, `landscape 0`,
   `256×256`, `start_day 712223`), `session-before.sav` retained. All eight
   exchanges `READY`/`SURVEY_OBSERVED`, funds `£492,149` read back on every
   exchange, `state_changed: false`, no halt, no retries, request budget
   headroom untouched (8 of 32).
5. **Post-attempt code correction (fail-closed discovery).** The first
   replay `verify` run refused with `the retained survey receipt replay
   mismatch`, exit 1. Root cause: the run writes `receipt.json` flat
   (`dict(phase, before_save_sha256=…, census_findings=…)`) while the
   replay arm compared a nested `retained_receipt.get("phase")` key that
   never exists — the mixed-tuple/list equality also needed the JSON round
   trip. The refusal itself was correct fail-closed behavior (no predicate
   was weakened to pass). The comparison was fixed to compare exactly the
   written shape (every phase key present and equal, plus the retained
   `census_findings` re-derived and equal); regression tests added:
   synthetic fully-consumed eight-frame `SURVEY_COMPLETION_VERIFIED`
   replay, tampered-retained-receipt refusal, tampered-census-findings
   refusal. Module bytes therefore changed **after** staging and the
   attempt; the candidate's own frozen manifest and every staged binding
   were untouched and the replay re-derives its facts from retained
   candidate evidence only.
6. **Verified replay.** `verify` exit 0: `SURVEY_COMPLETION_VERIFIED`,
   radius 3, production 104, six observations, `census_findings` empty (no
   divergence from the pre-construction census), cleanup certified, no
   world change, launch seals 1/1.

## 2. The measured acceptance facts (verbatim)

| Exchange | Tile | Measured | Census hypothesis | Divergence |
|---|---|---|---|---|
| radius-00 | — | radius 3 | radius unmeasured before | new native fact |
| accept-00 (control) | 50351 | 0 | 0 | none |
| accept-01 | 50607 (175,197) | 8 | 8 | none |
| accept-02 | 50863 (175,198) | 8 | 8 | none |
| accept-03 | 51119 (175,199) | 8 | 8 | none |
| accept-04 | 51375 (175,200) | 8 | 8 | none |
| accept-05 | 50605 (173,197) | 8 | 8 | none |
| prod-00 | — | production 104 | 104 (E36 site readback) | none |

Key facts:

- **The native truck-stop coverage radius is 3**, not the assumed value —
  measured in the same world, first, per the schedule's radius-first rule.
- The control `50351` re-measured **0**, confirming the E36 finding of
  record (`D5-FREIGHT-1`'s delivery stop zero-acceptance) unchanged.
- All five candidate tiles measure **8 ≥ 1/8 under a radius-3 catchment**
  in the live 15.3 world — positive catchment only; NOT a stop, NOT a
  route, NOT a freight cycle. No candidate tile is claimed buildable.
- Funds read back `£492,149` on every exchange (the D4 close-out pin),
  `max_cost 0` everywhere, zero cost-bearing API use.
- `census_findings` is empty: measured zero (control) is structurally
  distinguished from refusal/missing by the contract, and every value
  matched its pinned hypothesis — a fact recorded, not a pass-rate.

## 3. Cleanup, mutation absence, and tree state

- `cleanup.json`: `reaped`, `sockets_closed`, `workspace_disposed`,
  `credential_removed` all true, `returncode 0`, no cleanup or
  verification error, endpoint probe closed, reservation released,
  `remaining_processes` empty. Post-run `pgrep`/`ss` re-check: no OpenTTD
  process and no AdminPort listener remain.
- Zero world mutation: every exchange is a read-only op under
  `max_cost 0`; the GameScript handler contains no accounting or mutation
  command; `state_changed` false is re-derived by replay; the authoritative
  source save and all historical artifacts were never written (the survey
  saves nothing itself; `session-before.sav`/`after-diagnostic.sav` are
  owned diagnostic copies inside the candidate).
- Git: branch and HEAD unchanged, nothing committed or pushed. New untracked
  paths: the candidate directory, this outcome record. Modified tracked
  paths: `docs/d5-acceptance-survey-1-preparation.md` (outcome section),
  `app/simulation/openttd/proof/corridor_accept_survey_native.py` and
  `tests/test_corridor_accept_survey_native.py` (the §1.5 post-attempt
  correction, no frozen candidate binding affected), `TASKS.md` and its
  byte-identical mirror. The pre-existing dirty set is otherwise preserved.
- Checks: survey 25/25 + survey-native 25/25 (122-letter suite: freight
  42/42, freight-native 55/55 also re-ran PASS as release), `ruff check`
  and `ruff format --check` clean on the touched files, `py_compile` clean,
  `git diff --check` clean, TASKS mirror `cmp` byte-identical.

## 4. What this unlocks / does NOT unlock

- The corridor-freight redesign now has native, same-world acceptance
  facts: a truck stop placed within radius 3 of any candidate tile expects
  cargo-1 acceptance 8, with the control re-pinned at 0. Radius 3 is the
  measured catchment the next placement design must respect.
- This consumed one candidate, one claim, one authorization and one
  launch. The next stage (route redesign / a new D5 freight attempt) needs
  a new plan, a new candidate and a NEW explicit authorization. Nothing
  here authorizes construction, vehicles, orders or delivery. The
  `D5-FREIGHT-1` and `D5-ACCEPT-SURVEY-1` identities stay consumed.
- Limitation of record: the replay receipt-arm fix (§1.5) executed after
  the attempt. The live attempt's own result (all eight `SURVEY_OBSERVED`
  receipts, funds readbacks, zero-cost halt capability unused) is
  independent of the fix; the replay verifier's refusal came from the
  receipt re-read arm only. Both the fix and its regression coverage are
  reviewed only by this session's self-review, not a third-party reviewer.
