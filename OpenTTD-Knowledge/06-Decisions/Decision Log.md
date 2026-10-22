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

---

**Rules for adding records:** date them, cite the source path, set `status`, and never
edit an accepted record's rationale — append a superseding record instead.
