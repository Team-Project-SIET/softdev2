# P08 controlled two-sweep equality design

Status: proposed controlled implementation, 2026-10-10. Architecture authority:
[`CONTEXT.md`](../../CONTEXT.md). This design supplements the
[regional acquisition plan](p08-multi-page-terrain-acquisition.md); it does not
change `openttd-offline-evidence-contract-baseline-1` or authorize execution.

## Scope and reuse

Add a pure equality-admission module over two independent `TerrainPagination`
instances. Reuse `Region`, `PaginationBudget`, `TileFactsRequest`,
`TileFactsExchange`, `TerrainDataset` and their validation. Python owns assembly.
No network client, process, credential, proof writer or planning adapter is added.

`TerrainCollector`/`TerrainObservation` already implement controlled WPO-qualified
two-sweep collection and full-row equality. They remain unchanged: their qualified
month, industry and reciprocal-road checks are additional integration requirements,
not proof that this standalone slice has WPO provenance. Do not introduce another
collector or replace that model. A later integration must explicitly reconcile the
two paths rather than maintain competing pagination implementations.

The accepted object represents repeatable CONTROLLED observations of one bounded
region. It is not native evidence, an atomic snapshot, saved-world correspondence,
complete supplemental planning facts or construction authority. A 256-tile region
is partial coverage of a 64×64 map.

## Identity and interface

Proposed implementation: `app/simulation/openttd/terrain_sweeps.py`.

* Immutable `TerrainSweepContext`: acquisition ID, declared world fingerprint
  (existing `Digest` shape), map width/height and `Region`. Geometry must pass the
  existing tile-protocol map validation. The world fingerprint identifies a declared
  source context, not the changing terrain rows; do not hash terrain to manufacture
  a stable world identity. CONTROLLED callers supply synthetic source context,
  explicitly labeled as such. Native authentication of this context is deferred.
* `TerrainTwoSweep(context, *, per_sweep_budget, combined_budget)` owns its two
  pagination instances privately. Snapshot and validate constructor inputs; do not
  expose mutable paginator configuration. Sweep identities are `(acquisition_id,1)`
  and `(acquisition_id,2)`. Request prefixes are distinct `id-s1` and `id-s2`, with
  existing `-pNNN` suffixes. Validate the longest resulting request ID at construction.
* `requests` exposes an immutable tuple for the current sweep. `accept(sweep,
  observed_context, exchange)` checks the exact sweep identity and context, then
  delegates page admission. The supplied context is an attestation from the future
  adapter; the response itself only corroborates geometry, not a world fingerprint.
* `complete_sweep()` calls pagination `finish()`; it never accepts a caller-created
  `TerrainDataset`. After sweep one it exposes sweep two; after sweep two it performs
  equality and freezes the result. `finish()` returns the accepted result only.
* `abort(reason)` terminally rejects interruption. Read-only progress/diagnostics
  disclose received/missing page identities and failure reason, never partial success.

`VerifiedTerrainPair` is a frozen result containing context, two immutable datasets,
the shared ordered rows, individual accounting and aggregate accounting. Derived
metadata returns fresh values; no mutable dictionary is stored as authority. It
contains both exact byte exchanges and receipt digests, not only a rows hash.
The next slice has no persistent evidence schema or REAL_PASS output.

## State and failure contract

| State | Allowed transition |
| --- | --- |
| FIRST_COLLECTING | Admit the next page; `complete_sweep` requires exact complete coverage |
| FIRST_COMPLETE | Internal transition to SECOND_COLLECTING; no caller-admitted page in between |
| SECOND_COLLECTING | Admit the next second-sweep page; complete only with exact coverage |
| VALIDATING_EQUALITY | Internal comparison, then ACCEPTED or REJECTED |
| ACCEPTED | Read immutable result; repeated `finish` is read-only; further admission is an error |
| REJECTED | Read diagnostics; no further admission, completion, retry or reset |

Any admission/context/accounting/coverage/equality error before acceptance becomes
terminal REJECTED and raises `ValueError` with a specific reason and preserved cause
when wrapping existing validation. Premature completion is rejection, not a polling
operation; callers use progress to discover readiness. Misuse after ACCEPTED raises
without changing or invalidating the already frozen result. Retain bounded partial
exchanges for diagnostics, but never return them as accepted terrain. A new object
is not runtime retry permission.

## Coverage and equality

Each sweep independently enumerates the same rectangle: regional ordinal `i`
maps to `(y+i//w)*map_width+x+i%w`. Cursor advances by five except the partial
terminal page. Require exactly `ceil(N/5)` pages, exactly N unique row-major tiles,
correct cursor/terminal behavior and strict response order. No empty sentinel or
empty region is permitted by `Region`; the minimum is one tile. Reject duplicates,
overlaps, conflicts, missing pages, wrong map/region and out-of-region rows through
existing page validation. Logical page identity is ordinal/cursor/tile coverage;
request IDs must differ between sweeps and must not be compared for equality.

After both datasets complete, compare geometry and exact ordered tuples of all ten
protocol fields: tile ID, minimum height, slope, occupancy flags, industry ID,
owner, ordinary-road presence, outgoing, incoming and assessed direction masks.
No tolerance, unknown-value reinterpretation, projection or partial comparison.
Use existing dataset canonical JSON/`rows_sha256` for diagnostic digest identity;
acceptance compares the tuples themselves, not hashes alone. Do not duplicate its
canonicalization logic or use `TerrainObservation.semantic_digest` as if it were a
standalone row digest: that digest includes WPO source and trust context.

Request IDs, raw JSON formatting, receipt hashes, network sequences, byte counts,
operation counts and capture dates are transport/evidence metadata, not terrain
equality fields. Validate them individually through exchange validation and budgets.
Require ordered date brackets (`before<=after`, next before>=previous after) across
both sweeps; preserve them, without requiring equal dates. This does not introduce
the WPO qualified-month rule into a standalone slice. Changed fingerprint or
geometry rejects before admitting the affected page. Equality cannot exclude
transient mutations restored between reads, mutations during a sweep or subsequent
changes. It must never be described as atomic-world consistency.

## Budget scopes

| Measured application quantity | Each sweep ceiling | Combined ceiling |
| --- | ---: | ---: |
| Pages | 52 | 104 |
| Request bytes/page | 159 | 159 (unchanged) |
| Response bytes/page | 508 | 508 (unchanged) |
| Request bytes | 8,268 | 16,536 |
| Response bytes | 26,416 | 52,832 |
| Query operations | 416 | 832 |

Retain independent per-sweep `PaginationBudget`; add only a frozen aggregate
budget with exact positive integers bounded by the combined ceilings above.
Smaller selected caps are allowed, booleans are not integers for this contract.
Preflight the page count; check actual lengths/operations before every admission,
including aggregate consumption from sweep one. Never reset aggregate accounting
at the sweep transition. Completed totals must equal sums of retained exchanges;
metadata supplied by a caller is not accounting authority. Different valid payload
sizes or operation counts between sweeps do not imply terrain drift.
Operation totals sum validated recorded exchange counters, each in the existing
4..8 range. They are not independently measured transport or getter events in
this pure module.

These totals follow the regional design; they are not permission to double a native
security limit. Native static getter bound remains `44*N+6*P` per sweep, at most
23,152 combined; this module cannot dynamically measure getters. Future session
planning has a distinct <=838 post-auth frame envelope, excludes authentication,
and must separately budget the ordinary-road selector setter, framing/encryption,
startup, cleanup and all timeout scopes. No session limit is enforced or proven by
this pure module. Existing 262,144-byte capture limits per stream remain unchanged.
Combined request/response payload storage <=69,368 bytes excludes receipts, source
objects, indexes and logs; total package size and deadlines remain future proof
requirements. No cumulative log copies per page.

## Evidence replay and compatibility

For controlled independent verification, replay both retained exchange sequences
through a new coordinator using the original declared context and budgets. Reparse
requests/responses, verify receipt byte digests, coverage and actual accounting,
then reproduce row equality and metadata. A mutated payload with unchanged receipt
must fail; recomputing its receipt cannot hide unequal terrain or invalid coverage.
No arbitrary result constructor or supplied `complete=true` field grants acceptance.

This in-memory evidence model does not modify the frozen single-page attempt
inventory, PRELAUNCH, log scope or `verify_retained_attempt()`. Persistent multi-page
packaging still needs explicit compatibility review, exact page-index artifacts,
multi-request lifecycle log validation and a separately reviewed proof contract.
Historical REAL_PASS remains supported; historical full offline acceptance remains
AUDIT_BLOCKED with 13 missing canonical inputs. No history is regenerated.

P08 integration later consumes accepted facts only inside this region and after
independent source/supplemental-fact requirements. P05 remains supplied-candidate
optimization. Neither integration is implemented here.

## Controlled test matrix

All tests exercise the proposed public interface and real pagination/protocol code.

| Challenge | Required outcome |
| --- | --- |
| Equal regions of 1, 5, 6, 255, 256 tiles | Complete pair; exact rows and independent coverage |
| Partial final page, including 256th tile | Correct terminal cursor and row count in both sweeps |
| Empty region | Constructor rejects under existing Region contract |
| Change each of ten row fields independently, with otherwise valid rows | Reject drift; schema-invalid variants reject at protocol admission |
| Different valid dates/receipt IDs/bytes with equal rows | Accept; preserve distinct metadata |
| Date bracket inversion/regression | Reject temporal evidence inconsistency |
| Changed context fingerprint/geometry; wrong sweep identity | Reject context/sweep mismatch |
| Changed page ID/order/cursor, missing page in either sweep | Reject; no assembled pair |
| Duplicate/conflicting/overlapping/out-of-region tile | Reject through real page coverage validation |
| Abort or incomplete second sweep | Terminal rejection; diagnostics preserved |
| Sweep-local cap, aggregate cap, invalid budget type | Reject exact offending scope; no counter reset bypass |
| Accounting tampered in replay/result metadata | Derive actual totals; inconsistent claimed totals reject in replay comparison |
| Immutable rows/exchanges/context/result | Mutation impossible; metadata copies cannot alter authority |
| Request/response byte mutation or incorrect receipt digest | Replay rejects independently |
| Recomputed receipt around changed second-sweep terrain | Equality rejects |
| Attempts to admit forged completed datasets or resume rejected state | No admission path; no success |
| Existing pagination and WPO collector regressions | Unchanged behavior and semantics |

## Implementation sequence and gates

1. Add `terrain_sweeps.py` and `tests/test_terrain_sweeps.py` only, using TDD for
   context, identities and sequential completeness. Gate: 1/5/6 tile coverage.
2. Add full-row equality, terminal failures, per-sweep/combined actual accounting
   and immutable result. Gate: the entire positive/negative matrix above.
3. Independently replay retained exchanges and test byte digests/metadata. Gate:
   replay accepts valid pairs and rejects targeted mutations without mocked validators.
4. Run existing pagination, terrain collection, protocol, P08/P05 and offline
   evidence regressions, serial ordinary suite (real-native deselected), Ruff,
   format, scoped typecheck, import audit, diff check and historical integrity.
5. Independent Spec/Standards review before accepting the controlled slice.

Do not change existing modules merely to share hypothetical functionality. A shared
canonical helper is unnecessary because tuple comparison and existing dataset
metadata suffice. Document any demonstrated integration dependency before editing
the qualified collector or baseline files.

Future native work requires separate source/identity authority, session/time/frame/
getter/storage bounds, compatible immutable packaging, independent controlled
acceptance, explicit seal preparation and exact one-shot Model A authorization.
These deferred requirements do not block pure controlled equality implementation.

## Design reviews

Independent Spec Review: PASS, no blocking mismatch with the regional plan,
pagination or frozen evidence baseline. Native fingerprint attestation and future
session/storage/log proof integration remain deferred requirements.

Independent Standards Review: PASS, no blocking architecture finding. The review
confirmed private paginator ownership, full-row equality, terminal failure,
aggregate accounting and behavior-focused replay tests. Its accounting precision
note is incorporated above: operation counters are validated records, not native
measurements. These are design reviews, not executed two-sweep implementation tests.
