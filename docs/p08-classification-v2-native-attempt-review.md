# P08 Tile Classification V2 — authorized one-shot attempt review (STOP BEFORE LAUNCH)

**Date:** 2026-10-18. Scope: execute at most ONE native OpenTTD 15.3 launch for the
prepared Seed 17 Tile Classification V2 candidate
`artifacts/demos/classification-seed17-b6fb1410/`
(identity `b6fb1410fb9fb76f250be0ab787e92495ed3f538dc920f543c9259d0388c8525`).

**Outcome: STOP BEFORE LAUNCH — zero launches, zero AdminPort connections, zero
classification requests. The one-shot authorization was NOT consumed; the
candidate state remains `PENDING_AUTHORIZATION` and all candidate bytes are
unchanged.** Historical evidence is untouched; nothing was committed, pushed,
staged or overwritten.

## Pre-launch review status

Reviews executed in this order: harness/skill discovery, repository context
documents, the two classification records, candidate inspection, code-path
inspection of every module the launch path would use, then the reviewed
preflight with offline independent re-verification.

Skills discovery: no project-local, user-local skill directories and no
project/user-local `SKILL.md` files exist in this checkout. The
OpenCode-provided skills (`code-review`, `feature-dev`, `tdd`,
`diagnosing-bugs`, …) are change-review/feature-development skills; none applies
to a gated native capture execution. The review therefore used the repository's
own reviewed code, its pinned offline suites, and fresh hashing — no external
skill was invoked.

Context documents read: `CONTEXT.md`, `AI_HANDOFF.md`, `TASKS.md`,
`EVIDENCE_INDEX.md`, `REPRODUCE.md` (no `RULES.md`/`AGENTS.md` exists),
[`docs/p08-classification-v2-native-capture-preparation.md`](p08-classification-v2-native-capture-preparation.md),
[`docs/p08-native-tile-classification.md`](p08-native-tile-classification.md),
plus the retained run's `PRELAUNCH.json`.

## Preflight and independent verification (all PASS)

- `PreparedCapture.preflight()` on the real candidate: PASS.
  `state=PENDING_AUTHORIZATION`, `authorized=False`, `native_launches=0`,
  `requests_sent=0`; 196 frozen sources verified; all four retained references
  verified by sha256; staged-seam validation PASS; 90 pinned request payloads
  re-derived; region coherence `[170,171,15,30]` vs retained facts PASS.
- Independent re-derivation (fresh hashing, not trusting the candidate):
  - Attempt identity recomputed equal:
    `b6fb1410fb9fb76f250be0ab787e92495ed3f538dc920f543c9259d0388c8525`.
  - Package digest
    `9f2ccb16f38c33f8dac0a133e06efa9b955451727e5cd18d361618be8d56d1d1`;
    `info.nut`/`main.nut` per-file sha256 and byte counts match
    (`main.nut` = 25,388 composed bytes).
  - v1 terrain composition
    `ee2fdbf3fd3bb3a7d4f6e590df9fecd546b6359c23c44dfff47135333b755c55` —
    frozen v1 identity unchanged.
  - OpenTTD binary
    `/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd` exists, is
    executable, sha256 `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`
    (pinned, equal to the retained Seed 17 prelaunch binary).
  - Plan: exactly 90 pages, 2 bands — band A `region` echo `(170,171,15,17)`
    (51 pages, cursors 0…250 step 5), band B `(170,188,15,13)` (39 pages,
    cursors 0…190 step 5); every payload ≤ 159 bytes (max observed 142), every
    payload contains `"schema":2`, uniform `request_id` and full region echo;
    total 450 tiles ≤ 512 census ceiling; 90 ≤ 103-page budget; aggregate
    response ceiling 103×508 = 52,324 bytes; budgets otherwise exactly as the
    candidate records (1 launch/connection, 0 retries, 600 s).
  - Retained correspondence inputs verified: `network-facts-0.json`,
    `runtime-identity.json`, `world-planning-observation.json`,
    `random-generation-request.json` all hash-match; retained welcome
    `{seed 17, width 256, height 256, landscape 0, revision "15.3",
    start_day 712223, dedicated True}`; retained TileFacts 450 tiles with
    exactly 19 projection-dropped tiles (the historically unknown class).
  - No OpenTTD process was resident before or during the review
    (`pgrep -af openttd-15.3` returned none).
- Offline regression rerun in this checkout: 46 tests pass —
  `tests/test_tile_classification_receipt.py` (16),
  `tests/test_tile_classification.py` (13),
  `tests/test_p08_classification_workflow.py` (7, retained replay binds a
  90-page/450-tile synthetic census and reproduces the retained assessment
  digest-for-digest with the 19 dropped tiles UNKNOWN),
  `tests/test_terrain_classification_preparation.py` (9 + the gated
  real-candidate preflight check). No native claims are made by these tests.
- Candidate immutability after review: the directory still holds exactly the
  five prepared files with unchanged mtimes (`Oct 17 23:56`); no `CLAIM.json`,
  no `isolated/` directory. The retained Seed 17 one-shot claim is untouched
  consumed history (`CLAIM.json` in
  `playable-demo-698799a2dfb146948fd2983ff2032253`).

## Why the launch is gated (Section-3 STOP condition met)

The candidate's launch-command template is
`[openttd, -D127.0.0.1:{reserved_game_port}, -c <candidate>/isolated/openttd-15.3-staged/openttd.cfg, -x, -X, -G, 17, -g, -dscript=4,grf=1,net=3]`
with the two declared variables ("freshly reserved endpoints", "freshly staged
isolated configuration directory") explicitly re-materialized at "the execution
preflight". That execution preflight does not exist in this checkout. It cannot
therefore produce a fully reviewed executable command, which forces STOP before
any launch, per the authorizing review procedure itself.

Verified fail-closed facts (code paths inspected, not assumed):

1. **No reviewed launcher for the candidate's staged configuration.** The
   staging path `isolated/openttd-15.3-staged/openttd.cfg` is named only by
   `proof/terrain_classification_preparation.py` (record) and the duty doc. No
   module materializes it. `RuntimeWorkspace.create()` creates
   `openttd-15.3-<random-suffix>` directories, and all `harness.prepare_proof`
   modes stage a 64×64 seed-42 test world configuration
   (`[game_creation] map_x=6 map_y=6 generation_seed=42`) — not the required
   temperate 256×256 seed-17 world creation settings; no mode stages the
   classification world. Inventing or hand-patching that configuration would be
   exactly the prohibited "manually invent/patch/substitute launch flags" path.
2. **The classification package composition is never materialized for a
   runtime.** `terrain_classification_bridge.classification_package_bytes()` is
   memory-only by contract ("no file writes"); the only GameScript staging
   helper, `gamescript_bridge.stage_bridge()`, writes the frozen *base*
   package whose `main.nut` implements neither the classification handler nor
   the composed marker. The candidate records only the composition digest; no
   reviewed code installs `info.nut` + composed `main.nut` into a runtime
   `game/` directory.
3. **No reviewed native exchange path for schema 2.**
   `GameScriptTransport` exposes `tile_facts_page` (v1) and other read queries;
   it has no `tile_classification_page` method, and `_read_query`'s
   receipt-dispatch union does not include `TileClassificationRequest` — a sent
   classification request reaches the no-receipt abort path and kills the
   single, no-retry session before any page is returned. The proof backends
   (`proof/*_native.py`, `proof/__main__.py` modes) contain no
   tile-classification mode, and the only plan/exchange runner
   (`terrain_native_integration.py`) is an explicitly simulated lifecycle whose
   `SimulatedBackend` implementations "must never open native resources".
4. **Endpoint reservation / owned config / credential binding for this
   candidate** — the components exist only for other, separately prepared
   attempts (harness/terrain/demo runners); no reviewed procedure binds them to
   this candidate's `PENDING_AUTHORIZATION` state (the candidate explicitly
   states that no authorization record is created until an authorized launch
   runs under a fresh one-shot record).

Consequence: executing `docker`-style manual argv substitution to bypass the
unresolved variables, or writing new unreviewed runtime code in this task, were
both out of scope of the authorization; the launch was not consumable under the
reviewed procedure, so the safe state — unspent one-shot authorization — is
retained.

## World-correspondence gate analysis (Section 4)

- Preferred path (authorized byte-verified source-save load) is **not offered
  by the candidate**: the template launches a fresh random world (`-G 17 -g`,
  no save-load argument). The acceptance contract instead relies on the
  candidate's own correspondence rule: a fresh launch must echo the retained
  welcome keys (seed 17, 256×256, landscape 0, revision 15.3, start_day
  712223) **and** every classified tile must agree with the retained TileFact
  projection (height, slope, industry sentinel, projected flags) for
  `TileClassificationSweep.bound` to become true; any contradiction records
  explicit failures (e.g. `WORLD_IDENTITY_MISMATCH:*`,
  `HEIGHT_DIFFERS_FROM_TILE_FACT`) and blocks fusion. A matching seed alone is
  explicitly not accepted.
- The prepared plan contains **no same-session TileFacts acquisition** (only
  the 90 classification requests), so acceptance is by construction a
  cross-run fusion of fresh schema-2 census bytes against retained historical
  TileFacts. Tile-level coherence across all 450 tiles would be strong
  correspondence evidence if it passed, but it can only be evaluated after a
  launch; before any launch this requirement remains **unsatisfied and
  unverifiable**, and the Section-4 rule ("if the candidate requires cross-run
  fusion for acceptance and cannot satisfy that requirement, STOP") therefore
  independently supports the STOP decision.
- Because no launch occurred, the actual historical-world correspondence is
  **NOT established**. The retained Seed 17
  `INCOMPLETE_TILE_CLASSIFICATION` assessment (450 tiles = 339
  `ROAD_BUILDABLE` + 63 `SUPPORTED_CLEARING` + 19 `UNKNOWN_OCCUPANCY` + 29
  `UNSUPPORTED_CONSTRUCTION`, 24-tile corridor) is historical fact and was NOT
  reinterpreted or re-run for feasibility. The 19 historically unknown tiles
  remain UNKNOWN; no claim may be made about their resolution.

## Cleanup and evidence (post-review, no launch)

No owned process existed, none was launched; no socket, credential, temporary
workspace or runtime directory was created or consumed. The frozen candidate
bytes and every retained evidence file are bit-identical (verified before and
after the review). The offline verification script used by this review is
retained as review diagnostics at `/tmp/opencode/verify_candidate.py` (outside
all artifact evidence); it is read-only and connects to nothing.

## What a future authorized attempt must first provide (all offline-preparable)

1. A reviewed execution-preflight/staging implementation that materializes the
   composed classification package into an owned isolated workspace, stages the
   candidate's declared configuration path, reserves distinct localhost
   endpoints, generates the fresh admin credential, stages OpenGFX, and writes
   the seed-17/256×256/temper/terrain-0/towns-1/industries-2 world-creation
   configuration consistent with the retained prelaunch identity, then records
   the exact final argv and config digest.
2. Transport dispatch for `tile_classification_page` responses
   (`TileClassificationReceipt.correlate` integration, exchange build and
   one-per-page completion barriers) through the existing encrypted AdminPort
   session machinery.
3. A capture runner that exactly walks the 90 pinned plan pages, retains per
   page the request/response bytes and hashes, and reaps owned processes on
   success or failure (zero retries/reconnects), with a fresh one-shot
   authorization record.
4. An explicit correspondence policy decision for the post-capture fusion (the
   current rule binds fresh census bytes tile-by-tile against the retained
   TileFacts plus the welcome echo) — apples for `WORLD_IDENTITY_MISMATCH`
   handling either as partial evidence or as refusal of historical fusion.

Until then, the prepared candidate must remain `PENDING_AUTHORIZATION` with
zero launches; every further review of this identity should re-run
`PreparedCapture.preflight()` and repeat the independent verification above. If
a fresh launch is made the confirmation that it did not consume this
authorization must come from an unmodified `CANDIDATE.json`
(`native_launches=0`, `requests_sent=0`, `authorized=False`).
