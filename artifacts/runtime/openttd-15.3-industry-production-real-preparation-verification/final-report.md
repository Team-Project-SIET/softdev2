# Single-native industry-production real-proof preparation

## Baseline

HEAD: `b6f5cfaf65a4025edebf659cd4744b2534341ae1`.
Working tree before task: **21 modified tracked entries and 20 untracked entries**,
including the controlled production implementation and P08 work. Full original
status and authority hashes are retained in `baseline.json`; unrelated work is preserved.
No commit or push performed. HEAD remains unchanged.

## Production target

Supporting structural proof: `/home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-structural-world-real-attempt1`.
Supporting structural digest: `060fb6368d2f73deaf3081ec14c9081b4cad4c70541981fe9199131afbc7ac11`.
Selected industry_id: **0**. Selected cargo_id: **1**.
Eligibility: historical proven structural evidence, a produced relationship.
Target-selection rule: industry_id ascending, then cargo_id ascending, selecting
the lexicographically first member of `produces`. Accepted-only/synthetic sources reject.
Supporting file digests: immutable freeze `production-target.json`.

## Canonical request

request_id: `openttd15-industry-production-001`.
Canonical bytes (ASCII, no trailing newline):

```json
{"cargo_id":1,"industry_id":0,"protocol":1,"request_id":"openttd15-industry-production-001","type":"industry_production"}
```

Size: **121 bytes**.
SHA-256: `2ef8ec7084050cb0d40f108ca2700c091d52a6b1d8eec2dfe4b4d47d4428c670`.
Serializer: existing IndustryProductionRequest.to_bytes(); not reconstructed.
Not sent.

## Native API

Production API: `ScriptIndustry::GetLastMonthProduction` → `GSIndustry.GetLastMonthProduction`.
Transported API: `ScriptIndustry::GetLastMonthTransported` → `GSIndustry.GetLastMonthTransported`.
Percentage API: `ScriptIndustry::GetLastMonthTransportedPercentage` → `GSIndustry.GetLastMonthTransportedPercentage`.
Economy-date/window API: `ScriptDate::GetCurrentDate` → `GSDate.GetCurrentDate`, before/after reads.
Validity APIs: `ScriptIndustry::IsValidIndustry` → `GSIndustry.IsValidIndustry`;
`ScriptCargo::IsValidCargo` → `GSCargo.IsValidCargo`.
Common handler APIs: `ScriptLog::Info` → `GSLog.Info`; `ScriptAdmin::Send` → `GSAdmin.Send`.
Exact generated GameScript names follow tagged15.3 CMake GS selection and export-generator
class-prefix/static-method registration. Retained source hashes validate; all8 original
production reference sources match freshly fetched exact tag bytes. Additional engine,
station-allocation, percent and common-handler authority is retained in the new reference manifest.
Invalid industry/cargo/nonproduced relationships return -1 from metric getters and reject.
production_level: **DEFERRED / NOT INCLUDED**.

Tagged primary authorities: [industry getters](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_industry.cpp),
[date getters](https://github.com/OpenTTD/OpenTTD/blob/15.3/src/script/api/script_date.cpp),
[export generator](https://github.com/OpenTTD/OpenTTD/blob/15.3/cmake/scripts/SquirrelExport.cmake).

## Response contract

Fields: protocol, type, request_id, status, industry_id, cargo_id,
economy_date_before, economy_date_after, last_month_produced,
last_month_transported, last_month_transported_pct.
Worst-case bytes: **335**, verified through current canonical serializer.
Application limit: **512**. Application headroom: **177 bytes**.
Native ceiling: **1450**, strict payload `<1450`. Native headroom: **1115 bytes**.
No level, localized name, label duplication, capacity, rate, stockpile, delivery or pickup fields.

## Semantic claim

Raw production: native previous economy-month counter; zero and nonzero both valid.
Fresh-world/seeded-history ambiguity remains allowed.
Transported: **OpenTTD station-allocation metric**, not vehicle pickup, delivery or attributed throughput.
Percentage: native integer quantization/clamping0..100, zero when production is zero;
no synthetic ratio or universal transported<=produced constraint.
Economy-date bracket: typed native before/after readings with existing V1 range and
monotonicity validation; time metadata does not qualify a historical window.
Qualified history: **NOT PROVEN**; qualified real production history **NOT YET PROVEN**.
qualified_for_planning: **false**. No full IndustryProductionObservation constructed.
Same-run structural provenance: **NOT PROVEN BY THIS SLICE**.
Independent production source: **NONE**. Complete production coverage: **NO**.
Optimizer supply suitability: **NOT PROVEN**. P08 completion: **NO**.

## Evidence

GameScript: BRIDGE_REQUEST_RECEIVED → INDUSTRY_PRODUCTION_READ → BRIDGE_RESPONSE_SENT
→ BRIDGE_POST_RESPONSE_ALIVE, canonical pair/raw metric/date scalar evidence.
Python: INDUSTRY_PRODUCTION_REQUEST_SENT → INDUSTRY_PRODUCTION_RESPONSE_RECEIVED
→ TRANSPORT_RECEIPT_CREATED → PRODUCTION_RECORD_VALIDATED.
Receipt: retained request/response correlation and digests, distinct from semantic proof.
Semantic validation: immutable IndustryProductionVerification retains request/digests,
pair, typed raw fields, economy bracket, payload size, semantic result, runtime and bridge identity.
Liveness: native post-response marker, secure completion barrier, owned process health.
Python correlates native field evidence with the observed response digest; no native SHA256 API claimed.
No real receipt or production values are claimed in this preparation.

## Proof-specific bounds

Application requests: **1**. Query operations: **4** (send, response, completion PING/PONG).
Setup/control overhead: **6** (encrypted PROTOCOL/WELCOME2 + subscription setup3 + QUIT1).
Total post-auth frames: **10 = 2+3+4+1**.
Shared native accounting object: ProductionFrameBudget specializes StructuralFrameBudget;
SecureAdminSession observes actual encrypted/decrypted frames, without double counting receipts.
Exact budget accepted; over-budget rejected. Structural budgets remain unchanged.
Future launches/connections: **1/1**. Retry: **0**. Reconnect: **0**.
Additional command types: **0**. No rollover waiting; later512-request coverage budget not used.

## Attempt identity

Proof kind: **industry-production**.
Attempt ID: `industry-production-v2-native-attempt1`.
Predecessors: **none**.
Lineage behavior: isolated production kind; verified zero-activity prelaunch predecessors
only in a newer revision; runtime failures cannot continue as prelaunch failures.
Structural/cargo/enrichment failures are not production predecessors.
Runtime destination: `artifacts/runtime/openttd-15.3-industry-production-real-attempt1/`.
Destination override rejected; destination equality regression passes. Destination does not exist yet.

## Freeze

Directory: `artifacts/runtime/openttd-15.3-industry-production-real-prelaunch-v2/`.
Earlier revision: original unsuffixed freeze preserved byte-identically.
Revision2 fixes the preflight API-authority reporting flag and declares the full future
artifact inventory. A development inventory-list mix-up was caught and corrected by
controlled tests before freezing revision2; its development test log is retained separately.
Source/input count: **187**.
Protected public files: **1035**.
Archived credential identities: **7**.
Protected manifest digest: `7840c283dc357a94cf27b722ddeed711dcc39b97936b7f55965ab1078164874a`.
Lineage digest: `a9eaa960c96c2f082b091015a0bba84e2a18079d317b509fdc322202b9d0a056`.
Bridge digest: `cee002001d0a7a69c899e94c5c2cf77893a507e69686f4ac2e6d71effe94c58a`.
Request digest: `2ef8ec7084050cb0d40f108ca2700c091d52a6b1d8eec2dfe4b4d47d4428c670`.
Proof-config digest: `f9adc900a671ba95c476e389a27039b465c7f7fe8b58158c56cea029de568be5`.
Frame-accounting identity: `0fc3a21d85a8529a59e0d07d07d15ff10ebc77b7b1cff7ffc5c0211b84459832`.
OpenTTD binary SHA-256: `276d5b698a6b706154f3af588f6f885b3aebe518f4ecc8f869abf71383b1904c`.
OpenGFX archive SHA-256: `43a0c1dabf39cb865394f3a6cc36d4da5c10ecfaaf55652043104806810903be`.
Secure profile: isolated HOME/XDG/config/data, loopback, insecure login disabled,
X25519 AuthorizedKey, owned process, isolated GS package. Fresh credential0600,
public identity distinct from archived identities; private bytes/hashes excluded from evidence.

## Guarded preflight

Public CLI: `.venv/bin/python -m app.simulation.openttd.proof preflight --mode industry-production`.
Freeze loaded: **YES**. Target loaded: **YES**. Request loaded: **YES**.
Native API authority loaded: **YES**. Production validator loaded: **YES**.
Accounting wired: **YES**. Secure credential/config validated: **YES**.
Exact destination and historical supporting target checked: **YES**.
EndpointReservation.allocate() owns/reserves both frozen endpoints: **YES**.
Final subprocess creation boundary validated with creation guard: **YES**.
READY_TO_LAUNCH: **YES**.
Subprocess created: **NO**. Admin connected: **NO**. Request sent: **NO**.
Prelaunch failure: immutable0/0/0 failure evidence, stop, no retry under same authorization.
Post-launch failure: retain available evidence, no resend/reconnect/relaunch, stop/reap,
verify endpoint closure and remove runtime credential.

## Historical integrity

Historical hashes: **all1035 protected public files match**,7 archived credential
public identities/modes match. Exact protected paths/digests are in freeze historical-integrity.json.
Structural-world proof: **byte-identical**, including retained manifest.
Complete catalog, capability/enrichment, inventory and all earlier captured proofs/freezes/failures:
**byte-identical**. Revision1 freeze: **byte-identical**.
Production controlled evidence (both revisions): **byte-identical**.
Production audit/design documents: **unchanged**.
CONTEXT.md: **unchanged** against starting hash and retained prior structural freeze.
Historical files modified: **NO**.

## Tests

- preparation: **57 passed**.
- controlled production: **81 passed**.
- qualification: **16 passed (dedicated subset; also included in the 81 controlled tests)**.
- structural: **117 passed**.
- catalog: **162 passed**.
- capability: **159 passed**.
- inventory: **218 passed**.
- bridge/protocol/transport: **345 passed**.
- secure Admin: **62 passed**.
- lineage: **41 passed**.
- evidence/causality: **53 passed**.
- production CLI: **5 passed**.
- runtime: **64 passed**.
- P03/P04: **73 passed**.
- P05: **37 passed**.
- P06: **51 passed**.
- P07: **22 passed**.
- P08: **78 passed**.
- ordinary: **2255 passed, 38 skipped**.

Module counts are retained in test-counts.json and ordinary-junit.xml. Group totals are
controlled checks; skipped native tests were not executed. They do not prove new native
production binding or history qualification. Production-mode CLI/lifecycle/lineage cases
also live in the57 preparation tests.

## Quality

Ruff: **PASS**. Format: **PASS**,292 files already formatted.
Typecheck: **PASS** for app/simulation/openttd and the new preparation tests.
Diff/import/whitespace: **PASS**. No relevant diagnostic was waived.
Test adequacy review: canonical/schema/error cases, no-activity public preflight,
full controlled lifecycle/cleanup failure cases, lineage, budgets, immutable history and
qualification separation covered. Source review: final source/contract/destination checks pass.

## Runtime activity

Gameplay launches: **0**. Admin connections: **0**. Real requests: **0**.
No economy waiting. No commit. No push.

## Remaining blockers

None for preparation. Separate explicit authorization is required before the single
future native request. Native production binding and qualified real history remain
unproven limitations, not completed claims.

## Status

READY TO REQUEST AUTHORIZATION FOR ONE OPENTTD 15.3 REAL INDUSTRY-PRODUCTION QUERY
