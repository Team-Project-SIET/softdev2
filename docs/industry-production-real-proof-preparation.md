# OpenTTD 15.3 single-native industry-production proof preparation

This slice prepares one separately authorized read-only native binding and raw V1
metric proof. Preparation performs zero gameplay launches, zero live Admin
connections and zero real application requests. It neither waits for economy-month
rollovers nor constructs a complete IndustryProductionObservation. Production
history qualification, optimizer supply, independent semantic equivalence and P08
completion remain unproven. `production_level` is DEFERRED / NOT INCLUDED.

Architecture authority: local CONTEXT.md. Semantic authorities remain
[industry-production-native-api-audit.md](industry-production-native-api-audit.md)
and [industry-production-dynamic-supply-design.md](industry-production-dynamic-supply-design.md).
Neither authority nor historical proof reports are edited by this slice.

## Target and wire contract

Use retained successful REAL same-run structural-world evidence at
`artifacts/runtime/openttd-15.3-structural-world-real-attempt1/` only to choose the
lexicographically first `(industry_id, cargo_id)` in the capability `produces` sets:
`(0, 1)`. Its structural digest is
`060fb6368d2f73deaf3081ec14c9081b4cad4c70541981fe9199131afbc7ac11`.
The manifest, successful REAL activity, pinned native identity, complete same-run
observation, canonical structural digest and capability semantic digest are checked.
Accepted-only, synthetic and nonfirst targets fail. No new discovery request occurs.

The existing IndustryProductionRequest canonical serializer freezes exactly:

```json
{"cargo_id":1,"industry_id":0,"protocol":1,"request_id":"openttd15-industry-production-001","type":"industry_production"}
```

The request is 121 bytes. `production-target.json` retains supporting paths and
file digests. This historical source is never attached to the new process as a
StructuralWorldObservation. Same-run structural/production provenance is NOT
PROVEN BY THIS SLICE.

V1 response fields are exactly `protocol`, `type`, `request_id`, `status`,
`industry_id`, `cargo_id`, `economy_date_before`, `economy_date_after`,
`last_month_produced`, `last_month_transported`, `last_month_transported_pct`.
The production model enforces IDs, integer ranges, nonnegative date brackets,
monotonic readings, request/type/pair correlation and strict field membership.
The existing serializer must reproduce the audited worst-case 335 bytes or
preparation stops. Application limit512 gives177 bytes headroom; native ceiling1450
requires strict `<1450` and gives1115 bytes headroom. Neither localized metadata,
level, capacity, rate, stockpile, delivered cargo nor vehicle pickup is added.

## Exact native authority

Tagged 15.3 retained API sources and generator inputs are hash checked. The original
production manifest was also compared with freshly fetched tag15.3 bytes. Additional
engine sources in `tests/reference/industry_production_proof_15_3/` freeze release,
station allocation, percentage conversion and common bridge API authority.
`source-authority.json` binds those sources and the original semantic audits.

| C++ API | Generated GameScript name | Semantics |
|---|---|---|
| ScriptIndustry::IsValidIndustry | GSIndustry.IsValidIndustry | Native pool membership; false for invalid industry. |
| ScriptCargo::IsValidCargo | GSCargo.IsValidCargo | Active native cargo membership; false for invalid cargo. |
| ScriptIndustry::GetLastMonthProduction | GSIndustry.GetLastMonthProduction | Previous economy-month production counter, uint16 storage; -1 for invalid industry/cargo/nonproduced relation. |
| ScriptIndustry::GetLastMonthTransported | GSIndustry.GetLastMonthTransported | Previous economy-month station-allocation counter, uint16 storage; same -1 cases. |
| ScriptIndustry::GetLastMonthTransportedPercentage | GSIndustry.GetLastMonthTransportedPercentage | Native quantized/clamped integer0..100; zero for zero production; same -1 cases. |
| ScriptDate::GetCurrentDate | GSDate.GetCurrentDate | Current economy date, read immediately before and after metrics. |
| ScriptLog::Info | GSLog.Info | Compact canonical native evidence. |
| ScriptAdmin::Send | GSAdmin.Send | Native table-to-JSON transport;1450-byte ceiling. |

The export CMake rules select `game;GS`; SquirrelExport replaces the `Script`
prefix with `GS` and registers each original static method name. Names are sourced,
not guessed from AI names. No additional industry/date API is introduced into the
handler. Raw zero and raw nonzero (including generation-seeded history) both pass.
Transported means allocation to station waiting cargo, never pickup/delivery or
plan-attributed throughput. No universal transported<=produced inequality or
synthetic percentage is imposed. Date brackets retain read-time metadata; they
neither establish a fully elapsed historical bucket nor planning suitability.

## Owned lifecycle and evidence

Public future execution path:

`python -m app.simulation.openttd.proof run --mode industry-production --authorize-one-launch`

The flag requires separate future explicit user authorization. It must not be used
in preparation. The default immutable freeze is
`artifacts/runtime/openttd-15.3-industry-production-real-prelaunch-v2/`. Revision1
is retained byte-identically; revision2 fixes the preflight native-authority reporting
flag and expands the declared future evidence inventory. The exact sole
future evidence destination is
`artifacts/runtime/openttd-15.3-industry-production-real-attempt1/`.
Destination overrides fail validation. Revisions must be new sibling freezes; no
frozen revision is patched in place.

Public CLI → preflight/freeze/lineage validation → EndpointReservation.allocate()
→ exclusive attempt claim → one owned process → one encrypted X25519 AuthorizedKey
Admin connection → one frozen industry_production request → semantic/evidence
verification → owned cleanup. The backend checks readiness using owned `/proc`
listener identity, not repeated socket connections. No wrapper/manual client,
additional application command, retry, reconnect or relaunch is used.

Lifecycle: PREPARED → LAUNCHED → ADMIN_ACTIVE →
INDUSTRY_PRODUCTION_REQUEST_SENT → INDUSTRY_PRODUCTION_RESPONSE_RECEIVED →
TRANSPORT_RECEIPT_CREATED → PRODUCTION_RECORD_VALIDATED →
POST_RESPONSE_LIVENESS_VERIFIED → COMPLETED. FAILED is explicit. A transport
receipt cannot skip the independent immutable IndustryProductionVerification.
It retains request/response digests, pair, typed raw metrics, date bracket,
payload size, semantic result, runtime/bridge identity and verified status.
It remains `qualified_for_planning=false`, `complete_coverage=false` and has no
independent production source. No rollover state is added to GameScript.

GameScript evidence: BRIDGE_REQUEST_RECEIVED → INDUSTRY_PRODUCTION_READ →
BRIDGE_RESPONSE_SENT → BRIDGE_POST_RESPONSE_ALIVE. Canonical scalars bind every
raw response field. Python evidence: INDUSTRY_PRODUCTION_REQUEST_SENT →
INDUSTRY_PRODUCTION_RESPONSE_RECEIVED → TRANSPORT_RECEIPT_CREATED →
PRODUCTION_RECORD_VALIDATED. Python binds retained native field evidence to the
observed raw response digest; no native SHA256 API is claimed.

## Proof-specific native frame accounting

ProductionFrameBudget specializes the shared StructuralFrameBudget accounting
object with production-specific limits. SecureAdminSession invokes its observer at
the actual encryption/decryption boundary. Query receipts are compared to these
counts, never added a second time. The structural budget remains unchanged.

| Category | Frames | Derivation |
|---|---:|---|
| Establishment | 2 | Encrypted SERVER_PROTOCOL + SERVER_WELCOME after authentication enablement. |
| Setup | 3 | UPDATE_FREQUENCY + setup PING + matching PONG. |
| Production query | 4 | One ADMIN_GAMESCRIPT + one SERVER_GAMESCRIPT + completion PING/PONG. |
| Cleanup | 1 | Graceful ADMIN_QUIT; TCP EOF adds no frame. |
| Total post-auth | 10 | 2+3+4+1; query operations4, setup/control overhead6. |

Exact-at-budget succeeds. An over-budget frame fails before outbound write or
semantic admission. Unexpected traffic cannot consume an arbitrary spare allowance.
One application request/launch/connection; zero retry/reconnect/other command types.
The later complete-coverage512-request ceiling does not apply to this proof.

## Freeze, credentials and failure

The isolated established OpenTTD15.3/OpenGFX profile uses pinned binary/graphics,
isolated HOME/XDG/config/data, loopback endpoints, insecure Admin login disabled,
an isolated bridge package and owned shutdown. A fresh0600 credential's public
identity is frozen and compared against archived identities. Private bytes and
private hashes are excluded from public evidence/source manifests.

The immutable freeze includes baseline HEAD, runtime-critical source/input hashes,
protected historical public paths and archived public credential identities,
protocol/validator/lifecycle/accounting identities, exact target/request, payload
and frame bounds, new `industry-production` lineage, exact destination, public CLI
configuration and evidence validators. Structural/cargo/enrichment failures are
supporting history, never production predecessors. Hardened lineage permits only
verified zero-activity prelaunch predecessors in a newer revision; runtime failure
cannot be continued under prelaunch authorization.

Guarded public preparation check:

`python -m app.simulation.openttd.proof preflight --mode industry-production`

The audit hook forbids subprocess creation and socket connect. It loads and checks
all frozen inputs, credential metadata, target authority, production verifier,
shared frame accounting, exact destination and endpoint ownership; it reaches the
same final validate_launch boundary used immediately before Popen without creation.
Any prelaunch failure retains immutable failure evidence with0/0/0 activity and
stops without retry. Any post-launch failure retains available response/receipt,
semantic/native/network evidence, cleans/reaps the owned process, verifies endpoint
closure and removes the runtime credential. No resend/reconnect/relaunch follows.

A successful future proof establishes only native bindings and raw serialization,
semantic validation, receipt/evidence/liveness and clean shutdown. Qualified real
production history = NOT YET PROVEN. Independent production source = NONE.
Complete production coverage = NO. Optimizer supply suitability = NOT PROVEN.
P08 completion = NO.
