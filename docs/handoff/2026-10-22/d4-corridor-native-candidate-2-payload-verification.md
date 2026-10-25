# D4 candidate-2 — read-only authorization-payload verification handoff

Status: **READ-ONLY VERIFICATION COMPLETE — this is not authorization and not
execution.** The staged fresh candidate `D4-CORRIDOR-2`
(`artifacts/experiments/d4-corridor-native-candidate-2/`) remains
**`PENDING_AUTHORIZATION`** and Milestone D4 remains **INCOMPLETE (native)**.
The private signing key was not accessed or used; nothing was signed; no
`AUTHORIZATION.json`, `CLAIM.json` or launch-consumption record was created,
modified or consumed; the frozen candidate, its manifest and its closure were
not modified or regenerated; OpenTTD was not launched and no AdminPort
connection was made; no Git stage/commit/push/reset/clean/stash was performed.

Predecessor records:
[d4-corridor-native-candidate-2-preparation.md](d4-corridor-native-candidate-2-preparation.md)
(E24 staging; the verified facts below all re-read that candidate),
[d4-corridor-option-c-implementation-review.md](d4-corridor-option-c-implementation-review.md)
(E23 independent review, `PASS WITH CONCERNS`),
[d4-corridor-native-candidate-1-outcome.md](d4-corridor-native-candidate-1-outcome.md)
(E21 consumed attempt close-out).

## 1. Verified values

| Fact | Value |
| --- | --- |
| Prelaunch seal (sha-256 of `PRELAUNCH.json`) | **`de0e16f73d71efbad636271217a4981b4e6350412184bdbdfa17533e3d304f00`** (bytes end `…04f00`) |
| Canonical authorization payload (sha-256) | **`e85ea64ba8ec15c383e913a72df7d1e4bd13569496a83d297bf7ee2c1952ff17`** |
| Canonical payload size | **2,393 bytes** |
| Plan digest (signed inside the payload) | **`2a30e95048e89ffa1420e0ae392b79f4d051f447d7a15a3edb896b4bbdcabb3a`** (`2a30e950…cabb3a`, v2, eight ops) |
| Source world (signed inside the payload) | `fbebef54dd466e0bea23cc30e11e94ebaf2a3ca07e2e9b7aadd6a6645c37d59e` (`fbebef54…d59e`, the D3-TERRAFORMING-1 after.sav; diagnostic save never a substitute) |
| Frozen closure | **3,447 entries — 3,447 verified, 0 missing, 0 mismatches** |
| Authorization state after this session | unsigned; `AUTHORIZATION.json` / `CLAIM.json` do not exist for candidate-2 |
| Company / max_cost / stale rule / launch count | company 0; `max_cost` £2,000 per op; the staged stale-refusal rule; 1 launch, 0 retries (all bound in the payload and unchanged from E24) |

## 2. Verification method (all read-only, offline)

1. **Seal re-check.** `sha256sum` over the staged `PRELAUNCH.json` equals the
   staged `PRELAUNCH.sha256` and the seal above — the E24 staging seal is
   byte-intact.
2. **Payload rebuild.** The canonical authorization payload was rebuilt offline
   from the candidate's own staged `PRELAUNCH.json` with the documented
   production functions (no key, no signing):
   `operator_authorization.authorization_payload(metadata, seal)` from
   `app/simulation/openttd/proof/operator_authorization.py` plus
   `canonical_authorization_bytes()`, then cross-checked byte-equal against
   `staged_authorization_payload_digest()` from
   `app/simulation/openttd/proof/corridor_construction_native.py`. Result:
   the rebuilt canonical bytes hash to the payload digest above over exactly
   **2,393 canonical bytes** — identical to the staged digest.
3. **Schedule cross-check.** The signed eight-op `operation_schedule` equals
   the E24 preparation record's §2 table and the `corridor_schedule()` v2
   derivation from the same pinned compiled facts; the signed `plan_digest`
   equals the digest above. The signed sevenths fields are consistent with
   the staged staging record (§3).
4. **Frozen closure verification.** The candidate's closure manifest
   hash-verifies read-only: **3,447 entries, 3,447 verified, 0 missing,
   0 mismatches**, against the working tree.
5. **Retained-evidence manifests.** Re-verified unchanged, read-only:
   consumed `d4-corridor-native-candidate-1` **28/28 OK**,
   `d2-clearing-native-candidate-3` **26/26 OK**,
   `d3-clearing-native-candidate-1` **26/26 OK**,
   `d3-clearing-native-candidate-2` **26/26 OK**,
   `d3-terraform-native-candidate-1` **385/385 OK**; the pinned after.sav
   re-reads `fbebef54…d59e`.
6. **Freshness scan.** No file in the candidate directory is newer than its
   own staging (the staged `PRELAUNCH.json` at 19:19:39 local). In the wider
   changed set the only later write is
   `OpenTTD-Knowledge/05-Planning/Next Actions.md` (19:39:21), which was
   written **by the payload-review session itself** — see §5.

The candidate's expected-result machinery was **not** exercised beyond these
read-only re-checks: preflight was not re-run, nothing was replayed natively,
and no file under the candidate was opened for writing.

## 3. What is signed — and the schedule-version binding limitation

The rebuilt payload binds, among other signed fields: the attempt identity
(`D4-CORRIDOR-2`), milestone, workspace, binary, the seal itself, the target
tile/company/construction and stale-refusal rules, `max_cost` £2,000, the
source world `fbebef54…d59e`, the complete budget table, the exact execution
command (`.venv/bin/python -m app.simulation.openttd.proof.corridor_construction_native
run artifacts/experiments/d4-corridor-native-candidate-2`), and the full
ordered eight-op `operation_schedule` with its `plan_digest`
`2a30e950…cabb3a`.

**Limitation (deliberate, per E23 §7 finding 3):** the `schedule_version`
number is **not** a signed payload key. The version's only role is choosing
the schedule derivation; the binding is carried instead by the signed
`operation_schedule` and `plan_digest`, which must equal the compiled
derivation of the selected version at preflight and at verify, and an unknown
version refuses fail-closed. A candidate-2 authorization can never authorize
candidate-1: their expected payloads differ in seven signed fields (`attempt`,
`prelaunch_sha256`, `workspace`, `plan_digest`, `operation_schedule`,
`budgets`, `execution_command`) and candidate-1's claim is consumed.

## 4. Read-only boundary — what this session did NOT do

No key access or signing; no `AUTHORIZATION.json`, `CLAIM.json` or
`LAUNCH-CONSUMED.json` created, modified or consumed; no launch, no AdminPort
connection, no native execution; no modification/regeneration of the frozen
candidate, its manifest, its closure or any retained evidence; no Git
staging/commit/push/reset/clean/stash (`git add` was not used at all). The
results below and in the corrected notes are *verification*, never
authorization: **any execution still requires exactly ONE fresh explicit
operator authorization**, the one-shot run under the existing rules.

## 5. Discrepancy findings recorded durably (2026-10-22)

The original **operator-review package** of the earlier 2026-10-22 payload
verification was **not stored as a durable repository file** — its exact §8/§9
wording is UNKNOWN and is not reconstructed here. This section is the durable
substitute for the two findings that matter, and the corrected conclusions:

- **"Next Actions.md was edited" — PROVEN true.** The file's only write that
  day is 19:39:21, by the payload-review session; every other vault write that
  day is from the 19:23–19:27 staging/vault batch, and no candidate file is
  newer than its staging.
- **"All pre-existing files preserved byte-for-byte" — OVERBROAD for exactly
  that one file.** The claim is compatible only when scoped as "except the
  review's own documentation writes"; as stated it was false.
- **Prior bytes UNKNOWN.** No retained copy of
  `OpenTTD-Knowledge/05-Planning/Next Actions.md` immediately before 19:39:21
  exists, so the exact byte-level prior state cannot be reconstructed and is
  not claimed. The 19:39:21 file is the first durable state of that note.
- **Binding impact: none.** Any such documentation mismatch is note-level;
  signature verification recomputes the seal from file bytes at
  authorization/verify time, so documentation shorthand errors do not affect
  the seal, the payload or the closure.

## 6. Corrections applied in this documentation session (all recorded, none silent)

Documentation-only edits made after §5, themselves kept on record here,
explicitly identified as corrections rather than quiet rewrites:

| Site | Correction |
| --- | --- |
| Abbreviated seal tail `de0e16f7…2bf00` in active references (root + vault-copy `EVIDENCE_INDEX.md` E24 row, `04-Evidence/Evidence Index.md` E24 row, `AI_START_HERE.md` §3/§4, `00-Project/Current Status.md`, `00-Project/Roadmap.md`, `02-Milestones/Pending Milestones.md`, `05-Planning/Blockers.md` §§1+8, `05-Planning/Task Board.md`, `05-Planning/Next Actions.md`, this record's predecessor §7.1) | corrected to `de0e16f7…04f00` per the verified bytes above (full `…3d304f00`) |
| `d4-corridor-native-candidate-2-preparation.md` §7.1 | the same shorthand tail corrected (its §1 always carried the correct full seal) |
| `d4-corridor-native-candidate-2-preparation.md` §8 | the dangling phrase "the evidence-index update below" (no such section exists) replaced by the actual evidence: the E24 evidence-index rows written immediately after that record (root + byte-verified vault copy) |
| `d4-corridor-native-candidate-2-preparation.md` §7.2 | a duplicated clause ("the `schedule_version` number itself is not a signed key;" twice) removed |
| `OpenTTD-Knowledge/05-Planning/Next Actions.md` | the overbroad preservation statement corrected to the §5 findings (self-written note, prior bytes unknown) and this record linked as the durable verification record |
| Root `TASKS.md` item 8 | a dated update records the E24 staging, this verification and the corrections (previously ended at the E23 review) |
| New E24 narrative entry in `EVIDENCE_INDEX.md` | the table row existed without its addendum narrative; the sixth entry records staging plus this verification (no new E-ID assigned) |

## 7. Honest limits

- The frozen closure covers `.venv` (3,203), `app` (221), the candidate
  workspace, the pinned interpreter, `CONTEXT.md`, `pyproject.toml` and
  `uv.lock` — **no tests, docs, or vault notes**; closure verification therefore
  says nothing about vault-note preservation (which is why §5 must be explicit).
- The original operator-review package was never written to the repository and
  remains unrecoverable; no substitute pretends to reproduce its exact text.
- Only the active (latest-day) note references were corrected; no historical
  quoted/labeled evidence text was rewritten.
- Pre-existing untracked local files were left untouched:
  `--version`, `OpenTTD-Knowledge.zip`, `OpenTTD-Knowledge/.obsidian/`,
  `docs/handoff/local-artifacts-before.json`, `opencode-debug.log`.

The one report button is the operator's. This record states offline
verification facts and documentation corrections only; it does not authorize,
attribute, promise or simulate any future launch. **Milestone D4:
INCOMPLETE. Candidate `D4-CORRIDOR-2`: PENDING_AUTHORIZATION. Next required
step: ONE fresh explicit operator authorization** (then the one-shot bounded
run: eight ops + route read, phase halts prefix-preserving on any failure).
