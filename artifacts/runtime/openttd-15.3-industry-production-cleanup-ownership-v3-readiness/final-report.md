# Industry-production cleanup ownership reconciliation and V3 readiness

## Failure diagnosis

deleted path count: **16**.
classification A/B/C/D: **0 / 12 / 4 / 0**.
exact paths, hashes and the full requested ownership/creator/deletion/lifetime table: [diagnosis](/home/fed/codes/softdev2/docs/industry-production-cleanup-ownership-reconciliation.md).
The 12 copies are ten OpenGFX archive members and two canonical GameScript files. The four generated files are .runtime-owned, openttd.cfg, private.cfg and secrets.cfg. All existed before native launch and were produced by prelaunch setup; none was created by live runtime setup. Canonical archive/package hashes and retained sanitized-config hashes establish this classification. No path was classified by its name alone.

root cause: disposable materialized paths entered the persistent input manifest, while final success preceded their disposal.
cleanup caller: execute_production_attempt → PreparedProof.dispose → LaunchSpecification.close → RuntimeWorkspace.close → shutil.rmtree(reopened workspace root).
freeze-construction cause: prepare_proof appended workspace.root.rglob files (except .admin-secret) to source_freeze alongside canonical sources. Content required to launch was conflated with a path required to survive. Generated configs were included; the private credential was excluded. Direct copied paths, rather than a symlink/bind alias, caused the observed deletion.

## Ownership model

immutable source: canonical source/archive/binary and public generated templates; hash before launch and after disposal; never cleanup-owned.
historical: exact captured public paths and archived credential identities; preserved unchanged; never cleanup-owned.
runtime ephemeral: isolated materializations may be deleted; runtime-materializations.json retains canonical origin/hash, expected copy hash and derivation. Prelaunch validates content before native launch. New runtime descendants inherit disposable ownership.
credential: current .admin-secret is cleanup-owned, mode0600; public identity only, no private bytes/hash in evidence. Archived credentials remain protected historical identities.
generated evidence: formal output belongs to the exact retained attempt directory outside cleanup roots.
ambiguity rule: one ownership class per resolved path. Persistent/evidence paths equal to, beneath or aliasing into cleanup roots are rejected before launch. Symlinks and cross-policy hardlinks are rejected. Recursive disposal validates the frozen graph and ownership marker. Canonical input inventory/public manifest have explicit persistent ownership and post-disposal canonical byte checks.

## Lifecycle repair

old final-success point: COMPLETED/REAL_SUCCESS and terminal manifest, then prepared.dispose.
new final-success point: **COMPLETED only after mandatory cleanup and POSTRUN_INTEGRITY_VERIFIED**.
workspace disposal ordering: retain logs/evidence → owned process reap and endpoint closure → credential removal → workspace disposal.
post-run integrity ordering: hash persistent inputs and validate protected history **after workspace disposal**, then final success.

RUNTIME_SEMANTICS_VERIFIED → CLEANUP_STARTED → PROCESS_REAPED → ENDPOINTS_CLOSED → CREDENTIAL_REMOVED → WORKSPACE_DISPOSED → POSTRUN_INTEGRITY_VERIFIED → COMPLETED; FAILED explicit. Cleanup/integrity failure cannot retain a true final source_integrity claim. The same finalization gate is used by ACK/world_info, industry/inventory, cargo/page/catalog, enrichment and structural-world runners. Their original successful historical proofs remain valid evidence for their original configurations; no unsupported retroactive invalidation or rewriting occurred.

## Attempt 1

freeze: openttd-15.3-industry-production-real-prelaunch-v2/PRELAUNCH.json.
attempt: industry-production-v2-native-attempt1; immutable terminal identity industry-production-v2-runtime-8ef0fd0237929ac5.
classification: **POST-LAUNCH FAILURE**.
launches:1. connections:1. requests:1. retries:0. reconnects:0.
native semantic result: PASS before final integrity failure; raw production168, station allocation0, transported percentage0, economy bracket712223→712223, response283 bytes. These are historical observations, never new expected constants.
overall result: **FAILED**.
evidence immutable: YES. Native runtime report still retains its original intermediate REAL_SUCCESS; the separately retained post-run verdict remains FAILED. No repair/restoration/retry of Attempt1.

Narrow supported claim: REAL NATIVE INDUSTRY-PRODUCTION BINDING EXECUTED SUCCESSFULLY DURING ATTEMPT 1 BEFORE POST-RUN INTEGRITY FAILURE. Qualified history, complete production coverage and same-run structural/production provenance: NOT PROVEN. Independent production source:NONE. P08 completion:NO.

## Production semantics

protocol changed: **NO**.
response contract changed: **NO**.
production_level: **DEFERRED / NOT INCLUDED**.
query ceiling: **4**.
frame ceiling: **10** (2 establishment +3 setup +4 query +1 cleanup).
Worst-case response335 bytes, application512/native1450, headroom177/1115 unchanged. Canonical request121 bytes, target0/1; target selection remains historical proven lexicographic first produced pair, not new same-run provenance. Produced/transported independent unsigned native counters, native percentage and economy-date brackets retain audited semantics; transported means station allocation, not pickup/delivery. Raw zero/nonzero valid; no rollover waiting or planner qualification.

## V3

freeze directory: `/home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-industry-production-real-prelaunch-v3/`.
baseline HEAD: `b6f5cfaf65a4025edebf659cd4744b2534341ae1`.
source/input count: **181** persistent hash entries, plus explicit canonical inventory/manifest byte validation.
protected public files: **1133**.
archived credential identities: **7**.
protected manifest digest: `42832f81f6a320fcbd6a0c88132cfeda222714ab034e63fd5d12bb70b60612ee`.
lineage digest: `e25039ba5307dfbb53c76d9ef3d99ae9d344df12be209647a14f26f8fe70c883`.
bridge digest: `cee002001d0a7a69c899e94c5c2cf77893a507e69686f4ac2e6d71effe94c58a`.
request digest: `2ef8ec7084050cb0d40f108ca2700c091d52a6b1d8eec2dfe4b4d47d4428c670`.
proof-config digest: `f9adc900a671ba95c476e389a27039b465c7f7fe8b58158c56cea029de568be5`.
shared Admin-accounting identity: `1ab02c572cc6d30604b6bc0f51eeb57af9c9c26ab4db5be814d54715bed39b5f`.
future destination: **artifacts/runtime/openttd-15.3-industry-production-real-attempt2/**.
Fresh v3 credential: mode0600; distinct from historical public identities; private bytes excluded. It remains restricted in the prepared workspace pending fresh authorization. V3 sources, ownership graph, materialization identity, native binary/OpenGFX/bridge/protocol/validator/API authorities, request/target, public CLI config and lineage are frozen. V3 was not patched after creation.

## V3 lineage

Attempt1 classification: **POST-LAUNCH FAILURE**.
prelaunch exception used: **NO**.
fresh authorization required: **YES**.
new attempt ID: `industry-production-v3-native-attempt2`.
predecessor authorized ID: `industry-production-v2-native-attempt1`.
predecessor freeze revision:2.
predecessor runtime manifest digest: `85cad0c7e27084bb6dc1ffe5bea40a27c18a3d97f4feeae6d919678e2b1e9f23`.
predecessor revision authority digest: `a494e98079457b3e43d5a2b261bd30711ef815350912bfb54bfb90fa18a869e5`.
post-run failure evidence: `/home/fed/codes/softdev2/artifacts/runtime/openttd-15.3-industry-production-real-attempt1-postrun-verification`.
post-run manifest digest: `9ab055a78090d13025ba1005e5d237d49abe44f5471bf98e0aab81614ae545e1`.
post-run report digest: `6fba907f86fb2c213374e0960d9a2ed3999dd6f8c766148d19a64194f8d932dc`.
post-run integrity digest: `0fdaf62885e80dc1c69cc0b396483646ec44e80bbc8edb72e5f1b2b4bdd1af33`.
terminal failure reason: Final prepared.dispose()/RuntimeWorkspace.close removed isolated workspace containing 16 frozen inputs; no repair or retry.
Lineage uses actual launches for numbering. Prelaunch-only failures remain distinct. Attempt1 destination and overrides are rejected; no consumed-freeze or consumed-attempt retry.

## Guarded preflight

public CLI: `.venv/bin/python -m app.simulation.openttd.proof preflight --mode industry-production --directory artifacts/runtime/openttd-15.3-industry-production-real-prelaunch-v3`.
ownership validation: PASS; no persistent/cleanup intersection.
lineage validation: PASS; one post-launch predecessor; no continuation exception.
READY_TO_LAUNCH: **YES**.
subprocess created: **NO / 0**.
Admin connected: **NO / 0**.
request sent: **NO / 0**.
Exact target/request/digest/secure config/4-query/10-frame/destination loaded. EndpointReservation.allocate ownership resolved and reservations released. Final production subprocess boundary validated with process/connection audit guards installed; creation blocked. No public run command invoked.

## Historical integrity

PRELAUNCH v2: byte-identical public evidence.
Attempt1 evidence: byte-identical native and post-run reports/manifests.
older evidence: exact; original before-task protection1116 public files and7 archived credentials verified. V3 additionally protects the17 immutable controlled-repair verification files, yielding1133.
CONTEXT.md: unchanged.
files restored: **NO**; all16 old missing paths remain absent.
Historical files modified:NO. Original audit/design docs, production protocol/models/validator, canonical GameScript bridge and controlled production evidence remain unchanged. New source repairs and a separate diagnosis document only.

## Tests

ownership: **33 passed**.
lifecycle: **9 full controlled production cases passed**, including cleanup/disposal/integrity failures; final ordering and canonical manifest mutations covered.
freeze/source integrity and preparation: covered by33 ownership +59 production proof/preparation tests.
production: **81 controlled tests passed**; proof/preparation59 passed.
qualification: **11 dedicated regressions passed**, also included in81.
lineage:41 shared enrichment lineage regressions plus production/new-attempt/exception tests; public V3 validation PASS.
structural:117 passed.
catalog:162 passed (catalog/page).
capability/enrichment:159 passed.
inventory:218 passed (inventory/page).
bridge/protocol/transport:345 passed; evidence/causality53 passed; Admin session13 passed.
secure Admin:62 passed.
production CLI:5 existing CLI tests plus public production dispatch/guard tests within59; real V3 guarded preflight PASS.
runtime:64 external/assets controlled tests passed.
P03/P04:73 passed,1 opt-in skipped. P05:37 passed. P06:51 passed. P07:22 passed. P08:78 passed.
ordinary: **2290 passed,38 skipped**. No opt-in native test executed.
Focused run: **173 passed =33 ownership +59 proof/preparation +81 controlled production**.
Full module counts and JUnit/logs: `openttd-15.3-industry-production-cleanup-ownership-controlled-verification/`.

## Quality

Ruff:PASS.
format:PASS (297 files).
typecheck:PASS for OpenTTD source and changed proof/ownership tests.
diff/import/whitespace:PASS. Unrelated existing ther.md whitespace and established planning-adapter imports outside the proof/runtime boundary remain unchanged/non-blocking.

## Runtime activity

launches: **0**.
connections: **0**.
real requests: **0**.
No gameplay mutations, retry, commit or push.

## Status

**READY TO REQUEST FRESH AUTHORIZATION FOR OPENTTD 15.3 REAL INDUSTRY-PRODUCTION QUERY ATTEMPT 2**
