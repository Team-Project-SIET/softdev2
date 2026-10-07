# Post-run industry-production verification

## Final status

OPENTTD 15.3 REAL INDUSTRY-PRODUCTION QUERY FAILED — NO RETRY PERFORMED — cleanup removed 16 frozen source/input files

The frozen public CLI recorded REAL_SUCCESS for transport, typed raw V1 validation,
GameScript/Python evidence and liveness. Its source check ran **before** final
`prepared.dispose()`. Disposal subsequently removed the complete isolated workspace,
including 16 files listed in revision 2's frozen source/input manifest. The required
**post-cleanup all-inputs-exact criterion therefore fails**. No waiver, restoration,
source change, replacement freeze, additional connection/request/launch or retry occurred.
The original CLI result and terminal attempt evidence remain immutable; this separate
post-run analysis records the stricter final acceptance result without rewriting them.

Cause: `app/simulation/openttd/proof/production_attempt.py:285-286` disposes the prepared
workspace after retaining the successful result and manifest. `RuntimeWorkspace.close`
in `app/simulation/openttd/runtime/config.py:115-120` recursively removes that workspace.
This is a frozen lifecycle/retention defect, not a production metric failure.

## Authorization and identities

Only revision 2 used: `/home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-industry-production-real-prelaunch-v2`.
Baseline/current HEAD: `b6f5cfaf65a4025edebf659cd4744b2534341ae1`.
Attempt ID: `industry-production-v2-native-attempt1`. Proof kind: industry-production. Predecessors: none.
Actual runtime evidence destination: `/home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-industry-production-real-attempt1` — unchanged; no suffix or override.
This postrun-verification directory contains offline analysis/tests only; it is not an
alternate runtime attempt destination and performs no native execution.
Guarded public preflight reached READY_TO_LAUNCH with 0/0/0, validated the exact destination
and EndpointReservation ownership. The authorized public CLI was invoked exactly once.

Request ID: `openttd15-industry-production-001`. Pair: industry 0, cargo 1, from historical proven produced
relationship only; supporting structural digest `060fb6368d2f73deaf3081ec14c9081b4cad4c70541981fe9199131afbc7ac11`.
Request:121 canonical bytes; digest `2ef8ec7084050cb0d40f108ca2700c091d52a6b1d8eec2dfe4b4d47d4428c670`.
Response:283 bytes; digest `5d96681fa83e0082ab17316d5751edaf00b3e21f2b7cd71d94e7b8ca50c18e51`.
Bridge digest: `cee002001d0a7a69c899e94c5c2cf77893a507e69686f4ac2e6d71effe94c58a`.
Proof-config digest: `f9adc900a671ba95c476e389a27039b465c7f7fe8b58158c56cea029de568be5`.
Admin-accounting identity: `0fc3a21d85a8529a59e0d07d07d15ff10ebc77b7b1cff7ffc5c0211b84459832`.
Lineage digest: `a9eaa960c96c2f082b091015a0bba84e2a18079d317b509fdc322202b9d0a056`.
Protected manifest digest: `7840c283dc357a94cf27b722ddeed711dcc39b97936b7f55965ab1078164874a`.
Binary, graphics archive, current bridge/protocol/native-authority/validator/accounting source
hashes and public freeze metadata remain exact. The staged package/OpenGFX/config inputs
inside the disposed runtime directory are missing and cannot satisfy final exact-path checks.

## Real native result

| Frozen V1 field | Observed value |
|---|---:|
| industry_id | 0 |
| cargo_id | 1 |
| last_month_produced | 168 |
| last_month_transported | 0 |
| last_month_transported_pct | 0 |
| economy_date_before | 712223 |
| economy_date_after | 712223 |

The exact frozen native production, transported, percentage and GSDate.GetCurrentDate
bindings executed through the real OpenTTD 15.3 GameScript bridge. Raw production 168 is
valid without claiming elapsed/qualified history; generation-seeded history ambiguity
remains allowed. Transported 0 means **station allocation**, not vehicle pickup, delivery,
delivered throughput or plan performance. Native transported percentage 0 is retained
separately, without synthesis. Date brackets validate raw native time metadata, not
planning suitability. `production_level` is **DEFERRED / NOT INCLUDED**.

Semantic validation: VALID_RAW_V1_RECORD / PASS. IndustryProductionVerification.verified=true.
Transport receipt: PASS. Exact request/type/status/pair and response digest correlation: PASS.
GameScript chain: BRIDGE_REQUEST_RECEIVED → INDUSTRY_PRODUCTION_READ → BRIDGE_RESPONSE_SENT
→ BRIDGE_POST_RESPONSE_ALIVE, canonical raw field evidence.
Python chain: INDUSTRY_PRODUCTION_REQUEST_SENT → INDUSTRY_PRODUCTION_RESPONSE_RECEIVED
→ TRANSPORT_RECEIPT_CREATED → PRODUCTION_RECORD_VALIDATED.
Post-response liveness: PASS. No native object/debug representation used in formal evidence.
Actual 283-byte payload satisfies frozen335-byte bound, <=512 and <1450.

## Runtime limits and cleanup

Gameplay launches:1. Live Admin proof connections:1. industry_production requests:1.
Total application requests:1. Retries:0. Reconnects:0. Additional command types:0.
Additional OpenTTD launches:0. No gameplay mutation, P05/P06 execution, P07 evaluation,
P08 extraction or economy-month waiting occurred. Script crashes:0. Protocol errors:0.
Secure X25519 AuthorizedKey authentication and encrypted session: PASS; insecure login disabled.
Shared native accounting: establishment2 + setup3 + production4 + cleanup1 =10 frames.
Proof-specific query operations:4/4. Post-auth frames:10/10. No counter reset.
Clean exit code0; graceful quit and reap. Remaining OpenTTD processes:0.
Endpoints independently re-reserved after shutdown: closed. Runtime credential retained:NO.
Private key was0600 before launch, removed by cleanup and excluded from public evidence.

## Post-cleanup integrity

Frozen source/input entries:187. Matching entries:171. **Missing entries:16 — FAIL**.
The missing files are the ownership marker;10 OpenGFX files;2 staged GameScript files;
and openttd.cfg/private.cfg/secrets.cfg. Exact paths and expected hashes are retained in
missing-frozen-inputs.json and post-cleanup-integrity.json. No hash identities regenerated.
PRELAUNCH.json and top-level public freeze manifest: exact. The isolated subtree is removed.
Runtime attempt payload/terminal identity/manifest: exact and unchanged.
Protected historical files:1035/1035 exact. Archived credential identities:7/7 exact.
Prior structural-world proof, production controlled verification, all earlier captured
proof/freeze/failure evidence and CONTEXT.md: unchanged. Production audit/design docs unchanged.
Current repository source hashes: exact. No source edit, commit or push.

## Post-run verification

Ordinary suite: **2255 passed,38 skipped**. Includes the structural-world, catalog,
capability/enrichment, inventory, bridge/protocol/transport, secure Admin, lineage,
evidence/causality, CLI, external-runtime and P03/P04/P05/P06/P07/P08 regressions.
Dedicated focused run: **138 passed =57 preparation +81 controlled production tests**.
Qualification subset: **16 passed,65 deselected**, also covered by the81 controlled tests.
Ruff:PASS. Format:PASS (293 files). Applicable typecheck:PASS.
Git diff --check:PASS. Whitespace/import-boundary audits:PASS.
These controlled tests do not override the failed post-cleanup input-retention criterion.
No native OpenTTD launch occurred during post-run verification. Module counts and full logs retained.

## Claim boundaries and remaining blocker

Complete production coverage:NOT CLAIMED. No complete IndustryProductionObservation created.
Qualified real production history: **NOT PROVEN**. qualified_for_planning=false.
Same-run structural/production provenance: **NOT PROVEN BY THIS SLICE**.
Independent production source:NONE. Optimizer-ready supply:NOT PROVEN. P08 completion:NO.

Concrete blocker: frozen cleanup deletes inputs whose exact paths/hashes are required
for final verification. A later attempt needs separately prepared/authorized lifecycle
retention semantics under the attempt-lineage rules. No repair or second attempt is
performed under this authorization.
