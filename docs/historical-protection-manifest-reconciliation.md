# Historical protection reconciliation for enrichment V3

CONTEXT.md remains the architecture authority and is unchanged. This repair is
controlled only. No real OpenTTD launch, Admin connection, or application request
is authorized. The old preparation and gate-failure evidence remain immutable.

## Root cause and exact set

The original 489-entry authority is `historical_snapshot()` in
`app/simulation/openttd/proof/preflight.py`, called by `prepare_proof()` in
`harness.py`. It snapshots files recursively under runtime child directories,
excluding the current preparation. It skips runtime root-level files and does
not include the repository's CONTEXT.md.

The original 491 expectation came from the preparation audit, not a production
constant. The retained session command at 2026-10-06T10:21:33.321Z enumerated
`Path('artifacts/runtime').rglob('*')` files plus `Path('CONTEXT.md')` into
`/tmp/enrichment-history.json`. The subsequent verification report recorded
`protected_historical_files=len(baseline)`. Its retained result is
`artifacts/runtime/openttd-15.3-industry-capability-enrichment-real-preparation-verification/verification.json`.
The temporary baseline is no longer present; the recorded enumeration, frozen
path sets, and separately frozen hashes establish the exact difference.

The two paths in the audit scope but outside the directory snapshot are:

- `CONTEXT.md`
- `artifacts/runtime/openttd-15.3-real-ack-preparation-verification.json`

Both existed before the freeze and both are already exact SHA-256 inputs in the
old `source-freeze.json`. Thus the old preparation protected 491 paths across two
manifests; equating the directory manifest's count to the combined audit count
was invalid. There is no evidence of a rename, move, replacement, or duplicate.
All original historical identities were verified against current files. No T5
failure file belongs to the original 491 audit scope.

## Time boundary

- T1: CONTEXT.md mtime 2026-10-04T12:01:10.609303Z; root report mtime
  2026-10-05T08:26:15.027446Z. The recorded baseline enumeration is
  2026-10-06T10:21:33.321Z. Mtimes corroborate the recorded/frozen evidence and
  are not the sole authority for existence.
- T2: historical snapshot 2026-10-06T10:41:26.204012Z; source freeze
  2026-10-06T10:41:26.266906Z.
- T3: authorization message 2026-10-06T14:14:16.906Z.
- T4: previous turn evaluated the count-only authorization assertion and stopped
  before process creation, although the production guarded preflight itself
  returned READY_TO_LAUNCH.
- T5: retained failure report mtime 2026-10-06T14:15:17.278475Z.

The later preparation verification directory and T5 failure directory are not
retroactive requirements of T2. They are pre-existing historical artifacts at the
new capture boundary and therefore belong to the next freeze.

## Unified protected-set contract

`historical_protection.py` owns capture and validation for the combined enrichment
proof. Capture records sorted historical runtime directory roots, explicit
runtime root files, and CONTEXT.md. Within captured roots, exact path-set equality
is required. Every captured public file requires its exact SHA-256. Missing paths,
renames, same-count substitutions, changed hashes, duplicate entries, mismatched
path lists, or inconsistent summary counts fail.

The boundary excludes the current preparation (including its live isolated
workspace), the named future attempt, and private `.admin-secret` files. Archived
workspace inputs already retained in old freezes remain historical files; their
public bytes are preserved. Private material is never included or hashed into
public evidence. Archived credentials retain the legacy public-key/mode identity
validation in a separate identity list; these are not public SHA-256 entries.
Old credentials remain untouched. A separate before/after audit
also verifies every pre-existing file byte-identically without publishing private
credential hashes.

New sibling directories or root files created after capture are not retroactive
inputs. A new file inside an already captured historical directory changes that
root's protected path set and fails. A next freeze includes historical failure
artifacts existing at its new boundary. No numeric count defines membership.

The manifest records ordered paths, ordered digest entries, roots/exclusions,
unique count, and a canonical SHA-256 binding the whole authority. PRELAUNCH binds
that digest and count; source-freeze binds both manifest and PRELAUNCH. The
proof-config digest now includes the exact-path policy version. The production
gate and post-run verification call the same validator. Other proof modes retain
their existing historical contracts.

## New authorization boundary

Only the public production CLI prepares
`artifacts/runtime/openttd-15.3-industry-capability-enrichment-real-prelaunch-v3/`
and performs guarded `preflight --mode industry-enrichment --directory ...`.
Revision 3 is distinct; old evidence is never regenerated or overwritten.
The same future attempt directory remains absent. No `run` invocation is made.

FRESH AUTHORIZATION REQUIRED — PRELAUNCH FREEZE CHANGED.

## Controlled V2 loader failure

The first repaired V2 freeze was captured successfully, but its public guarded
preflight rejected revision 2 because `load_prepared()` still accepted only
enrichment revision 1. This failure occurred before protected-set validation or
process creation. V2 and its `-v2-gate-failure/` evidence are preserved. A regression
reproduced this rejection through the actual public loader. The loader and generator
now share `ENRICHMENT_REVISION`, bound into the proof configuration. V3 is the next
new capture, including V2 public preparation/failure evidence as history.
No real execution or native retry took place. Fresh authorization must name V3.
