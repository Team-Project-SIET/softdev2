---
title: "Decision Log"
type: decision
status: current
updated: 2026-10-22
tags:
  - openttd
  - decisions
---

# Decision Log

Records derived from project source documents. Each record names its source; decisions
keep their original dates. Full indexing practice: [[06-Decisions/Architecture Decision Records]].

---

## ADR-001 — AdminPort + GameScript as the 15.3 integration boundary

- **Status:** accepted 2026-10-11-era (CONTEXT §5–§7), reiterated in every handoff.
- **Decision:** connect Python to OpenTTD 15.3 via an external AdminPort client and a
  thin Bridge GameScript (`GSEventAdminPort` intake, `GSAdmin.Send` replies),
  `GSCompanyMode` for company-scoped execution. No filesystem polling.
- **Rationale (per CONTEXT):** native communication path in 15.3; OpenTTD 14+ expanded
  company-control capabilities of GameScript; costs/ownership charged to the company.
- **Consequences:** small correlated JSON messages; lifecycle discipline (Start loop,
  script ticks); plan transport no longer depends on 13.4 AI file mechanisms.

## ADR-002 — Keep planning in Python; GameScript stays thin

- **Status:** accepted (CONTEXT §5/§21/§23; `docs/specs/planning-executor-boundary.md`).
- **Decision:** OR-Tools CP-SAT (P05) and P08 candidate generation remain in Python;
  the GameScript executes + reads back only. P05 does not perform YAPF or arbitrary
  terrain search; OpenTTD/YAPF navigates built roads.
- **Consequences:** contract hashes bind plans; executor receipt proves execution, not
  optimization; game-side scripts must not make planning decisions.

## ADR-003 — Deterministic synchronous execution (no async default)

- **Status:** accepted (CONTEXT §12).
- **Decision:** initial proofs use synchronous deterministic behavior; `GSAsyncMode`
  not default for controlled proofs since queued results can diverge from estimates.
- **Consequences:** simpler proof semantics; throughput is not a goal (see Non-Goals).

## ADR-004 — Historical 13.4 results are regression evidence only

- **Status:** accepted (CONTEXT §4, §19).
- **Decision:** OpenTTD 13.4/OpenTTDLab proofs are never cited as 15.3 compatibility;
  verified 15.3 evidence overrides historical assumptions in the documented order.
- **Consequences:** the previous Thin-AI transport can be replaced for 15.3; old
  mechanisms are not preserved merely because code exists.

## ADR-005 — Fixed Scenario is the default product; Random World is opt-in and bounded

- **Status:** accepted (README; AI_HANDOFF; TASKS).
- **Decision:** stable fixed demo remains the default; Random World allowed only at
  256×256 with explicit generation settings, ≤32 industries observed, ≤16 relationships,
  ≤8 services/vehicles, one vehicle/service, P05 1–60 s; Funding separate from service
  construction.
- **Consequences:** stability of the verified demo (E1) is protected; random facts stay
  gated on capture budgets ([[05-Planning/Blockers]]).

## ADR-006 — Expand random capture rectangle to 512 fully observed tiles, preserve legacy 256

- **Status:** accepted (controlled/offline, E5; `random-rectangle-512-v1` profile).
- **Decision:** separate compatibility from capture admission; legacy sealed random
  budgets retain 256-tile admission and their identities; new profile requires complete
  tile + declared cargo-coverage observations, 45 s, ≤546 reads/relationship; global
  guard `(capture_tile_limit+36)×max_relationships+1`.
- **Consequences:** no silent truncation; consumed identities never reused.

## ADR-007 — One-shot operator-authorized attempts; immutable evidence; fail-closed

- **Status:** accepted (AI_HANDOFF; EVIDENCE_INDEX; `docs/specs/openttd-offline-evidence-freeze.md`).
- **Decision:** every native mutation is a single preflighted launch under one fresh
  operator authorization and one-shot claim; no retry/reconnect; failure retains partial
  evidence; cleanup never deletes historical saves/logs; receipts verify with exact
  log prefixes/identities; verification never launches OpenTTD.
- **Consequences:** consumed identities are final; statuses can never be upgraded after
  the fact; the record-writing sessions explicitly did not initiate launches (E17/E19).

## ADR-008 — Response-bound escalation for the D4 corridor contract

- **Status:** accepted, 2026-10-22 (E20).
- **Decision:** corridor wire contract v4 raises the response bound to **640 B** on the
  D4 contract alone (all other historical 512-B bounds unchanged) because the route read
  must echo the ordered 24-tile witness + observation fields; dropping fields would
  weaken fail-closed verifiers.
- **Consequences:** bounds stay per-contract; honesty over uniformity; oversized readings
  are refused frames.

## ADR-009 — Staged AI must satisfy the save's stored identity

- **Status:** accepted, 2026-10-18 (E15 — repair decision after consumed failure E14).
- **Decision:** when a prepared save stores a GameScript/AI identity, staging must stage
  the matching packages (`RoadProofCompany`), seal digests in PRELAUNCH records, and treat
  `which is no longer available` fallback as fatal; the dummy-AI death is exempt exactly
  once under a strict three-line condition.
- **Consequences:** repairs addressed the *health check + staging*, not the historical
  evidence; cost of a wrong staging decision is a consumed authorization (E14).

## ADR-010 — Reconciliation must not relabel sealed verdicts

- **Status:** accepted (uncommitted 2026-10-18 record; consistent with EVIDENCE_INDEX).
- **Decision:** offline V1/V2 reconciliation is a derived, read-only layer; sealed
  coherence gate and native verdicts (`TILE_CLASSIFICATION_V2_CAPTURED_INCOHERENT`,
  `SOURCE_SAVE_FUSION REJECTED`) stay untouched; temporal tiles never fuse/reclassify;
  P08 binding requires fresh same-instant evidence or an operator policy decision.
- **Consequences:** derived verdict ≠ sealed verdict; both remain separately visible
  ([[05-Planning/Blockers]] keeps the contradiction explicit).

## ADR-011 — D4 Option C: split-run-B restage inside the unchanged per-op ceiling

- **Status:** accepted, 2026-10-22 (offline implementation E22; source decision context
  E21 close-out §9; implementation record
  `docs/handoff/2026-10-22/d4-corridor-option-c-implementation.md`).
- **Decision:** rescope the staged corridor at **staging time, never live**: keep
  `MAX_CORRIDOR_COST = 2000` unchanged and stage the 17-tile run B as two contiguous
  straight `BuildRoadFull` segments (45999→48047, 9 tiles; 48303→50095, 8 tiles) plus a
  separate interior `BuildRoad` join (48047↔48303) built after both segments; the
  historical corner join, both stops and the depot are unchanged (8 static ops, 8×3+1 =
  25 planned exchanges, dispatcher budget 31). Derivation is versioned:
  `schedule_version 2` for fresh staging; the consumed `D4-CORRIDOR-1` replay keeps
  re-deriving its historical 6-op schedule (v1, compiled from the same pinned facts,
  never hand-retold); unknown versions refuse fail-closed.
- **Consequences:** every op is quoted natively again at its own admission inside the
  ceiling (the joins are own-admission ops; road pieces never auto-merge); the geometry
  stays two straight runs joined by one corner and `corridor_facts()`/`route_policy()`
  are untouched. There is deliberately **no aggregate phase-spending budget** — the
  per-op ceiling remains the only cost contract (worst-case theoretical exposure
  8 × £2,000 = £16,000 is an exposure bound, not a budget). Historical quotes
  (£2,549/£785) are controlled references of the consumed attempt, never facts of the
  new plan. This decision is offline/controlled only — it neither stages a candidate
  nor grants any runtime authority; D4 stays INCOMPLETE (native) until a fresh
  reviewed candidate plus one fresh explicit operator authorization exist.
- **Supersedes:** nothing (ADR-008's response-bound decision is orthogonal and
  stands).
- **Preparation status (2026-10-22, E24):** the ADR's staged outcome is real —
  fresh candidate `D4-CORRIDOR-2` staged offline (`PRELAUNCH PASS` + read-only
  `PREFLIGHT PASS`, seal `de0e16f7…04f00`, plan digest `2a30e950…cabb3a`,
  attempt identity operator-approved before staging). Candidate-2 was later
  proved stale and a fresh candidate-3 was staged, signed and consumed exactly
  once (E27, E28); that native attempt built `op-00`–`op-02` but halted when
  `op-03` was refused at admission, so the eight-op schedule is still not
  natively accepted. The ADR's decision status is unchanged (accepted,
  offline); D4 stays INCOMPLETE (native).
- **Review status (2026-10-22, E23):** the implementation of this ADR was
  independently reviewed offline — **`PASS WITH CONCERNS`**
  (`docs/handoff/2026-10-22/d4-corridor-option-c-implementation-review.md`): two
  non-blocking observations (a latent fail-safe request-count check that can only
  refuse, never accept; an authorization-payload version-inclusion enhancement idea)
  and one documentation defect (fixed during the review). The implementation is
  suitable to proceed to fresh-candidate preparation via the existing authorization
  process; this ADR stays offline/controlled and grants no runtime authority.
- **Verification status (2026-10-22, read-only):** the staged authorization
  payload of `D4-CORRIDOR-2` was rebuilt offline and matched its staged
  digest (`e85ea64b…52ff17` over 2,393 bytes), the frozen closure
  hash-verified 3,447/3,447 (0 missing, 0 mismatches) and the retained
  manifests re-verified unchanged — verification only: nothing signed, no
  claim, no launch (record:
  `docs/handoff/2026-10-22/d4-corridor-native-candidate-2-payload-verification.md`).
  The decision status is unchanged (accepted, offline); D4 stays INCOMPLETE
  (native).

---

## ADR-012 — Six temporal tiles: save-instant census authoritative for tree-lifecycle deltas (planning evidence only)

- **Date:** 2026-10-24. **Status:** accepted. **Source:**
  `docs/handoff/2026-10-24/adr-012-six-temporal-tiles-census-authority.md`.
- **Decision (delegated):** the operator delegated the Option A / Option B
  choice for the six `TEMPORAL_SECOND_INSTANT` tiles (43951, 47286, 47288,
  48042, 48309, 51378) of the P08 V1/V2 reconciliation; the runner-side agent
  selected **Option B** on code-level feasibility grounds: the same-state
  criterion is computed from the sealed, immutable census instants
  (712224–712226) and the retained window (712285–712291), so no future
  observation can make them same-instant — a fresh re-observation (Option A)
  could at best confirm the already mechanically-explained tree deltas, not
  decide which instant governs P08 planning. For those six tiles the
  save-instant census is declared authoritative **for planning evidence only**.
- **Implemented (offline):** `app/simulation/openttd/v2_semantic_reconciliation.py`
  gains `CensusAuthorityDecision` / `apply_census_authority` — explicit,
  fail-closed, scope-contained. It refuses: scope ≠ sealed temporal set,
  hygiene/identity failures, unreproduced completeness, unverified manifest,
  non-single-instant census pages, non-`TEMPORAL` outcomes (contradictions /
  unresolved are never absorbed) and fields outside the ADR's concept scope.
  Accepted rows preserve retained and census values verbatim; definitional
  `vacant-projection-1` rows pass through untouched; the base reconciliation
  object and its report bytes are unchanged. Derived verdict
  `SEMANTIC_RECONCILED_CENSUS_AUTHORITATIVE_TEMPORAL` (derived report:
  `artifacts/experiments/v1v2-semantic-reconciliation/census-authority-policy-report.json`).
  Tests: `tests/test_census_authority_policy.py` 14/14 PASS (2026-10-25),
  including the sealed Seed-17 replay proving all six tiles resolve and the
  base report bytes do not move.
- **Not established:** no relabeling of sealed verdicts (ADR-010 stands), no
  fusion-gate opening, **P08 binding remains not allowed** (19 retained-UNKNOWN
  tiles, sealed verdict immutability, separate reviewed rebinding step), no
  native evidence — nothing captured, signed, consumed or launched. The six
  tiles are resolved only in the authority-attribution sense.
- **Rebinding pass (2026-10-25, offline):** `rebind_p08_policy` /
  `P08PolicyRebinding` re-derive the policy report from the sealed inputs and
  byte-compare it; only the exact six-tile temporal scope with verbatim rows is
  accepted (out-of-scope tiles, contradictions, unresolved evidence, stale or
  edited reports refused). Wired into
  `build_v2_snapshot_assessment(..., policy_report=...)` / `--policy-report`
  without changing the planning input or pinned base assessment. Derived
  evidence: `artifacts/experiments/v1v2-semantic-reconciliation/p08-policy-rebinding-report.json`
  (sha256 `c9d11d41…107ed0`); tests `tests/test_p08_policy_rebinding.py` 24/24
  PASS. Computed `p08_binding.allowed` is still **false**: the 19 retained-
  UNKNOWN tiles are outside ADR-012, so P08 stays
  `INCOMPLETE_TILE_CLASSIFICATION`. The rebinding removes only the
  "separate reviewed step not implemented" blocker.
- **Alternatives:** Option A retained as an **optional conditional future
  delta-confirmation run** (own staged candidate + fresh authorization); never
  assumed. Adopting both simultaneously rejected as contradictory.
- **Supersedes:** nothing.

---

## ADR-013 — Native `IsBuildable` semantics for the 19 definitional P08 tiles (accepted 2026-10-25)

**Status:** accepted. **Date:** 2026-10-25. **Source:**
`docs/handoff/2026-10-25/adr-013-p08-native-isbuildable-definitional-semantics.md`.
**Relates:** ADR-010, ADR-012.

- **Decision:** adopt native `GSTile.IsBuildable` semantics for P08 segment
  classification of exactly the 19 operator-approved definitional tiles
  (`46517, 46518, 46772, 47027, 47028, 47282, 47283, 47538, 47793, 48049,
  48304, 48305, 48554–48560`) and map them to `TERRAIN_MODIFICATION` when, and
  only when, every evidence gate passes. The retained planner-`Vacant`
  `buildable=False` is the definitional projection of native `IsBuildable` on
  unowned sloped clear ground.
- **Implemented (offline):**
  `NativeIsBuildableDecision` / `apply_native_isbuildable_policy` /
  `NativeIsBuildablePolicyApplication` / `P08NativeIsBuildableRebinding` /
  `rebind_p08_native_isbuildable` in
  `app/simulation/openttd/v2_semantic_reconciliation.py`; CLI
  `--apply-adr-013` and `--rebind-p08`; optional snapshot integration via
  `native_isbuildable_report=` / `--native-isbuildable-report` (requires the
  ADR-012 report). The layer refuses wrong scope, count drift, non-definitional
  status, contradictions/unresolved evidence, malformed census facts,
  non-single-instant pages, entangled ADR-012 scope, stale/edited reports and
  any non-`TERRAIN_MODIFICATION` derivation. The base reconciliation object
  and sealed bytes are never mutated.
- **Derived evidence:** `native-isbuildable-policy-report.json` sha256
  `7616f6262c99dc7a97bd26c0043dcc1c0dc6ba5287f1b203b1ffe72529a3a65d`;
  separate combined `p08-native-isbuildable-rebinding-report.json` sha256
  `079fce64c4a37295c05cb87cf129aa9317abccfddba9114bb84341ee04adee62`.
  Derived segmentation **339 ROAD_BUILDABLE / 63 SUPPORTED_CLEARING /
  29 UNSUPPORTED_CONSTRUCTION / 19 TERRAIN_MODIFICATION / 0 UNKNOWN**.
  Existing base/report artifacts verified byte-identical.
- **P08 effect:** the separate rebinding (both ADR-012 and ADR-013)
  computes `p08_binding.allowed: true` for **planning classification only**,
  with zero blockers. It records `p08_complete: false`; P08 as a milestone is
  **not** complete.
- **Not established / still closed:** sealed `SOURCE_SAVE_FUSION` verdict
  remains `REJECTED`; the fusion gate remains **CLOSED** and was not opened.
  No signing, candidate consumption, OpenTTD launch, AdminPort access or native
  execution occurred. No native construction/terraforming/delivery evidence
  exists; terraform cost and native success remain unproven.
- **Tests:** `tests/test_p08_policy_rebinding.py` 41/41 focused; broader
  reconciliation/snapshot group 83/83; feasibility classification 24/24; Ruff
  clean on changed Python files.
- **Supersedes:** nothing.

---

## ADR-014 — Explicit CONTEXT.md authority-pin supersession (accepted 2026-10-25)

**Status:** accepted. **Date:** 2026-10-25. **Source:**
`docs/handoff/2026-10-25/context-authority-pin-repair.md`.
**Relates:** ADR-010, ADR-013; evidence protection.

- **Decision:** keep every retained 2026-10-08 protection manifest and all
  historical bytes frozen and unmodified. Add one explicit, operator-authorized
  supersession record (`docs/authority/context-authority-supersession.json`)
  that binds exactly the path `CONTEXT.md`, the historical digest `b94b966…`,
  the successor digest `36648f9…`, and `historical_bytes_retained: false`.
- **Enforcement:** `app/simulation/openttd/proof/authority_supersession.py`
  verifies the frozen manifest's own digest first, substitutes only the
  recorded path/digest pair, then delegates every other entry to the unchanged
  `validate_protection` contract. The base validator still rejects the diverged
  file without the record.
- **Scope:** offline repository authority only. It grants no native authority,
  changes no protected artifact, and does not claim the historical bytes are
  recoverable (they are UNKNOWN on this machine).
- **Effect:** the three baseline failures
  (`test_protected_history_and_context_exact`,
  `test_protected_historical_authority_remains_exact[CONTEXT.md]`,
  `test_architecture_authority_unchanged`) are resolved without weakening any
  other protection check.
- **Supersedes:** nothing. The historical pin remains historical evidence.
