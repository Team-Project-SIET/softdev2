# Tile Classification V2 — executable execution path (Tasks A–D)

This record covers the four components that were missing when
`docs/p08-classification-v2-native-attempt-review.md` stopped the first native
attempt: (**A**) executable runtime preparation, (**B**) schema-2 AdminPort
dispatch, (**C**) the bounded capture runner, and (**D**) the fail-closed
world-correspondence policy. Everything here is implemented and validated
**offline only**: no OpenTTD launch, no AdminPort connection, no claim
consumption and no mutation of any historical record. The prior stopped
execution attempt remains the historical record of a one-shot authorization
that was never consumed — it is not reclassified as a native classification
failure.

## Policy basis

- The frozen prepared candidate
  `artifacts/demos/classification-seed17-b6fb1410/` stays **byte-unchanged**;
  its staged launch template was never executable (no reviewed procedure ever
  materialized the runtime), and this task does not reuse it — a **new**
  execution candidate is bounded to actual source/package/config/argv digests
  with the claim unconsumed.
- Correspondence modes (`proof/world_correspondence.py`):
  `SOURCE_SAVE_FUSION` (bound), `FRESH_GENERATION_FACT_COHERENCE`
  (alternative family), `SAME_SESSION_CENSUS` (fallback schedule, recorded
  for review, **not** bound to an executable attempt — that needs its own new
  reviewed candidate).
- Binding choice: the capture process loads the byte-verified retained
  `before.sav` (`-g <save>`, the Q3 reload precedent; **no** `-G 17`), the
  census runs against the retained qualified world state and no same-session
  facts bank is required (session budget stays exactly 90 classification
  pages). The retained welcome `start_day` 712223 is save-stable, so the
  SOURCE_SAVE welcome-echo gate is satisfiable.
- Save compatibility: OpenTTD resolves a save's GameScript by the stored
  name/version, so the staged composition keeps the frozen composed
  `main.nut` **byte-identical** and adapts only the info identity (protected
  retained staged identity `RoadFreightProof`, version 1, short name `RFP1`)
  via asserted-anchored replacement. This is a rehearsal of the retained
  identity, not a new bridge: controller class and registration stay
  byte-identical to the frozen base.

## Implementation

- **Task A — executable staging** (`proof/classification_execution.py`):
  re-derives and re-verifies the frozen candidate's task-meaningful artifacts
  (see "Historical supersession" below), then stages, in one fresh owned
  directory: an isolated `RuntimeWorkspace` (write_config with a private
  0600 Admin credential, pinned port reservation verified at preflight, the
  exact retained Seed 17 generator recipe stark `[game_creation]…[economy]…`
  including `multiple_industry_per_town = true`, `OpenGFX` graphics from the
  verified archive, the composed package written `xb` under a 0700
  `RoadFreightProof/` directory), the byte-verified `before.sav` staged as
  `source.sav`, and the sealed records: the exact final argv
  (`[bin, -D127.0.0.1:<port>, -c <cfg>, -x, -X, -g <workspace>/source.sav,
  -dscript=4,grf=1,net=3]`), config digest, package digests, request-plan
  payload digests, budgets, save binding, cleanup procedure and
  `AUTHORIZATION_REQUIRED.json`. `PRELAUNCH.json` is written last and sealed
  with `PRELAUNCH.sha256`; `artifact-manifest.sha256` enumerates the
  candidate files. **No CLAIM.json, no launch, no connection** — the claim is
  written only by the runner after a full preflight.
- **Task B — schema-2 dispatch** (`gamescript_transport.py`): public
  `tile_classification_page()`; `_read_query` accepts
  `TileClassificationRequest`/`TileClassificationReceipt` with
  correlation-before-failure and receipt-bound exchange validation; the
  uniqueness key is `(request_id, region selector, cursor)` for schema-2
  pages while every schema-1 family keeps the `request_id` key; duplicate,
  surplus, staleness and malformed responses fail closed through the existing
  conversion chain (`MalformedResponse`/`TransportProtocolError`/`TransportTimeout`),
  the transport disables itself and closes the session on any incomplete
  query (no retry, no reconnect), and the outbound budget cap
  (`operation_budget=8`) leaves page operations at 7 (with inline
  subscription) or 4.
- **Task C — bounded runner** (`proof/classification_capture.py`):
  `execute_capture` consumes the claim only after `prepared.preflight()`,
  then one launch (`NativeCaptureBackend`: proven retained-runner
  launch/connect/cleanup choreography; readiness marker wait
  `BRIDGE_STARTED protocol=1 api=15`; one secure connection; welcome-identity
  gate with `CaptureWorldIdentityError`), 90 exactly-ordered page exchanges
  through the backend seam (per-page timeout 15 s, operation budget 8, per
  page ≤508 response bytes, cumulative ≤52,324 bytes, observation deadline
  600 s), exact request/response bytes retained per page
  (`classification-pNNN-request.json`/`-response.json`), roll-up only via
  `TileClassificationSweep.record` plus `evaluate_correspondence`
  (`classification-completeness.json`, `classification-receipts.json`,
  `correspondence-verdict.json`), and a freight-mirroring `finally` that
  always runs owned cleanup, verifies the released endpoints, disposes the
  workspace, removes the credential, writes `cleanup.json`/`result.json`
  (statuses `TILE_CLASSIFICATION_V2_CAPTURED`,
  `..._CAPTURED_INCOHERENT`, `PARTIAL_CLASSIFICATION_CAPTURE`, `FAILED`,
  `FAILED_CLEANUP`) and refreshes the manifest. Partial captures keep every
  retained page plus `capture-failure.json` with a bounded failure code; a
  launch failure still produces failure evidence and the owned cleanup; the
  metadata world-identity gate cannot consume the claim silently (post-claim
  statements are guarded, and the claim is refused on re-run).
- **Task D — correspondence policy** (`proof/world_correspondence.py`):
  byte-verified retained save binding (save/prelaunch/runtime/world digests,
  staged-save byte verification), the explicit same-session schedule (facts
  90 + census 90 = 180 requests, per-bank byte ceilings — recorded for
  review, never silently bound), `fresh_fact_contradictions` (tile-by-tile
  equality of a fresh v1 facts bank against the retained projection) and
  `evaluate_correspondence` verdicts:
  `CORRESPONDENCE_ESTABLISHED` only with a bound sweep, verified save binding
  (source-save) and no contradictions; `REJECTED` on any world-identity,
  tile or cross-run contradiction; `PARTIAL_CORRESPONDENCE` for unbound
  evidence that stays recorded with all retained unknown tiles UNKNOWN.

## Historical supersession (deliberate, documented)

The frozen candidate's `frozen_source` pinned the exact byte state of every
runtime module at preparation time, including `gamescript_transport.py` and
`tile_classification.py`. Tasks B/C legitimately extend those modules, so the
byte snapshot is superseded **as an induction target** — the active binding
(`source_candidate_binding()`) re-derives the load-bearing evidence instead:
plan payload digests page by page (90/90 verified unchanged), the composed
package digest (unchanged), the retained Seed 17 references and welcome
identity, the unconsumed one-shot record (no launches, no requests, no claim
file) and refuse-on-drift/ambiguity. The historical record file itself is
untouched. The **current** source tree is pinned by the execution candidate's
own frozen inventory (verified by its preflight), so any further drift stops
it. The real-candidate test now verifies through this stronger re-derivation
and states the substitution in its docstring.

## Validation (offline)

- New suites: `tests/test_classification_execution.py` (10: records/argv/
  world/save correspondence, save-compatible composition, argv shapes, sealed
  budgets, preflight pass + claim/package/config/seal tamper refusals,
  round-trip load, source-candidate binding + drift/ambiguity/claim
  refusals), `tests/test_gamescript_transport_classification.py` (10:
  full controlled 90-page walk with operation accounting `[7]+[4]*89`,
  stale replay/duplicate/garbage/non-JSON/surplus-after-pong/wrong-token
  refusals, repeated-key refusal, session death, v1 facts interleave on the
  same transport), `tests/test_classification_capture.py` (10: full bound
  controlled capture with byte retention, mid-census failure keeps evidence
  and never retries, welcome mismatch fails before any page with diagnostics,
  page/byte budget fail-closed, consumed-claim refusal, unauthorized backend
  refusal, launch-failure-after-proof cleanup honesty, real-record-shape
  requested_pages regression, failure codes), `tests/test_world_correspondence.py`
  (8: binding verification/tamper, schedule, verdicts, cross-run refusal,
  staged-save gate).
- Regression: pinned touched suites 100 PASS (`test_gamescript_transport`,
  `test_tile_classification`, `test_tile_classification_receipt`,
  `test_terrain_classification_preparation`, the four new files);
  neighbor groups 540 PASS + 7 skipped (tile-facts/terrain/admin/P08) and
  80 PASS (external runtime/native save/workspace/paired native). Full-suite
  run exceeds the offline time box (heavy unrelated experiment suites) and is
  documented instead of silently truncated.
- Real staging smoke: prepare + full preflight pass offline into a tmp
  directory (fresh ports, 90/90 plan, 90/90 budget); the authorized-candidate
  artifact itself is materialized at
  `artifacts/demos/classification-exec-seed17-e71c95a3/`
  (composition identity `e71c95a3fde6202c…`, attempt
  `750167949a4f46af…`, claim absent, full preflight PASS at preparation
  time — and the preflight is idempotent re-runnable; ports are re-verified
  free by the preflight because they are not held across sessions). The
  first staged candidate of this composition was disposed and re-prepared
  after a post-staging source edit invalidated its own frozen current-tree
  inventory: fail-closed drift detection of the execution candidate works
  exactly as sealed.
- Independent review (general agent, full cross-module): two blocking findings
  (metadata plan-shape KeyError consuming the claim with zero evidence; stale
  local `proof` producing false cleanup evidence) — both fixed and re-verified
  PASS by the same reviewer with two regression tests added; no new blocking
  findings.
- Gates: ruff check/format clean on all touched files; compileall clean;
  `git diff --check` clean; typecheck tooling unavailable (no mypy/ty/pyright),
  reported not silently skipped. No commit/push/reset/clean; the untracked
  root file `--version` was never executed.

## Remaining native validation requirements (never silently assumed)

1. One fresh operator authorization after preflight; the execution candidate
   records `PENDING_AUTHORIZATION`, `authorized: false`, `maximum_launches: 1`.
2. OpenTTD 15.3 save-load GameScript resolution: the staged composition
   advertises the retained stored identity (`RoadFreightProof`/1). Whether the
   engine matches save-stored name+version against the staged info and how it
   handles the old GameScript's Save-data versus the new class without a Load
   hook are engine-native facts that only the authorized launch can confirm;
   a mismatch manifests as a TransportTimeout on page 1 plus stderr log
   markers and fails closed.
3. The first classification page response doubles as composition-resolution
   evidence (no extra preflight ping; session budget stays 90).
4. Real fixture/graphics loading under the staged isolated profile and the
   exact Seed 17 world reload correspondence — verified exhaustively only
   during the capture itself.
5. The SAME_SESSION_CENSUS fallback (180-request schedule) remains a review
   record, not an executable attempt; binding it needs a new reviewed
   candidate with its own authorization.
