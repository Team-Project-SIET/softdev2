---
title: "Blockers"
type: planning
status: current
updated: 2026-10-26
tags:
  - openttd
  - planning
  - blockers
---

# Blockers

Live blockers with their sources. A blocker stays listed until a dated record resolves it
([[07-Reference/Status Definitions]]; preserve contradictions until properly investigated).

## 1. Authorization is always required before native work

**Type: process, standing.** The project's one-shot model means the *only* way anything
native happens is a fresh, explicit operator authorization per attempt (E17/E19 launch
records: "the record-writing session did NOT initiate the launch" — authorizations were
consumed by separate operator actions). That now includes D4: the one-shot
authorization for `D4-CORRIDOR-1` was consumed 2026-10-22 (E21 — the attempt halted
`PHASE_HALTED_PREFIX_PRESERVED`, Milestone D4 INCOMPLETE; the frozen closure must
never be edited or reused). Candidate-2 was subsequently proved **stale** (E27,
2026-10-25: a read-only preflight fails `verify_freeze` because its frozen
closure predates the accepted ADR-012/ADR-013 edits; it was never consumed and
was not edited). Fresh candidate `D4-CORRIDOR-3` was staged, signed and then
**consumed exactly once** on 2026-10-25 (E28): `op-00`–`op-02` built and read
back, `op-03` was refused at admission (`NOT_BUILDABLE`, cost 0), and the
attempt ended `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`,
`FAILED_CLEANUP` with no authoritative after-save/receipt. The consumed
`D4-CORRIDOR-1`, stale `D4-CORRIDOR-2`, and consumed `D4-CORRIDOR-3`
identities are never retried or reused. Any resumption needs a fresh,
separately authorized candidate. **Offline correction 2026-10-25 (E29):** the
`op-03` interior join was redundant, not an admission defect; collinear
`BuildRoadFull` endpoints auto-connect (`pairs_ok 1`), while the perpendicular
corner still needs its own join. Fresh schedule v3 has 7 ops / budget 28;
v1/v2 replay derivations preserved. Record:
`docs/handoff/2026-10-25/d4-corridor-op03-root-cause.md`.
**Consumed 2026-10-25 (E32):** fresh `D4-CORRIDOR-4` (v3) was signed under the
pinned anchor and consumed by exactly one authorized native run. `op-00`–`op-05`
built and read back (£4,004; funds £496,543 → £492,539), including the
perpendicular corner `45743↔45999` and both stops. `op-06` (depot `45487`) was
dispatched; the native log reports `D4_RESPONSE depot-06 BUILT`, but its
513-byte GameScript payload exceeded the then-hard-coded 512-byte application
limit and `decode_gamescript` raised `MalformedMessage` before parsing. No
`confirm-06`, `receipt.json` or authoritative `after.sav` exists; the route read
did not run. Result `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`,
`PHASE_HALTED_PREFIX_PRESERVED`; cleanup PASS (all four fields true), manifest
80/80, and read-only replay raised the same `MalformedMessage` at the time.
Offline E33 corrects protocol 4's decode bound to 640 (version-one 512
unchanged); the retained frame now parses, but replay still refuses for missing
durable confirmation. **D4 remains INCOMPLETE (native).** No retry, re-sign,
replacement candidate or claim reuse is permitted. Candidate-3's historical
`FAILED_CLEANUP` remains unchanged; cleanup certification was resolved as
attempt-scoped, not a cross-candidate prerequisite. *(Chain close 2026-10-26,
E35: `D4-CORRIDOR-5` completed the v3 schedule natively — D4 is no longer
incomplete; see §8 below.)*
**Operator-guidance correction 2026-10-24 (documentation only):** the extraction
commands in the provisioning doc §1 and D2-3 §6(b) were corrected to the tested
`od`/`tr` pipeline with `pipefail` state preserved; validation used synthetic keys
only, no production key was accessed, and nothing was signed. This removes a
documentation defect, **not** the authorization blocker: no `AUTHORIZATION.json`,
`CLAIM.json` or `LAUNCH-CONSUMED.json` exists for candidate-2.

## 2. Random World infeasibility chain (Seed 17)

**Type: technical — evidence-driven, immutable so far.**

- 5 of 6 compatible relationships exceed capture budgets even under `random-rectangle-512-v1`
  (Wood 1122, Livestock/Grain 17947, Oil 8436, Iron ore 2457 tiles vs 512-tile cap) — only
  coal (450 tiles) was capturable; Wood is also the nearest at 185 Manhattan tiles (E4/E5,
  `docs/random-world-distance-support.md`).
- The coal pair itself is **completely disconnected** in the supported corridor graph
  (17 water, 50 trees, 13 rough, 12 industry, 19 steep non-buildable tiles) —
  `NO_BOUNDED_CORRIDOR` is a complete-search proof (E9).
- With classified levelling admitted, **no connected corridor exists even in principle**
  via supported modifications: all 23 height-step adjacencies are fenced by
  forbidden-class tiles; 19 of 450 tiles' house/station class cannot be recovered offline
  → `NO_CONNECTED_LEVELED_CORRIDOR` (E10).
- Fresh V2 census disagrees with the retained projection on 83 tiles
  (`PROJECTED_FLAGS_DIFFER`) → fusion stays **REJECTED** (E16); the 19 historical
  UNKNOWN tiles stay UNKNOWN in the base ledger, but ADR-013 (accepted 2026-10-25)
  resolves them in the derived planning layer; see the update below.
- Uncommitted 2026-10-18 reconciliation found 0 contradictions but 6 **temporal**
  second-instant tiles (43951, 47286, 47288, 48042, 48309, 51378 — tree growth/death
  mechanics vs retained V1 window economy days 712285–712291; fresh census at 712224–712226)
  → `SEMANTICALLY_RECONCILED_TEMPORAL_UNRESOLVED`, P08 binding not allowed. **Recorded
  minimum additional evidence:** a bounded, separately-authorized same-instant native
  re-observation of exactly those six tiles, and/or an explicit operator policy decision
  declaring the save-instant census authoritative; sealed in a NEW reviewed candidate.
  Status caveat: this reconciliation is uncommitted working-tree work, not an indexed
  evidence record (no E-ID). *(Contradiction preserved, not resolved.)*
  **Update 2026-10-24:** the operator-facing **policy decision record** is
  prepared (offline only, deciding nothing):
  `docs/random-world-six-tile-policy-decision.md` — it formalizes exactly the
  two resolution paths (A: new reviewed same-instant re-observation candidate
  of `[43951, 47286, 47288, 48042, 48309, 51378]` with `date_before ==
  date_after` under a fresh one-shot authorization; B: explicit operator
  policy declaring the save-instant census authoritative for the six tree
  deltas, sealed as a new ADR) plus prerequisites, consequences and non-goals.
  The focused suite re-verified this session: 15/15
  (`tests/test_v2_semantic_reconciliation.py`). The choice remains the
  operator's; no fusion gate opened, P08 stays `INCOMPLETE_TILE_CLASSIFICATION`.
  **Decision exercised 2026-10-24/25 (delegated to the runner-side agent;
  ADR-012, Option B):** the save-instant census is declared authoritative for
  the six tiles' tree-lifecycle deltas — **planning evidence only** — via a
  fail-closed scope-contained layer (`apply_census_authority`, 14/14 tests
  PASS, derived report
  `artifacts/experiments/v1v2-semantic-reconciliation/census-authority-policy-report.json`).
  Option A was rejected **as the resolution path** on code-level grounds: the
  same-state criterion uses the sealed immutable census/retained instants, so
  no fresh observation can make them same-instant; A remains an optional
  future delta-confirmation run under its own authorization. Unchanged: the
  base ledger keeps `TEMPORAL_SECOND_INSTANT`, sealed verdicts are
  unrelabelled, the fusion gate is closed, P08 remains
  `INCOMPLETE_TILE_CLASSIFICATION` (19 retained-UNKNOWN tiles outside
  ADR-012), and no native evidence was collected.
  **Rebinding pass 2026-10-25 (offline):** `rebind_p08_policy` re-derives the
  policy report from the sealed inputs and byte-compares it; only the exact
  six-tile scope with verbatim rows is accepted (stale/edited/out-of-scope/
  contradictory evidence refused). Snapshot adapter takes it via
  `policy_report=`/`--policy-report`; derived evidence
  `artifacts/experiments/v1v2-semantic-reconciliation/p08-policy-rebinding-report.json`
  (sha256 `c9d11d41…107ed0`), tests 24/24 PASS. The computed binding is still
  **not allowed** because the 19 `UNKNOWN_OCCUPANCY` tiles remain unresolved
  and outside ADR-012; P08 stays `INCOMPLETE_TILE_CLASSIFICATION`.
  **19-tile root cause 2026-10-25 (diagnosis only):** all 19 are one
  definitional group — census `CLEAR`, unowned, non-flat, already
  `SEMANTIC_RECONCILED` on `buildable`; the retained-only segmenter maps them
  to UNKNOWN. No resolution: adopting native `IsBuildable` semantics for P08
  segmentation needs separate reviewed authorization (or fresh same-instant
  evidence). Evidence
  `artifacts/experiments/v1v2-semantic-reconciliation/p08-unknown-occupancy-diagnosis.json`
  (sha256 `66ed07cc…7e459`). The fusion gate stays independently closed by
  the six temporal tiles.
  **ADR-013 accepted and active 2026-10-25 (operator-authorized, offline):**
  native `GSTile.IsBuildable` semantics are adopted for exactly the 19
  definitional tiles and map them to `TERRAIN_MODIFICATION` in the derived
  layer only when every fail-closed evidence gate passes. The base ledger still
  records them as `UNKNOWN_OCCUPANCY`; no sealed evidence was changed. Derived
  counts are **339 ROAD_BUILDABLE / 63 SUPPORTED_CLEARING /
  29 UNSUPPORTED_CONSTRUCTION / 19 TERRAIN_MODIFICATION / 0 UNKNOWN**.
  Policy evidence:
  `native-isbuildable-policy-report.json` (sha256 `7616f626…a3a65d`).
  **Separate combined rebinding 2026-10-25:** the pass verifies both ADR-012
  and ADR-013 reports and computes `p08_binding.allowed: true` for **P08
  planning classification only**, with no blockers. It records
  `p08_complete: false`; the fusion gate remains **CLOSED** and was not opened
  (sealed `SOURCE_SAVE_FUSION` verdict immutable). Evidence:
  `p08-native-isbuildable-rebinding-report.json`
  (sha256 `079fce64…4adee62`). Focused tests 41/41; broader group 83/83;
  feasibility classification 24/24. No signing, candidate consumption,
  OpenTTD launch, AdminPort access or native execution occurred.
- **Consequence:** any new random native run is currently expected to hit
  `NO_FEASIBLE_SERVICES` again unless those facts change; TASKS explicitly says "Do not
  promise the coal pair will yield a feasible road".

## 3. CONTEXT.md authority-pin conflict — RESOLVED 2026-10-25 (E26, ADR-014)

**Type: integrity/process (resolved, offline).** The 2026-10-08 byte pin
(sha256 `b94b966…`) stays frozen and historical. Its bytes are not retained on
this machine. An explicit operator-authorized supersession record
(`docs/authority/context-authority-supersession.json`) scopes exactly the
path/digest transition to the live canonical file (`36648f9…`), and the
fail-closed validator delegates all other entries to the unchanged
`validate_protection` contract. The two protected-authority tests and the
architecture test now pass; no other protection is weakened. See
[[04-Evidence/Evidence Preservation]] and
`docs/handoff/2026-10-25/context-authority-pin-repair.md`.

## 4. Fourth-vehicle / matched A/B native readiness

**Type: missing artifact.** No retained canonical pre-intervention save contains the
original constructed fleet; no verified reload preserves its GameScript bindings and
native state. Historical REAL_PASS evidence does not fill this gap
([[99-Source-Documents/TASKS]] item 6; `docs/capacity-experiment.md`).

## 5. Missing historical inputs

**Type: documentation/artifact gap, permanent until artifacts appear.** The original
terrain audit and canonical inputs remain missing; retained-evidence absence on a machine
→ UNKNOWN (`docs/specs/openttd-offline-evidence-freeze.md`).

## 6. Tooling unavailability (recorded, honest)

**Type: environment.** Typecheck (`mypy`/`ty`/`pyright`) repeatedly recorded unavailable
offline; `ty` is configured in the project but not installed. Full-tree test/lint health
UNKNOWN beyond recorded checks. Fixing this is straightforward but must be done honestly:
install, re-run, and record new results as fresh checks — do not reuse historical "PASS"
claims afterwards ([[03-Engineering/Testing Strategy]]).

## 7. Remote documentation completeness unverified

**Type: knowledge risk.** The project-local OpenTTD docs repository contents/version
availability is unverified (CONTEXT §4) — OpenTTD-specific behavior must be verified
against official 15.3 docs and/or 15.3 sources when project-local docs are incomplete
([[01-Architecture/OpenTTD Integration]]).

## 8. D4 restage decision — TAKEN (Option C); chain closed COMPLETE 2026-10-26 (E35)

**Type: decision, staging-time (no live override) — RESOLVED 2026-10-22 (E22, ADR-011);
implementation review-cleared 2026-10-22 (E23).** The consumed attempt's 17-tile run `op-01` was refused at
admission: native quote **£2,549** vs the authorized **£2,000** per-operation ceiling
(E21). The Option C path was chosen and implemented **offline**: keep the ceiling
unchanged, stage the run B as two contiguous segments (45999→48047, 48303→50095) plus a
separate interior road join after both (8 static ops, 25 planned exchanges, budget 31),
with a schedule-version selector keeping the consumed attempt's replay re-derivable
(E22; record `docs/handoff/2026-10-22/d4-corridor-option-c-implementation.md`). **Review
outcome (2026-10-22, E23):** the independent offline review of that implementation
returned **`PASS WITH CONCERNS`**
(`docs/handoff/2026-10-22/d4-corridor-option-c-implementation-review.md`) — two
non-blocking observations and one documentation defect (fixed during the review); it
clears fresh-candidate preparation and grants no runtime authority. **Staging
outcome (2026-10-22, E24):** the fresh candidate is staged — **`D4-CORRIDOR-2`**
at `artifacts/experiments/d4-corridor-native-candidate-2/`, `PRELAUNCH PASS` +
read-only `PREFLIGHT PASS`, seal `de0e16f7…04f00`, plan digest
`2a30e950…cabb3a`, with the attempt identity operator-approved before staging
(consumed `D4-CORRIDOR-1` → never-consumed `D4-CORRIDOR-2`)
(`docs/handoff/2026-10-22/d4-corridor-native-candidate-2-preparation.md`).
**Read-only payload verification (2026-10-22):** the staged authorization
payload was rebuilt offline and matched its staged digest
`e85ea64b…52ff17` (2,393 bytes), the frozen closure hash-verifying
3,447/3,447 (0 missing, 0 mismatches); verification only — nothing signed,
nothing launched (record
`docs/handoff/2026-10-22/d4-corridor-native-candidate-2-payload-verification.md`).
**Superseded by execution (2026-10-25, E28):** the fresh authorization for
`D4-CORRIDOR-3` was issued, the candidate was consumed exactly once, and the
attempt halted at `op-03`; see the executed-outcome paragraph below. Candidate-2
remains stale. Every op gets a fresh native quote at its own admission; the
historical £2,549/£785 quotes are controlled references of the consumed attempt,
never facts of the new plan.
There is deliberately no aggregate phase-spending budget (the per-op ceiling
remains the only cost contract; worst-case theoretical exposure 8 × £2,000 =
£16,000 if all eight ops quoted the ceiling is an exposure bound, not a
budget). Sources: E21, E22, E23, E24,
[[06-Decisions/Decision Log]] ADR-011, [[99-Source-Documents/EVIDENCE_INDEX]].

**2026-10-25 restage (E27):** candidate-2's frozen closure was proved stale
against the accepted ADR-012/ADR-013 source edits (read-only preflight fails
`verify_freeze`; never consumed, not edited). Fresh candidate
**`D4-CORRIDOR-3`** is staged at
`artifacts/experiments/d4-corridor-native-candidate-3/`: `PRELAUNCH PASS` +
read-only `PREFLIGHT PASS`, seal `8cc8c1f7…7d24`, plan digest
`2a30e950…cabb3a`, payload `e1163d09…068d` (2,393 bytes), 3,448-entry frozen
closure, focused suites 55/55 PASS.

**Executed and closed 2026-10-25 (E28):** `D4-CORRIDOR-3` was signed, verified
and consumed exactly once. `op-00`–`op-02` built and read back (£496,543 →
£493,209); `op-03` interior join `48047↔48303` was refused at admission as
`NOT_BUILDABLE` with cost 0 (`road0/road1 true`, `pairs_ok 1`), so the runner
halted with `ValueError: native READY admission with positive tested cost
required`. `op-04`–`op-07` and the route read never executed. Result
`PARTIAL_EXECUTION_EVIDENCE`, `verified: false`, `FAILED_CLEANUP`; no
authoritative `after.sav`/`receipt.json`; replay refuses `halted attempt cleanup
incomplete` (TCP state-5 observation prevented workspace/credential disposal;
no listener remains). D4 remains INCOMPLETE (native). **Offline correction
2026-10-25 (E29):** `op-03` was a redundant scheduled interior join. Scripted
full-build endpoints auto-connect the collinear run-B segments; admission
correctly rejected the already-connected pair. The perpendicular corner remains
a required join. Fresh schedule v3 has 7 ops / budget 28; v1/v2 replay
derivations preserved. **Cleanup remediation verified 2026-10-25 (E30):**
candidate-3 workspace disposal and credential removal are confirmed
(`credential_removed: true`, `workspace_disposed: true`, workspace absent, no
secret/config file or process/listener). The historical state-5
`verification_error`, missing `sockets_closed`, `FAILED_CLEANUP` result and
replay refusal remain, so this is not native success. **Fresh candidate-4 staged and consumed 2026-10-25 (E31/E32):**
`D4-CORRIDOR-4` uses v3 (7 ops, 22 planned, cap 28, £2,000 per-op, no redundant
interior join, corner retained), seal `88cd1ecc…fd22c3`, plan digest
`b5b472ff…2283a78`, payload `4037c5d8…487c7f`, source world `fbebef54…d59e`;
`PRELAUNCH PASS` + `PREFLIGHT PASS`, focused suites 55/55. It was then signed
under the pinned anchor and consumed by exactly one native run: `op-00`–`op-05`
built and read back (£4,004; funds £496,543 → £492,539), including the corner
and both stops; `op-06` depot was dispatched and the native log reports
`BUILT`, but its 513-byte GameScript payload exceeded the 512-byte application
limit and was rejected before parsing (`MalformedMessage`). No `confirm-06`,
receipt or authoritative after-save exists; the route read did not run. Phase
`PARTIAL_EXECUTION_EVIDENCE`, `verified: false`,
`PHASE_HALTED_PREFIX_PRESERVED`; cleanup PASS, manifest 80/80, replay raised the
same `MalformedMessage` at the time. Offline E33 now corrects the protocol-4
decode bound to 640 while preserving the version-one 512 default; the retained
513-byte depot payload parses, but replay still refuses for the missing durable
response/confirmation. The attempt is closed and must not be retried or reused.
**Closed 2026-10-26 (E35):** the remaining gate was met and spent —
`D4-CORRIDOR-5` was staged from the reviewed v3 sources (independent fresh-context
review **PASS 20/20**), every pre-signing gate re-verified fresh, signed under a
fresh explicit operator authorization covering signing plus one attempt, and
consumed exactly once: 1 launch / 1 connection / 22 of 28 requests; all seven
v3 ops verified with quote-equal native costs (£785 + £1,398 + £1,151 + £71 +
£307 + £292 + £390 = £4,394; funds £496,543 → £492,149), `ROUTE_VERIFIED` 23/23,
authoritative receipt-bound `after.sav` `a81ac836…ef261`, cleanup certified,
manifest 90/90, read-only replay `RECEIPT_VERIFIED`. **D4 is COMPLETE (native)
for exactly the reviewed v3 scope — this blocker is resolved. The next
authorization gate is D5 vehicle work, which does not exist yet and is not
authorized.** Records:
`docs/handoff/2026-10-25/d4-corridor-native-candidate-3-outcome.md`,
`…-cleanup-remediation.md`, `…-candidate-4-preparation.md`,
`…-candidate-4-outcome.md`, `…-response-limit-fix.md`,
`docs/handoff/2026-10-25/d4-corridor-op03-root-cause.md` and
`docs/handoff/2026-10-26/d4-corridor-native-candidate-5-outcome.md`.

## Consequence summary for the next agent

The engineered path forward (D4) had its §8 decision taken (Option C implemented
offline, E22/ADR-011), its implementation independently reviewed offline (`PASS WITH
CONCERNS`, E23), and candidate-3 staged, signed and consumed exactly once (E27,
E28). It halted at `op-03`: the interior join was refused at admission because
collinear full-run endpoints already connect. The offline v3 correction (E29)
removed only that redundant join and retained the perpendicular corner.
Candidate-3 cleanup remediation was verified as a separate later event (E30)
without changing its failed outcome. Fresh candidate `D4-CORRIDOR-4` was then
staged `PRELAUNCH PASS` + `PREFLIGHT PASS` (E31), signed under the pinned anchor
and consumed by exactly one native run (E32): `op-00`–`op-05` built and read
back (£4,004; funds £496,543 → £492,539), including the corner and both stops,
and `op-06` depot was dispatched but its 513-byte response exceeded the
then-hard-coded 512-byte application limit and was rejected before parsing. The
attempt ended `PARTIAL_EXECUTION_EVIDENCE`, `verified: false`,
`PHASE_HALTED_PREFIX_PRESERVED`, with cleanup PASS, 80/80 manifest. Offline E33
corrects protocol 4's decode bound to 640 (default 512 unchanged); the retained
frame now parses, but replay still refuses for missing durable confirmation.
The chain then closed successfully on 2026-10-26 (E35): `D4-CORRIDOR-5` — staged
from the reviewed v3 sources (review PASS 20/20) and signed under a fresh
explicit operator authorization — was consumed exactly once with all seven v3
ops verified (quote-equal native costs, £4,394; £496,543 → £492,149),
`ROUTE_VERIFIED` 23/23, authoritative `after.sav` `a81ac836…ef261`, certified
cleanup, 90/90 manifest and read-only replay `RECEIPT_VERIFIED`. **D4 is
COMPLETE (native) for exactly the reviewed v3 scope; the D4 authorization
chain is exhausted and must not be retried.** The next authorization gate is
D5 vehicle work (not designed, not staged, not authorized). The Random World
path is evidence-gated: it needs new authorized native facts
(same-instant tiles) or an operator decision before any feasibility verdict
changes. Do not soften either gate.
