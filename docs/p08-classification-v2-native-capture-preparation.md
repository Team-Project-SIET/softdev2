# P08 Tile Classification V2 — native capture readiness (offline preparation)

Milestone: prepare ONE fresh, independently reviewable Seed 17 Tile
Classification V2 census attempt. No OpenTTD launch, no AdminPort connection,
no authorization consumption, no historical evidence mutation happened in this
task; the candidate is `PENDING_AUTHORIZATION` and consumes nothing.

Prior records: `docs/p08-bounded-terrain-modification-support.md`
(bounded terraforming), `docs/p08-native-tile-classification.md`
(schema-2 contracts, feasibility assessment, readiness registry).

## Task A — TileClassificationReceipt, correlation and census binding

Additive module tail in `app/simulation/openttd/tile_classification.py`
(schema-2 paths only; every schema-1 identity stays byte-identical):

- `projection_disagrees(tile_fact, flags)` — the exact same-instant coherence
  gate (carried ground/transport bits, three-way road OR, buildable bit with
  native house/station suppression). `p08_terrain._projection_disagrees`
  now delegates to it: a single projection authority for the assessor and the
  receipt layer.
- `TileClassificationReceipt.correlate(request, response)` — binds one page:
  request parse first, response size budget (`RESPONSE_LIMIT_EXCEEDED`),
  identity read BEFORE any bounded native error propagates (torn envelopes
  surface as the generic `MalformedMessage`, exactly like the v1 receipt),
  `REQUEST_ID_MISMATCH`, `UNSUPPORTED_CLASSIFICATION_SCHEMA`, then
  `CURSOR_MISMATCH` unless region/cursor/schema echo the request. Receipts pin
  the sha256 of both payloads.
- `TileClassificationExchange` + `CLASSIFICATION_NETWORK_SEQUENCE` — exact
  `1 request → 1 response`, zero retries; `validate()` re-derives the receipt
  and refuses any accounting drift (`ACCOUNTING_LIMIT_EXCEEDED`).
- `classification_plan(region, request_id)` — deterministic bounded request
  sequence. A census rectangle larger than the 256-tile v1 request budget is
  split into guillotine bands (area ≤ 256 each), every band paginated from
  cursor 0 with `PAGE_SIZE` steps. The Seed 17 census rectangle (15×30 = 450
  tiles) becomes bands of 15×17 + 15×13 and exactly 90 pages. A shape that
  would need more than `CLASSIFICATION_PAGE_LIMIT` (103) requests is refused
  (`ACCOUNTING_LIMIT_EXCEEDED`) instead of silently over-paging.
- `TileClassificationSweep.record(requests, exchanges, *, retained_facts,
  retained_facts_digest, retained_welcome, observed_welcome)` — composes one
  `TileClassificationIndex` per band, enforces the exact prepared plan
  (every exchange's request bytes must equal the pinned plan page bytes;
  extra/foreign/missing pages ⇒ `INCOMPLETE_SWEEP`), enforces the census
  tile budget (`CLASSIFICATION_MAX_REGION_TILES` = 512) and the aggregate
  response budget, then fuses tile-by-tile against the retained `TileFact`
  rows: height, slope, industry (null sentinel) and the projection gate above.
  `bound` is true only with zero coherence failures AND a welcome-identity
  echo (seed/width/height/landscape/revision/start_day). Failures are kept in
  full (tile id + reason) — never repaired, renamed or downgraded.
  `require_bound()` is the assessor gate (it raises on an unbound census);
  `completeness_summary()` is a machine-readable JSON record (counts, unknown
  ids, failure inventory, digests); `digest` is its sha256.

Budgets (fixed, fail closed): 5 tiles/page, request ≤ 159 B, response ≤ 508 B
(shared caps), census ≤ 512 tiles, ≤ 103 pages, aggregate responses ≤ 103×508.

## Task B — bridge integration on a fresh, unfrozen path

`app/simulation/openttd/proof/terrain_classification_preparation.py`:

- `validate_staging_seams()` — the composed classification package must carry
  exactly one renamed raw marker, the additive handler seam
  (`class NoMutationBridge extends TerrainClassificationBridge {}`), the six-field
  request gate (`request.len()!=6`), the schema-2 echo, no prohibited
  mutation seam (`RaiseTile`/`LowerTile`/`LevelTiles`), and the v1 terrain
  composition must still be byte-exact from its frozen authority. Any missing
  or contradictory seam fails preparation with a named `ValueError`.
- Package identity: `classification_package_digest()` over
  `info.nut` + composed `main.nut` (`name\0 len\0 content`), recorded in the
  candidate; the frozen v1 compositions keep their own digests untouched.
- `prepare()` — materializes `artifacts/demos/classification-seed17-<id8>/`:
  `CANDIDATE.json` (PENDING_AUTHORIZATION, zero launches, zero requests),
  exact `classification-requests.json` pages (90 payload bytes + shas),
  `receipts-required.json`, `cleanup.json`, `AUTHORIZATION_REQUIRED.json`.
  `preflight()` re-verifies frozen sources, retained references, plan digests
  and composition identity and refuses drifted or tampered candidates.
- Legacy package identities preserved: the staging path never writes into the
  frozen packages, and the composed classification bytes live only in the new
  candidate directory.

## Task C — Seed 17 classification workflow (prepared, not executed)

The runbook for the future authorized attempt (all verification steps exist as
code today; only the native launch is pending):

1. `PreparedCapture.preflight()` — frozen sources, staged package, retained
   references and the 90-page plan all re-verified (`PENDING_AUTHORIZATION`
   state, authorized=false, launches=0).
2. Retained identity check: `runtime-identity.json` welcome
   (seed 17, 256×256, landscape 0, revision 15.3) recorded as
   `world_identity_requirements`; same-seed recipes are NOT assumed identical.
3. Native acquisition (future): 90 request pages with the exact prepared
   payloads; one correlated receipt per page; ≤ 508 response bytes per page;
   zero retries; full band coverage with terminal `has_more` parity.
4. `TileClassificationSweep.record(...)` — completeness, uniqueness, ordering
   and terminal coverage verified; every classified tile checked against its
   retained TileFact projection (height/slope/industry/flags coherence).
5. Binding decision: `bound == True` requires zero coherence failures and the
   welcome echo; a mismatch ⇒ the census stays UNUSED
   (`WORLD_IDENTITY_MISMATCH` recorded), never fused by a seed-name argument.
6. `sweep.require_bound()` → `(tile_classes, tile_flags)` fused into
   `assess_world_feasibility(...)` (three bounded tiers; budgets unchanged).
7. Updated segment distribution + corridor + `INCOMPLETE_TILE_CLASSIFICATION`
   codes produced as before; the retained historical numbers are NOT edited.
8. Task D mapping (below) produces the readiness projection per classified
   obstacle; unknown tiles still map to `UNKNOWN_TILE` (capture missing).
9. Machine-readable records: `completeness_summary()` (JSON) and
   `FeasibilityDiagnosis.as_dict()` (JSON). No native classification claim is
   possible until the authorized capture actually runs.

Offline replay proof (tests/test_p08_classification_workflow.py): a census
synthesized exactly from the retained TileFact projection — with the 19
projection-dropped tiles carrying NO predicate, i.e. genuinely UNKNOWN —
binds (90 pages, 450 tiles) and reproduces the retained assessment
byte-for-byte: same code (`INCOMPLETE_TILE_CLASSIFICATION`), same corridor,
same segment counts (339 ROAD_BUILDABLE, 63 SUPPORTED_CLEARING, 19 UNKNOWN,
29 UNSUPPORTED), same digest. The replay is a workflow demonstration over
retained observations, not a native measurement.

One projection semantics fix was required to make that fusion sound:
`classify_segment` no longer treats an agreeing schema-2 ground class
(TREES/FARM/ROCK/ROUGH over projected clearing ground) as a contradiction when
a coherent same-instant mask is present — the projection gate has already
verified every shared bit in that case. All previous behavior for mask-less
index-only claims (the felled-tree ambiguity) is preserved verbatim, and all
pinned suites still pass.

## Task D — construction readiness projection

`app/planning/construction_readiness.py` additions (mapping only):

- `requirement_for_tile_class(tile_class, *, slope)` — CLEAR is shape-aware
  (flat → `BUILD_ROAD`, sloped → `CORNER_RAISE`); TREES/FARM/ROCK/ROUGH →
  `CLASSIFIED_CLEAR`; HOUSE/STATION/INDUSTRY/WATER/COAST/AIRPORT/ROAD/RAIL/
  DOCK → `OCCUPANCY_CONVERSION`; `UNKNOWN_OCCUPANCY` → `UNKNOWN_TILE`;
  anything else raises.
- `classification_readiness_report(counts)` — machine-readable per-class
  projection of `requirement_id`, `native_api`, `native_support` (planning vs
  native execution) and a `planning_only` flag. No entry converts a planning
  proposal into an executable native command; terrain mutation, bridges and
  tunnels remain out of scope in this task.

## Prepared native capture identity

- Attempt: prepare via `prep.prepare()` (identity derived from the package
  digest, v1 composition digest, retained reference digests, the 90 request
  payload digests, region and schema version — attempts are reproducible and
  stable across test/doc edits because only frozen content enters the digest).
- Materialized candidate (this checkout): `artifacts/demos/
  classification-seed17-b6fb1410/`, attempt identity
  `b6fb1410fb9fb76f250be0ab787e92495ed3f538dc920f543c9259d0388c8525`,
  package digest `9f2ccb16f38c33f8dac0a133e06efa9b955451727e5cd18d361618be8d56d1d1`,
  `PENDING_AUTHORIZATION`, preflight verifying 196 frozen sources, all four
  retained references, the 90 pinned request payload digests and the package
  composition identity offline.
- Candidate directory: `artifacts/demos/classification-seed17-<id8>/`.
- State: `PENDING_AUTHORIZATION`; launches 0; requests 0; claim untouched
  (the retained Seed 17 CLAIM is consumed history and is never re-read for
  authorization).

Exact proposed launch command (template; the retained prelaunch argv shape
with only the freshly reserved endpoints and the freshly staged isolated
configuration path variable):

```
/exact proposed launch command

/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd \
  -D127.0.0.1:{reserved_game_port} \
  -c <candidate>/isolated/openttd-15.3-staged/openttd.cfg \
  -x -X -G 17 -g -dscript=4,grf=1,net=3
```

- Binary sha256 pinned in the candidate equals the retained prelaunch binary.
- Connection requirements: dedicated server on freshly reserved localhost
  endpoints, one AdminPort connection, exchange only through the staged
  additive classification package; no interactive GUI.
- Budgets: 90 classification requests (+ correlation receipts), 508 B/page
  response cap, 103-page/52,324-response-byte aggregate caps, 600
  observation seconds, 1 launch, 0 retries.
  Note: 103 × 508 = 52,324. The 512-tile census ceiling is reachable only in
  band-able shapes: a 16×32, 512×1 or 256×2 rectangle would need more than
  103 one-band pages and is refused (`ACCOUNTING_LIMIT_EXCEEDED`) instead of
  over-paged.
- Required receipts (candidate `receipts-required.json`): per-page
  correlation receipts, 508 B envelope parity, complete in-order page set,
  census coherence bound against the retained TileFact projection,
  machine-readable completeness + feasibility records.
- Cleanup: close reserved sockets, record the exact launched command, stop
  the runtime and retain failure.sav/frames when present, remove the staged
  isolated runtime directory, keep classification artifacts intact; any claim
  ledger is untouched unless the capture launched under its own fresh
  one-shot record (no CLAIM consumption happens during preparation).
- Authorization: ONE fresh operator authorization after preflight; the
  prior Seed 17 one-shot remains consumed; no offline action consumes
  anything.

## Validation

- `tests/test_tile_classification_receipt.py` (16 PASS): receipt round-trip and
  identity-read precedence, size/cursor/schema rejection, exchange fail-closed,
  plan shapes and page budget, complete binding + determinism, incomplete/
  foreign/extra page rejection, re-encoded-request-bytes refusal, mislocated
  row rejection (and why coherent streams cannot duplicate a tile),
  flags/industry/geometry/world-identity contradictions, projection truth
  table, v1 receipt compatibility.
- `tests/test_p08_classification_workflow.py` (7): Task D mapping for all 15
  classes + planning/native distinction; the retained replay binds the full
  census and reproduces the retained assessment (identical digest); the 19
  unknown tiles stay UNKNOWN; plan pinning; prepared-capture linkage.
- `tests/test_terrain_classification_preparation.py` (9 PASS + 1 gated
  real-candidate check): candidate shape, launch template vs the retained
  prelaunch (exact retained argv tail order), request plan match,
  receipts/cleanup, preflight, tamper refusals (authorized/state/identity/
  launches, frozen source, package digest, plan digest), malformed staged
  handler refusal, retained-evidence requirement.
- Pinned suites re-run green with exact counts: controlled road 62 +
  controlled e2e 62 + bounded routing 17 + design audit 18 (159), bounded
  terrain 14, feasibility 24, tile classification 13; protocol/terrain group —
  gamescript bridge 35, gamescript protocol 29, terrain capture 22, terrain
  historical root 11, terrain model A 41, tile-facts protocol 27, supplemental
  planning contracts 65 (230).
- Gates: ruff check/format clean on touched files; compileall clean;
  `git diff --check` clean; typecheck tooling unavailable in this environment
  (reported, not silently skipped).

## Remaining blockers to a native census

1. One fresh operator authorization (offline work consumed nothing).
2. The exact prepared command must be re-materialized at the execution
   preflight (fresh ports + staged isolated configuration), then recorded.
3. Native classification extraction itself is the future capture; offline
   preparation cannot observe tiles, so no classification success is claimed.
