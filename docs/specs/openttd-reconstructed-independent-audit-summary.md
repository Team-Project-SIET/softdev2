# Reconstructed Independent Audit Summary

## Provenance and status

This is a conversation-derived archival summary, not the original audit matrix or
restored primary evidence. Source is the user-supplied 24-case summary in the task
"Recover the Audit Summary and Adjudicate Contract Freeze", together with the prior
independent auditor's final historical-root adjudication in this conversation.
All outcomes below are reported outcomes, not new mutation executions in this task.
No exact original payload, timestamp, fixture digest or absent raw field is inferred.

The reported final counts are 24 PASS, 0 DEFECT, 0 INCONCLUSIVE, 0 NOT_TESTED.
Case 14 was adjudicated separately after 23 cases had become PASS. The final run
carried those 23 cases forward; it did not freshly rerun every listed mutation.

## Conversation-preserved cases

| Case | Reported challenge | Reported result | Reported rejection boundary or positive outcome |
| --- | --- | --- | --- |
| 1 | Coordinated attempt identity | PASS | lineage mismatch |
| 2 | Invalid coordinated owner | PASS | lineage mismatch |
| 3 | Trust and operation allowance | PASS | lineage mismatch |
| 4 | Coordinated retry policy | PASS | lineage mismatch |
| 5 | Cross-attempt authorization | PASS | lineage mismatch |
| 6 | CONTROLLED-to-REAL separation | PASS | REAL authentication mismatch |
| 7 | Invocation claim digest | PASS | lineage mismatch |
| 8 | Ownership plus source inventory | PASS | immutable ownership mismatch |
| 9 | Protected path made disposable | PASS | immutable ownership mismatch |
| 10 | Invalid ownership classification | PASS | immutable ownership mismatch |
| 11 | Canonical identity substitution | PASS | sealed-index mismatch |
| 12 | Materialization relationship | PASS | materialization provenance mismatch |
| 13 | Retained object substitution | PASS | canonical-content mismatch |
| 14 | Historical root substitution | PASS | immutable historical commitment rejects unauthorized modification |
| 15 | Canonical symlink alias | PASS | canonical-content validation |
| 16 | Unexpected canonical artifact | PASS | exact canonical inventory |
| 17 | Snapshot byte mismatch | PASS | log-scope validation |
| 18 | Final-log digest mismatch | PASS | log-scope validation |
| 19 | Offset and length substitution | PASS | log-scope validation |
| 20 | Unrelated request log | PASS | log correlation |
| 21 | Duplicate lifecycle marker | PASS | log lifecycle validation |
| 22 | False cleanup result gate | PASS | result-gate consistency |
| 23 | Live endpoint contradicting closure | PASS | endpoint observation validation |
| 24 | Append-only shutdown log | PASS | valid offline acceptance |

## Final historical-root adjudication

The unauthorized root modification preserved the original immutable PRELAUNCH
commitment and was rejected twice as `Historical protection differs from immutable
seal` by `terrain_retention.verify_inputs()` through `verify_retained_attempt()`.
It did not reach `explicit_protection_base()`. This earlier authoritative rejection
protects the root-binding invariant; no contract requires a different order.

Thirteen separate production resolver/integrity checks passed under isolated
controlled authority: authorized absolute base, relative base, wrong provenance,
missing base, traversal, symlink alias, ambiguous lexical identity, missing metadata,
changed cwd, valid protected bytes, modified bytes, missing bytes and missing root.
Valid identities/bytes accepted and invalid cases rejected. These separately test
resolver and filesystem integrity, without bypassing the original immutable authority.

## Recovery search and known references

The original JSON bytes were not recovered. Searches covered current documentation,
retained verification report names/content, accessible temporary audit locations,
Codex sessions and archived sessions, and relevant local history. No claim is made
about inaccessible backups or storage outside those searched locations.

An accessible session record is:
`/home/fed/.codex/sessions/2026/10/09/rollout-2026-10-09T19-20-02-01a1209b-2b1a-7610-b6cf-e988683daf71.jsonl`.
It preserves audit messages and recorded script text. At search time, line 3375
reports 23 PASS/1 INCONCLUSIVE; line 3382 contains a command describing mutations
and provenance labels; line 3682 preserves the final adjudication message. Those
records are useful provenance, not the original matrix file. No session log was edited.

Former primary paths `/tmp/terrain-final-bounded-audit/matrix.json` and
`/tmp/historical-root-adjudication/matrix.json` are unavailable. Resolver/binding
result files and disposable controlled packages referred to in the reports are also
not represented here as retained. Their historical paths are locators, not live links.

Accessible supporting records remain the
[contract baseline](openttd-offline-evidence-baseline.md),
[repair history](../p08-15-3-offline-terrain-evidence-repair.md), production validators
and [regression tests](../../tests/test_terrain_offline_retention.py).
These support reproducible controlled verification, but do not recover old fixtures.

## Assurance limits and freeze adjudication

This summary preserves reported case identities, outcomes and stated boundaries.
It cannot independently establish exact changed bytes, fixture validity, original
manifest updates, original file hashes or full execution traces for every case.
It does not certify those unavailable details and is not a substitute for runtime
proof artifacts required by the production verifier. Existing regressions describe
repeatable checks; their availability does not mean they were rerun in this task.

No established project contract inspected requires the exact original audit JSON as
a mandatory freeze or retained-attempt artifact. `CONTEXT.md` requires evidence-based
claims and preserved proof evidence. `verify_attempt_inventory()` and
`verify_inputs()` define mandatory attempt/seal artifacts; neither includes this
audit matrix. The earlier baseline's archival blocker was a documentation-deliverable
gap, not an immutable runtime acceptance requirement. The supplied summary now
completes the named case record with an explicit primary-evidence limitation.

Controlled contract verification remains reported PASS. Original primary audit
preservation remains incomplete. The current controlled contract is ready for freeze
review on the documented summary, coverage references, existing regressions and final
independent adjudication; this task does not freeze it or rerun the complete audit.
No existing runtime gate or historical preservation rule is waived.

Historical native REAL_PASS remains SUPPORTED; historical complete offline acceptance
remains AUDIT_BLOCKED with 13 missing canonical inputs. The previously validated
historical baseline contains 1,868 artifacts and 1,847 protected paths. The later
1,876-file documentation snapshot is a broader current runtime-file comparison,
not a replacement historical baseline or evidence that missing inputs were restored.
