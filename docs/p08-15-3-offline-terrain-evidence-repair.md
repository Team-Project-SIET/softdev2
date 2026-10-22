# Durable offline terrain proof evidence

Architecture authority: `CONTEXT.md`. This repair is controlled implementation;
it does not authorize execution, allocate a real attempt, publish a seal, or
change terrain/road semantics. Historical artifacts remain byte-identical.

## Diagnosis

The first successful native single-page attempt remains `REAL_PASS`. Its complete
offline audit remains `AUDIT_BLOCKED`. Native execution and durable reconstruction
are separate claims.

The immutable seal froze canonical files inside a temporary candidate root. Runtime
cleanup removed only the explicitly owned runtime workspace; later candidate removal
made 13 canonical source paths unavailable. The original source inventory has 964
entries: 951 were present and matching at audit, 13 missing. Source edits made during
this repair also invalidate current-source comparison with that historical freeze;
they never change its recorded hashes.

The native evidence producer returned an observed log snapshot before connection
shutdown. Its digest covers 7,334 bytes. Final retained stderr contains 7,529 bytes.
The old offline verifier recomputed the snapshot gate from the full final log.
Both byte scopes are valid, but unequal. Neither defect is native execution failure.

## Ownership of the 13 missing inputs

All paths below are relative to the historical temporary candidate root.

| File | Ownership and lifetime |
| --- | --- |
| `CANDIDATE.json` | Non-secret immutable review record; exact bytes needed for candidate/seal provenance |
| `bridge/info.nut` | Non-secret immutable package input; duplicate of generated runtime copy |
| `bridge/main.nut` | Non-secret immutable composed handler; exact package bytes required |
| `config-template.cfg` | Deterministic non-secret recipe template; retained independently of runtime edits |
| `historical-integrity.json` | Non-secret immutable history inventory; duplicated by retained seal member |
| `materialization-inputs/.runtime-owned` | Deterministic public workspace marker template; runtime copy disposable |
| `materialization-inputs/openttd.cfg` | Deterministic public config plus selected endpoints; runtime copy disposable |
| `materialization-inputs/private.cfg` | Audited public-only bind/public-key config despite its filename; runtime copy disposable |
| `materialization-inputs/secrets.cfg` | Credential-capable config, but this mode permits only the exact empty-password placeholder; runtime copy disposable |
| `path-ownership.json` | Non-secret immutable candidate ownership graph; differs from seal ownership graph |
| `request.json` | Non-secret exact request; duplicated by retained seal member |
| `runtime-materializations.json` | Non-secret origin/copy digest ledger; duplicated by retained seal member |
| `source.json` | Non-secret deterministic world recipe; also represented in seal metadata |

The private `.admin-secret` key was never a canonical frozen input. It remains a
runtime credential and must be deleted. A filename containing “private” or “secrets”
is not sufficient to classify contents: retention permits the exact public-key
configuration and empty password placeholder only. Nonempty password settings,
private-key contents, unknown private settings, and secret/token config templates
reject before those bytes can be copied into the durable package.

## Future seal-owned canonical retention

`terrain_retention.py` adds a terrain-specific `canonical-inputs.json` ledger and
flat `canonical/<sha256>` content directory. Exact copies are deduplicated by hash.
The ledger records original reviewed provenance, a logical identity, the relative
artifact identity, and SHA256. Candidate-relative logical identities and digest
artifact names do not depend on the continued existence of `/tmp` paths.

The immutable PRELAUNCH subject binds the ledger digest. The existing source-freeze,
path-ownership, artifact manifest, exclusive publication and final pre-Popen checks
remain in force. Live launch validation still verifies original source paths,
candidate records, package bytes, runtime copies and the private credential. Durable
copies are not a way to admit changed live inputs.

Retention uses only the reviewed source inventory and an explicit candidate-file
allowlist, never recursive workspace copying. External inputs must match the current
runtime-critical source inventory or reviewed executable/graphics inputs. The
offline verifier checks each required copy, exact inventory coverage, candidate file
commitments, candidate/seal fields, source recipe, bridge package, request, configuration
digest and runtime-copy provenance. Missing, replaced, unexpected or aliasing content
rejects. Existing manifests are reused; no general artifact framework is introduced.

The next seal must be reviewed with its actual digest. This task does not create it.
For a future accepted attempt, the verifier follows launch-claim to the retained seal,
checks consumed authorization and native invocation bindings, validates canonical
coverage, validates response/receipt and native evidence, reconciles accounting, and
requires cleanup and post-run integrity evidence. The seal must remain retained;
candidate and runtime workspaces may disappear after their authorized lifetimes.

## Explicit execution-log scope

`execution-log.json`, policy `terrain-execution-log-v1`, contains:

- Snapshot: `stderr.log` artifact identity, start offset zero, exclusive end offset,
  selected byte length, exact selected SHA256, and associated post-response lifecycle
  marker. The producer records the length of the bytes it actually observed.
- Final log: `stderr.log` artifact identity, total length and complete-file SHA256.
- Exact request identity and policy version.

Offline verification hashes the recorded range from the final retained log. It
checks lengths, offsets, prefix inclusion, full-file digest, snapshot digest and the
native sequence. It also parses the complete final log so extra matching request
markers cannot be hidden outside the selected range. It does not search for a marker
to determine the endpoint. Append-only shutdown logging is accepted when both scopes
are recorded correctly; replacement, truncation and missing scope fields reject.

Only one final log is stored. Ranges reference it rather than duplicating cumulative
logs. Existing capture limits remain 262,144 bytes per stream. Response, getter,
frame and request limits are unchanged.

`cleanup-attestation.json` records workspace disposal, credential removal and
post-run source validation after those operations finish. The existing raw cleanup
and endpoint evidence remain separate, retained records.

## Historical compatibility and trust limits

`verify_retained_attempt()` fails closed with an explicit legacy limitation when
scope metadata is missing; a legacy REAL attempt also cannot pass without durable
canonical provenance. `inspect_legacy_attempt()` is diagnostic only and always
reports `AUDIT_BLOCKED`. It enumerates missing/changed source inputs, verifies the
recorded prefix digest against retained line-aligned byte prefixes, and validates
the matching native page. It does not search lifecycle markers for an endpoint,
special-case an attempt identity, synthesize new evidence, or promote reconstructed
diagnostic ranges into an explicit producer contract.

The historical prefix and final-file hashes can therefore be independently verified,
while absent source bytes and absent explicit scope metadata remain limitations.
Its original `REAL_PASS`, result gates and all artifacts remain unchanged.

Private key reproducibility is intentionally excluded. Public-key identity,
authenticated encrypted-session evidence, secure public configuration and cleanup
attestation define the credential boundary. Retaining a private key is neither
required nor permitted. These remain local operator/process attestations, not an
independent signed proof of human consent, kernel execution identity, or secret
erasure. An unkeyed hash ledger needs a trusted externally reviewed seal digest;
it is integrity evidence, not independent source authorship authentication.

The repair does not prove two-sweep repeatability, full-map coverage, saved-world
correspondence, production-world provenance, candidate validity or construction.

## Controlled acceptance repairs and cleanup ownership

The independent audit reproduced three acceptance defects. Actual candidate
preparation included `app/simulation/openttd/terrain_bridge.nut`, while retention's
reviewed external inventory omitted it. Controlled authorization records were
optional and their trust, owner, allowance and retry fields were unchecked. Finally,
ownership metadata could be substituted by recomputing mutable inventories and
manifests without changing PRELAUNCH.

Source discovery now includes the exact repository bridge source and its digest.
Retention requires canonical absolute source identities, rejects symlink/traversal
aliases, and admits no wildcard external-source policy. Ownership metadata has a
PRELAUNCH digest commitment and must satisfy the authoritative ownership schema,
exact path inventory, input/output classifications and materialization relationships.

Both modes require consumed authorization and a digest-linked invocation record.
The records bind seal, attempt, destination, operation, allowance, retry policy and
owner identity. CONTROLLED requires `CONTROLLED_OPERATOR_ATTESTED` and an explicitly
controlled invocation marker. REAL requires `LOCAL_OPERATOR_ATTESTED`, the native
marker and authenticated encrypted-session evidence. Neither controlled fixtures
nor recomputed mutable manifests establish genuine operator consent. Hash ledgers
still require trusted custody of the reviewed seal and runtime attestations.

Historical paths originate relative to the capture's provenance base, independently
of the directory containing the proof package. Future terrain candidates record
that explicit base; PRELAUNCH binds the same base and the historical inventory.
Preparation, post-run integrity and retained verification validate those commitments.
The resolver rejects missing, relative, ambiguous, wrong or aliased roots. Historical
protected bytes remain declared external immutable authorities; they are not
implicitly disposable canonical originals. Existing historical seals are not edited
or retroactively upgraded. Their missing original inputs keep complete historical
offline acceptance AUDIT_BLOCKED.

The post-run digest check uses `harness.sha256(Path)`, which hashes the whole file
and returns a hexadecimal SHA256 string. Missing frozen files propagate their
original `FileNotFoundError`; readable bytes with a digest mismatch raise
`ValueError`. Lifecycle callers fail acceptance on either exception. No exception
is suppressed and no digest scope changes.

The temporary-originals regression previously selected every frozen path beneath
its `/tmp` parent. It selected 13 candidate files plus a fixture executable,
repository bridge source and pinned graphics archive. The archive was also captured
protected history. Directory placement was not permission to remove these files.

The corrected destructive test explicitly permits only the 13 temporary candidate
originals after successful durable controlled acceptance. They remain immutable
launch inputs before that phase. Persistent fixture source and pinned assets,
protected history, and retained canonical objects are separate sets. The guard
compares resolved identities and rejects overlaps, undeclared paths, traversal and
symlink aliases before any mutation. It validates the production package before
unlinking the complete approved set. Negative tests challenge protected/source/asset
and retained-object deletion, conflicting classification, aliases and mixed deletion
sets. Destructive cases operate only in isolated fixtures. Production validators
and protected-path coverage are unchanged.

Positive regressions exercise actual source discovery, candidate and temporary seal
serialization, canonical retention, controlled claims, fake execution, digest scopes,
historical integrity, credential disposal and offline verification. Fresh interpreters
verify from a separate working directory after permitted cleanup. No OpenTTD launch,
live connection, real authorization, persistent seal, commit or push is performed.

## Completed controlled verification

The final style-only repair split two verifier-script string literals without
changing their concatenated bytes and sorted one test import block. Production
validators were unchanged by that repair. Ruff and repository-wide format checks
passed before verification resumed.

Final controlled results: 95 focused lifecycle/security tests passed. The serial
ordinary suite passed with 3,291 tests passed, 35 skipped and 3 real OpenTTD tests
explicitly deselected. Both tagged 15.3 VM and serializer probes were enabled.
The complete production inventory package, cleanup-independent verification and
fresh-interpreter verification passed. Scoped typecheck, import-boundary audit,
source integrity and whitespace checks passed. All 1,847 protected historical
paths and credential identities validated, and all 1,868 snapshotted historical
files remained byte-identical.

This establishes controlled readiness for an independent audit. It does not
authorize native execution or upgrade the historical incomplete offline package.
The historical native REAL_PASS remains supported; complete historical acceptance
remains AUDIT_BLOCKED with 13 missing original canonical inputs. No historical
bytes were reconstructed or modified. No real native launch, live Admin connection,
real request, real attempt consumption, persistent seal, commit or push occurred.

## Exact attempt artifact inventory and authentication isolation

An independent production-package attack added `unexpected-audit-artifact.txt`
and recomputed the mutable attempt manifest. The retained verifier accepted it.
A manifest establishes content consistency, not permission to retain an artifact.
The retained-attempt boundary now requires both manifest equality and the exact
successful writer contract. Required outputs are accounting, authentication,
cleanup and raw cleanup, execution-log scope, launch claim, response and receipt,
result, source identities, stderr and the manifest. Canonical packages additionally
require consumed authorization, cleanup attestation and the invocation marker for
their exact mode. Only the writer's conditional stdout capture is optional.
Failure-only response diagnostics cannot belong to an accepted successful package;
failed packages still remain retained and cannot establish offline acceptance.
No deletion of rejected evidence occurs.

The attempt root must have a canonical absolute identity. Its entries must be
regular files without symlinks; directories and nested artifacts are rejected.
Digest-addressed canonical objects remain in the separately verified seal, whose
retention index enforces its own exact inventory. This contract comes from trusted
production verifier/writer source and verified mode/lifecycle commitments, not
mutable manifest entries. No PRELAUNCH schema or immutable seal is rewritten.
Historical legacy diagnostic inspection remains separate from complete acceptance.

The authentication regression originally changed only result and claim mode to
REAL while retaining the CONTROLLED invocation marker. Inventory correctly rejected
that inconsistent fixture before authentication. Production ordering was not
changed. The repaired isolated fixture creates consistent synthetic REAL-shaped
record bytes, including the native marker and linked authorization digest. These
bytes are test data, never a typed local operator grant or evidence of native
execution. Tests validate the prerequisite inventory and lineage, then mutate only
the authentication field under test. The full production verifier rejects each
mutation at `verify_retained_authentication`, with its exception cause preserved.
Separate tests reject missing/wrong-mode markers, missing authentication, invalid
lineage and extra artifacts. A typed CONTROLLED grant still cannot authorize a
native process. No synthetic package is certified as a genuine REAL proof.

The original retained unexpected-artifact attack now rejects at the inventory
boundary. Focused lifecycle/security, terrain, tagged 15.3 VM/serializer and P08/P05
regressions passed: 473 tests. The production package retains 188 canonical
identities and verifies before cleanup, after permitted original removal and in a
fresh interpreter. Historical verification found 1,847 protected paths valid and
all 1,868 baseline artifacts unchanged. Historical complete acceptance remains
AUDIT_BLOCKED with 13 missing original canonical inputs; native REAL_PASS remains
supported. Local-attested REAL records still require trusted custody; synthetic
metadata does not prove real human consent, encryption or native execution.

Final resumed verification: serial ordinary suite 3,309 passed, 35 skipped and
3 real native tests deselected. Ruff passed, 398 Python files passed format check,
scoped typecheck passed, the log-evidence import-boundary audit passed and
`git diff --check` passed. Authentication isolation contributed 16 targeted passes;
the wider focused run passed 473 tests. No production validation ordering was
changed by the fixture repair. These controlled results require independent audit
and do not authorize a real attempt or resolve historical missing provenance.

## Cleanup evidence consistency repair

Independent audit changed only raw cleanup `reaped` to false, preserved the embedded
cleanup's true value, and recomputed the manifest. Full production verification
accepted twice. The mutation was reproduced before repair, and a full-verifier
regression failed with `DID NOT RAISE ValueError`.

The writer captures backend cleanup once: raw JSON first, then the identical record
embedded in cleanup JSON with independently observed endpoint closure. These are
the same post-process phase, not a permitted false-to-true transition. Later owned
workspace disposal and source/historical integrity checks produce the separate
cleanup attestation. `reaped` means the owned process has exited and was collected
by its lifecycle; native evidence also records its PID, return code and lifecycle
events. No timestamp-based transition is used by this contract.

Retained acceptance now parses both records, requires exact shared record equality,
rejects missing/unknown semantic fields, and requires reaped=true with empty remaining
process and error lists. CONTROLLED records use the fake lifecycle's three-field
schema. REAL records require the native writer's PID, graceful-attempt flag, quit
command, integer return code, lifecycle ending in reaped and frame-accounting snapshot.
Native accounting must match the independent retained accounting artifact. Existing
endpoint observations, exact artifact inventory, immutable source/ownership bindings,
log scopes, credential disposal and post-run checks remain mandatory. No writer,
authorization, road semantics or immutable historical seal was changed.

The original attack now rejects with `Retained cleanup evidence inconsistent or
unsuccessful`. Full-verifier regressions reject raw/summary contradictions, both
unsuccessful, missing/malformed records, missing fields, unknown status, wrong types,
remaining processes, cleanup errors and substituted record shape. Recomputing the
manifest does not bypass these checks. Coordinated successful summaries still reject
when endpoint evidence records process_reaped=false. A synthetic REAL-shaped package
with no observed exit code rejects; it is never certified as real native execution.

A cross-attempt record with different lifecycle facts rejects through equality or
schema validation. Byte-identical cleanup records have no intrinsic attempt identity
and cannot be distinguished by this contract. Process exit and endpoint records are
local attestations, not cryptographic measurements supplied by an independent kernel
witness. Replacing every local attestation consistently can remain undetectable under
the documented Model A custody boundary. Filesystem checks independently confirm the
declared disposable workspace/key paths are absent; they do not prove universal
credential erasure or historical process activity. This repair adds consistency,
not stronger authentication or reproducibility claims.

Focused controlled verification passed 489 tests, including production inventory,
packaging, cleanup-independent and fresh-process verification, all prior security
regressions, tagged 15.3 VM/serializer probes and P08/P05 coverage. Historical auditing
validated 1,847 protected paths and 1,868 byte-identical baseline artifacts. Historical
native REAL_PASS remains supported; complete acceptance remains AUDIT_BLOCKED with
13 missing original canonical inputs. No historical bytes were reconstructed.

Final cleanup-repair quality gates: serial ordinary suite 3,325 passed, 35 skipped,
3 real native tests deselected. Ruff passed; all 398 Python files passed format check;
scoped typecheck, log-evidence import-boundary audit and `git diff --check` passed.
No real native launch, Admin connection, application request, real attempt consumption,
persistent seal, historical mutation, commit or push occurred.

## Result-gate consistency and rebuilt independent reproduction

The independent audit changed `result.gates.cleanup` from true to false, retained
successful raw/normalized cleanup, endpoints and disposal attestations, and recomputed
the attempt manifest. Full verification accepted twice. The deterministic production
regression accepted its valid baseline and then failed with `DID NOT RAISE ValueError`
for the mutated gate before the repair.

Successful execution's mandatory result-gate relationships are:

| Gate | Meaning and supporting evidence | Acceptance contract |
| --- | --- | --- |
| schema_valid | Parsed response and receipt | Must match verify_page boolean |
| coverage_valid | Exact requested five-tile coverage/cursor | Must match verify_page boolean |
| native_read_evidence | Response-correlated GameScript markers | Must match verify_page boolean |
| post_yield_liveness | Completed native marker sequence | Must match verify_page boolean |
| response_sha256 | Exact retained response bytes and receipt | Must match verified digest string |
| evidence_sha256 | Explicit verified execution-log snapshot | Must match verified digest string |
| cleanup | Raw/normalized cleanup, lifecycle and endpoint closure | Must be true after those validators and required disposal checks pass |
| post_run_integrity | Retained source/ownership/historical commitments and canonical cleanup attestation | Must be true with existing evidence checks retained |

The writer obtains the first six entries from verify_page, then records cleanup and
post-run gates only after their respective lifecycle checks. Failed attempts may
contain partial gates and diagnostics; their FAILED status/error excludes successful
offline acceptance. No new diagnostic or readiness fields are elevated to evidence
requirements.

The repair reconciles cleanup at the end of acceptance, after existing independent
evidence checks succeed. It reuses verify_cleanup_records and removes the duplicated
reaped/remaining-process/error predicates in the caller. Recorded page gates now
match both the verified value and JSON primitive type, preventing integer values
from substituting for booleans. Existing post_run_integrity checking remains intact.
No artifact schema, PRELAUNCH, writer, authorization, road semantics or historical
seal was changed. This establishes record consistency, not independent kernel or
operator authentication.

The previous standalone replay was blocked because its disposable /tmp package was
deleted. A path-validation rejection did not establish the intended repair. The
replacement at /tmp/result-gate-verification-current uses actual production source
discovery, preparation, temporary sealing, retention and the controlled fake-native
boundary; acceptance validators are unmodified. It retained 188 canonical identities,
accepted before cleanup and after permitted original removal, and accepted CONTROLLED
in a fresh interpreter from /tmp. Generated private credential bytes were absent
from retained objects, and the owned credential/runtime workspace were disposed.

Only result.json and its mutable manifest change in the attack; raw/normalized
cleanup, endpoints and disposal evidence remain byte-identical. Both replay calls
raise ValueError at verify_retained_attempt with the exact message:
`Retained result cleanup gate contradicts verified evidence`. They reach the
intended consistency boundary, not path, inventory or unrelated validation.
The fresh script, baseline package and repeated outcomes are retained in the
isolated disposable workspace for review.

Focused verification passed 486 tests with 12 optional tagged-VM/serializer tests
skipped because their former /tmp executables are unavailable. These skipped tests
are not counted as PASS. Result-gate, cleanup, inventory, authorization, source,
ownership, root, log, Model A, full production lifecycle and fresh-process tests
passed. The prior adversarial matrix's 24 NOT_TESTED cases remain NOT_TESTED; this
repair does not complete the independent audit. Historical native REAL_PASS stays
supported; complete historical acceptance stays AUDIT_BLOCKED with 13 missing inputs.

The restoration run passed Ruff, format verification (398 Python files), scoped
typecheck, the log-evidence import audit and diff whitespace checks. Its final
historical artifact comparison matched all 1,868 current-run baseline files.
However, a subsequent audit assertion incorrectly required the current repaired
production sources to match the historical source freeze. The legacy diagnostic
reports six changed production source files, while still supporting REAL_PASS and
reporting 13 missing original inputs and AUDIT_BLOCKED. This is source evolution,
not historical artifact mutation. Following the mandatory stop rule, the ordinary
suite was interrupted around 72%; no completed ordinary-suite count is available.
The restoration therefore remains blocked on completion of the ordinary suite,
not on the independently replayed result-gate attack.

### Historical assertion correction and completed verification

The incorrect assertion belonged to a standalone verification command, not a
repository test or production validator. Requiring changed_source_inputs to be
empty confused present development sources with the preserved historical source
commitments. The corrected disposable audit validates historical artifact bytes,
the exact historical PRELAUNCH digest and all 1,847 protected paths. It separately
reports current source differences without treating them as historical mutations.
The six current files are historical_protection.py (explicit root binding),
ownership.py (capture ownership, disposal and post-run verification),
terrain_attempt.py (offline acceptance contracts), terrain_native.py (capture and
native lifecycle safety), terrain_preparation.py (source discovery and provenance)
and terrain_seal.py (retention and immutable commitments). No source comparison
requirement for newly prepared attempts was changed.

The complete serial ordinary suite was restarted and finished: 3,321 passed,
48 skipped, three real-native tests deselected. Skips were 35 opt-in PostgreSQL
cases and 13 unavailable tagged VM/probe cases, not successful native checks.
The subsequent focused lifecycle/security suite passed 486 tests with 12 tagged
probe skips. A new production package in /tmp/result-gate-final-verification
retained 188 canonical identities and passed CONTROLLED execution, verification
before and after permitted cleanup, and fresh-interpreter verification from /tmp.
Generated credential bytes were absent from retained evidence and disposable
credentials/runtime materializations were removed.

Ruff, format verification (398 files), scoped typecheck, the log-evidence import
audit and git diff --check passed. Final historical checks preserved all 1,868
current-run baseline artifacts and validated the retained historical commitments.
The previous temporary snapshot was unavailable, so this run's byte comparison
uses its own before/after snapshot alongside the retained protected authority.
SUPPORTED REAL_PASS and AUDIT_BLOCKED remain distinct, with 13 missing canonical
inputs unreconstructed. No production source, repository test or historical
artifact was modified in this completion run.

### Endpoint observation repair — verification blocked

The independent endpoint finding was replayed through production preparation,
retention, controlled execution and offline verification. A valid package retained
188 identities and passed before/after cleanup and in a fresh process. Inserting
a relevant TCP LISTEN observation (numeric state 10) into cleanup.json, while
retaining closure summaries and recomputing the manifest, was accepted twice.
The full-verifier regression for state 10 failed before repair with DID NOT RAISE.

The scoped implementation factors final socket interpretation into endpoints.py,
reuses it online and for retained observations, and adds sealed endpoint identity,
exact observation schema and closure-summary validation at retained acceptance.
It preserves the producer's TIME_WAIT representation and unrelated-port filtering.
The offline retained set must contain only matched residual TCP TIME_WAIT rows.
This remains local attestation consistency, not cryptographic kernel evidence.

The first post-repair focused run stopped after 10 passes at the wildcard fixture:
the test expected a retained TCP6 TIME_WAIT row on :: to reject, while the existing
producer permits matching TCP TIME_WAIT rows. That test expectation requires
reconciliation with the existing contract. No test was suppressed or relaxed;
the mandatory stop rule prevented further repair or verification. The post-repair
independent replay, remaining regressions, ordinary suite and quality gates are
not certified by this run. No persistent seal or historical evidence was changed.

### TCP6 TIME_WAIT expectation corrected; endpoint verification completed

The wildcard failure was a test contract mismatch. Inspection of the original
producer at baseline HEAD confirms that both local and remote tuples are matched
against the sealed game/Admin ports. Unspecified IPv4/IPv6 and IPv4-mapped IPv6
addresses are conservatively treated as potentially covering IPv4 loopback.
Relevant UDP or non-TIME_WAIT sockets reject; relevant TCP TIME_WAIT is retained.
The observation is one final post-reap sample, not a multi-phase socket history.
The producer stores matched rows only, with table, local/remote addresses and ports,
state and inode, normalizing numeric kernel state 6 to the string TIME_WAIT.
An empty matched list is valid. Unrelated ports are filtered by the producer and
must not be substituted for matched retained observations.

The test now accepts the contract-permitted TCP6 TIME_WAIT wildcard fixture and
adds IPv4 wildcard, mapped IPv6 TIME_WAIT and TCP6 LISTEN/ESTABLISHED/CLOSE_WAIT
cases. Live states remain rejected regardless of wildcard addressing. A prior
endpoint-summary regression now expects the new endpoint-observation boundary's
diagnostic while retaining its rejection assertion. Production validators were
not changed in this completion run.

Thirty focused endpoint/summary checks passed. The broader controlled security,
Model A, source/ownership/root, cleanup, result-gate, inventory and log regression
set passed 515 tests with 12 optional tagged-probe skips. A fresh actual-production
package in /tmp/endpoint-timewait-verification retained 188 canonical identities
and passed CONTROLLED execution, before/after permitted cleanup and fresh-process
verification. Credentials were disposed and generated secret bytes were absent
from retained evidence. Replaying only the relevant LISTEN row plus recomputed
manifest rejected twice at verify_retained_endpoints with ValueError:
Retained endpoint observation inconsistent or malformed.

The complete serial ordinary suite passed 3,350 tests with 48 skips and three
real-native tests deselected. Skips are 35 opt-in PostgreSQL cases and 13 unavailable
tagged VM/probe cases; none is certified as PASS. Ruff, format verification
(398 files), scoped typecheck, scoped log-evidence import audit and diff whitespace
checks passed. The historical standalone audit no longer asserts a fixed count of
current development source differences. It preserves strict historical artifact,
seal and protected-path verification and reports current sources separately:
endpoints.py, historical_protection.py, ownership.py, terrain_attempt.py,
terrain_native.py, terrain_preparation.py and terrain_seal.py.

Historical REAL_PASS remains supported; complete offline acceptance remains
AUDIT_BLOCKED with 13 missing original inputs, unreconstructed. Endpoint and
process observations are locally attested; semantic consistency and byte identity
do not provide independent cryptographic proof of kernel state or process cleanup.

## Verified baseline and next milestone reference

The accepted contract is recorded in
[the offline evidence baseline](specs/openttd-offline-evidence-baseline.md), including
schema/policy identifiers, authoritative inventories, result-gate relationships,
validation order, coverage references and historical limitations. The completed
independent audit reports 24 PASS, with the final historical-root case adjudicated
through immutable binding plus independent resolver checks. Exact original row
archival availability is documented separately from acceptance correctness.

[The bounded multi-page plan](specs/p08-multi-page-terrain-acquisition.md) distinguishes
existing controlled collection from future native proof-package integration. It does
not authorize execution or claim that a 256-tile region covers a 64x64 map.

## Independent audit archival adjudication

The [reconstructed summary](specs/openttd-reconstructed-independent-audit-summary.md)
preserves the conversation-reported 24 PASS cases and final root adjudication. The
original JSON has not been recovered. No exact-original-matrix requirement was found
in the established acceptance contract; freeze review is ready with this archival
limitation recorded. This does not upgrade historical offline AUDIT_BLOCKED or
restore missing canonical inputs, and no new tests or native proofs are implied.
