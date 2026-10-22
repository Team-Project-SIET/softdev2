# Continuation tasks — 2026-10-17

Read AI_HANDOFF, CONTEXT and EVIDENCE_INDEX first. This list grants no runtime
authority. Current product priority is the stable demo plus bounded Random World.
Canonical creation/reload Q3 are historical PROVEN milestones, not pending tasks.

1. **Offline transfer verification.** Compare branch/HEAD, dirty paths and source
   hashes with `docs/handoff/2026-10-17/`. Confirm required ignored artifacts exist
   and verify selected evidence hashes. Report missing bytes as UNKNOWN. Done:
   reviewed source/evidence inventory, no secret transfer and no historical edits.
2. **Offline fresh random readiness.** Review the 512-tile profile, legacy 256
   compatibility, staged bridge, capture budgets, qualified-month window, native
   47-tile path filter, P05 timeout, diagnostics/replay and cleanup. Run focused
   controlled tests from REPRODUCE. Prepare only a new uniquely named package if
   preparation is requested; preserve consumed sources and claims. Done: concrete
   frozen-input identity and independent preflight report, with staleness and
   runtime blockers explicit; zero launches/Admin connections during preparation.
3. **Separate authorization: one new Seed 17 native smoke.** Use seed 17, 256×256,
   temperate/terrain 0/towns 1/industries 2, freshly frozen current code and finite
   settings/budgets. One server and encrypted Admin session; spectator only when
   included in the reviewed scope. Capture all required tiles, coverage, settings,
   engines and same-session source correspondence. Run P08/P05 only on admitted
   native facts. Retain diagnostics on infeasibility; no retry/reconnect. Done:
   independently replayable generation/qualification/capture, explicit candidate
   and selection results, any authorized construction/delivery receipts, and full
   owned-runtime cleanup. A valid unsupported-world result remains distinct from
   a successful delivery. Do not promise the coal pair will yield a feasible road.
   The offline readiness/observation-inventory record is
   [the observation inventory](docs/random-world-observation-inventory.md).
   The prepared, independently reviewed fresh smoke identity for the
   future authorized one-shot run (run dir `playable-demo-698799a2d…`, frozen
   inputs, verdict with all 9 offline preflight checks PASS, launch command,
   capture checklist, budgets, cleanup plan) is
   [the smoke preparation record](docs/seed17-native-smoke-preparation.md).
   **Update:** that authorization was consumed (one-shot, 2026-10-17). Native
   facts were complete but P08 found `NO_BOUNDED_CORRIDOR` on the only
   capturable pair (coal), giving 0 candidates, P05 not run and
   `NO_FEASIBLE_SERVICES`; no construction or delivery. Read the record's
   "Consumed outcome" section for the retained evidence.
4. **Offline P07 continuation after accepted delivery.** Replay into a fresh sibling
   output. Verify per-service totals, charts/history, world/seed/plan attribution,
   null/UNKNOWN behavior and comparisons. Done: reproducible reports with native
   measurements distinct from derivations; no invented OPEX/profit/ROI.
5. **Later product work, separately scoped.** Improve support for obstructed terrain,
   long corridors, >32 industries or larger maps only with explicit contracts and
   bounded observation/search/execution. Current implementation does not support
   arbitrary slopes, clearing, bridges/tunnels or arbitrary-world road feasibility.
   **Update (2026-10-17, offline):** P08 now runs a bounded terrain-aware
   reachability oracle before candidate selection, and the retained Seed 17
   `NO_BOUNDED_CORRIDOR` was proven a complete-search infeasibility for the coal
   pair (construction-extension classification included; no supported construction
   connects it). See
   [the bounded routing record](docs/p08-bounded-terrain-aware-routing.md).
   **Update (2026-10-17, second, offline):** bounded terrain-modification
   planning/validation is implemented (`app/planning/p08_terrain.py`, hooked
   into both `NO_BOUNDED_CORRIDOR` branches of `generate_road_scenario` as
   planning-only diagnostics): the retained Seed 17 levelling question is
   answered structurally — all 23 height-step adjacencies are fenced by
   unclassifiable obstruction tiles (house/station class dropped by the
   `TileFact` projection), so `NO_CONNECTED_LEVELED_CORRIDOR` reproduces and
   nothing connects the coal pair even with levelling classified. Native
   execution stays unsupported pending a fresh authorization. See
   [the bounded terrain-modification record](docs/p08-bounded-terrain-modification-support.md).
   **Update (2026-10-17, third, offline):** native tile classification and
   generalized feasibility are implemented additive-only: schema-2
   `tile_classification_page` contracts plus a composed classification bridge
   (no frozen path changed; the capture still requires a fresh one-shot
   authorization), five deterministic corridor segment classes with
   conflicting evidence downgraded to UNKNOWN (never inferred), a three-tier
   bounded `assess_world_feasibility` diagnosis (world identity, industry
   relationship, observed coverage, per-class corridor, required-op
   inventory) attached to `NO_BOUNDED_CORRIDOR` without changing pinned
   strings, a construction-readiness registry with exact per-op blockers, and
   additive diagnostic codes. Retained Seed 17 assessment: 450 tiles = 339
   ROAD_BUILDABLE + 63 SUPPORTED_CLEARING + 19 UNKNOWN + 29 UNSUPPORTED;
   `INCOMPLETE_TILE_CLASSIFICATION` — a corridor exists only through tiles
   whose class the retained evidence dropped. See
   [the classification record](docs/p08-native-tile-classification.md).
   **Update (2026-10-17, fourth, offline):** Tile Classification V2 native
   capture is prepared, not executed: receipt/correlation/census-binding
   layer (`TileClassificationReceipt`/`TileClassificationExchange`/
   `TileClassificationSweep` with the deterministic multi-band request plan —
   the Seed 17 15×30, 450-tile census becomes exactly 90 ≤256-tile-band
   pages), staged classification candidate
   (`proof/terrain_classification_preparation.py` refuse-on-missing-seam
   staging; `PENDING_AUTHORIZATION`, zero launches, zero requests, claim
   untouched), a Task D readiness projection per classified obstacle
   (planning vs native support stated per record), and an offline retained
   replay that fuses a synthetic census (19 projection-dropped tiles stay
   UNKNOWN, one same-instant ground-agreement semantics fix in
   `classify_segment`, all pinned suites intact) reproducing the retained
   assessment digest-for-digest. Exact launch template, budgets, receipts and
   cleanup are recorded in the candidate; no native claim is possible until
   the fresh one-shot capture runs. See
   [the preparation record](docs/p08-classification-v2-native-capture-preparation.md).
6. **Separate engineering backlog.** Fourth-vehicle intervention, matched A/B runs,
   continuous dispatch and five-year experiments require their own reviewed
   contracts/authorization. Reload-only Q3 proves correspondence and heartbeat,
   not purchase or unpause. Attempt 19 is contextual history, not a matched arm.
   Preserve terrain-proof offline acceptance gaps and missing canonical inputs;
   historical REAL_PASS does not fill them. See `docs/capacity-experiment.md` and
   `docs/specs/openttd-offline-evidence-freeze.md` before that work.
7. **Tile Classification V2 executable path (done offline, awaiting
   authorization).** The four execution blockers are implemented and validated
   offline (`classification_execution.py` staging bound to actual
   source/package/config/argv digests + byte-verified retained `before.sav`,
   schema-2 AdminPort dispatch keyed `(request_id, region, cursor)`, the
   bounded 90-page runner with byte retention and freight-mirroring cleanup,
   and the fail-closed correspondence policy); the frozen prepared candidate
   stays byte-unchanged and the SAME_SESSION fallback is a review-only
   schedule. Native validation of save-load GameScript resolution and the
   census itself require ONE fresh operator authorization; a mismatch fails
   closed (TransportTimeout on page 1 + stderr markers), never silently. See
   [the execution path record](docs/p08-classification-v2-execution-path.md).
   **Update (2026-10-18, native):** the one-shot authorization of execution
   candidate `classification-exec-seed17-e71c95a3` (attempt
   `750167949a4f46af…`) was consumed by a single authorized launch. All
   pre-launch gates passed, the staged composition resolved against the
   save's stored GameScript identity and started, but the instance died
   unexpectedly (no `Load()` hook for the retained save data) before any
   AdminPort page: 0 requests/0 pages, world correspondence NOT established,
   the 19 unknown tiles remain UNKNOWN and the retained
   `INCOMPLETE_TILE_CLASSIFICATION` assessment is unchanged; terminal
   `FAILED_CLEANUP` evidence is preserved in the candidate directory. Read
   [the terminal outcome record](docs/p08-classification-v2-native-capture-outcome.md).
   **Update (2026-10-18, offline diagnosis + repair):** the death was
   re-diagnosed from OpenTTD 15.3 sources + the pinned binary as a **benign,
   engine-designed dummy-AI fallback death misattributed by the runner's
   fatal-log health check**: the staged runtime staged no AI, so the save's
   stored `RoadProofCompany`/1 resolve fell back to the instant-dying dummy
   AI (three `[0] [E]` lines → `Start()` returns → `Died()`), while the
   GameScript itself survived (`[18] BRIDGE_STARTED`; the two post-death
   `[18] [W]` save warnings at the single exit-save prove liveness). Minimal
   repair, no historical bytes touched: the runner health vocabulary now
   recognizes OpenTTD 15.3's `which is no longer available` save-load
   fallback (always fatal), adds a `[S]`-severity tripwire, and exempts
   exactly the designed dummy-AI death (full three-line sequence + direct
   script-log adjacency, once, never for a second death); SOURCE_SAVE
   staging now stages the retained AI package (`RoadProofCompany`, provably
   never dies), sealing its digest in the composition/candidate/PRELAUNCH
   records with byte-exact preflight verification. Fresh non-executed
   candidate `classification-exec-seed17-3a8f9e46` (attempt
   `556e97b81230bfd3…`, composition `3a8f9e46969687b6…` including the staged
   AI package digest `3708a4181df49a3e…`) staged `PENDING_AUTHORIZATION`,
   preflight PASS; 35 focused + 213 broader controlled tests re-run green;
   no launch, no connection, no claim consumed. Read
   [the diagnosis/repair record](docs/p08-classification-v2-native-capture-diagnosis.md).
   **Update (2026-10-18, native):** that fresh one-shot authorization was
   consumed and Tile Classification V2 completed natively
   (`TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT`): 90/90 pages, 450/450 tiles,
   schema-2 exchange for every page, staged AI (`RoadProofCompany READY`) and
   GameScript (`BRIDGE_STARTED protocol=1 api=15`) starting with zero script
   deaths, exact per-page byte budgets held and cleanup completed (process
   reaped, sockets closed, credential removed, workspace disposed). The
   SOURCE_SAVE_FUSION correspondence verdict is **`REJECTED`** with 83
   `PROJECTED_FLAGS_DIFFER` contradictions; nothing was fused, the
   historically UNKNOWN 19 tiles were all observed CLEAR+buildable in the
   fresh census and, as contradictions, are NOT accepted into the retained
   assessment; P08 stays `INCOMPLETE_TILE_CLASSIFICATION`. An offline
   rebinding of the retained page bytes reproduced the recorded completeness
   byte-equal, and the 198-file artifact manifest hash-verifies. Capture
   success is not world correspondence; reconciling the fresh census with the
   historical projection is separately scoped future work. Read
   [the completion record](docs/p08-classification-v2-native-capture-completion.md).
8. **Milestone D3 complete; Milestone D4 (native road + station construction)
   attempt consumed 2026-10-22 — INCOMPLETE.** D3 closed 2026-10-22: the two bounded
   clears (45999, 49326, £30/£45) and the 16-compiled-S-corner terraforming phase
   (£3,382) all replay-`RECEIPT_VERIFIED`, finances reconciled to £496,543, and
   the receipt-bound post-D3 world (`fbebef54…d59e`) proves the planned 24-tile
   corridor flat min-height 2, slope 0, CLEAR, unowned on every tile. Read
   [the D3 close-out record](docs/handoff/2026-10-22/d3-terraform-native-candidate-1-outcome.md).
   D4 stages ONE candidate (`D4-CORRIDOR-1`, additive wire contract + package +
   `proof/corridor_construction_native.py` reusing the shared D2/D3 machinery)
   from that world: 2 straight `BuildRoadFull` runs, the 2-tile corner piece,
   2 truck stops (pickup 45748 front 45747; delivery 50351 front 50095) and the
   depot at 45487 facing 45743 — `PENDING_AUTHORIZATION`, no claim consumption,
   strict offline validation, catchment/acceptance re-checked natively only at
   construction admission. Staging completed 2026-10-22: the candidate is staged
   with `PRELAUNCH PASS` + read-only `PREFLIGHT PASS` (19 planned protocol-4
   exchanges, 640-B response bound, fail-closed never-consumed verify verdict;
   superseded intermediate stages (pre-fix/pre-lint frozen bytes) were deleted
   and re-staged fresh from the final reviewed bytes). Read [the D4 staging
   record](docs/handoff/2026-10-22/d4-corridor-native-candidate-1-preparation.md).
   **Update (2026-10-22, native):** the operator authorization was consumed by ONE
   launch; the corridor ceremony ended `PHASE_HALTED_PREFIX_PRESERVED` with
   `verified: false`, so Milestone D4 remains INCOMPLETE. Only `op-00` was
   verified (5-tile road run at £785, independently re-read, funds £496,543 →
   £495,758); `op-01` was refused at admission because its native quote £2,549
   exceeded the £2,000 per-operation ceiling (no native command issued), and
   `op-02`–`op-05` plus the route read were never executed — no receipt or
   `after.sav` exists. The read-only replay verifier was repaired offline
   (26 → 29 PASS; wire suite 21 PASS). The consumed candidate `D4-CORRIDOR-1` must
   never be edited or reused; a future attempt requires a fresh staged candidate
   plus fresh explicit operator authorization, and none has been staged or
   authorized. Read
   [the D4 close-out record](docs/handoff/2026-10-22/d4-corridor-native-candidate-1-outcome.md).

A documentation-only handoff is complete when links and evidence references are
valid, implementation bytes remain unchanged, the final diff is reviewed and fresh
checks are reported separately from inherited validation. No commit/push is needed.
