# D4 Native Road & Station Construction — close-out handoff

Status: **D4-CORRIDOR-1 CONSUMED ONE TIME — phase ended
`PHASE_HALTED_PREFIX_PRESERVED`; only `op-00` is a verified prefix operation;
Milestone D4 remains INCOMPLETE. The original halted result stays
`verified: false`, the read-only replay verifier was repaired offline, and the
retained evidence is preserved byte-for-byte (manifest re-verified)**

Predecessor records:
[d4-corridor-native-candidate-1-preparation.md](d4-corridor-native-candidate-1-preparation.md)
("stage handoff: one candidate `D4-CORRIDOR-1`, `PENDING_AUTHORIZATION`") and
[d3-terraform-native-candidate-1-outcome.md](d3-terraform-native-candidate-1-outcome.md)
("receipt-bound after.sav `fbebef54…d59e` — the verified post-D3 source world").
This document closes the preparation record for the **consumed attempt**: the
candidate's one-shot claim was consumed under an operator authorization and
the corridor ceremony executed, halting prefix-preserving at `op-01`. Nothing
after that first halt was executed, relabeled, retried or compensated, and a
subsequent offline session repaired the read-only replay verifier (two
locations) with regression tests, reviewed independently as
`PASS WITH CONCERNS`.

This close-out is **documentation only**. It modified no source file, no test,
no candidate artifact, no retained evidence file, no save, no frozen authority
pin and no `CONTEXT.md`; it performed no Git stage/commit/push/reset/clean/
stash; it launched no OpenTTD process and connected to no port; it created or
consumed no authorization/claim record and signed nothing; and it staged no
fresh candidate.

## 1. What happened — factual record

| Time (observed file mtimes, 2026-10-22) | Event |
| --- | --- |
| 10:35 | Candidate staged and prelaunched per the staging handoff (`PRELAUNCH.json`/`PRELAUNCH.sha256`, isolated frozen workspace). |
| 12:08 | `AUTHORIZATION.json` present in the candidate directory. |
| 12:09 | Attempt consumed: `CLAIM.json` written (`consumed: true`, zero retries), one launch/one encrypted connection, four exchanges, `PHASE_HALTED_PREFIX_PRESERVED` at `op-01`, cleanup complete. |
| later (offline) | Two-locus replay-verifier repair + three regression tests; independent offline review `PASS WITH CONCERNS`; read-only post-repair replay reproduces the preserved-halt verdict. |

Who carried out the launch is not asserted by this document; the retained
authorization record binds the attempt the same way every consumed D2/D3
attempt does (claim `prelaunch_digest` = the staged seal, operator key identity
`cbb63ff5…ae40c614`). The session writing this record initiated no launch and
performed only read-only checks, the offline verifier repair, and its tests.

## 2. The consumed attempt at a glance

| Fact | Value |
| --- | --- |
| Candidate directory | `artifacts/experiments/d4-corridor-native-candidate-1/` |
| Attempt | `D4-CORRIDOR-1` (milestone `D4-CONSTRUCTION`, kind `corridor`) |
| Prelaunch seal | `0b000d68852aac75504a0c16fb65807051d6f52dfccb6ea99de29a230781a18f` |
| Plan digest | `3bf3eddffa807cca2bde279425332d5079a025dec3b1dabe7114164822d8a912` |
| Source world | D3-TERRAFORMING-1 `after.sav`, `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e` (unchanged) |
| One-shot claim | consumed, `launches_allowed: 1`, `retries: 0`, authorization sha `ed292a7c4eef0d171ac7f775d0444e5492ba8737e12b5d94cb5cc718653030e2` under the production operator anchor |
| Session identity | 1 launch / 1 connection, encrypted X25519, revision `15.3`, seed `17`, landscape `0`, 256×256, `start_day 712223` (pid 29669; ports 43823/40993) |
| Result | `status: "PHASE_HALTED_PREFIX_PRESERVED"`, **`verified: false`**, `returncode: 0`, **4 requests** of 19 planned, 1 launch, 1 connection, 0 retries/reconnects |
| Requests retained | `inspect-00`, `full-00`, `confirm-00`, `inspect-01` — with their response pairs and the complete session frame stream (`frames.json`) |
| Halt record | `{"label": "op-01", "error": "ValueError: native READY admission with positive tested cost required"}` |
| Cleanup | process reaped (returncode 0), sockets closed, credential removed, workspace disposed, endpoints certified (TIME_WAIT kernel rows only); no script-log health findings retained |
| Receipt record | none — `receipt.json` does not exist; no `PHASE_COMPLETE` was reached and no route read was performed |

Runtime narration (retained `stderr.log`): `D4_READY` and the company AI
readiness markers, the admin client `D4-CORRIDOR-1` connecting and
authenticating, then `inspect-00 READY → full-00 BUILT → confirm-00 READ →
inspect-01 COST_LIMIT`, followed by disconnect and a clean shutdown. The
`[W] Save function is not implemented` lines are the known benign saved-script
warning (E15), with the scripts alive at every save; nothing died.

## 3. The executed schedule — verified prefix, refused op, pending ops

| Op | Kind | Pins | State at halt | Evidence |
| --- | --- | --- | --- | --- |
| 0 | `full` | start 45747 → end 45743, run length 5 | **EXECUTED AND VERIFIED** — `BUILT` then independent `READ` | the only verified receipt |
| 1 | `full` | start 45999 → end 50095, run length 17 | **REFUSED AT ADMISSION** — native quote £2,549 > £2,000 per-op ceiling (`inspect-01` returned `COST_LIMIT`) | no native command was issued for `op-01` |
| 2–5 | `road`, `station`, `station`, `depot` | compiled schedule | **NOT EXECUTED** | no requests, no evidence files |
| route read | `route` | 24-tile witness | **NEVER SCHEDULED** — the phase did not complete | no `route-00` exchange exists |

`op-00` verified prefix, recomputable from the retained exchange documents:

- `inspect-00` (prelaunch seal as plan): `READY`, both endpoints unowned
  (`owner0/1 = −1`) and roadless, covered 0, `pairs_ok 0`, staged `run_len 5`,
  positive tested quote **£785** within the £2,000 ceiling, funds £496,543
  (the D3 final balance, unchanged).
- `full-00` (prelaunch seal as plan, no target): `BUILT`, cost equal to the
  quote (£785), funds £496,543 → **£495,758**, both endpoints company-owned
  (`owner0/1 = 0`) with road on both, covered 5, `pairs_ok 4`.
- `confirm-00` (independent read, plan = the admitted intent digest
  `96cfbaf3a728db096090465e9b2bd9c2ab1eadb202e229ee468cb8c64349efec`): `READ`
  with the identical post-state and funds — same owners, road flags, run
  summary, and funds as `full-00`.
- Receipt (relabel-free, part of the retained `result.json` phase record):
  `company-corridor-receipt-v1` for `op-00` — intent
  `96cfbaf3…9efec`, before
  `a33ff798b74bce67232cd61c36356fc8efa3e8118b9000409f71771ffcae3794`,
  construction
  `678076842ef8627785168f15c295a51e634e25b6df55452336e406ade5418095`, after
  `12d7aeb806a280747a2e0204ab98a94b7572e82a75b654e49c46ae812f832a24`,
  `verification: NATIVE_STATE_CHANGED`.
- Retained intent
  (`corridor-00-intent.json`): kind `full`, pins 45747→45743, `run_len 5`,
  binding seal `0b000d68…` and the session-before save
  `e3d352b53cfb2362adf99f915ce66157cebd6a174dfa6076e72ca4b8d20d513c`.

After `op-00` the verified finance position is **£496,543 → £495,758**
(£500,000 D2 start − £3,457 D3 − £785 D4 `op-00`), confirmed by the `confirm-00`
and `inspect-01` readback funds. No later state change is evidenced because no
later operation executed.

## 4. What the halt preserves — and what it does not

- The one-shot claim is consumed; this attempt can never launch again, and no
  evidence was relabeled or re-run. `op-01` through the depot op remain
  unexecuted and unquoted (only `op-01`'s inspect-time quote is retained).
- The post-halt world state is **explicitly uncertain beyond the verified
  prefix**: the production phase vocabulary records
  `world_state: UNCERTAIN_AFTER_FAILED_COMMAND` for the halted attempt. For
  `op-01` specifically the retained request inventory proves no native command
  was issued (its wire exchange is the inspect refusal only), so the
  uncertainty attaches to everything the phase never executed, not to
  `op-01`'s tiles.
- **`after-diagnostic.sav` (sha
  `ff574308557b30073b3347e649886ccc6770d16bcf5b08093803f6ebf`) is not an
  authoritative receipt-bound save.** No `after.sav` exists, no `receipt.json`
  was written, and the diagnostic save is never a substitute for one — the
  same rule that governs the retained D3 diagnostic save.
- The overall D4 phase is **not successful**: the retained result says
  `PHASE_HALTED_PREFIX_PRESERVED` with `verified: false`, and the replay
  verifier (below) returns the halted-phase verdict, never a verified one, for
  this candidate.

## 5. The offline verifier repair (read-only replay path only)

The retained halted attempt exposed two defects in
`app/simulation/openttd/proof/corridor_construction_native.py`'s replay
verifier `verify_corridor_attempt`, which otherwise guarded faithfully and
which repairs were addressed offline; both are confined to the retained-evidence
replay path (no production execution or staging behavior changed):

1. **Admitted-intent binding.** The lint comparing an admitted intent to its
   staged entry now reads
   `if intent.kind != entry["kind"] or _pins(entry) != _pins(entry, intent=intent):`
   (the `_pins()` definition and its `_corridor_request()` call site are
   unchanged). The previous form passed the intent model itself where a staged
   entry dict is required, so replaying the retained attempt crashed with
   `TypeError: 'CorridorIntent' object is not subscriptable`.
2. **Retained evidence boundary.** Each per-op evidence file
   (`corridor-{pos}-{before,intent,built,independent}.json`) now parses on the
   retained bytes through pydantic's own JSON parser —
   `CorridorIntent.model_validate_json(path.read_bytes())` for intents and
   `CorridorReadback.model_validate_json(path.read_bytes())` for readbacks —
   matching the strict-contract conventions (`Contract` refuses raw text
   feeds) used by the D2/D3 retained-family parsing. The previous text-feed
   boundary could never validate a retained evidence file and silently dropped
   every readback it touched, masking the verified `op-00` prefix.

Regression coverage in `tests/test_corridor_construction_native.py` (26 → 29
tests, all passing; the companion wire suite `tests/test_corridor_construction.py`
stays 21 PASS):

- `test_verify_inputs_pin_contract_is_staged_entry_versus_admitted_intent` —
  the entry-versus-intent `_pins()` contract (equality, drift equality-refusal,
  entry-less call stays a `TypeError`), always runs.
- `test_retained_readback_evidence_parses_the_json_boundary_directly` — the
  retained JSON boundary (pretty file parses; the identical pretty document
  parses identically through `model_validate_json`; and the historical text
  feed is documented to fail), gated on the retained evidence.
- `test_retained_d4_attempt_replays_as_phase_halted_evidence_preserved` —
  reverts of either repair make this fail: with the old `_pins()` form the
  replay raises the `TypeError` above; with a text-feed parse the dropped
  readback evidence makes the recomputed phase fail at `op-00`, so the
  retained halt record contradicts and the replay raises. A review simulation
  of both reverts reproduced exactly those failure modes; with both repairs
  present the production verifier, driven read-only through the CLI
  (`python -m app.simulation.openttd.proof.corridor_construction_native verify
  artifacts/experiments/d4-corridor-native-candidate-1`), returns:

  ```json
  {"completed": ["full"], "error": "corridor attempt lacks retained execution evidence", "failed": {"error": "corridor attempt lacks retained execution evidence", "label": "op-01", "world_state": "UNCERTAIN_AFTER_FAILED_COMMAND"}, "pending": ["op-02", "op-03", "op-04", "op-05"], "result_status": "PHASE_HALTED_PREFIX_PRESERVED", "verification": "PHASE_HALTED_EVIDENCE_PRESERVED"}
  ```

  The production replay re-derives the phase from retained files (it does not
  trust `result.json`), so the verified `op-00` prefix is **re-verified** —
  admission, execution, independent readback and the receipt digests
  recomputed — while the overall phase stays the preserved-halt verdict.

## 6. Independent review verdict

An independent offline review of the repair (2026-10-22, before any fresh
candidate work) returned **`PASS WITH CONCERNS`**:

- **Confirmed correct**: both repairs are semantically correct, minimal and
  confined to the replay-verifier evidence path; the retained JSON parsing
  matches the project's strict-contract conventions exactly; the regression
  tests genuinely reproduce both original defects; the replay verifies only
  the retained `op-00` prefix and never misrepresents the phase as successful.
- **Optional concerns — improvements, not confirmed defects** (recorded as
  such, non-blocking):
  1. The two artifact-gated regression tests skip when the consumed candidate
     directory is absent (it is a gitignored retained artifact), so defect
     reproduction is conditional on that evidence being present; the
     always-on `_pins()` contract test remains.
  2. No executed coverage exists for the site-op (station/depot) branch of the
     pin comparison: the attempt halted before any site intent was admitted,
     and the `_pins()` contract test pins the road leg only.
- `ruff check` and `py_compile` clean on the staging module and the test
  module at close.

## 7. Evidence preservation

- All **28** retained candidate artifact hashes re-verified unchanged (2026-10-22,
  read-only `sha256sum -c` against the candidate's own
  `artifact-manifest.sha256`; zero mismatches).
- D2/D3 evidence stayed untouched: the consumed-attempt directories are
  unmodified, and the offline suites re-verified the pinned D3 bound
  (`after.sav` still `fbebef54…d59e`; the distinct D3 diagnostic save remains
  never a substitute). The pinned D4 source world is therefore still the
  verified post-D3 save.
- The close-out work itself is documentation-only (this file and the noted
  evidence-index entry); the review and test runs wrote nothing into the
  candidate directory or any retained artifact.

## 8. The frozen closure is stale by design — never edit or reuse it

The candidate's frozen closure (`PRELAUNCH.json` frozen set, staged 10:35)
pins the **pre-repair** verifier bytes staged at that time; the verifier
repair postdates staging, and no one may edit the frozen closure, re-sign it,
or relabel the candidate to make its freeze match current sources. The
candidate is consumed anyway (one-shot claim), and preflight refuses an
already-consumed candidate outright. **Any future D4 attempt requires a fresh
candidate regenerated from the current reviewed source** — staged, prelaunched
and preflighted from scratch under the existing machinery — never an edit of
this directory or its `PRELAUNCH.json`.

## 9. Remaining decisions — blockers for a future attempt

1. **Ceiling vs. scope for `op-01`.** The 17-tile run B was natively quoted
   **£2,549** at admission against the authorized **£2,000** per-operation
   ceiling — a positive native quote, not an engine refusal. Choose one
   before restaging: raise the per-operation cost ceiling for the road runs
   (re-signed authorization payload, same fail-closed admission) **or**
   rescope/split the 17-tile operation into bounded pieces inside the current
   ceiling. Either way the change is a staging-time decision, not a live
   override.
2. **Fresh native quotes for everything unexecuted.** `op-02` through `op-05`
   (corner, both stops, depot) have no native quote at all, and `op-01`'s
   retained £2,549 belonged to that attempt's world state — the fresh
   candidate's admission re-quotes every op natively (a zero-cost native
   refusal stays terminal), so historical costs remain controlled references,
   never authorization.
3. **A fresh reviewed candidate under the existing authorization rules.**
   Prepare a new candidate directory from current source (staging → prelaunch
   → read-only preflight), then the ONE fresh operator authorization, one-shot
   claim and the same bounded ceremony. The verified `op-00` prefix of this
   attempt is evidence, not a shortcut: the fresh candidate starts from the
   receipt-bound D3 after-save through its own save-load session.

**No fresh candidate has been staged and no new native attempt has been
authorized** as of this record; nothing in this close-out authorizes, prepares,
or schedules one.

## 10. Honesty and limits

- **Result never upgraded.** `verified: false` is retained as-is; the halted
  status, the refused op and the pending ops are recorded verbatim from
  `result.json` and the retained request/response files; nothing was relabeled
  or backfilled.
- **Exactly what the evidence shows.** Five road tiles company-owned,
  £785, independently re-read; one admission refusal; nothing else executed;
  no route, no stops, no depot exist as proved facts of this attempt.
- **D4 remains incomplete.** No service, delivery, OPEX, revenue or P07
  claim follows from this attempt; the corridor route scope was never
  observed.
- **Read-only close-out.** The only writes in producing this record are this
  file and the corresponding evidence-index entry.
