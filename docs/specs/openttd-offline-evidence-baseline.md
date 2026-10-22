# Verified OpenTTD offline evidence contract baseline

## Status and authority

Reference baseline prepared on 2026-10-10 against the current uncommitted worktree
at HEAD `b10cd2dc99b241ff713b3211d87662be7d5136b7`. `CONTEXT.md` is architecture
authority. This document records existing behavior; it creates no seal, changes no
validator and authorizes no execution. A documentation baseline is not an immutable
runtime source freeze. Future proofs need their own reviewed exact source inventory.

The independent audit concluded 24 PASS, 0 DEFECT, 0 INCONCLUSIVE and 0 NOT_TESTED.
The final adjudication carried forward 23 completed cases and independently tested
Historical Root Substitution. The latest completed verification was 188 canonical
identities, 515 focused tests passed with 12 skipped, and 3,350 ordinary tests passed
with 48 skipped and 3 real-native tests deselected. Ruff, formatting, scoped typecheck,
the scoped log-evidence import audit and diff checks passed. These are prior verified
results, not executions by this documentation task. Ordinary skips comprise 35
PostgreSQL opt-in cases and 13 unavailable tagged VM/probe cases.

Related records: [repair history](../p08-15-3-offline-terrain-evidence-repair.md),
[multi-page plan](p08-multi-page-terrain-acquisition.md), and
[existing terrain design](../p08-15-3-native-terrain-road-acquisition-design.md).
Earlier repair results in those documents remain historical stage-specific reports.

## Existing identifiers

| Component | Existing identifier and source |
| --- | --- |
| Controlled collector semantic record | `terrain-two-sweep-v1`, `TerrainObservation` semantic digest record |
| Tile wire protocol | `protocol=1`, `tile_facts_page` / `tile_facts_page_result`, `tile_facts.py` |
| Canonical retention | `terrain-durable-canonical-v1`, `terrain_retention.POLICY` |
| Log scope | `terrain-execution-log-v1`, `terrain_logs.POLICY` |
| Path ownership | `resolved-path-ownership-v1`, runtime `OwnershipGraph.public()` |
| Materialization ledger | `frozen-content-disposable-path-v1`, `ownership.freeze_materializations()` |
| Historical inventory | `historical-exact-paths-v1`, `historical_protection.POLICY` |
| Endpoint closure | `linux-kernel-endpoint-closure-v1`, `endpoints.POLICY` |
| Independent authorization DTO | `openttd-terrain-one-launch`, version 1, `OneLaunchAuthorization` |
| Model A local policy | `OPERATOR_ATTENDED_LOCAL_PROOF`; REAL trust `LOCAL_OPERATOR_ATTESTED`, CONTROLLED trust `CONTROLLED_OPERATOR_ATTESTED` |
| Proof operation | `openttd-15.3.tile_facts_page.single_page` |
| PRELAUNCH subject | `mode=terrain-single-page`, `state=SEALED_UNAUTHORIZED`; no separate top-level numeric schema version |

The independent authorization DTO does not establish an installed signing issuer.
Model A remains a separate local operator-attested policy. No new identifier or
schema version is introduced here. Existing documents without a schema field must
not be described as globally versioned merely because some policy identifiers end in v1.

## Authoritative artifact inventory

`terrain_attempt.verify_attempt_inventory()` authorizes successful attempt outputs
independently of `harness.manifest()`. A mutable manifest describes bytes; it cannot
permit extra artifacts. The full verifier rejects symlinks, directories and other
nonregular attempt members before opening them. This also rejects nested artifacts.

Every successful attempt requires `accounting.json`, `artifact-manifest.sha256`,
`authentication.json`, `cleanup.json`, `cleanup.raw.json`, `execution-log.json`,
`launch-claim.json`, `receipt.json`, `response.json`, `result.json`,
`source-identities.json` and `stderr.log`.

A durable canonical package additionally requires `authorization-consumed.json`,
`cleanup-attestation.json` and exactly one mode-specific invocation marker:
`native-launch-claimed.json` for REAL or `controlled-launch-claimed.json` for
CONTROLLED. The opposite marker is forbidden. `stdout.log` is the only optional
successful-attempt member, emitted when the owned capture exists.

Failure writers can retain partial evidence, `failed-response.json` and bounded
failure diagnostics. Such records preserve failures; they never authorize successful
offline acceptance. A failed status or non-null result error rejects before success
inventory acceptance. Do not delete diagnostics to manufacture a successful package.

`terrain_retention.verify_inputs()` separately requires the seal root to contain
exactly `PRELAUNCH.json`, `SEAL.sha256`, `artifact-manifest.sha256`,
`source-freeze.json`, `historical-integrity.json`, `runtime-materializations.json`,
`path-ownership.json`, `request.json`, `canonical-inputs.json` and `canonical/`.
The index permits exactly its reviewed `canonical/<sha256>` regular objects, with
no unexpected objects, duplicate identities, symlink substitutions or traversal.
Objects may be deduplicated by content digest; 188 logical identities does not mean
188 distinct content objects. 188 is the verified current inventory count, not a
permanent schema constant.

## Immutable authority and validation order

The externally reviewed PRELAUNCH SHA256 is the acceptance authority. Its subject
binds candidate bytes, the canonical index, ownership metadata, request, source and
configuration identities, runtime/graphics/bridge digests, endpoints/public key,
exact attempt/destination, budgets, acceptance/cleanup declarations, historical
base and historical inventory digest, and log policy. `SEAL.sha256` alone is an
unkeyed self-check, not an independent trusted signature.

`verify_retained_attempt()` follows this current order:

1. Canonical absolute attempt directory, regular member types and manifest equality.
2. Mode/status/error, one-shot counts and frame/accounting invariants.
3. Source and log-scope presence, claim mode/no-retry, then exact mode-specific inventory.
4. Seal manifest, PRELAUNCH/SEAL identity, destination and source-inventory agreement.
5. `verify_inputs()`: retained index/objects, reviewed provenance, candidate/package,
   materialization and ownership commitments, historical inventory binding, resolver
   and protected filesystem bytes.
6. Runtime workspace/key absence and exact disposal attestation; request binding.
7. REAL authenticated encrypted-session evidence, then universal authorization/invocation lineage.
8. Response/receipt, snapshot and final log verification; `verify_page()` and result-gate reconciliation.
9. Raw/normalized cleanup agreement, lifecycle/accounting, endpoint closure,
   post-run gate and final cleanup-gate consistency.

Historical root substitution with the original immutable commitment rejects in
`verify_inputs()` as `Historical protection differs from immutable seal`, before
`explicit_protection_base()`. This is the intended authorization boundary. The
resolver separately requires an existing canonical absolute base equal to the
trusted base; it rejects relative, missing, wrong, traversal and symlink aliases.
`validate_protection()` checks exact protected inventory and hashes. There is no
contract requiring unauthorized metadata to reach the resolver first.

## Mandatory result gates

| Gate | Independent verification and required result |
| --- | --- |
| `schema_valid` | Parsed canonical response/receipt; boolean true from `verify_page()` |
| `coverage_valid` | Tiles 65–69 in order, region [1,1,5,1], cursor 0, terminal page; boolean true |
| `native_read_evidence` | Response-correlated native marker facts; boolean true |
| `post_yield_liveness` | Complete expected marker sequence; boolean true |
| `response_sha256` | Exact response bytes/receipt; identical verified digest string |
| `evidence_sha256` | Explicit validated snapshot byte range; identical verified digest string |
| `post_run_integrity` | Source/ownership/history verification and disposal attestation; boolean true |
| `cleanup` | Established cleanup, endpoints and disposal checks already passed; boolean true |

Type and value must agree for the six `verify_page()` outputs. Mandatory cleanup
and post-run gates require actual boolean true. Readiness lists and diagnostic fields
are not substitutes. Success status is exactly `<mode>_PASS` with no error; a failed
attempt can be legitimate failure evidence but cannot return successful acceptance.

## Contract coverage matrix

Paths below are relative to `app/simulation/openttd/proof/` unless qualified.
Tests are in `tests/`; these names identify executable regressions, not new runs.

| Mandatory invariant | Evidence/authority | Verification function | Regression reference |
| --- | --- | --- | --- |
| Exact successful artifact set/types | Production writer contract, mode | `terrain_attempt.verify_attempt_inventory`, `verify_retained_attempt` | `test_terrain_offline_retention.py::test_exact_attempt_inventory`, `test_valid_optional_stdout_inventory` |
| Canonical content and exact coverage | PRELAUNCH index digest, source freeze, retained objects | `terrain_retention.verify_inputs` | `test_durable_input_damage_rejects`, `test_full_production_inventory_package` |
| Reviewed origin, exact bridge identity, no aliases | Candidate and source commitments | `retain_inputs`, `verify_inputs` | `test_exact_external_source_policy`, `test_wrong_original_source_provenance_rejects` |
| No secret retention; runtime disposal mandatory | Reviewed public configs, workspace/key paths | retention content checks, `verify_retained_attempt`, `ownership.dispose_and_verify` | `test_secret_configuration_never_copied`, `test_private_key_not_retained_and_cleanup_mandatory` |
| Ownership semantics and seal binding | PRELAUNCH ownership digest, graph/materializations | `verify_retained_ownership`, `OwnershipGraph.validate` | `test_ownership_semantic_challenges`, `test_ownership_substitution_defect_regression` |
| Materialization derivation and retained origins | Ledger plus immutable candidate commitments | `verify_inputs`, `ownership.validate_ownership` | `test_full_production_inventory_package`, `test_ownership_semantic_challenges` |
| Historical root and unchanged captured history | PRELAUNCH base/inventory digest | `explicit_protection_base`, `validate_protection`, `verify_inputs` | `test_mutable_manifests_cannot_replace_historical_base`; `test_terrain_historical_root.py` |
| One-shot authorization, claim and invocation | Seal/attempt/destination, consumed digest, owner/trust | `verify_execution_lineage`, final prelaunch and claim routines | `test_controlled_lineage_defect_regression`; `test_terrain_model_a.py` |
| CONTROLLED cannot authorize native execution | Explicit controlled grant, mode marker | lineage and native grant checks | `test_controlled_grant_cannot_authorize_native_process`, `test_synthetic_real_contract_rejects` |
| REAL authenticated encrypted session | Authentication/public-key identity, sealed public config | `verify_retained_authentication` | `test_production_verifier_checks_authentication` |
| Request/response/schema/exact coverage | Frozen request, response, receipt, marker facts | `verify_page`, `TileFactsExchange.validate` | `test_tile_facts_protocol.py`, `test_terrain_single_page_preparation.py` |
| Snapshot and final log distinct exact scopes | `execution-log.json`, retained stderr | `terrain_logs.verify_log_record` | `test_log_scope_rejects_tampering`, `test_appended_log_production_verifier` |
| Lifecycle frames and query counts | Accounting categories, receipt | `verify_retained_attempt` | `test_terrain_model_a.py`; `test_terrain_query.py::test_accounting_observer_mismatch_rejects_receipt` |
| Raw/normalized cleanup consistency | Same observation phase, process/endpoints | `verify_cleanup_records` | `test_cleanup_consistency_full_verifier`, `test_real_shaped_cleanup_requires_observed_process_exit` |
| Final endpoint identity and socket semantics | Sealed ports, final kernel rows and closure summary | `endpoints.verify_retained_endpoints` | `test_endpoint_observation_full_verifier`, `test_coordinated_cleanup_cannot_override_endpoint_observation` |
| Successful result agrees with evidence | Result gates plus independently verified outcomes | `verify_retained_attempt` | `test_result_gate_consistency_full_verifier` |
| Permitted original cleanup excludes persistent inputs | Ownership, protected/source/asset/retained identities | production retention plus fixture deletion guard | `test_all_permitted_temporary_originals_can_disappear`, `test_fixture_deletion_rejects_persistent_and_aliased_paths` |
| Independent acceptance after permitted cleanup | Entire retained package and declared authorities | `verify_retained_attempt` in fresh interpreter | `test_offline_after_candidate_and_runtime_cleanup`, `test_full_production_inventory_package` |
| Historical legacy limits remain explicit | Original retained evidence and missing sources | `inspect_legacy_attempt` | `test_historical_pass_remains_blocked_and_byte_identical` |

## Independent audit summary and archival limitation

The completed audit verdict is 24 PASS, 0 DEFECT, 0 INCONCLUSIVE, 0 NOT_TESTED.
In the final adjudication, 23 PASS cases were carried forward. The remaining root
case became PASS through two independent propositions:

| Proposition | Newly executed evidence | Boundary and result |
| --- | --- | --- |
| Unauthorized root substitution | Two full-verifier calls, mutable manifests recomputed, immutable authority unchanged | `verify_inputs`: immutable historical digest rejection twice |
| Authorized root path/integrity guarantees | 13 isolated production-function checks | Valid base, cwd independence and bytes accepted; relative/wrong/missing/traversal/symlink/ambiguous identities and changed/missing history rejected |

A fresh production CONTROLLED package had 188 canonical identities and accepted
before cleanup, after cleanup and in a fresh interpreter. The final quality gates
above were newly executed in that adjudication. The other 23 adversarial cases were
not rerun there. Do not call all 24 fresh executions.

The original 24-row JSON bytes remain unavailable. The supplied conversation
reports are now archived as the clearly labeled
[Reconstructed Independent Audit Summary](openttd-reconstructed-independent-audit-summary.md).
It records all reported cases and the separate root adjudication, without inventing
payloads, timestamps or fixture hashes. Search references and assurance limits are
included there. This is not recovery of the original primary artifact.

No exact-original-JSON archival gate was found in the established project contract
or production acceptance inventories. The earlier documentation completeness blocker
is resolved by the supplied named-case summary. Controlled verification remains PASS;
primary audit preservation remains incomplete; freeze review is READY with this
archival limitation disclosed. Mandatory runtime evidence requirements are unchanged.

## Guarantees, compatibility and reuse

Cryptographic verification establishes exact bytes and relationships relative to
a trusted reviewed seal digest. Semantic verification establishes approved inventories,
provenance/ownership, schemas, coverage, accounting, endpoint/cleanup agreement,
log ranges and mandatory result consistency. Mutable manifests alone establish neither
authorization nor semantic correctness.

Model A operator identity, authentication/lifecycle observations, native execution
and cleanup events are locally attested. Coordinated fabrication of all local
attestations is not independently excluded by unkeyed hashes. The trusted verifier
source and declared absolute external historical root remain dependencies. Absence
of retained private credentials does not prove physical secret erasure.

Future CONTROLLED attempts must use controlled fixtures and markers, never REAL_PASS.
Future REAL attempts require separately reviewed fresh source/package commitments,
one-shot attended authorization, REAL authentication and native lifecycle evidence.
No repaired validator retroactively upgrades an old seal. Unknown policies and missing
mandatory evidence fail closed; no attempt-specific exceptions are permitted.

Historical native single-page REAL_PASS is SUPPORTED. Complete historical offline
acceptance remains AUDIT_BLOCKED with 13 missing original canonical inputs. The last
independent check preserved 1,868 artifacts and validated 1,847 protected paths.
Current development source edits may differ from historical frozen sources; they
must not alter historical artifacts or recorded commitments. Nothing is reconstructed.

P08 may reuse unchanged canonical retention, explicit ownership and disposal,
historical authority validation, endpoint socket semantics, secure transport DTOs,
page schema validation and log range/hash mechanics. It cannot reuse the single-page
operation allowance, fixed request/coverage, result writer, exact attempt inventory
or log parser as a multi-page acceptance contract without deliberate adaptation.

## Documentation-session verification

This session executed 70 selected historical-root, design, result-gate, log-append,
legacy-preservation and endpoint regressions successfully. Local document links and
referenced regression symbols validated; `git diff --check` passed. A read-only
start/end snapshot verified all 1,876 currently retained runtime files unchanged.
This broader current snapshot is not a replacement for the previously verified
1,868-file historical baseline or its 1,847-path protection contract. Production
validators and repository tests were not changed. The full suite and static checks
listed above are prior audit results, not rerun claims from this documentation task.
