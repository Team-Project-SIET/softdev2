# P08 Tile Classification V2 — native capture terminal outcome (FAILED)

**Date:** 2026-10-18. One authorized native OpenTTD 15.3 launch was executed for
the prepared execution candidate
`artifacts/demos/classification-exec-seed17-e71c95a3/`
(attempt `750167949a4f46af16250b8d8927a3e95160aaceabcd321d6c1d9ea3dbee3c7b`,
composition `e71c95a3fde6202c…`, correspondence `SOURCE_SAVE_FUSION`).

**Terminal result: the native capture FAILED with zero classification pages.
The one-shot authorization is consumed** (`CLAIM.json` exists, `consumed: true`,
`launches_allowed: 1`, `retries: 0`); no second launch was made and none is
authorized. The runner terminated with `status = FAILED_CLEANUP` (see Cleanup).
This record is owned runtime outcome documentation; no historical evidence,
frozen candidate record or pinned code was modified.

## Pre-launch gates (all PASS before the launch)

The runner's read-only `preflight` was re-run immediately before execution:
`PREFLIGHT_PASS` with the same argv byte-for-byte as the sealed records.

1. **Candidate/source identity** — attempt identity and composition identity
   match the directory name, `CANDIDATE.json` and the sealed `PRELAUNCH.json`
   (`PRELAUNCH.sha256` seal verified). The staging preflight re-verifies the
   frozen prepared candidate `classification-seed17-b6fb1410/` (state
   `PENDING_AUTHORIZATION`, `authorized: false`, zero launches, zero requests,
   no claim file), the deterministic 90-page plan digests, the retained
   references and the retained welcome/region identity.
2. **Frozen package correspondence** — staged `game/RoadFreightProof/info.nut`
   (552 B, sha `190bd0f7…512ee`) and `main.nut` (25,388 B, sha `ae212ab7…96e6f`)
   match the recorded per-file digests; package digest
   `392c42baaee1974f6022eed18300f09e472f50d2a295139d32ee73a34d5f2309` re-derived
   with the `name\0<len:8BE>content` convention from the staged bytes. The
   composed main is byte-identical to the frozen classification composition and
   carries no prohibited mutation seam.
3. **Binary identity** — `/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd`
   sha256 `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`
   (pinned, equal to the retained Seed 17 prelaunch binary); no resident
   `openttd` processes at launch time.
4. **Source save identity** — staged `source.sav` (61,728 B, sha
   `e81f655363347b808daf07e504dee281144cc095cbec128f0b3c0ff7b127117c`) is
   byte-identical to the retained `before.sav`
   (`playable-demo-698799a2dfb146948fd2983ff2032253/`); save correspondence
   record verified by the preflight.
5. **GameScript loading (offline-verifiable extent)** — the staged composition
   announces the retained stored save identity (name `RoadFreightProof`,
   version 1, short name `RFP1`, controller `CreateInstance() → NoMutationBridge`);
   whether the engine resolves a save-stored GameScript against this staged
   info and tolérates the stored Save-data without a `Load()` hook was
   documented as an engine-native fact decidable only at launch (fail-closed).
6. **Schema-2 transport compatibility** — `GameScriptTransport.tile_classification_page`
   + `_read_query` union with the `(request_id, region, cursor)` uniqueness key
   implemented; controlled 90-page walk with `[7]+[4]*89` operation accounting
   passes offline.
7. **Receipt/correspondence contracts** — `TileClassificationReceipt.correlate`
   / `TileClassificationExchange` / `TileClassificationSweep.record` +
   `evaluate_correspondence` (SOURCE_SAVE_FUSION) implemented and pinned suites
   pass (108 tests across the nine classification suites re-run immediately
   before the launch, all PASS).
8. **Exact effective argv/config** — the preflight-recomputed argv equals the
   sealed argv (`[openttd, -D127.0.0.1:33209, -c <workspace>/openttd.cfg, -x,
   -X, -g <workspace>/source.sav, -dscript=4,grf=1,net=3]`); the staged config
   carries the exact Seed 17 creation recipe (temperate, 256×256, terrain 0,
   towns 1, industries 2, `multiple_industry_per_town = true`, `graphicsset =
   OpenGFX`, `pause_on_newgame = false`).
9. **Endpoint/credential isolation** — loopback-only server (`127.0.0.1`),
   ports 33209 (game) / 51519 (admin) re-verified free by the preflight right
   before the launch; admin credential `.admin-secret` was 0600 32 B with the
   matching authorized public key `3cc5e6c108ab6223cc3a8742b74c254defe2de0f939fba931a8f0c1d79f48e67`
   in the staged `secrets.cfg`; `allow_insecure_admin_login = false`.
10. **Budgets** — sealed: 90 classification requests, page limit 103, ≤508 B
    response/page, ≤52,324 aggregate response bytes, 600 s observation, 1
    launch, 1 connection, 0 retries, 0 reconnects, 0 mutations, 0 construction
    actions, 0 v1 TileFacts requests; enforced by the runner before each
    request and again in the roll-up.
11. **One-shot claim absence** — no `CLAIM.json` (nor any capture output file)
    existed before the run; the claim is written only by the runner after the
    full preflight.
12. **Cleanup ownership** — freight-mirroring `finally` cleanup with endpoint
    verification, staged-workspace disposal-on-success, credential removal and
    a dedicated FAILED_CLEANUP status if any link fails.

## Execution and the native failure

- Command executed (the only authorized invocation):
  `.venv/bin/python -m app.simulation.openttd.proof.classification_capture run
  artifacts/demos/classification-exec-seed17-e71c95a3 --authorize-one-launch`
- Exactly **1 launch** (pid 76507, returncode 0), **0 AdminPort sessions
  recorded, 0 classification requests, 0 pages exchanged** (of 90), 0 response
  bytes. The runner consumed the claim and then failed closed during the
  readiness/metadata window before any census exchange:
  `capture-failure.json`: `{"code": "RUNTIMEERROR", "detail": "Native
  script/asset error", "connected": false, "pages_exchanged": 0,
  "elapsed_seconds": 0.38}`.

Native stderr (staged runtime, retained; the decisive markers):

```
dbg: [script:3] [18] [W] Loading failed: there was data for the script to load,
     but the script does not have a Load() function.
dbg: [script:4] [18] [I] BRIDGE_STARTED protocol=1 api=15
dbg: [script:1] [0] [E] No suitable AI found to load.
dbg: [script:0] The script died unexpectedly.
dbg: [script:3] [18] [W] Save function is not implemented
dbg: [script:3] [18] [W] Save function is not implemented
```

Reading of this evidence (this is the observed native record, not a repaired
interpretation):

- The engine loaded the staged GameScript **by the save's stored identity**
  (script instance `[18]`, save carried stored GameScript data) and the staged
  composition **started** (the `BRIDGE_STARTED protocol=1 api=15` marker can
  only come from the staged composed main). Save-name resolution therefore
  worked; the previously open engine question was answered natively for the
  resolution step.
- The stored save data could not be restored because the new class has no
  `Load()` function (the logged `Loading failed` warning) — the explicitly
  documented engine-native surface for this composition (execution-path record,
  remaining native validation requirement 2).
- The instance then died unexpectedly (`The script died unexpectedly.`,
  attributed to the GameScript by the adjacent `[18]` Save warnings) within
  ~0.4 s of the marker, i.e. inside the capture's readiness window. The
  runner's fail-closed fatal-log health check fired first, so the short-circuit
  happened **before** the byte-forecast page-1 timeout path; result identical
  in kind: fail-closed, zero exchanges, no silent retry. The precise Squirrel
  root cause is not determinable from the retained logs and was not further
  probed (no second launch authorized).
- The base graphics evidence gate not withstanding (`Using the OpenGFX base
  graphics set` was present), other pre-connect gates never executed: no
  welcome identity was observed and the staged dictionary
  `runtime-identity.json` was never written.

## Result integrity

`result.json`: `status = FAILED_CLEANUP`, `launches = 1`, `connections = 0`,
`requests = 0`, `pages = 0`, `requested_pages = 90`, `mutations = 0`,
`response_bytes = 0`, failure `RUNTIMEERROR / "Native script/asset error"`.

Cleanup semantics (retained verbatim in `cleanup.json`): the owned process was
reaped cleanly (`quit_requested`, `reaped`, returncode 0, no remaining
processes), the staged credential was removed (`.admin-secret` no longer
exists), endpoints closed (ports 33209/51519 freed, verified post-run), but the
strict chain marked the cleanup failed: the final fatal-log health check
reports the (by now expected) fatal script-death marker, so
`verify_cleanup_endpoints` refuses "Endpoint closure requires unambiguous owned
process reap" (its precondition includes empty `cleanup_error`), and staged
workspace disposal was intentionally skipped under that refusal. Therefore
`isolated/openttd-15.3-0bi44oib/` is retained as owned forensic state for this
consumed attempt. This is honest FAILED_CLEANUP evidence, not a leak: no live
credential, no open sockets, no resident process.

## Verification questions answered

- Real GameScript composition resolution: **partially proven** — the staged
  composition resolved against the save's stored identity and started; its
  instance then died unexpectedly and never served a request. Not proven:
  stable request servicing/end-to-end census exchange.
- Exact request/response correlation, schema-2 dispatch, 90-page census:
  **not exercised** (0 requests/pages; transport paths remain offline-proven
  only).
- Native ownership/occupancy, tile classification completeness, compatibility
  with retained TileFacts, classification receipt integrity:
  **not obtained** — no page responses exist.
- World/save identity: the welcome-identity gate never executed
  (`connected: false`); world correspondence is **NOT established** and no
  `correspondence-verdict.json` was produced. `TileClassificationSweep` was
  never invoked; nothing was fused into the retained record.
- Status of the 19 previously unknown tiles: **unchanged — still UNKNOWN** (the
  retained Seed 17 projection is historical fact; this capture produced no new
  classification evidence).
- P08 feasibility classification: **unchanged** — retained
  `INCOMPLETE_TILE_CLASSIFICATION` diagnosis (450 tiles = 339 ROAD_BUILDABLE +
  63 SUPPORTED_CLEARING + 19 UNKNOWN + 29 UNSUPPORTED; 24-tile corridor only
  through unknown-class tiles) stands untouched; the coal corridor remains
  unassessed with native taxonomy. In line with the world-correspondence
  policy, the failed capture is retained as this attempt's terminal evidence —
  a consumed one-shot native outcome — and no offline derivation may relabel it
  as a classification or correspondence success.
- Required construction operations: **no new statement** — the offline Task D
  readiness projection (per-class `requirement_for_tile_class` mapping) is
  unchanged; no native census binds it and no construction was executed or
  authorized.
- The SAME_SESSION_CENSUS fallback (180-request schedule) was **not used and
  remains review-only** (`same-session-accounting.json` untouched); binding it
  would require its own fresh reviewed candidate.

## Evidence inventory (all inside `artifacts/demos/classification-exec-seed17-e71c95a3/`)

| File | SHA-256 | Meaning |
|---|---|---|
| `result.json` | `7db905692bfbac4fe1e9802963cae6ec5155f1e66463036453aa7634de8a0f56` | Terminal capture result (FAILED_CLEANUP) |
| `capture-failure.json` | `753bd1d959984b4c5c72f3d3b498e78d602bea97efda469619c57d7f29a3e733` | Bounded failure record (RUNTIMEERROR, 0 pages) |
| `stderr.log` | `57a11449cb413b530ac1c20a8b29ac66f9c9791da1f261028396fc0b868b2dd3` | Native script-death evidence (verbatim above) |
| `stdout.log` | `239836d45516d94ded30a5dbcf255e00524a51f450183a7e3de28c2ed2df8e09` | Quit-time failure save acknowledgement |
| `failure.sav` | `ee21468cdc2e4ddabfc85a6f592763313baea843a49f10ea9cf29cc04cb99932` | Native world snapshot at terminal (61,616 B) |
| `CLAIM.json` | `693caed5dbd68f7c5e24e63e3c16dc9f07c113a1e8c8c57638523b81c57b7364` | Consumed one-shot claim (prelaunch digest `6acbd4970e4b38869fefadcef4005a1e919f969b2b208a8a84a39c4f0f332d34` = the sealed `PRELAUNCH.sha256`) |
| `cleanup.json` | `b3130c069bbc6c4a9eb348c5258d6a75438569466fc5b784120d362f32982f6b` | Cleanup honesty record (FAILED_CLEANUP cause chain) |
| `artifact-manifest.sha256` | (refreshed by the runner) | Post-terminal file enumeration |

Sealed preparation inputs (mtime 2026-10-18 11:20, before the 11:32 run)
`CANDIDATE.json`, `PRELAUNCH.json`, `PRELAUNCH.sha256`,
`classification-requests.json`, `receipts-required.json`, `AUTHORIZATION_REQUIRED.json`,
`same-session-accounting.json`, `save-correspondence.json`, `graphics-identity.json`
are byte-preserved; the staged workspace `isolated/openttd-15.3-0bi44oib/` is
retained as owned forensic state (see Cleanup semantics).

## What a future authorized attempt must change

1. A new reviewed execution candidate (this one-shot is consumed; re-running
   `750167949a4f46af…` is refused by its own consumed claim).
2. The composed classification GameScript must address the native save-load
   behavior observed here — the stored save data cannot be restored without a
   `Load()` hook and the instance died immediately after starting (root cause
   not visible in the retained logs). Candidate remedies for such a candidate
   (all need fresh review and fresh authorization): ship a compatible
   `Load()/Save()` pair in the staged composition; or run the census on a fresh
   generation correspondence mode (`FRESH_GENERATION_FACT_COHERENCE`), which
   keeps the census but changes the fusion policy; or otherwise re-prepare the
   retained identity. No repair may be made silently and the retained
   classification/feasibility numbers remain frozen history regardless.
3. Everything else in the executable path (staging, transport, runner,
   correspondence policy, offline suites) needed no repair: the failure was
   native GameScript termination, and the runner/fail-closed chain behaved as
   documented.

No P07 delivery metrics are generated or claimed by this record. No commit,
push, stage, reset or clean was performed; the untracked root file `--version`
was never executed.
