# Requirements → evidence matrix (single consolidated view)

**Date:** 2026-10-25. Offline consolidation only. This matrix summarizes
already-retained evidence; it creates no native authority and does not relabel
any failed, rejected, consumed or sealed outcome. Status vocabulary:
`PROVEN`, `CONTROLLED`, `PREPARED`, `PARTIAL`, `FAILED`, `UNKNOWN`. A test or
offline derivation is not native proof.

| Requirement / acceptance condition | Status | Evidence | Remaining gap / boundary |
|---|---|---|---|
| Stable fixed-demo native gameplay: selected services, deliveries, revenue, spectator, P07, cleanup | **PROVEN** (native 15.3, scope-bound) | E1; `artifacts/demos/playable-demo-25d891bc…/` | No direct company control; no full OPEX/profit/ROI |
| Canonical create + fresh-process reload Q3 correspondence | **PROVEN** (historical engineering; reload-only) | E2; `artifacts/runtime/canonical-fleet-{create,reload}-q3/` | Purchase/dispatch/unpause not exercised |
| Random World generation, discovery, spectator, cleanup | **PROVEN** (Seed 17 native) | E4, E8 | Service execution is a separate, failed outcome below |
| Seed 17 native coal-pair feasibility through P08/P05 | **FAILED** (terminal), with complete-search infeasibility proof | E8, E9, E10 | Do not promise a feasible route; no retry of the consumed identity |
| Tile Classification V2 native census capture | **PROVEN** (capture only) | E16; `artifacts/demos/classification-exec-seed17-3a8f9e46/` | Capture success is not world correspondence |
| `SOURCE_SAVE_FUSION` correspondence / fusion gate | **FAILED / CLOSED** (sealed `REJECTED`, 83 disagreements) | E16, ADR-010 | Same-instant criterion structurally unmet; no relabeling |
| Offline V1/V2 semantic reconciliation (77 definitional / 6 temporal / 0 contradictions / 0 unresolved) | **CONTROLLED** (offline replay) | `reconciliation-report.json`; `docs/p08-v1v2-semantic-reconciliation.md` | Base remains `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED` |
| Six temporal tiles under ADR-012 (save-instant census authoritative for planning evidence) | **CONTROLLED** (policy layer) | ADR-012; `census-authority-policy-report.json`; `p08-policy-rebinding-report.json` | Planning evidence only; base keeps `TEMPORAL_SECOND_INSTANT` |
| Nineteen definitional retained-UNKNOWN tiles under ADR-013 (native `IsBuildable` → `TERRAIN_MODIFICATION`) | **CONTROLLED** (accepted policy, fail-closed offline) | E25; ADR-013; `native-isbuildable-policy-report.json` | Native `IsBuildable` semantics adopted by policy, not fresh native capture; base keeps `UNKNOWN_OCCUPANCY` |
| Combined P08 planning binding after ADR-012 + ADR-013 | **CONTROLLED** (`allowed: true`, `p08_complete: false`) | `p08-native-isbuildable-rebinding-report.json`; snapshot with both reports | Fusion gate closed; no native construction/delivery/execution evidence |
| D2 native clearing (tile 46769) | **PROVEN** (native, one tile) | E17 | One tile only; no road/service claim |
| D3 native clearing + bounded terraforming (finances reconcile) | **PROVEN** (native, scope-bound) | E19; post-D3 after-save `fbebef54…d59e` | No road/stop/depot constructed |
| D4 native road + station construction | **PROVEN — COMPLETE (native)** (four attempts consumed; candidate-5 verified 7/7 + route + authoritative after-save + replay `RECEIPT_VERIFIED`) | E21, E28, E29, E30, E31, E32, E33, E35 | `D4-CORRIDOR-1`: run-B exceeded per-op ceiling, only `op-00` verified. `D4-CORRIDOR-3`: 3/8 ops built; `op-03` redundant interior join was correctly `NOT_BUILDABLE` (`pairs_ok 1`); no authoritative after-save/receipt; historical cleanup remains `FAILED_CLEANUP`. `D4-CORRIDOR-4`: 6/7 verified, `op-06` halted by the then-hard-coded 512-byte response limit (no readback/receipt); cleanup PASS. E29/E33 are the offline v3 + 640-byte corrections. **`D4-CORRIDOR-5` (E35): all seven v3 ops verified with independent readbacks (amounts £785/£1,398/£1,151/£71/£307/£292/£390; funds £496,543 → £492,149 exact), `ROUTE_VERIFIED` 23/23, receipt-bound `after.sav` `a81ac836…ef261`, cleanup certified, manifest 90/90, read-only replay `RECEIPT_VERIFIED`** — the proof is exactly the reviewed v3 schedule over the D3-verified world, not vehicle/delivery/OPEX/ROI |
| D4 `D4-CORRIDOR-2` fresh candidate | **STALE / SUPERSEDED** (never consumed) | E24; `artifacts/experiments/d4-corridor-native-candidate-2/` | Frozen closure predates the ADR-012/ADR-013 source edits; read-only preflight now fails `verify_freeze`. Not edited or reused |
| D4 `D4-CORRIDOR-3` fresh candidate | **CONSUMED ONCE / PARTIAL** (`verified: false`) | E27, E28; `artifacts/experiments/d4-corridor-native-candidate-3/`; seal `8cc8c1f7…7d24`, payload `e1163d09…068d`, authorization `5484cdc1…3be705e` | `op-00`–`op-02` built and read back (£496,543 → £493,209); `op-03` interior join refused at admission, `op-04`–`op-07` and route read not executed; no receipt-bound after-save; replay refuses incomplete cleanup. Must not be retried or reused |
| D4 `D4-CORRIDOR-3` credential remediation | **CONTROLLED** (read-only, non-secret verification) | E30; `cleanup.json` sha `52e1055c…463d8f`; 48/48 manifest | `credential_removed: true`, `workspace_disposed: true`, workspace absent, `isolated/` empty, no candidate-3 secret/config file or process/listener. Historical `verification_error` and absent `sockets_closed` preserved; the outcome stays `FAILED_CLEANUP` and replay still refuses. No native success or authoritative after-save is claimed |
| D4 `D4-CORRIDOR-4` fresh candidate | **CONSUMED ONCE / PARTIAL** (`verified: false`) | E31, E32; `artifacts/experiments/d4-corridor-native-candidate-4/`; seal `88cd1ecc…fd22c3`, payload `4037c5d8…487c7f`, v3 plan digest `b5b472ff…2283a78`, authorization `b069b484…5db6d` | 7 road ops, 22 planned exchanges, cap 28, per-op ceiling £2,000, no redundant interior join, perpendicular corner retained; source world `fbebef54…d59e`; `op-00`–`op-05` verified (£4,004), `op-06` depot rejected by response-size limit, no authoritative `after.sav`/`receipt.json`; cleanup PASS; replay raises `MalformedMessage`. Must not be retried or reused; D4 remains INCOMPLETE (native) |
| D4 `D4-CORRIDOR-4` native cleanup | **PASS** (current attempt) | E32; `cleanup.json`; 80/80 manifest | `reaped: true`, `sockets_closed: true`, `workspace_disposed: true`, `credential_removed: true`, `cleanup_error: []`, return 0; workspace absent and no process/listener. The historical candidate-3 cleanup remains `FAILED_CLEANUP` and is not rewritten |
| D4 protocol-4 response bound | **CONTROLLED** (offline fix and regression) | E33; `docs/handoff/2026-10-25/d4-corridor-response-limit-fix.md`; `app/simulation/openttd/gamescript_transport.py`; `app/simulation/openttd/corridor_construction.py`; `app/simulation/openttd/proof/corridor_construction_native.py`; focused tests 129 PASS | Version-one decode default remains 512; protocol 4 explicitly uses 640; the retained 517-byte depot frame (513-byte JSON payload) decodes and correlates to a `BUILT` readback. Exact 640 passes, 641 fails; malformed/truncated/duplicate-key/invalid-UTF-8 bodies fail closed; multibyte UTF-8 is measured in bytes; an application bound may never exceed the 32763-byte frame-body maximum. The fix does not create a receipt, verify the consumed attempt or complete D4; replay still refuses for the missing `depot-06-response.json`/confirmation |
| D4 `D4-CORRIDOR-5` (staged 2026-10-25, prepared + independently reviewed) | **PREPARED / INDEPENDENTLY REVIEWED** (never consumed at review time) | Preparation record `docs/handoff/2026-10-25/d4-corridor-native-candidate-5-preparation.md` (reviewer verdict PASS 20/20); `artifacts/experiments/d4-corridor-native-candidate-5/`; seal `505b5d49…4a7c`, payload `77a965f0…0e4` (2,307 canonical bytes), v3 plan digest `b5b472ff…2283a78`, 3,448-entry frozen closure | Fresh candidate staged from current reviewed source after E33's one-identity advance; all offline gates re-verified 2026-10-26 before signing (preflight, protocol statics/dynamics, 129/129 focused suites, runtime clean, never-consumed state). PENDING_AUTHORIZATION at review close; signing and the native attempt required separate explicit operator authorization |
| D4 `D4-CORRIDOR-5` native outcome | **CONSUMED ONCE / PROVEN** (`verified: true`, `NATIVE_CORRIDOR_VERIFIED`, replay `RECEIPT_VERIFIED`) | E35; `artifacts/experiments/d4-corridor-native-candidate-5/`; authorization `55486971…dec03`, operator identity `sha256-ed25519-public-key:cbb63ff5…40c614` | Signed under explicit operator authorization via the approved checklist (seed never displayed, signature verified before writing). Attempt: 1 launch / 1 connection / 22 of 28 requests; all 7 ops verified with costs = positive tested quotes ≤ £2,000 each (total £4,394; £496,543 → £492,149 exact); `confirm-06` finally exists (`depot-06-response.json`, 513-byte payload, under the 640-byte bound); route `ROUTE_VERIFIED` 23/23; authoritative `after.sav` `a81ac836…ef261`; cleanup certified (4/4 true, rc 0); manifest 90/90; read-only replay `RECEIPT_VERIFIED`. Proof is exactly the v3 scope — no vehicle/delivery/OPEX/ROI claim; consumed identity must not be retried or reused |
| Repository authority-pin integrity | **PROVEN** (offline, explicit repair) | E26; ADR-014; `docs/authority/context-authority-supersession.json` | Historical 2026-10-08 bytes are not retained; the record scopes only the exact path/digest transition, all other entries remain byte-exact |
| P07 offline analytics extension | **CONTROLLED** (offline; advisory) | P07 analytics record; retained Attempt 19/fixed-demo evidence | No new native OPEX/profit/ROI facts |
| Native execution attempt analytics (run-level metrics, lineage comparison, schedule-revision observations) | **CONTROLLED** (offline; read-only; integrated) | E34; `docs/native-attempt-analytics.md`; `app/experiments/native_attempt_analytics.py`; `app/experiments/cli.py` (`analyze-native-attempts`); deterministic example `artifacts/experiments/native-attempt-analytics-example/` | Consumes retained `PRELAUNCH.json`/`result.json`/`cleanup.json` only; statuses and verified flags copied verbatim, unverified attempts never counted as verified successes; OPEX/net-profit/ROI stay UNKNOWN; no native evidence is created or re-verified; D4 remains INCOMPLETE (native) |
| Full OPEX / net-profit / ROI | **UNKNOWN** | — | Never invent; requires native accounting evidence |
| Native execution / AdminPort / signing / candidate consumption for ADR-013 | **NOT AUTHORIZED** | Operator authorization (2026-10-25) | Explicitly excluded from the ADR-013 authorization |

## Key boundaries

- `p08_binding.allowed: true` in the combined rebinding is **planning
  classification only**. It is not a fusion verdict, not native proof and not
  completion of P08 (`p08_complete: false`).
- The sealed fusion verdict remains `REJECTED`; the fusion gate remains
  **CLOSED**.
- The base reconciliation ledger and all consumed/frozen evidence remain
  byte-unchanged; ADR-013 changes only the derived policy view.
- Native proof for the 19 tiles, D4 completion and full OPEX/ROI remain
  uncollected and require separate authorization.
- `D4-CORRIDOR-2` is stale by construction (later accepted source edits); it is
  not launchable and must not be edited or reused. `D4-CORRIDOR-3` was the only
  launchable candidate at the time, was consumed exactly once on 2026-10-25, and
  must not be retried or reused. Its `after-diagnostic.sav` is not an
  authoritative save. E29 corrects the `op-03` defect offline: the interior join
  was redundant because collinear `BuildRoadFull` endpoints auto-connect; v3
  schedules 7 ops and keeps the perpendicular corner join. E30 verifies the
  candidate-3 credential removal and workspace disposal as a separate later
  event, but its historical cleanup certification remains failed
  (`sockets_closed` absent) and no native success is implied. The cleanup
  certification is attempt-scoped: it does not block a fresh candidate, but the
  current isolation conditions (no process, listener, workspace or staged
  secret) were independently verified before signing E32. `D4-CORRIDOR-4` was
  consumed once from v3 after `PRELAUNCH PASS` + `PREFLIGHT PASS`; `op-00`–
  `op-05` verified, `op-06` was rejected at the then-hard-coded 512-byte response
  limit after the native log reported `BUILT`, cleanup passed, and no
  authoritative `after.sav`/`receipt.json` exists. E33 corrects the decoder
  offline: protocol 4 now uses its documented 640-byte bound while the
  version-one 512-byte default is unchanged. The retained 513-byte depot payload
  parses, but replay still refuses because the client never persisted
  `depot-06-response.json` and no confirmation/receipt exists. A fresh,
  independently reviewed candidate (`D4-CORRIDOR-5`) was then staged from the
  corrected source, and on 2026-10-26 — under explicit operator authorization
  and after every pre-signing gate was re-verified — it was signed and consumed
  exactly once (E35): all seven v3 operations verified, route `ROUTE_VERIFIED`
  23/23, authoritative receipt-bound `after.sav`, cleanup certified, manifest
  90/90, and the read-only replay verdict `RECEIPT_VERIFIED`. **Milestone D4
  native road and station construction is COMPLETE for exactly the reviewed v3
  scope.** This record authorizes no further native execution: the candidate
  claim is consumed, and any next attempt (e.g. D5 vehicles/orders/delivery)
  needs a fresh reviewed candidate and a fresh explicit operator authorization.
