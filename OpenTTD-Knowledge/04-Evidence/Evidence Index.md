---
title: "Evidence Index"
type: evidence
status: current
updated: 2026-10-22
tags:
  - openttd
  - evidence
---

# Evidence Index

Condensed view of E1–E21 from [[99-Source-Documents/EVIDENCE_INDEX]] (canonical). Hashes
identify bytes; they do not authenticate outcomes nor replace production
seals/protection manifests. Existing attempts remain immutable. Addenda dates: E1–E13
from the 2026-10-17 index; E16 from 2026-10-18; E17/E18 from 2026-10-21; E19/E20/E21
from 2026-10-22.

> Note: the 2026-10-18 *offline V1/V2 semantic reconciliation* work (see
> [[05-Planning/Blockers]]) is **not** assigned an E-ID by EVIDENCE_INDEX; it is
> preserved as uncommitted record(s) in the working tree. Represented here for
> navigation, with that status explicit.

| ID | Retained source (repo-relative) | Supported proposition — and limits |
|---|---|---|
| E1 | `artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a/` (result.json, receipt.json), `artifacts/demos/playable-demo-25d891bc9f3444aca73058165d10055a-report/results.md`, smoke-verification `…/smoke-review-210cd759…/verification.json` | 3 services/vehicles, 60 coal, £1,022 revenue, £28,459 CAPEX; spectator inspection, P07, cleanup, integrity PASS. No direct company control or full OPEX/ROI. |
| E2 | `artifacts/runtime/canonical-fleet-create-q3/`, `…canonical-fleet-reload-q3/` (result.json, reload-correspondence.json) | Native creation then exact reload-only correspondence; source save sha `51e45689…97eb`. 0 mutations, paused, heartbeat advances. No purchase/dispatch/unpause proof. |
| E3 | `artifacts/runtime/openttd-15.3-first-freight-delivery-attempt19/result.json`, `artifacts/experiments/attempt19-offline-recovery/` (derived-finalization.json, verification.json), `docs/five-year-freight-performance-analysis.md` | Five economy years within separate offline recovery scope. Original FAILED terminal unchanged (finalization collided with existing company-policy.json). |
| E4 | `artifacts/demos/playable-demo-b84b9bd854a342f1a86e4ba669d8e450/result.json`, `random-smoke-correction-b84b9bd…/native-smoke-summary.json`, `postrun-independent-review.json` | Native generator/settings, 10 industries, 11 cargos, 6 compatible pairs, spectator + cleanup verified; terminal FAILED, P05 NOT_RUN, no construction/delivery. Funding setup separate. |
| E5 | `docs/random-world-distance-support.md`, `artifacts/demos/random-distance-seed17-offline-20261017/` (admission analysis, controlled pipeline, review) | 450-tile coal rectangle newly admitted for observation. Synthetic flat pipeline = 1 candidate/service; no native terrain/engine capture. Prior suites 149/135 PASS with overlap — not summed unique count nor fresh run. |
| E6 | `docs/handoff/2026-10-17/` (environment.json, git-status-before.txt, implementation-before.json, ignored-paths-before.txt) | Checkout identity, uncommitted implementation, local-only inventory. No credentials copied; no staging/commit/push. |
| E7 | `docs/random-world-observation-inventory.md` | Offline verification + independent review: observation pipeline implemented, suites green (90+297+216, 11 skipped); no native observation collected. Native Seed 17 facts UNKNOWN (at that record's date). |
| E8 | `docs/seed17-native-smoke-preparation.md` + `artifacts/demos/random-smoke-review-698799a2d…/` and consumed `playable-demo-698799a2d…` | One-shot smoke consumed 2026-10-17: preflight 12/12 PASS, 145 s, world identity verified, native facts complete (coal capture 462/462), P08 `NO_BOUNDED_CORRIDOR` → 0 candidates → P05 NOT_RUN → `NO_FEASIBLE_SERVICES`; no construction/delivery; cleanup fail-closed; diagnostics retained. Delivery/OPEX/profit/ROI UNKNOWN. |
| E9 | `docs/p08-bounded-terrain-aware-routing.md`, `docs/p08-bounded-routing-review.md`, retained `artifacts/demos/playable-demo-698799a2d…/network-facts-0.json` | Bounded terrain-aware reachability oracle; frozen corridor regression intact; retained Seed 17 replay proves coal catchments disconnected in the supported corridor graph (17 water, 50 trees, 13 rough, 12 industry, 19 steep tiles) → complete-search proof, not first-four-stop artifact. Native feasibility/delivery/OPEX UNKNOWN. |
| E10 | `docs/p08-bounded-terrain-modification-support.md`, `docs/p08-bounded-terrain-review-modification.md`, `app/planning/p08_terrain.py`, tests `tests/test_p08_bounded_terrain.py` (14 PASS) | Offline planning contracts for bounded levelling (15.3 terraform surface verified; typed budgets; planning-only proposals). Retained replay: deterministic `NO_CONNECTED_LEVELED_CORRIDOR` (176 expansions; all 23 height-step adjacencies fenced by forbidden-class tiles). Native terraforming feasibility UNKNOWN at record date (later proven in D3, E19). |
| E11 | `docs/p08-native-tile-classification.md`, `tile_classification.py` + `terrain_classification.nut`/bridge, `p08_terrain.py`, `construction_readiness.py`, tests 13+24 PASS | Additive schema-2 wire, five segment classes, conflicts→UNKNOWN, three-tier feasibility, construction-readiness registry, additive diagnostics. Retained assessment: 450 = 339 ROAD_BUILDABLE + 63 SUPPORTED_CLEARING + 19 UNKNOWN + 29 UNSUPPORTED; `INCOMPLETE_TILE_CLASSIFICATION`. |
| E12 | `docs/p08-classification-v2-native-capture-preparation.md`, receipt/exchange/sweep + staging modules, tests 16+7+9(+1) PASS | Offline preparation of ONE fresh V2 census attempt: 90 pages ≤256 tiles (census 15×30 → bands 15×17+15×13), budgets page 103 / bytes 52,324; sweep binding to retained TileFact; refuse-on-missing-seam staging → `PENDING_AUTHORIZATION` candidate; launch template pinned. |
| E13 | `docs/p08-classification-v2-execution-path.md`, `proof/classification_execution.py`, `classification_capture.py`, `world_correspondence.py`, gamescript schema-2 dispatch, tests 10+10+10+8 PASS offline | Four execution blockers implemented online-capable, validated offline; realized candidate `artifacts/demos/classification-exec-seed17-e71c95a3/` (composition `e71c95a3fde6202c`, attempt `750167949a4f46af`). |
| E14 | `docs/p08-classification-v2-native-capture-outcome.md`, consumed attempt evidence in `artifacts/demos/classification-exec-seed17-e71c95a3/` | ONE authorized launch consumed; capture **FAILED** with 0 requests/0 pages: bridge started (`BRIDGE_STARTED protocol=1 api=15`) but save data could not restore without a `Load()` hook → instance died in readiness window; runner failed closed; terminal `FAILED_CLEANUP`; claim consumed; SAME_SESSION fallback untouched/review-only. 19 unknown tiles remain UNKNOWN. |
| E15 | `docs/p08-classification-v2-native-capture-diagnosis.md`, repair in `classification_capture.py` + `classification_execution.py`, tests 35 PASS (incl. 9 log-health + 6 AI-staging regressions) | Offline repair: misattributed benign dummy-AI fallback death re-diagnosed (15.3 sources + pinned binary); health vocabulary extended (fallback wording fatal, `[S]` tripwire, single strict exemption); SOURCE_SAVE staging of stored AI `RoadProofCompany`/1 sealed in composition; fresh candidate `classification-exec-seed17-3a8f9e46` staged `PENDING_AUTHORIZATION`, preflight PASS; no launch/claim. |
| E16 | `docs/p08-classification-v2-native-capture-completion.md`, consumed attempt evidence `artifacts/demos/classification-exec-seed17-3a8f9e46/` | Repaired one-shot consumed; capture **SUCCEEDED IN FULL** (`TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT`): 90/90 pages, 450/450 tiles, staged AI+GameScript startup, 0 script deaths, 0 mutations, byte budgets held, cleanup complete. **SOURCE_SAVE_FUSION verdict REJECTED** (83 `PROJECTED_FLAGS_DIFFER`); nothing fused; 19 UNKNOWN stay UNKNOWN; P08 stays `INCOMPLETE_TILE_CLASSIFICATION`; offline rebinding byte-equal; 198-file manifest verifies. Capture success ≠ world correspondence. |
| E17 | `docs/handoff/2026-10-21/d2-native-clearing-candidate-3-outcome.md` + `artifacts/experiments/d2-clearing-native-candidate-3/` (PRELAUNCH/CLAIM/LAUNCH-CONSUMED/Auth, 4 exchange pairs, receipt, result, saves, 25-file `artifact-manifest.sha256`) | ONE operator-authorized launch consumed → **Milestone D2 PROVED**: tile 46769 cleared (£15 = cash delta £500,000→£499,985), `NATIVE_STATE_VERIFIED`, 1 launch/1 X25519 connection, revision 15.3 seed 17; claim `d2-clearing-claim-authorization-v2` consumed; record-writing session did NOT initiate the launch; limits: one tile; no more. |
| E18 | `docs/handoff/2026-10-21/d3-native-integration-preflight-preparation.md`, `proof/terrain_terraform_native.py`, tests 23 PASS, staged `artifacts/experiments/d3-clearing-native-candidate-1/` | Offline preparation of the D3 chain as three one-shot candidates reusing proven D2 machinery; candidate-1 staged prelaunch; awaiting operator signature; no launch. |
| E19 | `docs/handoff/2026-10-22/d3-terraform-native-candidate-1-outcome.md` + three consumed evidence dirs | **Milestone D3 PROVEN** end-to-end: clears 45999 (£30) + 49326 (£45), terraforming 16 S-corner raises (£3,382, 16/16 `NATIVE_STATE_CHANGED`); all `RECEIPT_VERIFIED`; finance £500,000−£30−£45−£3,382 = **£496,543**; authoritative after.sav `fbebef54…d59e`; 27/27 geometry agreement; post-D3 corridor flat/CLEAR/unowned. |
| E20 | `docs/handoff/2026-10-22/d4-corridor-native-candidate-1-preparation.md`, `corridor_construction.py` (v4), `d4_corridor_package/main.nut`, `proof/corridor_construction_native.py`, tests 21+26 PASS, staged `artifacts/experiments/d4-corridor-native-candidate-1/` | Offline **D4 staging**: one candidate bound to the verified post-D3 world; 6 ops / 19 planned exchanges; budgets (25 requests, ≤512 B requests, ≤640 B responses, 900 s); `PRELAUNCH PASS` + read-only `PREFLIGHT PASS`; `PENDING_AUTHORIZATION`; no claim, nothing launched. |
| E21 | `docs/handoff/2026-10-22/d4-corridor-native-candidate-1-outcome.md` + consumed attempt evidence `artifacts/experiments/d4-corridor-native-candidate-1/` (consumed one-shot claim, `LAUNCH-CONSUMED.json`, 4 retained exchange pairs + `frames.json`, per-op evidence, retained saves, 28-file manifest; **no `receipt.json`**) | The ONE authorized launch was consumed; `PHASE_HALTED_PREFIX_PRESERVED`, **`verified: false`** over 4/19 planned requests → Milestone D4 **INCOMPLETE**. Verified prefix `op-00` only (5 tiles, £785, funds £496,543→£495,758, `NATIVE_STATE_CHANGED`); `op-01` refused at admission (£2,549 > £2,000 ceiling, no command issued); `op-02`–`op-05` and the route read never executed. Offline replay-verifier repair (26→29 PASS, wire 21 PASS, `PASS WITH CONCERNS`). Frozen closure never edit/reuse; fresh candidate + fresh authorization required — none staged/authorized. |

## Historical index note

Detailed historical indexes + hashes live in
`docs/handoff/2026-10-17/previous-EVIDENCE_INDEX.md`; they describe older snapshots and
are not the current checkout inventory. Fresh documentation/source-preservation validation:
`docs/handoff/2026-10-17/validation.md` — independent of native acceptance.

Navigation: [[04-Evidence/Native Verification]] · [[04-Evidence/Controlled Tests]] ·
[[04-Evidence/Failed Attempts]] · [[04-Evidence/Evidence Preservation]] ·
[[99-Source-Documents/EVIDENCE_INDEX]] (canonical full text).
