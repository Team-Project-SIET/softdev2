# D5 terrain-survey instrument — offline implementation record

Status: **OFFLINE IMPLEMENTATION ONLY.** No OpenTTD process was launched, no
AdminPort connection was opened, no candidate was staged in the runtime
experiment area (`artifacts/experiments/`), and no claim, authorization
payload, signature or Gate/claim artifact exists from this work. The
authoritative D4 candidate-5 after-save, the consumed identities
(`D5-FREIGHT-1`, `D5-ACCEPT-SURVEY-1`, `D5-CORRIDOR-EXTENSION-1`), and every
retained evidence byte are untouched.

## 1. Purpose

The terrain-aware recovery design
(`docs/handoff/2026-10-29/d5-corridor-recovery-terrain-aware-design.md`)
moved the extension branch to stop tile **50863** fronting **50864** and
declared the stop/front live slope, branch vacancy and the extension-world
acceptance UNKNOWN until a native verify. The existing acceptance-survey
instrument cannot establish those facts (its frozen op surface measures
radius/acceptance/production only), and the extension's own stage-0 gate
runs only inside a mutating-authorized construction launch. This record
describes the new additive read-only instrument built this session, exactly
scoped to close those UNKNOWNs in a dedicated one-launch read-only session
against the pinned world.

## 2. What landed (exact working-tree additions/changes)

- `app/simulation/openttd/corridor_terrain_survey.py` (new) — protocol-7
  wire contract: `TerrainSurveyPlan`, `TerrainRequest`/`TerrainReadback`
  with strict per-op field subsets, fail-closed `parse_for` correlation,
  `verify_request_against_terrain_survey_plan`, and the fail-closed
  `terrain_phase_outcome` replay verifier (a measured nonzero slope or an
  occupied tile is a FINDING of record, never a survey failure).
- `app/simulation/openttd/d5_freight_package/main.nut` — additive
  protocol-7 `TerrainHandle`: its own `terrain_planned` ordered schedule,
  stage/halted accounting, `TERRA_TILES` / acceptance pins,
  `TerrainGuard` bounds and `TerrainFactNorm` boolean normalization. The
  protocol-5 freight and protocol-6 acceptance-survey schedules, latches
  and accounting are untouched. Source-shape finding: the first cut
  compared `typeof` against the literal `"boolean"`; Squirrel's actual
  `typeof` name is `"bool"` (as the package's own protocol-5/6 guards
  use), which would have deadlocked every tile-fact reply. Corrected
  upstream in the same session; the VM suite pins the live `"bool"`
  spellings.
- `app/simulation/openttd/proof/corridor_terrain_survey_native.py` (new) —
  the `D5-TERRAIN-SURVEY-1` native ceremony mirroring
  `corridor_accept_survey_native.py` **by import**:
  `_require_terrain_survey_plan` refuses any other plan model; protocol-7
  only session validation (a freight protocol-5 or protocol-6 frame fails
  before any handler); schedule admits only the read-only
  `radius`/`tile`/`accept` ops with `max_cost` 0 everywhere; funds 492149
  read back per exchange; census hypotheses derived from the retained
  census source the D5 extension module uses (absent row =
  `CENSUS_ABSENT`; a measured divergence is a recorded finding, never
  normalized or refused); one-launch backend; read-only replay verifier
  re-deriving every binding and all nine exchanges through the production
  `terrain_phase_outcome`; cleanup certification gates every completion
  verdict; no forced success label can verify.
- `tests/test_corridor_terrain_survey.py` (new, 17 tests) — Squirrel-VM
  suite driving the shipped `TerrainHandle` in the real VM against the
  staged fact stub surface (happy nine-exchange path incl. the integer
  `TerrainFactNorm` variant, pin/order/pin-drift/company/pause refusals
  with zero observation fields, 32-request budget accounting, terrain
  stage halt, and protocol-5/6 isolation probes).
- `tests/test_corridor_terrain_survey_native.py` (new, 33 tests) — staged
  candidate + payload rebuild + preflight re-derivation, cross-session
  refusal both ways, mutation-op and exchange-budget refusals,
  request/response persistence plus malformed/stale/truncated/over-512
  failures, census hypothesis/finding semantics, and replay fail-closed
  verdicts.

## 3. Pinned identity and schedule

- Attempt: `D5-TERRAIN-SURVEY-1` (fresh identity; no consumed id reused).
- Schemas: `d5-terrain-survey-prelaunch-v1` (+ the readonly/cross-guard
  record schemas in the ceremony); prerequisite and launch-consumed
  lineage reused from `corridor_freight_native`
  (`d5-native-prerequisite-attempt-v1`, `d5-native-launch-consumed`).
- Nine planned exchanges, 32-request budget, 512/512-byte bounds,
  company 0, cargo 1:
  `radius-00`; `tile-00` `50095` (built delivery front, live company-road
  fact), `tile-01` `50096`, `tile-02` `50352`, `tile-03` `50608`,
  `tile-04` `50864` (front), `tile-05` `50863` (stop); `accept-00`
  control `50351` (expected zero per E36, re-measured never assumed) and
  `accept-01` stop `50863`.
- World bound: authoritative D4 candidate-5 after-save
  `a81ac83677732f9951f5acb3a119395020e49b2317adb3419edf6bc626cef261`;
  funds pin 492149.
- Observed per tile op: `slope`, `min_height`, `max_height`, `buildable`,
  `owner`, `tree`, `water`, `coast`, `farm`, `rock`, `rough`, `road`,
  `rail`, `water_transport`, `air_transport` — the same live facts the
  extension's stage-0 gate inspects, sampled before any mutation.

## 4. Verification in this tree

- Focused: terrain VM 16 PASS (+1 by-design skip of the corrected
  deadlock regression pin), terrain-native 33 PASS, acceptance-survey VM
  25 PASS, plus extension 93 and freight 42/55 regressions re-run — all
  green after the format pass (148 + 141 in the two combined runs).
- Static: `ruff check` / `ruff format` clean on all four files,
  `py_compile` clean, `git diff --check` clean.
- No launch, no AdminPort, no staged runtime-area candidate, no
  claim/signature/authorization. `artifacts/experiments/` is unchanged.

## 5. What this instrument does NOT establish

- It does not build anything, does not prove the station op's native
  buildability before its front road exists (the engine constraint the
  recovery design records), does not prove a freight route, and does not
  correct any retained evidence. A nonzero live slope, an occupied tile
  or an acceptance divergence at a pinned tile is a FINDING of record:
  the design record's section-4 alternatives are then re-evaluated
  offline; the world is never mutated to test a hypothesis.

## 6. Remaining gates to execute the survey

1. Fresh independent read-only review of this additive implementation
   (the T7-analog gate; staging in the runtime area is gated on it).
2. Then staging + seal + PRELAUNCH + read-only PREFLIGHT from the
   reviewed bytes.
3. Then ONE fresh explicit operator authorization covering exactly the
   one read-only native session (1 launch, 1 encrypted connection, 9
   planned exchanges within the 32-request budget, zero mutation, funds
   recorded never changed). Nothing in TASKS.md, this document, the
   recovery design record or any past authorization grants it; anything
   broader is refused.
