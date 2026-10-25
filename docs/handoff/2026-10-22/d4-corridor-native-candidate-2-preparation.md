# D4 Native Road & Station Construction — fresh candidate-2 staging handoff

Status: **D4 STAGED — one fresh candidate `D4-CORRIDOR-2` at
`artifacts/experiments/d4-corridor-native-candidate-2/`, `PENDING_AUTHORIZATION`;
`PRELAUNCH PASS` + read-only `PREFLIGHT PASS`; no claim written, nothing
launched, no tile changed**

Predecessor records:
[d4-corridor-option-c-implementation-review.md](d4-corridor-option-c-implementation-review.md)
(E23, `PASS WITH CONCERNS`, review-cleared fresh staging),
[d4-corridor-native-candidate-1-outcome.md](d4-corridor-native-candidate-1-outcome.md)
(E21 consumed attempt close-out) and
[d3-terraform-native-candidate-1-outcome.md](d3-terraform-native-candidate-1-outcome.md)
(receipt-bound after.sav `fbebef54…d59e` — the authoritative verified post-D3
world).

This document closes the D4 **preparation** step for the approved Option C
restage (ADR-011): the eight-operation schedule is staged as one fresh
save-load candidate whose source world is the receipt-verified D3 output,
reusing the proven D2/D3 one-launch machinery exactly (operator authorization,
runtime freeze, dependency identity, immutable launch environment, one-shot
claim, signed replay, cleanup boundaries), parameterized at call time. No
second security framework exists.

Nothing in staging launched OpenTTD, connected to any port, mutated any tile,
or wrote a claim. No Git stage/commit/push/reset/clean/stash was performed.

## 1. The staged candidate at a glance

| Fact | Value |
| --- | --- |
| Candidate directory | `artifacts/experiments/d4-corridor-native-candidate-2/` (new directory, created `exist_ok=False`; no existing candidate touched) |
| Attempt | `D4-CORRIDOR-2` (one attempt, milestone `D4-CONSTRUCTION`, kind `corridor`) |
| Prelaunch schema | `d4-corridor-native-prelaunch-v1` |
| Prelaunch seal (PRELAUNCH.json sha-256) | `de0e16f73d71efbad636271217a4981b4e6350412184bdbdfa17533e3d304f00` |
| Source world mode | `PREREQUISITE_ATTEMPT_SOURCE_SAVE_LOAD` |
| Source save | the consumed D3-TERRAFORMING-1 attempt's `after.sav`, sha-256 **`fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e`** (re-verified unchanged before staging; the distinct `after-diagnostic.sav` remains never a substitute) |
| Prerequisite record | `d4-native-prerequisite-attempt-v1`: attempt `D3-TERRAFORMING-1`, replay-verified, chain `… → D3-CLEARING-2 → D3-CLEARING-1` |
| Welcome (must match at execution) | revision `15.3`, seed `17`, landscape `0`, 256×256, `start_day 712223` |
| Company | 0 (authorized company for every op) |
| Plan digest | `2a30e95048e89ffa1420e0ae392b79f4d051f447d7a15a3edb896b4bbdcabb3a` (the v2 digest `2a30e950…cabb3a` named in E23 §4) |
| Schedule version | **2** |
| Budgets | 1 launch, 1 connection, **25 planned requests** (8 ops × 3 exchanges + 1 route read), request budget **31**, 8 road ops, 0 retries/reconnects, readiness 45 s, request 10 s, total 900 s, response bound ≤ 640 B, request bound ≤ 512 B, gsadmin 1450 B |
| Per-op cost ceiling | `MAX_CORRIDOR_COST = 2000` (£2,000), unchanged; **no aggregate phase budget** (the £16,000 worst-case figure remains an exposure bound, not a budget) |
| Authorization | `PENDING — requires ONE fresh operator authorization after all preflight gates; no authorization file exists and no claim exists` |
| Execution command (after authorization) | `.venv/bin/python -m app.simulation.openttd.proof.corridor_construction_native run artifacts/experiments/d4-corridor-native-candidate-2` |

## 2. The staged corridor schedule (v2, eight operations)

Derived offline by `corridor_schedule()` from the same pinned compiled facts;
verified against the staged `PRELAUNCH.json` byte-for-byte:

| Index | Operation | Pins (derived + asserted) |
| --- | --- | --- |
| 0 | `full` run A | `45747 → 45743`, run length 5 |
| 1 | `full` run-B segment 1 | `45999 → 48047`, run length 9 |
| 2 | `full` run-B segment 2 | `48303 → 50095`, run length 8 |
| 3 | `road` interior join | `48047 ↔ 48303` |
| 4 | `road` corner join | `45743 ↔ 45999` |
| 5 | `station` pickup | tile `45748`, front `45747` |
| 6 | `station` delivery | tile `50351`, front `50095` |
| 7 | `depot` | tile `45487`, front `45743`, orientation `south` |

## 3. The attempt-identity decision (operator-approved)

The staging module pinned `CORRIDOR_ATTEMPT = "D4-CORRIDOR-1"` — the identity
of the already-consumed candidate (E21), which the project's rules forbid
retrying. Per explicit operator approval of 2026-10-22 (the recommended
option), the single module constant was changed **before staging** to
`CORRIDOR_ATTEMPT = "D4-CORRIDOR-2"` so the fresh candidate carries a
never-consumed identity:

- The edit is one line in
  `app/simulation/openttd/proof/corridor_construction_native.py:147`. No other
  source, test or package byte changed for this preparation.
- The full focused suites, ruff, compileall and `git diff --check` were
  re-run after the edit (below) — 55/55 PASS, clean.
- The consumed candidate `D4-CORRIDOR-1` retains its own identity, seal,
  frozen closure and one-shot consumed claim, untouched. Its frozen closure is
  stale by design and is never edited or reused.

## 4. Live-repository verification before staging

- Repository `/home/fed/codes/softdev2`, branch `devmodule2`, HEAD
  `f5d2f1e4a8557ea7c93964dc758f7a22c7be4b5c` (unchanged throughout this
  session; the tree is intentionally dirty with the E22/E23 work).
- `mise.toml` verifies clean against HEAD — consistent with the operator's
  clarification (they removed `bun = "latest"` themselves; it was not
  restored). See §10 of the review record.
- Consumed `D4-CORRIDOR-1`: 28/28 manifest entries re-verified OK
  (read-only `sha256sum -c`) both before and after this staging session.
- D2/D3 evidence: `d2-clearing-native-candidate-3` 26/26 OK,
  `d3-clearing-native-candidate-1` 26/26 OK, `-2` 26/26 OK,
  `d3-terraform-native-candidate-1` 385/385 OK; pinned after.sav re-reads
  `fbebef54…d59e`.
- Vault source-doc copies `CONTEXT.md`, `EVIDENCE_INDEX.md`, `TASKS.md`
  byte-equal to their roots before the update below.

## 5. Offline validation performed

| Check | Command | Result |
| --- | --- | --- |
| Focused suites (after the identity edit) | `.venv/bin/python -m pytest tests/test_corridor_construction.py tests/test_corridor_construction_native.py` | exit 0; **55 tests** (wire 23 + native 32), all pass, 0 skipped — the clicked-through dots are suppressed by the in-process Squirrel driver, exactly as recorded in E22/E23; both consumed-artifact replay regressions ran against untouched `D4-CORRIDOR-1` and still return the preserved-halt verdict under the v1 selector |
| Lint | `.venv/bin/python -m ruff check` (module + both test files) | exit 0, "All checks passed!" |
| Byte-compile | `.venv/bin/python -m compileall` (module + both test files) | exit 0, clean |
| Whitespace hygiene | `git diff --check` | exit 0, clean |
| Staging | `.venv/bin/python -m app.simulation.openttd.proof.corridor_construction_native prepare artifacts/experiments/d4-corridor-native-candidate-2` | exit 0, **`PRELAUNCH PASS`** (staging + offline launch-boundary rehearsal in one step) |
| Standalone read-only preflight | `.venv/bin/python -m app.simulation.openttd.proof.corridor_construction_native preflight artifacts/experiments/d4-corridor-native-candidate-2` | exit 0, **`PREFLIGHT PASS`** |

The preflight gates are the documented D4 lineage set: prelaunch seal intact;
claim absent; schema the D4 corridor lineage; the full frozen source closure +
D2 runtime closure + installed dependency inventory byte-verified against the
candidate's recorded freeze (including the staged `source.sav` and the
staged `info.nut`/`main.nut` composition); staged schedule/plan-digest/route
equality with the compiled v2 derivation; site-front adjacency; the
prerequisite binding equal to a live re-verification of the retained D3
attempt (claim consumed, receipt replay-verified under the production
operator anchor, after-save digest `fbebef54…d59e`); expected welcome equal to
the retained facts; workspace ownership and the key's permissions; backend
preflight gates (pinned binary digest, exclusive runtime — no matching
process); endpoint reservation reallocated-and-released.

## 6. Freshness guarantees

- The destination directory did not exist and was created with
  `exist_ok=False` — an overwrite of any existing candidate is impossible by
  construction.
- The attempt identity `D4-CORRIDOR-2` has never appeared in any staged,
  consumed or retained record (the only prior D4 attempt is `D4-CORRIDOR-1`).
- The consumed candidate `artifacts/experiments/d4-corridor-native-candidate-1/`
  was never opened for writing, never edited, regenerated, reused or deleted;
  its manifest re-verified 28/28 after staging.
- The fresh candidate freezes the current reviewed source bytes (including the
  approved one-constant identity edit and whole-block fresh closure, staged
  `source.sav`, staged `.nut` composition, workspace config and works).

## 7. Authorization posture — what remains for the operator

1. The candidate is `PENDING_AUTHORIZATION` only; no `AUTHORIZATION.json`
   exists and no `CLAIM.json` may be created by anything but the runner after
   an operator record verifies. Attempt identity `D4-CORRIDOR-2`, milestone
   `D4-CONSTRUCTION`, one launch / zero retries, the entire budget table, the
   eight-op schedule with plan digest `2a30e950…cabb3a`, the sealed source
   world (`fbebef54…d59e`) and the expected welcome are all bound by the
   staged prelaunch record and its digest `de0e16f7…04f00` and the
   rebuildable authorization payload (`staged_authorization_payload_digest`).
2. The authorization payload binds `max_cost`, the full ordered
   `operation_schedule` and `plan_digest` additively (per E23 §7 finding 3 the
   `schedule_version` number itself is not a signed key; the version's only
   role is choosing the derivation, and the record's schedule/digest must
   equal that derivation at preflight and verify).
3. After ONE fresh explicit operator authorization, the `run` command executes
   the one ceremony: claim consumption, one launch, one encrypted connection,
   the eight scheduled ops (phase halts prefix-preserving on any failure),
   then the route read, retained receipt, cleanup and replay verification —
   exit 0 only if everything verifies.

## 8. Honesty and limits

- **Nothing ran.** No OpenTTD process, no AdminPort connection, no save
  mutation; the only filesystem writes are the candidate's own staging
  directory and this/documentation files plus the E24 evidence-index update
  (the E24 rows written immediately after this record in the root
  `EVIDENCE_INDEX.md` and its byte-verified vault copy
  `OpenTTD-Knowledge/99-Source-Documents/EVIDENCE_INDEX.md`).
- **No native quotes exist for the new schedule.** Every op is quoted natively
  at its own admission inside a future authorized run; a zero-cost native
  refusal stays terminal. The historical £2,549/£785 quotes are controlled
  references of the consumed attempt only.
- **Strictly the staged schedule.** The staged evidence covers exactly the
  eight bounded ops and the route read; no demolition/terraforming commands
  exist in the handler by construction.
- **Milestone D4 remains `INCOMPLETE (native)`.** Controlled staging never
  upgrades a project status.
- The verified `op-00` prefix of the consumed attempt is evidence, not a
  shortcut; the fresh candidate starts from the receipt-bound D3 after-save
  through its own save-load session.
- The one report button is the operator's. This handoff records staged facts
  and offline verification only; it does not authorize, attribute, promise or
  simulate any future launch.

## 9. Correction note (2026-10-22, later the same day — recorded, not silent)

A follow-up documentation session applied three corrections to this record and
recorded the full read-only payload verification durably in
[payload-verification](d4-corridor-native-candidate-2-payload-verification.md)
(external link: `docs/handoff/2026-10-22/d4-corridor-native-candidate-2-payload-verification.md`):

1. **§7.1 seal shorthand corrected.** "its digest `de0e16f7…2bf00`" used a
   wrong abbreviated tail; the verified seal bytes end `…04f00` (full seal
   `de0e16f73d71efbad636271217a4981b4e6350412184bdbdfa17533e3d304f00`, already
   correct in §1 of this record and in the staged `PRELAUNCH.sha256`). The
   same shorthand in other active notes was corrected the same day.
2. **§8 dangling phrase fixed.** The original §8 text "plus the evidence-index
   update below" pointed at a section that does not exist; §8 now names the
   actual evidence — the E24 rows written immediately after this record in the
   root `EVIDENCE_INDEX.md` and its byte-verified vault copy.
3. **§7.2 duplicated clause removed.** "the `schedule_version` number itself
   is not a signed key;" appeared twice in one sentence.
4. **Review-package durability.** The earlier payload-review's operator-review
   package was never stored as a durable repository file (exact §8/§9 wording
   UNKNOWN, not reconstructed); the verification record is its durable
   substitute, including the finding that
   `OpenTTD-Knowledge/05-Planning/Next Actions.md` was written by that review
   session (single write 19:39:21) and its exact pre-session bytes are
   UNKNOWN — "all pre-existing files preserved byte-for-byte" holds only when
   scoped to except those documentation writes.
