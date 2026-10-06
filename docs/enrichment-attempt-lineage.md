# Enrichment attempt lineage and controlled V4 preparation

CONTEXT.md remains the local architecture authority. This change performs no
OpenTTD gameplay launch, live Admin connection, or real application request.

## Diagnosis

Before this repair, `validate_native_inputs()` in `proof/preflight.py` emitted
`Previous enrichment prelaunch failure; no retry` whenever the current preparation's
sibling `<preparation>-gate-failure/` directory existed. The enrichment runner
independently rejected the same directory or an existing runtime attempt directory.
Neither read the failure's state, activity counts, manifest, freeze revision, or
authorization identity. An empty directory had the same blocking effect as a
recorded runtime failure. The condition distinguished preparation *paths*, but not
semantic freeze revisions or authorization attempts. It did not establish 0/0/0.

The public V3 preflight reproduced the error before process creation. A controlled
new-preparation fixture showed a separate deficiency: a different preparation path
could pass without acknowledging earlier failures. Thus the old code permanently
blocked same-path reuse but did not itself forbid every differently named future
freeze. The repair prohibits same-freeze reuse while requiring explicit validated
lineage for a newer freeze. V3 is historical and rejected by the current revision
loader; V3 is not patched or usable for another execution.

## Identity and continuation

`enrichment_lineage.py` defines immutable normalized AttemptIdentity values:
proof kind, frozen revision, deterministic attempt ID, parent identities where
available, terminal classification/status, exact activity counts, evidence
directory, evidence manifest/content digests and revision-authority digest.
Legacy failures get canonical identities in the new frozen lineage without editing
old evidence. New terminal attempts retain `proof-attempt.json`; its canonical
public payload digest binds evidence, and the final artifact manifest binds that
record. No wall-clock timestamp determines identity.

PRELAUNCH requires terminal PRELAUNCH_FAILED/PREFLIGHT_FAILED, exact integer
launches/connections/requests=0/0/0, no process-creation indicator, and no LAUNCHED
state/process-launch artifact. Booleans, missing counts, contradictory aliases,
negative counts and malformed evidence fail closed. Any positive activity or
process-creation evidence is RUNTIME regardless of directory name. An absent
actual process PID is not evidence sufficient to undo a runtime claim.

Prelaunch failure invalidates its authorization and remains immutable. Continuation
requires a *newer* freeze, frozen predecessor lineage, exact evidence validation,
and fresh external authorization. The same freeze cannot acknowledge itself.
Runtime failure cannot use the prelaunch exception: there is no retry, resume,
reconnect, renaming, or conversion under the previous authorization. Any separately
prepared future native attempt requires a new frozen runtime-failure continuation
policy and fresh authorization; V4 does not authorize such a continuation.

Relevant failures are discovered under the shared proof root by the enrichment
artifact naming prefix or explicit modern proof-kind identity. The current
preparation's own gate failure is also checked. An unknown/unacknowledged relevant
failure, missing predecessor, changed manifest/content, or noncanonical/duplicate
predecessor identity fails preflight. Newly added unrelated proof evidence is not
mistaken for an enrichment failure. No force/ignore/retry CLI switch exists.

## Frozen V4 lineage

V4 acknowledges all four earlier enrichment failures: the original count-scope
failure, V2 loader failure, V3 destination mismatch, and V3 reauthorization gate
failure. `attempt-lineage.json` contains exact deterministic identities, evidence
manifest/content digests and PRELAUNCH 0/0/0 classifications, sorted by attempt ID.
PRELAUNCH binds the lineage digest, selected native identity and predecessor IDs;
source-freeze binds the lineage file and metadata. The gate compares the exact
acknowledged set to discovered relevant failures and derives each identity again
from retained evidence and its original PRELAUNCH revision authority.

The production gate validates the exact historical protected set, lineage,
configuration, destination, secure Admin/credential identities and endpoint
reservation before launch. Fresh explicit authorization remains enforced by the
public CLI's separate `--authorize-one-launch` requirement. Authorization prose
cannot bypass a failing frozen machine gate.

## Native attempt numbering and destination

Existing production authority uses attempt1 for the combined native proof and
atomically creates that directory only after preflight. Prior zero-activity gate
failures use separate preparation-failure directories. Auditing the actual runtime
root found no combined native attempt1 directory and no enrichment native runtime
evidence. They have therefore not consumed native attempt1.

V4 explicitly freezes:
`artifacts/runtime/openttd-15.3-industry-capability-enrichment-real-attempt1/`.
The config, metadata, gate, and runner agree. The public CLI has no destination
argument or environment override; parser and exact-destination regressions reject
substitution. Any existing claim at that destination fails, even without a process.
A rename does not make a failed runtime record eligible for prelaunch lineage.

## Controlled preparation

Use public production CLI `prepare --mode industry-enrichment --directory
artifacts/runtime/openttd-15.3-industry-capability-enrichment-real-prelaunch-v4/`,
then guarded `preflight` for the same mode/directory. No `run` invocation is made.
A fresh V4 credential is generated, mode 0600, private bytes excluded from public
evidence. All historical files, archived credentials, prior freezes and failures,
and CONTEXT.md remain byte-identical.

Inventory/cargo protocols, semantic digests, pagination, budgets, stable-world
assumption, one connection, zero retries/reconnects and mutation restrictions are
unchanged. V4 changes proof-attempt/gate authority only.

FRESH EXPLICIT AUTHORIZATION REQUIRED FOR V4.
