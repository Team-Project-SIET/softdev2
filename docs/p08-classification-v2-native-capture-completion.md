# P08 Tile Classification V2 — native capture completed, correspondence REJECTED

**Date:** 2026-10-18 13:25 (+0700). The operator-authorized one-shot launch for
the repaired execution candidate
`artifacts/demos/classification-exec-seed17-3a8f9e46/`
(attempt `556e97b81230bfd39d2146c6e05885c5492e416dde2e26513ef42916029d94ed`,
composition `3a8f9e46969687b68af7a69adb391c2c5e6d93c1bd13050f9e1d638505da4886`,
correspondence `SOURCE_SAVE_FUSION`) was consumed by one native OpenTTD 15.3
launch ([E14]/[E15] record the consumed failed predecessor). The claim is used
(`CLAIM.json`: `consumed: true`, `launches_allowed: 1`, `retries: 0`,
`prelaunch_digest = 1c96b6c8…fabc`, matching `PRELAUNCH.json` in
`artifact-manifest.sha256`); consuming retries none and none is authorized:
**never retry a consumed identity**.

**Terminal result: `TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT`.** The census
capture itself succeeded in full; the native capture is therefore NOT equivalent
to successful world correspondence. The `SOURCE_SAVE_FUSION` verdict is
**`REJECTED`** — nothing was fused into the retained record and the retained P08
assessment is unchanged. Composed main and staged bytes were verified in the
completion doc preflight; the launch argv equals the sealed records:

```
/home/fed/Downloads/openttd-15.3-linux-generic-amd64/openttd \
  -D127.0.0.1:56299 -c <workspace>/openttd.cfg -x -X \
  -g <workspace>/source.sav -dscript=4,grf=1,net=3
```

## Execution (all numbers read from the retained artifacts)

| Item | Result |
|---|---|
| Launches / connections | 1 / 1, encrypted X25519 admin (`result.json.auth.state=ACTIVE`), pid 118415 |
| Welcome identity | revision `15.3`, seed `17`, 256×256, landscape 0, dedicated (`runtime-identity.json`) — `world_identity_mismatch: false` |
| Census | 90/90 pages requested and exchanged, 2 bands (`[170,171,15,17]` + `[170,188,15,13]` over the 15×30 = 450-tile region), schema 2, protocol version 3 |
| Coverage | 450/450 tiles classified; fresh classes CLEAR 359, TREES 52, WATER 17, INDUSTRY 12, ROUGH 10; `unknown_tiles: []` in the fresh census |
| Bytes | 33,613 total response bytes = the sum over the 90 retained envelopes; max page 381 B ≤ 508; max request 142 B ≤ 159; total ≤ 52,324 budget |
| GameScript/AI startup | `[18] BRIDGE_STARTED protocol=1 api=15`; staged AI package `RoadProofCompany` started (`[0] [I] ROAD_PROOF_COMPANY_READY`); **zero** `The script died` lines and **zero** `[E]` lines for this run (contrast [E14]) |
| Mutations | 0 |
| Cleanup | completed: `quit_requested`, reaped returncode 0, sockets closed, listener closed, credential removed, reservation released, workspace disposed (`cleanup.json`) — cleaning PASSED this time |
| Script liveness | `BRIDGE_REQUEST_RECEIVED`/`TILE_CLASSIFICATION_READ`/`BRIDGE_RESPONSE_SENT`/`BRIDGE_POST_RESPONSE_ALIVE` cycles through page 89 (`has_more: false`); `(request_id="seed17-tile-classification-v2", region, cursor)` keying exercised for all 90 pages |

## Correspondence verdict (the decisive outcome)

`correspondence-verdict.json` = `result.json["verdict"]`:
`status = REJECTED`, mode `SOURCE_SAVE_FUSION`, statement:

> "classified or freshly re-observed tiles contradict the retained TileFacts;
> nothing was fused and every contradiction is recorded"

- **83 tiles disagree with the retained projection** (`PROJECTED_FLAGS_DIFFER`;
  83 identical entries in `classification-completeness.json coherence_failures`
  and the verdict's `tile_disagreements`).
- `fresh_fact_contradictions: []`, `identity_failures: []`,
  `accounting: null`; rejection is caused purely by projected-flag
  disagreements, logged by `TileClassificationSweep.record`
  (`tile_classification.py`: any disagreement means the two records could not
  have been captured in the same instant, so the census stays unbound).
- The sweep is therefore **unbound** (`bound=false`) →
  `TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT` per
  `classification_capture.py`.

## Fresh census vs the retained historical assessment (independent offline rebinding)

An offline re-binding of the retained page bytes through the project's own code
(`TileClassificationRequest.parse` + `TileClassificationReceipt.correlate` +
`TileClassificationExchange.validate` + `TileClassificationSweep.record`, no
launch) reproduced the run on 2026-10-18:

- `classification-completeness.json` reproduced **byte-equal**; coherence
  failures recomputed as the same **83** (tile, code) map as recorded.
- Historical legacy segmentation of the retained
  `playable-demo-698799a2dfb146948fd2983ff2032253/network-facts-0.json`
  (sha `9e4c5c4225b697312230deae40989de643bcdd79db1063cf6eda9fa365d8bb6e`,
  equal to the sealed `retained_facts_sha256`) reproduces
  339 ROAD_BUILDABLE + 63 SUPPORTED_CLEARING + 19 UNKNOWN + 29 UNSUPPORTED.
- The **19 historically UNKNOWN tiles** (projection-dropped occupancy — house/
  station-shaped tiles whose same-instant class the retained projection could
  not recover) were all observed **CLEAR with the buildable predicate** in the
  fresh census, and all 19 are inside the 83 disagreements. Under the
  world-correspondence policy they are **observed, recorded and NOT accepted**
  into the historical fused assessment: an agreeing ground claim over a dropped
  flag projection must stay rejected because the observations cannot be proven
  same-instant (pinned in `classify_segment`
  "conflicting-occupancy-evidence" semantics and the workflow tests).
- Consequently the retained P08 diagnosis stays exactly
  `INCOMPLETE_TILE_CLASSIFICATION` (24-tile corridor only through
  unknown-class tiles; 724 expansions) — the fresh capture is evidence of
  contradiction, not equivalence, and was not fused.

## Result integrity verification (offline, read-only)

- `artifact-manifest.sha256`: **198 listed files, 198 SHA-256 matches, zero
  mismatch, zero extra unlisted files** in the candidate directory.
- All 90 `classification-receipts.json` entries re-correlate: per-page
  `request_payload_sha256`/`response_payload_sha256` equal re-hashes of the
  retained page files; page indexes are in exact 0..89 order.
- Budgets held inside the run and in the roll-up; no `capture-failure.json` and
  no fatal health findings were produced (in contrast to [E14]).

## What this does NOT establish

- World correspondence between the fresh source-save world and the retained
  facts is **REJECTED**, not established; 83 tiles cannot be bound same-instant.
- No construction readiness claim, no P05 run, no delivery — the census is
  classification-only (0 mutations).
- The 19-tile question stays UNKNOWN in the historical fused assessment; a
  semantic reconciliation (accepting fresh classes as superseding observations
  under a new authorized world contract) is **future work and was not
  performed** — nothing in this record may be read as advancing it.
- The `SAME_SESSION_CENSUS` fallback stays review-only (`same-session-accounting.json`
  untouched, `tile_facts_requests: 0`).

## Evidence inventory (all inside `artifacts/demos/classification-exec-seed17-3a8f9e46/`)

| File | Meaning |
|---|---|
| `result.json` | Terminal capture result (`TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT`, verdict REJECTED, 83 disagreements) |
| `correspondence-verdict.json` | Read-only duplicate of the verdict inside `result.json` |
| `classification-completeness.json` | Machine-readable census summary (90 pages/450 tiles/83 coherence failures/retained-facts digest) |
| `classification-receipts.json` + `classification-p000..p089-request/-response.json` | Per-page correlation receipts and exact request/response bytes |
| `artifact-manifest.sha256` | SHA-256 manifest over all 200 candidate files |
| `CLAIM.json` | Consumed claim (1 launch, 0 retries) |
| `PRELAUNCH.json` + `PRELAUNCH.sha256`, `CANDIDATE.json`, `AUTHORIZATION_REQUIRED.json`, `save-correspondence.json`, `runtime-identity.json`, `graphics-identity.json`, `same-session-accounting.json` | Sealed pre-launch identity chain of the repaired candidate |
| `stdout.log`, `stderr.log` | Native logs (Startup AI/GameScript markers; final admin disconnect + graceful shutdown) |
| `cleanup.json` | Completed cleanup verification (contrast [E14]) |
| `isolated/` | Workspace disposal remnants of the owned isolated runtime |

Consumed attempt evidence is retained in place; no historical or frozen records
were modified by this capture or by this documentation.
