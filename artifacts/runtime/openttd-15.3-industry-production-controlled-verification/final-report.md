# OpenTTD 15.3 controlled industry-production implementation

## Baseline

HEAD: `b6f5cfaf65a4025edebf659cd4744b2534341ae1`, unchanged.
Working tree before task: existing README/SRS/planning-boundary changes, untracked
P08 preparation work/tests/design, local CONTEXT.md/.env.example, and the two production
audit documents. Those unrelated changes and authority documents were preserved.
No commit or push.

## Protocol

Command: `industry_production`, one industry/cargo pair, no pagination.
Request: protocol1, type, request_id, industry_id, cargo_id.
Canonical example child request:

```json
{"cargo_id":1,"industry_id":3,"protocol":1,"request_id":"openttd15-industry-production-001-p001","type":"industry_production"}
```

Canonical request size:126 bytes for that example.
SHA-256:`a3033799f72e8ea4a0cf5625e7562dd07468cb34ddc6969ac41560b22458725d`.
Response: `industry_production_result`, statusok, request/pair IDs,
economy_date_before/after, last_month_produced, last_month_transported,
last_month_transported_pct, production_level.
Worst-case canonical response:358 bytes. Application headroom154, native headroom1092.
Limits remain512 and strict <1450. The audit's335-byte candidate excluded level;
the current requested distinct level field adds23 bytes. Audit documents unchanged.

## Native APIs

Production: ScriptIndustry::GetLastMonthProduction → GSIndustry.GetLastMonthProduction.
Transported: ScriptIndustry::GetLastMonthTransported → GSIndustry.GetLastMonthTransported.
Native percentage: ScriptIndustry::GetLastMonthTransportedPercentage →
GSIndustry.GetLastMonthTransportedPercentage.
Production level: ScriptIndustry::GetProductionLevel → GSIndustry.GetProductionLevel.
Date brackets: ScriptDate::GetCurrentDate → GSDate.GetCurrentDate.
Validity: GSIndustry.IsValidIndustry / GSCargo.IsValidCargo.
Exact15.3 source/header/export-generator authority is hash-pinned in the new reference
manifest. Native bindings are source verified and the actual handler exercised under
controlled SQVM fake APIs, not proven in real OpenTTD here.
Unsupported getters: no general industry cargo-rate or output-stockpile getter invented.
Input waiting, income and dynamic acceptance APIs remain excluded.

## Models

Record: immutable IndustryProductionRecord, exact raw metrics/date brackets/level.
Observation: immutable IndustryProductionObservation, source structural reference,
same-run context, qualification, canonical records, validated transactions and budgets.
Qualification: immutable ProductionWindowQualification with typed economy-month readings.
Planning composition: future seam documented; no new planner composition or P08 mapping.
StructuralWorldObservation modified: **NO**. Inventory/capability/catalog also unchanged.

## Qualification

Initial: UNQUALIFIED_INITIAL, including seeded positive native values.
First rollover: UNQUALIFIED_AFTER_FIRST_ROLLOVER.
Second rollover: QUALIFIED_AFTER_SECOND_ROLLOVER, measured intervening full economy month.
Qualified_for_planning requires complete validated coverage and coherent same-run window.
Complete vs qualified: explicitly separate; complete initial/first-window observations
remain unqualified. Duplicate readings do not increment count; skipped/backward boundaries
or changed runtime/process/connection/world/config/bridge fail. Capture brackets must
remain in one current economy month. Qualified window is sealed.
Owner supplies controlled economy-clock readings; no native month observer or real
warm-up is implemented. Native preparation must prove observed boundaries and industry
presence/identity throughout the measured interval. No positivity/wall-clock proxy.

## Bounds

Max industries32; native produced cargo slots16; max records/requests32×16=512.
Max cumulative bytes512×358=183296. A full512-pair controlled run passes through the
shared transport without resetting IDs or accounting. A513th production request fails.
Abstract query-operation allowance512×8=4096, consumed from real exchange accounting;
this is **not** a native total post-auth Admin-frame budget. Future preparation must
derive combined structural+production native frame limits independently.

## Referential integrity

Industry: must exist in the complete source structural observation.
Produced cargo: target comes only from that industry's immutable produces capability.
Catalog: every target cargo must exist in the source complete catalog.
Accepted-only / missing cargo / extra or duplicate pair: rejected.
Shared cargo and multiple outputs: valid. Empty industry world performs zero queries.
Exact complete coverage required; partial failures retain evidence and publish no complete
observation or digest. Source structural digest and context match exactly.

## Digest

Ordering: industry ID ascending, then cargo ID ascending.
Stable fields: source structural semantic digest, qualification/window identity and exact
raw produced/transported/native-percentage/current-level metrics.
Qualification identity: status/count plus observed economy-month identities/boundaries.
Capture brackets remain retained evidence; coherent month is canonical window authority.
Request-ID independence: tested. Transaction-order independence: tested.
No logs, paths, timestamps, packets, localized strings or memory addresses.
Source structural digest remains unchanged when dynamic qualification/data changes.

## Evidence

GameScript: REQUEST_RECEIVED → INDUSTRY_PRODUCTION_READ → RESPONSE_SENT → POST_RESPONSE_ALIVE.
Python: INDUSTRY_PRODUCTION_REQUEST_SENT → RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED →
PRODUCTION_RECORD_VALIDATED.
Session: STARTED → validated records → PRODUCTION_OBSERVATION_ASSEMBLED →
PRODUCTION_QUALIFICATION_EVALUATED → COMPLETED; FAILED explicit.
Qualification is separately retained semantic evidence, not inferred from a receipt.
Canonical pair/date/metric/level metadata correlates against response and receipt digests.
No fabricated native SHA-256 or cross-process total clock ordering.
Timeout/disconnect/missing liveness fails terminally; no retry/reconnect/resume.
Evidence wait and cleanup are bounded. Original owned connection is closed; cleanup
failure is retained separately without masking the original failure.

## Semantics

Seeded last-month values: raw initialization estimates until qualified, not observed history.
Zero: valid and ambiguous; cannot remove structural capability or imply capacity.
Transported: station waiting-cargo allocation, not vehicle pickup or final delivery.
Percentage: exact native quantized/clamped service indicator, not a synthetic ratio.
Native uint16 counters may wrap; transported<=produced is not a universal wire assertion.
Production level: current dimensionless industry control state, not monthly quantity.
Capacity/rate: no native generic rate promised; no quantity×level calculation.
Stockpile: no output stockpile getter added.
Stable-world assumption: same-run collection remains non-atomic; external/autonomous
changes and industry replacement require future native qualification/provenance safeguards.

## Planning boundary

PRE-DECISION: collector checks owner decision boundary before/after reads/evidence/assembly.
POST-DECISION: owner marking intervention rejects later input collection; no evaluation
telemetry enters this builder. Future evaluation has separate attributed windows.
P08 coupling: none; no planning/evaluation imports in query/transport/new observation code.
Future adapter: explicit projection policy plus complete, qualified same-run provenance.

## Verification claim

Controlled production query: PROVEN.
Real native production binding: NOT YET PROVEN.
Qualified real production history: NOT YET PROVEN.
Independent production source: NONE.
P08 completion: NO.

## Historical integrity

997 captured hashes remain exact, including previous runtime proof/freeze/failure evidence,
CONTEXT.md and all four existing semantic model sources. Structural-world proof, cargo
proof and enrichment proof unchanged. Historical files modified: NO.
New checkpoint bridge fixture is a byte-identical copy from baseline with hash manifest.
Legacy proof regressions explicitly use it; old frozen gate/API/digest contracts are not
weakened to accept the expanded production bridge. Current bridge has a separate exact
read-only method/symbol audit. No old proof report rewritten.

## Tests

Production/qualification: **82 passed** (controlled typed models, transport, full512-pair
run, SQVM handler, evidence, qualification, failures, budgets, provenance and digest).
Structural:65 semantic +36 production-preparation +16 frame-budget regressions passed.
Catalog:79 controlled catalog tests plus cargo-page/complete catalog proof regressions passed.
Capability/enrichment, inventory, industry-page/cargo, world-info, bridge/protocol/transport,
secure Admin, lineage, causality, production CLI and external runtime regressions passed
within the ordinary suite.
P03/P04/P05/P06/P07/P08: controlled regressions passed in ordinary suite; native tests skipped.
Ordinary suite: **2198 passed, 38 skipped** in153.93s. One additional whole-current-bridge
API audit was added after that run's collection; it passes in the final82-test focused run.
All current tests are covered by those runs; no source implementation changed after them.

Test adequacy review: passed across semantics, failures, boundaries, controlled integration
and assertions. Standards review: all reported findings fixed; no blocking findings.
Spec review: all reported findings fixed; no blocking findings.

## Quality

Ruff: PASS (repository).
Format: PASS (284 Python files).
Typecheck: PASS (app/simulation/openttd + production tests).
Known unrelated planning diagnostics were not changed.
Diff: git diff --check PASS.
Whitespace: changed/new owned-source audit PASS; exact upstream/checkpoint copies preserved.
Import boundary: new observation/query/session/transport AST audit PASS.

## Runtime activity

Launches:0. Live Admin connections:0. Real application requests:0.
No native runtime smoke test, production credential/freeze, commit or push.

## Status

READY FOR SINGLE-NATIVE INDUSTRY-PRODUCTION REAL-PROOF PREPARATION
